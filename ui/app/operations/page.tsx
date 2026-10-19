"use client"

import { useState, useEffect } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { fetchTraces, fetchDocsList, saveDocumentReview, parseOutput, parseChunks, API_URL, type TraceEvent, type DocSummary } from "@/lib/api"

function DecisionBadge({ decision }: { decision: string | null }) {
  if (!decision) return <span className="text-neutral-500 text-xs">IN PROGRESS</span>
  const colors: Record<string, string> = {
    ACCEPTED: "bg-orange-500/20 text-orange-400 border-orange-500/30",
    ESCALATED: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
    FAILED: "bg-red-500/20 text-red-400 border-red-500/30",
  }
  return (
    <span className={`text-xs font-mono font-bold px-1.5 py-0.5 rounded border ${colors[decision] ?? "text-neutral-400"}`}>
      {decision}
    </span>
  )
}

const EDITABLE_FIELDS = ["supplier", "date", "number", "htva", "tva", "ttc", "timbre_fiscal", "matricule_fiscal", "currency", "account_code"]

function TraceDrawer({ docId, onClose, onSaved }: { docId: string; onClose: () => void; onSaved: () => void }) {
  const [traces, setTraces] = useState<TraceEvent[]>([])
  const [fields, setFields] = useState<Record<string, string>>({})
  const [note, setNote] = useState("")
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState("")
  const [saved, setSaved] = useState(false)
  useEffect(() => {
    fetchTraces(docId).then(items => {
      setTraces(items)
      const extracted = items.find(t => t.step === "extract")
      const reviewed = [...items].reverse().find(t => t.step === "review")
      const coded = [...items].reverse().find(t => t.step === "code")
      const out = extracted ? parseOutput(extracted) : {}
      const reviewOut = reviewed ? parseOutput(reviewed) : {}
      const reviewFields = (reviewOut.fields ?? {}) as Record<string, unknown>
      const merged: Record<string, unknown> = { ...out, ...(coded ? { account_code: parseOutput(coded).account_code } : {}), ...reviewFields }
      setFields(Object.fromEntries(EDITABLE_FIELDS.map(k => [
        k,
        merged[k] == null ? "" : k === "lines" ? JSON.stringify(merged[k], null, 2) : String(merged[k]),
      ])))
    })
  }, [docId])

  const handleSave = async () => {
    setSaving(true); setSaveError(""); setSaved(false)
    try {
      const submitted = { ...fields, lines: fields.lines ? JSON.parse(fields.lines) : [] }
      await saveDocumentReview(docId, submitted, note)
      const updated = await fetchTraces(docId)
      setTraces(updated)
      setSaved(true)
      onSaved()
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "Could not save review")
    } finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/60" onClick={onClose} />
      <div className="w-full max-w-[620px] bg-neutral-900 border-l border-neutral-700 overflow-y-auto p-5 md:p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold text-white font-mono">{docId}</h2>
          <button onClick={onClose} className="text-neutral-500 hover:text-white text-lg">✕</button>
        </div>

        <section className="rounded-lg border border-neutral-700 bg-neutral-950 p-4">
          <h3 className="text-sm font-semibold text-white">Review extracted data</h3>
          <p className="mt-1 text-xs leading-5 text-neutral-500">Edit a value and save it as a new human-review event. The original LLM output stays in the audit history; CSV export uses the latest reviewed values.</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {EDITABLE_FIELDS.filter(key => key !== "lines").map(key => <label key={key} className="space-y-1 text-xs text-neutral-400">
              <span className="capitalize">{key.replaceAll("_", " ")}</span>
              <input value={fields[key] ?? ""} onChange={e => setFields(v => ({ ...v, [key]: e.target.value }))}
                className="w-full rounded border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-white focus:border-orange-500 focus:outline-none" />
            </label>)}
          </div>
          <label className="mt-3 block space-y-1 text-xs text-neutral-400">Invoice lines (JSON)
            <textarea value={fields.lines ?? "[]"} onChange={e => setFields(v => ({ ...v, lines: e.target.value }))} rows={5}
              className="w-full rounded border border-neutral-700 bg-neutral-900 px-3 py-2 font-mono text-xs text-white focus:border-orange-500 focus:outline-none" />
          </label>
          <label className="mt-3 block space-y-1 text-xs text-neutral-400">Reviewer note
            <textarea value={note} onChange={e => setNote(e.target.value)} rows={2} placeholder="Why was this value changed?"
              className="w-full rounded border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-white placeholder:text-neutral-600 focus:border-orange-500 focus:outline-none" />
          </label>
          <div className="mt-3 flex items-center gap-3">
            <button onClick={handleSave} disabled={saving} className="rounded bg-orange-500 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">{saving ? "Saving…" : "Save review"}</button>
            {saved && <span className="text-xs text-emerald-400">Saved to SQLite audit history</span>}
          </div>
          {saveError && <div className="mt-2 text-xs text-red-300">{saveError}</div>}
        </section>

        {traces.length === 0 && (
          <div className="text-neutral-500 text-xs font-mono">Loading traces…</div>
        )}

        {traces.map(t => {
          const out = parseOutput(t)
          const chunks = parseChunks(t)
          return (
            <div key={t.id} className={`border-l-2 pl-4 py-2 space-y-1 ${t.status === "error" ? "border-red-500" : "border-orange-500"}`}>
              <div className="flex gap-3 text-xs font-mono">
                <span className="text-orange-500 w-20 uppercase">{t.step}</span>
                <span className={t.status === "error" ? "text-red-400" : "text-green-400"}>{t.status}</span>
                <span className="text-neutral-400">{t.duration_ms}ms</span>
                <span className="text-neutral-600">[{t.skill_version}]</span>
              </div>

              {/* Extraction fields */}
              {t.step === "extract" && (
                <div className="mt-2 bg-neutral-800 rounded p-3 text-xs space-y-1">
                  <div className="text-neutral-400 font-mono grid grid-cols-2 gap-x-4 gap-y-1">
                    {["supplier","date","number","htva","tva","ttc","timbre_fiscal","matricule_fiscal","currency"].map(k => (
                      out[k] != null ? (
                        <div key={k} className="flex gap-2">
                          <span className="text-neutral-600 w-28 flex-shrink-0">{k}</span>
                          <span className="text-white font-mono truncate">{String(out[k])}</span>
                        </div>
                      ) : null
                    ))}
                  </div>
                  {(out.lines as unknown[])?.length > 0 && (
                    <div className="mt-2">
                      <div className="text-neutral-600 text-xs mb-1">Lines:</div>
                      <table className="w-full text-xs text-neutral-300">
                        <thead><tr className="text-neutral-600"><th className="text-left">Description</th><th className="text-right">HTVA</th><th className="text-right">TVA</th><th className="text-right">TTC</th></tr></thead>
                        <tbody>
                          {(out.lines as Array<Record<string,unknown>>).slice(0,5).map((l,i) => (
                            <tr key={i}>
                              <td className="truncate max-w-[140px]">{String(l.description ?? "")}</td>
                              <td className="text-right font-mono">{String(l.htva ?? "")}</td>
                              <td className="text-right font-mono">{String(l.tva ?? "")}</td>
                              <td className="text-right font-mono">{String(l.ttc ?? "")}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  {typeof out.source_text === "string" && out.source_text && <details className="mt-3">
                    <summary className="cursor-pointer text-neutral-400">Text sent to the Extractor</summary>
                    <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded bg-neutral-950 p-2 text-[11px] leading-5 text-neutral-300">{out.source_text}</pre>
                  </details>}
                </div>
              )}

              {/* Coding result */}
              {t.step === "code" && (
                <div className="mt-1 text-xs bg-neutral-800 rounded p-2 space-y-1">
                  <div><span className="text-neutral-500">account_code: </span><span className="text-white font-mono font-bold">{String(out.account_code ?? "—")}</span></div>
                  <div><span className="text-neutral-500">cited_rule: </span><span className="text-neutral-300">{String(out.cited_rule ?? "—").slice(0,80)}</span></div>
                  {chunks.length > 0 && (
                    <div className="text-neutral-600">{chunks.length} RAG chunks · top score {(chunks[0]?.score * 100).toFixed(1)}%</div>
                  )}
                </div>
              )}

              {/* Validation */}
              {t.step === "validate" && (
                <div className="mt-1 text-xs">
                  {Array.isArray(out.errors) && out.errors.length > 0 ? (
                    <div className="text-red-400">{(out.errors as string[]).join(", ")}</div>
                  ) : (
                    <div className="text-green-400">No errors</div>
                  )}
                  {typeof out.duplicate_of === "string" && out.duplicate_of && (
                    <div className="mt-1 rounded border border-amber-800 bg-amber-950/30 px-2 py-1 text-amber-300">
                      Possible duplicate of document {out.duplicate_of}
                    </div>
                  )}
                  {out.explanation != null && <div className="text-neutral-400 mt-1 italic">{String(out.explanation).slice(0,120)}</div>}
                </div>
              )}

              {t.step === "review" && (
                <div className="rounded bg-neutral-800 p-2 text-xs">
                  <div className="font-semibold text-emerald-300">Human review saved</div>
                  <div className="mt-1 text-neutral-400">{String(out.note || "No reviewer note")}</div>
                  <pre className="mt-2 overflow-auto whitespace-pre-wrap text-[11px] text-neutral-400">{JSON.stringify(out.changes ?? {}, null, 2)}</pre>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function OperationsPage() {
  const [docs, setDocs] = useState<DocSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null)
  const [filter, setFilter] = useState("")
  const [decisionFilter, setDecisionFilter] = useState<string>("ALL")
  const [companyFilter, setCompanyFilter] = useState<string>("ALL")
  const [showDiagnostic, setShowDiagnostic] = useState(false)
  const [loadError, setLoadError] = useState("")
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    const load = () => fetchDocsList(200)
      .then(d => { setDocs(d); setLoadError("") })
      .catch(e => setLoadError(e instanceof Error ? e.message : "Could not load SQLite ledger"))
      .finally(() => setLoading(false))
    load()
    const interval = setInterval(load, 15000)
    return () => clearInterval(interval)
  }, [refreshKey])

  const visibleDocs = docs.filter(d => {
    const idLooksDiagnostic = /^(?:debug(?:[-_]|$)|test(?:[-_]|$)|e2e(?:[-_]|$)|tol\d|demo(?:[-_]|$)|=+$)/i.test(d.doc_id)
    const diagnostic = d.is_diagnostic ?? idLooksDiagnostic
    const complete = d.is_complete ?? Boolean(d.decision)
    return showDiagnostic || (!diagnostic && complete)
  })
  const filtered = visibleDocs.filter(d => {
    const matchText = !filter || [d.doc_id, d.supplier, d.number, d.account_code, d.company_id, d.filename].some(
      v => v?.toLowerCase().includes(filter.toLowerCase())
    )
    const matchDecision = decisionFilter === "ALL" || d.decision === decisionFilter
    const matchCompany = companyFilter === "ALL" || d.company_id === companyFilter
    return matchText && matchDecision && matchCompany
  })

  const stats = {
    total: visibleDocs.length,
    accepted: visibleDocs.filter(d => d.decision === "ACCEPTED").length,
    escalated: visibleDocs.filter(d => d.decision === "ESCALATED").length,
    failed: visibleDocs.filter(d => d.decision === "FAILED").length,
    reviewed: visibleDocs.filter(d => d.reviewed).length,
  }

  return (
    <div className="p-6 space-y-6">
      {selectedDoc && <TraceDrawer docId={selectedDoc} onClose={() => setSelectedDoc(null)} onSaved={() => setRefreshKey(k => k + 1)} />}

      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-wider">DOCUMENT LEDGER</h1>
          <p className="text-sm text-neutral-400">Stored agent outputs, validation decisions, and human corrections. Open a row to inspect or edit it.</p>
        </div>
        <a href={`${API_URL}/export/csv`} download="docdesk-ledger.csv"
          className="text-xs font-mono bg-neutral-800 hover:bg-neutral-700 border border-neutral-600 text-white px-3 py-2 rounded">
          ⬇ Download for Excel (CSV)
        </a>
      </div>

      {loadError && <div className="rounded border border-red-900 bg-red-950/30 p-3 text-sm text-red-300">Could not load the ledger: {loadError}. The UI needs the FastAPI service and its SQLite database.</div>}

      {/* KPI bar */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {[
          { label: "TOTAL", value: stats.total, color: "text-white" },
          { label: "ACCEPTED", value: stats.accepted, color: "text-orange-400" },
          { label: "ESCALATED", value: stats.escalated, color: "text-yellow-400" },
          { label: "FAILED", value: stats.failed, color: "text-red-400" },
          { label: "HUMAN REVIEWED", value: stats.reviewed, color: "text-emerald-400" },
        ].map(k => (
          <Card key={k.label} className="bg-neutral-900 border-neutral-700">
            <CardContent className="p-4">
              <div className="text-xs text-neutral-500 tracking-wider">{k.label}</div>
              <div className={`text-3xl font-bold font-mono mt-1 ${k.color}`}>{k.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-col gap-3 md:flex-row">
        <input value={filter} onChange={e => setFilter(e.target.value)}
          placeholder="Search doc_id, supplier, number, code…"
          className="flex-1 bg-neutral-800 border border-neutral-600 text-white text-sm px-3 py-2 rounded placeholder-neutral-500 font-mono" />
        <select value={decisionFilter} onChange={e => setDecisionFilter(e.target.value)}
          className="bg-neutral-800 border border-neutral-600 text-white text-sm px-3 py-2 rounded">
          <option value="ALL">All decisions</option>
          <option value="ACCEPTED">ACCEPTED</option>
          <option value="ESCALATED">ESCALATED</option>
          <option value="FAILED">FAILED</option>
        </select>
        <select value={companyFilter} onChange={e => setCompanyFilter(e.target.value)}
          className="bg-neutral-800 border border-neutral-600 text-white text-sm px-3 py-2 rounded">
          <option value="ALL">All companies</option>
          <option value="company_a">Company A</option>
          <option value="company_b">Company B</option>
        </select>
        <label className="inline-flex shrink-0 cursor-pointer items-center gap-2 rounded border border-neutral-600 bg-neutral-800 px-3 py-2 text-xs text-neutral-300">
          <input type="checkbox" checked={showDiagnostic} onChange={e => setShowDiagnostic(e.target.checked)} className="accent-orange-500" />
          Show test &amp; unfinished runs
        </label>
      </div>

      {/* Data table */}
      <Card className="bg-neutral-900 border-neutral-700">
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b border-neutral-800 text-neutral-500">
                  {["Doc ID","Company","Type","Decision","Supplier","Date","Number","HTVA","TVA","TTC","Account Code","Review","Time (ms)","Last activity"].map(h => (
                    <th key={h} className="text-left px-3 py-3 tracking-wider whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={14} className="text-center py-8 text-neutral-500">Loading stored documents…</td></tr>
                )}
                {!loading && filtered.length === 0 && (
                  <tr><td colSpan={14} className="text-center py-8 text-neutral-600">
                    {docs.length === 0 ? "No stored documents found. Process a document to create an audit record." : "No completed documents match these filters. Enable test & unfinished runs to inspect diagnostic history."}
                  </td></tr>
                )}
                {filtered.map(doc => (
                  <tr key={doc.doc_id}
                    onClick={() => setSelectedDoc(doc.doc_id)}
                    className="border-b border-neutral-800/50 hover:bg-neutral-800 cursor-pointer transition-colors">
                    <td className="px-3 py-2 text-orange-400">{doc.doc_id}</td>
                    <td className="px-3 py-2 text-neutral-500">{doc.company_id?.replace("company_", "Company ") ?? "—"}</td>
                    <td className="px-3 py-2 text-neutral-500">{doc.doc_type ?? "—"}</td>
                    <td className="px-3 py-2"><DecisionBadge decision={doc.decision} /></td>
                    <td className="px-3 py-2 text-neutral-300 max-w-[120px] truncate">{doc.supplier ?? "—"}</td>
                    <td className="px-3 py-2 text-neutral-400">{doc.date ?? "—"}</td>
                    <td className="px-3 py-2 text-neutral-400">{doc.number ?? "—"}</td>
                    <td className="px-3 py-2 text-right text-neutral-300">{doc.htva != null ? Number(doc.htva).toFixed(3) : "—"}</td>
                    <td className="px-3 py-2 text-right text-neutral-300">{doc.tva != null ? Number(doc.tva).toFixed(3) : "—"}</td>
                    <td className="px-3 py-2 text-right text-white font-bold">{doc.ttc != null ? Number(doc.ttc).toFixed(3) : "—"}</td>
                    <td className="px-3 py-2 text-center">
                      {doc.account_code ? (
                        <span className="bg-orange-500/20 text-orange-400 border border-orange-500/30 px-1.5 py-0.5 rounded">
                          {doc.account_code}
                        </span>
                      ) : "—"}
                    </td>
                    <td className="px-3 py-2">{doc.reviewed ? <span className="text-emerald-400">REVIEWED</span> : <span className="text-neutral-600">—</span>}</td>
                    <td className="px-3 py-2 text-neutral-500 text-right">{doc.total_ms?.toLocaleString()}</td>
                    <td className="px-3 py-2 text-neutral-600">{new Date(doc.last_seen).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <div className="text-xs text-neutral-600 text-right">
        Showing {filtered.length} of {visibleDocs.length} {showDiagnostic ? "visible records" : "completed documents"}{!showDiagnostic && docs.length > visibleDocs.length ? ` · ${docs.length - visibleDocs.length} diagnostic or unfinished runs hidden` : ""} · refreshes every 15s · click a row to inspect stages and save corrections
      </div>
    </div>
  )
}
