# Implementation Plan: n8n Multi-Agent Document Pipeline

## Overview

Build a multi-agent accounting document pipeline for Tunisian companies. A document submitted via a React UI traverses five LLM agents (Router → Extractor → Coder → Validator → ExceptionHandler) orchestrated by n8n, with FastAPI as the backend, Qdrant-embedded RAG, SQLite tracing, and a single `python run.py` entry point. All components run locally without Docker.

---

## Tasks

- [x] 1. Foundation — LLM client, environment, and dependencies

  - [x] 1.1 Create `.env.template` and `requirements.txt`
    - Write `.env.template` with all required variables: `AZURE_ENDPOINT`, `AZURE_API_KEY`, `AGENT_DEPLOYMENT`, `VISION_DEPLOYMENT`, `OPTIMIZER_DEPLOYMENT`, `AZURE_API_VERSION` (optional), `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `DEMO_CACHE`
    - Write `requirements.txt` with pinned versions from the design: `fastapi==0.115.6`, `uvicorn[standard]==0.32.1`, `pydantic==2.10.3`, `python-dotenv==1.0.1`, `python-multipart==0.0.20`, `openai==1.57.2`, `qdrant-client==1.12.1`, `sentence-transformers==3.3.4`, `torch==2.5.1`, `tiktoken==0.8.0`, `reportlab==4.2.5`, `pypdf==5.1.0`, `pdf2image==1.17.0`, `Pillow==11.1.0`, `numpy==2.2.0`, `scikit-learn==1.6.0`, `streamlit==1.41.1`, `pytest==8.3.4`, `hypothesis==6.123.4`, `pytest-asyncio==0.25.2`, `httpx==0.28.1`
    - _Requirements: 1.1, 1.2, 13.2_

  - [x] 1.2 Implement `agents/llm_client.py` — `LLMClient` and `MissingDeploymentError`
    - Create `agents/__init__.py` (empty)
    - Implement `MissingDeploymentError(Exception)` with message naming the missing variable
    - Implement `LLMClient` class with `ROLE_DEPLOYMENT_MAP = {"agent": "AGENT_DEPLOYMENT", "vision": "VISION_DEPLOYMENT", "optimizer": "OPTIMIZER_DEPLOYMENT"}`
    - In `__init__`: load `.env` via `python-dotenv`; detect provider (Azure if `AZURE_ENDPOINT` set, else OpenAI-compatible via `OPENAI_BASE_URL`); store client reference; temperature is locked at 0 — never passed as a parameter that can be overridden
    - Implement `call(role, system_prompt, user_message, image_b64=None) -> str`
      - Resolve deployment name from `ROLE_DEPLOYMENT_MAP`; raise `MissingDeploymentError` naming the missing env var if absent
      - Compute SHA-256 cache key: `sha256(role + "\x00" + system_prompt + "\x00" + user_message + "\x00" + (image_b64 or ""))`
      - If `DEMO_CACHE=1` and `.cache/<hash>.pkl` exists: return `pickle.load(...)` with **zero** network calls
      - Call LLM with `temperature=0`; if `DEMO_CACHE=1` persist response to `.cache/<hash>.pkl`
      - Return response text string
    - Implement helper functions `_cache_key()`, `get_cached()`, `set_cached()` as per design §5.1
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

  - [x]* 1.3 Write property tests for `LLMClient` — Properties 1, 2, 3
    - Create `tests/unit/test_llm_client.py`
    - **Property 1: Temperature invariant** — `@given(role, system, user)` verify every outgoing call has `temperature=0`
      - Tag: `# Feature: n8n-multiagent-doc-pipeline, Property 1: Temperature invariant`
      - **Validates: Requirements 1.3**
    - **Property 2: Cache round-trip with zero network calls** — `@given(role, system, user)` call twice when `DEMO_CACHE=1`; assert same response, zero network calls on second invocation
      - Tag: `# Feature: n8n-multiagent-doc-pipeline, Property 2: Cache round-trip`
      - **Validates: Requirements 1.4, 1.6, 16.8**
    - **Property 3: Missing deployment raises named exception** — `@given(role)` with env var unset; assert `MissingDeploymentError` raised and message contains var name
      - Tag: `# Feature: n8n-multiagent-doc-pipeline, Property 3: Missing deployment`
      - **Validates: Requirements 1.5**
    - Use `@settings(max_examples=100)` on all tests

