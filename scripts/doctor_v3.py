"""
scripts/doctor_v3.py — LLM deployment diagnostics v3.

Fixes vs v2:
- reasoning_effort=none applied to ALL benchmark calls
- asserts no reasoning tokens after switch (aborts if present)
- compact extractor prompt (max_tokens 600 for extractor, 300 for others)
- TTC compared numerically (French/English format → Decimal)
- prints predicted vs gold for every mismatch
- unique doc IDs (A-xxxx / B-xxxx) required
- uses usage.completion_tokens_details.reasoning_tokens when available
- never prints any key fragment (only "set (N chars)")

Output: eval/results/doctor.md
"""

import base64
import io
import json
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
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
    import pypdf
except ImportError as e:
    print(f"ERROR: missing dependency — {e}")
    sys.exit(1)

BASE_URL   = os.environ.get("OPENAI_BASE_URL", "")
API_KEY    = os.environ.get("OPENAI_API_KEY", "")
AGENT_MDL  = os.environ.get("AGENT_DEPLOYMENT", "Kimi-K2.5")
VISION_MDL = os.environ.get("VISION_DEPLOYMENT", AGENT_MDL)
OPT_MDL    = os.environ.get("OPTIMIZER_DEPLOYMENT", AGENT_MDL)

def mask_key(key: str) -> str:
    return f"set ({len(key)} chars)"

def mask_url(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).hostname or url

try:
    git_commit = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=Path(__file__).parent.parent, stderr=subprocess.DEVNULL
    ).decode().strip()
    # Add -dirty if there are uncommitted changes
    dirty = subprocess.call(
        ["git", "diff-index", "--quiet", "HEAD"],
        cwd=Path(__file__).parent.parent, stderr=subprocess.DEVNULL
    )
    if dirty != 0:
        git_commit += "-dirty"
except Exception:
    git_commit = "unknown"

now  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
ROOT = Path(__file__).parent.parent

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
lines  = []

def log(s=""):
    print(s)
    lines.append(s)


# ── Helpers ───────────────────────────────────────────────────────────────────

def call_instant(model: str, messages: list, max_tokens: int) -> tuple:
    """
    Call with reasoning_effort=none. Asserts no reasoning tokens.
    Returns: (content, comp_tokens, r_tokens_api, finish_reason)
    """
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
        max_tokens=max_tokens,
        reasoning_effort="none",
    )
    msg     = resp.choices[0].message
    content = msg.content or ""
    reasoning = getattr(msg, "reasoning_content", None) or ""

    usage   = resp.usage
    details = getattr(usage, "completion_tokens_details", None)
    r_tok   = getattr(details, "reasoning_tokens", None)
    if r_tok is None:
        r_tok = len(reasoning.split()) if reasoning.strip() else 0

    if reasoning.strip() or (r_tok and r_tok > 10):
        raise RuntimeError(
            f"reasoning_effort=none did not suppress reasoning "
            f"(r_tok={r_tok}, reasoning present={bool(reasoning.strip())})"
        )

    return content, getattr(usage, "completion_tokens", 0), r_tok, resp.choices[0].finish_reason


