"""
rag/ingest.py — CLI ingestion script for loading company rules into Qdrant.

Usage:
    python3 -m rag.ingest --company_id=company_a [--chunker_type=fixed|semantic]
"""

import argparse
from pathlib import Path

from rag.engine import RAGEngine


def load_company_documents(company_id: str) -> list[dict]:
    """Load only company-visible accounting policy and chart documents.

    The granular knowledge-base files keep retrieval relevance measurable at
    the topic level. Hidden house rules and generated gold labels are excluded.
    """
    data_dir = Path("data") / company_id
    documents = []
    chart_path = data_dir / "chart_of_accounts.md"
    if chart_path.exists():
        documents.append({"text": chart_path.read_text(encoding="utf-8"), "source": chart_path.name})
    kb_dir = data_dir / "knowledge_base"
    if kb_dir.exists():
        for path in sorted(kb_dir.rglob("*.md")):
            documents.append({"text": path.read_text(encoding="utf-8"), "source": path.name})
    else:
        # Backward-compatible fallback for older project checkouts.
        rules_path = data_dir / "coding_rules.md"
        if rules_path.exists():
            documents.append({"text": rules_path.read_text(encoding="utf-8"), "source": rules_path.name})
    return documents


def ingest_company(company_id: str, chunker_type: str = "fixed") -> int:
    """Load company-visible policy and chart documents into Qdrant."""
    documents = load_company_documents(company_id)
    for document in documents:
        print(f"  Loaded {document['source']} ({len(document['text'])} chars)")

    if not documents:
        print("No documents to ingest.")
        return 0

    engine = RAGEngine(company_id=company_id)
    n = engine.ingest(documents, chunker_type=chunker_type, prune_company=True)
    print(f"  Upserted {n} chunks for {company_id} (chunker={chunker_type})")
    return n


def main():
    parser = argparse.ArgumentParser(description="Ingest company rules into Qdrant RAG.")
    parser.add_argument("--company_id", required=True, choices=["company_a", "company_b", "all"])
    parser.add_argument("--chunker_type", default="fixed", choices=["fixed", "semantic"])
    args = parser.parse_args()

    if args.company_id == "all":
        for cid in ["company_a", "company_b"]:
            print(f"\n=== Ingesting {cid} ===")
            ingest_company(cid, args.chunker_type)
    else:
        print(f"\n=== Ingesting {args.company_id} ===")
        ingest_company(args.company_id, args.chunker_type)


if __name__ == "__main__":
    main()
