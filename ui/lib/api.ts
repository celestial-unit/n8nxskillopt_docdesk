// lib/api.ts — Typed API client for FastAPI backend and n8n webhook

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const N8N_WEBHOOK = process.env.NEXT_PUBLIC_N8N_WEBHOOK_URL ?? "http://localhost:5678/webhook/pipeline";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface TraceEvent {
  id: number;
  doc_id: string;
  step: string;
  status: string;
  duration_ms: number;
  output_json: string;
  chunks_json: string;
  skill_version: string;
  timestamp: string;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  components: Record<string, string>;
}

export interface PipelineResponse {
  decision?: string;
  doc_id?: string;
  trace_id?: number;
}

// ── API calls ─────────────────────────────────────────────────────────────────

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    return { status: "degraded", components: body.components ?? {} };
  }
  return res.json();
}

export async function fetchTraces(docId: string): Promise<TraceEvent[]> {
  const res = await fetch(`${API_URL}/trace/${encodeURIComponent(docId)}`, {
    cache: "no-store",
  });
  if (!res.ok) return [];
  const data = await res.json();
  return data.traces ?? [];
}

export async function submitToWebhook(payload: {
  doc_id: string;
  company_id: string;
  file_b64?: string;
  filename?: string;
  text?: string;
}): Promise<PipelineResponse> {
  const res = await fetch(N8N_WEBHOOK, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`Webhook error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail ?? `${path} failed (${res.status})`);
  return data as T;
}

/** Run the same agent sequence directly when the local n8n service is unavailable. */
export async function processDocumentViaApi(payload: {
  doc_id: string;
  company_id: string;
  file_b64: string;
  filename: string;
}) {
  try {
    const route = await postJson<{ doc_id: string; company_id: string; doc_type: string; modality: string; source_text: string }>("/route", payload);
    const extracted = await postJson<Record<string, unknown>>("/extract", {
      doc_id: payload.doc_id, company_id: payload.company_id,
      text: route.source_text, doc_type: route.doc_type,
    });
    const code = await postJson<Record<string, unknown>>("/code", {
      doc_id: payload.doc_id, company_id: payload.company_id,
      extracted, doc_type: route.doc_type, rag_enabled: true,
    });
    const validation = await postJson<{ needs_review: boolean; errors: string[]; explanation: string }>("/validate", {
      doc_id: payload.doc_id, company_id: payload.company_id, extracted,
    });

    if (validation.needs_review) {
      const handler = await postJson<{ escalation_dossier?: Record<string, unknown> }>("/handle", {
        doc_id: payload.doc_id, company_id: payload.company_id,
        extracted, validation,
      });
      await postJson("/escalate", {
        doc_id: payload.doc_id, company_id: payload.company_id,
        dossier: handler.escalation_dossier ?? {},
      });
    } else {
      await postJson("/accept", {
        doc_id: payload.doc_id, company_id: payload.company_id,
        result: { extracted, account_code: code.account_code, cited_rule: code.cited_rule },
      });
    }
    return { doc_id: payload.doc_id, decision: validation.needs_review ? "ESCALATED" : "ACCEPTED" };
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown pipeline error";
    await postJson("/fail", { doc_id: payload.doc_id, company_id: payload.company_id, error: message }).catch(() => undefined);
    throw error;
  }
}

export async function fetchAllTraces(): Promise<Record<string, TraceEvent[]>> {
  // Returns a map of doc_id → traces by fetching from SQLite via a simple endpoint
  // This is a best-effort approach since we don't have a /traces list endpoint
  return {};
}

// List all processed documents with their extracted fields and decisions
export interface DocSummary {
  doc_id: string;
  first_seen: string;
  last_seen: string;
  total_ms: number;
  decision: string | null;
  supplier: string | null;
  date: string | null;
  number: string | null;
  htva: number | null;
  tva: number | null;
  ttc: number | null;
  account_code: string | null;
  company_id: string | null;
  filename: string | null;
  doc_type: string | null;
  modality: string | null;
  cited_rule: string | null;
  validation_errors: string[];
  duplicate_of?: string | null;
  reviewed: boolean;
  skill_versions: string[];
  is_diagnostic?: boolean;
  is_complete?: boolean;
  trace_count?: number;
}

export async function fetchDocsList(limit: number = 100): Promise<DocSummary[]> {
  const res = await fetch(`${API_URL}/docs-list?limit=${limit}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Document ledger unavailable (${res.status})`);
  const data = await res.json();
  return data.docs ?? [];
}

export async function saveDocumentReview(docId: string, fields: Record<string, unknown>, note: string) {
  const res = await fetch(`${API_URL}/documents/${encodeURIComponent(docId)}/review`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fields, note }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `Could not save review (${res.status})`);
  }
  return res.json();
}

// Fetch evaluation results from the eval results markdown files
export interface RetrievalEval {
  recallA: number | null;
  mrrA: number | null;
  recallB: number | null;
  mrrB: number | null;
  nQueriesA?: number | null;
  nQueriesB?: number | null;
  nChunksA?: number | null;
  nChunksB?: number | null;
}

export async function fetchRetrievalEval(): Promise<RetrievalEval> {
  try {
    const res = await fetch(`${API_URL}/eval/retrieval`, { cache: "no-store" });
    if (!res.ok) return { recallA: null, mrrA: null, recallB: null, mrrB: null };
    return await res.json();
  } catch {
    return { recallA: null, mrrA: null, recallB: null, mrrB: null };
  }
}

export interface BaselineEval {
  companyA: { extractor: number; coderRag: number; coderNoRag: number; validator: number };
  companyB: { extractor: number; coderRag: number; coderNoRag: number; validator: number };
}

export async function fetchBaselineEval(): Promise<BaselineEval | null> {
  try {
    const res = await fetch(`${API_URL}/eval/baseline`, { cache: "no-store" });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export interface CoderImprovementEval {
  summary?: {
    baseline_v001?: { code_accuracy?: number; supported_coder_score?: number };
    improved_v004?: { code_accuracy?: number; supported_coder_score?: number };
    paired_n?: number;
    paired_delta_pp?: number;
    wins?: number;
    losses?: number;
    ties?: number;
  };
}

export async function fetchCoderImprovement(): Promise<CoderImprovementEval | null> {
  try {
    const res = await fetch(`${API_URL}/eval/coder-improvement`, { cache: "no-store" });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export interface SkillOptSummary {
  baseline_hard: number;
  best_hard: number;
  total_steps: number;
  total_wall_time_s: number;
}

export async function fetchSkillOptSummary(): Promise<SkillOptSummary | null> {
  try {
    const res = await fetch(`${API_URL}/skillopt/summary`, { cache: "no-store" });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// Decode trace output_json safely
export function parseOutput(trace: TraceEvent): Record<string, unknown> {
  try {
    return JSON.parse(trace.output_json);
  } catch {
    return {};
  }
}

// Decode chunks_json safely
export function parseChunks(trace: TraceEvent): Array<{ text: string; score: number; source: string }> {
  try {
    return JSON.parse(trace.chunks_json) ?? [];
  } catch {
    return [];
  }
}

export { API_URL, N8N_WEBHOOK };
