"""
eval/baseline.py — Baseline evaluation on SELECTION set using v001 skills.

Scores each agent on SELECTION split, with and without RAG for the Coder.
Writes results to eval/results/baseline.md.

Usage:
    python3 -m eval.baseline --company company_a
    python3 -m eval.baseline --company all
"""

import argparse
import json
import time
from pathlib import Path

from agents.llm_client import LLMClient
from agents.extractor_agent import ExtractorAgent
from agents.coder_agent import CoderAgent
from agents.validator_agent import ValidatorAgent
from agents.skill_loader import load_skill
from eval.scorers import extractor_score, coder_score, validator_score


def load_selection_docs(company_id: str) -> list[dict]:
    """Load SELECTION split gold documents for a company."""
    splits_path = Path("data/splits.json")
    if not splits_path.exists():
        print("  ERROR: data/splits.json not found. Run python3 -m data.generator first.")
        return []

    splits = json.loads(splits_path.read_text(encoding="utf-8"))
    selection_ids = splits.get(company_id, {}).get("selection", [])

    docs_dir = Path("data") / company_id / "documents"
    docs = []
    for doc_id in selection_ids:
        gold_path = docs_dir / f"{doc_id}_gold.json"
        pdf_path = docs_dir / f"{doc_id}.pdf"
        if gold_path.exists():
            gold = json.loads(gold_path.read_text(encoding="utf-8"))
            gold["pdf_path"] = str(pdf_path) if pdf_path.exists() else None
            docs.append(gold)
    return docs


def evaluate_company(company_id: str, llm: LLMClient) -> dict:
    docs = load_selection_docs(company_id)
    if not docs:
        return {}

    print(f"  {len(docs)} SELECTION documents for {company_id}")

    extractor = ExtractorAgent(llm_client=llm)
    coder_rag = CoderAgent(llm_client=llm)
    coder_no_rag = CoderAgent(llm_client=llm)
    validator = ValidatorAgent(llm_client=llm)

    ext_scores, coder_rag_scores, coder_no_rag_scores, val_scores = [], [], [], []
    failures = []

    for doc in docs:
        doc_id = doc["doc_id"]
        gold_fields = doc.get("fields", {})
        gold_code = doc.get("account_code", "")
        gold_errors = doc.get("injected_errors", [])

        try:
            # Read PDF text (if available)
            pdf_text = ""
            if doc.get("pdf_path") and Path(doc["pdf_path"]).exists():
                from agents.multimodal import extract_text_from_pdf
                pdf_text = extract_text_from_pdf(doc["pdf_path"])

            # Extract
            ext_result = extractor.run(
                {"text": pdf_text or str(gold_fields), "doc_type": doc.get("doc_type", "invoice")},
                company_id,
            )
            e_score = extractor_score(ext_result, gold_fields)
            ext_scores.append(e_score)

            # Load skill for coder scoring
            skill_text, _ = load_skill(company_id, "coder")

            # Code with RAG
            code_rag = coder_rag.run(
                {"extracted": ext_result, "doc_type": doc.get("doc_type", "invoice")},
                company_id,
                rag_enabled=True,
            )
            c_rag = coder_score(code_rag, {"account_code": gold_code}, skill_text, code_rag.get("chunks", []))
            coder_rag_scores.append(c_rag)

            # Code without RAG
            code_no_rag = coder_no_rag.run(
                {"extracted": ext_result, "doc_type": doc.get("doc_type", "invoice")},
                company_id,
                rag_enabled=False,
            )
            c_no_rag = coder_score(code_no_rag, {"account_code": gold_code}, skill_text, [])
            coder_no_rag_scores.append(c_no_rag)

            # Validate
            val_result = validator.run({"extracted": ext_result, "doc_id": doc_id}, company_id)
            v_score = validator_score(val_result.get("errors", []), gold_errors)
            val_scores.append(v_score)

        except Exception as e:
            failures.append({"doc_id": doc_id, "error": str(e)})
            ext_scores.append(0.0)
            coder_rag_scores.append(0.0)
            coder_no_rag_scores.append(0.0)
            val_scores.append(0.0)

    def avg(lst): return round(sum(lst) / len(lst), 4) if lst else 0.0

    return {
        "n_docs": len(docs),
        "extractor_nem": avg(ext_scores),
        "coder_with_rag": avg(coder_rag_scores),
        "coder_no_rag": avg(coder_no_rag_scores),
        "validator_f_beta": avg(val_scores),
        "failures": failures,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", default="all", choices=["company_a", "company_b", "all"])
    args = parser.parse_args()

    llm = LLMClient()
    companies = ["company_a", "company_b"] if args.company == "all" else [args.company]

    results = {}
    for cid in companies:
        print(f"\n=== Baseline: {cid} ===")
        results[cid] = evaluate_company(cid, llm)

    # Write report
    Path("eval/results").mkdir(parents=True, exist_ok=True)
    report = Path("eval/results/baseline.md")

    lines = [
        "# Baseline Evaluation — SELECTION Set\n",
        "Skill version: v001 | Split: SELECTION (20%)\n",
        "| Company | Docs | Extractor NEM | Coder (RAG) | Coder (no RAG) | Validator F-β |",
        "|---------|------|--------------|-------------|----------------|---------------|",
    ]
    for cid, r in results.items():
        if r:
            lines.append(
                f"| {cid} | {r['n_docs']} | {r['extractor_nem']} | {r['coder_with_rag']} "
                f"| {r['coder_no_rag']} | {r['validator_f_beta']} |"
            )

    lines += [
        "\n## Failures",
        "",
    ]
    for cid, r in results.items():
        for f in r.get("failures", []):
            lines.append(f"- **{cid}** `{f['doc_id']}`: {f['error']}")

    lines += [
        "\n## Notes",
        "- All scores are from real pipeline runs.",
        "- Extractor NEM: normalized exact match across gold fields.",
        "- Coder: 1.0 only if code matches gold AND cited rule appears in skill/chunks.",
        "- Validator F-β (β=√2): false negatives cost 2× false positives.",
        "- v002 scores will be added after prompt corrections.",
    ]

    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {report}")

    # Print failures for manual correction
    for cid, r in results.items():
        if r.get("failures"):
            print(f"\nFailed docs for {cid}:")
            for f in r["failures"]:
                print(f"  - {f['doc_id']}: {f['error']}")


if __name__ == "__main__":
    main()
