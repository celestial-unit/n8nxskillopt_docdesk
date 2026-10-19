# Feature: n8n-multiagent-doc-pipeline, ExtractorAgent property tests
"""
tests/integration/test_extractor_agent.py — Property test for ExtractorAgent.

Property 13: Extractor output is a key superset of gold fields
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings, strategies as st

# Required keys from the design document
REQUIRED_EXTRACTOR_KEYS = {
    "supplier", "date", "number", "lines",
    "htva", "tva", "ttc", "timbre_fiscal",
    "matricule_fiscal", "skill_version",
}


def _make_extractor(response_dict: dict):
    """Create an ExtractorAgent with a mocked LLM returning the given dict as JSON."""
    from agents.extractor_agent import ExtractorAgent
    mock_llm = MagicMock()
    mock_llm.call.return_value = json.dumps(response_dict)
    return ExtractorAgent(llm_client=mock_llm)


# ── Property 13: Extractor output is a key superset of gold fields ────────────
# Feature: n8n-multiagent-doc-pipeline, Property 13: Key superset
# Validates: Requirements 4.2, 16.1

@settings(max_examples=100)
@given(
    supplier=st.text(min_size=1, max_size=50),
    date=st.text(min_size=10, max_size=10).filter(lambda s: True),
    number=st.text(min_size=1, max_size=20),
    amount=st.floats(min_value=0.0, max_value=999999.0, allow_nan=False, allow_infinity=False),
)
def test_extractor_output_is_key_superset_of_required_fields(supplier, date, number, amount):
    """
    Extractor output dict keys must be a superset of all required gold field keys.
    """
    fake_response = {
        "supplier": supplier,
        "date": date,
        "number": number,
        "lines": [],
        "htva": amount,
        "tva": amount * 0.19,
        "ttc": amount * 1.19,
        "timbre_fiscal": 0.6,
        "matricule_fiscal": "1234567A",
    }

    agent = _make_extractor(fake_response)
    result = agent.run(
        {"text": f"Facture {number} de {supplier}", "doc_type": "invoice"},
        "company_a",
    )

    result_keys = set(result.keys())
    missing = REQUIRED_EXTRACTOR_KEYS - result_keys
    assert not missing, (
        f"Extractor output missing required keys: {missing}"
    )


def test_extractor_output_superset_of_gold_fields():
    """
    For actual gold documents, extractor output keys must ⊇ gold fields keys.
    """
    # Load a sample gold JSON if available
    gold_dir = Path("data/company_a/documents")
    if not gold_dir.exists():
        pytest.skip("Gold documents not available in test environment")

    gold_files = list(gold_dir.glob("*_gold.json"))[:5]
    if not gold_files:
        pytest.skip("No gold JSON files found")

    from agents.extractor_agent import ExtractorAgent

    for gold_path in gold_files:
        gold = json.loads(gold_path.read_text())
        gold_fields = gold.get("fields", {})
        if not gold_fields:
            continue

        # Mock the LLM to return the gold fields directly
        mock_llm = MagicMock()
        mock_llm.call.return_value = json.dumps(gold_fields)
        agent = ExtractorAgent(llm_client=mock_llm)

        result = agent.run(
            {"text": "Document de test", "doc_type": gold.get("doc_type", "invoice")},
            gold.get("company_id", "company_a"),
        )

        result_keys = set(result.keys())
        gold_keys = set(gold_fields.keys())
        missing = gold_keys - result_keys
        assert not missing, (
            f"For {gold_path.name}: extractor output missing gold keys: {missing}"
        )


@settings(max_examples=50)
@given(
    doc_type=st.sampled_from(["invoice", "receipt", "purchase_order"]),
    company=st.sampled_from(["company_a", "company_b"]),
)
def test_extractor_always_returns_skill_version(doc_type, company):
    """skill_version must always be present in extractor output."""
    fake_response = {
        "supplier": "STEG",
        "date": "01/01/2024",
        "number": "F-001",
        "lines": [],
        "htva": 100.0,
        "tva": 19.0,
        "ttc": 119.0,
        "timbre_fiscal": 0.6,
        "matricule_fiscal": "1234567A",
    }

    agent = _make_extractor(fake_response)
    result = agent.run({"text": "Facture test", "doc_type": doc_type}, company)

    assert "skill_version" in result, "skill_version must be in extractor output"
    assert result["skill_version"], "skill_version must not be empty"
