"""Evaluate a TRAIN-derived Company B skill rule on held-out TechVision cases."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from agents.llm_client import LLMClient
from eval.scorers import coder_score
from rag.engine import RAGEngine

ROOT = Path(__file__).resolve().parents[1]
BEFORE = ROOT / "prompts/iterations/company_b_coder_v002_candidate.md"
AFTER = ROOT / "skills/company_b/coder/v003.md"
SELECTION = ROOT / "skillopt_data/selection.json"
OUT = ROOT / "eval/results/company_b_skill_adaptation.json"


def parse_response(raw: str) -> dict:
    clean = raw.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean, flags=re.I)
    match = re.search(r"\{.*\}", clean, flags=re.S)
    return json.loads(match.group(0) if match else clean)


def main() -> None:
    rows = json.loads(SELECTION.read_text(encoding="utf-8"))
    items = [x for x in rows if x.get("company_id") == "company_b"
             and x.get("gold_fields", {}).get("supplier") == "TechVision International"]
    if len(items) != 4:
        raise SystemExit(f"Expected four held-out Company B TechVision items, found {len(items)}")
    prompts = {"v002": BEFORE.read_text(encoding="utf-8"),
               "v003": AFTER.read_text(encoding="utf-8")}
    os.environ["DEMO_CACHE"] = "0"
    llm = LLMClient()
    llm._client = llm._client.with_options(timeout=30.0, max_retries=0)
    rag = RAGEngine("company_b")
    results = {k: [] for k in prompts}

    def checkpoint(status: str) -> None:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({
            "experiment": "company_b_train_derived_skill_adaptation",
            "status": status,
            "split": "SELECTION",
            "n_items": len(items),
            "input_policy": "gold extracted fields isolate coding; identical RAG for both versions",
            "results": results,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    for index, item in enumerate(items, 1):
        fields = item["gold_fields"]
        doc_type = item.get("doc_type", "invoice")
        chunks = rag.search(f"{fields.get('supplier', '')} {doc_type} honoraires conseil audit étude de marché", top_k=5)
        context = "\n\n## Règles récupérées :\n" + "\n---\n".join(
            f"[Score: {c.get('score', 0):.3f}] {c.get('text', '')}" for c in chunks
        ) if chunks else ""
        message = f"Document extrait :\n{json.dumps(fields, ensure_ascii=False, indent=2)}\n{context}"
        order = list(prompts) if index % 2 else list(reversed(prompts))
        for version in order:
            row = {"id": item["id"], "gold_code": item["gold_account_code"],
                   "parse_ok": False, "score": 0}
            started = time.monotonic()
            try:
                raw = llm.call("agent", prompts[version], message)
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
        print(f"Completed held-out case {index}/{len(items)}", flush=True)

    summary = {}
    for version, vals in results.items():
        summary[version] = {
            "n": len(vals),
            "parse_rate": round(sum(r["parse_ok"] for r in vals) / len(vals), 4),
            "code_accuracy": round(sum(r.get("predicted_code") == r["gold_code"] for r in vals) / len(vals), 4),
            "supported_coder_score": round(sum(r["score"] for r in vals) / len(vals), 4),
        }
    checkpoint("complete")
    payload = json.loads(OUT.read_text(encoding="utf-8"))
    payload["summary"] = summary
    payload["paired_delta"] = round(summary["v003"]["supported_coder_score"] - summary["v002"]["supported_coder_score"], 4)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary, "paired_delta": payload["paired_delta"], "output": str(OUT)}, indent=2), flush=True)


if __name__ == "__main__":
    main()
