import type React from "react"
import type { Metadata } from "next"
import "./globals.css"

export const metadata: Metadata = {
  title: "DocDesk — Accounting Document Workflow",
  description: "Process, review, and audit Tunisian accounting documents.",
  generator: "DocDesk",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className="bg-[#1a1915] font-sans text-neutral-100 antialiased">{children}</body>
    </html>
  )
}
