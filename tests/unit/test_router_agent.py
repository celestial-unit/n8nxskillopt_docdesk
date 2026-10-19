# Feature: n8n-multiagent-doc-pipeline, RouterAgent property tests
"""
tests/unit/test_router_agent.py — Property test for RouterAgent.

Property 7: Router output completeness and validity
"""
from unittest.mock import MagicMock, patch
import json

import pytest
from hypothesis import given, settings, strategies as st

VALID_DOC_TYPES = ["invoice", "receipt", "purchase_order"]
VALID_MODALITIES = ["text", "photo"]


def _make_router(llm_response: str):
    """Create a RouterAgent with a mocked LLM returning the given JSON string."""
    from agents.router_agent import RouterAgent
    mock_llm = MagicMock()
    mock_llm.call.return_value = llm_response
    return RouterAgent(llm_client=mock_llm)


# ── Property 7: Router output completeness and validity ───────────────────────
# Feature: n8n-multiagent-doc-pipeline, Property 7: Router output
# Validates: Requirements 4.1, 9.3

@settings(max_examples=100)
@given(
    doc_type=st.sampled_from(VALID_DOC_TYPES),
    modality=st.sampled_from(VALID_MODALITIES),
    extra_text=st.text(min_size=0, max_size=50),
)
def test_router_output_completeness_and_validity(doc_type, modality, extra_text):
    """
    RouterAgent must return a dict with:
    - doc_type in ["invoice", "receipt", "purchase_order"]
    - modality in ["text", "photo"]
    regardless of the (valid) LLM response.
    """
    llm_json = json.dumps({"doc_type": doc_type, "modality": modality})
    agent = _make_router(llm_json)

    result = agent.run(
        {"file_path": "test.pdf", "text": extra_text or "Facture STEG"},
        "company_a",
    )

    assert "doc_type" in result, "Result must contain 'doc_type'"
    assert "modality" in result, "Result must contain 'modality'"
    assert "skill_version" in result, "Result must contain 'skill_version'"
    assert result["doc_type"] in VALID_DOC_TYPES, (
        f"doc_type '{result['doc_type']}' not in {VALID_DOC_TYPES}"
    )
    assert result["modality"] in VALID_MODALITIES, (
        f"modality '{result['modality']}' not in {VALID_MODALITIES}"
    )


@settings(max_examples=50)
@given(
    bad_json=st.text(min_size=0, max_size=100).filter(lambda s: not s.strip().startswith("{")),
)
def test_router_falls_back_on_invalid_json(bad_json):
    """
    When LLM returns non-JSON, RouterAgent should either raise AgentParseError
    or fall back to valid defaults — it must not return invalid values.
    """
    from agents.exceptions import AgentParseError

    agent = _make_router(bad_json)

    try:
        result = agent.run({"file_path": "test.pdf", "text": "Document"}, "company_a")
        # If it doesn't raise, result must still be valid
        assert result["doc_type"] in VALID_DOC_TYPES
        assert result["modality"] in VALID_MODALITIES
    except AgentParseError:
        pass  # Acceptable — agent correctly detected unparseable response
