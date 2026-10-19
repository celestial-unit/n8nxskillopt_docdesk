"""
skillopt_envs/docdesk/extractor_rollout.py — Rollout for the docdesk extractor task.

For each item:
1. Call the extractor LLM with the skill + document text
2. Score: normalized exact match (NEM) across all gold_fields keys
          hard = 1.0 if NEM >= 0.75, else 0.0
          soft = NEM (continuous)
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Score only fields that the production Extractor response contract supports.
# The benchmark additionally labels `reference_unique`, which is not in
# ExtractResponse; line_descriptions are represented in production as lines[].
SUPPORTED_GOLD_FIELDS = {
    "supplier", "date", "number", "line_descriptions", "htva", "tva",
    "ttc", "timbre_fiscal", "matricule_fiscal", "currency",
}

# Add project root to path
PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _normalize(s) -> str:
    """Normalize text and numeric strings for exact but format-robust scoring."""
    if s is None:
        return ""
    s = str(s).strip().lower()
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"[\s\u00a0\u202f]+", "", s)
    s = s.replace(",", ".")
    try:
        # Treat 0.600, 0.6, and the corresponding numeric value as equal.
        return format(Decimal(s).normalize(), "f")
    except InvalidOperation:
        pass
    return s


def _nem_score(predicted: dict, gold: dict) -> float:
    """Normalized exact match across all gold keys."""
    if not gold:
        return 1.0
    scores = []
    for key in gold:
        g = _normalize(gold[key])
        value = predicted.get(key, "")
        if key == "line_descriptions" and not value:
            lines = predicted.get("lines", [])
            value = [line.get("description", "") for line in lines if isinstance(line, dict)]
        p = _normalize(value)
        scores.append(1.0 if p == g else 0.0)
    return sum(scores) / len(scores)


def _call_extractor(
    skill_text: str,
    item: dict,
    model_cfg: dict,
    *,
    recovery: bool = False,
) -> tuple[str, str, dict]:
    """Call the extractor, with one concise JSON retry after bad output."""
    from skillopt.model import chat_target_messages

    text = item.get("text", "")
    doc_type = item.get("doc_type", "invoice")

    if recovery:
        system_prompt = (
            f"{skill_text}\n\n"
            "MODE DE RÉCUPÉRATION: ne produis aucun raisonnement. Retourne un objet JSON compact, "
            "sans markdown ni texte autour. Si une valeur est absente, utilise une chaîne vide ou null."
        )
        user_msg = f"Document ({doc_type}). Extrais les champs et réponds uniquement en JSON.\n\n{text[:4000]}"
    else:
        system_prompt = skill_text
        user_msg = (
            f"Type de document : {doc_type}\n\n"
            f"Extrais tous les champs structurés du document suivant :\n\n{text[:4000]}"
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    model_cfg = dict(model_cfg)
    model_cfg.setdefault("reasoning_effort", "none")
    if recovery:
        model_cfg["max_completion_tokens"] = min(
            int(model_cfg.get("max_completion_tokens", 4096)) * 2, 8192
        )
    last_error = None
    for attempt in range(2):
        try:
            response = chat_target_messages(messages, **model_cfg)
            break
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(2)
    else:
        raise RuntimeError(f"Extractor call failed after one recovery retry: {last_error}") from last_error
    # SkillOpt 0.2.0 returns (content, usage_metadata); parse only content.
    content = response[0] if isinstance(response, tuple) else response
    usage = response[1] if isinstance(response, tuple) and isinstance(response[1], dict) else {}
    return str(content), str(content), usage


def _extract_json(text: str) -> dict | None:
    """Extract JSON from LLM response, stripping markdown fences."""
    clean = text.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        clean = "\n".join(lines[1:-1]) if len(lines) > 2 else "\n".join(lines[1:])
    m = re.search(r"\{.*\}", clean, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def run_batch(
    items: list[dict],
    skill_text: str,
    out_dir: str,
    model_cfg: dict,
    workers: int = 1,
) -> list[dict]:
    """
    Run extraction rollouts for a batch of items. Returns list of result dicts.
    Saves each prediction to out_dir/predictions/<id>/conversation.json.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import os

    results = []

    def process_one(item: dict) -> dict:
        doc_id = item["id"]
        all_gold_fields = item.get("gold_fields", {})
        gold_fields = {key: value for key, value in all_gold_fields.items()
                       if key in SUPPORTED_GOLD_FIELDS}
        excluded_gold_fields = sorted(set(all_gold_fields) - SUPPORTED_GOLD_FIELDS)
        company_id = item.get("company_id", "company_a")
        recovery_attempted = False

        try:
            raw, content, usage = _call_extractor(skill_text, item, model_cfg)
            parsed = _extract_json(content)
            if parsed is None:
                recovery_attempted = True
                retry_raw, retry_content, retry_usage = _call_extractor(
                    skill_text, item, model_cfg, recovery=True
                )
                raw, content, parsed = retry_raw, retry_content, _extract_json(retry_content)
                usage = {
                    key: int((usage or {}).get(key, 0) or 0) + int((retry_usage or {}).get(key, 0) or 0)
                    for key in {*(usage or {}).keys(), *(retry_usage or {}).keys()}
                }

            if parsed is None:
                nem = 0.0
                parse_ok = False
            else:
                nem = _nem_score(parsed, gold_fields)
                parse_ok = True

            # hard = 1 if NEM >= 0.75, soft = NEM
            hard = 1.0 if nem >= 0.75 else 0.0
            soft = nem

            result = {
                "id":           doc_id,
                "company_id":   company_id,
                "doc_type":     item.get("doc_type", ""),
                "nem":          nem,
                "hard":         hard,
                "soft":         soft,
                "fields_scored": sorted(gold_fields),
                "excluded_gold_fields": excluded_gold_fields,
                "parse_ok":     parse_ok,
                "recovery_attempted": recovery_attempted,
                "raw_response": content[:500],
                "usage": usage,
            }

            # Save conversation.json for the reflect step
            conv_dir = os.path.join(out_dir, "predictions", doc_id)
            os.makedirs(conv_dir, exist_ok=True)
            with open(os.path.join(conv_dir, "conversation.json"), "w") as f:
                json.dump({
                    "id":           doc_id,
                    "input":        item,
                    "gold_fields":  gold_fields,
                    "excluded_gold_fields": excluded_gold_fields,
                    "predicted":    parsed or {},
                    "nem":          nem,
                    "hard":         hard,
                    "soft":         soft,
                    "recovery_attempted": recovery_attempted,
                    "raw_response": content,
                    "usage": usage,
                }, f, ensure_ascii=False, indent=2)

            return result

        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            try:
                conv_dir = os.path.join(out_dir, "predictions", doc_id)
                os.makedirs(conv_dir, exist_ok=True)
                with open(os.path.join(conv_dir, "conversation.json"), "w", encoding="utf-8") as f:
                    json.dump({"id": doc_id, "input": item, "gold_fields": gold_fields,
                               "excluded_gold_fields": excluded_gold_fields,
                               "error": error}, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            return {
                "id": doc_id, "company_id": company_id,
                "doc_type": item.get("doc_type", ""),
                "nem": 0.0, "hard": 0.0, "soft": 0.0, "parse_ok": False,
                "error": error[:400],
                "fields_scored": sorted(gold_fields),
                "excluded_gold_fields": excluded_gold_fields,
            }

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(process_one, item): item for item in items}
            for fut in as_completed(futures):
                results.append(fut.result())
    else:
        for item in items:
            results.append(process_one(item))

    return results
