# Architecture — n8n Multi-Agent Document Pipeline

## Overview

A multi-agent pipeline processes Tunisian accounting documents (invoices, receipts, purchase orders)
through five specialized LLM agents, orchestrated by n8n, backed by a FastAPI server, and
stored in SQLite + Qdrant.

## Agent Roles

| Agent | LLM Calls | Input | Output |
|-------|-----------|-------|--------|
| **Router** | 1 | raw document text/bytes | `doc_type`, `modality` |
| **Extractor** | 1 | document text (or image via vision) | structured fields (supplier, date, amounts, NIF) |
| **Coder** | 1 | extracted fields + RAG chunks | `account_code`, `cited_rule` |
| **Validator** | 1 | extracted fields (Python pre-check) | `errors[]`, `explanation`, `needs_review` |
| **Exception_Handler** | 1 | extracted + validation | `escalation_dossier` |

Each agent loads its system prompt from `skills/<company_id>/<agent>/v<NNN>.md`.

## Information Flow

```
User/UI
  │
  ▼ POST to n8n webhook
n8n Webhook
  │
  ▼ POST /route (FastAPI)
RouterAgent ──── load_skill() ──── LLMClient.call(role="agent")
  │
  ▼ POST /extract
ExtractorAgent ─ load_skill() ──── LLMClient.call(role="agent"|"vision")
  │
  ├─ pypdf (text PDF) or LLM vision (photo)
  │
  ▼ POST /code
CoderAgent ────── RAGEngine.search() ── QdrantClient ── SentenceTransformer
  │                                                      (paraphrase-multilingual-mpnet)
  ▼ POST /validate
ValidatorAgent ── Python checks (arithmetic, NIF, duplicate)
  │              ── LLMClient.call() for explanation
  │
  ▼ IF needs_review
  ├─ TRUE  → POST /handle → ExceptionHandlerAgent → POST /escalate
  └─ FALSE → POST /accept
  │
  ▼ Respond to n8n
  │
  ▼ SQLite traces.db
    (every step recorded with step, status, duration_ms, chunks, skill_version)
```

## Why Multi-Agent, Not a Single LLM Call?

1. **Separation of concerns**: Each agent is tuned for one narrow task. A single prompt
   doing routing + extraction + coding + validation would need to handle all failure modes.

2. **Independent retry**: n8n retries each agent node independently (×2). A monolithic call
   has no mid-pipeline recovery.

3. **Traceability**: Each agent writes a SQLite trace row with timing, output, and skill version.
   A monolithic call produces one opaque log.

4. **Skill versioning**: Agent prompts (skills) can be updated independently. v001 → v002
   for the Extractor doesn't affect the Router or Coder.

5. **RAG injection**: The Coder receives only the relevant chunks for its specific query.
   In a monolithic call, all context would compete.

6. **Evaluation**: Each agent has its own scorer (NEM for Extractor, binary for Coder,
   F-β for Validator). Disentangled agents make ablation straightforward.

## Components

- **FastAPI** (port 8000): Exposes exactly 10 REST endpoints. Handles all agent calls.
- **n8n** (port 5678): Visual workflow engine. Orchestrates the pipeline via HTTP calls.
- **SQLite** (`traces.db`): Append-only trace log for all pipeline events.
- **Qdrant** (`qdrant_local/`): Embedded vector store for accounting rules.
- **SentenceTransformer**: `paraphrase-multilingual-mpnet-base-v2` for multilingual embeddings.
- **React UI** (`./ui`): Cyberpunk dashboard polling FastAPI every 500ms.
- **run.py**: Starts all three services concurrently with 30s health-check timeouts.

## Skills Directory

```
skills/
  company_a/
    router/v001.md, v002.md (after prompt fix)
    extractor/v001.md, v002.md
    coder/v001.md
    validator/v001.md
    exception_handler/v001.md
  company_b/  (same structure)
```

## Data Flow for RAG

```
Coding rules markdown
  │
  ▼ rag.ingest (python3 -m rag.ingest --company_id=all)
FixedChunker (512 tok / 64 overlap) + SemanticChunker (headings, max 1024)
  │
  ▼ SentenceTransformer encode
QdrantClient.upsert (idempotent by chunk_id hash)
  │
  ▼ At inference: RAGEngine.search(query, top_k=5, filter=company_id)
  ▼ Top chunks injected into Coder system prompt
  ▼ Coder cites rule from chunks → CoderScorer validates citation
```
