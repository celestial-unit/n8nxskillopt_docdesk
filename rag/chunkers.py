"""
rag/chunkers.py — Text chunking strategies for RAG ingestion.

FixedChunker: 512 tokens per chunk, 64-token overlap (tiktoken cl100k_base).
SemanticChunker: split on markdown headings, max 1024 tokens per chunk.
"""

import hashlib
import re
from typing import Optional

try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    TIKTOKEN_AVAILABLE = True
except Exception:
    TIKTOKEN_AVAILABLE = False
    _enc = None


def _tokenize(text: str) -> list[int]:
    if TIKTOKEN_AVAILABLE and _enc:
        return _enc.encode(text)
    # Fallback: approximate by whitespace words (4 chars ≈ 1 token)
    return list(range(max(1, len(text) // 4)))


def _detokenize(tokens: list[int]) -> str:
    if TIKTOKEN_AVAILABLE and _enc:
        return _enc.decode(tokens)
    return ""


def _make_chunk_id(source: str, discriminator: str) -> str:
    raw = f"{source}\x00{discriminator}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class FixedChunker:
    """
    Token-based sliding-window chunker.
    chunk_size=512 tokens, overlap=64 tokens.
    """

    def __init__(self, chunk_size: int = 512, overlap: int = 64) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str, source: str) -> list[dict]:
        """
        Split text into fixed-size token chunks with overlap.

        Returns list of:
            {text, chunk_id, source, start_token, end_token}
        """
        tokens = _tokenize(text)
        if not tokens:
            return []

        chunks = []
        start = 0
        step = self.chunk_size - self.overlap

        while start < len(tokens):
            end = min(start + self.chunk_size, len(tokens))
            chunk_tokens = tokens[start:end]

            if TIKTOKEN_AVAILABLE and _enc:
                chunk_text = _detokenize(chunk_tokens)
            else:
                # Fallback: extract text by character approximation
                char_start = start * 4
                char_end = min(end * 4, len(text))
                chunk_text = text[char_start:char_end]

            chunk_id = _make_chunk_id(source, f"{start}:{end}")
            chunks.append({
                "text": chunk_text,
                "chunk_id": chunk_id,
                "source": source,
                "start_token": start,
                "end_token": end,
            })

            if end >= len(tokens):
                break
            start += step

        return chunks


HEADING_RE = re.compile(r"^(#{1,6}\s+.+)$", re.MULTILINE)


class SemanticChunker:
    """
    Markdown heading-based semantic chunker.
    Splits on headings (#, ##, ###, ...) and respects max_tokens limit.
    """

    def __init__(self, max_tokens: int = 1024) -> None:
        self.max_tokens = max_tokens

    def chunk(self, text: str, source: str) -> list[dict]:
        """
        Split text on markdown headings, flushing when chunk exceeds max_tokens.

        Returns list of:
            {text, chunk_id, heading, source}
        """
        # Split text on headings, keeping the headings as separators
        parts = HEADING_RE.split(text)
        # parts alternates: [pre-content, heading1, content1, heading2, content2, ...]

        chunks: list[dict] = []
        buffer = ""
        current_heading = ""
        flush_count = 0

        def flush(buf: str, heading: str) -> None:
            nonlocal flush_count
            buf = buf.strip()
            if not buf:
                return
            cid = _make_chunk_id(source, f"{heading}:{flush_count}")
            flush_count += 1
            chunks.append({
                "text": buf,
                "chunk_id": cid,
                "heading": heading,
                "source": source,
            })

        i = 0
        while i < len(parts):
            part = parts[i]
            # Check if this part is a heading
            if HEADING_RE.match(part.strip()):
                # It's a heading — save current buffer if accumulating
                candidate = (buffer + "\n" + part).strip()
                if len(_tokenize(candidate)) > self.max_tokens and buffer.strip():
                    # Flush current buffer before adding heading
                    flush(buffer, current_heading)
                    buffer = part
                    current_heading = part.strip()
                else:
                    buffer = candidate
                    current_heading = part.strip()
            else:
                # It's content — append to buffer
                candidate = (buffer + "\n" + part).strip()
                if len(_tokenize(candidate)) > self.max_tokens and buffer.strip():
                    flush(buffer, current_heading)
                    buffer = part
                else:
                    buffer = candidate
            i += 1

        # Flush remaining buffer
        flush(buffer, current_heading)

        # If no chunks produced (no headings), fall back to fixed chunking
        if not chunks:
            fc = FixedChunker(chunk_size=self.max_tokens, overlap=0)
            for c in fc.chunk(text, source):
                chunks.append({
                    "text": c["text"],
                    "chunk_id": c["chunk_id"],
                    "heading": "",
                    "source": source,
                })

        return chunks
