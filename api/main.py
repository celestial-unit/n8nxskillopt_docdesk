"""
api/main.py — FastAPI application for the multi-agent document pipeline.

Core pipeline endpoints:
  POST /route, /extract, /code, /validate, /handle, /accept, /escalate, /fail
  GET  /trace/{id}, /health

Every pipeline and human-review endpoint writes an append-only event to SQLite.
CORS is enabled for all origins.
"""

import json
import re
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from api.db import TraceStore
from api.models import (
    RouteRequest, RouteResponse,
    ExtractRequest, ExtractResponse,
    CodeRequest, CodeResponse,
    ValidateRequest, ValidateResponse,
    HandleRequest, HandleResponse,
    AcceptRequest, EscalateRequest, FailRequest,
    HealthResponse, DocumentReviewRequest,
)
from agents.llm_client import LLMClient
from agents.skill_loader import load_skill
from agents.router_agent import RouterAgent
from agents.extractor_agent import ExtractorAgent
from agents.coder_agent import CoderAgent
from agents.validator_agent import ValidatorAgent
from agents.exception_handler_agent import ExceptionHandlerAgent
from agents.multimodal import detect_modality, extract_text_from_pdf, transcribe_document_via_vision

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="Document Pipeline API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Singletons (initialized lazily or at startup)
_db: TraceStore | None = None
_llm: LLMClient | None = None


def get_db() -> TraceStore:
    global _db
    if _db is None:
        _db = TraceStore("./traces.db")
    return _db


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm


# Ensure inbox exists
Path("./inbox").mkdir(exist_ok=True)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/route", response_model=RouteResponse)
def route(req: RouteRequest):
    """
    Extract text from a text-layer PDF or transcribe a scan/photo with the vision model.
    Doc_type is guessed from the resulting text.
    """
    import base64, tempfile, os, re
    db = get_db()
    t0 = time.monotonic()

    text = req.text or ""
    modality = "text"
    doc_type = "invoice"  # default

    if req.filename and req.file_b64:
        ext = Path(req.filename).suffix.lower()
        if ext not in {".pdf", ".jpg", ".jpeg", ".png", ".webp"}:
            raise HTTPException(status_code=415, detail="Supported files: PDF, JPG, PNG, WEBP")
        try:
            file_bytes = base64.b64decode(req.file_b64, validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail="file_b64 is not valid base64")
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            modality = detect_modality(tmp_path)
            if modality == "text":
                text = extract_text_from_pdf(tmp_path)
            else:
                text = transcribe_document_via_vision(tmp_path, req.file_b64, get_llm())
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Could not read document: {exc}") from exc
        finally:
            os.unlink(tmp_path)

    # Guess type from document content, including vision-transcribed scans.
    text_lower = (text or "").lower()
    if "bon de commande" in text_lower or "bondecommande" in text_lower or "purchase order" in text_lower:
        doc_type = "purchase_order"
    elif "reçu" in text_lower or "recu" in text_lower or "receipt" in text_lower:
        doc_type = "receipt"
    elif "facture" in text_lower or "invoice" in text_lower:
        doc_type = "invoice"

    result = {
        "doc_type": doc_type,
        "modality": modality,
        "company_id": req.company_id,
        "filename": req.filename or "",
        "source_text": text,
        "skill_version": "deterministic-v1",
    }

    duration_ms = int((time.monotonic() - t0) * 1000)
    trace_id = db.write(req.doc_id, "route", "success", duration_ms, result, [], result["skill_version"])

    return RouteResponse(
        doc_id=req.doc_id,
        company_id=req.company_id,
        doc_type=result["doc_type"],
        modality=result["modality"],
        source_text=text,
        skill_version=result["skill_version"],
        trace_id=trace_id,
    )


