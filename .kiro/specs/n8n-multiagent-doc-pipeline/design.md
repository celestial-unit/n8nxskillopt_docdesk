# Design Document — n8n Multi-Agent Document Pipeline

## Overview

Ce système est un pipeline multi-agents de traitement de documents comptables (factures, reçus, bons de commande) pour des entreprises tunisiennes fictives. Un document soumis via l'interface React traverse cinq agents spécialisés orchestrés par n8n : **Router → Extractor → Coder (RAG) → Validator → Exception_Handler**. Chaque agent effectue exactement un appel LLM et enregistre une trace complète dans SQLite. Le backend FastAPI expose les endpoints consommés par n8n et l'interface utilisateur. Qdrant embarqué stocke les embeddings des règles comptables par entreprise.

**Objectif principal** : démonstrateur fonctionnel avec résultats chiffrés issus d'exécutions réelles, démarrant via `python run.py` sans Docker.

---

## Architecture

### Diagramme ASCII

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           python run.py                                      │
│   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────────┐   │
│   │   FastAPI :8000  │   │    n8n :5678     │   │   React UI :3000     │   │
│   │   (uvicorn)      │   │   (npx n8n@1)    │   │   (pnpm dev)         │   │
│   └────────┬─────────┘   └────────┬─────────┘   └──────────┬───────────┘   │
└────────────┼────────────────────── ┼─────────────────────── ┼───────────────┘
             │                       │                         │
             │  POST /route,extract, │  Webhook → nodes        │  upload / poll
             │  code,validate,...    │  → HTTP calls           │  /trace every 500ms
             │◄──────────────────────┤                         │
             │                       │                         │
             ▼                       ▼                         ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                           Pipeline Internals                                │
│                                                                              │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  Router  │→ │  Extractor   │→ │    Coder     │→ │   Validator      │   │
│  │  Agent   │  │   Agent      │  │  Agent+RAG   │  │   Agent          │   │
│  └──────────┘  └──────────────┘  └──────┬───────┘  └────────┬─────────┘   │
│       │               │                 │                     │             │
│       │               │          ┌──────┴──────┐             │             │
│       │               │          │  RAG Engine │             ▼             │
│       │               │          │  (Qdrant)   │    needs_review?          │
│       │               │          └──────┬──────┘         ┌──┴──┐          │
│       │               │                 │                 │     │          │
│       │               │                 │              Yes│     │No        │
│       │               │                 │                 ▼     ▼          │
│       │               │                 │      ┌──────────┐  ┌────────┐   │
│       │               │                 │      │Exception │  │ Accept │   │
│       │               │                 │      │ Handler  │  │        │   │
│       │               │                 │      └────┬─────┘  └───┬────┘   │
│       │               │                 │           │             │        │
│  ─────┴───────────────┴─────────────────┴───────────┴─────────────┴────── │
│                              SQLite Traces                                  │
│  ─────────────────────────────────────────────────────────────────────────  │
│       LLM_Client (Azure AI Foundry / OpenAI-compatible, temp=0)             │
│       DEMO_CACHE=1 → .cache/ (SHA-256 keyed pickle)                        │
└────────────────────────────────────────────────────────────────────────────┘
```

### Flux de données n8n

```
Webhook
  │
  ├─► Router Node (POST /route, retries=2)
  │       │
  │       ▼
  │   Switch(modality)
  │       │
  │       ├─ text ──► Extractor Node (POST /extract, retries=2)
  │       └─ photo ─► [Vision transcription] ─► Extractor Node
  │                       │
  │                       ▼
  │                   Coder Node (POST /code, retries=2)
  │                       │
  │                       ▼
  │                   Validator Node (POST /validate, retries=2)
  │                       │
  │                   IF(needs_review)
  │                       │
  │           ┌───────────┴────────────┐
  │           │ true                   │ false
  │           ▼                        ▼
  │   Exception_Handler Node      Accept Node
  │   (POST /handle, retries=2)   (POST /accept)
  │           │                        │
  │           ▼                        │
  │       Escalate Node                │
  │   (POST /escalate)                 │
  │           │                        │
  │           └──────────┬─────────────┘
  │                       ▼
  │                   Respond Node
  │
  └─ Error ──► Fail Node (POST /fail) ──► Respond Node
```

---

## Components and Interfaces

### 1. `agents/llm_client.py` — LLMClient

Point d'entrée unique vers les LLMs.

```python
class MissingDeploymentError(Exception):
    """Raised when the deployment env var for a given role is missing."""
    pass

class LLMClient:
    ROLE_DEPLOYMENT_MAP = {
        "agent":     "AGENT_DEPLOYMENT",
        "vision":    "VISION_DEPLOYMENT",
        "optimizer": "OPTIMIZER_DEPLOYMENT",
    }

    def __init__(self):
        # Load .env via python-dotenv
        # Determine provider: Azure (AZURE_ENDPOINT) or OpenAI-compatible (OPENAI_BASE_URL)
        # Initialize openai.AzureOpenAI or openai.OpenAI client with temperature locked at 0

    def call(
        self,
        role: str,                # "agent" | "vision" | "optimizer"
        system_prompt: str,
        user_message: str,
        image_b64: str | None = None,
    ) -> str:
        # 1. Resolve deployment name from ROLE_DEPLOYMENT_MAP; raise MissingDeploymentError if missing
        # 2. Build cache key: sha256(role + system_prompt + user_message + (image_b64 or ""))
        # 3. If DEMO_CACHE=1 and cache hit: return pickle.loads(cache_file)
        # 4. Call LLM with temperature=0
        # 5. If DEMO_CACHE=1: persist response to .cache/<hash>.pkl
        # 6. Return response text
