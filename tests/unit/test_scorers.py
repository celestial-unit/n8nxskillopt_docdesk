# Feature: n8n-multiagent-doc-pipeline, Scorer property tests
"""
tests/unit/test_scorers.py — Property tests for evaluation scorers.

Property 8:  Normalizer idempotence on equivalent strings
Property 9:  Coder scorer is strictly binary
Property 16: Validator scorer returns 1.0 for empty inputs
"""
import math
import pytest
from hypothesis import given, settings, strategies as st

from eval.scorers import normalize, extractor_score, coder_score, validator_score


# ── Property 8: Normalizer idempotence on equivalent strings ──────────────────
# Feature: n8n-multiagent-doc-pipeline, Property 8: Normalizer idempotence
# Validates: Requirements 5.1

@settings(max_examples=100)
@given(s=st.text(min_size=0, max_size=200))
def test_normalize_is_idempotent(s):
    """normalize(normalize(s)) == normalize(s) — idempotent."""
    once = normalize(s)
    twice = normalize(once)
    assert once == twice, f"normalize not idempotent: {once!r} != {twice!r}"


@settings(max_examples=100)
@given(
    base=st.text(min_size=1, max_size=50).filter(lambda s: s.strip()),
    spaces=st.lists(st.text(alphabet=" \t\n", min_size=1, max_size=5), min_size=0, max_size=3),
)
def test_extractor_score_ignores_whitespace(base, spaces):
    """extractor_score == 1.0 for values differing only in whitespace."""
    predicted_val = base.strip()
    gold_val = ("  " + base.strip() + "  ")  # leading/trailing spaces

    predicted = {"field": predicted_val}
    gold = {"field": gold_val}

    score = extractor_score(predicted, gold)
    assert score == 1.0, (
        f"Expected 1.0 for whitespace-only difference: {predicted_val!r} vs {gold_val!r}, got {score}"
    )


@settings(max_examples=100)
@given(
    base=st.text(
        min_size=1, max_size=50,
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789 _-",
    ).filter(lambda s: s.strip())
)
def test_extractor_score_case_insensitive(base):
    """extractor_score == 1.0 for ASCII values differing only in case."""
    predicted = {"field": base.lower()}
    gold = {"field": base.upper()}

    score = extractor_score(predicted, gold)
    assert score == 1.0, (
        f"Expected 1.0 for case difference: {base.lower()!r} vs {base.upper()!r}, got {score}"
    )


# ── Property 9: Coder scorer is strictly binary ───────────────────────────────
# Feature: n8n-multiagent-doc-pipeline, Property 9: Binary coder score
# Validates: Requirements 5.2

@settings(max_examples=100)
@given(
    pred_code=st.text(min_size=1, max_size=20),
    gold_code=st.text(min_size=1, max_size=20),
    cited=st.text(min_size=0, max_size=100),
    skill=st.text(min_size=0, max_size=500),
)
def test_coder_score_is_strictly_binary(pred_code, gold_code, cited, skill):
    """coder_score always returns exactly 0.0 or 1.0."""
    predicted = {"account_code": pred_code, "cited_rule": cited}
    gold = {"account_code": gold_code}

    score = coder_score(predicted, gold, skill, [])

    assert score in (0.0, 1.0), (
        f"Expected 0.0 or 1.0, got {score}"
    )


@settings(max_examples=100)
@given(
    code=st.text(min_size=6, max_size=6, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
    cited=st.text(min_size=10, max_size=100),
)
def test_coder_score_1_when_code_matches_and_rule_found(code, cited):
    """coder_score == 1.0 when code matches AND cited_rule in skill_text."""
    predicted = {"account_code": code, "cited_rule": cited}
    gold = {"account_code": code}
    skill_text = f"Les règles... {cited} ...fin."

    score = coder_score(predicted, gold, skill_text, [])
    assert score == 1.0


@settings(max_examples=100)
@given(
    pred_code=st.text(min_size=6, max_size=6, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
    gold_code=st.text(min_size=6, max_size=6, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789").filter(
        lambda s: s != "AAAAAA"
    ),
)
def test_coder_score_0_when_code_mismatch(pred_code, gold_code):
    """coder_score == 0.0 when codes don't match, regardless of cited rule."""
    if pred_code == gold_code:
        gold_code = gold_code[:-1] + ("B" if gold_code[-1] != "B" else "C")

    predicted = {"account_code": pred_code, "cited_rule": "rule that definitely exists"}
    gold = {"account_code": gold_code}
    skill_text = "rule that definitely exists"

    score = coder_score(predicted, gold, skill_text, [])
    assert score == 0.0


# ── Property 16: Validator scorer returns 1.0 for empty inputs ─────────────────
# Feature: n8n-multiagent-doc-pipeline, Property 16: Empty validator score
# Validates: Requirements 5.4, 16.7

def test_validator_score_empty_both():
    """validator_score([], []) must return exactly 1.0."""
    score = validator_score([], [])
    assert score == 1.0, f"Expected 1.0 for empty inputs, got {score}"


def test_extractor_score_uses_production_line_schema_and_ignores_reference_unique():
    """Do not penalize unsupported benchmark metadata; map lines[].description."""
    predicted = {
        "supplier": "STEG",
        "lines": [{"description": "Électricité"}, {"description": "Gaz"}],
        "htva": 10.0,
    }
    gold = {
        "supplier": "steg",
        "line_descriptions": ["Électricité", "Gaz"],
        "htva": "10,000",
        "reference_unique": "REF-FAC-123456",
    }
    assert extractor_score(predicted, gold) == 1.0


@settings(max_examples=100)
@given(
    predicted=st.lists(st.sampled_from(["arithmetic_mismatch", "missing_matricule", "duplicate_id"]), min_size=0, max_size=3),
    reference=st.lists(st.sampled_from(["arithmetic_mismatch", "missing_matricule", "duplicate_id"]), min_size=0, max_size=3),
)
def test_validator_score_in_range(predicted, reference):
    """validator_score always returns a float in [0.0, 1.0]."""
    score = validator_score(predicted, reference)
    assert 0.0 <= score <= 1.0, (
        f"Score {score} out of [0, 1] for pred={predicted} ref={reference}"
    )


@settings(max_examples=100)
@given(
    errors=st.lists(
        st.sampled_from(["arithmetic_mismatch", "missing_matricule", "duplicate_id"]),
        min_size=1, max_size=3,
    )
)
def test_validator_score_perfect_match(errors):
    """validator_score == 1.0 when predicted == reference (exact match)."""
    score = validator_score(list(set(errors)), list(set(errors)))
    assert score == 1.0, f"Expected 1.0 for identical sets, got {score}"
