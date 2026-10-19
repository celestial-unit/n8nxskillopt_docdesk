"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { Activity, Check, Clock3, GitBranch, History, Play, RefreshCw, ShieldCheck, X } from "lucide-react"
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { SkillOptShowcase } from "@/components/skillopt-showcase"

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
type Payload = {
  run: Record<string, any>
  summary: Record<string, any>
  runs: Array<Record<string, any>>
  steps: Array<Record<string, any>>
  skillopt_versions: Array<{ version: string; text: string }>
  runtime_versions: Array<{ version: string; path: string; text: string }>
  model_usage?: { calls: number; prompt_tokens: number; completion_tokens: number; total_tokens: number }
  log: string
}

function percent(value: unknown) {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "—"
}

export function SkillOptView() {
  const [data, setData] = useState<Payload | null>(null)
  const [error, setError] = useState("")
  const [running, setRunning] = useState(false)
  const [selected, setSelected] = useState("")

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/skillopt/history`, { cache: "no-store" })
      if (!response.ok) throw new Error(`SkillOpt API returned ${response.status}`)
      const next = await response.json() as Payload
      setData(next)
      setRunning(next.run?.status === "running")
      setError("")
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load SkillOpt history")
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => { void refresh() }, 2500)
    return () => clearInterval(timer)
  }, [running, refresh])

  const chart = useMemo(() => (data?.steps ?? []).map((step, index) => ({
    step: `Step ${step.step ?? index + 1}`,
    current: typeof step.current_score === "number" ? step.current_score : null,
    best: typeof step.best_score === "number" ? step.best_score : null,
    rollout: typeof step.rollout_hard === "number" ? step.rollout_hard : null,
  })), [data])

  async function startRun() {
    setError("")
    setRunning(true)
    try {
      const response = await fetch(`${API_URL}/skillopt/run`, { method: "POST" })
      const body = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(body.detail ?? `Could not start SkillOpt (${response.status})`)
      await refresh()
    } catch (e) {
      setRunning(false)
      setError(e instanceof Error ? e.message : "Could not start SkillOpt")
    }
  }

  const baseline = data?.summary?.baseline_selection_score ?? data?.summary?.baseline_selection_soft ?? data?.summary?.baseline_selection_hard
  const best = data?.summary?.best_selection_score ?? data?.summary?.best_selection_hard
  const baselineCases = data?.summary?.baseline_selection_cases
  const activeSkill = data?.runtime_versions?.find(v => v.version === selected) ?? data?.runtime_versions?.at(-1)
  const selectionMetrics = data?.summary?.selection_metrics
  const testBaselineMetrics = data?.summary?.test_baseline_metrics
  const testInitialMetrics = data?.summary?.test_initial_metrics
  const testBestMetrics = data?.summary?.test_best_metrics
  const testBaseline = testBaselineMetrics?.mean_field_exact_match
  const testBest = testBestMetrics?.mean_field_exact_match

  return <main className="mx-auto max-w-[1480px] space-y-6 p-5 md:p-8">
    <SkillOptShowcase />
    <header className="flex flex-col justify-between gap-4 border-b border-neutral-700 pb-6 md:flex-row md:items-end">
      <div>
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-orange-400"><GitBranch size={15} /> Skill optimization</div>
        <h1 className="text-3xl font-semibold tracking-tight text-neutral-100">Company skills</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">Inspect every prompt version, see how its measured score changed, and review why SkillOpt kept or rejected an edit.</p>
      </div>
      <div className="flex gap-2">
        <button onClick={() => void refresh()} className="inline-flex items-center gap-2 rounded-lg border border-neutral-700 px-3 py-2 text-sm text-neutral-300 hover:bg-neutral-800"><RefreshCw size={15} /> Refresh</button>
        <button onClick={() => void startRun()} disabled={running} className="inline-flex items-center gap-2 rounded-lg bg-orange-500 px-4 py-2 text-sm font-semibold text-white hover:bg-orange-400 disabled:cursor-wait disabled:opacity-60"><Play size={15} /> {running ? "SkillOpt running…" : "Run SkillOpt"}</button>
      </div>
    </header>

    {error && <div className="rounded-lg border border-red-900 bg-red-950/30 p-4 text-sm text-red-300">{error}</div>}
    {data?.run?.status === "failed" && <div className="rounded-lg border border-red-900 bg-red-950/30 p-4 text-sm text-red-200"><b>Run failed.</b> {data.run.error} <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-xs text-red-300">{data.run.log_tail}</pre></div>}

    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-7">
      {[
        ["Status", data?.run?.status ?? "Loading", data?.run?.accepted === true ? "A skill version cleared the selection gate" : data?.run?.status === "complete" ? "No edit passed the strict improvement gate" : "Real SkillOpt library run"],
        ["Selection · baseline → best", `${percent(baseline)} → ${percent(best)}`, baselineCases ? `${baselineCases.completed}/${baselineCases.total} gate documents · mean field exact match` : "Mean normalized field exact match"],
        ["Unseen test · field match", `${percent(testBaseline)} → ${percent(testBest)}`, "Mean exact match on successful model responses only"],
        ["Unseen test · coverage", `${testBaselineMetrics?.model_responses ?? "—"}/${testBaselineMetrics?.documents_scored ?? "—"} → ${testBestMetrics?.model_responses ?? "—"}/${testBestMetrics?.documents_scored ?? "—"}`, "Returned predictions · total test documents"],
        ["Exact selection documents", selectionMetrics ? `${selectionMetrics.documents_exact}/${selectionMetrics.documents_scored}` : "—", "Every scored field matched exactly"],
        ["Evaluation cohort", data?.run?.splits ? `${data.run.splits.train} train · ${data.run.splits.selection} selection · ${data.run.splits.test ?? 0} test` : "12 train · 20 selection · 10 test", "Balanced Company B synthetic documents"],
        ["Target model tokens", data?.model_usage ? data.model_usage.total_tokens.toLocaleString() : "—", `${data?.model_usage?.calls ?? 0} recorded extraction calls`],
      ].map(([label, value, note]) => <div key={String(label)} className="rounded-xl border border-neutral-700 bg-neutral-900/70 p-4">
        <div className="text-xs uppercase tracking-wider text-neutral-500">{label}</div><div className="mt-2 text-2xl font-semibold tabular-nums text-neutral-100">{value}</div><div className="mt-1 text-xs text-neutral-500">{note}</div>
      </div>)}
    </section>

    <section className="grid gap-5 xl:grid-cols-[1.4fr_1fr]">
      <div className="rounded-xl border border-neutral-700 bg-neutral-900/65 p-5">
        <div className="mb-4 flex items-start justify-between"><div><h2 className="font-semibold text-neutral-100">Selection performance</h2><p className="mt-1 text-xs text-neutral-500">The library scores each candidate on the held-out selection split before accepting it.</p></div><Activity className="text-orange-400" size={18} /></div>
        <div className="h-64">
          {chart.length ? <ResponsiveContainer width="100%" height="100%"><LineChart data={chart} margin={{ top: 8, right: 12, bottom: 2, left: -20 }}><CartesianGrid stroke="#39362f" vertical={false} /><XAxis dataKey="step" tick={{ fill: "#a8a29e", fontSize: 11 }} axisLine={false} tickLine={false} /><YAxis domain={[0, 1]} tickFormatter={v => `${Math.round(v * 100)}%`} tick={{ fill: "#a8a29e", fontSize: 11 }} axisLine={false} tickLine={false} /><Tooltip contentStyle={{ background: "#262520", border: "1px solid #4a463e", borderRadius: 10, color: "#ece9e3" }} formatter={(v: number) => percent(v)} /><Line type="monotone" dataKey="current" name="Current skill" stroke="#D97757" strokeWidth={2.5} connectNulls dot={{ r: 3 }} /><Line type="monotone" dataKey="best" name="Best skill" stroke="#2dd4a0" strokeWidth={2.5} connectNulls dot={{ r: 3 }} /></LineChart></ResponsiveContainer> : <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-neutral-700 text-sm text-neutral-500">{running ? "Collecting rollout and validation results…" : "Run SkillOpt to build the first score history"}</div>}
        </div>
        <div className="mt-3 flex flex-wrap gap-4 text-xs text-neutral-400"><span className="inline-flex items-center gap-2"><i className="h-2 w-2 rounded-full bg-orange-400" /> Current skill</span><span className="inline-flex items-center gap-2"><i className="h-2 w-2 rounded-full bg-emerald-400" /> Best validated skill</span></div>
      </div>

      <div className="rounded-xl border border-neutral-700 bg-neutral-900/65 p-5">
        <div className="mb-4 flex items-center gap-2"><ShieldCheck className="text-orange-400" size={18} /><h2 className="font-semibold text-neutral-100">What this run does</h2></div>
        <ol className="space-y-3 text-sm text-neutral-400">
          <li className="flex gap-3"><span className="text-orange-400">01</span><span>The target model runs the current extractor skill on TRAIN documents and scores the 10 fields in the production Extractor contract.</span></li>
          <li className="flex gap-3"><span className="text-orange-400">02</span><span>The SkillOpt optimizer reflects on failed trajectories and proposes bounded edits.</span></li>
          <li className="flex gap-3"><span className="text-orange-400">03</span><span>The library gates each proposed version on the continuous SELECTION score; only a strict gain is promoted.</span></li>
        </ol>
        <div className="mt-5 rounded-lg border border-neutral-700 bg-neutral-950/50 p-3 text-xs leading-5 text-neutral-400">The cohort uses {data?.run?.splits?.train ?? 12} TRAIN, {data?.run?.splits?.selection ?? 20} SELECTION, and {data?.run?.splits?.test ?? 10} TEST documents. The test set stays out of SkillOpt’s edit gate and runs after optimization. Scores are normalized exact match over supported Extractor API fields; line descriptions map to production <code>lines[]</code>, and unsupported <code>reference_unique</code> is excluded. This is a synthetic benchmark, not company-wide accuracy.</div>
        {data?.run?.status === "complete" && typeof baseline === "number" && baseline >= 0.999 && selectionMetrics?.documents_scored === baselineCases?.total && <div className="mt-3 rounded-lg border border-amber-800/60 bg-amber-950/20 p-3 text-xs leading-5 text-amber-200">Ceiling reached on the full selection cohort: SkillOpt has no measured headroom to improve this score. The optimizer must not promote a no-change run. Check the untouched test score before claiming the quality generalizes.</div>}
      </div>
    </section>

    <section className="rounded-xl border border-neutral-700 bg-neutral-900/65 p-5">
      <h2 className="font-semibold text-neutral-100">Held-out field breakdown</h2>
      <p className="mt-1 text-xs text-neutral-500">Baseline skill · exact matches over scored selection cases. It does not average fields together invisibly.</p>
      <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{Object.entries(selectionMetrics?.field_accuracy ?? {}).map(([field, metric]: [string, any]) => <div key={field} className="flex items-center justify-between rounded-lg border border-neutral-800 bg-neutral-950/50 px-3 py-2 text-xs"><span className="text-neutral-300">{field.replaceAll("_", " ")}</span><span className="font-mono text-neutral-400">{metric.correct}/{metric.total} · {percent(metric.score)}</span></div>)}</div>
      {!Object.keys(selectionMetrics?.field_accuracy ?? {}).length && <p className="mt-3 text-sm text-neutral-500">No persisted held-out field predictions are available yet.</p>}
      {((testInitialMetrics?.provider_failures ?? 0) + (testBestMetrics?.provider_failures ?? 0) > 0) && <div className="mt-4 rounded-lg border border-red-900/70 bg-red-950/20 p-3 text-xs leading-5 text-red-200">The initial test was affected by provider connection errors: {testInitialMetrics.provider_failures}/{testInitialMetrics.documents_scored} baseline attempts failed. Any recovery attempts are merged into the baseline result above; candidate test coverage is {testBestMetrics.model_responses}/{testBestMetrics.documents_scored}. Accuracy is conditional on completed model responses, with coverage shown separately.</div>}
    </section>

    <section className="grid gap-5 xl:grid-cols-[1.1fr_1.4fr]">
      <div className="overflow-hidden rounded-xl border border-neutral-700 bg-neutral-900/65">
        <div className="flex items-center justify-between border-b border-neutral-700 px-5 py-4"><div><h2 className="font-semibold text-neutral-100">Optimization history</h2><p className="mt-1 text-xs text-neutral-500">Rollouts, edits and gate decisions from the actual library run.</p></div><History size={18} className="text-orange-400" /></div>
        <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead className="text-neutral-500"><tr>{["Step", "Train score", "Best score", "Decision"].map(x => <th key={x} className="px-4 py-3 font-medium">{x}</th>)}</tr></thead><tbody>{(data?.steps ?? []).map((step, i) => <tr key={step.step ?? i} className="border-t border-neutral-800"><td className="px-4 py-3 font-medium text-neutral-200">{step.step ?? i + 1}</td><td className="px-4 py-3 text-neutral-300">{percent(step.rollout_hard)}</td><td className="px-4 py-3 text-neutral-300">{percent(step.best_score)}</td><td className="px-4 py-3"><span className="inline-flex items-center gap-1 text-neutral-300">{String(step.action ?? "pending").includes("accept") ? <Check size={13} className="text-emerald-400" /> : String(step.action ?? "").includes("reject") ? <X size={13} className="text-red-400" /> : <Clock3 size={13} className="text-amber-400" />}{step.action ?? "pending"}</span></td></tr>)}</tbody></table>{!data?.steps?.length && <p className="p-5 text-sm text-neutral-500">No optimizer steps recorded yet.</p>}</div>
        {data?.runs?.length ? <div className="border-t border-neutral-700 p-4"><h3 className="mb-2 text-xs uppercase tracking-wider text-neutral-500">Previous runs</h3>{data.runs.filter(run => run.run_id !== data.run?.run_id).map(run => <div key={run.run_id} className="flex justify-between border-t border-neutral-800 py-2 text-xs"><span className="text-neutral-300">{run.run_id}</span><span className="text-neutral-400">{run.status === "failed" ? "stopped · metric issue recorded" : `${percent(run.baseline_selection_hard)} → ${percent(run.best_selection_hard)} · ${run.total_accepts ?? 0} accepted`}</span></div>)}</div> : null}
      </div>

      <div className="overflow-hidden rounded-xl border border-neutral-700 bg-neutral-900/65">
        <div className="border-b border-neutral-700 px-5 py-4"><h2 className="font-semibold text-neutral-100">Skill versions</h2><p className="mt-1 text-xs text-neutral-500">Compare the immutable runtime skill files produced by the optimizer.</p></div>
        <div className="flex flex-wrap gap-2 border-b border-neutral-800 p-4">{(data?.runtime_versions ?? []).map(version => <button key={version.version} onClick={() => setSelected(version.version)} className={`rounded-lg border px-3 py-1.5 text-xs ${selected === version.version || (!selected && activeSkill?.version === version.version) ? "border-orange-400/50 bg-orange-400/10 text-orange-200" : "border-neutral-700 text-neutral-400 hover:bg-neutral-800"}`}>{version.version}{version.version === data?.run?.promoted_version ? " · promoted" : ""}</button>)}</div>
        {activeSkill ? <div className="p-4"><div className="mb-2 font-mono text-xs text-neutral-500">{activeSkill.path}</div><pre className="max-h-[420px] overflow-auto whitespace-pre-wrap rounded-lg border border-neutral-800 bg-neutral-950/70 p-4 text-xs leading-5 text-neutral-300">{activeSkill.text}</pre></div> : <div className="p-5 text-sm text-neutral-500">No runtime skill files found.</div>}
      </div>
    </section>

    <details className="rounded-xl border border-neutral-700 bg-neutral-900/50 p-4"><summary className="cursor-pointer text-sm text-neutral-300">SkillOpt run log</summary><pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-neutral-950 p-4 text-xs leading-5 text-neutral-400">{data?.log || "No run log yet."}</pre></details>
  </main>
}