```

**Contrat** :
- `call(role, system, user, image_b64=None) -> str`
- Lève `MissingDeploymentError` si la variable de déploiement est absente
- Cache disque dans `.cache/<sha256>.pkl` quand `DEMO_CACHE=1`
- Temperature toujours = 0, sans exception

---

### 2. `agents/router_agent.py` — RouterAgent

```python
class RouterAgent:
    def run(self, input: dict, company_id: str) -> dict:
        # input: {"file_path": str, "file_bytes_b64": str | None}
        # Loads skill: skills/<company_id>/router/v<NNN>.md
        # One LLM call (role="agent")
        # Returns:
        return {
            "doc_type":      str,   # "invoice" | "receipt" | "purchase_order"
            "modality":      str,   # "text" | "photo"
            "skill_version": str,   # e.g. "v001"
        }
```

---

### 3. `agents/extractor_agent.py` — ExtractorAgent

```python
class ExtractorAgent:
    def run(self, input: dict, company_id: str) -> dict:
        # input: {"text": str, "doc_type": str}
        # One LLM call (role="agent" for text, role="vision" for photo with image_b64)
        # Returns:
        return {
            "supplier":       str,
            "date":           str,        # dd/mm/yyyy
            "number":         str,
            "lines":          list[dict],  # [{description, htva, tva_rate, tva, ttc}]
            "htva":           float,
            "tva":            float,
            "ttc":            float,
            "timbre_fiscal":  float,
            "nif":            str,         # XXXXXXXX/X/XXX/XXX
            "skill_version":  str,
        }
```

---

### 4. `agents/coder_agent.py` — CoderAgent

```python
class CoderAgent:
    def run(self, input: dict, company_id: str) -> dict:
        # input: {"extracted": dict, "doc_type": str}
        # 1. RAGEngine.search(query, top_k=5) filtered by company_id
        # 2. One LLM call (role="agent") with retrieved chunks injected into prompt
        # Returns:
        return {
            "account_code":  str,   # [A-Z0-9]{6} for A, [0-9]{4}-[A-Z]{2}[0-9]{3} for B
            "cited_rule":    str,   # ≥10 chars substring of skill or any retrieved chunk
            "chunks":        list[dict],  # [{text, score, chunk_id}]
            "skill_version": str,
        }
```

---

### 5. `agents/validator_agent.py` — ValidatorAgent

```python
class ValidatorAgent:
    def run(self, input: dict, company_id: str) -> dict:
        # input: {"extracted": dict, "doc_id": str}
        # Phase 1 — Python deterministic checks (no LLM):
        #   a. Arithmetic: abs(htva + tva - ttc) <= 0.001
        #   b. NIF presence: nif is not None and nif != ""
        #   c. Duplicate ID: check SQLite for existing doc_id
        # Phase 2 — One LLM call (role="agent") for 1-sentence explanation
        # Returns:
        return {
            "valid":         bool,
            "errors":        list[str],   # e.g. ["arithmetic_mismatch"]
            "explanation":   str,         # 1 sentence from LLM
            "needs_review":  bool,        # True if any error detected
            "skill_version": str,
        }
```

---

### 6. `agents/exception_handler_agent.py` — ExceptionHandlerAgent

```python
class ExceptionHandlerAgent:
    def run(self, input: dict, company_id: str) -> dict:
        # input: {"extracted": dict, "validation": dict, "doc_id": str}
        # One LLM call (role="agent")
        # Returns:
        return {
            "escalation_dossier": dict,  # {summary, errors, recommended_action, contact}
            "skill_version":      str,
        }
```

---

### 7. `rag/engine.py` — RAGEngine

```python
class RAGEngine:
    def __init__(self, company_id: str, qdrant_path: str = "./qdrant_local"):
        # QdrantClient(path=qdrant_path)
        # SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")
        # Collection name: "accounting_rules"

    def ingest(self, documents: list[dict], chunker_type: str = "fixed") -> int:
        # Returns number of newly upserted chunks (0 if all existed)
        # Idempotent: upsert by chunk_id (deterministic hash of company_id+source+offset)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        # Filter by payload.company_id == self.company_id
        # Returns: [{text, score, chunk_id, source}]
```

---

### 8. `rag/chunkers.py` — Chunkers

```python
class FixedChunker:
    """512 tokens per chunk, 64 token overlap."""
    def chunk(self, text: str, source: str) -> list[dict]:
        # Returns: [{text, start_token, end_token, source}]

class SemanticChunker:
    """Split on markdown headings (##, ###), max 1024 tokens per chunk."""
    def chunk(self, text: str, source: str) -> list[dict]:
        # Returns: [{text, heading, source}]
```

---

### 9. `api/main.py` — FastAPI Application

```python
# Endpoints:
POST /route       → RouterAgent.run()
POST /extract     → ExtractorAgent.run()
POST /code        → CoderAgent.run()
POST /validate    → ValidatorAgent.run()
POST /handle      → ExceptionHandlerAgent.run()
POST /accept      → record ACCEPTED decision in SQLite
POST /escalate    → record ESCALATED decision in SQLite
POST /fail        → record FAILED status in SQLite