@app.post("/extract", response_model=ExtractResponse)
def extract(req: ExtractRequest):
    db = get_db()
    llm = get_llm()
    t0 = time.monotonic()

    agent = ExtractorAgent(llm_client=llm)
    try:
        result = agent.run({"text": req.text, "doc_type": req.doc_type}, req.company_id)
    except Exception as e:
        duration_ms = int((time.monotonic() - t0) * 1000)
        db.write(req.doc_id, "extract", "error", duration_ms, {"error": str(e), "company_id": req.company_id}, [], "")
        raise HTTPException(status_code=500, detail=str(e))

    duration_ms = int((time.monotonic() - t0) * 1000)
    trace_output = {**result, "company_id": req.company_id, "source_text": req.text}
    trace_id = db.write(req.doc_id, "extract", "success", duration_ms, trace_output, [], result.get("skill_version", ""))

    return ExtractResponse(
        doc_id=req.doc_id,
        supplier=result.get("supplier"),
        date=result.get("date"),
        number=result.get("number"),
        lines=result.get("lines", []),
        htva=result.get("htva"),
        tva=result.get("tva"),
        ttc=result.get("ttc"),
        timbre_fiscal=result.get("timbre_fiscal"),
        matricule_fiscal=result.get("matricule_fiscal"),
        currency=result.get("currency", "TND"),
        skill_version=result.get("skill_version", ""),
        trace_id=trace_id,
    )


@app.post("/code", response_model=CodeResponse)
def code(req: CodeRequest):
    db = get_db()
    llm = get_llm()
    t0 = time.monotonic()

    agent = CoderAgent(llm_client=llm)
    try:
        result = agent.run(
            {"extracted": req.extracted, "doc_type": req.doc_type},
            req.company_id,
            rag_enabled=req.rag_enabled,
        )
    except Exception as e:
        duration_ms = int((time.monotonic() - t0) * 1000)
        db.write(req.doc_id, "code", "error", duration_ms, {"error": str(e), "company_id": req.company_id}, [], "")
        raise HTTPException(status_code=500, detail=str(e))

    duration_ms = int((time.monotonic() - t0) * 1000)
    chunks = result.get("chunks", [])
    trace_id = db.write(req.doc_id, "code", "success", duration_ms, {**result, "company_id": req.company_id}, chunks, result["skill_version"])

    return CodeResponse(
        doc_id=req.doc_id,
        account_code=result["account_code"],
        cited_rule=result["cited_rule"],
        chunks=chunks,
        skill_version=result["skill_version"],
        trace_id=trace_id,
    )


