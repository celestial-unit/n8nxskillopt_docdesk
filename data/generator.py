"""
data/generator.py — Deterministic synthetic Tunisian accounting document generator.

Rules (from .kiro/steering/rules.md):
- Globally unique IDs: Company A → A-DOC-NNNN, Company B → B-DOC-NNNN
- matricule_fiscal format: 7 digits + letter (e.g. "1234567A")
- reference_unique independent of corpus index
- amounts stored as French-format strings ("1 011,500")
- gold total_ttc == sum(line.ttc) except arithmetic_mismatch
- house-rule text not in public knowledge files
- stratified split: all house rules, account codes, error types, doc types in every split
- hard scan variant: rotation 8-15°, noise sigma 15-20, JPEG quality 55-65
- 150 docs/company, split 70 TRAIN / 30 SELECTION / 50 TEST

Usage:
    python3 -m data.generator
"""

import hashlib
import json
import random
import re
import uuid
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

SEED = 42
N_DOCS = 150
SPLIT = {"train": 70, "selection": 30, "test": 50}
ERROR_RATE = 0.30
TIMBRE_FISCAL = 0.600  # TND — standard; mark as unverified, check real invoices

# ── Dependency checks (no silent stubs) ──────────────────────────────────────

def _require(pkg_name: str, import_name: str = None):
    import importlib
    name = import_name or pkg_name
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False

REPORTLAB_OK   = _require("reportlab", "reportlab.pdfgen")
PIL_OK         = _require("Pillow", "PIL")
PDF2IMAGE_OK   = _require("pdf2image")

if REPORTLAB_OK:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas as rl_canvas

if PIL_OK:
    from PIL import Image as PILImage

if PDF2IMAGE_OK:
    import pdf2image as _p2i


# ── Formatting helpers ────────────────────────────────────────────────────────

def format_tnd(amount: float) -> str:
    """Format as French TND: 1011.5 → '1\u202f011,500'"""
    int_part = int(amount)
    dec_val  = round(abs(amount - int_part) * 1000)
    int_fmt  = f"{int_part:,}".replace(",", "\u202f")
    return f"{int_fmt},{dec_val:03d}"

def format_date(d: date) -> str:
    return d.strftime("%d/%m/%Y")

def _random_date(rng: random.Random) -> date:
    return date(2024, 1, 1) + timedelta(days=rng.randint(0, 364))


# ── Matricule fiscal (7 digits + letter) ─────────────────────────────────────

def _matricule(rng: random.Random) -> str:
    """Generate a Tunisian matricule fiscal: 7 digits + letter (e.g. '1234567A')."""
    digits = "".join(str(rng.randint(0, 9)) for _ in range(7))
    letter = rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ")
    return f"{digits}{letter}"

# Fixed per-supplier matricule fiscals (seeded, stable across runs)
_MAT_RNG = random.Random(SEED + 1)

def _make_suppliers_a():
    r = random.Random(SEED + 10)
    return [
        {"name": "STEG",                        "matricule_fiscal": _matricule(r), "category": "energy"},
        {"name": "SONEDE",                       "matricule_fiscal": _matricule(r), "category": "energy"},
        {"name": "Tunisie Telecom",              "matricule_fiscal": _matricule(r), "category": "telecom"},
        {"name": "Ooredoo Tunisie",             "matricule_fiscal": _matricule(r), "category": "telecom"},
        {"name": "Orange Tunisie",              "matricule_fiscal": _matricule(r), "category": "telecom"},
        {"name": "Monoprix Tunisie",            "matricule_fiscal": _matricule(r), "category": "supplies"},
        {"name": "Carrefour Tunisie",           "matricule_fiscal": _matricule(r), "category": "supplies"},
        {"name": "Station Total Berges du Lac", "matricule_fiscal": _matricule(r), "category": "fuel"},
        {"name": "Station Shell La Soukra",     "matricule_fiscal": _matricule(r), "category": "fuel"},
        {"name": "InfoPro IT Services",         "matricule_fiscal": _matricule(r), "category": "it"},
        {"name": "SysTech Solutions",           "matricule_fiscal": _matricule(r), "category": "it"},
        {"name": "DataSys SARL",                "matricule_fiscal": _matricule(r), "category": "it"},
    ]

