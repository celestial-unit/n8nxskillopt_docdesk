"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { SkillOptShowcase } from "@/components/skillopt-showcase"
import {
  fetchTraces, parseChunks,
  fetchRetrievalEval, fetchBaselineEval,
  fetchCoderImprovement, type CoderImprovementEval,
  type RetrievalEval, type BaselineEval
} from "@/lib/api"

function ScoreBar({ value, max = 1, label, color = "bg-orange-500" }: { value: number; max?: number; label: string; color?: string }) {
  const pct = Math.round((value / max) * 100)
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-neutral-400">{label}</span>
        <span className="text-white font-mono font-bold">{(value * 100).toFixed(1)}%</span>
      </div>
      <div className="w-full bg-neutral-800 rounded-full h-2">
        <div className={`${color} h-2 rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export default function IntelligencePage() {
  const [docId, setDocId] = useState("")
  const [chunks, setChunks] = useState<Array<{text: string; score: number; source: string}>>([])
  const [loading, setLoading] = useState(false)
  const [retrieval, setRetrieval] = useState<RetrievalEval | null>(null)
  const [baseline, setBaseline] = useState<BaselineEval | null>(null)
  const [coderImprovement, setCoderImprovement] = useState<CoderImprovementEval | null>(null)

  useEffect(() => {
    fetchRetrievalEval().then(setRetrieval)
    fetchBaselineEval().then(setBaseline)
    fetchCoderImprovement().then(setCoderImprovement)
  }, [])

  const handleFetch = async () => {
    setLoading(true)
    const ts = await fetchTraces(docId.trim())
    const codeTrace = ts.find(t => t.step === "code")
    setChunks(codeTrace ? parseChunks(codeTrace) : [])
    setLoading(false)
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white tracking-wider">QUALITY & RETRIEVAL</h1>
        <p className="text-sm text-neutral-400">Measured baseline quality, retrieved company rules, and the current SkillOpt status.</p>
      </div>

      {/* ── RAG Retrieval Evaluation ──────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-4">
        {[
          { company: "Company A (Alpha SARL)", recall: retrieval?.recallA, mrr: retrieval?.mrrA, queries: retrieval?.nQueriesA, chunks: retrieval?.nChunksA },
          { company: "Company B (Beta International)", recall: retrieval?.recallB, mrr: retrieval?.mrrB, queries: retrieval?.nQueriesB, chunks: retrieval?.nChunksB },
        ].map(({ company, recall, mrr, queries, chunks: indexedChunks }) => (
          <Card key={company} className="bg-neutral-900 border-neutral-700">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs text-neutral-400 tracking-wider">RAG — {company}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {recall != null ? (
                <>
                  <ScoreBar value={recall} label="Recall@5" color="bg-orange-500" />
                  {mrr != null && <ScoreBar value={mrr} label="MRR@5" color="bg-blue-500" />}
                  <p className="text-xs text-neutral-600">
                    {queries ?? "—"} queries · {indexedChunks ?? "—"} indexed chunks · paraphrase-multilingual-mpnet-base-v2
                  </p>
                </>
              ) : (
                <p className="text-xs text-neutral-600">Run python3 -m eval.retrieval_eval to populate</p>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* ── Baseline Agent Scores ────────────────────────────────────────── */}
      <SkillOptShowcase />
      {coderImprovement?.summary && <Card className="bg-neutral-900 border-orange-800/60">
        <CardHeader className="pb-2"><CardTitle className="text-xs text-orange-300 tracking-wider">CODER PROMPT · PAIRED IMPROVEMENT</CardTitle></CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-3">
            <div><div className="text-xs text-neutral-500">Code accuracy</div><div className="mt-1 font-mono text-xl text-white">{Math.round((coderImprovement.summary.baseline_v001?.code_accuracy ?? 0) * 100)}% <span className="text-neutral-500">→</span> <span className="text-emerald-300">{Math.round((coderImprovement.summary.improved_v004?.code_accuracy ?? 0) * 100)}%</span></div></div>
            <div><div className="text-xs text-neutral-500">Correct code + supported citation</div><div className="mt-1 font-mono text-xl text-white">{Math.round((coderImprovement.summary.baseline_v001?.supported_coder_score ?? 0) * 100)}% <span className="text-neutral-500">→</span> <span className="text-emerald-300">{Math.round((coderImprovement.summary.improved_v004?.supported_coder_score ?? 0) * 100)}%</span></div></div>
            <div><div className="text-xs text-neutral-500">Paired selection cases</div><div className="mt-1 font-mono text-xl text-white">{coderImprovement.summary.paired_n ?? 0} <span className="text-neutral-500">· +{coderImprovement.summary.paired_delta_pp ?? 0} pp supported score</span></div></div>
          </div>
          <p className="mt-3 text-xs leading-5 text-neutral-400">Gold extracted fields and identical top-5 RAG context isolate the Coder prompt. Fixed 10-document SELECTION sample; useful early evidence, not a full-corpus or TEST result.</p>
        </CardContent>
      </Card>}
      <Card className="bg-neutral-900 border-neutral-700">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs text-neutral-400 tracking-wider">BASELINE SCORES — SELECTION SET (v001 skills)</CardTitle>
        </CardHeader>
        <CardContent>
          {!baseline ? (
            <p className="text-xs text-neutral-600">Run python3 -m eval.baseline to populate</p>
          ) : (
            <div className="grid grid-cols-2 gap-6">
              {(["companyA", "companyB"] as const).map(company => {
                const d = baseline[company]
                if (!d) return null
                const label = company === "companyA" ? "Company A" : "Company B"
                return (
                  <div key={company} className="space-y-3">
                    <div className="text-xs text-neutral-500 tracking-wider">{label}</div>
                    <ScoreBar value={d.extractor} label="Extractor NEM" color="bg-cyan-500" />
                    <ScoreBar value={d.coderRag} label="Coder (with RAG)" color="bg-orange-500" />
                    <ScoreBar value={d.coderNoRag} label="Coder (no RAG)" color="bg-orange-800" />
                    <ScoreBar value={d.validator} label="Validator F-β" color="bg-purple-500" />
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── SkillOpt: method and verified project state ───────────────────── */}
      <Card className="bg-neutral-900 border-neutral-700">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs text-neutral-400 tracking-wider">SKILLOPT · PROMPT IMPROVEMENT LOOP</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="max-w-4xl text-sm leading-6 text-neutral-400">SkillOpt optimizes an agent’s Markdown skill. The target model tries TRAIN documents, the optimizer studies mistakes and proposes bounded edits, and a selection-set gate accepts only improvements. After the single optimization run, compare baseline and best skill on the held-out TEST set.</p>
          <div className="grid gap-3 md:grid-cols-4">
            {[
              ["TRAIN", "Generate examples and failure traces"],
              ["OPTIMIZE", "Propose a small prompt patch"],
              ["SELECTION", "Accept or reject the patch"],
              ["TEST", "One final held-out comparison"],
            ].map(([title, detail]) => <div key={title} className="rounded border border-neutral-800 bg-neutral-950 p-3">
              <div className="text-xs font-bold tracking-wider text-orange-400">{title}</div>
              <div className="mt-2 text-xs leading-5 text-neutral-500">{detail}</div>
            </div>)}
          </div>
          <div className="rounded border border-neutral-700 bg-neutral-950/50 p-4">
            <div className="text-sm font-semibold text-neutral-200">Production skill history</div>
            <p className="mt-1 text-xs leading-5 text-neutral-400">The production prompt remains unchanged when the isolated weak-skill showcase runs. Open Skill History to inspect the real production optimization run and its selection gate.</p>
          </div>
        </CardContent>
      </Card>

      {/* ── RAG Chunk Inspector ──────────────────────────────────────────── */}
      <Card className="bg-neutral-900 border-neutral-700">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs text-neutral-400 tracking-wider">RAG CHUNK INSPECTOR</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-3">
            <input value={docId} onChange={e => setDocId(e.target.value)}
              placeholder="Enter doc_id to inspect retrieved RAG chunks"
              className="flex-1 bg-neutral-800 border border-neutral-600 text-white text-sm px-3 py-2 rounded placeholder-neutral-500 font-mono" />
            <Button onClick={handleFetch} disabled={loading} className="bg-orange-500 hover:bg-orange-600 text-white">
              {loading ? "Loading…" : "Inspect"}
            </Button>
          </div>

          {chunks.length > 0 && (
            <div className="space-y-3">
              <div className="text-xs text-neutral-500">{chunks.length} chunks retrieved for the Coder agent</div>
              {chunks.map((c, i) => (
                <div key={i} className="border border-neutral-700 rounded p-3 space-y-2">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-neutral-500 font-mono">{c.source}</span>
                    <span className="text-orange-500 font-mono font-bold">cosine {c.score.toFixed(3)}</span>
                  </div>
                  <div className="w-full bg-neutral-800 rounded-full h-1.5">
                    <div className="bg-orange-500 h-1.5 rounded-full"
                      style={{ width: `${Math.max(0, Math.min(1, c.score)) * 100}%` }} />
                  </div>
                  <p className="text-xs text-neutral-300 leading-relaxed">
                    {c.text.slice(0, 250)}{c.text.length > 250 ? "…" : ""}
                  </p>
                </div>
              ))}
            </div>
          )}

          {chunks.length === 0 && docId && !loading && (
            <div className="text-neutral-500 text-xs font-mono text-center py-4">
              No RAG chunks found. Process a document through the full pipeline first.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
