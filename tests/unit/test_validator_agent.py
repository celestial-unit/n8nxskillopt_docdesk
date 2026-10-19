# Feature: n8n-multiagent-doc-pipeline, ValidatorAgent property tests
"""
tests/unit/test_validator_agent.py — Property test for ValidatorAgent.

Property 15: Validator detects arithmetic mismatches
"""
from unittest.mock import MagicMock
from decimal import Decimal

import pytest
from hypothesis import given, settings, strategies as st


def _make_validator(explanation: str = "Erreur arithmétique détectée."):
    """Create a ValidatorAgent with a mocked LLM."""
    from agents.validator_agent import ValidatorAgent
    mock_llm = MagicMock()
    mock_llm.call.return_value = explanation
    return ValidatorAgent(llm_client=mock_llm, trace_store=None)


# ── Property 15: Validator detects arithmetic mismatches ──────────────────────
# Feature: n8n-multiagent-doc-pipeline, Property 15: Arithmetic detection
# Validates: Requirements 4.4, 16.6

@settings(max_examples=100)
@given(
    htva=st.floats(min_value=0.0, max_value=100000.0, allow_nan=False, allow_infinity=False),
    tva=st.floats(min_value=0.0, max_value=20000.0, allow_nan=False, allow_infinity=False),
    ttc_offset=st.floats(
        min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False
    ).map(lambda x: round(x, 3)),
    nif=st.text(min_size=5, max_size=20),
)
def test_validator_detects_arithmetic_mismatch(htva, tva, ttc_offset, nif):
    """
    When abs(htva + tva - ttc) > 0.001, Validator must set needs_review=True
    and include 'arithmetic_mismatch' in errors.
    """
    ttc = round(htva + tva + ttc_offset, 3)  # deliberately wrong (offset > 0.001)
    extracted = {
        "htva": htva,
        "tva": tva,
        "ttc": ttc,
        "matricule_fiscal": nif,
    }

    agent = _make_validator()
    result = agent.run(
        {"extracted": extracted, "doc_id": "TEST-ARITH-001"},
        "company_a",
    )

    assert result["needs_review"] is True, (
        f"Expected needs_review=True for htva={htva} tva={tva} ttc={ttc}"
    )
    assert "arithmetic_mismatch" in result["errors"], (
        f"Expected 'arithmetic_mismatch' in errors, got {result['errors']}"
    )


@settings(max_examples=100)
@given(
    htva=st.floats(min_value=0.0, max_value=100000.0, allow_nan=False, allow_infinity=False),
    tva=st.floats(min_value=0.0, max_value=20000.0, allow_nan=False, allow_infinity=False),
    nif=st.text(min_size=5, max_size=20),
)
def test_validator_passes_correct_arithmetic(htva, tva, nif):
    """
    When ttc == htva + tva (within tolerance), no arithmetic_mismatch should be flagged.
    """
    ttc = round(htva + tva, 3)
    extracted = {
        "htva": htva,
        "tva": tva,
        "ttc": ttc,
        "matricule_fiscal": nif,
    }

    agent = _make_validator()
    result = agent.run(
        {"extracted": extracted, "doc_id": "TEST-CORRECT-001"},
        "company_a",
    )

    assert "arithmetic_mismatch" not in result["errors"], (
        f"Unexpected arithmetic_mismatch for htva={htva} tva={tva} ttc={ttc}"
    )


@settings(max_examples=50)
@given(nif=st.text(min_size=5, max_size=20))
def test_validator_flags_missing_matricule(nif):
    """
    When matricule_fiscal is absent or empty, validator should flag it.
    """
    extracted = {
        "htva": 100.0,
        "tva": 19.0,
        "ttc": 119.0,
        "matricule_fiscal": "",  # explicitly empty
    }

    agent = _make_validator()
    result = agent.run(
        {"extracted": extracted, "doc_id": "TEST-NIF-001"},
        "company_a",
    )

    assert "missing_nif" in result["errors"] or "missing_matricule" in result["errors"], (
        f"Expected 'missing_nif' or 'missing_matricule' in errors, got {result['errors']}"
    )
    assert result["needs_review"] is True