def _make_suppliers_b():
    r = random.Random(SEED + 20)
    return [
        {"name": "STEG",                        "matricule_fiscal": _matricule(r), "category": "energy",     "currency": "TND"},
        {"name": "SONEDE",                       "matricule_fiscal": _matricule(r), "category": "water",      "currency": "TND"},
        {"name": "Tunisie Telecom",              "matricule_fiscal": _matricule(r), "category": "telecom",    "currency": "TND"},
        {"name": "Ooredoo Tunisie",             "matricule_fiscal": _matricule(r), "category": "telecom",    "currency": "TND"},
        {"name": "Orange Tunisie",              "matricule_fiscal": _matricule(r), "category": "telecom",    "currency": "TND"},
        {"name": "Monoprix Tunisie",            "matricule_fiscal": _matricule(r), "category": "supplies",   "currency": "TND"},
        {"name": "Carrefour Tunisie",           "matricule_fiscal": _matricule(r), "category": "supplies",   "currency": "TND"},
        {"name": "Station Total Berges du Lac", "matricule_fiscal": _matricule(r), "category": "fuel",       "currency": "TND"},
        {"name": "EuroTech Import SARL",        "matricule_fiscal": _matricule(r), "category": "it",         "currency": "EUR"},
        {"name": "TechVision International",    "matricule_fiscal": _matricule(r), "category": "consulting", "currency": "EUR"},
        {"name": "Conseil & Audit Beta",        "matricule_fiscal": _matricule(r), "category": "consulting", "currency": "TND"},
        {"name": "AssurPlus Courtage",          "matricule_fiscal": _matricule(r), "category": "insurance",  "currency": "TND"},
    ]

COMPANY_A_SUPPLIERS = _make_suppliers_a()
COMPANY_B_SUPPLIERS = _make_suppliers_b()

# Company A: inspired by Tunisian SCE class-6 — UNVERIFIED, check against official source
COMPANY_A_CODE_MAP = {
    "energy":   "606100",
    "telecom":  "626100",
    "fuel":     "606300",
    "supplies": "606200",
    "it":       "617000",
    "default":  "606000",
}

# Company B: format NNNN-CCNNN — UNVERIFIED
COMPANY_B_CODE_MAP = {
    "energy":     ("6060-EN001", 0.19),
    "water":      ("6060-EA001", 0.07),
    "telecom":    ("6261-TE001", 0.19),
    "fuel":       ("6060-CA001", 0.13),
    "supplies":   ("6060-FO001", 0.19),
    "it":         ("6170-IT001", 0.19),
    "consulting": ("6226-HO001", 0.19),
    "insurance":  ("6161-AS001", 0.07),
}

DOC_TYPES = ["invoice", "receipt", "purchase_order"]

# ── Meaningful line descriptions per category ─────────────────────────────────

LINE_DESCRIPTIONS = {
    "energy":     ["Consommation électricité", "Abonnement gaz naturel", "Consommation eau potable",
                   "Fourniture énergie basse tension", "Relevé mensuel électricité"],
    "telecom":    ["Abonnement téléphonique mensuel", "Forfait internet ADSL", "Communications mobiles",
                   "Location ligne fixe", "Services data 4G"],
    "fuel":       ["Carburant sans plomb 95", "Gasoil véhicule commercial", "Carburant diesel",
                   "Lubrifiants et additifs", "Gazole professionnel"],
    "supplies":   ["Fournitures de bureau", "Consommables informatiques", "Articles de papeterie",
                   "Produits d'entretien", "Matériel de nettoyage"],
    "it":         ["Maintenance informatique", "Licence logiciel annuelle", "Prestation développement",
                   "Support technique niveau 2", "Installation et configuration"],
    "consulting": ["Honoraires conseil financier", "Audit comptable", "Étude de marché",
                   "Mission consulting RH", "Rapport d'analyse stratégique"],
    "insurance":  ["Prime d'assurance multirisques", "Assurance responsabilité civile",
                   "Cotisation annuelle assurance", "Prime assurance véhicule de société"],
    "water":      ["Consommation eau potable", "Abonnement SONEDE", "Relevé eau mensuel"],
    "default":    ["Prestation de service", "Fourniture diverse", "Article divers"],
}

