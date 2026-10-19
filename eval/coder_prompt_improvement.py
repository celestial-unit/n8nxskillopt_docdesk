"""Paired, gold-input Coder prompt comparison on a fixed Company B sample.

This isolates coding decisions from extraction. It compares the original
baseline prompt with the active v003 skill, using identical top-5 RAG context.
The sample includes varied vendors and the four TechVision consulting cases.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from agents.llm_client import LLMClient
from eval.scorers import coder_score
from rag.engine import RAGEngine

ROOT = Path(__file__).resolve().parents[1]
OLD_PROMPT = ROOT / "prompts/iterations/company_b_coder_v001_baseline.md"
NEW_PROMPT = ROOT / "skills/company_b/coder/v004.md"
DATA = ROOT / "skillopt_data/selection.json"
OUT = ROOT / "eval/results/company_b_coder_improvement.json"
SAMPLE_IDS = [
    "B-DOC-0113", "B-DOC-0129",  # TechVision consulting
    "B-DOC-0089",                # energy
    "B-DOC-0002",                # water
    "B-DOC-0010",                # telecom
    "B-DOC-0073",                # supplies
    "B-DOC-0116",                # fuel
    "B-DOC-0142",                # EuroTech IT
    "B-DOC-0149",                # independent consulting vendor
    "B-DOC-0057",                # insurance
]


def parse_response(raw: str) -> dict:
    clean = raw.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean, flags=re.I)
    match = re.search(r"\{.*\}", clean, flags=re.S)
    return json.loads(match.group(0) if match else clean)


def main() -> None:
    items_by_id = {
        item["id"]: item for item in json.loads(DATA.read_text(encoding="utf-8"))
        if item.get("company_id") == "company_b"
    }
    missing = [doc_id for doc_id in SAMPLE_IDS if doc_id not in items_by_id]
    if missing:
        raise SystemExit(f"Sample documents missing from SELECTION: {missing}")
    items = [items_by_id[doc_id] for doc_id in SAMPLE_IDS]
    prompts = {
        "baseline_v001": OLD_PROMPT.read_text(encoding="utf-8"),
        "improved_v004": NEW_PROMPT.read_text(encoding="utf-8"),
    }
    os.environ["DEMO_CACHE"] = "0"
    llm = LLMClient()
    llm._client = llm._client.with_options(timeout=30.0, max_retries=0)
    rag = RAGEngine("company_b")
    results = {key: [] for key in prompts}

    def checkpoint(status: str) -> None:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({
            "experiment": "company_b_coder_prompt_improvement",
            "status": status,
            "split": "SELECTION",
            "sample_size": len(items),
            "sample_ids": SAMPLE_IDS,
            "input_policy": "gold extracted fields; isolates coding prompt",
            "rag_policy": "same company-filtered top-5 chunks per document",
            "prompt_sha256": {k: hashlib.sha256(v.encode()).hexdigest() for k, v in prompts.items()},
            "results": results,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    for index, item in enumerate(items, 1):
        fields = item["gold_fields"]
        chunks = rag.search(
            f"{fields.get('supplier', '')} {item.get('doc_type', 'invoice')} codification comptable",
            top_k=5,
        )
        context = "\n\n## Règles récupérées :\n" + "\n---\n".join(
            f"[Score: {chunk.get('score', 0):.3f}] {chunk.get('text', '')}" for chunk in chunks
        ) if chunks else ""
        message = f"Document extrait :\n{json.dumps(fields, ensure_ascii=False, indent=2)}\n{context}"
        order = list(prompts) if index % 2 else list(reversed(prompts))
        for version in order:
            row = {"id": item["id"], "gold_code": item["gold_account_code"],
                   "response_received": False, "parse_ok": False, "score": 0}
            started = time.monotonic()
            try:
                raw = llm.call("agent", prompts[version], message)
                row["response_received"] = True
                pred = parse_response(raw)
                row.update({
                    "parse_ok": True,
                    "predicted_code": str(pred.get("account_code", "")),
                    "cited_rule": str(pred.get("cited_rule", "")),
                    "score": int(coder_score(pred, {"account_code": item["gold_account_code"]},
                                             prompts[version], chunks)),
                })
            except Exception as exc:
                row.update({"error_type": type(exc).__name__, "error": str(exc)[:240]})
            row["latency_ms"] = round((time.monotonic() - started) * 1000)
            results[version].append(row)
            checkpoint("running")
            time.sleep(8)
        print(f"Completed paired document {index}/{len(items)}", flush=True)

    by_prompt = {}
    for key, rows in results.items():
        responded = [row for row in rows if row["response_received"]]
        by_prompt[key] = {
            "attempts": len(rows),
            "responses": len(responded),
            "parse_rate": round(sum(row["parse_ok"] for row in responded) / len(responded), 4) if responded else None,
            "code_accuracy": round(sum(row.get("predicted_code") == row["gold_code"] for row in responded) / len(responded), 4) if responded else None,
            "supported_coder_score": round(sum(row["score"] for row in responded) / len(responded), 4) if responded else None,
        }
    paired = []
    left = {row["id"]: row for row in results["baseline_v001"] if row["response_received"]}
    right = {row["id"]: row for row in results["improved_v004"] if row["response_received"]}
    for doc_id in SAMPLE_IDS:
        if doc_id in left and doc_id in right:
            paired.append((left[doc_id], right[doc_id]))
    before = sum(a["score"] for a, _ in paired)
    after = sum(b["score"] for _, b in paired)
    summary = {
        "baseline_v001": by_prompt["baseline_v001"],
        "improved_v004": by_prompt["improved_v004"],
        "paired_n": len(paired),
        "paired_baseline_correct": before,
        "paired_improved_correct": after,
        "paired_delta_pp": round((after - before) / len(paired) * 100, 1) if paired else None,
        "wins": sum(b["score"] > a["score"] for a, b in paired),
        "losses": sum(b["score"] < a["score"] for a, b in paired),
        "ties": sum(b["score"] == a["score"] for a, b in paired),
    }
    checkpoint("complete")
    payload = json.loads(OUT.read_text(encoding="utf-8"))
    payload["summary"] = summary
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary, "output": str(OUT)}, indent=2), flush=True)


if __name__ == "__main__":
    main()
