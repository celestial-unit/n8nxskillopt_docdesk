"""
scripts/doctor_v2.py — Rigorous LLM deployment diagnostics v2.

Tests:
  1. Vision benchmark: 10 invoice photo scans → JSON extraction, vs gold labels
  2. Thinking-switch search: 4 parameter styles tested one by one
  3. Latency benchmark: extractor v001 prompt on 10 SELECTION documents

Output: eval/results/doctor.md (never print any key fragment)

Run: python3 scripts/doctor_v2.py
"""

import base64
import json
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Load .env ─────────────────────────────────────────────────────────────────
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

BASE_URL  = os.environ.get("OPENAI_BASE_URL", "")
API_KEY   = os.environ.get("OPENAI_API_KEY", "")
AGENT_MDL = os.environ.get("AGENT_DEPLOYMENT", "Kimi-K2.5")
VISION_MDL= os.environ.get("VISION_DEPLOYMENT", AGENT_MDL)
OPT_MDL   = os.environ.get("OPTIMIZER_DEPLOYMENT", AGENT_MDL)

# Mask: never print any key fragment
def mask_key(key: str) -> str:
    return f"set ({len(key)} chars)"

def mask_url(url: str) -> str:
    from urllib.parse import urlparse
    p = urlparse(url)
    return p.hostname or url

# Git commit
try:
    git_commit = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=Path(__file__).parent.parent, stderr=subprocess.DEVNULL
    ).decode().strip()
except Exception:
    git_commit = "unknown"

now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
ROOT = Path(__file__).parent.parent

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
lines = []  # markdown output

def log(s=""):
    print(s)
    lines.append(s)

log(f"# Doctor Report v2")
log(f"")
log(f"| Field | Value |")
log(f"|-------|-------|")
log(f"| Date | {now} |")
log(f"| Git commit | {git_commit} |")
log(f"| Endpoint host | {mask_url(BASE_URL)} |")
log(f"| API key | {mask_key(API_KEY)} |")
log(f"| Agent model | {AGENT_MDL} |")
log(f"| Vision model | {VISION_MDL} |")
log(f"| Optimizer model | {OPT_MDL} |")
log()


# ── Helpers ───────────────────────────────────────────────────────────────────

def call(model: str, messages: list, max_tokens: int = 4096,
         extra_body: dict | None = None) -> tuple[str, str | None, int, int, str]:
    """
    Returns: (content, reasoning_content, completion_tokens, reasoning_tokens, finish_reason)
    """
    kwargs = dict(model=model, messages=messages, temperature=0, max_tokens=max_tokens)
    if extra_body:
        kwargs["extra_body"] = extra_body
    resp = client.chat.completions.create(**kwargs)
    msg = resp.choices[0].message
    content   = msg.content or ""
    reasoning = getattr(msg, "reasoning_content", None) or ""
    finish    = resp.choices[0].finish_reason or ""
    usage     = resp.usage or type("U", (), {"completion_tokens": 0})()
    comp_tok  = getattr(usage, "completion_tokens", 0) or 0
    r_tok     = len(reasoning.split()) if reasoning else 0
    return content, reasoning, comp_tok, r_tok, finish


