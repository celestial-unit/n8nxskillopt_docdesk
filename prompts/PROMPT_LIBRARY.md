# Prompt Library and Evaluation Notes

This annex summarizes the prompts, versions, and measured evidence. Full
operational prompt text remains versioned under `skills/` and
`prompts/iterations/`.

## Company B Coder

**Role:** assign a Company B ledger code from extracted invoice fields and
company-filtered rules; return a supporting citation.

**Techniques:** role prompting, company context, structured JSON, citation
constraint, retrieval-grounded policy.

| Version | Prompt change | Evidence |
|---|---|---|
| v001 | Baseline chain-of-thought instruction and JSON schema; `prompts/iterations/company_b_coder_v001_baseline.md` | Baseline outputs sometimes included prose before JSON. |
| v002 | JSON-only output, no private reasoning, explicit output contract; `prompts/iterations/company_b_coder_v002_candidate.md` | Rate-limited paired run: 12 valid pairs, supported code score 9/12 vs 8/12. Incomplete and inconclusive. |
| v003 | TRAIN-derived exception: TechVision consulting, audit, research, and honoraria map to `6226-HO001`; technical IT remains `6170-IT001`; cite the exact rule. See `skills/company_b/coder/v003.md`. | On four targeted SELECTION cases with gold extracted fields, supported coding rose from 0/4 to 4/4. Narrow, not end-to-end evidence. |
| v004 | Explicit supplier-to-account map, supplier-first decisions for this benchmark, TechVision line-description exception, and short verbatim citations. See `skills/company_b/coder/v004.md`. | Paired fixed sample (N=10, SELECTION; gold fields and identical top-5 RAG): code accuracy 7/10->9/10; supported code+citation 2/10->6/10; 4 wins, 0 losses, 6 ties. Selection-only early evidence. |

## Extractor

**Role:** extract supplier, invoice identifiers, dates, currency, amounts,
line items, taxes, and fiscal identifiers as schema-valid JSON.

**Techniques:** role prompting, explicit schema, date and amount formatting
rules, multilingual field guidance, JSON-only output.

The old full-corpus NEM values 0.6061 / 0.3106 are withdrawn because their
scorer counted a benchmark-only field and did not map nested production line
items. Do not report these as valid accuracy results. The corrected broad
baseline has not been rerun.

## SkillOpt production-skill run

The integrated SkillOpt 0.2.0 pilot used 12 TRAIN, 20 SELECTION, and 10 TEST
Company B documents. The initial Extractor skill scored 1.00 hard exact match
on SELECTION; all three failure-only steps skipped edits. After retrying six
provider failures, both the original and selected (identical) skill scored
10/10 exact on TEST. This is a no-change result, not an optimization gain.
See `eval/results/company_b_extractor_skillopt.json`.

## Deliberately weak SkillOpt showcase

The isolated demo-only starting prompt in
`prompts/iterations/skillopt_showcase/weak_extractor.md` instructs the model to
return `UNKNOWN` rather than extract. SkillOpt accepted two candidate updates
and skipped one step.

| Split | Weak prompt | Selected skill | Metric |
|---|---:|---:|---|
| SELECTION (N=20) | 0.01 | 0.21 | Soft normalized exact match (NEM) |
| TEST (N=10) | 0.02 | 0.17 | Soft normalized exact match (NEM) |
| TEST (N=10) | 0/10 | 0/10 | Strict hard exact match |

This synthetic demonstration improves partial-field overlap, while no complete
document is an exact match. It is not a normal production baseline or a claim
of reliable extraction. See
`eval/results/skillopt_improvement_showcase.json` and
`skillopt_output/company_b_extractor_showcase/`.

## Coder baseline and RAG ablation

On the existing SELECTION baseline, Company A scored 0.30 with RAG and 0.10
without; Company B scored 0.2051 and 0.00. A controlled Company B prompt
comparison on 10 fixed SELECTION documents raised code accuracy 70%->90% and
supported code+citation 20%->60%. It used gold extracted fields and is not
full-pipeline or held-out TEST evidence. See `eval/results/baseline.md` and
`eval/results/company_b_coder_improvement.json`.

## Validator

The Validator combines deterministic Python checks with an LLM-generated
review explanation. Baseline F-beta (beta=sqrt(2)) was 0.1083 for Company A and
0.0000 for Company B. The current API also checks normalized company, supplier,
invoice-number, and date keys against the SQLite ledger. The baseline metric
predates that duplicate check and has not been rerun.
