"""agents/extractor_agent.py — ExtractorAgent: extracts structured fields."""

import json
from typing import Optional
from agents.llm_client import LLMClient
from agents.skill_loader import load_skill
from agents.exceptions import AgentParseError


class ExtractorAgent:
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()

    def run(self, input: dict, company_id: str) -> dict:
        """
        Extract structured fields from a document.

        Args:
            input: {"text": str, "doc_type": str} or {"image_b64": str, "doc_type": str}
            company_id: "company_a" or "company_b"

        Returns:
            {supplier, date, number, lines, htva, tva, ttc, timbre_fiscal, matricule_fiscal, currency, skill_version}
        """
        skill_text, skill_version = load_skill(company_id, "extractor")

        text = input.get("text", "")
        image_b64 = input.get("image_b64")
        doc_type = input.get("doc_type", "invoice")

        user_msg = (
            f"Type de document : {doc_type}\n\n"
            f"Extrais tous les champs structurés du document suivant :\n\n{text[:4000] if text else '(image fournie)'}"
        )

        response = self.llm.call(
            role="vision" if image_b64 else "agent",
            system_prompt=skill_text,
            user_message=user_msg,
            image_b64=image_b64,
        )

        try:
            clean = response.strip()
            # Strip markdown code fences if present
            if clean.startswith("```"):
                lines = clean.split("\n")
                # Find the JSON block
                start = 1
                end = len(lines) - 1
                for i, line in enumerate(lines):
                    if line.strip().startswith("```") and i > 0:
                        end = i
                        break
                clean = "\n".join(lines[start:end])
            # Try to extract JSON object if embedded in text
            if not clean.startswith("{"):
                import re
                match = re.search(r"\{.*\}", clean, re.DOTALL)
                if match:
                    clean = match.group(0)
            result = json.loads(clean)
        except json.JSONDecodeError as e:
            raise AgentParseError(
                f"ExtractorAgent failed to parse LLM response: {e}\nRaw: {response[:200]}"
            )

        result["skill_version"] = skill_version
        # Ensure required keys have defaults
        for key in ("supplier", "date", "number", "lines", "htva", "tva", "ttc", "timbre_fiscal", "matricule_fiscal", "currency"):
            if key not in result:
                result[key] = None
        if result.get("lines") is None:
            result["lines"] = []

        return result
