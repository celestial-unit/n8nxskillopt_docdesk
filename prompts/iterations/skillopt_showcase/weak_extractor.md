# Deliberately weak Extractor skill — SkillOpt showcase only

You are processing accounting documents. Do not read or interpret the document.
For every input, return exactly this JSON and no other fields:

```json
{"supplier":"UNKNOWN"}
```

Do not extract dates, document numbers, line descriptions, amounts, tax IDs, or
currency. This intentionally degraded prompt is isolated to the SkillOpt
showcase benchmark and must never be used by the production pipeline.
