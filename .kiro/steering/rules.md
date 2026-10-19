# Standing Rules — n8n Multi-Agent Document Pipeline

These rules apply to every script, agent, evaluation, and report in this project.
Violations must be recorded in docs/failures.md.

## LLM calls
- All agent and vision calls use `reasoning_effort="none"` (Instant mode).
- Optimizer calls (SkillOpt) use default reasoning (no override).
- Never rely on `max_tokens` small values to control reasoning; use the switch.
- Strip `reasoning_content` from all outputs before passing to the pipeline.
- Log actual reasoning tokens from `usage.completion_tokens_details.reasoning_tokens`, not estimates.

## Data integrity
- Document IDs are globally unique: Company A uses prefix `A-DOC-NNNN`, Company B uses `B-DOC-NNNN`.
- No document ID appears in more than one split. Duplicates (seeded error type) use a `duplicate_of` field and a fresh unique ID.
- Every gold label: `total_ttc == sum(line.ttc for line in lines)` except for docs with `injected_error == arithmetic_mismatch`.
- Account codes in gold labels must exist in the company's chart of accounts.
- House-rule text must not appear verbatim in any public knowledge file.
- Amounts stored as strings in French format (`1 011,500`). Comparisons use `Decimal` with 3-place tolerance `0.005`.
- The Tunisian tax ID field is called `matricule_fiscal` (format: 7 digits + letter, e.g. `1234567A`).
- Every generated document includes a `reference_unique` field (independent of corpus index).

## Secrets
- Never print any part of an API key, even the first N characters.
- Print only `set (N chars)` and the endpoint hostname.
- `.env` is gitignored. Only `.env.example` is committed.

## Evaluation
- Every results file header must include: date, git commit (with `-dirty` if uncommitted), model IDs, reasoning mode, N, seed.
- A `make verify` command must fail if any results file contains placeholders (`TBD`, `XX`, `0.00` with no run, `*run to fill*`).
- All scores come from real pipeline runs. Never invent or estimate a number.
- Report per split, per company, per agent.
- Statistical claims require sample size and 95% confidence interval.

## No stubs
- No function returns fake data silently. If a dependency is missing, raise a clear error.
- If pypdf, reportlab, Pillow, or qdrant-client are not installed, raise `ImportError` with install instructions.
- The Coder agent raises `RAGCollectionEmptyError` if the Qdrant collection for the company is empty.

## Chart of accounts
- The chart is described as "inspired by the Tunisian SCE class-6 structure, not verified against an official source".
- Account numbers are marked as unverified and must be checked against an official source before any production use.
