"use client"

import { useEffect, useState } from "react"
import { ArrowRight, FlaskConical } from "lucide-react"

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

type Showcase = {
  status: string
  label?: string
  selection?: { weak_baseline?: number; optimized?: number; total?: number }
  test?: { weak_baseline_exact?: number; optimized_exact?: number; total?: number }
  accepted?: boolean
  note?: string
}

function score(value: number | undefined) {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "—"
}

export function SkillOptShowcase() {
  const [data, setData] = useState<Showcase | null>(null)

  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = async () => {
      try {
        const response = await fetch(`${API_URL}/skillopt/showcase`, { cache: "no-store" })
        const value = response.ok ? await response.json() as Showcase : null
        if (!active) return
        setData(value)
        if (value?.status !== "complete") timer = setTimeout(() => void load(), 5000)
      } catch {
        if (!active) return
        setData(null)
        timer = setTimeout(() => void load(), 5000)
      }
    }
    void load()
    return () => { active = false; if (timer) clearTimeout(timer) }
  }, [])

  const hasSelection = typeof data?.selection?.weak_baseline === "number" && typeof data?.selection?.optimized === "number"
  return <section className="rounded-xl border border-emerald-800/70 bg-gradient-to-br from-emerald-950/40 to-neutral-900 p-5">
    <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-emerald-300"><FlaskConical size={15} /> SkillOpt improvement showcase</div>
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <h2 className="text-lg font-semibold text-neutral-100">Weak skill → optimized skill</h2>
      <span className="rounded-full border border-amber-700/70 bg-amber-950/40 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-200">deliberately weak demo baseline</span>
    </div>
    <p className="mt-2 max-w-4xl text-xs leading-5 text-neutral-400">This isolated benchmark starts from a prompt that explicitly refuses to extract fields. It demonstrates SkillOpt’s repair loop; it is not the normal production baseline.</p>
    {hasSelection ? <>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-neutral-700 bg-neutral-950/60 p-4">
          <div className="text-[10px] uppercase tracking-wider text-neutral-500">SELECTION · optimizer gate</div>
          <div className="mt-2 flex items-center gap-3 text-2xl font-semibold tabular-nums text-neutral-100"><span className="text-rose-300">{score(data.selection?.weak_baseline)}</span><ArrowRight size={18} className="text-neutral-500" /><span className="text-emerald-300">{score(data.selection?.optimized)}</span></div>
          <div className="mt-1 text-xs text-neutral-500">Soft normalized field match · {data.selection?.total ?? "—"} documents</div>
        </div>
        <div className="rounded-lg border border-neutral-700 bg-neutral-950/60 p-4">
          <div className="text-[10px] uppercase tracking-wider text-neutral-500">UNSEEN TEST · final check</div>
          <div className="mt-2 flex items-center gap-3 text-2xl font-semibold tabular-nums text-neutral-100"><span className="text-rose-300">{data.test?.weak_baseline_exact ?? "—"}/{data.test?.total ?? "—"}</span><ArrowRight size={18} className="text-neutral-500" /><span className="text-emerald-300">{data.test?.optimized_exact ?? "—"}/{data.test?.total ?? "—"}</span></div>
          <div className="mt-1 text-xs text-neutral-500">{data.test ? "Exact match is strict; see the report for soft NEM detail" : "Held-out comparison appears after the selection gate finishes"}</div>
        </div>
      </div>
      <p className="mt-3 text-xs leading-5 text-neutral-300">{data.note}</p>
    </> : <div className="mt-4 rounded-lg border border-dashed border-neutral-700 p-4 text-xs text-neutral-400">{data?.status === "running" ? "SkillOpt is optimizing the weak prompt. Refresh this page after the run finishes to see measured scores." : "The SkillOpt showcase has not published its measured result yet."}</div>}
  </section>
}
