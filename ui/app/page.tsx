"use client"

import { useEffect, useState } from "react"
import { ChevronRight, Database, FileInput, Gauge, GitBranch, LayoutDashboard, Settings, Users } from "lucide-react"
import { Button } from "@/components/ui/button"
import { DashboardView } from "@/components/dashboard-view"
import CommandCenterPage from "./command-center/page"
import AgentNetworkPage from "./agent-network/page"
import OperationsPage from "./operations/page"
import IntelligencePage from "./intelligence/page"
import SystemsPage from "./systems/page"
import { SkillOptView } from "@/components/skillopt-view"

export default function TacticalDashboard() {
  const [activeSection, setActiveSection] = useState("overview")
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true)

  useEffect(() => {
    const breakpoint = window.matchMedia("(min-width: 768px)")
    const syncSidebar = () => setSidebarCollapsed(!breakpoint.matches)
    syncSidebar()
    breakpoint.addEventListener("change", syncSidebar)
    return () => breakpoint.removeEventListener("change", syncSidebar)
  }, [])

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <div
        className={`${sidebarCollapsed ? "w-16" : "w-64"} bg-neutral-950 border-r border-neutral-800 transition-all duration-300 fixed md:relative z-50 md:z-auto h-full md:h-auto ${!sidebarCollapsed ? "md:block" : ""}`}
      >
        <div className="p-4">
          <div className="flex items-center justify-between mb-8">
            <div className={`${sidebarCollapsed ? "hidden" : "block"}`}>
              <h1 className="text-orange-400 font-semibold text-lg tracking-tight">DocDesk</h1>
              <p className="text-neutral-500 text-[10px] tracking-[0.13em]">ACCOUNTING WORKFLOW</p>
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
                className="rounded-lg text-neutral-400 transition-colors hover:bg-neutral-800 hover:text-orange-300"
            >
              <ChevronRight
                className={`w-4 h-4 sm:w-5 sm:h-5 transition-transform ${sidebarCollapsed ? "" : "rotate-180"}`}
              />
            </Button>
          </div>

          <nav className="space-y-2">
            {[
              { id: "overview", icon: LayoutDashboard, label: "OVERVIEW" },
              { id: "process", icon: FileInput, label: "PROCESS DOCUMENT" },
              { id: "ledger", icon: Database, label: "DOCUMENT LEDGER" },
              { id: "quality", icon: GitBranch, label: "QUALITY & RAG" },
              { id: "skillopt", icon: GitBranch, label: "SKILL HISTORY" },
              { id: "agents", icon: Users, label: "AGENT NETWORK" },
              { id: "systems", icon: Settings, label: "SYSTEM HEALTH" },
            ].map((item) => (
              <button
                key={item.id}
                onClick={() => setActiveSection(item.id)}
                  className={`w-full flex items-center gap-3 rounded-xl p-3 text-left transition-colors duration-200 ${
                  activeSection === item.id
                    ? "border border-orange-400/20 bg-orange-400/10 text-orange-200"
                    : "text-neutral-400 hover:bg-neutral-800/80 hover:text-neutral-100"
                }`}
              >
                <item.icon className="w-5 h-5 md:w-5 md:h-5 sm:w-6 sm:h-6" />
                {!sidebarCollapsed && <span className="text-sm font-medium">{item.label}</span>}
              </button>
            ))}
          </nav>

          {!sidebarCollapsed && (
            <div className="mt-8 rounded-xl border border-neutral-700/80 bg-neutral-900/60 p-4">
              <div className="flex items-center gap-2 mb-2">
                <Database size={12} className="text-orange-400" />
                <span className="text-xs text-white">PROJECT DATA</span>
              </div>
              <div className="text-xs text-neutral-500">
                <div className="flex items-center gap-2"><Database size={12} /> Local SQLite audit ledger</div>
                <div className="flex items-center gap-2"><Gauge size={12} /> Live metrics from processed documents</div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Mobile Overlay */}
      {!sidebarCollapsed && (
        <div className="fixed inset-0 bg-black/50 z-40 md:hidden" onClick={() => setSidebarCollapsed(true)} />
      )}

      {/* Main Content */}
      <div className={`flex-1 flex flex-col ${!sidebarCollapsed ? "md:ml-0" : ""}`}>
        {/* Top Toolbar */}
        <div className="flex h-16 items-center justify-between border-b border-neutral-800 bg-neutral-950/70 px-6">
          <div className="flex items-center gap-4">
            <div className="text-sm text-neutral-400">DocDesk <span className="mx-2 text-neutral-600">/</span><span className="text-orange-300">{activeSection.replaceAll("-", " ").toUpperCase()}</span></div>
          </div>
          <div className="text-xs text-neutral-500">Local audit · SQLite</div>
        </div>

        {/* Dashboard Content */}
        <div className="flex-1 overflow-auto">
          {activeSection === "overview" && <DashboardView onNavigate={setActiveSection} />}
          {activeSection === "process" && <CommandCenterPage />}
          {activeSection === "ledger" && <OperationsPage />}
          {activeSection === "agents" && <AgentNetworkPage />}
          {activeSection === "quality" && <IntelligencePage />}
          {activeSection === "skillopt" && <SkillOptView />}
          {activeSection === "systems" && <SystemsPage />}
        </div>
      </div>
    </div>
  )
}