GET  /trace/{id}  → return all trace rows for doc_id
GET  /health      → check Qdrant + SQLite + LLM_Client reachability
```

Toutes les routes POST acceptent `application/json`. CORS activé pour toutes les origines (`*`). Chaque handler écrit une trace dans SQLite avant de retourner.

---

### 10. `api/db.py` — SQLite Trace Store

```python
class TraceStore:
    def __init__(self, db_path: str = "./traces.db"):
        # CREATE TABLE IF NOT EXISTS traces (...)

    def write(self, trace: TraceEvent) -> None: ...
    def get_by_doc_id(self, doc_id: str) -> list[TraceEvent]: ...
    def doc_id_exists(self, doc_id: str) -> bool: ...
```

---

### 11. `run.py` — Entry Point

```python
# Starts three processes concurrently:
# 1. uvicorn api.main:app --port 8000
# 2. npx n8n@<pinned_version> (sets N8N_PORT=5678)
# 3. pnpm dev (cwd=./ui) OR streamlit run streamlit_app.py if ./ui absent
# Each process has a 30s startup health check timeout.
# On failure: print which component failed, terminate all, exit(1).
```

---

## Data Models

### Pydantic Models (`api/models.py`)

```python
from pydantic import BaseModel, Field
from typing import Optional

# ── Request bodies ────────────────────────────────────────────────────────────

class RouteRequest(BaseModel):
    doc_id:      str
    company_id:  str
    file_b64:    str            # base64-encoded file bytes
    filename:    str

class ExtractRequest(BaseModel):
    doc_id:     str
    company_id: str
    text:       str             # extracted text or vision transcript
    doc_type:   str

class CodeRequest(BaseModel):
    doc_id:     str
    company_id: str
    extracted:  dict
    doc_type:   str

class ValidateRequest(BaseModel):
    doc_id:     str
    company_id: str
    extracted:  dict

class HandleRequest(BaseModel):
    doc_id:     str
    company_id: str
    extracted:  dict
    validation: dict

class AcceptRequest(BaseModel):
    doc_id:     str
    company_id: str

class EscalateRequest(BaseModel):
    doc_id:     str
    company_id: str
    dossier:    dict

class FailRequest(BaseModel):
    doc_id:     str
    company_id: str
    error:      str

# ── Response bodies ───────────────────────────────────────────────────────────

class RouteResponse(BaseModel):
    doc_id:        str
    doc_type:      str          # "invoice" | "receipt" | "purchase_order"
    modality:      str          # "text" | "photo"
    skill_version: str
    trace_id:      int

class ExtractResponse(BaseModel):
    doc_id:        str
    supplier:      str
    date:          str
    number:        str
    lines:         list[dict]
    htva:          float
    tva:           float
    ttc:           float
    timbre_fiscal: float
    nif:           str
    skill_version: str
    trace_id:      int

class CodeResponse(BaseModel):
    doc_id:        str
    account_code:  str
    cited_rule:    str
    chunks:        list[dict]
    skill_version: str
    trace_id:      int

class ValidateResponse(BaseModel):
    doc_id:        str
    valid:         bool
    errors:        list[str]
    explanation:   str
    needs_review:  bool
    skill_version: str
    trace_id:      int

class HandleResponse(BaseModel):
    doc_id:             str
    escalation_dossier: dict
    skill_version:      str
    trace_id:           int

class HealthResponse(BaseModel):
    status:     str             # "ok" | "degraded"
    components: dict[str, str]  # {"qdrant": "ok", "sqlite": "ok", "llm": "ok"}

# ── Internal / Trace ──────────────────────────────────────────────────────────

class TraceEvent(BaseModel):
    id:            Optional[int] = None
    doc_id:        str
    step:          str          # "route" | "extract" | "code" | "validate" | "handle" | ...
    status:        str          # "success" | "error" | "cached"
    duration_ms:   int
    output_json:   str          # JSON-serialized agent output
    chunks_json:   str          # JSON-serialized retrieved chunks with scores
    skill_version: str
    timestamp:     str          # ISO 8601

# ── Gold / Evaluation ─────────────────────────────────────────────────────────

class GoldDocument(BaseModel):
    doc_id:          str
    doc_type:        str
    fields:          dict       # ground truth extracted fields
    account_code:    str
    injected_errors: list[str]  # [] or one of ["duplicate_id","arithmetic_mismatch","missing_nif"]
    company_id:      str
    split:           str        # "train" | "selection" | "test"
