"""
scripts/skillopt_train.py — SkillOpt training with docdesk adapter registered.

Run from project root in .venv-skillopt:
    source .venv-skillopt/bin/activate
    python scripts/skillopt_train.py --config configs/docdesk/default.yaml

This wrapper:
1. Loads .env (OPENAI_BASE_URL, OPENAI_API_KEY, AGENT_DEPLOYMENT)
2. Maps them to the SkillOpt env var names that openai_compatible_backend expects
3. Registers the docdesk adapter
4. Delegates to SkillOpt's train.py main()

IMPORTANT: env vars must be set BEFORE importing skillopt, because
openai_compatible_backend.py reads them at module import time.
"""
import sys
import os

# Ensure project root is first on path so skillopt_envs is found
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Load .env BEFORE any skillopt import ────────────────────────────────────
from pathlib import Path

env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

# ── Map .env vars to SkillOpt openai_compatible_backend env var names ──────
# Must happen before `import skillopt` because the backend reads env at import.
_base_url = os.environ.get("OPENAI_BASE_URL", "")
_api_key = os.environ.get("OPENAI_API_KEY", "")
_model = os.environ.get("AGENT_DEPLOYMENT", "Kimi-K2.5")

if _base_url:
    os.environ.setdefault("OPENAI_COMPATIBLE_BASE_URL", _base_url)
    os.environ.setdefault("OPTIMIZER_OPENAI_COMPATIBLE_BASE_URL", _base_url)
    os.environ.setdefault("TARGET_OPENAI_COMPATIBLE_BASE_URL", _base_url)

if _api_key:
    os.environ.setdefault("OPENAI_COMPATIBLE_API_KEY", _api_key)
    os.environ.setdefault("OPTIMIZER_OPENAI_COMPATIBLE_API_KEY", _api_key)
    os.environ.setdefault("TARGET_OPENAI_COMPATIBLE_API_KEY", _api_key)

if _model:
    os.environ.setdefault("OPENAI_COMPATIBLE_MODEL", _model)
    os.environ.setdefault("OPTIMIZER_OPENAI_COMPATIBLE_MODEL", _model)
    os.environ.setdefault("TARGET_OPENAI_COMPATIBLE_MODEL", _model)

# ── NOW import SkillOpt and register our adapter ───────────────────────────
import skillopt

# Locate scripts/train.py (shipped inside the skillopt package)
skillopt_path = os.path.dirname(skillopt.__file__)
train_path = os.path.join(skillopt_path, "..", "scripts")
sys.path.insert(0, train_path)

import train as skillopt_train

# Register docdesk adapter
from skillopt_envs.docdesk.adapter import DocDeskCoderAdapter
skillopt_train._register_builtins()
skillopt_train._ENV_REGISTRY["docdesk"] = DocDeskCoderAdapter

# Force-configure the OpenAI-compatible backend with our env vars
# (the backend reads env at import time; we override it now)
from skillopt.model.openai_compatible_backend import configure_openai_compatible
from skillopt.model.backend_config import set_optimizer_backend, set_target_backend
configure_openai_compatible(
    base_url=_base_url or None,
    api_key=_api_key or None,
    model=_model or None,
)
set_optimizer_backend("openai_compatible")
set_target_backend("openai_compatible")

print("Registered docdesk adapter.")
print(f"Available environments: {list(skillopt_train._ENV_REGISTRY.keys())}")

if __name__ == "__main__":
    skillopt_train.main()