# House rules — text must NOT appear in public knowledge files
# These appear only in gold labels' metadata
HOUSE_RULES_A = [
    {
        "id": "HR-A1",
        "trigger": lambda doc, sup: sup["category"] == "energy" and doc["htva"] > 1000.0,
        "effect": "haute_consommation",
        "description": "Factures STEG HTVA > 1 000,000 TND → flag haute_consommation dans gold",
    },
    {
        "id": "HR-A2",
        "trigger": lambda doc, sup: sup["name"] == "SysTech Solutions" and doc["doc_type"] == "purchase_order",
        "effect": "force_code_617000",
        "description": "BC SysTech → toujours 617000 même si description dit 'matériel'",
    },
    {
        "id": "HR-A3",
        "trigger": lambda doc, sup: sup["name"] in ("Monoprix Tunisie", "Carrefour Tunisie")
                   and any("entretien" in ln["description"].lower() for ln in doc.get("lines", [])),
        "effect": "override_code_615000",
        "description": "Monoprix/Carrefour avec 'entretien' → code 615000 au lieu de 606200",
    },
    {
        "id": "HR-A4",
        "trigger": lambda doc, sup: doc["timbre_fiscal"] > 1.0,
        "effect": "needs_review_timbre",
        "description": "Timbre fiscal > 1,000 TND → needs_review: true automatique",
    },
]

HOUSE_RULES_B = [
    {
        "id": "HR-B1",
        "trigger": lambda doc, sup: sup.get("currency") == "EUR",
        "effect": "requires_conversion",
        "description": "Factures EUR (EuroTech, TechVision) → conversion BNB obligatoire dans gold",
    },
    {
        "id": "HR-B2",
        "trigger": lambda doc, sup: sup["name"] == "TechVision International" and doc["htva"] > 5000.0,
        "effect": "high_value_consulting",
        "description": "TechVision HTVA > 5 000 TND → needs_review: true avant acceptation",
    },
    {
        "id": "HR-B3",
        "trigger": lambda doc, sup: sup["name"] == "AssurPlus Courtage",
        "effect": "force_code_6161_AS001",
        "description": "AssurPlus → toujours 6161-AS001 quelle que soit la description",
    },
    {
        "id": "HR-B4",
        "trigger": lambda doc, sup: sup["name"] == "Station Total Berges du Lac"
                   and doc["doc_type"] == "purchase_order",
        "effect": "chantier_flag",
        "description": "BC carburant Station Total → flag chantier: true dans gold",
    },
]


# ── Document generation ───────────────────────────────────────────────────────

def _unique_reference(rng: random.Random, company_id: str, doc_type: str) -> str:
    """Generate a reference unique to the document, independent of corpus index."""
    prefix = {"invoice": "REF-FAC", "receipt": "REF-REC", "purchase_order": "REF-BC"}.get(doc_type, "REF")
    suffix = "".join(str(rng.randint(0, 9)) for _ in range(6))
    return f"{prefix}-{suffix}"