@app.post("/validate", response_model=ValidateResponse)
def validate(req: ValidateRequest):
    db = get_db()
    llm = get_llm()
    t0 = time.monotonic()

    agent = ValidatorAgent(llm_client=llm, trace_store=db)
    try:
        # Python checks first — no LLM needed
        extracted = req.extracted
        doc_id = req.doc_id
        errors: list[str] = []

        # Check 1: Arithmetic — tolerance 0.005 TND (per steering rules)
        try:
            from decimal import Decimal, InvalidOperation
            def parse_amount(v):
                if v is None: return Decimal(0)
                s = str(v).replace('\u202f','').replace(' ','').replace(',','.')
                try: return Decimal(s)
                except InvalidOperation: return Decimal(float(s))
            dhtva = parse_amount(extracted.get("htva"))
            dtva  = parse_amount(extracted.get("tva"))
            dttc  = parse_amount(extracted.get("ttc"))
            if dttc != 0 and abs(dhtva + dtva - dttc) > Decimal("0.005"):
                errors.append("arithmetic_mismatch")
        except Exception:
            errors.append("arithmetic_mismatch")

        # Check 2: Matricule fiscal presence (accepts both field names)
        mf = extracted.get("matricule_fiscal")  or ""
        if not str(mf).strip():
            errors.append("missing_matricule")

        # Check 3: Match supplier + invoice number + date against prior business
        # documents. The trace log is not used for this: only completed pipeline
        # records reach validation, and replaying the same doc_id is idempotent.
        duplicate_of = db.register_document_key(
            company_id=req.company_id,
            supplier=extracted.get("supplier") or "",
            number=extracted.get("number") or "",
            date=extracted.get("date") or "",
            doc_id=doc_id,
        )
        if duplicate_of:
            errors.append("duplicate_id")

        needs_review = len(errors) > 0

        # Only call LLM for explanation if there are errors (conditional)
        if needs_review:
            skill_text, skill_version = load_skill(req.company_id, "validator")
            error_summary = ", ".join(errors)
            user_msg = (
                f"Résultat des vérifications Python sur le document {doc_id}:\n"
                f"Erreurs détectées: {error_summary}\n\n"
                f"Champs extraits:\n"
                f"  HTVA: {extracted.get('htva')}, TVA: {extracted.get('tva')}, TTC: {extracted.get('ttc')}\n"
                f"  Matricule fiscal: {extracted.get('matricule_fiscal', '')}\n"
                f"  Fournisseur: {extracted.get('supplier')}\n\n"
                f"  Document précédent correspondant: {duplicate_of or 'aucun'}\n\n"
                f"Génère UNE SEULE PHRASE d'explication."
            )
            explanation = llm.call(role="agent", system_prompt=skill_text, user_message=user_msg)
            explanation = explanation.strip().split("\n")[0]
        else:
            skill_version = "template-v1"
            explanation = ("Le document est arithmétiquement cohérent, le matricule fiscal est présent "
                          "et aucun doublon d'identifiant n'a été détecté.")

        result = {
            "valid": not needs_review,
            "errors": errors,
            "explanation": explanation,
            "needs_review": needs_review,
            "duplicate_of": duplicate_of,
            "skill_version": skill_version,
        }
    except Exception as e:
        duration_ms = int((time.monotonic() - t0) * 1000)
        db.write(req.doc_id, "validate", "error", duration_ms, {"error": str(e), "company_id": req.company_id}, [], "")
        raise HTTPException(status_code=500, detail=str(e))

    duration_ms = int((time.monotonic() - t0) * 1000)
    trace_id = db.write(req.doc_id, "validate", "success", duration_ms, {**result, "company_id": req.company_id}, [], result["skill_version"])

    return ValidateResponse(
        doc_id=req.doc_id,
        valid=result["valid"],
        errors=result["errors"],
        explanation=result["explanation"],
        needs_review=result["needs_review"],
        duplicate_of=result["duplicate_of"],
        skill_version=result["skill_version"],
        trace_id=trace_id,
    )


@app.post("/handle", response_model=HandleResponse)
def handle(req: HandleRequest):
    db = get_db()
    llm = get_llm()
    t0 = time.monotonic()

    agent = ExceptionHandlerAgent(llm_client=llm)
    try:
        result = agent.run(
            {"extracted": req.extracted, "validation": req.validation, "doc_id": req.doc_id},
            req.company_id,
        )
    except Exception as e:
        duration_ms = int((time.monotonic() - t0) * 1000)
        db.write(req.doc_id, "handle", "error", duration_ms, {"error": str(e), "company_id": req.company_id}, [], "")
        raise HTTPException(status_code=500, detail=str(e))

    duration_ms = int((time.monotonic() - t0) * 1000)
    trace_id = db.write(req.doc_id, "handle", "success", duration_ms, {**result, "company_id": req.company_id}, [], result["skill_version"])

    return HandleResponse(
        doc_id=req.doc_id,
        escalation_dossier=result["escalation_dossier"],
        skill_version=result["skill_version"],
        trace_id=trace_id,
    )


@app.post("/accept")
def accept(req: AcceptRequest):
    db = get_db()
    trace_id = db.write(req.doc_id, "accept", "success", 0, {"decision": "ACCEPTED", "result": req.result or {}}, [], "")
    return {"doc_id": req.doc_id, "decision": "ACCEPTED", "trace_id": trace_id}