- [x] 2. Data Generator — synthetic Tunisian accounting documents

  - [x] 2.1 Create static company data for Company A and Company B
    - Create `data/__init__.py` (empty)
    - Create `data/company_a/chart_of_accounts.md` — ≥20 lines modelled on SCE Tunisian class 6, 6-character codes (`[A-Z0-9]{6}`)
    - Create `data/company_a/suppliers.md` — ≥10 suppliers: STEG, SONEDE, Tunisie Telecom, Ooredoo, Orange, Monoprix, Carrefour, fuel stations, IT suppliers; each with fake NIF
    - Create `data/company_a/coding_rules.md` — coding rules in Markdown
    - Create `data/company_a/house_rules.md` — 4 hidden house rules (not in gold labels' visible fields)
    - Create equivalent files for Company B: `data/company_b/chart_of_accounts.md`, `suppliers.md`, `coding_rules.md`, `house_rules.md`
    - Company B accounts use format `6010-CC001` (`[0-9]{4}-[A-Z]{2}[0-9]{3}`), TVA rates 7%/13%/19% per line, EUR/TND currencies
    - _Requirements: 2.2, 2.3, 2.16_

  - [x] 2.2 Implement `data/generator.py` — deterministic PDF generator (seed=42)
    - Initialize `random.seed(42)` and `numpy` RNG with seed 42 at module level
    - Implement `format_tnd(amount: float) -> str` — French TND format with narrow no-break space `\u202f` and 3 decimal places (e.g. `1 011,500`)
    - Implement `format_date(dt) -> str` — `dd/mm/yyyy` format
    - Implement `generate_pdf(doc_data: dict, output_path: str)` using reportlab:
      - All text in French
      - Include lines: HTVA, TVA (company-appropriate rate), TTC, Timbre_Fiscal
      - Include NIF field in Tunisian format `XXXXXXXX/X/XXX/XXX`
      - Company A: TVA 19%, 6-char account codes; Company B: TVA 7/13/19% per line, `6010-CC001` codes
    - Implement `generate_photo_variant(pdf_path: str, output_path: str)` using Pillow + pdf2image: render PDF → image, apply slight rotation (1–5°), add Gaussian noise
    - Implement `inject_error(doc_data: dict, error_type: str) -> dict` for `duplicate_id`, `arithmetic_mismatch`, `missing_nif`
    - Implement `generate_corpus(company_id: str, n: int = 30) -> list[dict]` — generates invoices, receipts, purchase_orders with gold JSONs containing `doc_type`, `fields`, `account_code`, `injected_errors`; 30% of docs get exactly one injected error
    - Implement `split_corpus(docs: list, seed: int = 42) -> dict` — deterministic TRAIN 50% / SELECTION 20% / TEST 30% split; write `data/splits.json`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.10, 2.11, 2.12, 2.13, 2.14, 2.15_

  - [x] 2.3 Generate corpus and demo documents
    - Run generator to produce `data/company_a/` and `data/company_b/` PDFs + gold JSONs
    - Write `data/splits.json`
    - Create `demo/` folder with exactly 4 documents:
      - `demo/clean_invoice.pdf` — clean text-layer PDF
      - `demo/photo_receipt.jpg` — noisy photo variant
      - `demo/house_rule_po.pdf` — document requiring a hidden house rule
      - `demo/arithmetic_error.pdf` — document with arithmetic mismatch
    - Create `real/README.md` with instructions for adding real annotated documents (15–20 photos, same gold JSON schema)
    - _Requirements: 2.8, 2.9, 3.1, 3.2, 3.3_

  - [x]* 2.4 Write property tests for data generator — Properties 4, 5, 6, 17
    - Create `tests/unit/test_data_generator.py`
    - **Property 4: Data generator determinism** — run generator twice with seed=42; assert byte-identical output and identical `splits.json`
      - Tag: `# Feature: n8n-multiagent-doc-pipeline, Property 4: Determinism`
      - **Validates: Requirements 2.1**
    - **Property 5: Error injection cardinality** — `@given(doc_data)` for docs with injected errors; assert `len(injected_errors) == 1` and value in `["duplicate_id","arithmetic_mismatch","missing_nif"]`
      - Tag: `# Feature: n8n-multiagent-doc-pipeline, Property 5: Error cardinality`
      - **Validates: Requirements 2.5**
    - **Property 6: Generated document format invariants** — `@given(generated_doc)` assert amount strings match `\d[\d\u202f]*,\d{3}` and date strings match `\d{2}/\d{2}/\d{4}`
      - Tag: `# Feature: n8n-multiagent-doc-pipeline, Property 6: Format invariants`
      - **Validates: Requirements 2.11, 2.12**
    - **Property 17: Split proportions with no overlap** — assert TRAIN≈50%, SELECTION≈20%, TEST≈30% (±5%), and `TRAIN ∩ SELECTION ∩ TEST = ∅`
      - Tag: `# Feature: n8n-multiagent-doc-pipeline, Property 17: Split proportions`
      - **Validates: Requirements 2.7, 16.9**
    - Use `@settings(max_examples=100)` on all property tests

- [x] 3. Checkpoint — Foundation and data layer complete
  - Ensure all unit tests pass, LLM client and data generator are importable, demo/ folder contains 4 files. Ask the user if questions arise.

- [x] 4. Agent skill files

  - [x] 4.1 Create v001 skill files for Company A (5 agents)
    - Create `skills/company_a/router/v001.md` — system prompt: detect `doc_type` (invoice/receipt/purchase_order) and `modality` (text/photo); output JSON with both fields
    - Create `skills/company_a/extractor/v001.md` — system prompt: extract all structured fields (supplier, date, number, lines, HTVA, TVA, TTC, Timbre_Fiscal, NIF) in French, TND format, dd/mm/yyyy dates
    - Create `skills/company_a/coder/v001.md` — system prompt: assign 6-char `[A-Z0-9]{6}` account code using retrieved RAG chunks; cite the exact rule used (≥10 chars)
    - Create `skills/company_a/validator/v001.md` — system prompt: given arithmetic check results and NIF/duplicate flags, produce a single-sentence explanation
    - Create `skills/company_a/exception_handler/v001.md` — system prompt: produce structured escalation dossier with summary, errors, recommended_action, contact
    - _Requirements: 4.6, 4.7_

  - [x] 4.2 Create v001 skill files for Company B (5 agents)
    - Create equivalent `skills/company_b/<agent>/v001.md` for all 5 agents
    - Coder skill uses `6010-CC001` format codes, multi-rate TVA rules; extractor handles EUR/TND
    - All other skills adapted for Company B context
    - _Requirements: 4.6, 4.7_

  - [x] 4.3 Implement `agents/skill_loader.py` — `load_skill()` utility
    - Implement `load_skill(company_id: str, agent_name: str, version: str | None = None) -> tuple[str, str]` as per design §5.7
    - Use `glob.glob(f"skills/{company_id}/{agent_name}/v*.md")`, sort, take latest
    - Return `(skill_text, version_string)` e.g. `("...", "v001")`
    - Raise `FileNotFoundError` with descriptive message if no skill found
    - _Requirements: 4.6, 4.7, 4.8_

- [x] 5. Pipeline agents

  - [x] 5.1 Implement `agents/router_agent.py` — `RouterAgent`
    - Implement `RouterAgent.run(input: dict, company_id: str) -> dict`
    - `input`: `{"file_path": str, "file_bytes_b64": str | None}`
    - Load skill via `load_skill(company_id, "router")`; make one LLM call with `role="agent"`
    - Parse JSON response; raise `AgentParseError` on `JSONDecodeError`
    - Return `{"doc_type": str, "modality": str, "skill_version": str}`
    - Implement `PipelineError`, `AgentParseError`, `RAGEngineError`, `ValidationError` exception hierarchy in `agents/exceptions.py`
    - _Requirements: 4.1, 4.6, 9.3_

  - [x]* 5.2 Write property test for `RouterAgent` — Property 7
    - Create `tests/unit/test_router_agent.py`
    - **Property 7: Router output completeness and validity** — `@given(file_input)` mock LLM; assert returned dict contains `doc_type` in `["invoice","receipt","purchase_order"]` and `modality` in `["text","photo"]`
      - Tag: `# Feature: n8n-multiagent-doc-pipeline, Property 7: Router output`
      - **Validates: Requirements 4.1, 9.3**
    - `@settings(max_examples=100)`

  - [x] 5.3 Implement `agents/extractor_agent.py` — `ExtractorAgent`
    - Implement `ExtractorAgent.run(input: dict, company_id: str) -> dict`
    - `input`: `{"text": str, "doc_type": str}` (or `{"image_b64": str, "doc_type": str}` for photo)
    - Text documents: `role="agent"`; photo documents: `role="vision"` with `image_b64`
    - Load skill via `load_skill(company_id, "extractor")`; one LLM call
    - Return all required fields: `supplier`, `date`, `number`, `lines`, `htva`, `tva`, `ttc`, `timbre_fiscal`, `nif`, `skill_version`
    - _Requirements: 4.2, 9.1, 9.2_

  - [x]* 5.4 Write property test for `ExtractorAgent` — Property 13
    - Create `tests/integration/test_extractor_agent.py`
    - **Property 13: Extractor output is a key superset of gold fields** — for gold documents with text layer, assert returned dict keys ⊇ gold `fields` keys
      - Tag: `# Feature: n8n-multiagent-doc-pipeline, Property 13: Key superset`
      - **Validates: Requirements 4.2, 16.1**
    - `@settings(max_examples=100)`

  - [x] 5.5 Implement `agents/coder_agent.py` — `CoderAgent`
    - Implement `CoderAgent.run(input: dict, company_id: str) -> dict`
    - `input`: `{"extracted": dict, "doc_type": str}`
    - Instantiate `RAGEngine(company_id)`; call `search(query, top_k=5)`; inject top chunks into prompt
    - Load skill via `load_skill(company_id, "coder")`; one LLM call with `role="agent"`
    - Return `{"account_code": str, "cited_rule": str, "chunks": list[dict], "skill_version": str}`
    - _Requirements: 4.3, 8.8_

  - [x]* 5.6 Write property test for `CoderAgent` — Property 14
    - Create `tests/integration/test_coder_agent.py`
    - **Property 14: Account code format matches company pattern** — `@given(extracted_doc, company_id)` mock LLM to return codes; assert company_a codes match `^[A-Z0-9]{6}$` and company_b codes match `^\d{4}-[A-Z]{2}\d{3}$`
      - Tag: `# Feature: n8n-multiagent-doc-pipeline, Property 14: Account code format`
      - **Validates: Requirements 16.2, 16.3**
    - `@settings(max_examples=100)`

  - [x] 5.7 Implement `agents/validator_agent.py` — `ValidatorAgent`
    - Implement `ValidatorAgent.run(input: dict, company_id: str) -> dict`
    - `input`: `{"extracted": dict, "doc_id": str}`
    - Phase 1 (Python deterministic, no LLM):
      - Arithmetic: `abs(htva + tva - ttc) <= 0.001`
      - NIF presence: `nif is not None and nif != ""`
      - Duplicate ID: query `TraceStore.doc_id_exists(doc_id)`
    - Phase 2: one LLM call with `role="agent"` for 1-sentence explanation
    - Return `{"valid": bool, "errors": list[str], "explanation": str, "needs_review": bool, "skill_version": str}`
    - _Requirements: 4.4, 16.6_

  - [x]* 5.8 Write property test for `ValidatorAgent` — Property 15
    - Create `tests/unit/test_validator_agent.py`
    - **Property 15: Validator detects arithmetic mismatches** — `@given(htva, tva, ttc)` where `abs(htva+tva-ttc) > 0.001`; assert `needs_review=True` and `"arithmetic_mismatch"` in `errors`
      - Tag: `# Feature: n8n-multiagent-doc-pipeline, Property 15: Arithmetic detection`
      - **Validates: Requirements 4.4, 16.6**
    - `@settings(max_examples=100)`

  - [x] 5.9 Implement `agents/exception_handler_agent.py` — `ExceptionHandlerAgent`
    - Implement `ExceptionHandlerAgent.run(input: dict, company_id: str) -> dict`
    - `input`: `{"extracted": dict, "validation": dict, "doc_id": str}`
    - Load skill via `load_skill(company_id, "exception_handler")`; one LLM call with `role="agent"`
    - Return `{"escalation_dossier": dict, "skill_version": str}` where dossier includes `summary`, `errors`, `recommended_action`, `contact`
    - _Requirements: 4.5_

- [x] 6. Checkpoint — All five agents implemented
  - Ensure all agent unit tests pass, each agent is importable, skill files exist for both companies. Ask the user if questions arise.

- [x] 7. RAG engine

  - [x] 7.1 Implement `rag/chunkers.py` — `FixedChunker` and `SemanticChunker`
    - Create `rag/__init__.py` (empty)
    - Implement `FixedChunker.chunk(text: str, source: str) -> list[dict]`
      - Use `tiktoken` with `cl100k_base` encoding
      - 512 tokens per chunk, 64-token overlap
      - Deterministic `chunk_id`: `sha256(f"{source}:{start}:{end}").hexdigest()[:16]`
      - Return `[{text, chunk_id, source, start_token, end_token}]`
    - Implement `SemanticChunker.chunk(text: str, source: str) -> list[dict]`
      - Split on markdown headings (`##`, `###`) using `HEADING_RE = re.compile(r"^#{1,6}\s+.+", re.MULTILINE)`
      - Max 1024 tokens per chunk; flush buffer when exceeded
      - Deterministic `chunk_id`: `sha256(f"{source}:{heading}").hexdigest()[:16]`
      - Return `[{text, chunk_id, heading, source}]`
    - _Requirements: 8.2_

  - [x]* 7.2 Write unit tests for chunkers
    - Create `tests/unit/test_chunkers.py`
    - Test `FixedChunker`: assert no chunk exceeds 512 tokens; assert overlap equals 64 tokens between consecutive chunks; assert chunk IDs are unique
    - Test `SemanticChunker`: assert chunks split on heading boundaries; assert no chunk exceeds 1024 tokens
    - _Requirements: 8.2_

  - [x] 7.3 Implement `rag/engine.py` — `RAGEngine`
    - Implement `RAGEngine.__init__(company_id: str, qdrant_path: str = "./qdrant_local")`
      - `QdrantClient(path=qdrant_path)`
      - `SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")`
      - Collection name: `"accounting_rules"`; create collection if not exists with correct vector size
    - Implement `ingest(documents: list[dict], chunker_type: str = "fixed") -> int`
      - Idempotent upsert by deterministic `chunk_id` (hash of `company_id + source + offset`)
      - Returns number of newly upserted chunks (0 if all already existed)
    - Implement `search(query: str, top_k: int = 5) -> list[dict]`
      - Filter by `payload.company_id == self.company_id`
      - Return `[{text, score, chunk_id, source}]`
    - Implement `_chunk_id_to_uint(chunk_id: str) -> int` for Qdrant point IDs
    - _Requirements: 8.1, 8.3, 8.4, 8.5, 8.8_

  - [x]* 7.4 Write property tests for `RAGEngine` — Properties 11, 12
    - Create `tests/integration/test_rag_engine.py`
    - **Property 11: RAG company isolation** — `@given(query, company_a_docs, company_b_docs)` ingest both; search for company_a; assert all chunks have `company_id="company_a"`
      - Tag: `# Feature: n8n-multiagent-doc-pipeline, Property 11: Company isolation`
      - **Validates: Requirements 8.4**
    - **Property 12: RAG idempotence** — `@given(docs)` ingest once, record collection size; ingest same docs again; assert size unchanged
      - Tag: `# Feature: n8n-multiagent-doc-pipeline, Property 12: RAG idempotence`
      - **Validates: Requirements 8.5, 8.9, 16.4**
    - `@settings(max_examples=100)`; use `tmp_path` for isolated Qdrant instances

  - [x] 7.5 Implement `rag/ingest.py` — CLI ingestion script
    - Implement CLI: `python -m rag.ingest --company_id=company_a [--chunker_type=fixed]`
    - Load `data/<company_id>/coding_rules.md` and `data/<company_id>/chart_of_accounts.md`; instantiate `RAGEngine`; call `ingest()`
    - Print number of newly upserted chunks
    - _Requirements: 8.3_

  - [x] 7.6 Create 20 test queries per company for RAG evaluation
    - Create `rag/test_queries_company_a.json` — 20 queries in French and English targeting specific coding rules and chart-of-accounts entries for Company A
    - Create `rag/test_queries_company_b.json` — 20 queries in French and English for Company B
    - Each query entry: `{"query": str, "expected_sources": list[str]}`
    - _Requirements: 8.6_

- [x] 8. Evaluation scorers

  - [x] 8.1 Implement `eval/scorers.py` — `extractor_score`, `coder_score`, `validator_score`
    - Create `eval/__init__.py` (empty)
    - Implement `normalize(s: str) -> str`: strip, lowercase, NFC normalize, remove whitespace, replace `,` with `.` for French number format
    - Implement `extractor_score(predicted: dict, gold: dict) -> float` — normalized exact match across all gold keys; return `1.0` if `gold` is empty
    - Implement `coder_score(predicted: dict, gold: dict, skill_text: str, chunks: list[dict]) -> float` — binary: `1.0` iff code matches AND `cited_rule` (≥10 chars) appears as substring in `skill_text` or any chunk text
    - Implement `validator_score(predicted: list[str], reference: list[str]) -> float` — F1 with β=√2 (FN cost 2×); return `1.0` for both-empty case
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x]* 8.2 Write property tests for scorers — Properties 8, 9, 16
    - Create `tests/unit/test_scorers.py`
    - **Property 8: Normalizer idempotence on equivalent strings** — `@given(pairs)` where strings differ only in whitespace/case/French format; assert `normalize(a) == normalize(b)` → `extractor_score == 1.0`
      - Tag: `# Feature: n8n-multiagent-doc-pipeline, Property 8: Normalizer idempotence`
      - **Validates: Requirements 5.1**
    - **Property 9: Coder scorer is strictly binary** — `@given(code, cited, gold_code)` assert `coder_score()` returns exactly `0.0` or `1.0`
      - Tag: `# Feature: n8n-multiagent-doc-pipeline, Property 9: Binary coder score`
      - **Validates: Requirements 5.2**
    - **Property 16: Validator scorer returns 1.0 for empty inputs** — assert `validator_score([], []) == 1.0`
      - Tag: `# Feature: n8n-multiagent-doc-pipeline, Property 16: Empty validator score`
      - **Validates: Requirements 5.4, 16.7**
    - `@settings(max_examples=100)`

