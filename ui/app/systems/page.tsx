"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Server, Database, Activity, CheckCircle, AlertTriangle, Cpu } from "lucide-react"
import { fetchHealth, API_URL, N8N_WEBHOOK } from "@/lib/api"

const SYSTEM_DEFS = [
  { id: "fastapi",  name: "FASTAPI BACKEND",  type: "Primary Server", icon: "server",   url: API_URL },
  { id: "qdrant",   name: "QDRANT VECTOR DB",  type: "Database",       icon: "database", url: "http://localhost:6333" },
  { id: "llm",      name: "LLM CLIENT",        type: "Processing",     icon: "cpu",      url: "" },
  { id: "n8n",      name: "N8N WORKFLOW",      type: "Network",        icon: "activity", url: "http://localhost:5678" },
  { id: "sqlite",   name: "SQLITE TRACES",     type: "Storage",        icon: "database", url: "" },
]

export default function SystemsPage() {
  const [components, setComponents] = useState<Record<string, string>>({})
  const [n8nStatus, setN8nStatus] = useState<string>("checking")
  const [lastUpdated, setLastUpdated] = useState("")

  const poll = async () => {
    const h = await fetchHealth().catch(() => ({ status: "degraded" as const, components: {} as Record<string, string> }))
    setComponents(h.components ?? {})
    // probe n8n
    try {
      const r = await fetch("http://localhost:5678/healthz", { signal: AbortSignal.timeout(2000) })
      setN8nStatus(r.ok ? "ok" : "error")
    } catch { setN8nStatus("offline") }
    setLastUpdated(new Date().toLocaleTimeString())
  }

  useEffect(() => { poll(); const iv = setInterval(poll, 5000); return () => clearInterval(iv) }, [])

  const getComp = (id: string) => {
    if (id === "n8n") return n8nStatus
    if (id === "fastapi") return components.sqlite !== undefined ? "ok" : "error"
    return components[id] ?? "checking"
  }

  const statusColor = (s: string) => s === "ok" ? "bg-white/20 text-white" : s === "checking" ? "bg-neutral-500/20 text-neutral-400" : "bg-red-500/20 text-red-500"
  const dotColor   = (s: string) => s === "ok" ? "bg-orange-500 animate-pulse" : s === "checking" ? "bg-neutral-500" : "bg-red-500"

  const online = SYSTEM_DEFS.filter(s => getComp(s.id) === "ok").length

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-wider">SYSTEMS MONITOR</h1>
          <p className="text-sm text-neutral-400">Pipeline infrastructure health · Updated: {lastUpdated}</p>
        </div>
        <Button onClick={poll} className="bg-orange-500 hover:bg-orange-600 text-white">Refresh</Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card className="bg-neutral-900 border-neutral-700"><CardContent className="p-4 flex items-center justify-between">
          <div><p className="text-xs text-neutral-400 tracking-wider">SYSTEMS ONLINE</p><p className="text-2xl font-bold text-white font-mono">{online}/{SYSTEM_DEFS.length}</p></div>
          <CheckCircle className="w-8 h-8 text-white" /></CardContent></Card>
        <Card className="bg-neutral-900 border-neutral-700"><CardContent className="p-4 flex items-center justify-between">
          <div><p className="text-xs text-neutral-400 tracking-wider">FASTAPI</p><p className={`text-2xl font-bold font-mono ${getComp("fastapi")==="ok"?"text-orange-500":"text-red-500"}`}>{getComp("fastapi").toUpperCase()}</p></div>
          <Server className="w-8 h-8 text-white" /></CardContent></Card>
        <Card className="bg-neutral-900 border-neutral-700"><CardContent className="p-4 flex items-center justify-between">
          <div><p className="text-xs text-neutral-400 tracking-wider">N8N</p><p className={`text-2xl font-bold font-mono ${getComp("n8n")==="ok"?"text-orange-500":"text-red-500"}`}>{getComp("n8n").toUpperCase()}</p></div>
          <Activity className="w-8 h-8 text-white" /></CardContent></Card>
        <Card className="bg-neutral-900 border-neutral-700"><CardContent className="p-4 flex items-center justify-between">
          <div><p className="text-xs text-neutral-400 tracking-wider">LLM</p><p className={`text-2xl font-bold font-mono ${getComp("llm")==="ok"?"text-orange-500":"text-yellow-500"}`}>{getComp("llm").toUpperCase()}</p></div>
          <Cpu className="w-8 h-8 text-white" /></CardContent></Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
        {SYSTEM_DEFS.map(sys => {
          const s = getComp(sys.id)
          return (
            <Card key={sys.id} className={`bg-neutral-900 border transition-colors ${s==="ok"?"border-orange-500/50":"border-neutral-700"}`}>
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between">
                  <div><CardTitle className="text-sm font-bold text-white tracking-wider">{sys.name}</CardTitle>
                    <p className="text-xs text-neutral-400">{sys.type}</p></div>
                  <div className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${dotColor(s)}`} />
                    <Badge className={statusColor(s)}>{s.toUpperCase()}</Badge>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="text-xs text-neutral-500 font-mono space-y-1">
                  {sys.url && <div>URL: {sys.url}</div>}
                  <div>Status: <span className={s==="ok"?"text-orange-500":s==="checking"?"text-neutral-400":"text-red-400"}>{s}</span></div>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
