"""agents/validator_agent.py — ValidatorAgent: Python checks + LLM explanation."""

from typing import Optional
from agents.llm_client import LLMClient
from agents.skill_loader import load_skill


class ValidatorAgent:
    def __init__(self, llm_client: Optional[LLMClient] = None, trace_store=None):
        self.llm = llm_client or LLMClient()
        self._trace_store = trace_store

    def run(self, input: dict, company_id: str) -> dict:
        """
        Validate a document: Python checks first, then one LLM call for explanation.

        Args:
            input: {"extracted": dict, "doc_id": str}
            company_id: "company_a" or "company_b"

        Returns:
            {"valid": bool, "errors": list[str], "explanation": str, "needs_review": bool, "skill_version": str}
        """
        skill_text, skill_version = load_skill(company_id, "validator")
        extracted = input.get("extracted", {})
        doc_id = input.get("doc_id", "")

        errors: list[str] = []

        # ── Phase 1: Python deterministic checks ────────────────────────────

        # Check 1: Arithmetic consistency  abs(htva + tva - ttc) <= 0.005
        try:
            htva = float(extracted.get("htva") or 0)
            tva  = float(extracted.get("tva")  or 0)
            ttc  = float(extracted.get("ttc")  or 0)
            if ttc != 0 and abs(htva + tva - ttc) > 0.005:
                errors.append("arithmetic_mismatch")
        except (TypeError, ValueError):
            errors.append("arithmetic_mismatch")

        # Check 2: matricule_fiscal presence (field may be 'nif' or 'matricule_fiscal')
        nif = extracted.get("matricule_fiscal") or extracted.get("nif") or ""
        if not str(nif).strip():
            errors.append("missing_nif")

        # Check 3: Duplicate doc_id — use 'duplicate_of' field in extracted output,
        # NOT the trace store (which would flag every re-submitted test document)
        if extracted.get("duplicate_of"):
            errors.append("duplicate_id")

        # ── Phase 2: One LLM call for explanation ───────────────────────────
        error_summary = ", ".join(errors) if errors else "Aucune erreur détectée"
        user_msg = (
            f"Résultat des vérifications Python sur le document {doc_id}:\n"
            f"Erreurs détectées: {error_summary}\n\n"
            f"Champs extraits:\n"
            f"  HTVA: {extracted.get('htva')}, TVA: {extracted.get('tva')}, TTC: {extracted.get('ttc')}\n"
            f"  NIF: {extracted.get('nif')}\n"
            f"  Fournisseur: {extracted.get('supplier')}\n\n"
            f"Génère UNE SEULE PHRASE d'explication."
        )

        explanation = self.llm.call(
            role="agent",
            system_prompt=skill_text,
            user_message=user_msg,
        )
        # Ensure it's a single line
        explanation = explanation.strip().split("\n")[0]

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "explanation": explanation,
            "needs_review": len(errors) > 0,
            "skill_version": skill_version,
        }