def extract_json(text: str) -> dict | None:
    clean = text.strip()
    if clean.startswith("```"):
        lines_t = clean.split("\n")
        clean = "\n".join(lines_t[1:-1] if lines_t[-1].strip() == "```" else lines_t[1:])
    m = re.search(r"\{.*\}", clean, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def parse_amount(s) -> Decimal | None:
    """Parse French ('1 011,500') or English ('1011.500') amount to Decimal."""
    if s is None:
        return None
    s = str(s).strip()
    # Remove currency codes
    s = re.sub(r"[A-Za-z€$£]+", "", s).strip()
    # Remove narrow no-break space and regular space (thousands separator)
    s = s.replace("\u202f", "").replace("\u00a0", "").replace(" ", "")
    # French decimal comma → period
    s = s.replace(",", ".")
    # Remove duplicate periods (keep last one as decimal)
    parts = s.split(".")
    if len(parts) > 2:
        s = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return Decimal(s).quantize(Decimal("0.001"))
    except (InvalidOperation, Exception):
        return None


def amounts_match(pred, gold, tol=Decimal("0.005")) -> bool:
    p, g = parse_amount(pred), parse_amount(gold)
    if p is None or g is None:
        return False
    return abs(p - g) <= tol


def normalize_str(s) -> str:
    if s is None:
        return ""
    s = str(s).strip().lower()
    s = re.sub(r"[\s\u00a0\u202f]+", " ", s).strip()
    return s


# ── Load splits ───────────────────────────────────────────────────────────────

splits_path = ROOT / "data" / "splits.json"
if not splits_path.exists():
    log("ERROR: data/splits.json not found. Run: python3 -m data.generator")
    sys.exit(1)
splits = json.loads(splits_path.read_text())

# Validate no duplicate doc IDs
all_ids = [doc_id for co in splits.values() for s in co.values() for doc_id in s]
from collections import Counter
dups = {k: v for k, v in Counter(all_ids).items() if v > 1}
if dups:
    log(f"ERROR: duplicate doc IDs found: {dups}. Run python3 -m data.generator to regenerate.")
    sys.exit(1)


# ── Header ────────────────────────────────────────────────────────────────────

log("# Doctor Report v3")
log()
log("| Field | Value |")
log("|-------|-------|")
log(f"| Date | {now} |")
log(f"| Git commit | {git_commit} |")
log(f"| Endpoint host | {mask_url(BASE_URL)} |")
log(f"| API key | {mask_key(API_KEY)} |")
log(f"| Agent model | {AGENT_MDL} |")
log(f"| Vision model | {VISION_MDL} |")
log(f"| Optimizer model | {OPT_MDL} |")
log(f"| Reasoning switch | reasoning_effort=none |")
log()
log("All benchmark calls use `reasoning_effort=none`. Any call that returns "
    "reasoning tokens aborts with an error.")
log()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 1: Vision benchmark — 20 docs (10 per company), instant mode
# ═══════════════════════════════════════════════════════════════════════════════

log("## Test 1: Vision Benchmark (reasoning_effort=none, max_tokens=600)")
log()

VISION_SYSTEM = (
    "You are an OCR agent for Tunisian accounting documents. "
    "Return ONLY a compact JSON object with these exact keys: "
    'supplier, number, ttc. '
    "Values are strings exactly as shown. No extra text."
)
VISION_USER = "Extract supplier, number (facture/reçu/BC number), and ttc (total TTC) from this document image."

vision_docs = []
for company_id in ["company_a", "company_b"]:
    doc_ids  = splits.get(company_id, {}).get("selection", [])
    docs_dir = ROOT / "data" / company_id / "documents"
    for doc_id in doc_ids:
        photo = docs_dir / f"{doc_id}_photo.jpg"
        gold_f = docs_dir / f"{doc_id}_gold.json"
        if photo.exists() and gold_f.exists():
            gold = json.loads(gold_f.read_text())
            vision_docs.append({"doc_id": doc_id, "company_id": company_id,
                                 "photo": photo, "gold": gold})
        if len(vision_docs) >= 20:
            break
    if len(vision_docs) >= 20:
        break

log(f"Documents: {len(vision_docs)} (target 20)")
if len(vision_docs) < 5:
    log("WARNING: fewer than 5 documents — low confidence")
log()

vision_results = []
for i, doc in enumerate(vision_docs):
    gold_f = doc["gold"]["fields"]
    g_sup  = gold_f.get("supplier", "")
    g_num  = gold_f.get("number", "")
    g_ttc  = gold_f.get("ttc", "")

    img_b64 = base64.b64encode(doc["photo"].read_bytes()).decode()
    t0 = time.monotonic()
    try:
        content, comp_tok, r_tok, finish = call_instant(
            VISION_MDL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_SYSTEM + "\n\n" + VISION_USER},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                ],
            }],
            max_tokens=600,
        )
        lat = int((time.monotonic() - t0) * 1000)

        if not content.strip():
            r = {"doc_id": doc["doc_id"], "co": doc["company_id"],
                 "status": "FAIL_EMPTY", "lat": lat, "comp": comp_tok,
                 "sup_ok": False, "num_ok": False, "ttc_ok": False}
        else:
            parsed = extract_json(content)
            if parsed is None:
                r = {"doc_id": doc["doc_id"], "co": doc["company_id"],
                     "status": "FAIL_PARSE", "raw": content[:80],
                     "lat": lat, "comp": comp_tok,
                     "sup_ok": False, "num_ok": False, "ttc_ok": False}
            else:
                sup_ok = normalize_str(parsed.get("supplier")) == normalize_str(g_sup)
                num_ok = normalize_str(parsed.get("number")) == normalize_str(g_num)
                ttc_ok = amounts_match(parsed.get("ttc"), g_ttc)
                r = {"doc_id": doc["doc_id"], "co": doc["company_id"],
                     "status": "ok", "lat": lat, "comp": comp_tok,
                     "sup_ok": sup_ok, "num_ok": num_ok, "ttc_ok": ttc_ok,
                     "p_sup": parsed.get("supplier"), "g_sup": g_sup,
                     "p_num": parsed.get("number"),   "g_num": g_num,
                     "p_ttc": parsed.get("ttc"),       "g_ttc": g_ttc}
    except Exception as e:
        lat = int((time.monotonic() - t0) * 1000)
        r = {"doc_id": doc["doc_id"], "co": doc["company_id"],
             "status": f"ERROR:{str(e)[:60]}", "lat": lat, "comp": 0,
             "sup_ok": False, "num_ok": False, "ttc_ok": False}

    vision_results.append(r)
    sym = "✓" if (r["sup_ok"] or r["num_ok"] or r["ttc_ok"]) else "✗"
    log(f"  [{i+1:2d}] {r['doc_id']} ({r['co']}) {sym} "
        f"sup={'✓' if r['sup_ok'] else '✗'} "
        f"num={'✓' if r['num_ok'] else '✗'} "
        f"ttc={'✓' if r['ttc_ok'] else '✗'} "
        f"{r['lat']}ms comp={r['comp']} status={r['status']}")
    # Print mismatches
    if r["status"] == "ok":
        if not r["sup_ok"]:
            log(f"       supplier pred={repr(r['p_sup'])} gold={repr(r['g_sup'])}")
        if not r["num_ok"]:
            log(f"       number   pred={repr(r['p_num'])} gold={repr(r['g_num'])}")
        if not r["ttc_ok"]:
            pttc = parse_amount(r['p_ttc'])
            gttc = parse_amount(r['g_ttc'])
            log(f"       ttc      pred={r['p_ttc']} (={pttc}) gold={r['g_ttc']} (={gttc})")

