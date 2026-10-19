"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { fetchHealth } from "@/lib/api"

const AGENTS = [
  { id: "router", name: "ROUTER AGENT", role: "Classifies doc type and modality" },
  { id: "extractor", name: "EXTRACTOR AGENT", role: "Extracts structured fields from documents" },
  { id: "coder", name: "CODER AGENT", role: "Assigns account code via RAG" },
  { id: "validator", name: "VALIDATOR AGENT", role: "Validates arithmetic, NIF, duplicates" },
  { id: "exception_handler", name: "EXCEPTION HANDLER", role: "Prepares escalation dossier" },
]

export default function AgentNetworkPage() {
  const [health, setHealth] = useState<Record<string, string>>({})
  const [lastUpdated, setLastUpdated] = useState<string>("")

  useEffect(() => {
    const poll = async () => {
      const h = await fetchHealth().catch(() => ({ status: "degraded" as const, components: {} }))
      setHealth(h.components ?? {})
      setLastUpdated(new Date().toLocaleTimeString())
    }
    poll()
    const iv = setInterval(poll, 5000)
    return () => clearInterval(iv)
  }, [])

  const pipelineUp = health.sqlite === "ok"

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-wider">AGENT NETWORK</h1>
          <p className="text-sm text-neutral-400">Document pipeline agents — status and skill versions</p>
        </div>
        <div className="text-xs text-neutral-500 font-mono">Updated: {lastUpdated}</div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        {AGENTS.map(agent => (
          <Card key={agent.id} className="bg-neutral-900 border-neutral-700 hover:border-orange-500/50 transition-colors">
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between">
                <div>
                  <CardTitle className="text-sm font-bold text-white tracking-wider">{agent.name}</CardTitle>
                  <p className="text-xs text-neutral-400">{agent.role}</p>
                </div>
                <div className={`w-2 h-2 rounded-full mt-1 ${pipelineUp ? "bg-orange-500 animate-pulse" : "bg-neutral-600"}`} />
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between text-xs">
                <span className="text-neutral-400">STATUS</span>
                <span className={pipelineUp ? "text-orange-500 font-mono" : "text-neutral-500 font-mono"}>
                  {pipelineUp ? "READY" : "OFFLINE"}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-neutral-400">SKILL VERSION</span>
                <span className="text-white font-mono">v001</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-neutral-400">SKILL FILE</span>
                <span className="text-neutral-500 font-mono text-right">skills/*/</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-neutral-400">ENDPOINT</span>
                <span className="text-neutral-300 font-mono">POST /{agent.id === "exception_handler" ? "handle" : agent.id}</span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
