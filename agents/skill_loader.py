"""
agents/skill_loader.py — Load versioned skill (system prompt) files for agents.

Skill files live at: skills/<company_id>/<agent_name>/v<NNN>.md
Example: skills/company_a/router/v001.md
"""

import glob
import os
from pathlib import Path
from typing import Optional


def load_skill(
    company_id: str,
    agent_name: str,
    version: Optional[str] = None,
) -> tuple[str, str]:
    """
    Load the latest (or specified) skill file for an agent.

    Args:
        company_id: e.g. "company_a" or "company_b"
        agent_name: e.g. "router", "extractor", "coder", "validator", "exception_handler"
        version: optional explicit version string, e.g. "v001". If None, uses latest.

    Returns:
        Tuple of (skill_text: str, version_string: str), e.g. ("...", "v001")

    Raises:
        FileNotFoundError: if no skill file is found for the given agent.
    """
    base = Path("skills") / company_id / agent_name

    if version:
        path = base / f"{version}.md"
        if not path.exists():
            raise FileNotFoundError(
                f"Skill file not found: {path}. "
                f"Expected skills/{company_id}/{agent_name}/{version}.md"
            )
    else:
        pattern = str(base / "v*.md")
        matches = sorted(glob.glob(pattern))
        if not matches:
            raise FileNotFoundError(
                f"No skill file found at {base}/v*.md. "
                f"Create skills/{company_id}/{agent_name}/v001.md first."
            )
        path = Path(matches[-1])  # latest version (lexicographically)

    version_str = path.stem  # e.g. "v001" from "v001.md"

    with open(path, encoding="utf-8") as f:
        skill_text = f.read()

    return skill_text, version_str


def get_latest_version(company_id: str, agent_name: str) -> Optional[str]:
    """
    Return the latest version string for a skill, or None if no skill exists.

    Args:
        company_id: e.g. "company_a"
        agent_name: e.g. "router"

    Returns:
        Version string like "v002", or None.
    """
    base = Path("skills") / company_id / agent_name
    matches = sorted(glob.glob(str(base / "v*.md")))
    if not matches:
        return None
    return Path(matches[-1]).stem