def extract_json(text: str) -> dict | None:
    clean = text.strip()
    if clean.startswith("```"):
        clean = "\n".join(clean.split("\n")[1:])
        if "```" in clean:
            clean = clean[:clean.index("```")]
    m = re.search(r"\{.*\}", clean, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def normalize(s) -> str:
    if s is None:
        return ""
    s = str(s).strip().lower()
    s = re.sub(r"[\s\u00a0\u202f]+", "", s)
    s = s.replace(",", ".").replace("\u2019", "'")
    return s


# ── Load data ─────────────────────────────────────────────────────────────────

splits_path = ROOT / "data" / "splits.json"
if not splits_path.exists():
    log("ERROR: data/splits.json not found. Run python3 -m data.generator first.")
    sys.exit(1)

splits = json.loads(splits_path.read_text())

# Collect up to 10 SELECTION photo documents across both companies
vision_docs = []
for company_id in ["company_a", "company_b"]:
    doc_ids = splits.get(company_id, {}).get("selection", [])
    docs_dir = ROOT / "data" / company_id / "documents"
    for doc_id in doc_ids:
        photo_path = docs_dir / f"{doc_id}_photo.jpg"
        gold_path  = docs_dir / f"{doc_id}_gold.json"
        if photo_path.exists() and gold_path.exists():
            gold = json.loads(gold_path.read_text())
            vision_docs.append({
                "doc_id": doc_id,
                "company_id": company_id,
                "photo_path": str(photo_path),
                "gold": gold,
            })
        if len(vision_docs) >= 10:
            break
    if len(vision_docs) >= 10:
        break

log(f"Vision benchmark: {len(vision_docs)} photo documents available from SELECTION split")
if len(vision_docs) < 5:
    log("WARNING: fewer than 5 vision documents found — results will be low-confidence")
log()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 1: Vision benchmark
# ═══════════════════════════════════════════════════════════════════════════════

log("## Test 1: Vision Benchmark")
log()
log("Task: extract vendor, invoice number, and total TTC from each photo scan.")
log("Pass criterion: empty answer counts as FAILURE. Correct if normalized exact match.")
log()

VISION_PROMPT = """You are an expert OCR agent for Tunisian accounting documents.
Extract the following fields from this invoice/receipt image and return ONLY valid JSON:
{
  "supplier": "<vendor name>",
  "number": "<invoice or receipt number>",
  "ttc": "<total TTC amount as it appears>"
}
If a field is not visible, use null. Return only the JSON object, no other text."""

vision_results = []

for i, doc in enumerate(vision_docs):
    doc_id = doc["doc_id"]
    gold_fields = doc["gold"]["fields"]
    gold_supplier = gold_fields.get("supplier", "")
    gold_number   = gold_fields.get("number", "")
    gold_ttc      = gold_fields.get("ttc", "")

    img_b64 = base64.b64encode(Path(doc["photo_path"]).read_bytes()).decode()

    t0 = time.monotonic()
    try:
        content, reasoning, comp_tok, r_tok, finish = call(
            VISION_MDL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text",      "text": VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                ],
            }],
            max_tokens=4096,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        if not content.strip():
            result = {
                "doc_id": doc_id, "company": doc["company_id"],
                "status": "FAIL", "reason": "empty_response",
                "latency_ms": latency_ms, "finish": finish,
                "comp_tokens": comp_tok, "reasoning_tokens": r_tok,
                "supplier_ok": False, "number_ok": False, "ttc_ok": False,
            }
        else:
            parsed = extract_json(content)
            if parsed is None:
                result = {
                    "doc_id": doc_id, "company": doc["company_id"],
                    "status": "FAIL", "reason": "parse_error",
                    "raw": content[:120],
                    "latency_ms": latency_ms, "finish": finish,
                    "comp_tokens": comp_tok, "reasoning_tokens": r_tok,
                    "supplier_ok": False, "number_ok": False, "ttc_ok": False,
                }
            else:
                sup_ok = normalize(parsed.get("supplier")) == normalize(gold_supplier)
                num_ok = normalize(parsed.get("number"))   == normalize(gold_number)
                ttc_ok = normalize(parsed.get("ttc"))      == normalize(gold_ttc)
                result = {
                    "doc_id": doc_id, "company": doc["company_id"],
                    "status": "PASS" if (sup_ok or num_ok or ttc_ok) else "PARTIAL",
                    "latency_ms": latency_ms, "finish": finish,
                    "comp_tokens": comp_tok, "reasoning_tokens": r_tok,
                    "supplier_ok": sup_ok, "number_ok": num_ok, "ttc_ok": ttc_ok,
                    "pred_supplier": parsed.get("supplier"),
                    "pred_number":   parsed.get("number"),
                    "pred_ttc":      parsed.get("ttc"),
                    "gold_supplier": gold_supplier,
                    "gold_number":   gold_number,
                    "gold_ttc":      gold_ttc,
                }
    except Exception as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        result = {
            "doc_id": doc_id, "company": doc["company_id"],
            "status": "ERROR", "reason": str(e)[:100],
            "latency_ms": latency_ms,
            "supplier_ok": False, "number_ok": False, "ttc_ok": False,
        }

    vision_results.append(result)
    status_sym = "✓" if result["supplier_ok"] or result["number_ok"] or result["ttc_ok"] else "✗"
    log(f"  [{i+1:2d}] {doc_id} ({doc['company_id']}) {status_sym} "
        f"supplier={'✓' if result['supplier_ok'] else '✗'} "
        f"number={'✓' if result['number_ok'] else '✗'} "
        f"ttc={'✓' if result['ttc_ok'] else '✗'} "
        f"{result['latency_ms']}ms finish={result.get('finish','')} "
        f"comp={result.get('comp_tokens','?')} r_tok={result.get('reasoning_tokens','?')}")

