# DocDesk presentation guide

Twelve slides, roughly 12–15 minutes. Each slide is a visual cue; speak to the diagram and use one short example rather than reading text.

| Slide | Suggested talk track |
|---|---|
| 1 | Introduce DocDesk: turn accounting documents into auditable decisions. |
| 2 | Describe the read, interpret and verify workload. State that the evaluation uses synthetic French documents. |
| 3 | Explain the central separation: RAG supplies company facts; SKILL.md controls agent behavior. |
| 4 | Walk the document path and point out accepted, review and failure outcomes. Intake is webhook-enabled; Gmail/Drive await OAuth configuration. |
| 5 | Explain the four specialists and why deterministic checks complement LLM extraction and coding. |
| 6 | Justify n8n, FastAPI, Qdrant, SQLite and Kimi-K2.5 by their specific jobs. |
| 7 | Trace TRAIN feedback through bounded edits and the SELECTION gate; TEST is kept separate. |
| 8 | Demonstrate the intentionally poor prompt and the measured 1%→21% SELECTION change. Say “soft NEM,” explain that hard exact remained 0%, and avoid presenting this as reliable accuracy. |
| 9 | Read the RAG results as source retrieval, then explain why Recall@5 saturates with a small corpus. Show held-out extraction scores only after the artifact is complete. |
| 10 | Describe the 300-document generated corpus, clean splits and injected validation issues. |
| 11 | Cover local company filtering, traceability and review; acknowledge OAuth and production security work still needed. |
| 12 | Recap the thesis, then move to the live demo or questions. |

Every team member should be ready to explain intake, RAG, agent roles, SkillOpt gates, evaluation limits and security, regardless of who presents a particular slide.

## Live demo order

1. Open the dashboard and show the operations/history view.
2. Process a synthetic invoice; point to extracted fields, account code, validation outcome and trace.
3. Open SkillOpt and compare the weak-prompt baseline with the selected prompt. Explain SELECTION versus held-out TEST.
4. Show the knowledge base / retrieval metrics and mention their source-level limitation.
