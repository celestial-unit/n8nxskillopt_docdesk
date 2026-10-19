# RAG Retrieval Evaluation

Model: `paraphrase-multilingual-mpnet-base-v2`  
Chunker: FixedChunker (512 tokens, 64-token overlap); top-k = 5.

| Company | Queries | Recall@5 | MRR@5 |
|---------|---------|----------|-------|
| company_a | 20 | 1.0000 | 0.9167 |
| company_b | 20 | 1.0000 | 0.8875 |

## Corpus and method

Each company is evaluated in an isolated temporary Qdrant collection built from the visible chart of accounts and topic-level internal policy files. Hidden house rules and gold labels are excluded.

- **company_a**: 9 chunks from chart_of_accounts.md, banking.md, fuel.md, it_services.md, office_supplies.md, public_utilities.md, purchases.md, tax_and_stamp.md, telecommunications.md.
- **company_b**: 11 chunks from chart_of_accounts.md, banking.md, fuel.md, insurance.md, it_and_equipment.md, office_supplies.md, public_utilities.md, purchases.md, tax_and_stamp.md, telecommunications.md.

## Comment

Results above are from real RAG runs. Higher Recall@5 indicates more relevant rules
are retrieved in the top 5 results. MRR@5 measures how early the first relevant
result appears (1.0 = always first, 0.5 = always second, etc.).

Recall@5 is source-level: a query scores when its labeled policy source appears in the first five results. MRR@5 rewards an earlier first relevant source.