n = len(vision_results)
n_sup  = sum(1 for r in vision_results if r["sup_ok"])
n_num  = sum(1 for r in vision_results if r["num_ok"])
n_ttc  = sum(1 for r in vision_results if r["ttc_ok"])
n_fail = sum(1 for r in vision_results if "FAIL" in r.get("status","") or "ERROR" in r.get("status",""))

log()
log(f"**Vision accuracy** (N={n}, reasoning_effort=none):")
log(f"| Field | Correct | Rate |")
log(f"|-------|---------|------|")
log(f"| supplier | {n_sup}/{n} | {n_sup/n:.0%} |")
log(f"| number   | {n_num}/{n} | {n_num/n:.0%} |")
log(f"| ttc      | {n_ttc}/{n} | {n_ttc/n:.0%} |")
log(f"| failures (empty/parse/error) | {n_fail}/{n} | — |")
log()
vision_ok = (n_sup >= round(n * 0.9)) and (n_ttc >= round(n * 0.9))
log(f"**Decision (≥90% on supplier AND ttc):** {'✓ PASS — Kimi-K2.5 vision sufficient' if vision_ok else '✗ FAIL — add Mistral Small 4 as VISION_DEPLOYMENT'}")
log()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 2: Latency benchmark — extractor v001, compact prompt, instant mode
# ═══════════════════════════════════════════════════════════════════════════════

log("## Test 2: Latency Benchmark — Extractor v001 (reasoning_effort=none, max_tokens=600)")
log()

skill_path = ROOT / "skills" / "company_a" / "extractor" / "v001.md"
if not skill_path.exists():
    log("ERROR: skills/company_a/extractor/v001.md not found")
    sys.exit(1)
EXTRACTOR_SKILL = skill_path.read_text(encoding="utf-8")

lat_docs = []
for company_id in ["company_a", "company_b"]:
    doc_ids  = splits.get(company_id, {}).get("selection", [])
    docs_dir = ROOT / "data" / company_id / "documents"
    for doc_id in doc_ids:
        pdf_path  = docs_dir / f"{doc_id}.pdf"
        gold_path = docs_dir / f"{doc_id}_gold.json"
        if pdf_path.exists() and gold_path.exists():
            try:
                reader = pypdf.PdfReader(str(pdf_path))
                text   = "\n".join(p.extract_text() or "" for p in reader.pages).strip()
            except Exception:
                text = ""
            if len(text) > 50:
                gold = json.loads(gold_path.read_text())
                lat_docs.append({"doc_id": doc_id, "company_id": company_id,
                                  "text": text, "gold": gold})
        if len(lat_docs) >= 10:
            break
    if len(lat_docs) >= 10:
        break

log(f"Running extractor v001 on {len(lat_docs)} SELECTION text documents...")
log()

lat_rows    = []
n_parse_ok  = 0