def generate_document(
    company_id: str,
    idx: int,
    rng: random.Random,
    inject_error: Optional[str] = None,
    existing_docs: Optional[list[dict]] = None,
) -> dict:
    """Generate a single document with gold JSON and all integrity checks."""

    prefix = "A" if company_id == "company_a" else "B"
    doc_id = f"{prefix}-DOC-{idx:04d}"

    if company_id == "company_a":
        supplier  = rng.choice(COMPANY_A_SUPPLIERS)
        tva_rate  = 0.19
        n_lines   = rng.randint(1, 3)
        cat       = supplier["category"]
        descs     = LINE_DESCRIPTIONS.get(cat, LINE_DESCRIPTIONS["default"])
        lines     = []
        for i in range(n_lines):
            desc   = rng.choice(descs)
            htva_u = round(rng.uniform(50.0, 1500.0), 3)
            qty    = rng.randint(1, 5)
            htva   = round(htva_u * qty, 3)
            tva    = round(htva * tva_rate, 3)
            ttc    = round(htva + tva, 3)
            lines.append({"description": desc, "quantity": qty,
                           "unit_price_htva": htva_u, "htva": htva,
                           "tva_rate": tva_rate, "tva": tva, "ttc": ttc})
        account_code = COMPANY_A_CODE_MAP.get(cat, COMPANY_A_CODE_MAP["default"])
        currency     = "TND"
    else:
        supplier    = rng.choice(COMPANY_B_SUPPLIERS)
        code, tva_rate = COMPANY_B_CODE_MAP.get(supplier["category"], ("6010-AC001", 0.19))
        account_code   = code
        currency       = supplier.get("currency", "TND")
        n_lines        = rng.randint(1, 3)
        cat            = supplier["category"]
        descs          = LINE_DESCRIPTIONS.get(cat, LINE_DESCRIPTIONS["default"])
        lines          = []
        for i in range(n_lines):
            desc   = rng.choice(descs)
            htva_u = round(rng.uniform(100.0, 3000.0), 3)
            qty    = rng.randint(1, 3)
            htva   = round(htva_u * qty, 3)
            tva    = round(htva * tva_rate, 3)
            ttc    = round(htva + tva, 3)
            lines.append({"description": desc, "quantity": qty,
                           "unit_price_htva": htva_u, "htva": htva,
                           "tva_rate": tva_rate, "tva": tva, "ttc": ttc})

    total_htva = round(sum(l["htva"] for l in lines), 3)
    total_tva  = round(sum(l["tva"]  for l in lines), 3)
    total_ttc  = round(total_htva + total_tva, 3)

    doc_type  = rng.choice(DOC_TYPES)
    doc_date  = _random_date(rng)
    doc_prefix = {"invoice": "FAC", "receipt": "REC", "purchase_order": "BC"}[doc_type]
    number    = f"{doc_prefix}-{rng.randint(1000, 9999)}"
    ref_unique = _unique_reference(rng, company_id, doc_type)

    matricule = supplier["matricule_fiscal"]
    injected_errors: list[str] = []
    duplicate_of: Optional[str] = None
    duplicate_source = None

    # Apply error injection
    if inject_error == "arithmetic_mismatch":
        total_ttc = round(total_ttc + rng.uniform(0.5, 5.0), 3)
        injected_errors.append("arithmetic_mismatch")
    elif inject_error == "missing_matricule":
        matricule = ""
        injected_errors.append("missing_matricule")
    elif inject_error == "duplicate_id":
        # Make a genuine content duplicate of an earlier document while keeping
        # this record's ingestion ID distinct.
        if existing_docs:
            duplicate_source = rng.choice(existing_docs)
            duplicate_of = duplicate_source["doc_id"]
        injected_errors.append("duplicate_id")

    # Apply house rules
    applied_house_rules = []
    house_rules = HOUSE_RULES_A if company_id == "company_a" else HOUSE_RULES_B
    doc_tmp = {"htva": total_htva, "doc_type": doc_type,
               "timbre_fiscal": TIMBRE_FISCAL, "lines": lines}
    for hr in house_rules:
        try:
            if hr["trigger"](doc_tmp, supplier):
                applied_house_rules.append(hr["id"])
                # Apply override effects
                if hr["effect"] == "force_code_617000":
                    account_code = "617000"
                elif hr["effect"] == "override_code_615000":
                    account_code = "615000"
                elif hr["effect"] == "force_code_6161_AS001":
                    account_code = "6161-AS001"
        except Exception:
            pass

    doc = {
        "doc_id":          doc_id,
        "company_id":      company_id,
        "doc_type":        doc_type,
        "supplier":        supplier["name"],
        "matricule_fiscal": matricule,
        "date":            format_date(doc_date),
        "number":          number,
        "reference_unique": ref_unique,
        "lines":           lines,
        "htva":            total_htva,
        "tva":             total_tva,
        "ttc":             total_ttc,
        "timbre_fiscal":   TIMBRE_FISCAL,
        "account_code":    account_code,
        "injected_errors": injected_errors,
        "duplicate_of":    duplicate_of,
        "currency":        currency,
        "applied_house_rules": applied_house_rules,
        "fields": {
            "supplier":          supplier["name"],
            "date":              format_date(doc_date),
            "number":            number,
            "reference_unique":  ref_unique,
            "htva":              format_tnd(total_htva),
            "tva":               format_tnd(total_tva),
            "ttc":               format_tnd(total_ttc),
            "timbre_fiscal":     format_tnd(TIMBRE_FISCAL),
            "matricule_fiscal":  matricule,
            "currency":          currency,
            "line_descriptions": [l["description"] for l in lines],
        },
    }

    if duplicate_source is not None:
        for key in ("doc_type", "supplier", "matricule_fiscal", "date", "number",
                    "reference_unique", "lines", "htva", "tva", "ttc", "currency",
                    "account_code", "applied_house_rules"):
            doc[key] = deepcopy(duplicate_source[key])
        doc["fields"] = deepcopy(duplicate_source["fields"])

    # Integrity check: ttc == htva + tva (unless seeded mismatch)
    if "arithmetic_mismatch" not in injected_errors:
        expected = round(total_htva + total_tva, 3)
        if abs(expected - total_ttc) > 0.005:
            raise ValueError(
                f"[GENERATOR BUG] {doc_id}: ttc={total_ttc} != htva+tva={expected}"
            )

    return doc


