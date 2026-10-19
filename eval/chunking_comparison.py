"""Compare fixed and heading-based chunks on the same RAG query sets."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from eval.retrieval_eval import recall_at_k, mrr_at_k
from rag.engine import RAGEngine
from rag.ingest import load_company_documents

ROOT = Path(__file__).resolve().parents[1]


def company_docs(company_id: str) -> list[dict]:
    return load_company_documents(company_id)


def main() -> None:
    report: dict = {
        "embedding_model": "paraphrase-multilingual-mpnet-base-v2",
        "top_k": 5,
        "metrics": "source-level Recall@5 and MRR@5; same queries, corpus, and model",
        "chunkers": {},
    }
    queries_by_company = {
        cid: json.loads((ROOT / "rag" / f"test_queries_{cid}.json").read_text(encoding="utf-8"))
        for cid in ("company_a", "company_b")
    }
    for chunker in ("fixed", "semantic"):
        report["chunkers"][chunker] = {}
        for company_id, queries in queries_by_company.items():
            with tempfile.TemporaryDirectory(prefix=f"docdesk_{chunker}_{company_id}_") as temp:
                engine = RAGEngine(company_id=company_id, qdrant_path=temp)
                n_chunks = engine.ingest(company_docs(company_id), chunker_type=chunker)
                recalls, mrrs = [], []
                per_query = []
                for q in queries:
                    retrieved = engine.search(q["query"], top_k=5)
                    sources = [r["source"] for r in retrieved]
                    recall = recall_at_k(sources, q.get("expected_sources", []), k=5)
                    mrr = mrr_at_k(sources, q.get("expected_sources", []), k=5)
                    recalls.append(recall)
                    mrrs.append(mrr)
                    per_query.append({"query": q["query"], "recall_at_5": recall, "mrr_at_5": mrr})
                report["chunkers"][chunker][company_id] = {
                    "n_queries": len(queries),
                    "n_chunks": n_chunks,
                    "recall_at_5": round(sum(recalls) / len(recalls), 4),
                    "mrr_at_5": round(sum(mrrs) / len(mrrs), 4),
                    "per_query": per_query,
                }
                engine.client.close()
                print(f"{chunker} / {company_id}: {n_chunks} chunks, Recall@5={report['chunkers'][chunker][company_id]['recall_at_5']:.3f}, MRR@5={report['chunkers'][chunker][company_id]['mrr_at_5']:.3f}", flush=True)
    out = ROOT / "eval" / "results" / "chunking_comparison.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