n = len(vision_results)
n_supplier = sum(1 for r in vision_results if r["supplier_ok"])
n_number   = sum(1 for r in vision_results if r["number_ok"])
n_ttc      = sum(1 for r in vision_results if r["ttc_ok"])
n_empty    = sum(1 for r in vision_results if r.get("reason") == "empty_response")

log()
log(f"**Vision accuracy** (N={n}):")
log(f"| Field | Exact match | Rate |")
log(f"|-------|-------------|------|")
log(f"| supplier | {n_supplier}/{n} | {n_supplier/n:.0%} |")
log(f"| number   | {n_number}/{n}   | {n_number/n:.0%} |")
log(f"| ttc      | {n_ttc}/{n}      | {n_ttc/n:.0%} |")
log(f"| empty responses | {n_empty}/{n} | — |")
log()

# Apply decision rule: vision OK if >= 9/10 on totals AND vendor
vision_ok_supplier = n_supplier >= max(1, round(n * 0.9))
vision_ok_ttc      = n_ttc      >= max(1, round(n * 0.9))
log(f"**Decision (supplier ≥ 9/10):** {'✓ PASS' if vision_ok_supplier else '✗ FAIL'}")
log(f"**Decision (ttc ≥ 9/10):**      {'✓ PASS' if vision_ok_ttc else '✗ FAIL'}")
log()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 2: Thinking-switch search
# ═══════════════════════════════════════════════════════════════════════════════

log("## Test 2: Thinking-Switch Search")
log()
log("Testing 4 parameter styles to find Instant mode. Empty response = FAIL.")
log()

SWITCH_PROMPT = "What is 5+5? Reply with just the number."
switch_candidates = [
    ("extra_body:thinking:disabled",
     {"thinking": {"type": "disabled"}}),
    ("extra_body:chat_template_kwargs:thinking:false",
     {"chat_template_kwargs": {"thinking": False}}),
    ("extra_body:enable_thinking:false",
     {"enable_thinking": False}),
    ("param:reasoning_effort:none",
     None),  # handled separately
]

working_switch = None
switch_results = []

for name, extra in switch_candidates:
    t0 = time.monotonic()
    try:
        if name == "param:reasoning_effort:none":
            resp_obj = client.chat.completions.create(
                model=AGENT_MDL,
                messages=[{"role": "user", "content": SWITCH_PROMPT}],
                temperature=0,
                max_tokens=50,
                reasoning_effort="none",
            )
            content   = resp_obj.choices[0].message.content or ""
            reasoning = getattr(resp_obj.choices[0].message, "reasoning_content", None) or ""
            http_ok   = True
        else:
            content, reasoning, _, _, _ = call(
                AGENT_MDL,
                [{"role": "user", "content": SWITCH_PROMPT}],
                max_tokens=50,
                extra_body=extra,
            )
            http_ok = True

        latency_ms = int((time.monotonic() - t0) * 1000)
        reasoning_gone = not bool(reasoning.strip())
        effective = http_ok and bool(content.strip()) and reasoning_gone

        r = {
            "name": name, "http_ok": http_ok,
            "content": content.strip()[:30],
            "reasoning_gone": reasoning_gone,
            "latency_ms": latency_ms,
            "effective": effective,
        }
        if effective and working_switch is None:
            working_switch = name

    except Exception as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        r = {
            "name": name, "http_ok": False, "error": str(e)[:80],
            "reasoning_gone": None, "latency_ms": latency_ms, "effective": False,
        }

    switch_results.append(r)
    sym = "✓" if r["effective"] else ("✗" if r["http_ok"] else "⚠")
    log(f"  {sym} {name}")
    log(f"      HTTP ok: {r['http_ok']}  "
        f"reasoning_gone: {r.get('reasoning_gone','?')}  "
        f"latency: {r['latency_ms']}ms  "
        f"content: {repr(r.get('content',''))[:40]}  "
        f"{'ERROR: '+r['error'] if 'error' in r else ''}")

