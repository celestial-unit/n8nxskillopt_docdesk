# Real Documents — Hand-Labeled Set

This folder contains 15–20 photographed real receipts and invoices for evaluation.

## Structure

Each document consists of two files:
```
real/
  <id>.jpg      (or .png) — the photographed document
  <id>.json     — the hand-labeled gold JSON
```

## Gold JSON Schema

```json
{
  "doc_id": "<unique identifier, e.g. real-001>",
  "doc_type": "invoice" | "receipt" | "purchase_order",
  "fields": {
    "supplier": "<supplier name>",
    "date": "<dd/mm/yyyy>",
    "number": "<document number>",
    "htva": "<amount formatted as '1 011,500'>",
    "tva": "<TVA amount>",
    "ttc": "<TTC total>",
    "timbre_fiscal": "<stamp duty amount>",
    "nif": "<NIF in format XXXXXXXX/X/XXX/XXX or empty string if absent>",
    "currency": "TND" | "EUR"
  },
  "account_code": "<assigned account code>",
  "company_id": "company_a" | "company_b"
}
```

Note: `injected_errors` is omitted for real documents (errors are real, not synthetic).

## Rules

1. Place photos as `<id>.jpg` or `<id>.png`
2. Create a matching `<id>.json` with the same base name
3. Files without a matching JSON will be ignored in evaluation
4. These documents are **never used for prompt optimization or training**
5. Results are reported **separately** from synthetic dataset results

## Status

Place your labeled documents here. The evaluation pipeline will automatically
detect and process all paired files in this directory.