@app.post("/escalate")
def escalate(req: EscalateRequest):
    db = get_db()
    trace_id = db.write(req.doc_id, "escalate", "success", 0, {"decision": "ESCALATED", "dossier": req.dossier or {}}, [], "")
    return {"doc_id": req.doc_id, "decision": "ESCALATED", "trace_id": trace_id}


@app.post("/fail")
def fail(req: FailRequest):
    db = get_db()
    trace_id = db.write(req.doc_id, "fail", "error", 0, {"error": req.error}, [], "")
    return {"doc_id": req.doc_id, "status": "FAILED", "trace_id": trace_id}


@app.get("/eval/retrieval")
def eval_retrieval():
    """Return measured retrieval metrics and cohort sizes from the JSON artifact."""
    import json
    import re
    json_path = Path("eval/results/retrieval_eval.json")
    if json_path.exists():
        try:
            metrics = json.loads(json_path.read_text(encoding="utf-8"))
            a, b = metrics.get("company_a", {}), metrics.get("company_b", {})
            return {
                "recallA": a.get("recall_at_5"), "mrrA": a.get("mrr_at_5"),
                "recallB": b.get("recall_at_5"), "mrrB": b.get("mrr_at_5"),
                "nQueriesA": a.get("n_queries"), "nQueriesB": b.get("n_queries"),
                "nChunksA": a.get("n_chunks"), "nChunksB": b.get("n_chunks"),
            }
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    path = Path("eval/results/retrieval_eval.md")
    if not path.exists():
        return {"recallA": None, "mrrA": None, "recallB": None, "mrrB": None,
                "nQueriesA": None, "nQueriesB": None, "nChunksA": None, "nChunksB": None}
    text = path.read_text()
    result = {"recallA": None, "mrrA": None, "recallB": None, "mrrB": None,
              "nQueriesA": None, "nQueriesB": None, "nChunksA": None, "nChunksB": None}
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        if cells[0] not in {"company_a", "company_b"}:
            continue
        company = "A" if cells[0] == "company_a" else "B"
        try:
            result[f"recall{company}"] = float(cells[2])
            result[f"mrr{company}"] = float(cells[3])
            result[f"nQueries{company}"] = int(cells[1])
        except ValueError:
            continue
    return result


@app.get("/eval/baseline")
def eval_baseline():
    """Return baseline scores from eval/results/baseline.md."""
    import re
    path = Path("eval/results/baseline.md")
    if not path.exists():
        return None
    text = path.read_text()
    result = {"companyA": None, "companyB": None}
    for line in text.splitlines():
        # Match table rows: | company_a | 30 | 0.6061 | 0.3 | 0.1 | 0.1083 |
        m = re.search(r"company_a\s*\|\s*\d+\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)", line)
        if m:
            result["companyA"] = {
                "extractor": float(m.group(1)),
                "coderRag": float(m.group(2)),
                "coderNoRag": float(m.group(3)),
                "validator": float(m.group(4)),
            }
        m = re.search(r"company_b\s*\|\s*\d+\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)", line)
        if m:
            result["companyB"] = {
                "extractor": float(m.group(1)),
                "coderRag": float(m.group(2)),
                "coderNoRag": float(m.group(3)),
                "validator": float(m.group(4)),
            }
    return result


@app.get("/eval/coder-improvement")
def eval_coder_improvement():
    """Return the latest paired Company B Coder prompt comparison."""
    path = Path(__file__).resolve().parents[1] / "eval/results/company_b_coder_improvement.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@app.get("/skillopt/summary")
def skillopt_summary():
    """Expose actual SkillOpt CLI state, baseline, best score, and gate."""
    from api.skillopt_service import summary
    result = summary()
    run = result["run"]
    return {**result, "status": run.get("status", "not_run"),
            "results_valid": run.get("status") in {"complete", "running"}}


