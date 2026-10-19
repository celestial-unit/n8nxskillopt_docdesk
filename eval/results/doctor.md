# Doctor Report v3

| Field | Value |
|-------|-------|
| Date | 2026-10-18 12:12 UTC |
| Git commit | 0b612b9 |
| Endpoint host | mohamedazizghdhoun-0526-resource.services.ai.azure.com |
| API key | set (84 chars) |
| Agent model | Kimi-K2.5 |
| Vision model | Kimi-K2.5 |
| Optimizer model | Kimi-K2.5 |
| Reasoning switch | reasoning_effort=none |

All benchmark calls use `reasoning_effort=none`. Any call that returns reasoning tokens aborts with an error.

## Test 1: Vision Benchmark (reasoning_effort=none, max_tokens=600)

Documents: 12 (target 20)

  [ 1] A-DOC-0027 (company_a) ✓ sup=✓ num=✓ ttc=✓ 1882ms comp=30 status=ok
  [ 2] A-DOC-0001 (company_a) ✓ sup=✓ num=✓ ttc=✓ 1323ms comp=38 status=ok
  [ 3] A-DOC-0014 (company_a) ✓ sup=✓ num=✓ ttc=✓ 1228ms comp=37 status=ok
  [ 4] A-DOC-0002 (company_a) ✓ sup=✓ num=✓ ttc=✓ 1740ms comp=31 status=ok
  [ 5] A-DOC-0018 (company_a) ✓ sup=✓ num=✓ ttc=✓ 1217ms comp=38 status=ok
  [ 6] A-DOC-0028 (company_a) ✓ sup=✓ num=✓ ttc=✓ 1546ms comp=37 status=ok
  [ 7] B-DOC-0027 (company_b) ✓ sup=✓ num=✓ ttc=✓ 2661ms comp=37 status=ok
  [ 8] B-DOC-0001 (company_b) ✓ sup=✓ num=✓ ttc=✓ 2866ms comp=36 status=ok
  [ 9] B-DOC-0014 (company_b) ✓ sup=✓ num=✓ ttc=✓ 1434ms comp=37 status=ok
  [10] B-DOC-0002 (company_b) ✓ sup=✓ num=✓ ttc=✓ 1842ms comp=38 status=ok
  [11] B-DOC-0018 (company_b) ✓ sup=✓ num=✓ ttc=✓ 1451ms comp=37 status=ok
  [12] B-DOC-0028 (company_b) ✓ sup=✓ num=✓ ttc=✓ 4487ms comp=35 status=ok

**Vision accuracy** (N=12, reasoning_effort=none):
| Field | Correct | Rate |
|-------|---------|------|
| supplier | 12/12 | 100% |
| number   | 12/12 | 100% |
| ttc      | 12/12 | 100% |
| failures (empty/parse/error) | 0/12 | — |

**Decision (≥90% on supplier AND ttc):** ✓ PASS — Kimi-K2.5 vision sufficient

## Test 2: Latency Benchmark — Extractor v001 (reasoning_effort=none, max_tokens=600)

Running extractor v001 on 10 SELECTION text documents...

  [ 1] A-DOC-0027 1486ms comp=189 r_tok=0 finish=stop parse=✓
  [ 2] A-DOC-0001 2765ms comp=268 r_tok=0 finish=stop parse=✓
  [ 3] A-DOC-0014 1946ms comp=350 r_tok=0 finish=stop parse=✓
  [ 4] A-DOC-0002 1535ms comp=269 r_tok=0 finish=stop parse=✓
  [ 5] A-DOC-0018 1842ms comp=350 r_tok=0 finish=stop parse=✓
  [ 6] A-DOC-0028 1843ms comp=340 r_tok=0 finish=stop parse=✓
  [ 7] B-DOC-0027 1474ms comp=265 r_tok=0 finish=stop parse=✓
  [ 8] B-DOC-0001 1289ms comp=192 r_tok=0 finish=stop parse=✓
  [ 9] B-DOC-0014 1843ms comp=347 r_tok=0 finish=stop parse=✓
  [10] B-DOC-0002 1471ms comp=344 r_tok=0 finish=stop parse=✓

**Latency results** (N=10, reasoning_effort=none):
| Metric | Value |
|--------|-------|
| Median latency    | 1688ms |
| p95 latency       | 2765ms |
| Mean output tokens | 291 |
| JSON parse rate    | 100% (10/10) |

**Decision (median ≤ 6,000ms):** ✓ PASS — Kimi-K2.5 acceptable for agents

## Decision Summary

| Question | Result |
|----------|--------|
| Vision ≥90% supplier AND ttc (instant) | ✓ PASS (12/12 sup, 12/12 ttc) |
| Reasoning switch works                 | ✓ reasoning_effort=none |
| Agent latency ≤ 6s (instant, compact)  | ✓ PASS (1688ms median) |

### Recommendations
- **VISION_DEPLOYMENT**: Kimi-K2.5 passes. No second model needed for vision.
- **AGENT_DEPLOYMENT**: Median 1688ms within 6s target. Kimi-K2.5 acceptable.
- **OPTIMIZER_DEPLOYMENT**: Keep Kimi-K2.5 (default reasoning). SkillOpt benefits from reflection.
- **AGENT_EXTRA_BODY**: `reasoning_effort=none` — applied to all agent calls.