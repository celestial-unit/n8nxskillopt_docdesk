"""
scripts/doctor.py — Diagnose LLM deployment capabilities.

Tests for each role:
  1. Basic text completion (latency, JSON output)
  2. Instant mode (thinking disabled)
  3. Image input (vision capability)
  4. Never prints keys — only first 8 chars masked

Run: python3 scripts/doctor.py
"""

import base64
import json
import os
import sys
import time
from pathlib import Path

# Load .env
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: openai not installed. Run: pip install openai")
    sys.exit(1)

BASE_URL = os.environ.get("OPENAI_BASE_URL", "")
API_KEY = os.environ.get("OPENAI_API_KEY", "")
AGENT_MODEL = os.environ.get("AGENT_DEPLOYMENT", "")
VISION_MODEL = os.environ.get("VISION_DEPLOYMENT", AGENT_MODEL)
OPTIMIZER_MODEL = os.environ.get("OPTIMIZER_DEPLOYMENT", AGENT_MODEL)

def mask(key: str) -> str:
    return key[:8] + "..." if len(key) > 8 else "***"

def make_client(extra_body: dict | None = None):
    return OpenAI(base_url=BASE_URL, api_key=API_KEY)

print("=" * 60)
print("DOCTOR SCRIPT — LLM deployment diagnostics")
print("=" * 60)
print(f"Endpoint : {BASE_URL}")
print(f"API key  : {mask(API_KEY)}")
print(f"Agent    : {AGENT_MODEL}")
print(f"Vision   : {VISION_MODEL}")
print(f"Optimizer: {OPTIMIZER_MODEL}")
print()

client = make_client()
results = {}

# ── Test 1: Basic text completion ─────────────────────────────────────────────
print("─" * 40)
print("TEST 1: Basic text completion (agent role)")
t0 = time.monotonic()
try:
    resp = client.chat.completions.create(
        model=AGENT_MODEL,
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": 'Reply with exactly this JSON and nothing else: {"status": "ok", "value": 42}'},
        ],
        temperature=0,
        max_tokens=200,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    content = resp.choices[0].message.content or ""
    # Check for reasoning_content
    reasoning = getattr(resp.choices[0].message, "reasoning_content", None)
    reasoning_tokens = len(reasoning.split()) if reasoning else 0
    
    # Try to parse JSON from content
    json_ok = False
    try:
        # Strip markdown fences
        clean = content.strip()
        if clean.startswith("```"):
            clean = "\n".join(clean.split("\n")[1:-1])
        import re
        m = re.search(r"\{.*\}", clean, re.DOTALL)
        if m:
            clean = m.group(0)
        parsed = json.loads(clean)
        json_ok = parsed.get("status") == "ok" and parsed.get("value") == 42
    except Exception:
        pass

    print(f"  Latency   : {latency_ms}ms")
    print(f"  Content   : {repr(content[:100])}")
    print(f"  JSON parse: {'✓ PASS' if json_ok else '✗ FAIL (content did not parse to expected JSON)'}")
    print(f"  Reasoning : {'present, ~' + str(reasoning_tokens) + ' words' if reasoning else 'absent'}")
    print(f"  Finish    : {resp.choices[0].finish_reason}")
    results["text"] = {"ok": True, "latency_ms": latency_ms, "json_ok": json_ok}
except Exception as e:
    print(f"  ERROR: {e}")
    results["text"] = {"ok": False, "error": str(e)}

print()

