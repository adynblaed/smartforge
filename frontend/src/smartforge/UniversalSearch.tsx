import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { Boxes, FileText, Gauge, Search, Ticket as TicketIcon } from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { NAV_GROUPS } from "@/components/Sidebar/nav"
import { cn } from "@/lib/utils"
import { sf } from "@/smartforge/api"
import type { Machine, Page, PurchaseOrder, Sop, Ticket } from "@/smartforge/types"

type Kind = "page" | "machine" | "ticket" | "po" | "sop"
interface Item {
  kind: Kind
  label: string
  sub: string
  keywords: string // lowercased label + sub + aliases for fuzzy matching
  to?: string // page path
  id?: string // ticket / po id
  code?: string // sop code
}

// Synonyms/aliases per page so edge-case queries resolve (e.g. "pos" → Order
// Tracker / Purchase Orders, "kb" → Forge Facts).
const PAGE_ALIASES: Record<string, string> = {
  "/command-center": "home dashboard overview kpis",
  "/order-tracker": "po pos purchase order orders procurement receipt",
  "/supply-chain": "inventory supplier suppliers reorder stock materials po pos",
  "/quotes": "quote quoting purchase order po pos intake builder",
  "/knowledge-bases": "knowledge base bases kb forge facts notes",
  "/sops": "sop sops standard operating procedure",
  "/work-orders": "wo work order orders maintenance",
  "/tickets": "ticket tickets maintenance alert center",
  "/machines": "machine machines equipment health telemetry",
  "/factory-map": "simulation sim 3d digital twin factory",
  "/quality": "oee scrap defect defects quality inspection",
  "/optimization": "optimize optimization config what-if capacity simulation",
  "/logs": "log logs events terminal console audit",
  "/services": "service services uptime health heartbeat status",
  "/analytics": "analytics dashboards kpi charts",
  "/incidents": "incident incidents rca impact",
}

// Per-entity alias seeds so plurals/abbreviations match.
const KIND_ALIASES: Record<Kind, string> = {
  page: "",
  machine: "machine equipment",
  ticket: "ticket maintenance alert",
  po: "po pos purchase order orders",
  sop: "sop sops procedure",
}

const KIND_ICON: Record<Kind, React.ReactNode> = {
  page: <Search size={14} className="text-muted-foreground" />,
  machine: <Gauge size={14} className="text-sky-400" />,
  ticket: <TicketIcon size={14} className="text-amber-400" />,
  po: <Boxes size={14} className="text-emerald-400" />,
  sop: <FileText size={14} className="text-violet-400" />,
}