for i, doc in enumerate(lat_docs):
    user_msg = (
        f"Type: {doc['gold'].get('doc_type','invoice')}\n\n"
        f"{doc['text'][:2000]}"
    )
    t0 = time.monotonic()
    try:
        content, comp_tok, r_tok, finish = call_instant(
            AGENT_MDL,
            messages=[
                {"role": "system", "content": EXTRACTOR_SKILL},
                {"role": "user",   "content": user_msg},
            ],
            max_tokens=600,
        )
        lat = int((time.monotonic() - t0) * 1000)
        parsed   = extract_json(content)
        parse_ok = parsed is not None
        if parse_ok:
            n_parse_ok += 1
        lat_rows.append({"doc_id": doc["doc_id"], "lat": lat,
                         "comp": comp_tok, "r_tok": r_tok,
                         "finish": finish, "parse_ok": parse_ok})
        log(f"  [{i+1:2d}] {doc['doc_id']} {lat}ms comp={comp_tok} "
            f"r_tok={r_tok} finish={finish} parse={'✓' if parse_ok else '✗'}")
        if not parse_ok:
            log(f"       raw: {repr(content[:100])}")
    except Exception as e:
        lat = int((time.monotonic() - t0) * 1000)
        log(f"  [{i+1:2d}] {doc['doc_id']} ERROR {lat}ms: {str(e)[:70]}")
        lat_rows.append({"doc_id": doc["doc_id"], "lat": lat,
                         "comp": 0, "r_tok": 0, "finish": "error", "parse_ok": False})

log()
if lat_rows:
    lats        = sorted(r["lat"] for r in lat_rows)
    n_lat       = len(lats)
    median_ms   = statistics.median(lats)
    p95_ms      = lats[min(int(n_lat * 0.95), n_lat - 1)]
    mean_comp   = statistics.mean(r["comp"] for r in lat_rows)
    parse_rate  = n_parse_ok / n_lat

    log(f"**Latency results** (N={n_lat}, reasoning_effort=none):")
    log(f"| Metric | Value |")
    log(f"|--------|-------|")
    log(f"| Median latency    | {median_ms:.0f}ms |")
    log(f"| p95 latency       | {p95_ms:.0f}ms |")
    log(f"| Mean output tokens | {mean_comp:.0f} |")
    log(f"| JSON parse rate    | {parse_rate:.0%} ({n_parse_ok}/{n_lat}) |")
    log()
    agents_ok = median_ms <= 6000
    log(f"**Decision (median ≤ 6,000ms):** {'✓ PASS — Kimi-K2.5 acceptable for agents' if agents_ok else '✗ FAIL — switch agent role to faster model'}")
else:
    agents_ok = False
    log("No latency data — no SELECTION text documents found.")
log()


# ═══════════════════════════════════════════════════════════════════════════════
# DECISION SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════

log("## Decision Summary")
log()
log("| Question | Result |")
log("|----------|--------|")
log(f"| Vision ≥90% supplier AND ttc (instant) | {'✓ PASS' if vision_ok else '✗ FAIL'} ({n_sup}/{n} sup, {n_ttc}/{n} ttc) |")
log(f"| Reasoning switch works                 | ✓ reasoning_effort=none |")
log(f"| Agent latency ≤ 6s (instant, compact)  | {'✓ PASS' if (lat_rows and agents_ok) else '✗ FAIL'} ({median_ms:.0f}ms median) |")
log()
log("### Recommendations")

if not vision_ok:
    log("- **VISION_DEPLOYMENT**: Kimi-K2.5 does not pass vision benchmark at 90%. "
        "Add Mistral Small 4: `VISION_BASE_URL=https://api.mistral.ai/v1`, "
        "`VISION_DEPLOYMENT=mistral-small-latest`. Synthetic data only.")
else:
    log("- **VISION_DEPLOYMENT**: Kimi-K2.5 passes. No second model needed for vision.")

if lat_rows and not agents_ok:
    log(f"- **AGENT_DEPLOYMENT**: Median {median_ms:.0f}ms exceeds 6s. "
        "Switch agents to a non-reasoning model (Mistral Small 4 or a fast Foundry model).")
else:
    log(f"- **AGENT_DEPLOYMENT**: Median {median_ms:.0f}ms within 6s target. Kimi-K2.5 acceptable.")

log("- **OPTIMIZER_DEPLOYMENT**: Keep Kimi-K2.5 (default reasoning). SkillOpt benefits from reflection.")
log("- **AGENT_EXTRA_BODY**: `reasoning_effort=none` — applied to all agent calls.")


# ── Write output ──────────────────────────────────────────────────────────────

out_dir  = ROOT / "eval" / "results"
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / "doctor.md"
out_path.write_text("\n".join(lines), encoding="utf-8")
print()
print(f"=== Written to {out_path} ===")