# ── Public helper functions (used by tests and SkillOpt) ─────────────────────

def split_corpus(docs: list[dict], seed: int = SEED) -> dict[str, list[dict]]:
    """
    Public wrapper: split a flat list of docs into train/selection/test dicts.
    Returns {"train": [...], "selection": [...], "test": [...]} where each item
    is the full doc dict (not just an ID).

    Uses SPLIT counts: train=70, selection=30, test=50 per 150 docs.
    Scales proportionally for smaller corpora.
    """
    rng = random.Random(seed)
    n = len(docs)
    if n == 0:
        return {"train": [], "selection": [], "test": []}

    # Scale SPLIT proportionally
    total_split = sum(SPLIT.values())  # 150
    counts = {
        "train":     max(1, round(n * SPLIT["train"] / total_split)),
        "selection": max(1, round(n * SPLIT["selection"] / total_split)),
        "test":      0,
    }
    counts["test"] = max(0, n - counts["train"] - counts["selection"])

    shuffled = docs[:]
    rng.shuffle(shuffled)

    train = shuffled[:counts["train"]]
    sel   = shuffled[counts["train"]:counts["train"] + counts["selection"]]
    test  = shuffled[counts["train"] + counts["selection"]:]

    return {"train": train, "selection": sel, "test": test}


def inject_error(doc: dict, error_type: str) -> dict:
    """
    Public wrapper: inject exactly one error into a doc dict (copy, non-destructive).
    error_type: "duplicate_id" | "arithmetic_mismatch" | "missing_nif" | "missing_matricule"
    """
    import copy
    doc = copy.deepcopy(doc)

    if error_type == "arithmetic_mismatch":
        doc["ttc"] = doc.get("ttc", 0) + 1.234
        doc["injected_errors"] = ["arithmetic_mismatch"]

    elif error_type in ("missing_nif", "missing_matricule"):
        doc["matricule_fiscal"] = ""
        doc["nif"] = ""
        doc["injected_errors"] = ["missing_matricule"]

    elif error_type == "duplicate_id":
        original_id = doc.get("doc_id", "UNKNOWN")
        doc["duplicate_of"] = original_id
        doc["injected_errors"] = ["duplicate_id"]

    else:
        doc["injected_errors"] = [error_type]

    return doc


# ── Corpus generation with stratification ────────────────────────────────────