- [x] 9. FastAPI backend

  - [x] 9.1 Implement `api/db.py` — `TraceStore` with SQLite
    - Create `api/__init__.py` (empty)
    - Implement `TraceStore.__init__(db_path: str = "./traces.db")` — create table with schema from design:
      ```sql
      CREATE TABLE IF NOT EXISTS traces (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL, step TEXT NOT NULL, status TEXT NOT NULL, duration_ms INTEGER NOT NULL, output_json TEXT NOT NULL, chunks_json TEXT NOT NULL DEFAULT '[]', skill_version TEXT NOT NULL, timestamp TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS idx_traces_doc_id ON traces(doc_id);
      ```
    - Implement `write(trace: TraceEvent) -> None`
    - Implement `get_by_doc_id(doc_id: str) -> list[TraceEvent]` — ordered by timestamp
    - Implement `doc_id_exists(doc_id: str) -> bool`
    - _Requirements: 6.3, 6.4_

  - [x] 9.2 Implement `api/models.py` — all Pydantic request/response models
    - Implement all request models: `RouteRequest`, `ExtractRequest`, `CodeRequest`, `ValidateRequest`, `HandleRequest`, `AcceptRequest`, `EscalateRequest`, `FailRequest`
    - Implement all response models: `RouteResponse`, `ExtractResponse`, `CodeResponse`, `ValidateResponse`, `HandleResponse`, `HealthResponse`
    - Implement `TraceEvent` and `GoldDocument` models exactly as specified in the design Data Models section
    - _Requirements: 6.1_

  - [x] 9.3 Implement `api/main.py` — FastAPI app with all 10 endpoints
    - Create FastAPI app with CORS middleware allowing all origins (`*`)
    - Implement all 10 endpoints: `POST /route`, `POST /extract`, `POST /code`, `POST /validate`, `POST /handle`, `POST /accept`, `POST /escalate`, `POST /fail`, `GET /trace/{id}`, `GET /health`
    - Each POST handler: record start time `t0 = time.monotonic()`; call agent; compute `duration_ms`; write `TraceEvent` to SQLite; return response model
    - Use `./inbox` directory for file transit
    - `GET /health`: check Qdrant (`client.get_collections()`), SQLite (`SELECT 1`), LLM_Client (env var presence only — no network call); return 200 `{"status":"ok"}` or 503 with failing component name
    - Expose no other endpoints
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x]* 9.4 Write integration tests for API endpoints — Property 10
    - Create `tests/integration/test_api_endpoints.py`
    - Smoke test: `GET /health` returns 200 with all component keys
    - Example test: `POST /route` with demo PDF → returns valid `doc_type` and `modality`
    - **Property 10: Trace completeness after every pipeline step** — `@given(pipeline_step_call)` for each POST endpoint; assert SQLite row written with non-null `step`, `status`, `duration_ms`, `skill_version`
      - Tag: `# Feature: n8n-multiagent-doc-pipeline, Property 10: Trace completeness`
      - **Validates: Requirements 6.3, 16.5**
    - Assert exactly 10 routes are registered (no extras)
    - `@settings(max_examples=100)`