log()
if working_switch:
    log(f"**Working switch found:** `{working_switch}` → stored as AGENT_EXTRA_BODY")
    # Store the switch for the LLM client
    # reasoning_effort=none is a top-level param, stored as a special sentinel
    extra_val = "reasoning_effort:none" if working_switch == "param:reasoning_effort:none" else json.dumps(
        next((e for n, e in switch_candidates if n == working_switch and e is not None), {})
    )
    with open(ROOT / ".env", "a") as f:
        f.write(f"\n# Instant mode switch (found by doctor_v2)\nAGENT_EXTRA_BODY={extra_val}\n")
else:
    log("**No working switch found** → reasoning always on. Recording as AGENT_EXTRA_BODY=none")
    with open(ROOT / ".env", "a") as f:
        f.write(f"\n# Instant mode switch\nAGENT_EXTRA_BODY=none\n")
log()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 3: Latency benchmark — extractor v001 on 10 SELECTION documents
# ═══════════════════════════════════════════════════════════════════════════════

log("## Test 3: Latency Benchmark — Extractor v001")
log()

# Load extractor v001 skill
skill_path = ROOT / "skills" / "company_a" / "extractor" / "v001.md"
if not skill_path.exists():
    log("ERROR: skills/company_a/extractor/v001.md not found")
    sys.exit(1)
EXTRACTOR_SKILL = skill_path.read_text(encoding="utf-8")

# Collect up to 10 text-layer SELECTION docs
import pypdf as _pypdf

latency_docs = []
for company_id in ["company_a", "company_b"]:
    doc_ids = splits.get(company_id, {}).get("selection", [])
    docs_dir = ROOT / "data" / company_id / "documents"
    for doc_id in doc_ids:
        pdf_path  = docs_dir / f"{doc_id}.pdf"
        gold_path = docs_dir / f"{doc_id}_gold.json"
        if pdf_path.exists() and gold_path.exists():
            try:
                reader = _pypdf.PdfReader(str(pdf_path))
                text = "\n".join(p.extract_text() or "" for p in reader.pages).strip()
            except Exception:
                text = ""
            if len(text) > 50:
                gold = json.loads(gold_path.read_text())
                latency_docs.append({
                    "doc_id": doc_id, "company_id": company_id,
                    "text": text, "gold": gold,
                })
        if len(latency_docs) >= 10:
            break
    if len(latency_docs) >= 10:
        break

log(f"Running extractor v001 on {len(latency_docs)} SELECTION text-layer documents...")
log()

latency_rows = []
n_parse_ok = 0

