"""
eval/retrieval_eval.py — Evaluate RAG retrieval quality (Recall@5, MRR@5).

Usage:
    python3 -m eval.retrieval_eval
"""

import json
import tempfile
from pathlib import Path

from rag.engine import RAGEngine
from rag.ingest import load_company_documents


def recall_at_k(retrieved_sources: list[str], expected_sources: list[str], k: int = 5) -> float:
    """Fraction of expected sources found in top-k retrieved results."""
    if not expected_sources:
        return 1.0
    top_k = retrieved_sources[:k]
    hits = sum(1 for s in expected_sources if any(s in r for r in top_k))
    return hits / len(expected_sources)


def mrr_at_k(retrieved_sources: list[str], expected_sources: list[str], k: int = 5) -> float:
    """Mean Reciprocal Rank: 1/rank of first relevant result in top-k."""
    if not expected_sources:
        return 1.0
    top_k = retrieved_sources[:k]
    for i, source in enumerate(top_k):
        if any(e in source for e in expected_sources):
            return 1.0 / (i + 1)
    return 0.0


def evaluate_company(company_id: str) -> dict:
    queries_file = Path("rag") / f"test_queries_{company_id}.json"
    if not queries_file.exists():
        print(f"  WARNING: {queries_file} not found, skipping.")
        return {"recall_at_5": None, "mrr_at_5": None, "n_queries": 0}

    with open(queries_file, encoding="utf-8") as f:
        queries = json.load(f)

    recalls, mrrs = [], []
    per_query = []
    documents = load_company_documents(company_id)
    with tempfile.TemporaryDirectory(prefix=f"docdesk_retrieval_{company_id}_") as temp:
        engine = RAGEngine(company_id=company_id, qdrant_path=temp)
        engine.ingest(documents, chunker_type="fixed", prune_company=True)
        chunk_count = engine.collection_size()
        for q in queries:
            query = q["query"]
            expected = q.get("expected_sources", [])
            results = engine.search(query, top_k=5)
            retrieved = [r["source"] for r in results]
            r5 = recall_at_k(retrieved, expected)
            m5 = mrr_at_k(retrieved, expected)
            recalls.append(r5)
            mrrs.append(m5)
            per_query.append({
                "query": query,
                "expected_sources": expected,
                "retrieved_sources": retrieved,
                "recall_at_5": r5,
                "mrr_at_5": m5,
            })
        engine.client.close()

    return {
        "recall_at_5": round(sum(recalls) / len(recalls), 4) if recalls else None,
        "mrr_at_5": round(sum(mrrs) / len(mrrs), 4) if mrrs else None,
        "n_queries": len(queries),
        "n_chunks": chunk_count,
        "sources": [document["source"] for document in documents],
        "per_query": per_query,
    }


def main():
    Path("eval/results").mkdir(parents=True, exist_ok=True)
    results = {}

    for company_id in ["company_a", "company_b"]:
        print(f"\n=== Evaluating RAG for {company_id} ===")
        r = evaluate_company(company_id)
        results[company_id] = r
        if r["recall_at_5"] is not None:
            print(f"  Recall@5: {r['recall_at_5']:.4f}")
            print(f"  MRR@5:    {r['mrr_at_5']:.4f}")
            print(f"  Queries:  {r['n_queries']}")

    # Write markdown report
    report_path = Path("eval/results/retrieval_eval.md")
    lines = [
        "# RAG Retrieval Evaluation\n",
        "Model: `paraphrase-multilingual-mpnet-base-v2`  ",
        "Chunker: FixedChunker (512 tokens, 64-token overlap); top-k = 5.\n",
        "| Company | Queries | Recall@5 | MRR@5 |",
        "|---------|---------|----------|-------|",
    ]
    for cid, r in results.items():
        if r["recall_at_5"] is not None:
            lines.append(f"| {cid} | {r['n_queries']} | {r['recall_at_5']:.4f} | {r['mrr_at_5']:.4f} |")
        else:
            lines.append(f"| {cid} | 0 | N/A | N/A |")

    lines += [
        "\n## Corpus and method",
        "",
        "Each company is evaluated in an isolated temporary Qdrant collection built from the visible chart of accounts and topic-level internal policy files. Hidden house rules and gold labels are excluded.",
        "",
    ]
    for cid, result in results.items():
        if result["recall_at_5"] is not None:
            lines.append(f"- **{cid}**: {result['n_chunks']} chunks from {', '.join(result['sources'])}.")

    lines += [
        "\n## Comment",
        "",
        "Results above are from real RAG runs. Higher Recall@5 indicates more relevant rules",
        "are retrieved in the top 5 results. MRR@5 measures how early the first relevant",
        "result appears (1.0 = always first, 0.5 = always second, etc.).",
        "",
        "Recall@5 is source-level: a query scores when its labeled policy source appears in the first five results. MRR@5 rewards an earlier first relevant source.",
    ]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    (report_path.parent / "retrieval_eval.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nWrote {report_path}")


if __name__ == "__main__":
    main()
