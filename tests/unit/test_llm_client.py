# Feature: n8n-multiagent-doc-pipeline, LLMClient property tests
"""
tests/unit/test_llm_client.py — Property tests for LLMClient.

Property 1: Temperature invariant — every outgoing call has temperature=0
Property 2: Cache round-trip with zero network calls
Property 3: Missing deployment raises named exception
"""
import os
import pickle
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
from hypothesis import given, settings, strategies as st

# ── Helpers ───────────────────────────────────────────────────────────────────

VALID_ROLES = ["agent", "vision", "optimizer"]


def _make_env(role: str, cache: bool = False, base_url: str = "http://localhost:11434/v1") -> dict:
    """Return env vars dict sufficient to instantiate LLMClient."""
    dep_map = {
        "agent":     "AGENT_DEPLOYMENT",
        "vision":    "VISION_DEPLOYMENT",
        "optimizer": "OPTIMIZER_DEPLOYMENT",
    }
    env = {
        "OPENAI_BASE_URL": base_url,
        "OPENAI_API_KEY":  "test-key",
        dep_map[role]:     "test-model",
        "DEMO_CACHE":      "1" if cache else "0",
    }
    return env


# ── Property 1: Temperature invariant ────────────────────────────────────────
# Feature: n8n-multiagent-doc-pipeline, Property 1: Temperature invariant
# Validates: Requirements 1.3

@settings(max_examples=50, deadline=None)
@given(
    role=st.sampled_from(VALID_ROLES),
    system=st.text(min_size=1, max_size=200),
    user=st.text(min_size=1, max_size=200),
)
def test_temperature_invariant(role, system, user):
    """Every LLM call must use temperature=0 regardless of inputs."""
    captured_kwargs = []

    def mock_create(**kwargs):
        captured_kwargs.append(kwargs)
        msg = MagicMock()
        msg.content = '{"doc_type": "invoice", "modality": "text"}'
        msg.reasoning_content = None
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    with patch.dict(os.environ, _make_env(role)):
        from importlib import reload
        import agents.llm_client as llm_mod
        reload(llm_mod)
        client = llm_mod.LLMClient()

        with patch.object(client._client.chat.completions, "create", side_effect=mock_create):
            client.call(role=role, system_prompt=system, user_message=user)

    assert len(captured_kwargs) == 1
    assert captured_kwargs[0]["temperature"] == 0, (
        f"Expected temperature=0, got {captured_kwargs[0].get('temperature')}"
    )


# ── Property 2: Cache round-trip with zero network calls ──────────────────────
# Feature: n8n-multiagent-doc-pipeline, Property 2: Cache round-trip
# Validates: Requirements 1.4, 1.6, 16.8

@settings(max_examples=100)
@given(
    role=st.sampled_from(VALID_ROLES),
    system=st.text(min_size=1, max_size=100),
    user=st.text(min_size=1, max_size=100),
)
def test_cache_roundtrip_zero_network_calls(role, system, user):
    """Second call with same prompt returns cached result with zero network calls."""
    call_count = [0]
    fake_response = "cached-response-xyz"

    def mock_create(**kwargs):
        call_count[0] += 1
        msg = MagicMock()
        msg.content = fake_response
        msg.reasoning_content = None
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir)
        env = _make_env(role, cache=True)

        with patch.dict(os.environ, env):
            from importlib import reload
            import agents.llm_client as llm_mod
            reload(llm_mod)
            client = llm_mod.LLMClient()
            client._cache_dir = cache_dir  # redirect cache to temp dir

            with patch.object(client._client.chat.completions, "create", side_effect=mock_create):
                result1 = client.call(role=role, system_prompt=system, user_message=user)
                result2 = client.call(role=role, system_prompt=system, user_message=user)

    # Same response both times
    assert result1 == result2 == fake_response
    # Network was only called once (second call used cache)
    assert call_count[0] == 1, f"Expected 1 network call, got {call_count[0]}"


# ── Property 3: Missing deployment raises named exception ──────────────────────
# Feature: n8n-multiagent-doc-pipeline, Property 3: Missing deployment
# Validates: Requirements 1.5

@settings(max_examples=50, deadline=None)
@given(role=st.sampled_from(VALID_ROLES))
def test_missing_deployment_raises_named_error(role):
    """MissingDeploymentError is raised and message names the missing env var."""
    dep_map = {
        "agent":     "AGENT_DEPLOYMENT",
        "vision":    "VISION_DEPLOYMENT",
        "optimizer": "OPTIMIZER_DEPLOYMENT",
    }
    expected_var = dep_map[role]

    # Env without the deployment var for this role
    env = {
        "OPENAI_BASE_URL": "http://localhost:11434/v1",
        "OPENAI_API_KEY":  "test-key",
        "DEMO_CACHE":      "0",
    }
    # Explicitly remove the deployment var
    env_without_dep = {k: v for k, v in env.items() if k != expected_var}

    # Patch os.environ to only have our keys (remove the deployment var)
    clean_env = {k: v for k, v in os.environ.items() if k not in dep_map.values()}
    clean_env.update(env_without_dep)
    # Remove the specific role's deployment var
    clean_env.pop(expected_var, None)

    # Minimal clean env — only what's needed to init the client, minus the deployment var
    clean_env = {
        "OPENAI_BASE_URL": "http://localhost:11434/v1",
        "OPENAI_API_KEY":  "test-key",
        "DEMO_CACHE":      "0",
    }
    # Do NOT set the deployment var for this role

    with patch.dict(os.environ, clean_env, clear=True):
        from importlib import reload
        import agents.llm_client as llm_mod
        reload(llm_mod)
        client = llm_mod.LLMClient()

        with pytest.raises(llm_mod.MissingDeploymentError) as exc_info:
            client.call(role=role, system_prompt="test", user_message="test")

    error_msg = str(exc_info.value)
    assert expected_var in error_msg, (
        f"Expected error message to mention '{expected_var}', got: {error_msg}"
    )
