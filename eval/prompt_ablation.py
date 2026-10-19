"""Paired Company B Coder prompt experiment (gold fields isolate coding quality).

Runs the original prompt and a JSON-guardrailed candidate on the same
SELECTION documents, with identical gold extraction fields and company-filtered
RAG results. This is a bounded prompt comparison, not an end-to-end score.

Usage: .venv/bin/python -m eval.prompt_ablation [--limit 30]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import time
from pathlib import Path

from agents.llm_client import LLMClient
from eval.scorers import coder_score
from rag.engine import RAGEngine

ROOT = Path(__file__).resolve().parents[1]
BEFORE = ROOT / "prompts/iterations/company_b_coder_v001_baseline.md"
AFTER = ROOT / "prompts/iterations/company_b_coder_v002_candidate.md"
SELECTION = ROOT / "skillopt_data/selection.json"
OUT = ROOT / "eval/results/company_b_coder_prompt_ablation.json"


def parse_response(raw: str) -> dict:
    clean = raw.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean, flags=re.I)
    match = re.search(r"\{.*\}", clean, flags=re.S)
    return json.loads(match.group(0) if match else clean)


def wilson(successes: int, n: int) -> list[float]:
    if not n:
        return [0.0, 0.0]
    z = 1.96
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0, center - margin), 4), round(min(1, center + margin), 4)]


def mcnemar_exact(before: list[int], after: list[int]) -> float | None:
    b = sum(x == 1 and y == 0 for x, y in zip(before, after))
    c = sum(x == 0 and y == 1 for x, y in zip(before, after))
    n = b + c
    if n == 0:
        return None
    tail = sum(math.comb(n, k) for k in range(min(b, c) + 1)) / (2**n)
    return round(min(1.0, 2 * tail), 6)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()
    if not (0 < args.limit <= 30):
        raise SystemExit("--limit must be between 1 and 30 (Company B SELECTION only)")

    items = [x for x in json.loads(SELECTION.read_text(encoding="utf-8"))
             if x.get("company_id") == "company_b"][:args.limit]
    if len(items) != args.limit:
        raise SystemExit(f"Expected {args.limit} Company B selection items; found {len(items)}")

    prompts = {"v001_baseline": BEFORE.read_text(encoding="utf-8"),
               "v002_candidate": AFTER.read_text(encoding="utf-8")}
    # This experiment must query the model, not reuse a cached answer.
    os.environ["DEMO_CACHE"] = "0"
    llm = LLMClient()
    # Avoid an endpoint stall holding the whole evaluation indefinitely.
    llm._client = llm._client.with_options(timeout=30.0, max_retries=0)
    rag = RAGEngine(company_id="company_b")
    outputs = {key: [] for key in prompts}
    latencies = {key: [] for key in prompts}

    def write_checkpoint(status: str) -> None:
        partial_summary = {}
        for label, rows in outputs.items():
            n_rows = len(rows)
            model_rows = [r for r in rows if r.get("response_received")]
            correct = sum(r["score"] for r in model_rows)
            partial_summary[label] = {
                "attempts": n_rows,
                "model_responses": len(model_rows),
                "coder_score_on_responses": round(correct / len(model_rows), 4) if model_rows else None,
                "parse_rate_on_responses": round(sum(r["parse_ok"] for r in model_rows) / len(model_rows), 4) if model_rows else None,
                "median_latency_ms": sorted(r["latency_ms"] for r in model_rows)[len(model_rows) // 2] if model_rows else None,
            }
        checkpoint = {
            "experiment": "company_b_coder_prompt_ablation",
            "status": status,
            "split": "SELECTION",
            "input_policy": "gold extracted fields; isolates coder prompt and RAG",
            "rag": "same company-filtered top-5 retrieval for both prompts",
            "n_calls": sum(len(rows) for rows in outputs.values()),
            "prompt_sha256": {k: hashlib.sha256(v.encode()).hexdigest() for k, v in prompts.items()},
            "summary": partial_summary,
            "items": outputs,
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")

    for index, item in enumerate(items, 1):
        fields = item.get("gold_fields", {})
        supplier = fields.get("supplier", "")
        doc_type = item.get("doc_type", "invoice")
        chunks = rag.search(f"{supplier} {doc_type} codification comptable", top_k=5)
        rag_context = "\n\n## Règles récupérées :\n" + "\n---\n".join(
            f"[Score: {c.get('score', 0):.3f}] {c.get('text', '')}" for c in chunks
        ) if chunks else ""
        user_message = (f"Document extrait :\n{json.dumps(fields, ensure_ascii=False, indent=2)}\n"
                        f"{rag_context}")

        # Alternate call order to reduce systematic order effects.
        order = list(prompts) if index % 2 else list(reversed(prompts))
        for label in order:
            started = time.monotonic()
            row = {"id": item["id"], "response_received": False, "parse_ok": False, "score": 0}
            try:
                raw = llm.call("agent", prompts[label], user_message)
                row["response_received"] = True
                predicted = parse_response(raw)
                row["parse_ok"] = True
                row["score"] = int(coder_score(
                    predicted,
                    {"account_code": item.get("gold_account_code", "")},
                    prompts[label], chunks,
                ))
                row["predicted_code"] = str(predicted.get("account_code", ""))
            except Exception as exc:
                row["error_type"] = type(exc).__name__
                row["error"] = str(exc)[:240]
            row["latency_ms"] = round((time.monotonic() - started) * 1000)
            latencies[label].append(row["latency_ms"])
            outputs[label].append(row)
        print(f"Completed {index}/{len(items)} paired documents")
        write_checkpoint("running")

    n = len(items)
    summary = {}
    for label, rows in outputs.items():
        model_rows = [r for r in rows if r.get("response_received")]
        correct = sum(r["score"] for r in model_rows)
        parsed = sum(r["parse_ok"] for r in model_rows)
        summary[label] = {
            "attempts": len(rows),
            "model_responses": len(model_rows),
            "coder_score_on_responses": round(correct / len(model_rows), 4) if model_rows else None,
            "coder_score_95pct_wilson": wilson(correct, len(model_rows)),
            "parse_rate_on_responses": round(parsed / len(model_rows), 4) if model_rows else None,
            "median_latency_ms": sorted(r["latency_ms"] for r in model_rows)[len(model_rows) // 2] if model_rows else None,
        }
    baseline_by_id = {r["id"]: r for r in outputs["v001_baseline"] if r.get("response_received")}
    candidate_by_id = {r["id"]: r for r in outputs["v002_candidate"] if r.get("response_received")}
    paired_rows = [(baseline_by_id[doc_id], candidate_by_id[doc_id])
                   for doc_id in sorted(baseline_by_id.keys() & candidate_by_id.keys())]
    before_scores = [a["score"] for a, _ in paired_rows]
    after_scores = [b["score"] for _, b in paired_rows]
    summary["paired"] = {
        "n": len(paired_rows),
        "delta": round(sum(after_scores) / len(after_scores) - sum(before_scores) / len(before_scores), 4) if paired_rows else None,
        "mcnemar_exact_p": mcnemar_exact(before_scores, after_scores),
        "wins": sum(a > b for a, b in zip(after_scores, before_scores)),
        "losses": sum(a < b for a, b in zip(after_scores, before_scores)),
        "ties": sum(a == b for a, b in zip(after_scores, before_scores)),
    }
    result = {
        "experiment": "company_b_coder_prompt_ablation",
        "status": "complete" if len(paired_rows) == n else "partial_provider_errors",
        "split": "SELECTION",
        "input_policy": "gold extracted fields; isolates coder prompt and RAG",
        "rag": "same company-filtered top-5 retrieval for both prompts",
        "n_calls": 2 * n,
        "prompt_sha256": {k: hashlib.sha256(v.encode()).hexdigest() for k, v in prompts.items()},
        "summary": summary,
        "items": {k: rows for k, rows in outputs.items()},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary, "n_calls": 2 * n, "output": str(OUT)}, indent=2))


if __name__ == "__main__":
    main()
