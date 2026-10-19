"use client"

import { useEffect, useMemo, useState } from "react"
import { Activity, ArrowDown, ArrowRight, Database, Download, FileCheck2, FileSearch, GitBranch, ShieldCheck, Sparkles } from "lucide-react"
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { fetchDocsList, API_URL, type DocSummary } from "@/lib/api"

const FLOW = [
  { title: "1 · Receive", detail: "PDF or photo enters from the upload screen.", icon: FileSearch },
  { title: "2 · Extract", detail: "LLM turns the document into supplier, date, lines and totals.", icon: FileCheck2 },
  { title: "3 · Code", detail: "RAG finds company rules; the Coder assigns an account code and cites its rule.", icon: Sparkles },
  { title: "4 · Check", detail: "Python checks arithmetic and required fields; exceptions go to review.", icon: ShieldCheck },
  { title: "5 · Store", detail: "Each stage, result, duration and skill version is appended to SQLite.", icon: Database },
]

function pretty(value?: string | null) {
  return value ? new Date(value).toLocaleString() : "—"
}

export function DashboardView({ onNavigate }: { onNavigate: (page: string) => void }) {
  const [docs, setDocs] = useState<DocSummary[]>([])
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const data = await fetchDocsList(500)
        if (active) { setDocs(data); setError(""); setLoading(false) }
      } catch (e) {
        if (active) { setError(e instanceof Error ? e.message : "Could not read the SQLite ledger"); setLoading(false) }
      }
    }
    void load()
    const timer = setInterval(load, 15000)
    return () => { active = false; clearInterval(timer) }
  }, [])

  const counts = useMemo(() => ({
    total: docs.length,
    accepted: docs.filter(d => d.decision === "ACCEPTED").length,
    review: docs.filter(d => d.decision === "ESCALATED" || d.decision === "FAILED" || !d.decision).length,
    corrected: docs.filter(d => d.reviewed).length,
  }), [docs])
  const chart = [
    { name: "Accepted", count: counts.accepted },
    { name: "Needs review", count: counts.review },
    { name: "Human corrected", count: counts.corrected },
  ]

  return (
    <main className="mx-auto max-w-[1500px] space-y-6 p-5 md:p-8">
      <section className="flex flex-col justify-between gap-4 border-b border-neutral-800 pb-6 md:flex-row md:items-end">
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-orange-400"><Activity size={15} /> Document workflow</div>
          <h1 className="text-3xl font-semibold tracking-tight text-white">DocDesk</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">Process Tunisian accounting documents, inspect what the agents produced, correct extracted data, and keep an audit trail you can export to Excel.</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => onNavigate("process")} className="rounded-md bg-orange-500 px-4 py-2 text-sm font-semibold text-white hover:bg-orange-400">Process a document</button>
          <a href={`${API_URL}/export/csv`} className="flex items-center gap-2 rounded-md border border-neutral-700 px-4 py-2 text-sm text-neutral-200 hover:bg-neutral-800"><Download size={15} /> Excel CSV</a>
        </div>
      </section>

      {error && <div className="rounded-md border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">Could not load stored documents: {error}. Check that FastAPI is running and the project’s SQLite database is reachable.</div>}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ["Stored documents", loading ? "…" : counts.total, "Distinct document IDs in traces.db"],
          ["Accepted", loading ? "…" : counts.accepted, "Pipeline completed without escalation"],
          ["Needs attention", loading ? "…" : counts.review, "Escalated, failed, or still in progress"],
          ["Human corrected", loading ? "…" : counts.corrected, "Reviewed changes are saved as new audit events"],
        ].map(([label, value, hint]) => <div key={String(label)} className="rounded-lg border border-neutral-800 bg-neutral-900/70 p-4">
          <div className="text-xs uppercase tracking-wider text-neutral-500">{label}</div>
          <div className="mt-2 text-3xl font-semibold tabular-nums text-white">{value}</div>
          <div className="mt-1 text-xs text-neutral-500">{hint}</div>
        </div>)}
      </section>

      <section className="grid gap-5 xl:grid-cols-[1.5fr_1fr]">
        <div className="rounded-lg border border-neutral-800 bg-neutral-900/50 p-5">
          <div className="mb-4">
            <h2 className="font-semibold text-white">How one document moves through DocDesk</h2>
            <p className="mt-1 text-xs text-neutral-500">n8n coordinates the steps; FastAPI runs the agents and checks; SQLite stores each output.</p>
          </div>
          <div className="grid gap-2 md:grid-cols-5">
            {FLOW.map((item, i) => {
              const Icon = item.icon
              return <div key={item.title} className="relative rounded-md border border-neutral-800 bg-neutral-950 p-3">
                <div className="mb-3 flex items-center gap-2 text-orange-400"><Icon size={17} /><span className="text-xs font-semibold text-neutral-200">{item.title}</span></div>
                <p className="text-xs leading-5 text-neutral-500">{item.detail}</p>
                {i < FLOW.length - 1 && <ArrowRight className="absolute -right-3 top-1/2 z-10 hidden text-neutral-600 md:block" size={16} />}
              </div>
            })}
          </div>
          <div className="mt-4 rounded-md border border-neutral-800 bg-neutral-950/70 p-3 text-xs leading-5 text-neutral-400">
            <span className="font-semibold text-neutral-200">What gets stored:</span> a timestamped event for each route, extraction, coding, validation, decision and human review. Open a row in the ledger to compare the stage outputs and see retrieved rule chunks.
          </div>
        </div>

        <div className="rounded-lg border border-neutral-800 bg-neutral-900/50 p-5">
          <h2 className="font-semibold text-white">Ledger at a glance</h2>
          <p className="mt-1 text-xs text-neutral-500">Counts are read live from the local SQLite database.</p>
          <div className="mt-4 h-52">
            {docs.length ? <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chart} margin={{ top: 8, right: 8, left: -24, bottom: 0 }}>
                <CartesianGrid stroke="#262626" vertical={false} />
                <XAxis dataKey="name" tick={{ fill: "#a3a3a3", fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis allowDecimals={false} tick={{ fill: "#737373", fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={{ background: "#171717", border: "1px solid #404040", borderRadius: 8, color: "white" }} />
                <Bar dataKey="count" fill="#f97316" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer> : <div className="flex h-full items-center justify-center rounded-md border border-dashed border-neutral-800 text-sm text-neutral-500">{loading ? "Loading ledger…" : "No processed documents yet"}</div>}
          </div>
          <button onClick={() => onNavigate("ledger")} className="mt-3 inline-flex items-center gap-2 text-sm text-orange-400 hover:text-orange-300">Open document ledger <ArrowDown className="-rotate-90" size={15} /></button>
        </div>
      </section>

      <section className="grid gap-5 xl:grid-cols-[1.5fr_1fr]">
        <div className="overflow-hidden rounded-lg border border-neutral-800 bg-neutral-900/50">
          <div className="flex items-center justify-between border-b border-neutral-800 px-5 py-4">
            <div><h2 className="font-semibold text-white">Recently processed</h2><p className="mt-1 text-xs text-neutral-500">The latest documents found in the ledger.</p></div>
            <button onClick={() => onNavigate("ledger")} className="text-xs text-orange-400 hover:text-orange-300">View all</button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-neutral-500"><tr>{["Document", "Supplier", "Decision", "Account code", "Updated"].map(x => <th key={x} className="px-4 py-3 font-medium">{x}</th>)}</tr></thead>
              <tbody>{docs.slice(0, 6).map(d => <tr key={d.doc_id} className="border-t border-neutral-800/70">
                <td className="px-4 py-3 font-mono text-orange-300">{d.doc_id}</td><td className="px-4 py-3 text-neutral-300">{d.supplier || "—"}</td><td className="px-4 py-3 text-neutral-300">{d.decision || "IN PROGRESS"}</td><td className="px-4 py-3 font-mono text-neutral-300">{d.account_code || "—"}</td><td className="whitespace-nowrap px-4 py-3 text-neutral-500">{pretty(d.last_seen)}</td>
              </tr>)}</tbody>
            </table>
            {!docs.length && !loading && <div className="p-6 text-center text-sm text-neutral-500">Upload a demo PDF or photo to create the first stored record.</div>}
          </div>
        </div>

        <div className="rounded-lg border border-neutral-800 bg-neutral-900/50 p-5">
          <div className="flex items-center gap-2 text-orange-300"><GitBranch size={17} /><h2 className="font-semibold text-neutral-100">Company skill improvement</h2></div>
          <p className="mt-3 text-sm leading-6 text-neutral-400">The installed SkillOpt library learns from document failures and proposes small, reviewable skill edits. Every candidate is checked against held-out documents before DocDesk promotes it.</p>
          <div className="mt-4 rounded-xl border border-neutral-700 bg-neutral-950/40 p-3 text-xs leading-5 text-neutral-400">The current pilot uses real Company B invoices. Open Skill history to inspect each version, validation score, optimizer step and promotion decision.</div>
          <button onClick={() => onNavigate("skillopt")} className="mt-3 text-xs text-orange-300 hover:text-orange-200">Open skill history →</button>
        </div>
      </section>
    </main>
  )
}
