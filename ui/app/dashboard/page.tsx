"use client"

import { DashboardView } from "@/components/dashboard-view"

export default function DashboardPage() {
  return <DashboardView onNavigate={(page) => {
    const routes: Record<string, string> = {
      process: "/command-center",
      ledger: "/operations",
      quality: "/intelligence",
    }
    window.location.assign(routes[page] ?? "/")
  }} />
}
