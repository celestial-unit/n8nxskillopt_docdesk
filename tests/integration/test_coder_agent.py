# Feature: n8n-multiagent-doc-pipeline, CoderAgent property tests
"""
tests/integration/test_coder_agent.py — Property test for CoderAgent.

Property 14: Account code format matches company pattern
"""
import json
import re
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings, strategies as st

# Company A: 6 alphanumeric chars [A-Z0-9]{6}
COMPANY_A_CODE_RE = re.compile(r"^[A-Z0-9]{6}$")
# Company B: format 6010-CC001 = [0-9]{4}-[A-Z]{2}[0-9]{3}
COMPANY_B_CODE_RE = re.compile(r"^\d{4}-[A-Z]{2}\d{3}$")


def _make_coder(account_code: str, cited_rule: str = "Règle de codification applicable"):
    """Create a CoderAgent with mocked LLM and no RAG."""
    from agents.coder_agent import CoderAgent
    mock_llm = MagicMock()
    mock_llm.call.return_value = json.dumps({
        "account_code": account_code,
        "cited_rule": cited_rule,
    })
    # No RAG engine
    return CoderAgent(llm_client=mock_llm, rag_engine=None)


# ── Property 14: Account code format matches company pattern ──────────────────
# Feature: n8n-multiagent-doc-pipeline, Property 14: Account code format
# Validates: Requirements 16.2, 16.3

@settings(max_examples=100)
@given(
    code=st.text(
        alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        min_size=6, max_size=6,
    ),
)
def test_company_a_account_code_format(code):
    """
    Coder for company_a must return account codes matching [A-Z0-9]{6}.
    """
    agent = _make_coder(code)
    result = agent.run(
        {"extracted": {"supplier": "STEG", "doc_type": "invoice"}, "doc_type": "invoice"},
        "company_a",
        rag_enabled=False,
    )

    returned_code = result["account_code"]
    assert COMPANY_A_CODE_RE.match(returned_code), (
        f"company_a code '{returned_code}' does not match [A-Z0-9]{{6}}"
    )


@settings(max_examples=100)
@given(
    digits=st.text(alphabet="0123456789", min_size=4, max_size=4),
    letters=st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=2, max_size=2),
    suffix=st.text(alphabet="0123456789", min_size=3, max_size=3),
)
def test_company_b_account_code_format(digits, letters, suffix):
    """
    Coder for company_b must return account codes matching [0-9]{4}-[A-Z]{2}[0-9]{3}.
    """
    code = f"{digits}-{letters}{suffix}"
    agent = _make_coder(code)
    result = agent.run(
        {"extracted": {"supplier": "OOREDOO", "doc_type": "invoice"}, "doc_type": "invoice"},
        "company_b",
        rag_enabled=False,
    )

    returned_code = result["account_code"]
    assert COMPANY_B_CODE_RE.match(returned_code), (
        f"company_b code '{returned_code}' does not match \\d{{4}}-[A-Z]{{2}}\\d{{3}}"
    )


@settings(max_examples=50)
@given(
    doc_type=st.sampled_from(["invoice", "receipt", "purchase_order"]),
)
def test_coder_always_returns_required_fields(doc_type):
    """CoderAgent output must always contain account_code, cited_rule, chunks, skill_version."""
    agent = _make_coder("606100")
    result = agent.run(
        {"extracted": {"supplier": "STEG"}, "doc_type": doc_type},
        "company_a",
        rag_enabled=False,
    )

    assert "account_code" in result
    assert "cited_rule" in result
    assert "chunks" in result
    assert "skill_version" in result
    assert isinstance(result["chunks"], list)


@settings(max_examples=50)
@given(
    company=st.sampled_from(["company_a", "company_b"]),
)
def test_coder_cited_rule_is_string(company):
    """cited_rule must always be a string (possibly empty)."""
    agent = _make_coder("606100", cited_rule="Les fournitures de bureau utilisent le compte 606100")
    result = agent.run(
        {"extracted": {"supplier": "Monoprix"}, "doc_type": "invoice"},
        company,
        rag_enabled=False,
    )
    assert isinstance(result["cited_rule"], str)
