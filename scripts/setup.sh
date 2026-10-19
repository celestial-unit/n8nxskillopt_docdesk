#!/usr/bin/env bash
# scripts/setup.sh — Create venv, install pinned dependencies, verify imports.
# Usage: bash scripts/setup.sh

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"

echo "=== Setup: n8n Multi-Agent Document Pipeline ==="
echo "Python: $($PYTHON --version)"
echo ""

# ── Create venv ───────────────────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "Creating .venv..."
    "$PYTHON" -m venv .venv
fi

source .venv/bin/activate
echo "Venv: $(which python)"

# ── Install pinned requirements ──────────────────────────────────────────────
echo ""
echo "Installing requirements..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

# ── Verify imports (no silent fallbacks) ─────────────────────────────────────
echo ""
echo "Verifying imports..."
python -c "
import importlib, sys

required = {
    'reportlab': 'PDF generation',
    'pypdf':     'PDF text extraction',
    'PIL':       'Image processing (Pillow)',
    'qdrant_client': 'Qdrant vector DB',
    'sentence_transformers': 'Embedding model',
    'openai':    'LLM client',
    'fastapi':   'FastAPI backend',
    'uvicorn':   'ASGI server',
    'pydantic':  'Data models',
    'dotenv':    'Env loading',
    'tiktoken':  'Token counting',
    'numpy':     'Numerical ops',
    'httpx':     'API testing',
    'pytest':    'Testing',
}

errors = []
for pkg, desc in required.items():
    try:
        importlib.import_module(pkg)
        print(f'  ✓ {pkg} ({desc})')
    except ImportError as e:
        print(f'  ✗ {pkg} ({desc}) — {e}')
        errors.append(pkg)

if errors:
    print(f'')
    print(f'FAILED: {len(errors)} missing dependencies: {errors}')
    sys.exit(1)
else:
    print('')
    print('All imports verified.')
"

# ── Verify project modules ───────────────────────────────────────────────────
echo ""
echo "Verifying project modules..."
python -c "
from agents.llm_client import LLMClient, MissingDeploymentError
from agents.skill_loader import load_skill
from agents.router_agent import RouterAgent
from agents.extractor_agent import ExtractorAgent
from agents.coder_agent import CoderAgent
from agents.validator_agent import ValidatorAgent
from agents.exception_handler_agent import ExceptionHandlerAgent
from agents.multimodal import extract_text_from_pdf, detect_modality
from rag.chunkers import FixedChunker, SemanticChunker
from api.db import TraceStore
from api.models import RouteRequest, HealthResponse
from api.main import app
from eval.scorers import extractor_score, coder_score, validator_score
from data.generator import generate_corpus, format_tnd
print('  All project modules import OK')
"

# ── Check .env exists ─────────────────────────────────────────────────────────
echo ""
if [ ! -f ".env" ]; then
    echo "WARNING: .env not found. Copy .env.template to .env and fill in your credentials."
    cp .env.template .env
    echo "  Created .env from template — edit it with your Azure/OpenAI credentials."
else
    echo "  .env exists."
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your LLM credentials"
echo "  2. python -m data.generator          # generate corpus"
echo "  3. python -m rag.ingest --company_id=all  # load rules into Qdrant"
echo "  4. python run.py                      # start FastAPI + n8n + UI"