- [x] 10. Checkpoint — Backend API complete
  - Run `pytest tests/unit/ tests/integration/` and ensure all tests pass. Verify `GET /health` returns 200. Ask the user if questions arise.

- [x] 11. n8n Workflow (MOST GRADED)

  - [x] 11.1 Create `n8n/pipeline_workflow.json` — importable n8n workflow with 12 nodes
    - Create valid JSON file importable via `n8n import:workflow --input=n8n/pipeline_workflow.json`
    - Include exactly these named nodes: `Webhook`, `Router`, `Switch (modality)`, `Extractor`, `Coder`, `Validator`, `IF (needs_review)`, `Exception_Handler`, `Escalate`, `Accept`, `Respond`, `Fail`
    - Implement the sequence: `Webhook → Router → Switch(modality) → Extractor → Coder → Validator → IF(needs_review) → (Exception_Handler → Escalate | Accept) → Respond`
    - Add error branch: `Error → Fail (POST /fail) → Respond`
    - Configure all agent nodes (`Router`, `Extractor`, `Coder`, `Validator`, `Exception_Handler`) with `"retryOnFail": true, "maxTries": 2, "waitBetweenTries": 1000`
    - Each agent node calls corresponding FastAPI endpoint: `POST http://localhost:8000/{route|extract|code|validate|handle}`
    - `Accept` node calls `POST /accept`; `Escalate` node calls `POST /escalate`; `Fail` node calls `POST /fail`
    - Add sticky notes to canvas describing pipeline architecture (at minimum: overview note, agent descriptions, data flow note)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [x] 11.2 Create `n8n/import_and_activate.sh` — import and activate script
    - Script: `n8n import:workflow --input=n8n/pipeline_workflow.json && n8n update:workflow --id=<id> --active=true`
    - Include curl test command: `curl -X POST http://localhost:5678/webhook/pipeline -H "Content-Type: application/json" -d '{"doc_id":"test","company_id":"company_a","file_b64":"...","filename":"test.pdf"}'`
    - Export tested workflow back: `n8n export:workflow --id=<id> --output=n8n/pipeline_workflow.json`
    - _Requirements: 7.7, 7.8, 7.9_

