"use client"

import { useState, useEffect, useRef } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { fetchTraces, submitToWebhook, processDocumentViaApi, parseOutput, type TraceEvent } from "@/lib/api"

const STAGES = ["route", "extract", "code", "validate", "accept"] as const
const STAGE_LABELS: Record<string, string> = {
  route: "🔀 ROUTER", extract: "📋 EXTRACTOR", code: "🏷️ CODER",
  validate: "✅ VALIDATOR", accept: "DECISION", escalate: "DECISION", fail: "FAILED",
}

function StageCard({ stage, trace }: { stage: string; trace?: TraceEvent }) {
  const status = trace ? (trace.status === "success" ? "done" : "error") : "pending"
  const borderColor = status === "done" ? "border-orange-500" : status === "error" ? "border-red-500" : "border-neutral-700"
  const textColor = status === "done" ? "text-orange-500" : status === "error" ? "text-red-500" : "text-neutral-500"
  const output = trace ? parseOutput(trace) : {}
  return (
    <Card className={`bg-neutral-900 ${borderColor} border`}>
      <CardContent className="p-4">
        <div className={`text-xs font-bold tracking-wider ${textColor}`}>{STAGE_LABELS[stage] ?? stage.toUpperCase()}</div>
        {trace ? (
          <div className="mt-2 space-y-1">
            <div className="text-xs text-neutral-400 font-mono">{trace.duration_ms}ms · {trace.skill_version}</div>
            {!!output.doc_type && <div className="text-xs text-neutral-300">type: {String(output.doc_type)}</div>}
            {!!output.account_code && <div className="text-xs text-neutral-300">code: {String(output.account_code)}</div>}
            {(output.errors as string[] | undefined)?.length ? (
              <div className="text-xs text-red-400">{(output.errors as string[]).join(", ")}</div>
            ) : null}
          </div>
        ) : (
          <div className="mt-2 text-xs text-neutral-600">⏳ pending</div>
        )}
      </CardContent>
    </Card>
  )
}

