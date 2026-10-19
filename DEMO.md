# Demo Script — 5 Minutes

## Prerequisites
```bash
cp .env.template .env   # fill in your Azure/OpenAI credentials
pip3 install -r requirements.txt
python3 -m data.generator
python3 -m rag.ingest --company_id=all
python3 run.py           # starts FastAPI + n8n + UI
```

---

## Minute 1 — System Health

Open http://localhost:8000/docs → show the 10 endpoints.

```bash
curl http://localhost:8000/health
# → {"status": "ok", "components": {"sqlite": "ok", "qdrant": "ok", "llm": "ok"}}
```

Open http://localhost:3000 (or http://localhost:8501 for Streamlit fallback).
Click **Systems** tab — all components green.

---

## Minute 2 — Clean PDF (text-layer)

In the UI, **Command Center** tab:
- Pick file: `demo/clean_invoice.pdf`
- Company: `company_a`
- Click **▶ Run**

Watch the 5 stage cards light up: Router → Extractor → Coder → Validator → Decision.

Expected result: **ACCEPTED** badge (clean invoice, no errors).

---

## Minute 3 — Photo Variant (multimodal)

- Pick file: `demo/photo_receipt.jpg`
- Company: `company_a`
- Click **▶ Run**

The Router detects `modality=photo` → vision LLM transcribes → same pipeline.
Show the **Intelligence** tab: retrieved RAG chunks with similarity scores.

---

## Minute 4 — Arithmetic Error Document

- Pick file: `demo/arithmetic_error.pdf`
- Company: `company_a`
- Click **▶ Run**

Expected result: **ESCALATED** badge.
The Validator Python check detects `arithmetic_mismatch` (HTVA + TVA ≠ TTC).
Show the trace detail: validation step with `errors: ["arithmetic_mismatch"]`.

---

## Minute 5 — Trace View & Agent Network

Click **Operations** tab:
- List of all processed documents with doc_ids
- Click any doc → full trace timeline (step, duration_ms, skill_version)

Click **Agent Network**:
- 5 agent cards showing status and current skill version (v001)

Point out the n8n canvas at http://localhost:5678:
- Visual workflow with sticky notes
- 12 named nodes: Webhook → Router → Switch → Extractor → Coder → Validator → IF → ...

---

## Key Numbers (from real runs)

Measured baseline and retrieval results already recorded in
`eval/results/baseline.md` and `eval/results/retrieval_eval.md`:

| Metric | Value |
|--------|-------|
| Extractor NEM (SELECTION), company A / B | 0.6061 / 0.3106 |
| Coder score with RAG, company A / B | 0.3000 / 0.2051 |
| Coder score without RAG, company A / B | 0.1000 / 0.0000 |
| Validator F-β, company A / B | 0.1083 / 0.0000 |
| RAG Recall@5, company A / B | 1.0000 / 1.0000 |
| RAG MRR@5, company A / B | 0.8250 / 0.7167 |

SkillOpt was attempted once but returned empty SELECTION and TEST sets and
selected `gpt-4o-mini` instead of the project deployment. It produced no valid
optimization or TEST comparison; see `docs/failures.md`.