- [x] 12. Multimodality

  - [x] 12.1 Implement `agents/multimodal.py` — PDF text extraction and vision transcription
    - Implement `extract_text_from_pdf(file_path: str) -> str` using `pypdf`; return extracted text
    - Implement `transcribe_image_via_vision(image_b64: str, llm_client: LLMClient) -> str` — call `llm_client.call(role="vision", ...)` with base64 image; return transcription text
    - _Requirements: 9.1, 9.2_

  - [x] 12.2 Wire modality detection into `RouterAgent` and FastAPI `/route` handler
    - In `POST /route`: if file is PDF with text layer (pypdf extracts >10 chars), set `modality="text"`; else set `modality="photo"` and pass to vision transcription
    - Ensure `RouterAgent` receives the correct `modality` from file analysis
    - n8n `Switch(modality)` node correctly routes `text` branch vs `photo` branch to `Extractor`
    - _Requirements: 9.3, 9.4_

- [x] 13. RAG retrieval evaluation

  - [x] 13.1 Implement `eval/retrieval_eval.py` — Recall@5 and MRR@5 evaluation
    - Load test queries from `rag/test_queries_company_a.json` and `rag/test_queries_company_b.json`
    - For each query: call `RAGEngine.search(query, top_k=5)`; compute Recall@5 (fraction of expected sources retrieved) and MRR@5 (mean reciprocal rank of first relevant result)
    - Aggregate scores per company
    - Write results with comments to `eval/results/retrieval_eval.md` — include per-query scores and aggregates
    - _Requirements: 8.6, 8.7_

