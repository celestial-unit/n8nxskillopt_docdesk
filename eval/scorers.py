"""
eval/scorers.py — Evaluation metrics for the document pipeline agents.

extractor_score : normalized exact match across all gold fields
coder_score     : binary (1.0 iff code matches AND cited rule found in skill/chunks)
validator_score : F-beta weighted F1 with beta=sqrt(2) (FN cost 2x FP)
"""

import math
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Optional


# ── Normalization ─────────────────────────────────────────────────────────────

def normalize(s: str) -> str:
    """
    Normalize a string for comparison:
    - Strip leading/trailing whitespace
    - Lowercase
    - NFC unicode normalization
    - Remove all whitespace (including narrow no-break spaces)
    - Replace comma with period (French decimal → standard)

    Example: '1\u202f011,500 TND' → '1011.500tnd'
    """
    if not isinstance(s, str):
        s = str(s) if s is not None else ""
    s = s.strip().lower()
    s = unicodedata.normalize("NFC", s)
    # Remove all whitespace variants (including \u202f narrow no-break space)
    s = re.sub(r"[\s\u00a0\u202f]+", "", s)
    # French decimal comma → period
    s = s.replace(",", ".")
    try:
        return format(Decimal(s).normalize(), "f")
    except InvalidOperation:
        pass
    return s


# ── Extractor scorer ──────────────────────────────────────────────────────────

def extractor_score(predicted: dict, gold: dict) -> float:
    """
    Normalized exact match between predicted and gold fields.

    Compare fields supported by the production ExtractResponse contract.
    The benchmark-only reference_unique field is intentionally excluded. Gold
    line_descriptions are compared to descriptions nested in predicted lines[].
    Returns the mean score across all gold keys.
    Returns 1.0 if gold is empty.

    Args:
        predicted: dict of extracted fields
        gold: dict of reference fields

    Returns:
        Float in [0.0, 1.0]
    """
    if not gold:
        return 1.0

    scores = []
    for key in gold:
        # This field is in the synthetic benchmark but not in ExtractResponse.
        if key == "reference_unique":
            continue
        gold_val = normalize(str(gold[key])) if gold[key] is not None else ""
        if key == "line_descriptions":
            descriptions = predicted.get("line_descriptions")
            if descriptions is None:
                lines = predicted.get("lines", [])
                descriptions = [
                    line.get("description", "")
                    for line in lines if isinstance(line, dict)
                ]
            pred_val = [normalize(str(value)) for value in descriptions]
            gold_val = [normalize(str(value)) for value in (gold[key] or [])]
        else:
            pred_value = predicted.get(key, "")
            pred_val = normalize(str(pred_value)) if pred_value is not None else ""
        scores.append(1.0 if pred_val == gold_val else 0.0)

    return sum(scores) / len(scores) if scores else 1.0


# ── Coder scorer ──────────────────────────────────────────────────────────────

def coder_score(
    predicted: dict,
    gold: dict,
    skill_text: str,
    chunks: Optional[list[dict]] = None,
) -> float:
    """
    Binary scorer for the Coder agent.

    Returns 1.0 if AND ONLY IF:
    1. predicted["account_code"] == gold["account_code"]
    2. predicted["cited_rule"] (≥10 chars) is a substring of skill_text OR
       any chunk["text"] in chunks (case-insensitive)

    Returns 0.0 in all other cases.

    Args:
        predicted: Coder agent output dict with "account_code" and "cited_rule"
        gold: Gold label dict with "account_code"
        skill_text: full text of the loaded skill file
        chunks: list of retrieved RAG chunks, each with "text" key

    Returns:
        1.0 or 0.0
    """
    if chunks is None:
        chunks = []

    pred_code = predicted.get("account_code", "")
    gold_code = gold.get("account_code", "")
    cited_rule = predicted.get("cited_rule", "")

    # Check 1: code must match exactly
    if pred_code != gold_code:
        return 0.0

    # Check 2: cited rule must be ≥10 chars
    if len(cited_rule) < 10:
        return 0.0

    # Check 3: cited rule must appear as substring in skill_text or any chunk
    cited_lower = cited_rule.lower()
    if cited_lower in skill_text.lower():
        return 1.0

    for chunk in chunks:
        chunk_text = chunk.get("text", "")
        if cited_lower in chunk_text.lower():
            return 1.0

    return 0.0


# ── Validator scorer ──────────────────────────────────────────────────────────

def validator_score(predicted: list[str], reference: list[str]) -> float:
    """
    Weighted F1 score for the Validator agent.

    Uses beta = sqrt(2) so that FN (missed errors) cost 2x FP (false alarms).
    F_beta = (1 + beta²) * TP / ((1 + beta²) * TP + beta² * FN + FP)

    Special case: both lists empty → returns 1.0 (no errors, none predicted → perfect).

    Args:
        predicted: list of error types predicted by the Validator
        reference: list of actual error types (from gold labels)

    Returns:
        Float in [0.0, 1.0]
    """
    if not predicted and not reference:
        return 1.0

    pred_set = set(predicted)
    ref_set  = set(reference)

    tp = len(pred_set & ref_set)
    fp = len(pred_set - ref_set)
    fn = len(ref_set  - pred_set)

    beta = math.sqrt(2)
    beta2 = beta ** 2

    denom = (1 + beta2) * tp + beta2 * fn + fp
    if denom == 0:
        return 0.0

    return (1 + beta2) * tp / denom


# ── Aggregate scorer ──────────────────────────────────────────────────────────

def score_pipeline_run(
    extractor_pred: dict,
    extractor_gold: dict,
    coder_pred: dict,
    coder_gold: dict,
    skill_text: str,
    chunks: list[dict],
    validator_pred: list[str],
    validator_gold: list[str],
) -> dict:
    """
    Compute all three scores for a single pipeline run.

    Returns:
        {
            "extractor": float,
            "coder": float,
            "validator": float,
        }
    """
    return {
        "extractor": extractor_score(extractor_pred, extractor_gold),
        "coder": coder_score(coder_pred, coder_gold, skill_text, chunks),
        "validator": validator_score(validator_pred, validator_gold),
    }