```

### SQLite Schema

```sql
CREATE TABLE IF NOT EXISTS traces (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id        TEXT    NOT NULL,
    step          TEXT    NOT NULL,
    status        TEXT    NOT NULL,
    duration_ms   INTEGER NOT NULL,
    output_json   TEXT    NOT NULL,
    chunks_json   TEXT    NOT NULL DEFAULT '[]',
    skill_version TEXT    NOT NULL,
    timestamp     TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_traces_doc_id ON traces(doc_id);
```

---

## File Layout

```
final_dlexam/
├── run.py                          # Entry point — starts FastAPI + n8n + UI
├── .env                            # AZURE_ENDPOINT, AZURE_API_KEY, AGENT_DEPLOYMENT, ...
├── requirements.txt                # Python dependencies
│
├── api/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app, CORS, all 10 endpoints
│   ├── models.py                   # Pydantic request/response models
│   └── db.py                       # SQLite TraceStore
│
├── agents/
│   ├── __init__.py
│   ├── llm_client.py               # LLMClient, MissingDeploymentError
│   ├── router_agent.py             # RouterAgent
│   ├── extractor_agent.py          # ExtractorAgent
│   ├── coder_agent.py              # CoderAgent
│   ├── validator_agent.py          # ValidatorAgent
│   └── exception_handler_agent.py  # ExceptionHandlerAgent
│
├── rag/
│   ├── __init__.py
│   ├── engine.py                   # RAGEngine (Qdrant + SentenceTransformer)
│   ├── chunkers.py                 # FixedChunker, SemanticChunker
│   └── ingest.py                   # CLI: python -m rag.ingest --company_id=company_a
│
├── data/
│   ├── __init__.py
│   ├── generator.py                # Deterministic generator (seed=42), reportlab PDFs
│   ├── company_a/                  # Generated PDFs + gold JSONs for Company A
│   ├── company_b/                  # Generated PDFs + gold JSONs for Company B
│   └── splits.json                 # {"train": [...], "selection": [...], "test": [...]}
│
├── eval/
│   ├── __init__.py
│   ├── scorers.py                  # extractor_score, coder_score, validator_score
│   ├── baseline.py                 # Runs evaluation on SELECTION set
│   ├── retrieval_eval.py           # Recall@5, MRR@5 for RAG
│   └── results/
│       ├── baseline.md             # Scores v001 vs v002, with/without RAG
│       └── retrieval_eval.md       # RAG evaluation results
│
├── skills/
│   ├── company_a/
│   │   ├── router/v001.md
│   │   ├── extractor/v001.md
│   │   ├── coder/v001.md
│   │   ├── validator/v001.md
│   │   └── exception_handler/v001.md
│   └── company_b/
│       ├── router/v001.md
│       ├── extractor/v001.md
│       ├── coder/v001.md
│       ├── validator/v001.md
│       └── exception_handler/v001.md
│
├── prompts/
│   └── PROMPT_LIBRARY.md           # Documented prompts with techniques and results
│
├── n8n/
│   └── pipeline_workflow.json      # Importable n8n workflow JSON
│
├── demo/                           # 4 demo documents
│   ├── clean_invoice.pdf           # Clean text-layer PDF
│   ├── photo_receipt.jpg           # Noisy photo variant
│   ├── house_rule_po.pdf           # Document requiring a hidden house rule
│   └── arithmetic_error.pdf        # Document with arithmetic mismatch
│
├── inbox/                          # Transit directory for files being processed
│
├── real/
│   └── README.md                   # Instructions for adding real annotated documents
│
├── docs/
│   ├── architecture.md
│   ├── skillopt_api.md             # SkillOpt API reference (stretch goal)
│   └── failures.md                 # Failure log for SkillOpt and other issues
│
├── ui/                             # Existing Next.js React app (cyberpunk theme)
│   └── ...                         # (see UI Integration section)
│
├── streamlit_app.py                # Fallback UI if ./ui absent
│
├── qdrant_local/                   # Qdrant embedded storage
└── .cache/                         # DEMO_CACHE disk cache (.pkl files)
```

---

## Key Algorithms

### 5.1 Demo Cache (DEMO_CACHE=1)

```python
import hashlib, pickle, os

def _cache_key(role: str, system: str, user: str, image_b64: str = "") -> str:
    raw = role + "\x00" + system + "\x00" + user + "\x00" + image_b64
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def _cache_path(key: str) -> str:
    return os.path.join(".cache", f"{key}.pkl")

def get_cached(key: str) -> str | None:
    path = _cache_path(key)
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    return None

def set_cached(key: str, value: str) -> None:
    os.makedirs(".cache", exist_ok=True)
    with open(_cache_path(key), "wb") as f:
        pickle.dump(value, f)
```

Chaque appel LLM : calculer la clé → vérifier le cache → si miss : appeler le LLM et persister → retourner la valeur.

---

### 5.2 FixedChunker

```python
def chunk(self, text: str, source: str) -> list[dict]:
    tokens = tokenizer.encode(text)          # tiktoken cl100k_base
    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + 512, len(tokens))
        chunk_text = tokenizer.decode(tokens[start:end])
        chunk_id = hashlib.sha256(
            f"{source}:{start}:{end}".encode()
        ).hexdigest()[:16]
        chunks.append({
            "text": chunk_text,
            "chunk_id": chunk_id,
            "source": source,
            "start_token": start,
            "end_token": end,
        })
        start += 512 - 64   # 64-token overlap
    return chunks
```

---

### 5.3 SemanticChunker

```python
import re

HEADING_RE = re.compile(r"^#{1,6}\s+.+", re.MULTILINE)

def chunk(self, text: str, source: str) -> list[dict]:
    # Split on markdown headings, accumulate until max 1024 tokens
    sections = HEADING_RE.split(text)
    headings = HEADING_RE.findall(text)
    chunks = []
    buffer = ""
    current_heading = ""
    for i, section in enumerate(sections):
        candidate = buffer + section
        if len(tokenizer.encode(candidate)) > 1024 and buffer:
            # Flush buffer as a chunk
            chunk_id = hashlib.sha256(
                f"{source}:{current_heading}".encode()
            ).hexdigest()[:16]
            chunks.append({"text": buffer.strip(), "chunk_id": chunk_id,
                           "heading": current_heading, "source": source})
            buffer = section
        else:
            buffer = candidate
        if i < len(headings):
            current_heading = headings[i]
    if buffer.strip():
        chunk_id = hashlib.sha256(
            f"{source}:{current_heading}:tail".encode()
        ).hexdigest()[:16]
        chunks.append({"text": buffer.strip(), "chunk_id": chunk_id,
                       "heading": current_heading, "source": source})
    return chunks
