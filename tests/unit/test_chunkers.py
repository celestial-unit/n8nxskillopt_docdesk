# Feature: n8n-multiagent-doc-pipeline, Chunker unit tests
"""
tests/unit/test_chunkers.py — Unit tests for FixedChunker and SemanticChunker.

Tests:
- FixedChunker: no chunk exceeds 512 tokens; overlap = 64 tokens; unique chunk IDs
- SemanticChunker: splits on heading boundaries; no chunk exceeds 1024 tokens
"""
import hashlib
import pytest

from rag.chunkers import FixedChunker, SemanticChunker, _tokenize


# ── Helpers ───────────────────────────────────────────────────────────────────

def _long_text(n_words: int = 2000) -> str:
    """Generate a long repeating text."""
    word = "comptabilité "
    return (word * n_words).strip()


def _markdown_with_headings() -> str:
    return """\
# Chapitre 1: Introduction

Texte d'introduction du chapitre 1. Lorem ipsum dolor sit amet.

## Section 1.1: Comptes de charges

Les comptes de charges sont codifiés selon la classe 6 du SCE.

### Sous-section 1.1.1: Achats

Les achats de marchandises sont enregistrés au compte 601000.

## Section 1.2: Comptes de TVA

La TVA est enregistrée au compte 43600.

# Chapitre 2: Règles de codification

Texte du chapitre 2 sur les règles de codification comptable.

## Section 2.1: Règles générales

Chaque document doit être associé à un code comptable valide.
"""


# ── FixedChunker tests ────────────────────────────────────────────────────────

class TestFixedChunker:

    def test_empty_text_returns_empty(self):
        fc = FixedChunker()
        chunks = fc.chunk("", "source.md")
        assert chunks == []

    def test_short_text_single_chunk(self):
        fc = FixedChunker()
        chunks = fc.chunk("Bonjour monde.", "source.md")
        assert len(chunks) == 1
        assert chunks[0]["source"] == "source.md"
        assert "chunk_id" in chunks[0]

    def test_no_chunk_exceeds_512_tokens(self):
        fc = FixedChunker(chunk_size=512, overlap=64)
        text = _long_text(3000)
        chunks = fc.chunk(text, "long.md")
        assert len(chunks) > 1, "Long text should produce multiple chunks"
        for c in chunks:
            n_tokens = len(_tokenize(c["text"]))
            assert n_tokens <= 512, (
                f"Chunk has {n_tokens} tokens, expected ≤ 512"
            )

    def test_chunk_ids_are_unique(self):
        fc = FixedChunker(chunk_size=512, overlap=64)
        text = _long_text(3000)
        chunks = fc.chunk(text, "test.md")
        ids = [c["chunk_id"] for c in chunks]
        assert len(ids) == len(set(ids)), "Chunk IDs must be unique"

    def test_overlap_between_consecutive_chunks(self):
        """Consecutive chunks share ~64 tokens (the overlap window)."""
        fc = FixedChunker(chunk_size=512, overlap=64)
        text = _long_text(3000)
        chunks = fc.chunk(text, "test.md")
        if len(chunks) < 2:
            pytest.skip("Not enough chunks to test overlap")

        # end_token of chunk[i] should overlap with start_token of chunk[i+1]
        for i in range(len(chunks) - 1):
            end_i = chunks[i]["end_token"]
            start_next = chunks[i + 1]["start_token"]
            overlap = end_i - start_next
            assert overlap == 64, (
                f"Expected 64-token overlap between chunk {i} and {i+1}, "
                f"got {overlap} (end={end_i}, start={start_next})"
            )

    def test_chunk_fields_present(self):
        fc = FixedChunker()
        chunks = fc.chunk("Some text for testing.", "doc.md")
        for c in chunks:
            assert "text" in c
            assert "chunk_id" in c
            assert "source" in c
            assert "start_token" in c
            assert "end_token" in c


# ── SemanticChunker tests ─────────────────────────────────────────────────────

class TestSemanticChunker:

    def test_empty_text_returns_empty(self):
        sc = SemanticChunker()
        chunks = sc.chunk("", "source.md")
        assert chunks == []

    def test_short_text_single_chunk(self):
        sc = SemanticChunker()
        chunks = sc.chunk("Texte sans titres.", "source.md")
        assert len(chunks) >= 1

    def test_splits_on_heading_boundaries(self):
        """With very small max_tokens, headings force multiple chunks."""
        sc = SemanticChunker(max_tokens=50)  # Very small limit forces splits
        text = _markdown_with_headings()
        chunks = sc.chunk(text, "rules.md")
        assert len(chunks) >= 2, "Should produce multiple chunks from a document with headings and small max_tokens"

    def test_no_chunk_exceeds_1024_tokens(self):
        sc = SemanticChunker(max_tokens=1024)
        # Use very long content under each heading
        text = ""
        for i in range(5):
            text += f"## Section {i}\n\n" + ("mot " * 500) + "\n\n"
        chunks = sc.chunk(text, "long.md")
        for c in chunks:
            n_tokens = len(_tokenize(c["text"]))
            assert n_tokens <= 1024, (
                f"Chunk has {n_tokens} tokens, expected ≤ 1024"
            )

    def test_chunk_ids_are_unique(self):
        sc = SemanticChunker()
        text = _markdown_with_headings()
        chunks = sc.chunk(text, "test.md")
        ids = [c["chunk_id"] for c in chunks]
        assert len(ids) == len(set(ids)), "Chunk IDs must be unique"

    def test_chunk_fields_present(self):
        sc = SemanticChunker()
        text = _markdown_with_headings()
        chunks = sc.chunk(text, "doc.md")
        for c in chunks:
            assert "text" in c
            assert "chunk_id" in c
            assert "source" in c
            assert "heading" in c