@app.post("/skillopt/run")
def run_docdesk_skillopt():
    """Start the installed SkillOpt trainer on the focused Company B corpus."""
    try:
        from api.skillopt_service import start
        return start()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SkillOpt run failed: {type(exc).__name__}: {exc}") from exc


@app.get("/skillopt/history")
def skillopt_history():
    """Return skill versions, step scores, gate decisions, and run log."""
    from api.skillopt_service import history
    return history()


@app.get("/skillopt/showcase")
def skillopt_showcase():
    """Expose the isolated, deliberately weak-skill SkillOpt demo metrics."""
    import json
    from pathlib import Path

    artifact = Path(__file__).resolve().parents[1] / "eval/results/skillopt_improvement_showcase.json"
    if artifact.exists():
        return json.loads(artifact.read_text(encoding="utf-8"))
    run_dir = Path(__file__).resolve().parents[1] / "skillopt_output/company_b_extractor_showcase"
    state_path = run_dir / "runtime_state.json"
    baseline_dir = run_dir / "selection_eval_baseline/predictions"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        baseline_scores = []
        for prediction in baseline_dir.glob("*/conversation.json"):
            record = json.loads(prediction.read_text(encoding="utf-8"))
            if isinstance(record.get("nem"), (int, float)):
                baseline_scores.append(float(record["nem"]))
        selection_size = len(json.loads((Path(__file__).resolve().parents[1] /
                                         "skillopt_data/company_b_balanced/selection.json").read_text(encoding="utf-8")))
        return {
            "status": "running",
            "label": "Deliberately weak Extractor prompt",
            "selection": {
                "weak_baseline": sum(baseline_scores) / len(baseline_scores) if baseline_scores else None,
                "optimized": state.get("best_score"),
                "total": selection_size,
            },
            "note": "Live SELECTION scores; the untouched TEST comparison will appear when SkillOpt finishes.",
        }
    return {"status": "pending"}


@app.get("/docs-list")
def docs_list(limit: int = Query(default=200, ge=1, le=10000)):
    """List stored documents with final extracted, coded, and reviewed values."""
    db = get_db()
    result = []
    for row in db.list_doc_ids(limit=limit):
        doc_id = row["doc_id"]
        traces = db.get_by_doc_id(doc_id)
        fields = db.get_extraction_fields(doc_id)
        outputs = {step: db.get_latest_output(doc_id, step) for step in ("route", "extract", "code", "validate", "review")}
        route_data = outputs["route"]
        code_data = outputs["code"]
        review_data = outputs["review"]
        validation = outputs["validate"]
        company_id = next((outputs[step].get("company_id") for step in ("route", "extract", "code", "validate") if outputs[step].get("company_id")), None)
        result.append({
            **row,
            # Historical trace DBs also contain deliberate test/debug calls.
            # Keep them auditable, but let the UI separate them from intake.
            "is_diagnostic": bool(re.match(
                r"^(?:debug(?:-|$)|test(?:-|$)|e2e(?:-|$)|tol\d|demo(?:-|$)|=+$)",
                doc_id, re.IGNORECASE,
            )),
            "is_complete": row.get("decision") is not None,
            "trace_count": len(traces),
            "company_id": company_id,
            "doc_type": route_data.get("doc_type"),
            "modality": route_data.get("modality"),
            "filename": route_data.get("filename"),
            "supplier": fields.get("supplier"),
            "date": fields.get("date"),
            "number": fields.get("number"),
            "htva": fields.get("htva"),
            "tva": fields.get("tva"),
            "ttc": fields.get("ttc"),
            "lines": fields.get("lines", []),
            "account_code": fields.get("account_code") or code_data.get("account_code"),
            "cited_rule": code_data.get("cited_rule"),
            "validation_errors": validation.get("errors", []),
            "duplicate_of": validation.get("duplicate_of"),
            "reviewed": bool(review_data),
            "skill_versions": list(dict.fromkeys(
                trace.get("skill_version", "") for trace in traces if trace.get("skill_version")
            )),
        })
    return {"docs": result}