```

---

### 5.4 RAG Idempotent Upsert

```python
def ingest(self, documents: list[dict], chunker_type: str = "fixed") -> int:
    chunker = FixedChunker() if chunker_type == "fixed" else SemanticChunker()
    new_count = 0
    for doc in documents:
        chunks = chunker.chunk(doc["text"], doc["source"])
        for chunk in chunks:
            embedding = self.model.encode(chunk["text"]).tolist()
            point = PointStruct(
                id=self._chunk_id_to_uint(chunk["chunk_id"]),
                vector=embedding,
                payload={
                    "text":       chunk["text"],
                    "company_id": self.company_id,
                    "source":     chunk["source"],
                    "chunk_id":   chunk["chunk_id"],
                },
            )
            # upsert is idempotent by Qdrant's design when id is stable
            result = self.client.upsert(
                collection_name="accounting_rules",
                points=[point],
            )
            new_count += result.operation_id  # 0 if already existed
    return new_count
```

Chunk IDs sont des hashes déterministes de `company_id + source + position` → même document re-ingéré = même ID = upsert sans duplication.

---

### 5.5 Scorers

**extractor_score** (normalized exact match)

```python
import re, unicodedata

def normalize(s: str) -> str:
    s = s.strip().lower()
    s = unicodedata.normalize("NFC", s)
    # Normalize French number format: "1 011,500" → "1011.500"
    s = re.sub(r"\s+", "", s)
    s = s.replace(",", ".")
    return s

def extractor_score(predicted: dict, gold: dict) -> float:
    keys = gold.keys()
    if not keys:
        return 1.0
    scores = [
        1.0 if normalize(str(predicted.get(k, ""))) == normalize(str(gold[k]))
        else 0.0
        for k in keys
    ]
    return sum(scores) / len(scores)
```

**coder_score** (binary)

```python
def coder_score(predicted: dict, gold: dict, skill_text: str, chunks: list[dict]) -> float:
    code_ok = predicted.get("account_code") == gold.get("account_code")
    cited   = predicted.get("cited_rule", "")
    if len(cited) < 10:
        return 0.0
    rule_found = (cited in skill_text) or any(cited in c["text"] for c in chunks)
    return 1.0 if (code_ok and rule_found) else 0.0
```

**validator_score** (F1 with β=√2, FN cost 2×)

```python
import math

def validator_score(predicted: list[str], reference: list[str]) -> float:
    if not predicted and not reference:
        return 1.0
    pred_set = set(predicted)
    ref_set  = set(reference)
    tp = len(pred_set & ref_set)
    fp = len(pred_set - ref_set)
    fn = len(ref_set - pred_set)
    beta = math.sqrt(2)
    beta2 = beta ** 2
    denom = (1 + beta2) * tp + beta2 * fn + fp
    if denom == 0:
        return 0.0
    return (1 + beta2) * tp / denom
```

---

### 5.6 Data Generator — Montants TND

```python
import locale
# Amounts stored as float internally, formatted for display:
def format_tnd(amount: float) -> str:
    """Format float as French TND: 1011.500 → '1 011,500'"""
    int_part = int(amount)
    dec_part = round((amount - int_part) * 1000)
    int_fmt = f"{int_part:,}".replace(",", "\u202f")  # narrow no-break space
    return f"{int_fmt},{dec_part:03d}"
```

---

### 5.7 Skill Loader

```python
import glob, os

def load_skill(company_id: str, agent_name: str, version: str | None = None) -> tuple[str, str]:
    """
    Load the latest (or specified) skill file.
    Returns (skill_text, version_string).
    """
    base = f"skills/{company_id}/{agent_name}"
    if version:
        path = f"{base}/{version}.md"
    else:
        versions = sorted(glob.glob(f"{base}/v*.md"))
        if not versions:
            raise FileNotFoundError(f"No skill found at {base}/")
        path = versions[-1]
    version_str = os.path.splitext(os.path.basename(path))[0]  # "v001"
    with open(path, encoding="utf-8") as f:
        return f.read(), version_str
```

---

## Python Dependencies

```
# Core
fastapi==0.115.6
uvicorn[standard]==0.32.1
pydantic==2.10.3
python-dotenv==1.0.1
python-multipart==0.0.20

# LLM
openai==1.57.2          # Azure AI Foundry + OpenAI-compatible

# RAG / Embeddings
qdrant-client==1.12.1
sentence-transformers==3.3.4
torch==2.5.1             # CPU build sufficient
tiktoken==0.8.0          # For FixedChunker token counting

# PDF & Image
reportlab==4.2.5
pypdf==5.1.0
pdf2image==1.17.0        # Requires poppler-utils installed
Pillow==11.1.0

# Data / Eval
numpy==2.2.0
scikit-learn==1.6.0      # For F1 computation helpers

# Streamlit fallback
streamlit==1.41.1

# Dev / Test
pytest==8.3.4
hypothesis==6.123.4      # Property-based testing
pytest-asyncio==0.25.2
httpx==0.28.1            # FastAPI test client
```

---

## Tracing / Observability

Chaque appel à un endpoint agent suit ce cycle :

```
t0 = time.monotonic()
result = agent.run(payload, company_id)
duration_ms = int((time.monotonic() - t0) * 1000)

