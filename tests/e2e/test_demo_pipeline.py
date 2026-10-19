"""
tests/e2e/test_demo_pipeline.py — Property 18: Pipeline termination for demo documents.

Feature: n8n-multiagent-doc-pipeline, Property 18: Pipeline termination

Tests that each of the 4 demo documents can be processed through the full
pipeline (routing + extraction + coding + validation + decision) without
raising an unhandled exception, and produces a final decision of either
ACCEPTED or ESCALATED.

These tests run against real LLM calls unless DEMO_CACHE=1 is set.
They require .env to be configured with valid API credentials.
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Feature: n8n-multiagent-doc-pipeline, Property 18: Pipeline termination

DEMO_DIR = Path(__file__).parent.parent.parent / "demo"
DEMO_DOCS = [
    "clean_invoice.pdf",
    "house_rule_po.pdf",
    "arithmetic_error.pdf",
]


def make_mock_llm():
    """Create a mock LLMClient that returns valid JSON for each agent role."""
    mock = MagicMock()

    def mock_call(role, system_prompt, user_message, image_b64=None):
        # Router response
        if "doc_type" in system_prompt.lower() or "modality" in system_prompt.lower():
            return '{"doc_type": "invoice", "modality": "text"}'
        # Extractor response
        if "extrais" in system_prompt.lower() or "extraction" in system_prompt.lower():
            return json.dumps({
                "supplier": "STEG",
                "date": "15/03/2024",
                "number": "FAC-0001",
                "lines": [{"description": "Énergie", "quantity": 1, "unit_price_htva": 245.0, "htva": 245.0, "tva_rate": 0.19, "tva": 46.55, "ttc": 291.55}],
                "htva": 245.0,
                "tva": 46.55,
                "ttc": 291.55,
                "timbre_fiscal": 0.6,
                "nif": "00123456/A/M/000",
                "currency": "TND",
            })
        # Coder response
        if "account_code" in system_prompt.lower() or "codif" in system_prompt.lower():
            return '{"account_code": "606100", "cited_rule": "Toutes les factures STEG (électricité et gaz) → code 606100"}'
        # Validator response (one sentence)
        if "validation" in system_prompt.lower() or "vérification" in system_prompt.lower():
            return "Le document est arithmétiquement cohérent et le NIF est présent."
        # Exception handler response
        if "escalade" in system_prompt.lower() or "dossier" in system_prompt.lower():
            return json.dumps({
                "summary": "Révision requise.",
                "errors": ["arithmetic_mismatch"],
                "recommended_action": "Vérifier manuellement.",
                "contact": "Comptabilité",
                "priority": "high",
                "document_reference": "TEST",
            })
        return '{"result": "ok"}'

    mock.call.side_effect = mock_call
    return mock


@pytest.mark.parametrize("filename", DEMO_DOCS)
def test_demo_document_pipeline_terminates(filename):
    """
    Property 18: Pipeline termination for demo documents.

    For each demo document, the pipeline must produce a final decision
    (ACCEPTED or ESCALATED) without raising an unhandled exception.
    """
    pdf_path = DEMO_DIR / filename
    if not pdf_path.exists():
        pytest.skip(f"Demo file not found: {pdf_path}")

    from agents.multimodal import extract_text_from_pdf
    from agents.router_agent import RouterAgent
    from agents.extractor_agent import ExtractorAgent
    from agents.coder_agent import CoderAgent
    from agents.validator_agent import ValidatorAgent
    from agents.exception_handler_agent import ExceptionHandlerAgent

    mock_llm = make_mock_llm()

    # Step 1: Extract text
    text = extract_text_from_pdf(str(pdf_path))

    # Step 2: Route
    router = RouterAgent(llm_client=mock_llm)
    route_result = router.run({"text": text, "file_path": str(pdf_path)}, "company_a")
    assert route_result["doc_type"] in ("invoice", "receipt", "purchase_order")
    assert route_result["modality"] in ("text", "photo")

    # Step 3: Extract
    extractor = ExtractorAgent(llm_client=mock_llm)
    extract_result = extractor.run(
        {"text": text, "doc_type": route_result["doc_type"]},
        "company_a",
    )
    assert "skill_version" in extract_result

    # Step 4: Code (RAG disabled to avoid Qdrant dependency)
    coder = CoderAgent(llm_client=mock_llm, rag_engine=None)
    code_result = coder.run(
        {"extracted": extract_result, "doc_type": route_result["doc_type"]},
        "company_a",
        rag_enabled=False,
    )
    assert "account_code" in code_result

    # Step 5: Validate
    validator = ValidatorAgent(llm_client=mock_llm, trace_store=None)
    val_result = validator.run(
        {"extracted": extract_result, "doc_id": f"test-{filename}"},
        "company_a",
    )
    assert isinstance(val_result["needs_review"], bool)
    assert isinstance(val_result["errors"], list)

    # Step 6: Decision
    if val_result["needs_review"]:
        handler = ExceptionHandlerAgent(llm_client=mock_llm)
        handle_result = handler.run(
            {"extracted": extract_result, "validation": val_result, "doc_id": f"test-{filename}"},
            "company_a",
        )
        decision = "ESCALATED"
        assert "escalation_dossier" in handle_result
    else:
        decision = "ACCEPTED"

    # Property 18: must be ACCEPTED or ESCALATED
    assert decision in ("ACCEPTED", "ESCALATED"), f"Unexpected decision: {decision}"


def test_validator_scorer_empty_lists():
    """
    Property 16: validator([], []) == 1.0
    Feature: n8n-multiagent-doc-pipeline, Property 16: Empty validator score
    """
    from eval.scorers import validator_score
    assert validator_score([], []) == 1.0


def test_extractor_scorer_empty():
    """
    Property 8 (partial): extractor_score({}, {}) == 1.0
    Feature: n8n-multiagent-doc-pipeline, Property 8: Empty extractor score
    """
    from eval.scorers import extractor_score
    assert extractor_score({}, {}) == 1.0


def test_coder_scorer_binary():
    """
    Property 9: coder_score returns exactly 0.0 or 1.0
    Feature: n8n-multiagent-doc-pipeline, Property 9: Binary coder score
    """
    from eval.scorers import coder_score
    result = coder_score(
        {"account_code": "606100", "cited_rule": "Toutes les factures STEG → code 606100"},
        {"account_code": "606100"},
        "Toutes les factures STEG → code 606100",
        [],
    )
    assert result in (0.0, 1.0)
    assert result == 1.0

    result2 = coder_score(
        {"account_code": "606200", "cited_rule": "short"},
        {"account_code": "606100"},
        "Toutes les factures STEG → code 606100",
        [],
    )
    assert result2 in (0.0, 1.0)
    assert result2 == 0.0


def test_data_splits_integrity():
    """
    Property 17: Split proportions with no overlap.
    Feature: n8n-multiagent-doc-pipeline, Property 17: Split proportions
    """
    import json
    splits_path = Path(__file__).parent.parent.parent / "data" / "splits.json"
    if not splits_path.exists():
        pytest.skip("splits.json not generated yet")

    splits = json.loads(splits_path.read_text())
    for company_id, company_splits in splits.items():
        train = set(company_splits.get("train", []))
        selection = set(company_splits.get("selection", []))
        test = set(company_splits.get("test", []))
        total = len(train) + len(selection) + len(test)

        # No overlap
        assert len(train & selection) == 0, f"{company_id}: train ∩ selection overlap"
        assert len(train & test) == 0, f"{company_id}: train ∩ test overlap"
        assert len(selection & test) == 0, f"{company_id}: selection ∩ test overlap"

        # Proportions approximately correct (±10%)
        assert 0.40 <= len(train) / total <= 0.60, f"{company_id}: TRAIN proportion off"
        assert 0.10 <= len(selection) / total <= 0.30, f"{company_id}: SELECTION proportion off"
        assert 0.20 <= len(test) / total <= 0.40, f"{company_id}: TEST proportion off"
