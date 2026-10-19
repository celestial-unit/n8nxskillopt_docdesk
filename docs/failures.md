# Recorded Failures

## SkillOpt Extractor run — 2026-10-19

The required SkillOpt Extractor optimization was attempted once with
`configs/docdesk/extractor.yaml`, using the project deployment overrides and
the TEST comparison enabled. Output was isolated at
`/tmp/final_dlexam_skillopt_extractor_run`.

The initial run did not produce a valid optimization or evaluation:

- SkillOpt printed `Selection items: 0` and later `Test items: 0` for both TEST
  evaluations. No comparison score can be reported from empty splits.
- Despite passing the project deployment as both
  `--optimizer_openai_compatible_model` and
  `--target_openai_compatible_model`, SkillOpt printed
  `optimizer_model: gpt-4o-mini` and `target_model: gpt-4o-mini`.
- The final summary reported `steps=3 accept=0 reject=0 skip=3` and
  `total tokens: 0 (prompt=0 completion=0 calls=0)`.

This initial run was not a valid optimization and its artifacts must not be
presented as a successful result. The fixes and the subsequent valid run are
recorded separately below and in the project API's Skill History.

### Adapter repair and metric alignment

Two integration issues were isolated during the repair. First, the SkillOpt
trainer calls the selection split `valid_seen`, while the project loader stores
it as `selection`; mapping the names restored all four held-out rows. Second,
SkillOpt 0.2.0's target API returns `(text, usage_metadata)`, so the adapter
must parse the first element. Finally, the benchmark includes
`reference_unique`, which is not part of the production Extractor response
schema, and stores line descriptions outside the production `lines[]` shape.
The extractor scorer now excludes the unsupported field and maps production
`lines[].description` to the benchmark's line-description target. The excluded
field is recorded in rollout artifacts instead of being counted as an error.

The first service run also showed why the target output remained empty: the
SkillOpt trainer replaced the wrapper's Azure deployment with its own default
`gpt-4o-mini`, which is not deployed on this Foundry resource. A direct call to
the configured `Kimi-K2.5` deployment returned valid structured JSON when given
a 4,096-token completion budget. The SkillOpt YAML now pins `Kimi-K2.5` for
both optimizer and target, and raises the target budget to 4,096 so hidden
reasoning cannot consume the full response limit.

Run `20261019T150037Z` was stopped before completion when this metric mismatch
was noticed. Run `20261019T150445Z` restored the selection split and metric but
still inherited the unavailable model default; its 404 failures are retained
in Skill History. Run `20261019T151308Z` used the corrected metric and budget
but also inherited that default; its partial output is retained. No result from
those failed runs is a performance claim. Run `20261019T151548Z` completed on
the explicit Kimi deployment: the held-out set scored 4/4 on the binary gate,
with mean field NEM 0.90. The remaining soft-score loss came from treating
equivalent decimal representations such as `0.600` and `0.6` as unequal. No
candidate patches were proposed, and no skill was promoted. Decimal-aware
normalization and a continuous soft gate are now configured for the next run.

## Company B Coder prompt comparison — 2026-10-19

A paired v001/v002 experiment was attempted on all 30 Company B SELECTION
documents with gold extracted fields and the same company-filtered RAG results.
Azure returned rate-limit errors for many calls. The run produced valid model
responses for only 12 baseline prompts and 13 candidate prompts; 12 documents
had responses from both. On that paired subset, supported Coder score was 9/12
for v001 and 8/12 for v002. This is inconclusive and is not a full-set
comparison. The evaluator now separates provider failures from model outputs;
see `eval/results/company_b_coder_prompt_ablation.json`.

The focused v002/v003 held-out adaptation run completed without provider
errors: the four TechVision consulting cases scored 0/4 and 4/4, respectively.
That is a distinct, manually authored prompt experiment, recorded in
`eval/results/company_b_skill_adaptation.json`; it is not a SkillOpt result.
