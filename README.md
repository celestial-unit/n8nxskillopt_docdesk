# DocDesk — n8n × SkillOpt Multi-Agent Accounting Pipeline

> Automate Tunisian accounting document processing (invoices, receipts, purchase orders) with five specialized LLM agents, RAG-grounded account coding, and automated prompt optimization via SkillOpt.

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com/)
[![n8n](https://img.shields.io/badge/n8n-2.35.7-orange.svg)](https://n8n.io/)
[![SkillOpt](https://img.shields.io/badge/SkillOpt-0.2.0-purple.svg)](https://arxiv.org/abs/2605.23904)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What it does

A document arrives (PDF or photo scan) → five agents process it in sequence → it exits as **ACCEPTED** (auto-filed) or **ESCALATED** (sent to a human reviewer), with a full audit trace and a cited accounting rule.

| Step | Agent | What it does |
|------|-------|-------------|
| 1 | **Router** | Detects document type and modality (text / photo) |
| 2 | **Extractor** | Pulls all structured fields: supplier, date, amounts, matricule fiscal |
| 3 | **Coder** | Assigns the correct ledger code using RAG over company-specific rules |
| 4 | **Validator** | Python arithmetic + identifier checks, LLM explanation |
| 5 | **Exception Handler** | Builds a structured escalation dossier for the human reviewer |

**Business value:** 3–5 minutes per invoice → ~8 seconds.

---

## Architecture

```
                    ┌─────────────────────────────────────┐
                    │         python run.py                │
  ┌─────────────┐   ┌──────────────┐   ┌──────────────┐   │
  │ FastAPI     │   │ n8n          │   │ React UI     │   │
  │ :8000       │◄──│ :5678        │◄──│ :3000        │   │
  └──────┬──────┘   └──────────────┘   └──────────────┘   │
         │                                                  │
         ▼                                                  │
  ┌──────────────────────────────────────────────────────┐ │
  │  Router → Extractor → Coder+RAG → Validator → Decision│ │
  │           ↓ every step       ↓ RAG                   │ │
  │      SQLite traces.db    Qdrant local                 │ │
  └──────────────────────────────────────────────────────┘ │
                                                            │
  SkillOpt (offline) optimizes skill .md files from traces  │
  └─────────────────────────────────────────────────────────┘
```

> **Interactive diagram:** open [`docs/architecture.excalidraw`](docs/architecture.excalidraw) at [excalidraw.com](https://excalidraw.com) by dragging the file onto the canvas.

---

## Quick Start

### Prerequisites

- Python 3.12
- Node.js 18+ with pnpm (`npm i -g pnpm`)
- n8n 2.x (`npm i -g n8n`)
- An Azure AI Foundry endpoint **or** any OpenAI-compatible endpoint

### 1. Clone & install

```bash
git clone https://github.com/celestial-unit/n8nxskillopt_docdesk.git
cd n8nxskillopt_docdesk

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cd ui && pnpm install && cd ..
```

### 2. Configure credentials

```bash
cp .env.template .env
# Edit .env — fill in your LLM endpoint, API key, and deployment names
```

Required variables in `.env`:

```
AZURE_ENDPOINT=https://your-resource.services.ai.azure.com/openai/v1/
AZURE_API_KEY=your-key
AGENT_DEPLOYMENT=Kimi-K2.5
VISION_DEPLOYMENT=Kimi-K2.5
OPTIMIZER_DEPLOYMENT=Kimi-K2.5
AGENT_REASONING_EFFORT=none
```

### 3. Generate corpus and ingest rules

```bash
python3 -m data.generator           # generates 300 synthetic documents (seed=42)
python3 -m rag.ingest --company_id=all   # loads rules into Qdrant
```

### 4. Start everything

```bash
python3 run.py
# FastAPI :8000 + n8n :5678 + UI :3000 start concurrently
```

### 5. Import the n8n workflow

```bash
bash n8n/import_and_activate.sh
```

Or manually: open [http://localhost:5678](http://localhost:5678) → Import → select `n8n/pipeline_workflow.json` → Activate.

---

## Project Structure

```
docdesk/
├── agents/                  # Five LLM agents (one call each)
│   ├── llm_client.py        # Unified Azure/OpenAI client, temp=0, cache
│   ├── router_agent.py
│   ├── extractor_agent.py
│   ├── coder_agent.py       # RAG + LLM
│   ├── validator_agent.py   # Python checks + LLM explanation
│   └── exception_handler_agent.py
├── api/
│   ├── main.py              # FastAPI: 10 endpoints
│   ├── db.py                # SQLite trace store
│   └── models.py            # Pydantic request/response models
├── rag/
│   ├── engine.py            # Qdrant embedded, cosine similarity
│   ├── chunkers.py          # FixedChunker + SemanticChunker
│   └── ingest.py            # CLI: python -m rag.ingest
├── data/
│   ├── generator.py         # Deterministic corpus generator (seed=42)
│   ├── company_a/           # coding_rules.md, chart_of_accounts.md, house_rules.md
│   └── company_b/
├── skills/
│   ├── company_a/           # Versioned skill prompts: extractor/v001.md, coder/v001.md …
│   └── company_b/
├── skillopt_envs/docdesk/   # SkillOpt environment adapter
│   ├── adapter.py
│   ├── dataloader.py
│   └── rollout.py
├── configs/docdesk/
│   ├── default.yaml         # SkillOpt coder config
│   └── extractor.yaml       # SkillOpt extractor config
├── scripts/
│   ├── skillopt_train.py    # Run SkillOpt on Coder skill
│   ├── skillopt_extractor.py# Run SkillOpt on Extractor skill
│   └── doctor_v3.py         # LLM health check + benchmarks
├── eval/
│   ├── scorers.py           # NEM, binary coder score, F-β validator
│   ├── baseline.py          # Runs full evaluation on SELECTION set
│   └── results/             # baseline.md, retrieval_eval.md, doctor.md
├── tests/
│   ├── unit/                # Hypothesis property-based tests
│   └── integration/
├── n8n/
│   ├── pipeline_workflow.json  # Importable workflow (14 nodes)
│   └── import_and_activate.sh
├── ui/                      # Next.js 15 + Tailwind cyberpunk dashboard
├── docs/
│   ├── architecture.md
│   ├── architecture.excalidraw  # Editable diagram
│   └── skillopt_api.md
├── demo/                    # 4 pre-generated demo documents
├── report/                  # IEEE-style LaTeX report (source only)
│   ├── main.tex
│   ├── sections/
│   └── references.bib
├── .env.template            # Credential template
├── requirements.txt
├── run.py                   # Single entry point
└── DEMO.md                  # 5-minute demo script
```

---

## Evaluation Results

All numbers from real pipeline runs on the **SELECTION set** (60 documents, skill v001).

### Agent Scores

| Company | Extractor NEM | Coder + RAG | Coder no RAG | Validator F-β |
|---------|:---:|:---:|:---:|:---:|
| Company A (N=30) | 0.606 | 0.300 | 0.100 | 0.108 |
| Company B (N=30) | 0.311 | 0.205 | 0.000 | 0.000 |

**RAG provides a 3× lift** for Company A Coder (0.10 → 0.30) and is the difference between 0 and a working system for Company B.

### RAG Retrieval

| Company | Recall@5 | MRR@5 |
|---------|:---:|:---:|
| Company A | 1.000 | 0.825 |
| Company B | 1.000 | 0.717 |

### Latency (Kimi-K2.5, `reasoning_effort=none`)

| Metric | Value |
|--------|-------|
| Median per agent call | 1,688 ms |
| p95 per agent call | 2,765 ms |
| Full pipeline (5 agents) | ~8–10 s |
| Vision accuracy (12 docs) | 100% supplier + TTC |

---

## SkillOpt Integration

DocDesk uses [SkillOpt](https://arxiv.org/abs/2605.23904) (Microsoft Research, 2026) to automatically improve agent skill files from observed failures — without changing model weights.

```
Skill v001.md
    │
    ▼ Target model runs on training examples
Rollout failures
    │
    ▼ Optimizer proposes bounded add/delete/replace edits
Candidate edit
    │
    ▼ Validation gate: accept only if score improves
Best skill (promoted to v002.md, v003.md ...)
```

**Run SkillOpt on the Coder skill:**
```bash
source .venv-skillopt/bin/activate
python scripts/skillopt_train.py --config configs/docdesk/default.yaml
```

**Run SkillOpt on the Extractor skill:**
```bash
python scripts/skillopt_extractor.py --config configs/docdesk/extractor.yaml
```

Output lands in `skillopt_output/`. Compare `best_skill.md` against `v001.md` and promote manually.

---

## Running Tests

```bash
source .venv/bin/activate
pytest tests/unit/ -q              # 31 unit + property-based tests
pytest tests/integration/ -q       # requires running FastAPI
```

---

## Running Evaluation

```bash
# LLM health check first
python scripts/doctor_v3.py

# Baseline scores on SELECTION set
python3 -m eval.baseline

# RAG retrieval metrics
python3 -m eval.retrieval_eval
```

Results are written to `eval/results/`.

---

## Demo (5 minutes)

See [DEMO.md](DEMO.md) for a step-by-step walkthrough covering:
1. System health check
2. Clean invoice → ACCEPTED
3. Photo scan → multimodal path
4. Arithmetic error → ESCALATED
5. Trace view + Agent Network in the UI

---

## Why Multi-Agent?

| Property | Multi-agent (DocDesk) | Single LLM call |
|----------|:---------------------:|:---------------:|
| Mid-pipeline retry | ✅ n8n ×2 per node | ✗ |
| Per-step audit trail | ✅ SQLite | ✗ |
| Independent skill versioning | ✅ | ✗ |
| RAG injection point | ✅ Coder only | Context bloat |
| Deterministic validation | ✅ Python | Hallucination risk |
| SkillOpt target | ✅ Per-agent | Global only |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Orchestration | [n8n](https://n8n.io) 2.35.7 |
| Backend | FastAPI 0.115 + uvicorn |
| LLM | Kimi-K2.5 via Azure AI Foundry |
| Vector store | [Qdrant](https://qdrant.tech) 1.12 (embedded) |
| Embeddings | `paraphrase-multilingual-mpnet-base-v2` |
| Prompt optimization | [SkillOpt](https://arxiv.org/abs/2605.23904) 0.2.0 |
| Dashboard | Next.js 15 + Tailwind CSS |
| Tests | pytest + Hypothesis (property-based) |
| PDF generation | ReportLab 4.2 |

---

## Configuration Reference

| Variable | Description |
|----------|-------------|
| `AZURE_ENDPOINT` | Azure AI Foundry endpoint URL |
| `AZURE_API_KEY` | API key (never commit this) |
| `AGENT_DEPLOYMENT` | Deployment name for agent calls |
| `VISION_DEPLOYMENT` | Deployment name for vision/OCR |
| `OPTIMIZER_DEPLOYMENT` | Deployment name for SkillOpt optimizer |
| `AGENT_REASONING_EFFORT` | `none` disables reasoning (saves ~10s/call) |
| `DEMO_CACHE` | Set to `1` to cache LLM responses by prompt hash |
| `OPENAI_BASE_URL` | Alternative to Azure: any OpenAI-compatible endpoint |
| `OPENAI_API_KEY` | API key for OpenAI-compatible endpoint |

---

## Contributing

1. Fork the repo
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Never commit `.env` — it's in `.gitignore`
4. Run `pytest tests/unit/ -q` before pushing
5. Open a PR against `master`

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

## Citation

If you use DocDesk or build on this work:

```bibtex
@misc{docdesk2026,
  title  = {DocDesk: A Multi-Agent LLM Pipeline for Automated Tunisian Accounting Document Processing},
  author = {Ghdhoun, Mohamed Aziz},
  year   = {2026},
  url    = {https://github.com/celestial-unit/n8nxskillopt_docdesk}
}
```

SkillOpt paper:
```bibtex
@misc{skillopt2026,
  title         = {SkillOpt: Executive Strategy for Self-Evolving Agent Skills},
  author        = {Yang, Yifan and others},
  year          = {2026},
  eprint        = {2605.23904},
  archivePrefix = {arXiv}
}
```