// Site-wide universal search: jumps to a page or deep-links to an entity
// (ticket / PO / SOP / machine) which opens + highlights the relevant result.
export function UniversalSearch() {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState("")
  const navigate = useNavigate()

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        setOpen((o) => !o)
      }
    }
    window.addEventListener("keydown", h)
    return () => window.removeEventListener("keydown", h)
  }, [])

  const enabled = open
  const machines = useQuery({
    queryKey: ["machines"],
    queryFn: () => sf.get<Page<Machine>>("/machines/"),
    enabled,
  })
  const tickets = useQuery({
    queryKey: ["tickets"],
    queryFn: () => sf.get<Page<Ticket>>("/tickets/"),
    enabled,
  })
  const pos = useQuery({
    queryKey: ["purchase-orders"],
    queryFn: () => sf.get<Page<PurchaseOrder>>("/purchase-orders"),
    enabled,
  })
  const sops = useQuery({
    queryKey: ["sops", null],
    queryFn: () => sf.get<Page<Sop>>("/sops/"),
    enabled,
  })

  const items = useMemo<Item[]>(() => {
    const kw = (label: string, sub: string, kind: Kind, extra = "") =>
      `${label} ${sub} ${KIND_ALIASES[kind]} ${extra}`.toLowerCase()
    const list: Item[] = []
    for (const g of NAV_GROUPS)
      for (const it of g.items)
        list.push({
          kind: "page",
          label: it.title,
          sub: g.label,
          to: it.path,
          keywords: kw(it.title, g.label, "page", PAGE_ALIASES[it.path] ?? ""),
        })
    for (const m of machines.data?.data ?? [])
      list.push({
        kind: "machine",
        label: `${m.code} — ${m.name}`,
        sub: "Machine",
        id: m.id,
        keywords: kw(`${m.code} ${m.name} ${m.machine_type}`, "Machine", "machine"),
      })
    for (const t of tickets.data?.data ?? [])
      list.push({
        kind: "ticket",
        label: `${t.code} — ${t.title}`,
        sub: "Ticket",
        id: t.id,
        keywords: kw(`${t.code} ${t.title}`, "Ticket", "ticket"),
      })
    for (const p of pos.data?.data ?? [])
      list.push({
        kind: "po",
        label: p.po_number,
        sub: "Purchase Order",
        id: p.id,
        keywords: kw(p.po_number, "Purchase Order", "po"),
      })
    for (const s of sops.data?.data ?? [])
      list.push({
        kind: "sop",
        label: `${s.code} — ${s.title}`,
        sub: "SOP",
        code: s.code,
        keywords: kw(`${s.code} ${s.title}`, "SOP", "sop"),
      })
    return list
  }, [machines.data, tickets.data, pos.data, sops.data])

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase()
    if (!term) return items.filter((i) => i.kind === "page")
    // Every whitespace-separated token must appear somewhere in the keywords —
    // so "purchase orders", "po", and "pos" all resolve to PO-related results.
    const tokens = term.split(/\s+/).filter(Boolean)
    return items
      .filter((i) => tokens.every((tk) => i.keywords.includes(tk)))
      .slice(0, 40)
  }, [q, items])

  const go = (i: Item) => {
    setOpen(false)
    setQ("")
    if (i.kind === "ticket") navigate({ to: "/tickets", search: { ticket: i.id } })
    else if (i.kind === "po") navigate({ to: "/order-tracker", search: { po: i.id } })
    else if (i.kind === "sop") navigate({ to: "/sops", search: { sop: i.code } })
    else if (i.kind === "machine") navigate({ to: "/factory-map", search: { machine: i.id } })
    // page (dynamic path from the nav model)
    // biome-ignore lint/suspicious/noExplicitAny: nav paths are validated route strings
    else navigate({ to: i.to } as any)
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex w-[min(40vw,360px)] items-center gap-2 rounded-lg border bg-card/60 px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent"
      >
        <Search size={15} />
        <span className="flex-1 text-left">Search the platform…</span>
        <kbd className="rounded border bg-muted px-1.5 py-0.5 text-[10px] font-medium">⌘K</kbd>
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="top-[18%] max-h-[70vh] w-[min(96vw,640px)] max-w-[640px] translate-y-0 gap-0 overflow-hidden p-0">
          <DialogTitle className="sr-only">Universal search</DialogTitle>
          <div className="flex items-center gap-2 border-b px-3">
            <Search size={16} className="text-muted-foreground" />
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search pages, machines, tickets, POs, SOPs…"
              className="w-full bg-transparent py-3 text-sm outline-none placeholder:text-muted-foreground"
            />
          </div>
          <ul className="max-h-[55vh] overflow-y-auto p-2">
            {filtered.length === 0 && (
              <li className="px-2 py-6 text-center text-sm text-muted-foreground">
                No matches.
              </li>
            )}
            {filtered.map((i, idx) => (
              <li key={`${i.kind}-${i.id ?? i.code ?? i.to ?? idx}`}>
                <button
                  type="button"
                  onClick={() => go(i)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-accent",
                  )}
                >
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-md border bg-card">
                    {KIND_ICON[i.kind]}
                  </span>
                  <span className="min-w-0 flex-1 truncate">{i.label}</span>
                  <span className="shrink-0 text-[11px] uppercase tracking-wide text-muted-foreground">
                    {i.sub}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </DialogContent>
      </Dialog>
    </>
  )
}
