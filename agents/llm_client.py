"""
agents/llm_client.py — Unified LLM client for Azure AI Foundry / OpenAI-compatible endpoints.

Design:
  - Temperature always 0.
  - reasoning_effort per role (AGENT_REASONING_EFFORT, VISION_REASONING_EFFORT,
    OPTIMIZER_REASONING_EFFORT). Accepted values: none / low / medium / high / (empty).
    "none" disables reasoning on Foundry/Kimi. Empty = model default.
  - DEMO_CACHE=1 caches to .cache/<sha256>.pkl, keyed on role+system+user+image.
  - reasoning_content is stripped from the returned string; token count is logged.
"""

import hashlib
import logging
import os
import pickle
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI, AzureOpenAI

logger = logging.getLogger(__name__)

# ── Env var names ─────────────────────────────────────────────────────────────

ROLE_DEPLOYMENT_MAP = {
    "agent":     "AGENT_DEPLOYMENT",
    "vision":    "VISION_DEPLOYMENT",
    "optimizer": "OPTIMIZER_DEPLOYMENT",
}

ROLE_REASONING_MAP = {
    "agent":     "AGENT_REASONING_EFFORT",
    "vision":    "VISION_REASONING_EFFORT",
    "optimizer": "OPTIMIZER_REASONING_EFFORT",
}

VALID_REASONING_EFFORTS = {"none", "low", "medium", "high", ""}


class MissingDeploymentError(Exception):
    """Raised when a required deployment env var is not set."""
    pass


class LLMClient:
    """
    Unified LLM client.

    Roles: "agent", "vision", "optimizer"

    .env variables consumed:
        OPENAI_BASE_URL / OPENAI_API_KEY        — OpenAI-compatible endpoint
        AZURE_ENDPOINT / AZURE_API_KEY          — Azure OpenAI (if OPENAI_BASE_URL absent)
        AZURE_API_VERSION
        AGENT_DEPLOYMENT / VISION_DEPLOYMENT / OPTIMIZER_DEPLOYMENT
        AGENT_REASONING_EFFORT / VISION_REASONING_EFFORT / OPTIMIZER_REASONING_EFFORT
        DEMO_CACHE=1
    """

    def __init__(self) -> None:
        load_dotenv(override=False)
        self._demo_cache = os.environ.get("DEMO_CACHE", "0") == "1"
        self._cache_dir  = Path(".cache")

        azure_endpoint = os.environ.get("AZURE_ENDPOINT", "").strip()
        if azure_endpoint:
            self._client = AzureOpenAI(
                azure_endpoint=azure_endpoint,
                api_key=os.environ.get("AZURE_API_KEY", ""),
                api_version=os.environ.get("AZURE_API_VERSION", "2024-08-01-preview"),
            )
            self._mode = "azure"
        else:
            base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
            api_key  = os.environ.get("OPENAI_API_KEY", "").strip()
            if not base_url:
                raise MissingDeploymentError(
                    "Neither AZURE_ENDPOINT nor OPENAI_BASE_URL is set in .env"
                )
            self._client = OpenAI(base_url=base_url, api_key=api_key)
            self._mode = "openai"

    # ── Public API ─────────────────────────────────────────────────────────────

    def call(
        self,
        role: str,
        system_prompt: str,
        user_message: str,
        image_b64: Optional[str] = None,
    ) -> str:
        """
        Make one LLM call and return the answer text (reasoning stripped).

        Raises MissingDeploymentError if the deployment env var is absent.
        Logs reasoning token count if reasoning_content is present.
        """
        dep_var = ROLE_DEPLOYMENT_MAP.get(role)
        if dep_var is None:
            raise MissingDeploymentError(
                f"Unknown role '{role}'. Valid: {list(ROLE_DEPLOYMENT_MAP)}"
            )
        deployment = os.environ.get(dep_var, "").strip()
        if not deployment:
            raise MissingDeploymentError(
                f"Env var '{dep_var}' is not set. Add it to .env."
            )

        reasoning_effort = os.environ.get(ROLE_REASONING_MAP[role], "").strip().lower()
        if reasoning_effort not in VALID_REASONING_EFFORTS:
            raise ValueError(
                f"{ROLE_REASONING_MAP[role]}={reasoning_effort!r} is invalid. "
                f"Use one of {VALID_REASONING_EFFORTS}."
            )

        cache_key = _cache_key(role, system_prompt, user_message, image_b64 or "", reasoning_effort)

        if self._demo_cache:
            cached = _get_cached(cache_key, self._cache_dir)
            if cached is not None:
                logger.debug("Cache hit for role=%s", role)
                return cached

        t0 = time.monotonic()
        text, r_tokens = self._call_llm(
            deployment=deployment,
            system_prompt=system_prompt,
            user_message=user_message,
            image_b64=image_b64,
            reasoning_effort=reasoning_effort or None,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        if r_tokens:
            logger.info("role=%s latency=%dms reasoning_tokens≈%d", role, latency_ms, r_tokens)
        else:
            logger.debug("role=%s latency=%dms", role, latency_ms)

        if self._demo_cache:
            _set_cached(cache_key, text, self._cache_dir)

        return text

    # ── Internal ───────────────────────────────────────────────────────────────

    def _call_llm(
        self,
        deployment: str,
        system_prompt: str,
        user_message: str,
        image_b64: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
    ) -> tuple[str, int]:
        """
        Call the LLM. Returns (answer_text, reasoning_token_count).
        reasoning_content is stripped from the answer.
        """
        messages: list = [{"role": "system", "content": system_prompt}]

        if image_b64:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user_message},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{image_b64}",
                    }},
                ],
            })
        else:
            messages.append({"role": "user", "content": user_message})

        kwargs: dict = dict(
            model=deployment,
            messages=messages,
            temperature=0,
            max_tokens=600,  # Compact JSON output — enough for all agent schemas
        )
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort

        completion = self._client.chat.completions.create(**kwargs)
        msg = completion.choices[0].message

        # Strip reasoning_content (Kimi, o1, etc.) — return only the answer
        content   = msg.content or ""
        reasoning = getattr(msg, "reasoning_content", None) or ""
        r_tokens  = len(reasoning.split()) if reasoning else 0

        # If content is empty but reasoning contains the answer (shouldn't happen
        # with reasoning_effort=none, but guard anyway)
        if not content.strip() and reasoning:
            logger.warning("content empty, falling back to reasoning_content")
            content = reasoning

        return content, r_tokens


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_key(role: str, system: str, user: str, image_b64: str = "", reasoning_effort: str = "") -> str:
    raw = "\x00".join([role, system, user, image_b64, reasoning_effort])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_path(key: str, cache_dir: Path) -> Path:
    return cache_dir / f"{key}.pkl"


def _get_cached(key: str, cache_dir: Path) -> Optional[str]:
    path = _cache_path(key, cache_dir)
    if path.exists():
        with open(path, "rb") as f:
            return pickle.load(f)
    return None


def _set_cached(key: str, value: str, cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    with open(_cache_path(key, cache_dir), "wb") as f:
        pickle.dump(value, f)
