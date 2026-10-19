"""agents/router_agent.py — RouterAgent: determines doc_type and modality."""

import json
from agents.llm_client import LLMClient
from agents.skill_loader import load_skill
from agents.exceptions import AgentParseError

_VALID_DOC_TYPES = {"invoice", "receipt", "purchase_order"}
_VALID_MODALITIES = {"text", "photo"}


class RouterAgent:
    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()

    def run(self, input: dict, company_id: str) -> dict:
        """
        Determine doc_type and modality for a document.

        Args:
            input: {"file_path": str, "text": str | None, "file_bytes_b64": str | None}
            company_id: "company_a" or "company_b"

        Returns:
            {"doc_type": str, "modality": str, "skill_version": str}
        """
        skill_text, skill_version = load_skill(company_id, "router")

        # Build user message from available input
        text = input.get("text", "")
        file_path = input.get("file_path", "")
        if text:
            user_msg = f"Document à analyser:\n\n{text[:3000]}"
        elif file_path:
            user_msg = f"Fichier: {file_path}\n\nDéterminer le type de document et la modalité."
        else:
            user_msg = "Document vide ou illisible. Retourner doc_type=invoice, modality=text par défaut."

        response = self.llm.call(
            role="agent",
            system_prompt=skill_text,
            user_message=user_msg,
        )

        # Parse JSON response
        try:
            # Strip markdown code fences if present
            clean = response.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                clean = "\n".join(lines[1:-1]) if len(lines) > 2 else clean
            result = json.loads(clean)
        except json.JSONDecodeError as e:
            raise AgentParseError(
                f"RouterAgent failed to parse LLM response as JSON: {e}\nRaw: {response[:200]}"
            )

        doc_type = result.get("doc_type", "invoice")
        modality = result.get("modality", "text")

        # Validate and sanitize
        if doc_type not in _VALID_DOC_TYPES:
            doc_type = "invoice"
        if modality not in _VALID_MODALITIES:
            modality = "text"

        return {
            "doc_type": doc_type,
            "modality": modality,
            "skill_version": skill_version,
        }
