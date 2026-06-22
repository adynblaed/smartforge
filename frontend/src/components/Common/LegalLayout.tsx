import { Link } from "@tanstack/react-router"
import { ArrowLeft } from "lucide-react"
import type { ReactNode } from "react"

import { Appearance } from "@/components/Common/Appearance"
import { Footer } from "@/components/Common/Footer"

export function LegalLayout({
  title,
  updated,
  children,
}: {
  title: string
  updated: string
  children: ReactNode
}) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-10 border-b bg-background/80 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-4">
          <Link
            to="/"
            className="flex items-center gap-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft size={16} /> Back to SmartForge
          </Link>
          <Appearance />
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-6 py-10">
        <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-2 text-sm text-muted-foreground">Last updated {updated}</p>
        <div className="mt-8 space-y-4 text-sm leading-relaxed text-muted-foreground">
          {children}
        </div>
      </main>
      <Footer />
    </div>
  )
}

export const H2 = ({ children }: { children: ReactNode }) => (
  <h2 className="mt-10 text-xl font-semibold text-foreground">{children}</h2>
)

export const H3 = ({ children }: { children: ReactNode }) => (
  <h3 className="mt-6 text-base font-semibold text-foreground">{children}</h3>
)

export const P = ({ children }: { children: ReactNode }) => <p>{children}</p>

export const Lead = ({ children }: { children: ReactNode }) => (
  <p className="rounded-md border-l-2 border-primary/60 bg-muted/40 px-3 py-2 italic">
    {children}
  </p>
)

export const UL = ({ items }: { items: ReactNode[] }) => (
  <ul className="list-disc space-y-1.5 pl-6">
    {items.map((it, i) => (
      <li key={i}>{it}</li>
    ))}
  </ul>
)
