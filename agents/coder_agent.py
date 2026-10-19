"""agents/coder_agent.py — CoderAgent: assigns account code using RAG."""

import json
from typing import Optional
from agents.llm_client import LLMClient
from agents.skill_loader import load_skill
from agents.exceptions import AgentParseError


class CoderAgent:
    def __init__(self, llm_client: Optional[LLMClient] = None, rag_engine=None):
        self.llm = llm_client or LLMClient()
        self._rag_engine = rag_engine  # injected or lazy-loaded

    def _get_rag(self, company_id: str):
        if self._rag_engine is not None:
            return self._rag_engine
        try:
            from rag.engine import RAGEngine
            return RAGEngine(company_id)
        except Exception:
            return None

    def run(self, input: dict, company_id: str, rag_enabled: bool = True) -> dict:
        """
        Assign an account code to a document using RAG context.

        Args:
            input: {"extracted": dict, "doc_type": str}
            company_id: "company_a" or "company_b"
            rag_enabled: if False, skip RAG lookup (for baseline without RAG)

        Returns:
            {"account_code": str, "cited_rule": str, "chunks": list, "skill_version": str}
        """
        skill_text, skill_version = load_skill(company_id, "coder")
        extracted = input.get("extracted", {})

        chunks: list[dict] = []
        rag_context = ""

        if rag_enabled:
            rag = self._get_rag(company_id)
            if rag:
                supplier = extracted.get("supplier", "")
                doc_type = input.get("doc_type", "")
                query = f"{supplier} {doc_type} codification comptable"
                try:
                    chunks = rag.search(query, top_k=5)
                    if chunks:
                        rag_context = "\n\n## Règles récupérées :\n" + "\n---\n".join(
                            f"[Score: {c.get('score', 0):.3f}] {c.get('text', '')}"
                            for c in chunks
                        )
                except Exception:
                    pass

        user_msg = (
            f"Document extrait :\n{json.dumps(extracted, ensure_ascii=False, indent=2)}\n"
            f"{rag_context}"
        )

        response = self.llm.call(
            role="agent",
            system_prompt=skill_text,
            user_message=user_msg,
        )

        try:
            clean = response.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                clean = "\n".join(lines[1:-1]) if len(lines) > 2 else clean
            result = json.loads(clean)
        except json.JSONDecodeError as e:
            raise AgentParseError(
                f"CoderAgent failed to parse LLM response: {e}\nRaw: {response[:200]}"
            )

        return {
            "account_code": result.get("account_code", "606000"),
            "cited_rule": result.get("cited_rule", ""),
            "chunks": chunks,
            "skill_version": skill_version,
        }