def generate_corpus(company_id: str, n: int = N_DOCS) -> list[dict]:
    """
    Generate n documents with stratified error injection.
    All three error types and all doc types appear proportionally.
    """
    rng    = random.Random(SEED)
    errors = ["duplicate_id", "arithmetic_mismatch", "missing_matricule"]
    n_err  = max(3, round(n * ERROR_RATE))

    # Stratify: ~equal error types
    error_assignments = (errors * (n_err // 3 + 1))[:n_err]
    rng.shuffle(error_assignments)
    err_indices = set(rng.sample(range(n), n_err))

    docs: list[dict] = []
    existing_docs: list[dict] = []
    err_iter = iter(error_assignments)

    for i in range(n):
        err = next(err_iter) if i in err_indices else None
        doc = generate_document(company_id, i, rng,
                                inject_error=err, existing_docs=existing_docs[:])
        existing_docs.append(doc)
        docs.append(doc)

    return docs


def _stratified_split(docs: list[dict], counts: dict[str, int]) -> dict[str, list[str]]:
    """
    Produce train/selection/test splits with stratification by:
    - doc_type (invoice / receipt / purchase_order)
    - error type (no error / arithmetic / duplicate / missing_matricule)
    - account_code

    Falls back to shuffle if stratification can't be satisfied exactly.
    """
    rng = random.Random(SEED)

    # Group by strata key
    from collections import defaultdict
    strata: dict[str, list[str]] = defaultdict(list)
    for doc in docs:
        err_type = doc["injected_errors"][0] if doc["injected_errors"] else "none"
        key = f"{doc['doc_type']}|{err_type}|{doc['account_code']}"
        strata[key].append(doc["doc_id"])

    train_ids: list[str] = []
    sel_ids:   list[str] = []
    test_ids:  list[str] = []

    for key, ids in strata.items():
        rng.shuffle(ids)
        n = len(ids)
        # Proportional allocation
        n_train = max(1, round(n * counts["train"] / sum(counts.values())))
        n_sel   = max(1, round(n * counts["selection"] / sum(counts.values())))
        n_test  = n - n_train - n_sel
        if n_test < 0:
            n_test = 0
            n_sel  = n - n_train
        train_ids.extend(ids[:n_train])
        sel_ids.extend(ids[n_train:n_train + n_sel])
        test_ids.extend(ids[n_train + n_sel:n_train + n_sel + n_test])

    # Trim/pad to exact counts
    rng.shuffle(train_ids); rng.shuffle(sel_ids); rng.shuffle(test_ids)
    all_remaining = train_ids[counts["train"]:] + sel_ids[counts["selection"]:] + test_ids[counts["test"]:]
    train_ids = train_ids[:counts["train"]]
    sel_ids   = sel_ids[:counts["selection"]]
    test_ids  = test_ids[:counts["test"]]

    # Fill shortfalls from remaining
    rng.shuffle(all_remaining)
    pool = iter(all_remaining)
    while len(train_ids) < counts["train"]:
        try:
            train_ids.append(next(pool))
        except StopIteration:
            break
    while len(sel_ids) < counts["selection"]:
        try:
            sel_ids.append(next(pool))
        except StopIteration:
            break
    while len(test_ids) < counts["test"]:
        try:
            test_ids.append(next(pool))
        except StopIteration:
            break

    return {"train": train_ids, "selection": sel_ids, "test": test_ids}


# ── PDF generation ────────────────────────────────────────────────────────────

def generate_pdf(doc: dict, output_path: str) -> None:
    if not REPORTLAB_OK:
        raise ImportError(
            "reportlab is required for PDF generation. "
            "Install: pip install reportlab"
        )
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    c  = rl_canvas.Canvas(output_path, pagesize=A4)
    w, h = A4
    y  = h - 2 * cm
    lh = 0.6 * cm

    def t(x, yy, s, font="Helvetica", size=10):
        c.setFont(font, size)
        # Encode for reportlab (strip non-latin chars)
        safe = s.encode("latin-1", errors="replace").decode("latin-1")
        c.drawString(x, yy, safe)

    def hr(yy):
        c.setLineWidth(0.5)
        c.line(1.5 * cm, yy, w - 1.5 * cm, yy)

    labels = {"invoice": "FACTURE", "receipt": "RECU", "purchase_order": "BON DE COMMANDE"}
    t(1.5*cm, y, labels.get(doc["doc_type"], "DOCUMENT"), "Helvetica-Bold", 16); y -= 1.2*lh
    t(1.5*cm, y, f"N : {doc['number']}", size=11); y -= lh
    t(1.5*cm, y, f"Ref : {doc.get('reference_unique', '')}", size=10); y -= lh
    t(1.5*cm, y, f"Date : {doc['date']}", size=11); y -= lh
    t(1.5*cm, y, f"Document : {doc['doc_id']}", size=9); y -= 1.5*lh
    t(1.5*cm, y, "FOURNISSEUR", "Helvetica-Bold", 11); y -= lh
    t(1.5*cm, y, f"Nom : {doc['supplier']}"); y -= lh
    mf = doc.get("matricule_fiscal") or "(manquant)"
    t(1.5*cm, y, f"Matricule fiscal : {mf}"); y -= 1.5*lh
    hr(y); y -= 0.5*lh
    t(1.5*cm, y, "Description", "Helvetica-Bold", 9)
    t(9*cm,   y, "HTVA",        "Helvetica-Bold", 9)
    t(12*cm,  y, "TVA",         "Helvetica-Bold", 9)
    t(15*cm,  y, "TTC",         "Helvetica-Bold", 9)
    y -= 0.8*lh; hr(y); y -= 0.5*lh
    currency = doc.get("currency", "TND")
    for ln in doc.get("lines", []):
        pct  = int(ln.get("tva_rate", 0.19) * 100)
        desc = ln.get("description", "")[:40]
        t(1.5*cm, y, desc,                              size=9)
        t(9*cm,   y, format_tnd(ln["htva"]),            size=9)
        t(12*cm,  y, f"{format_tnd(ln['tva'])} ({pct}%)", size=9)
        t(15*cm,  y, format_tnd(ln["ttc"]),             size=9)
        y -= lh
    hr(y); y -= 0.5*lh
    t(9*cm,  y, f"Total HTVA : {format_tnd(doc['htva'])} {currency}",     "Helvetica-Bold", 10); y -= lh
    t(9*cm,  y, f"Total TVA  : {format_tnd(doc['tva'])} {currency}",      size=10);              y -= lh
    t(9*cm,  y, f"Timbre fiscal : {format_tnd(doc['timbre_fiscal'])} TND", size=10);              y -= lh
    t(9*cm,  y, f"Total TTC  : {format_tnd(doc['ttc'])} {currency}",      "Helvetica-Bold", 11); y -= 1.5*lh
    t(1.5*cm, y, "Inspire du SCE tunisien — codes non verifies officiellement", size=7)
    c.save()


def _apply_photo_effects(img, rng: random.Random, hard: bool = False) -> "PILImage":
    """Apply rotation and Gaussian noise. hard=True uses stronger degradation."""
    if hard:
        angle   = rng.uniform(8.0, 15.0)
        sigma   = rng.uniform(15.0, 20.0)
    else:
        angle   = rng.uniform(-3.0, 3.0)
        sigma   = rng.uniform(3.0, 7.0)
    img = img.rotate(angle, expand=True, fillcolor=(255, 255, 255))
    arr = np.array(img).astype(np.float32)
    np.random.seed(SEED)
    noise = np.random.normal(0, sigma, arr.shape).astype(np.float32)
    arr   = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return PILImage.fromarray(arr)


def generate_photo_variant(pdf_path: str, output_path: str, hard: bool = False) -> None:
    """Render PDF to JPEG with rotation and noise. hard=True uses stronger degradation."""
    if not PIL_OK:
        raise ImportError("Pillow is required for photo variants. Install: pip install Pillow")
    if not PDF2IMAGE_OK:
        raise ImportError("pdf2image is required for photo variants. Install: pip install pdf2image")
    pages = _p2i.convert_from_path(pdf_path, dpi=150)
    if not pages:
        return
    rng  = random.Random(SEED + hash(pdf_path) % 10000)
    img  = _apply_photo_effects(pages[0], rng, hard=hard)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    quality = rng.randint(55, 65) if hard else 85
    img.save(output_path, "JPEG", quality=quality)


# ── Main entry point ──────────────────────────────────────────────────────────

def main():
    root      = Path(__file__).parent.parent
    all_splits: dict = {}

    for company_id in ["company_a", "company_b"]:
        print(f"\n=== Generating {company_id} (n={N_DOCS}) ===")
        out_dir = root / "data" / company_id / "documents"
        out_dir.mkdir(parents=True, exist_ok=True)

        random.seed(SEED)
        np.random.seed(SEED)

        docs   = generate_corpus(company_id, n=N_DOCS)
        splits = _stratified_split(docs, SPLIT)
        all_splits[company_id] = splits

        n_tr = len(splits["train"])
        n_se = len(splits["selection"])
        n_te = len(splits["test"])
        print(f"  {len(docs)} docs | TRAIN={n_tr} SEL={n_se} TEST={n_te}")

        for doc in docs:
            doc_id  = doc["doc_id"]
            pdf_p   = str(out_dir / f"{doc_id}.pdf")
            photo_p = str(out_dir / f"{doc_id}_photo.jpg")
            hard_p  = str(out_dir / f"{doc_id}_photo_hard.jpg")
            gold_p  = str(out_dir / f"{doc_id}_gold.json")

            try:
                generate_pdf(doc, pdf_p)
            except ImportError as e:
                print(f"  WARN: {e}")

            if Path(pdf_p).exists():
                try:
                    generate_photo_variant(pdf_p, photo_p, hard=False)
                    generate_photo_variant(pdf_p, hard_p,  hard=True)
                except (ImportError, Exception) as e:
                    print(f"  WARN photo: {e}")

            gold = {k: doc[k] for k in (
                "doc_id", "doc_type", "fields", "account_code",
                "injected_errors", "company_id", "applied_house_rules",
                "duplicate_of", "reference_unique",
            )}
            Path(gold_p).write_text(
                json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    splits_path = root / "data" / "splits.json"
    splits_path.write_text(
        json.dumps(all_splits, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nWrote {splits_path}")

    _generate_demo(root)
    print("Done.")


def _generate_demo(root: Path) -> None:
    demo_dir = root / "demo"
    demo_dir.mkdir(exist_ok=True)
    rng = random.Random(SEED + 9999)

    d1 = generate_document("company_a", 9000, rng, inject_error=None)
    d1["doc_id"] = "DEMO-A-CLEAN"
    try:
        generate_pdf(d1, str(demo_dir / "clean_invoice.pdf"))
    except ImportError:
        pass

    d2 = generate_document("company_a", 9001, rng, inject_error=None)
    d2["doc_id"] = "DEMO-A-PHOTO"
    d2["doc_type"] = "receipt"
    tmp = str(demo_dir / "_tmp.pdf")
    try:
        generate_pdf(d2, tmp)
        if Path(tmp).exists():
            generate_photo_variant(tmp, str(demo_dir / "photo_receipt.jpg"), hard=False)
            generate_photo_variant(tmp, str(demo_dir / "photo_receipt_hard.jpg"), hard=True)
            Path(tmp).unlink(missing_ok=True)
    except (ImportError, Exception):
        pass

    d3 = generate_document("company_a", 9002, rng, inject_error=None)
    d3["doc_id"] = "DEMO-A-HOUSE"
    d3["supplier"] = "SysTech Solutions"
    d3["matricule_fiscal"] = d3.get("matricule_fiscal", "")
    d3["doc_type"] = "purchase_order"
    try:
        generate_pdf(d3, str(demo_dir / "house_rule_po.pdf"))
    except ImportError:
        pass

    d4 = generate_document("company_a", 9003, rng, inject_error="arithmetic_mismatch")
    d4["doc_id"] = "DEMO-A-ERROR"
    try:
        generate_pdf(d4, str(demo_dir / "arithmetic_error.pdf"))
    except ImportError:
        pass

    for doc, name in [(d1, "clean_invoice"), (d3, "house_rule_po"), (d4, "arithmetic_error")]:
        gold = {k: doc[k] for k in (
            "doc_id", "doc_type", "fields", "account_code",
            "injected_errors", "company_id", "applied_house_rules",
        )}
        (demo_dir / f"{name}_gold.json").write_text(
            json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print("Demo docs generated.")


if __name__ == "__main__":
    main()