@app.patch("/documents/{doc_id}/review")
def review_document(doc_id: str, req: DocumentReviewRequest):
    """Append a human correction event while retaining the original extraction."""
    db = get_db()
    traces = db.get_by_doc_id(doc_id)
    if not traces:
        raise HTTPException(status_code=404, detail="Document not found")

    allowed_fields = {
        "supplier", "date", "number", "lines", "htva", "tva", "ttc",
        "timbre_fiscal", "matricule_fiscal", "currency", "account_code",
    }
    unknown = set(req.fields) - allowed_fields
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unsupported fields: {', '.join(sorted(unknown))}")

    previous = db.get_extraction_fields(doc_id)
    current_code = db.get_latest_output(doc_id, "review").get("fields", {}).get("account_code")
    if current_code is None:
        current_code = db.get_latest_output(doc_id, "code").get("account_code")
    before = {**previous, "account_code": current_code}
    updated = {**before, **req.fields}
    changes = {
        key: {"from": before.get(key), "to": value}
        for key, value in req.fields.items()
        if before.get(key) != value
    }
    outputs = {step: db.get_latest_output(doc_id, step) for step in ("route", "extract", "code", "validate")}
    company_id = next((outputs[step].get("company_id") for step in outputs if outputs[step].get("company_id")), None)
    trace_id = db.write(
        doc_id,
        "review",
        "success",
        0,
        {"fields": updated, "changes": changes, "note": req.note.strip(), "company_id": company_id},
        [],
        "human-review",
    )
    return {"doc_id": doc_id, "reviewed": True, "changes": changes, "trace_id": trace_id}


@app.get("/export/csv")
def export_csv():
    """Export the live document ledger as Excel-compatible UTF-8 CSV."""
    import csv
    import json
    import io
    docs = docs_list(limit=10000)["docs"]
    columns = [
        "doc_id", "company_id", "filename", "doc_type", "modality", "decision",
        "reviewed", "supplier", "date", "number", "htva", "tva", "ttc", "invoice_lines_json",
        "timbre_fiscal", "matricule_fiscal", "currency", "account_code",
        "cited_rule", "validation_errors", "skill_versions", "first_seen",
        "last_seen", "total_ms",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for doc in docs:
        writer.writerow({
            **doc,
            "invoice_lines_json": json.dumps(doc.get("lines") or [], ensure_ascii=False),
            "validation_errors": "; ".join(doc.get("validation_errors") or []),
            "skill_versions": "; ".join(doc.get("skill_versions") or []),
        })

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        iter(["\ufeff" + output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=docdesk-ledger.csv"},
    )


@app.get("/trace/{doc_id}")
def trace(doc_id: str):
    db = get_db()
    rows = db.get_by_doc_id(doc_id)
    return {"doc_id": doc_id, "traces": rows}


@app.get("/health", response_model=HealthResponse)
def health():
    components: dict[str, str] = {}

    # SQLite check
    try:
        db = get_db()
        components["sqlite"] = "ok" if db.health_check() else "error"
    except Exception:
        components["sqlite"] = "error"

    # Qdrant check — just verify the directory exists (the embedded Qdrant
    # can't be opened by a second process while the app holds the lock)
    try:
        qpath = Path("./qdrant_local")
        if qpath.exists() and any(qpath.iterdir()):
            components["qdrant"] = "ok"
        else:
            components["qdrant"] = "empty"
    except Exception:
        components["qdrant"] = "error"

    # LLM check (env var presence only — no network call)
    import os
    if os.environ.get("AZURE_ENDPOINT") or os.environ.get("OPENAI_BASE_URL"):
        components["llm"] = "ok"
    else:
        components["llm"] = "unconfigured"

    status = "ok" if all(v == "ok" for v in components.values()) else "degraded"

    if status != "ok":
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"status": status, "components": components},
        )

    return HealthResponse(status=status, components=components)