export default function CommandCenterPage() {
  const [file, setFile] = useState<File | null>(null)
  const [companyId, setCompanyId] = useState("company_a")
  const [docId, setDocId] = useState<string | null>(null)
  const [traces, setTraces] = useState<TraceEvent[]>([])
  const [running, setRunning] = useState(false)
  const [decision, setDecision] = useState<string | null>(null)
  const [runMode, setRunMode] = useState<string>("")
  const [runError, setRunError] = useState<string>("")
  const pollRef = useRef<NodeJS.Timeout | null>(null)

  const stageMap = Object.fromEntries(traces.map(t => [t.step, t]))

  useEffect(() => {
    if (!docId || !running) return
    pollRef.current = setInterval(async () => {
      const ts = await fetchTraces(docId)
      setTraces(ts)
      const final = ts.find(t => ["accept","escalate","fail"].includes(t.step))
      if (final) {
        setDecision(final.step === "accept" ? "ACCEPTED" : final.step === "escalate" ? "ESCALATED" : "FAILED")
        setRunning(false)
        if (pollRef.current) clearInterval(pollRef.current)
      }
    }, 500)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [docId, running])

  const handleRun = async () => {
    if (!file) return
    const id = `ui-${Date.now()}`
    setDocId(id); setTraces([]); setDecision(null); setRunning(true); setRunError(""); setRunMode("")
    const b64 = await new Promise<string>((res) => {
      const r = new FileReader()
      r.onload = () => res((r.result as string).split(",")[1])
      r.readAsDataURL(file)
    })
    const payload = { doc_id: id, company_id: companyId, file_b64: b64, filename: file.name }
    try {
      await submitToWebhook(payload)
      setRunMode("Orchestrated by n8n")
    } catch {
      try {
        await processDocumentViaApi(payload)
        setRunMode("n8n unavailable · processed directly by FastAPI")
      } catch (error) {
        setRunError(error instanceof Error ? error.message : "Document processing failed")
        setRunning(false)
        setTraces(await fetchTraces(id))
      }
    }
  }

  const accepted = decision === "ACCEPTED"
  const escalated = decision === "ESCALATED"

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-wider">COMMAND CENTER</h1>
          <p className="text-sm text-neutral-400">Document pipeline control & monitoring</p>
        </div>
        <select value={companyId} onChange={e => setCompanyId(e.target.value)}
          className="bg-neutral-800 border border-neutral-600 text-white text-sm px-3 py-2 rounded">
          <option value="company_a">Company A (Alpha SARL)</option>
          <option value="company_b">Company B (Beta International)</option>
        </select>
      </div>

      <Card className="bg-neutral-900 border-neutral-700">
        <CardContent className="p-6 space-y-4">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
            <div className="flex-1">
              <label className="text-xs text-neutral-400 tracking-wider block mb-2">UPLOAD DOCUMENT</label>
              <input type="file" accept=".pdf,.jpg,.jpeg,.png"
                onChange={e => setFile(e.target.files?.[0] ?? null)}
                className="w-full bg-neutral-800 border border-neutral-600 text-white text-sm px-3 py-2 rounded file:mr-4 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-orange-500 file:text-white" />
            </div>
            <Button onClick={handleRun} disabled={!file || running}
              className="bg-orange-500 hover:bg-orange-600 text-white font-mono tracking-wider">
              {running ? "▶ RUNNING..." : "▶ RUN"}
            </Button>
          </div>
          {file && <p className="text-xs text-neutral-500 font-mono">Selected: {file.name}</p>}
          <p className="text-xs leading-5 text-neutral-500">The upload is routed through n8n when available. If n8n is stopped, the screen runs the same FastAPI stages directly. Each completed stage is written to the local SQLite audit ledger.</p>
        </CardContent>
      </Card>

      {runMode && <div className="text-xs text-emerald-400">{runMode}</div>}
      {runError && <div className="rounded border border-red-900 bg-red-950/30 p-3 text-sm text-red-300">Processing stopped: {runError}. Open System Health for service status.</div>}

      {(running || traces.length > 0) && (
        <>
          <div>
            <h2 className="text-xs font-medium text-neutral-400 tracking-wider mb-3">PIPELINE PROGRESS</h2>
            <div className="grid grid-cols-5 gap-3">
              {STAGES.map(s => <StageCard key={s} stage={s} trace={stageMap[s]} />)}
            </div>
          </div>

          {decision && (
            <div className={`text-center py-6 rounded border ${accepted ? "border-orange-500 bg-orange-500/10" : escalated ? "border-yellow-500 bg-yellow-500/10" : "border-red-500 bg-red-500/10"}`}>
              <div className={`text-3xl font-bold font-mono tracking-widest ${accepted ? "text-orange-500" : escalated ? "text-yellow-400" : "text-red-500"}`}>
                {decision}
              </div>
              {escalated && <div className="text-xs text-neutral-400 mt-1">Document requires human review</div>}
            </div>
          )}

          {docId && (
            <Card className="bg-neutral-900 border-neutral-700">
              <CardHeader className="pb-2">
                <CardTitle className="text-xs text-neutral-400 tracking-wider">TRACE — {docId}</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-1 max-h-48 overflow-y-auto font-mono text-xs">
                  {traces.map(t => (
                    <div key={t.id} className={`flex gap-3 ${t.status === "error" ? "text-red-400" : "text-neutral-300"}`}>
                      <span className="text-neutral-600">{new Date(t.timestamp).toLocaleTimeString()}</span>
                      <span className="text-orange-500 w-16">{t.step}</span>
                      <span className="text-neutral-400 w-8">{t.status}</span>
                      <span>{t.duration_ms}ms</span>
                      {t.skill_version && <span className="text-neutral-600">[{t.skill_version}]</span>}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