trace = TraceEvent(
    doc_id        = payload.doc_id,
    step          = "route" | "extract" | "code" | "validate" | "handle" | ...,
    status        = "success" | "error",
    duration_ms   = duration_ms,
    output_json   = result.model_dump_json(),
    chunks_json   = json.dumps(result.chunks if hasattr(result, "chunks") else []),
    skill_version = result.skill_version,
    timestamp     = datetime.utcnow().isoformat() + "Z",
)
db.write(trace)
```

`GET /trace/{doc_id}` retourne toutes les lignes de trace pour ce `doc_id`, ordonnées par timestamp. L'UI React interroge cet endpoint toutes les 500ms pour mettre à jour les 5 cartes de progression.

**Health check** (`GET /health`) :
- Qdrant : `client.get_collections()` sans exception
- SQLite : `SELECT 1` sans exception
- LLM_Client : présence des variables d'environnement requises (sans appel réseau)

---

## Error Handling

### Hiérarchie d'exceptions

```python
class PipelineError(Exception): pass
class MissingDeploymentError(PipelineError): pass   # var manquante
class AgentParseError(PipelineError): pass           # LLM retourne JSON invalide
class RAGEngineError(PipelineError): pass            # Qdrant inaccessible
class ValidationError(PipelineError): pass          # Erreur dans les checks Python
```

### Stratégie par couche

| Couche | Comportement en cas d'erreur |
|--------|------------------------------|
| **LLMClient** | Lève `MissingDeploymentError` si variable manquante. Les erreurs réseau remontent (pas de retry ici — c'est n8n qui gère les 2 retries). |
| **Agents** | Catchent `json.JSONDecodeError` sur la réponse LLM → lèvent `AgentParseError` avec le texte brut pour diagnostic. |
| **RAGEngine** | Catchent les exceptions Qdrant → lèvent `RAGEngineError`. |
| **FastAPI handlers** | `HTTPException(status_code=500, detail=str(e))` pour les erreurs inattendues. La trace est écrite avec `status="error"` avant de renvoyer l'erreur. |
| **n8n** | Chaque nœud a `retries=2`. En cas d'échec de toutes les tentatives → branche `Error → Fail → Respond`. |
| **run.py** | Timeout 30s par composant. Si un composant ne démarre pas → message d'erreur explicite + `sys.exit(1)`. |

### Pattern de retry n8n

```json
{
  "retryOnFail": true,
  "maxTries": 2,
  "waitBetweenTries": 1000
}
```

---

## UI Integration

### Architecture React (Next.js 15 + Tailwind cyberpunk)

L'UI existante dans `./ui` conserve son style et sa barre latérale. Toutes les données simulées sont remplacées par des appels réels.

**Variables d'environnement UI** (`.env.local` dans `./ui`) :
```
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_N8N_WEBHOOK_URL=http://localhost:5678/webhook/pipeline
```

### Pages et composants à modifier / créer

#### Command Center (`/command-center`)

Remplace le contenu statique existant par :

```typescript
// Composants:
// <DocumentUploader />     — drag & drop ou sélecteur de fichier
// <PipelineProgress />     — 5 cartes: Router, Extractor, Coder, Validator, Decision
// <KPIBar />               — docs traités aujourd'hui, taux d'acceptation, taux d'escalade
// <DecisionBadge />        — "ACCEPTED" | "ESCALATED" avec couleur

// Polling logic:
useEffect(() => {
  if (!docId || finalDecision) return
  const interval = setInterval(async () => {
    const traces = await fetch(`${API_URL}/trace/${docId}`).then(r => r.json())
    updateStageCards(traces)
    if (traces.some(t => ["accept","escalate","fail"].includes(t.step))) {
      setFinalDecision(getDecision(traces))
      clearInterval(interval)
    }
  }, 500)
  return () => clearInterval(interval)
}, [docId, finalDecision])
```

**5 cartes de progression** :

| Carte | Step SQLite | États possibles |
|-------|-------------|-----------------|
| Router | `"route"` | pending / running / success / error |
| Extractor | `"extract"` | pending / running / success / error |
| Coder | `"code"` | pending / running / success / error |
| Validator | `"validate"` | pending / running / success / error |
| Decision | `"accept"` ou `"escalate"` | pending / ACCEPTED / ESCALATED / FAILED |

#### Agent Network (`/agent-network`)

Affiche les 5 agents du pipeline (pas les agents fictifs existants) avec :
- Statut en temps réel (idle / processing / error)
- Version du skill actuellement chargée (depuis les dernières traces)
- Durée du dernier appel

#### Operations (`/operations`)

- Liste des documents traités (depuis SQLite via `GET /trace/{id}`)
- Vue de trace détaillée : timeline de toutes les étapes avec durées et outputs

#### Intelligence (`/intelligence`)

- Chunks récupérés avec barres de similarité (scores de cosinus)
- Tableau Recall@5 / MRR@5 issu de `eval/results/retrieval_eval.md`

#### Systems (`/systems`)

- État de santé en temps réel via `GET /health` (polling toutes les 5s)
- Composants : FastAPI, n8n, Qdrant_Local, LLM_Client

### Fallback Streamlit (`streamlit_app.py`)

Activé si `./ui` est absent. Reproduit les fonctionnalités clés du Command Center :

```python
import streamlit as st
import requests, time

API_URL = os.getenv("NEXT_PUBLIC_API_URL", "http://localhost:8000")

