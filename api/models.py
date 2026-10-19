"""api/models.py — Pydantic request/response models for the pipeline API."""

from typing import Optional
from pydantic import BaseModel


# ── Request bodies ─────────────────────────────────────────────────────────

class RouteRequest(BaseModel):
    doc_id: str
    company_id: str
    file_b64: Optional[str] = None      # base64-encoded file bytes
    filename: Optional[str] = None
    text: Optional[str] = None          # pre-extracted text (if available)


class ExtractRequest(BaseModel):
    doc_id: str
    company_id: str
    text: str                            # extracted text or vision transcript
    doc_type: str = "invoice"


class CodeRequest(BaseModel):
    doc_id: str
    company_id: str
    extracted: dict
    doc_type: str = "invoice"
    rag_enabled: bool = True


class ValidateRequest(BaseModel):
    doc_id: str
    company_id: str
    extracted: dict


class HandleRequest(BaseModel):
    doc_id: str
    company_id: str
    extracted: dict
    validation: dict


class AcceptRequest(BaseModel):
    doc_id: str
    company_id: str
    result: Optional[dict] = None


class EscalateRequest(BaseModel):
    doc_id: str
    company_id: str
    dossier: Optional[dict] = None


class FailRequest(BaseModel):
    doc_id: str
    company_id: str
    error: str


class DocumentReviewRequest(BaseModel):
    fields: dict
    note: str = ""


# ── Response bodies ────────────────────────────────────────────────────────

class RouteResponse(BaseModel):
    doc_id: str
    company_id: str
    doc_type: str
    modality: str
    source_text: str = ""
    skill_version: str
    trace_id: int


class ExtractResponse(BaseModel):
    doc_id: str
    supplier: Optional[str] = None
    date: Optional[str] = None
    number: Optional[str] = None
    lines: list = []
    htva: Optional[float] = None
    tva: Optional[float] = None
    ttc: Optional[float] = None
    timbre_fiscal: Optional[float] = None
    matricule_fiscal: Optional[str] = None
    currency: Optional[str] = "TND"
    skill_version: str
    trace_id: int


class CodeResponse(BaseModel):
    doc_id: str
    account_code: str
    cited_rule: str
    chunks: list = []
    skill_version: str
    trace_id: int


class ValidateResponse(BaseModel):
    doc_id: str
    valid: bool
    errors: list[str] = []
    explanation: str
    needs_review: bool
    duplicate_of: Optional[str] = None
    skill_version: str
    trace_id: int


class HandleResponse(BaseModel):
    doc_id: str
    escalation_dossier: dict
    skill_version: str
    trace_id: int


class HealthResponse(BaseModel):
    status: str                          # "ok" or "degraded"
    components: dict[str, str]           # {"qdrant": "ok", "sqlite": "ok", "llm": "ok"}


# ── Internal ───────────────────────────────────────────────────────────────

class TraceEvent(BaseModel):
    id: Optional[int] = None
    doc_id: str
    step: str
    status: str
    duration_ms: int
    output_json: str = "{}"
    chunks_json: str = "[]"
    skill_version: str = ""
    timestamp: str = ""


class GoldDocument(BaseModel):
    doc_id: str
    doc_type: str
    fields: dict
    account_code: str
    injected_errors: list[str] = []
    company_id: str
    split: str = "train"
