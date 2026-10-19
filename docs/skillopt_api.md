# SkillOpt API Reference — DocDesk Integration

## Overview

SkillOpt v0.2.0 is the actual installed prompt-space optimization library used
by DocDesk. It runs model rollouts against labeled documents, analyzes failures,
and proposes bounded edits to a versioned skill. Model weights are unchanged.

The product integration optimizes the Company B **Extractor** skill. A custom
`EnvAdapter` calls the same installed library target API used by SkillOpt's
built-in environments, scores the production extraction contract, and stores
each trajectory for reflection and audit. The Company B Coder adapter remains
available as a separate experiment.

## Installation

SkillOpt is installed in a separate virtualenv at `.venv-skillopt/`:

```bash
python3 -m venv .venv-skillopt
source .venv-skillopt/bin/activate
pip install skillopt==0.2.0
```

## Architecture

### Components

| Component | File | Purpose |
|-----------|------|---------|
| Extractor adapter | `skillopt_envs/docdesk/extractor_adapter.py` | Extends SkillOpt `EnvAdapter` and runs production-field rollouts |
| Extractor scoring | `skillopt_envs/docdesk/extractor_rollout.py` | Calls target model, normalizes fields, scores hard/soft NEM, saves trajectories |
| DataLoader | `skillopt_envs/docdesk/dataloader.py` | Maps SkillOpt `valid_seen` to the project `selection` split |
| Balanced sampler | `scripts/prepare_skillopt_company_b.py` | Builds reproducible 12/12 vendor- and document-type-balanced samples |
| Wrapper | `scripts/skillopt_extractor.py` | Loads `.env`, pins the deployment, registers the adapter, invokes library trainer |
| Config | `configs/docdesk/company_b_extractor.yaml` | One-epoch run with soft selection gating and 4,096 target tokens |
| Product service | `api/skillopt_service.py` | Runs the actual CLI, snapshots data, applies strict promotion, exposes history |
| UI | `ui/components/skillopt-view.tsx` | Shows scores, target token usage, step decisions, and skill versions |

### Env Adapter Interface

The adapter (`DocDeskCoderAdapter`) extends `EnvAdapter` from
`skillopt.envs.base`. It accepts these `__init__` kwargs:

```python
DocDeskCoderAdapter(
    split_dir="skillopt_data",      # directory with train.json, selection.json
    data_path="",
    split_mode="split_dir",
    split_ratio="7:2:1",
    split_seed=42,
    split_output_dir="",
    workers=2,                      # parallel rollout workers
    analyst_workers=2,              # parallel reflection workers
    failure_only=False,             # only analyze failed rollouts
    minibatch_size=4,               # items per analyst round
    edit_budget=4,                  # max edits per epoch
    seed=42,
    limit=0,                        # 0 = all items; N = first N only
    max_completion_tokens=300,      # target model max tokens
)
```

### Rollout Function

`run_batch()` in `rollout.py` is called by the adapter's `rollout()` method:

1. For each item, retrieves RAG chunks from Qdrant for the document's company
2. Builds a user message with extracted fields + retrieved rules
3. Calls the target LLM (via `chat_target_messages`) with the skill as system prompt
4. Parses JSON response for `account_code` and `cited_rule`
5. Scores: **hard** = 1.0 iff code matches AND cited_rule found in skill/chunks; **soft** = 0.5 iff code matches but rule not verified
6. Saves conversation.json per item for the reflection step

### Data Format

`skillopt_data/train.json` (140 items) and `skillopt_data/selection.json` (60 items).

Each item:
```json
{
  "id": "A-DOC-0000",
  "company_id": "company_a",
  "doc_type": "invoice",
  "gold_fields": {"supplier": "STEG", "htva": 1000.0, "currency": "TND", ...},
  "gold_account_code": "606100"
}
```

## Config YAML Format

SkillOpt supports two config formats: **structured** (sections) and **flat**
(legacy). The DocDesk config uses the **structured** format.

### Structured Sections

| Section | Keys | Description |
|---------|------|-------------|
| `model:` | `backend`, `optimizer_*`, `target_*` | LLM backend and credentials |
| `train:` | `num_epochs`, `batch_size`, `seed` | Training loop params |
| `gradient:` | `minibatch_size`, `analyst_workers`, `failure_only` | Reflection params |
| `optimizer:` | `learning_rate` (= edit_budget) | Optimization params |
| `env:` | `name`, `out_root`, `skill_init`, + adapter kwargs | Environment config |

### Model Backend (openai_compatible)

