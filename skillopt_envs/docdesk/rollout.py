"""
skillopt_envs/docdesk/rollout.py — Rollout for the docdesk coder task.

For each item:
1. Call the coder LLM with the skill + document fields + RAG chunks
2. Score: hard=1.0 if code matches gold AND cited_rule in skill/chunks, else 0.0
          soft=0.5 if code matches but cited_rule not found
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _load_rag_chunks(company_id: str, query: str, top_k: int = 5) -> list[dict]:
    """Retrieve relevant chunks from Qdrant for the given company and query."""
    try:
        from rag.engine import RAGEngine
        engine = RAGEngine(company_id=company_id)
        return engine.search(query, top_k=top_k)
    except Exception as e:
        return []


def _call_coder(skill_text: str, item: dict, model_cfg: dict) -> tuple[str, str]:
    """
    Call the coder LLM. Returns (raw_response, content).
    """
    from skillopt.model import chat_target_messages

    supplier = item.get("gold_fields", {}).get("supplier", "")
    doc_type = item.get("doc_type", "invoice")
    company_id = item.get("company_id", "company_a")

    # Get RAG chunks
    query = f"{supplier} {doc_type} codification comptable"
    chunks = _load_rag_chunks(company_id, query, top_k=5)
    rag_context = ""
    if chunks:
        rag_context = "\n\n## Règles récupérées :\n" + "\n---\n".join(
            f"[Score: {c.get('score', 0):.3f}] {c.get('text', '')}"
            for c in chunks
        )

    fields = item.get("gold_fields", {})
    user_msg = (
        f"Document extrait (tous les champs observés):\n"
        f"{json.dumps(fields, ensure_ascii=False, indent=2)}\n"
        f"Description du document:\n{item.get('text', '')[:2500]}\n"
        f"{rag_context}"
    )

    messages = [
        {"role": "system", "content": skill_text},
        {"role": "user", "content": user_msg},
    ]

    model_cfg = dict(model_cfg)
    model_cfg.setdefault("reasoning_effort", "none")
    response = chat_target_messages(messages, **model_cfg)
    return response, response


def _extract_json(text: str) -> dict | None:
    """Extract JSON from LLM response, stripping markdown fences."""
    clean = text.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        clean = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
    m = re.search(r"\{.*\}", clean, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def _coder_score(predicted_code: str, gold_code: str,
                  cited_rule: str, skill_text: str,
                  chunks: list[dict]) -> tuple[float, float]:
    """
    hard: 1.0 iff code matches AND cited_rule (≥10 chars) in skill or chunks
    soft: 0.5 iff code matches but cited_rule not found
    """
    if predicted_code != gold_code:
        return 0.0, 0.0

    if len(cited_rule) < 10:
        return 0.0, 0.5  # code right, rule missing/too short

    cited_lower = cited_rule.lower()
    if cited_lower in skill_text.lower():
        return 1.0, 1.0
    for chunk in chunks:
        if cited_lower in chunk.get("text", "").lower():
            return 1.0, 1.0

    return 0.0, 0.5  # code right, rule not found in skill/chunks


def run_batch(
    items: list[dict],
    skill_text: str,
    out_dir: str,
    model_cfg: dict,
    workers: int = 1,
) -> list[dict]:
    """
    Run rollouts for a batch of items. Returns list of result dicts.
    Saves each prediction to out_dir/predictions/<id>/conversation.json.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import os

    results = []

    def process_one(item: dict) -> dict:
        doc_id = item["id"]
        gold_code = item.get("gold_account_code", "")
        company_id = item.get("company_id", "company_a")

        supplier = item.get("gold_fields", {}).get("supplier", "")
        query = f"{supplier} {item.get('doc_type', '')} codification"
        chunks = _load_rag_chunks(company_id, query)

        try:
            raw, content = _call_coder(skill_text, item, model_cfg)
            parsed = _extract_json(content)

            if parsed is None:
                pred_code  = ""
                cited_rule = ""
                parse_ok   = False
            else:
                pred_code  = parsed.get("account_code", "")
                cited_rule = parsed.get("cited_rule", "")
                parse_ok   = True

            hard, soft = _coder_score(pred_code, gold_code, cited_rule, skill_text, chunks)

            result = {
                "id":           doc_id,
                "company_id":   company_id,
                "gold_code":    gold_code,
                "pred_code":    pred_code,
                "cited_rule":   cited_rule,
                "hard":         hard,
                "soft":         soft,
                "parse_ok":     parse_ok,
                "raw_response": content[:500],
            }

            # Save conversation.json for the reflect step
            conv_dir = os.path.join(out_dir, "predictions", doc_id)
            os.makedirs(conv_dir, exist_ok=True)
            with open(os.path.join(conv_dir, "conversation.json"), "w") as f:
                json.dump({
                    "id": doc_id,
                    "input": item,
                    "gold_code": gold_code,
                    "pred_code": pred_code,
                    "cited_rule": cited_rule,
                    "hard": hard,
                    "soft": soft,
                    "raw_response": content,
                    "chunks_used": [c.get("text", "")[:100] for c in chunks],
                }, f, ensure_ascii=False, indent=2)

            return result

        except Exception as e:
            return {
                "id": doc_id, "company_id": company_id,
                "gold_code": gold_code, "pred_code": "", "cited_rule": "",
                "hard": 0.0, "soft": 0.0, "parse_ok": False,
                "error": str(e)[:100],
            }

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(process_one, item): item for item in items}
            for fut in as_completed(futures):
                results.append(fut.result())
    else:
        for item in items:
            results.append(process_one(item))

    return results