- [x] 14. Baseline evaluation

  - [x] 14.1 Implement `eval/baseline.py` — SELECTION set evaluation with v001 skills
    - Accept CLI args: `--company company_a|company_b --split selection`
    - Load SELECTION split from `data/splits.json`; load gold JSONs
    - Run each agent in sequence on each document using skills v001
    - Compute scores: Extractor NEM via `extractor_score`, Coder binary via `coder_score` (with RAG and without RAG), Validator F-beta via `validator_score`
    - Record real failures for prompt correction
    - Write results to `eval/results/baseline.md` with columns: `agent | score_v001 | score_v001_no_rag | score_v002` (v002 column left as placeholder until v002 created)
    - Only real execution values — no estimated scores
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 14.2 Create v002 skill files after observing real baseline failures
    - After running `eval/baseline.py`, review failures logged in `eval/results/baseline.md`
    - Create corrected skill files `skills/company_a/<agent>/v002.md` and `skills/company_b/<agent>/v002.md` for agents where failures were observed
    - Re-run `eval/baseline.py` with v002 skills; update `eval/results/baseline.md` with v002 scores
    - _Requirements: 10.4, 10.5_

- [x] 15. Prompt library

  - [x] 15.1 Create `prompts/PROMPT_LIBRARY.md` from real runs
    - Create one entry per agent skill version used in the system
    - Each entry documents: agent role, technique used (few-shot/chain-of-thought/structured output/role prompting/guardrails), failures observed from real executions, correction applied, scores before/after
    - No hypothetical failures — only observations from actual baseline runs
    - _Requirements: 11.1, 11.2, 11.3_