for i, doc in enumerate(latency_docs):
    user_msg = (
        f"Type de document : {doc['gold'].get('doc_type', 'invoice')}\n\n"
        f"Document:\n{doc['text'][:3000]}"
    )
    t0 = time.monotonic()
    try:
        content, reasoning, comp_tok, r_tok, finish = call(
            AGENT_MDL,
            messages=[
                {"role": "system", "content": EXTRACTOR_SKILL},
                {"role": "user",   "content": user_msg},
            ],
            max_tokens=4096,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        parsed = extract_json(content)
        parse_ok = parsed is not None
        if parse_ok:
            n_parse_ok += 1
        latency_rows.append({
            "doc_id": doc["doc_id"], "latency_ms": latency_ms,
            "comp_tokens": comp_tok, "reasoning_tokens": r_tok,
            "finish": finish, "parse_ok": parse_ok,
        })
        log(f"  [{i+1:2d}] {doc['doc_id']} {latency_ms}ms "
            f"comp={comp_tok} r_tok={r_tok} finish={finish} "
            f"parse={'✓' if parse_ok else '✗'}")
    except Exception as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        log(f"  [{i+1:2d}] {doc['doc_id']} ERROR {latency_ms}ms {str(e)[:60]}")
        latency_rows.append({
            "doc_id": doc["doc_id"], "latency_ms": latency_ms,
            "comp_tokens": 0, "reasoning_tokens": 0, "finish": "error", "parse_ok": False,
        })

log()
if latency_rows:
    lats = [r["latency_ms"] for r in latency_rows]
    lats_sorted = sorted(lats)
    n_lat = len(lats_sorted)
    median_ms = statistics.median(lats_sorted)
    p95_ms    = lats_sorted[int(n_lat * 0.95) - 1] if n_lat >= 2 else lats_sorted[-1]
    avg_comp  = statistics.mean(r["comp_tokens"] for r in latency_rows)
    avg_r_tok = statistics.mean(r["reasoning_tokens"] for r in latency_rows)
    parse_rate = n_parse_ok / len(latency_rows)

    log(f"**Latency results** (N={n_lat}):")
    log(f"| Metric | Value |")
    log(f"|--------|-------|")
    log(f"| Median latency | {median_ms:.0f}ms |")
    log(f"| p95 latency | {p95_ms:.0f}ms |")
    log(f"| Mean completion tokens | {avg_comp:.0f} |")
    log(f"| Mean reasoning tokens (est.) | {avg_r_tok:.0f} |")
    log(f"| JSON parse success rate | {parse_rate:.0%} ({n_parse_ok}/{len(latency_rows)}) |")
    log()

    # Decision: agents OK on Kimi if median <= 6000ms
    agents_ok = median_ms <= 6000
    log(f"**Decision (median ≤ 6,000ms):** {'✓ PASS — Kimi-K2.5 acceptable for agents' if agents_ok else '✗ FAIL — consider a faster non-reasoning model for agents'}")
else:
    log("No latency data — no SELECTION text documents found.")
log()


# ═══════════════════════════════════════════════════════════════════════════════
# DECISION SECTION
# ═══════════════════════════════════════════════════════════════════════════════

log("## Decision Summary")
log()
log("| Question | Answer |")
log("|----------|--------|")

vis_sup_str = f"{n_supplier}/{n}" if n > 0 else "no data"
vis_ttc_str = f"{n_ttc}/{n}" if n > 0 else "no data"
log(f"| Vision: supplier ≥ 9/10 | {'✓ YES' if vision_ok_supplier else '✗ NO'} ({vis_sup_str}) |")
log(f"| Vision: ttc ≥ 9/10      | {'✓ YES' if vision_ok_ttc else '✗ NO'} ({vis_ttc_str}) |")
log(f"| Instant mode available  | {'✓ YES: ' + working_switch if working_switch else '✗ NO — reasoning always on'} |")

if latency_rows:
    log(f"| Agents: median ≤ 6s     | {'✓ YES' if agents_ok else '✗ NO'} ({median_ms:.0f}ms) |")
else:
    log(f"| Agents: median ≤ 6s     | no data |")

log()
log("### Recommendations")
if not vision_ok_supplier or not vision_ok_ttc:
    log("- **Vision**: Kimi-K2.5 does not reliably read invoice photos. Add Mistral Small 4 as VISION_DEPLOYMENT (synthetic data only).")
else:
    log("- **Vision**: Kimi-K2.5 passes vision benchmark. No second model needed for vision.")

if not working_switch:
    log("- **Reasoning overhead**: No Instant switch works on this Foundry deployment. All agent calls run with reasoning. Consider deploying a non-reasoning model (e.g. Mistral Small 4) as AGENT_DEPLOYMENT for latency-sensitive roles.")
else:
    log(f"- **Instant mode**: Use `{working_switch}` for AGENT role. Keep default (Thinking) for OPTIMIZER.")

if latency_rows and not agents_ok:
    log(f"- **Latency**: Median {median_ms:.0f}ms exceeds 6s target. Switch agents to a non-reasoning model.")
elif latency_rows:
    log(f"- **Latency**: Median {median_ms:.0f}ms is within 6s target. Kimi-K2.5 is acceptable for agents.")


# ═══════════════════════════════════════════════════════════════════════════════
# Write output
# ═══════════════════════════════════════════════════════════════════════════════

out_dir = ROOT / "eval" / "results"
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / "doctor.md"
out_path.write_text("\n".join(lines), encoding="utf-8")

print()
print(f"=== Written to {out_path} ===")