# ── Test 2: Instant mode (thinking disabled) ──────────────────────────────────
print("─" * 40)
print("TEST 2: Instant mode — extra_body={'thinking': {'type': 'disabled'}}")
t0 = time.monotonic()
instant_works = False
try:
    resp = client.chat.completions.create(
        model=AGENT_MODEL,
        messages=[{"role": "user", "content": "What is 3+3? Reply with just the number."}],
        temperature=0,
        max_tokens=50,
        extra_body={"thinking": {"type": "disabled"}},
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    content = resp.choices[0].message.content or ""
    reasoning = getattr(resp.choices[0].message, "reasoning_content", None)
    instant_works = True
    print(f"  Latency   : {latency_ms}ms")
    print(f"  Content   : {repr(content)}")
    print(f"  Reasoning : {'absent ✓ (Instant confirmed)' if not reasoning else 'still present (Thinking mode still on)'}")
    print(f"  Status    : ✓ PASS — extra_body thinking:disabled accepted")
    results["instant"] = {"ok": True, "reasoning_absent": not bool(reasoning)}
except Exception as e:
    latency_ms = int((time.monotonic() - t0) * 1000)
    print(f"  Status    : ✗ FAIL ({e})")
    results["instant"] = {"ok": False, "error": str(e)}

print()

# ── Test 3: Thinking mode (optimizer) ────────────────────────────────────────
print("─" * 40)
print("TEST 3: Thinking mode — extra_body={'thinking': {'type': 'enabled', 'budget_tokens': 512}}")
t0 = time.monotonic()
try:
    resp = client.chat.completions.create(
        model=OPTIMIZER_MODEL,
        messages=[{"role": "user", "content": "What is 7*8? Reply with just the number."}],
        temperature=0,
        max_tokens=600,
        extra_body={"thinking": {"type": "enabled", "budget_tokens": 512}},
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    content = resp.choices[0].message.content or ""
    reasoning = getattr(resp.choices[0].message, "reasoning_content", None)
    print(f"  Latency   : {latency_ms}ms")
    print(f"  Content   : {repr(content)}")
    print(f"  Reasoning : {'present ✓' if reasoning else 'absent'}")
    print(f"  Status    : ✓ PASS")
    results["thinking"] = {"ok": True, "reasoning_present": bool(reasoning)}
except Exception as e:
    print(f"  Status    : ✗ FAIL ({e})")
    results["thinking"] = {"ok": False, "error": str(e)}

print()

# ── Test 4: Image input (vision) ──────────────────────────────────────────────
print("─" * 40)
print("TEST 4: Image input (vision capability)")

# Create a minimal 1x1 white PNG in memory
import struct, zlib

def make_tiny_png() -> bytes:
    """Create a minimal valid 1x1 white PNG."""
    def chunk(name: bytes, data: bytes) -> bytes:
        c = name + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw = b"\x00\xff\xff\xff"  # filter byte + RGB white
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend

png_b64 = base64.b64encode(make_tiny_png()).decode()
t0 = time.monotonic()
try:
    resp = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this image in one word."},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png_b64}"}},
            ],
        }],
        temperature=0,
        max_tokens=50,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    content = resp.choices[0].message.content or ""
    print(f"  Latency   : {latency_ms}ms")
    print(f"  Content   : {repr(content)}")
    print(f"  Status    : ✓ PASS — image input accepted")
    results["vision"] = {"ok": True, "latency_ms": latency_ms}
except Exception as e:
    print(f"  Status    : ✗ FAIL ({e})")
    print(f"  → Vision calls will need a separate model or fallback.")
    results["vision"] = {"ok": False, "error": str(e)}

print()

# ── Summary ───────────────────────────────────────────────────────────────────
print("=" * 60)
print("SUMMARY")
print("=" * 60)
checks = {
    "text":     ("Basic completion", results.get("text", {}).get("ok", False)),
    "json":     ("JSON output",      results.get("text", {}).get("json_ok", False)),
    "instant":  ("Instant mode",     results.get("instant", {}).get("ok", False)),
    "thinking": ("Thinking mode",    results.get("thinking", {}).get("ok", False)),
    "vision":   ("Image input",      results.get("vision", {}).get("ok", False)),
}
for k, (label, ok) in checks.items():
    print(f"  {'✓' if ok else '✗'} {label}")

print()
instant_ok = results.get("instant", {}).get("ok", False)
vision_ok  = results.get("vision", {}).get("ok", False)

print("RECOMMENDATIONS:")
if instant_ok:
    print("  → Use extra_body={'thinking':{'type':'disabled'}} for AGENT role (Instant mode)")
    print("  → Use extra_body={'thinking':{'type':'enabled','budget_tokens':2048}} for OPTIMIZER role")
else:
    print("  → Instant mode switch not accepted — check if deployment supports it")
    print("  → Agents will run in Thinking mode (slower but works)")

if vision_ok:
    print("  → Image input works on this deployment — no second model needed for vision")
else:
    print("  → Image input fails — add Mistral Small 4 as VISION_DEPLOYMENT")
    print("    VISION_BASE_URL=https://api.mistral.ai/v1")
    print("    VISION_API_KEY=<your-mistral-key>")
    print("    VISION_DEPLOYMENT=mistral-small-latest")

print()
print("Save these results and share them — they determine the next config steps.")
