"""rag/engine.py — RAGEngine: Qdrant-backed semantic search for accounting rules."""

import hashlib
from pathlib import Path
from typing import Optional

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance, VectorParams, PointStruct, Filter,
        FieldCondition, MatchValue, PointIdsList,
    )
    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer
    ST_AVAILABLE = True
except ImportError:
    ST_AVAILABLE = False

from rag.chunkers import FixedChunker, SemanticChunker

COLLECTION_NAME = "accounting_rules"
EMBEDDING_MODEL = "paraphrase-multilingual-mpnet-base-v2"
VECTOR_SIZE = 768  # paraphrase-multilingual-mpnet-base-v2 output size


def _chunk_id_to_uint(chunk_id: str) -> int:
    """Convert a hex chunk_id string to a positive integer for Qdrant."""
    return int(chunk_id[:15], 16)


class RAGEngine:
    """
    Qdrant-embedded RAG engine for accounting rules.

    Each company's data is isolated by company_id filter on the payload.
    Ingestion is idempotent: re-ingesting the same documents produces no duplicates.
    """

    def __init__(
        self,
        company_id: str,
        qdrant_path: str = "./qdrant_local",
    ) -> None:
        self.company_id = company_id
        self.qdrant_path = qdrant_path

        if not QDRANT_AVAILABLE:
            raise ImportError("qdrant-client is not installed. Run: pip install qdrant-client")
        if not ST_AVAILABLE:
            raise ImportError("sentence-transformers is not installed.")

        self.client = QdrantClient(path=qdrant_path)
        self.model = SentenceTransformer(EMBEDDING_MODEL)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """Create collection if it doesn't exist."""
        existing = [c.name for c in self.client.get_collections().collections]
        if COLLECTION_NAME not in existing:
            self.client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )

    def ingest(
        self,
        documents: list[dict],
        chunker_type: str = "fixed",
        prune_company: bool = False,
    ) -> int:
        """
        Ingest documents into Qdrant. Idempotent: upsert by chunk_id.

        Args:
            documents: list of {"text": str, "source": str}
            chunker_type: "fixed" or "semantic"

        Returns:
            Number of points upserted.
        """
        chunker = FixedChunker() if chunker_type == "fixed" else SemanticChunker()
        points = []
        legacy_point_ids: set[int] = set()

        for doc in documents:
            text = doc.get("text", "")
            source = doc.get("source", "unknown")
            chunks = chunker.chunk(text, source)

            for chunk in chunks:
                chunk_text = chunk.get("text", "").strip()
                if not chunk_text:
                    continue
                embedding = self.model.encode(chunk_text).tolist()
                # The old ID was derived from source/offset only. Since both
                # tenants use filenames such as coding_rules.md, one company's
                # upsert could overwrite the other's point in the shared
                # collection. Namespace the stable chunk hash by tenant.
                raw_chunk_id = chunk["chunk_id"]
                scoped_chunk_id = hashlib.sha256(
                    f"{self.company_id}:{raw_chunk_id}".encode("utf-8")
                ).hexdigest()[:16]
                point_id = _chunk_id_to_uint(scoped_chunk_id)
                legacy_point_ids.add(_chunk_id_to_uint(raw_chunk_id))
                payload = {
                    "text": chunk_text,
                    "company_id": self.company_id,
                    "source": source,
                    "chunk_id": scoped_chunk_id,
                }
                points.append(PointStruct(id=point_id, vector=embedding, payload=payload))

        if not points:
            return 0

        existing = self.client.retrieve(
            collection_name=COLLECTION_NAME,
            ids=[point.id for point in points],
            with_payload=False,
            with_vectors=False,
        )
        self.client.upsert(collection_name=COLLECTION_NAME, points=points)
        # Remove pre-tenant-namespace points created by the previous version.
        # Re-ingesting all companies repopulates them under collision-safe IDs.
        if legacy_point_ids:
            self.client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=PointIdsList(points=sorted(legacy_point_ids)),
            )
        if prune_company:
            desired_ids = {point.id for point in points}
            stale_ids: list[int] = []
            offset = None
            while True:
                page, offset = self.client.scroll(
                    collection_name=COLLECTION_NAME,
                    scroll_filter=Filter(must=[
                        FieldCondition(key="company_id", match=MatchValue(value=self.company_id))
                    ]),
                    limit=256,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
                )
                stale_ids.extend(point.id for point in page if point.id not in desired_ids)
                if offset is None:
                    break
            if stale_ids:
                self.client.delete(
                    collection_name=COLLECTION_NAME,
                    points_selector=PointIdsList(points=stale_ids),
                )
        return max(0, len(points) - len(existing))

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Search for relevant chunks, filtered by company_id.

        Returns:
            list of {"text": str, "score": float, "chunk_id": str, "source": str}
        """
        query_vector = self.model.encode(query).tolist()

        try:
            # New Qdrant API (>=1.10)
            results = self.client.query_points(
                collection_name=COLLECTION_NAME,
                query=query_vector,
                limit=top_k,
                query_filter=Filter(
                    must=[
                        FieldCondition(
                            key="company_id",
                            match=MatchValue(value=self.company_id),
                        )
                    ]
                ),
                with_payload=True,
            )
            points = results.points if hasattr(results, 'points') else results
        except (AttributeError, TypeError):
            # Fallback: older Qdrant API
            results = self.client.search(
                collection_name=COLLECTION_NAME,
                query_vector=query_vector,
                limit=top_k,
                query_filter=Filter(
                    must=[
                        FieldCondition(
                            key="company_id",
                            match=MatchValue(value=self.company_id),
                        )
                    ]
                ),
                with_payload=True,
            )
            points = results

        return [
            {
                "text": r.payload.get("text", ""),
                "score": r.score if hasattr(r, 'score') else 0.0,
                "chunk_id": r.payload.get("chunk_id", ""),
                "source": r.payload.get("source", ""),
            }
            for r in points
        ]

    def collection_size(self) -> int:
        """Return total number of points in the collection."""
        info = self.client.get_collection(COLLECTION_NAME)
        return info.points_count

    def health_check(self) -> bool:
        """Return True if Qdrant is accessible."""
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False