# Upload → POST webhook → poll /trace → 5 colonnes de statut
```

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Temperature invariant

*For any* combination of role, system prompt, and user message, every outgoing LLM request made by `LLMClient.call()` SHALL have `temperature=0`.

**Validates: Requirements 1.3**

---

### Property 2: Cache round-trip with zero network calls

*For any* (role, system_prompt, user_message) tuple, when `DEMO_CACHE=1` is active and the same tuple is passed to `LLMClient.call()` a second time, the client SHALL return the identical response string and SHALL make zero outbound network calls for that second invocation.

**Validates: Requirements 1.4, 1.6, 16.8**

---

### Property 3: Missing deployment raises named exception

*For any* role whose corresponding deployment environment variable is not set, calling `LLMClient.call()` with that role SHALL raise `MissingDeploymentError` and the exception message SHALL contain the name of the missing environment variable.

**Validates: Requirements 1.5**

---

### Property 4: Data generator determinism

*For any* two independent executions of `DataGenerator` initialized with `seed=42`, both runs SHALL produce byte-for-byte identical output files and identical `splits.json` content.

**Validates: Requirements 2.1**

---

### Property 5: Error injection cardinality

*For any* document in the generated corpus that has a non-empty `injected_errors` list, the length of `injected_errors` SHALL be exactly 1, and its sole element SHALL be one of `["duplicate_id", "arithmetic_mismatch", "missing_nif"]`.

**Validates: Requirements 2.5**

---

### Property 6: Generated document format invariants

*For any* document generated by `DataGenerator`, all monetary amount strings SHALL match the French TND format regex `\d[\d\u202f]*,\d{3}` (digit groups separated by narrow no-break spaces, comma decimal separator, exactly 3 decimal places), and all date strings SHALL match `\d{2}/\d{2}/\d{4}`.

**Validates: Requirements 2.11, 2.12**

---

### Property 7: Router output completeness and validity

*For any* input document submitted to `RouterAgent.run()`, the returned dict SHALL contain both `doc_type` (value in `["invoice", "receipt", "purchase_order"]`) and `modality` (value in `["text", "photo"]`).

**Validates: Requirements 4.1, 9.3**

---

### Property 8: Normalizer idempotence on equivalent strings

*For any* pair of strings that differ only in leading/trailing whitespace, letter case, or French number formatting (`1 011,500` vs `1011.500`), the `normalize()` function used by `extractor_score` SHALL return identical strings, resulting in a normalized exact match score of `1.0`.

**Validates: Requirements 5.1**

---

### Property 9: Coder scorer is strictly binary

*For any* (coder_output, gold, skill_text, chunks) tuple, `coder_score()` SHALL return exactly `1.0` if and only if `coder_output["account_code"] == gold["account_code"]` AND `coder_output["cited_rule"]` (of length ≥10) appears as a substring in `skill_text` or in any element of `chunks`; otherwise it SHALL return exactly `0.0`.

**Validates: Requirements 5.2**

---

### Property 10: Trace completeness after every pipeline step

*For any* successful call to any of the POST endpoints (`/route`, `/extract`, `/code`, `/validate`, `/handle`, `/accept`, `/escalate`, `/fail`), the SQLite `traces` table SHALL contain a new row for the corresponding `doc_id` with non-null, non-empty values for `step`, `status`, `duration_ms`, and `skill_version`.

**Validates: Requirements 6.3, 16.5**

---

### Property 11: RAG company isolation

*For any* search query issued to `RAGEngine` for company `X`, every returned chunk SHALL have `payload.company_id == X`, and no chunk with `payload.company_id != X` SHALL appear in the results.

**Validates: Requirements 8.4**

---

### Property 12: RAG idempotence

*For any* batch of documents ingested into `RAGEngine`, ingesting the identical batch a second time SHALL leave the Qdrant collection size unchanged (same number of vectors after second ingestion as after first).

**Validates: Requirements 8.5, 8.9, 16.4**

---

### Property 13: Extractor output is a key superset of gold fields

*For any* document from the generated corpus that has a text layer, the dict returned by `ExtractorAgent.run()` SHALL contain every key present in the corresponding gold JSON `fields` dictionary (it may contain additional keys).

**Validates: Requirements 4.2, 16.1**

---

### Property 14: Account code format matches company-specific pattern

*For any* output produced by `CoderAgent.run()` for `company_id="company_a"`, `account_code` SHALL match the regex `^[A-Z0-9]{6}$`. *For any* output produced for `company_id="company_b"`, `account_code` SHALL match the regex `^\d{4}-[A-Z]{2}\d{3}$`.

**Validates: Requirements 16.2, 16.3**

---

### Property 15: Validator detects arithmetic mismatches

*For any* extracted document where `abs(sum(line.htva for line in lines) + sum(line.tva for line in lines) - ttc) > 0.001`, `ValidatorAgent.run()` SHALL return a dict with `needs_review=True` and `"arithmetic_mismatch"` in the `errors` list.

**Validates: Requirements 4.4, 16.6**

---

### Property 16: Validator scorer returns 1.0 for empty inputs

*For any* call to `validator_score([], [])` where both the predicted error list and the reference error list are empty, the function SHALL return exactly `1.0`.

**Validates: Requirements 5.4, 16.7**

---

### Property 17: Split proportions with no overlap

*For any* run of `DataGenerator` with `seed=42`, the generated `splits.json` SHALL satisfy: `|TRAIN| / |total| ≈ 0.50 ± 0.05`, `|SELECTION| / |total| ≈ 0.20 ± 0.05`, `|TEST| / |total| ≈ 0.30 ± 0.05`, and `TRAIN ∩ SELECTION ∩ TEST = ∅` (each document in exactly one split).

**Validates: Requirements 2.7, 16.9**

---

### Property 18: Pipeline termination for demo documents

*For any* document in the `demo/` folder processed through the full pipeline, the pipeline SHALL produce a final decision of either `"ACCEPTED"` or `"ESCALATED"` (written to the `traces` table) without raising an unhandled exception, regardless of the document's content or injected errors.

**Validates: Requirements 16.10**

---

## Testing Strategy

### Approche duale

Le projet combine **tests basés sur des exemples** (pytest classique) pour les comportements spécifiques et les points d'intégration, et des **tests basés sur des propriétés** (Hypothesis) pour les invariants universels décrits ci-dessus.

### Bibliothèque de PBT

**Hypothesis 6.x** est utilisé pour les property-based tests. Chaque test de propriété tourne au minimum **100 itérations** (configuré via `@settings(max_examples=100)`).

Format de tag pour chaque test :
```python
# Feature: n8n-multiagent-doc-pipeline, Property N: <property_text>
```

### Structure des tests

```
tests/
├── unit/
│   ├── test_llm_client.py          # P1, P2, P3
│   ├── test_chunkers.py            # FixedChunker sizes, SemanticChunker headings
│   ├── test_scorers.py             # P8, P9, P16
│   ├── test_validator_agent.py     # P15
│   ├── test_data_generator.py      # P4, P5, P6, P17
│   └── test_router_agent.py        # P7
├── integration/
│   ├── test_rag_engine.py          # P11, P12
│   ├── test_api_endpoints.py       # P10, endpoint existence
│   ├── test_extractor_agent.py     # P13
│   └── test_coder_agent.py         # P14
└── e2e/
    └── test_demo_pipeline.py       # P18