The `openai_compatible` backend talks to any OpenAI-compatible endpoint.
Credentials are resolved from environment variables (not YAML strings):

| Env Var | Purpose |
|---------|---------|
| `OPTIMIZER_OPENAI_COMPATIBLE_BASE_URL` | Optimizer LLM endpoint |
| `OPTIMIZER_OPENAI_COMPATIBLE_API_KEY` | Optimizer API key |
| `OPTIMIZER_OPENAI_COMPATIBLE_MODEL` | Optimizer model name |
| `TARGET_OPENAI_COMPATIBLE_BASE_URL` | Target LLM endpoint |
| `TARGET_OPENAI_COMPATIBLE_API_KEY` | Target API key |
| `TARGET_OPENAI_COMPATIBLE_MODEL` | Target model name |
| `OPENAI_COMPATIBLE_BASE_URL` | Shared fallback (both roles) |
| `OPENAI_COMPATIBLE_API_KEY` | Shared fallback (both roles) |
| `OPENAI_COMPATIBLE_MODEL` | Shared fallback (both roles) |

The wrapper script (`scripts/skillopt_train.py`) loads `.env` and maps vars
**before** importing skillopt (the backend reads env vars at import time):
- `OPENAI_BASE_URL` → `*_OPENAI_COMPATIBLE_BASE_URL`
- `OPENAI_API_KEY` → `*_OPENAI_COMPATIBLE_API_KEY`
- `AGENT_DEPLOYMENT` → `*_OPENAI_COMPATIBLE_MODEL`

### Config File (`configs/docdesk/default.yaml`)

```yaml
model:
  backend: openai_compatible
  optimizer_openai_compatible_temperature: 0.0
  optimizer_openai_compatible_max_tokens: 4096
  target_openai_compatible_temperature: 0.0
  target_openai_compatible_max_tokens: 300

train:
  num_epochs: 1
  batch_size: 4
  seed: 42

gradient:
  minibatch_size: 4
  analyst_workers: 2
  failure_only: false

optimizer:
  learning_rate: 4

env:
  name: docdesk
  out_root: skillopt_output/docdesk
  skill_init: skills/company_a/coder/v001.md
  split_dir: skillopt_data
  seed: 42
  limit: 10
  workers: 2
  analyst_workers: 2
  minibatch_size: 4
  edit_budget: 4
  max_completion_tokens: 300
```

## Running the Smoke Test

```bash
source .venv-skillopt/bin/activate
python scripts/skillopt_train.py --config configs/docdesk/default.yaml
```

For a full run (remove `limit` from config, increase epochs):
```bash
python scripts/skillopt_train.py --config configs/docdesk/default.yaml \
    --cfg-options env.limit=0 train.num_epochs=3
```

## Output

Optimized skills are written to `skillopt_output/docdesk/`.
Compare v001 vs the best optimized version on the SELECTION set.

## Product run: Company B Extractor

Start a run from the **Skill History** section in the DocDesk UI, or use:

```bash
curl -X POST http://localhost:8000/skillopt/run
```

The service creates 12 TRAIN and 12 SELECTION documents from the project’s
Company B splits. Sampling balances suppliers and the invoice, purchase order,
and receipt classes. Each run snapshots both JSON splits and records their
SHA-256 hashes in `run_state.json`.

The target is the configured Azure Foundry `Kimi-K2.5` deployment. Its
4,096-token completion budget is required for visible JSON output from this
deployment; SkillOpt's package default `gpt-4o-mini` is not deployed on this
resource and must be overridden explicitly in YAML.

Scoring uses normalized exact match over the ten fields supported by the
production Extractor schema. Numeric values are compared as decimals, so
`0.600` equals `0.6`. Benchmark `reference_unique` is recorded as excluded
because it is absent from the API response schema; `line_descriptions` are
mapped from `lines[].description`. SkillOpt gates on the continuous soft score.
The product promotes a new immutable `vNNN.md` only on a strict selection gain;
otherwise it retains the current version.

The API endpoints are `GET /skillopt/summary`, `GET /skillopt/history`, and
`POST /skillopt/run`. The history endpoint includes target-model token usage,
per-step scores and decisions, run logs, dataset hashes, candidate skill text,
and runtime skill versions.

## Standing Rules

- Optimizer calls (SkillOpt) use **default reasoning** (no `reasoning_effort` override).
- Agent and vision calls in the pipeline use `reasoning_effort="none"`.
- Never print any part of an API key.
- If SkillOpt fails, record the error in `docs/failures.md` and stop.
- No simulation or workaround — only the real SkillOpt API is used.
