"""agents/exception_handler_agent.py — ExceptionHandlerAgent: escalation dossier."""

import json
from typing import Optional
from agents.llm_client import LLMClient
from agents.skill_loader import load_skill
from agents.exceptions import AgentParseError


class ExceptionHandlerAgent:
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()

    def run(self, input: dict, company_id: str) -> dict:
        """
        Prepare a structured escalation dossier for human review.

        Args:
            input: {"extracted": dict, "validation": dict, "doc_id": str}
            company_id: "company_a" or "company_b"

        Returns:
            {"escalation_dossier": dict, "skill_version": str}
        """
        skill_text, skill_version = load_skill(company_id, "exception_handler")
        extracted = input.get("extracted", {})
        validation = input.get("validation", {})
        doc_id = input.get("doc_id", "")

        user_msg = (
            f"Document référence : {doc_id}\n"
            f"Fournisseur : {extracted.get('supplier', 'Inconnu')}\n"
            f"Montant TTC : {extracted.get('ttc', 'N/A')}\n"
            f"Erreurs détectées : {validation.get('errors', [])}\n"
            f"Explication : {validation.get('explanation', '')}\n\n"
            f"Prépare un dossier d'escalade structuré."
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
            dossier = json.loads(clean)
        except json.JSONDecodeError:
            # Fallback structured dossier
            dossier = {
                "summary": f"Document {doc_id} nécessite une révision manuelle.",
                "errors": validation.get("errors", []),
                "recommended_action": "Vérifier manuellement le document.",
                "contact": "Service comptabilité",
                "priority": "medium",
                "document_reference": doc_id,
            }

        return {
            "escalation_dossier": dossier,
            "skill_version": skill_version,
        }