```

### Exemples de tests de propriétés

```python
# tests/unit/test_llm_client.py
# Feature: n8n-multiagent-doc-pipeline, Property 1: Temperature invariant

from hypothesis import given, settings
from hypothesis import strategies as st
from unittest.mock import patch, MagicMock

@given(
    role=st.sampled_from(["agent", "vision", "optimizer"]),
    system=st.text(min_size=1, max_size=500),
    user=st.text(min_size=1, max_size=500),
)
@settings(max_examples=100)
def test_temperature_always_zero(role, system, user, monkeypatch):
    """Property 1: For any LLM call, temperature must be 0."""
    monkeypatch.setenv(f"{role.upper()}_DEPLOYMENT", "test-deployment")
    captured_calls = []
    with patch("openai.AzureOpenAI") as mock_client:
        mock_client.return_value.chat.completions.create.side_effect = (
            lambda **kwargs: captured_calls.append(kwargs) or MagicMock(
                choices=[MagicMock(message=MagicMock(content="ok"))]
            )
        )
        client = LLMClient()
        client.call(role, system, user)
    assert all(c.get("temperature") == 0 for c in captured_calls)
```

```python
# tests/unit/test_scorers.py
# Feature: n8n-multiagent-doc-pipeline, Property 9: Coder scorer is strictly binary

from hypothesis import given, settings
from hypothesis import strategies as st

@given(
    code=st.text(min_size=6, max_size=6,
                 alphabet=st.characters(whitelist_categories=("Lu", "Nd"))),
    cited=st.text(min_size=10, max_size=200),
    gold_code=st.text(min_size=6, max_size=6),
)
@settings(max_examples=100)
def test_coder_score_is_binary(code, cited, gold_code):
    """Property 9: coder_score is exactly 0.0 or 1.0."""
    result = coder_score(
        {"account_code": code, "cited_rule": cited},
        {"account_code": gold_code},
        skill_text=cited,   # ensure rule is always "findable" to isolate code match
        chunks=[],
    )
    assert result in (0.0, 1.0)
```

```python
# tests/integration/test_rag_engine.py
# Feature: n8n-multiagent-doc-pipeline, Property 12: RAG idempotence

from hypothesis import given, settings
from hypothesis import strategies as st

@given(
    docs=st.lists(
        st.fixed_dictionaries({
            "text": st.text(min_size=10, max_size=500),
            "source": st.text(min_size=1, max_size=50),
        }),
        min_size=1, max_size=5,
    )
)
@settings(max_examples=100)
def test_rag_idempotent_ingestion(docs, tmp_path):
    """Property 12: Ingesting the same batch twice leaves collection size unchanged."""
    engine = RAGEngine("company_a", qdrant_path=str(tmp_path / "qdrant"))
    engine.ingest(docs)
    size_after_first = engine.client.get_collection("accounting_rules").vectors_count
    engine.ingest(docs)
    size_after_second = engine.client.get_collection("accounting_rules").vectors_count
    assert size_after_first == size_after_second
```

### Tests d'exemples (non-PBT)

- **Smoke** : `GET /health` retourne 200 + toutes les clés de composants
- **Integration** : `POST /route` avec un PDF de démo → retourne `doc_type` et `modality` valides
- **Example** : Le workflow n8n JSON est parseable et contient exactement 5 nœuds d'agents
- **Example** : `extractor_score(gold, gold) == 1.0` pour chaque gold document
- **Example** : `validator_score([], []) == 1.0`

### Évaluation baseline

```bash
# Sur le SELECTION set (v001, avec et sans RAG) :
python -m eval.baseline --company company_a --split selection
python -m eval.baseline --company company_b --split selection

# Résultats écrits dans eval/results/baseline.md
# Format: agent | score_v001 | score_v001_no_rag | score_v002
```

### Évaluation RAG

```bash
python -m eval.retrieval_eval --company company_a
python -m eval.retrieval_eval --company company_b
# Recall@5 et MRR@5 écrits dans eval/results/retrieval_eval.md
```
