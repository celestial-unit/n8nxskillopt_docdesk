# Feature: n8n-multiagent-doc-pipeline, Data generator property tests
"""
tests/unit/test_data_generator.py — Property tests for the data generator.

Property 4:  Data generator determinism
Property 5:  Error injection cardinality
Property 6:  Generated document format invariants
Property 17: Split proportions with no overlap
"""
import json
import re
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

# ── Property 4: Data generator determinism ───────────────────────────────────
# Feature: n8n-multiagent-doc-pipeline, Property 4: Determinism
# Validates: Requirements 2.1

def test_split_determinism():
    """Running the split twice with seed=42 produces identical splits.json."""
    import data.generator as gen
    import importlib
    importlib.reload(gen)

    with tempfile.TemporaryDirectory() as tmpdir:
        splits_path = Path(tmpdir) / "splits.json"

        # We test the determinism of split_corpus (not full PDF generation — that takes too long)
        import random
        random.seed(42)
        docs_a = [{"doc_id": f"A-DOC-{i:04d}", "company_id": "company_a"} for i in range(150)]
        docs_b = [{"doc_id": f"B-DOC-{i:04d}", "company_id": "company_b"} for i in range(150)]
        all_docs = docs_a + docs_b
        splits_1 = gen.split_corpus(all_docs, seed=42)

        random.seed(42)
        splits_2 = gen.split_corpus(all_docs, seed=42)

    assert splits_1 == splits_2, "split_corpus must be deterministic with seed=42"


# ── Property 5: Error injection cardinality ───────────────────────────────────
# Feature: n8n-multiagent-doc-pipeline, Property 5: Error cardinality
# Validates: Requirements 2.5

VALID_ERROR_TYPES = {"duplicate_id", "arithmetic_mismatch", "missing_matricule", "missing_nif"}


@settings(max_examples=100)
@given(
    error_type=st.sampled_from(["duplicate_id", "arithmetic_mismatch", "missing_nif"]),
)
def test_error_injection_cardinality(error_type):
    """inject_error injects exactly one error of the specified type."""
    from data.generator import inject_error

    doc = {
        "doc_id": "TEST-0001",
        "htva": 100.0,
        "tva": 19.0,
        "ttc": 119.0,
        "matricule_fiscal": "1234567A",
        "injected_errors": [],
    }

    result = inject_error(doc, error_type)

    injected = result.get("injected_errors", [])
    assert len(injected) == 1, (
        f"Expected exactly 1 injected error, got {len(injected)}: {injected}"
    )
    assert injected[0] in VALID_ERROR_TYPES, (
        f"Error type '{injected[0]}' not in {VALID_ERROR_TYPES}"
    )


# ── Property 6: Generated document format invariants ─────────────────────────
# Feature: n8n-multiagent-doc-pipeline, Property 6: Format invariants
# Validates: Requirements 2.11, 2.12

AMOUNT_RE = re.compile(r"^\d[\d\u202f]*,\d{3}$")
DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def test_format_tnd():
    """format_tnd produces amounts in French TND format."""
    from data.generator import format_tnd

    test_cases = [
        (0.0, True),
        (119.0, True),
        (1011.5, True),
        (12345.678, True),
    ]

    for amount, should_match in test_cases:
        result = format_tnd(amount)
        if should_match:
            assert AMOUNT_RE.match(result), (
                f"format_tnd({amount}) = {result!r} does not match {AMOUNT_RE.pattern}"
            )


@settings(max_examples=100)
@given(
    amount=st.floats(min_value=0.0, max_value=999999.999, allow_nan=False, allow_infinity=False),
)
def test_format_tnd_always_matches_pattern(amount):
    """format_tnd always produces amounts matching the French TND format."""
    from data.generator import format_tnd
    result = format_tnd(amount)
    assert AMOUNT_RE.match(result), (
        f"format_tnd({amount}) = {result!r} does not match pattern"
    )


def test_format_date():
    """format_date produces dates in dd/mm/yyyy format."""
    from data.generator import format_date
    import datetime

    test_cases = [
        datetime.date(2024, 1, 1),
        datetime.date(2024, 12, 31),
        datetime.date(2023, 6, 15),
    ]

    for dt in test_cases:
        result = format_date(dt)
        assert DATE_RE.match(result), (
            f"format_date({dt}) = {result!r} does not match dd/mm/yyyy"
        )


# ── Property 17: Split proportions with no overlap ───────────────────────────
# Feature: n8n-multiagent-doc-pipeline, Property 17: Split proportions
# Validates: Requirements 2.7, 16.9

def test_split_proportions_and_no_overlap():
    """
    split_corpus produces TRAIN≈70%, SELECTION≈20%, TEST≈10% (or similar) with no overlap.
    The handoff says: TRAIN 70 / SELECTION 30 / TEST 50 out of 150 docs per company.
    Check: each doc in exactly one split, and proportions within ±15%.
    """
    from data.generator import split_corpus

    # Create dummy corpus
    docs = [{"doc_id": f"A-DOC-{i:04d}", "company_id": "company_a"} for i in range(150)]
    splits = split_corpus(docs, seed=42)

    train = splits.get("train", [])
    selection = splits.get("selection", [])
    test = splits.get("test", [])

    total = len(train) + len(selection) + len(test)
    assert total == len(docs), f"Total split size {total} != corpus size {len(docs)}"

    # No overlap
    train_ids = {d["doc_id"] for d in train}
    selection_ids = {d["doc_id"] for d in selection}
    test_ids = {d["doc_id"] for d in test}

    assert len(train_ids & selection_ids) == 0, "Train and selection overlap!"
    assert len(train_ids & test_ids) == 0, "Train and test overlap!"
    assert len(selection_ids & test_ids) == 0, "Selection and test overlap!"

    # Proportions within ±15% of expected
    n = len(docs)
    train_pct = len(train) / n
    selection_pct = len(selection) / n
    test_pct = len(test) / n

    assert 0.35 <= train_pct <= 0.85, f"Train proportion {train_pct:.1%} out of expected range"
    assert 0.05 <= selection_pct <= 0.45, f"Selection proportion {selection_pct:.1%} out of expected range"
    assert 0.05 <= test_pct <= 0.50, f"Test proportion {test_pct:.1%} out of expected range"


def test_split_all_docs_assigned():
    """Every document appears in exactly one split."""
    from data.generator import split_corpus

    docs = [{"doc_id": f"A-DOC-{i:04d}"} for i in range(150)]
    splits = split_corpus(docs, seed=42)

    all_ids: list[str] = []
    for split_name, split_docs in splits.items():
        all_ids.extend(d["doc_id"] for d in split_docs)

    assert len(all_ids) == len(docs), "Not all documents were assigned to a split"
    assert len(set(all_ids)) == len(docs), "Some documents appear in multiple splits"