- [x] 16. UI integration — wire React app to real FastAPI and n8n

  - [x] 16.1 Create `ui/.env.local` and shared API client
    - Create `ui/.env.local`:
      ```
      NEXT_PUBLIC_API_URL=http://localhost:8000
      NEXT_PUBLIC_N8N_WEBHOOK_URL=http://localhost:5678/webhook/pipeline
      ```
    - Create `ui/lib/api.ts` — typed fetch wrapper for all FastAPI endpoints and n8n webhook
    - _Requirements: 12.1, 12.2_

  - [x] 16.2 Implement Command Center page (`/command-center`) with real data
    - Replace static content in `ui/app/command-center/page.tsx` with:
      - `<DocumentUploader />` component — drag & drop or file picker; on submit POST to n8n webhook
      - `<PipelineProgress />` component — 5 stage cards: Router, Extractor, Coder, Validator, Decision; each card shows pending/running/success/error state mapped from SQLite step names
      - Polling logic: `setInterval(() => fetch(\`/trace/\${docId}\`), 500)` — stop when `accept`, `escalate`, or `fail` step found
      - `<KPIBar />` — docs processed today, acceptance rate, escalation rate (aggregate from trace history)
      - `<DecisionBadge />` — `ACCEPTED` (green) or `ESCALATED` (amber) badge at end of processing
    - _Requirements: 12.3, 12.4_

  - [x] 16.3 Implement Agent Network page (`/agent-network`) with real data
    - Replace mock agents in `ui/app/agent-network/page.tsx` with the 5 real agents: Router, Extractor, Coder, Validator, ExceptionHandler
    - Display real-time status (idle/processing/error) from latest traces
    - Show skill version currently loaded (from most recent trace `skill_version` field)
    - Show duration of last call (from `duration_ms` field)
    - _Requirements: 12.5_

  - [x] 16.4 Implement Operations page (`/operations`) with real data
    - Replace mock data in `ui/app/operations/page.tsx` with list of processed documents from `GET /trace/{id}` (aggregated)
    - Detailed trace view: timeline of all steps for selected document with durations and output previews
    - _Requirements: 12.6_

  - [x] 16.5 Implement Intelligence page (`/intelligence`) with real data
    - Replace mock data in `ui/app/intelligence/page.tsx` with RAG chunk display: list chunks with cosine similarity bars
    - Display Recall@5 / MRR@5 table loaded from `eval/results/retrieval_eval.md`
    - _Requirements: 12.7_

  - [x] 16.6 Implement Systems page (`/systems`) with real health data
    - Replace mock status in `ui/app/systems/page.tsx` with real `GET /health` polling every 5 seconds
    - Display component status cards: FastAPI, n8n, Qdrant_Local, LLM_Client
    - _Requirements: 12.8_

  - [x] 16.7 Implement `streamlit_app.py` — fallback UI if `./ui` absent
    - Implement file uploader → POST to n8n webhook → poll `/trace` → display 5 status columns matching Command Center layout
    - _Requirements: 12.9_

- [x] 17. Checkpoint — Full pipeline end-to-end
  - Process all 4 demo documents through the full pipeline; verify each produces `ACCEPTED` or `ESCALATED` without unhandled exceptions. Run `pytest tests/e2e/`. Ask the user if questions arise.

- [x] 18. End-to-end pipeline test — Property 18

  - [x] 18.1 Write end-to-end test for demo documents — Property 18
    - Create `tests/e2e/test_demo_pipeline.py`
    - **Property 18: Pipeline termination for demo documents** — for each of the 4 files in `demo/`, process through full pipeline; assert final trace step is `"accept"` or `"escalate"` (not an exception)
      - Tag: `# Feature: n8n-multiagent-doc-pipeline, Property 18: Pipeline termination`
      - **Validates: Requirements 16.10**
    - _Requirements: 16.10_

- [x] 19. `run.py` — single entry point

  - [x] 19.1 Implement `run.py` — start FastAPI + n8n + UI concurrently
    - Start three subprocesses concurrently:
      1. `uvicorn api.main:app --port 8000`
      2. `npx n8n@<pinned_version>` with env `N8N_PORT=5678`
      3. `pnpm dev` (cwd `./ui`) OR `streamlit run streamlit_app.py` if `./ui` absent
    - For each component: health-poll with 30s timeout
      - FastAPI: `GET http://localhost:8000/health`
      - n8n: `GET http://localhost:5678/healthz`
      - UI: TCP connect to port 3000 (Next.js) or 8501 (Streamlit)
    - If any component fails to respond within 30s: print `"ERROR: <component> failed to start"`, terminate all processes, `sys.exit(1)`
    - Pin n8n version (e.g. `n8n@1.x.x`) to match the installed compatible version
    - _Requirements: 13.1, 13.2, 13.3_

- [x] 20. Documentation

  - [x] 20.1 Create `docs/architecture.md`
    - Describe each agent's role, tools used, information flow between components
    - Justify multi-agent architecture vs. monolithic LLM call: separation of concerns, traceability, skill versioning, independent retry logic
    - Include ASCII architecture diagram (from design)
    - _Requirements: 15.1_

  - [x] 20.2 Create `DEMO.md` — 5-minute demonstration script
    - Cover: start system (`python run.py`), upload clean PDF via UI, follow 5 stage cards, upload photo variant, show escalation on arithmetic error document, show trace view, show RAG Intelligence view
    - No invented performance numbers — placeholder for real scores from baseline
    - _Requirements: 15.2_

  - [x] 20.3 Create `README.md` — setup in ≤10 command lines
    - Include: clone, install Python deps (`pip install -r requirements.txt`), copy `.env.template` to `.env` and fill in, ingest data (`python -m rag.ingest --company_id=company_a` and `company_b`), generate corpus (`python data/generator.py`), run (`python run.py`)
    - No invented performance numbers
    - _Requirements: 15.3_

- [x] 21. Stretch goal — SkillOpt optimization (optional)

  - [x]* 21.1 Install SkillOpt and document API in `docs/skillopt_api.md`
    - Attempt to install SkillOpt; document the API in `docs/skillopt_api.md`
    - If installation fails: record failure in `docs/failures.md` with exact error message and stop
    - _Requirements: 14.1_

  - [x]* 21.2 Run SkillOpt optimization on Extractor skill
    - Use TRAIN split for rollouts, SELECTION split for validation
    - Run exactly one optimization on `skills/<company>/extractor/v001.md`
    - If SkillOpt fails: record error in `docs/failures.md`, stop immediately — no simulation
    - Compare v001 vs best version on TEST set (read TEST set only here)
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

- [x] 22. Final checkpoint — All systems go
  - Run full test suite `pytest tests/`. Verify `python run.py` starts all three components. Process all demo documents. Confirm `eval/results/baseline.md` and `eval/results/retrieval_eval.md` contain real scores. Ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP (test tasks and stretch goals)
- The n8n workflow (Group 11) is the most heavily graded component — ensure it is complete, importable, and tested
- All evaluation scores in `.md` files must come from real executions — never invent numbers
- DEMO_CACHE=1 allows running demos without incurring LLM costs on repeated prompts
- The TEST set must never be accessed outside `eval/baseline.py` comparison step
- `real/` folder documents must never be used for prompt optimization
- Property-based tests use `hypothesis==6.123.4` with `@settings(max_examples=100)`
- Each PBT is tagged with `# Feature: n8n-multiagent-doc-pipeline, Property N: <text>`
- Company A account codes: `[A-Z0-9]{6}`; Company B: `[0-9]{4}-[A-Z]{2}[0-9]{3}`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2", "2.2", "4.3"] },
    { "id": 2, "tasks": ["1.3", "2.3", "2.4", "4.1", "4.2", "7.1", "8.1"] },
    { "id": 3, "tasks": ["5.1", "5.3", "5.5", "5.7", "5.9", "7.3", "8.2", "7.2", "9.1", "9.2"] },
    { "id": 4, "tasks": ["5.2", "5.4", "5.6", "5.8", "7.4", "7.5", "7.6", "9.3"] },
    { "id": 5, "tasks": ["9.4", "12.1", "12.2", "13.1"] },
    { "id": 6, "tasks": ["11.1", "14.1", "16.1"] },
    { "id": 7, "tasks": ["11.2", "14.2", "16.2", "16.3", "16.4", "16.5", "16.6", "16.7"] },
    { "id": 8, "tasks": ["15.1", "18.1", "19.1"] },
    { "id": 9, "tasks": ["20.1", "20.2", "20.3"] },
    { "id": 10, "tasks": ["21.1"] },
    { "id": 11, "tasks": ["21.2"] }
  ]
}
```
