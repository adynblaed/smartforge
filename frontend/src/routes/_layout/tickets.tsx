import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import {
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Clock,
  ExternalLink,
  Package,
  Ticket as TicketIcon,
  TriangleAlert,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { cn } from "@/lib/utils"
import useAuth from "@/hooks/useAuth"
import { sf } from "@/smartforge/api"
import { Loading, PageHeader, StatusBadge } from "@/smartforge/components"
import { POLL } from "@/smartforge/constants"
import type {
  Page,
  Ticket,
  TicketDetail,
  TicketLog,
  TicketReference,
} from "@/smartforge/types"

export const Route = createFileRoute("/_layout/tickets")({
  validateSearch: (search: Record<string, unknown>): { ticket?: string } => ({
    ticket: typeof search.ticket === "string" ? search.ticket : undefined,
  }),
  component: TicketsPage,
  head: () => ({ meta: [{ title: "Tickets - SmartForge" }] }),
})

const LOCAL_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone

function fmtTime(iso: string | null, tz?: string | null): string {
  if (!iso) return "—"
  const d = new Date(iso)
  try {
    const s = new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: tz || undefined,
    }).format(d)
    return tz ? `${s} (${tz})` : s
  } catch {
    return d.toLocaleString()
  }
}

const STATUS_STYLE: Record<string, string> = {
  open: "bg-sky-500/10 text-sky-400 border-sky-500/30",
  acknowledged: "bg-amber-500/10 text-amber-400 border-amber-500/30",
  in_progress: "bg-violet-500/10 text-violet-400 border-violet-500/30",
  resolved: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  closed: "bg-muted text-muted-foreground",
}

function StatusChip({ status }: { status: string }) {
  return (
    <Badge variant="outline" className={cn("capitalize", STATUS_STYLE[status])}>
      {status.replace("_", " ")}
    </Badge>
  )
}

const TABS = [
  { key: "open", label: "Open" },
  { key: "acknowledged", label: "Acknowledged" },
  { key: "in_progress", label: "In progress" },
  { key: "resolved", label: "Resolved" },
  { key: "all", label: "All" },
] as const

function TicketsPage() {
  const { ticket: ticketParam } = Route.useSearch()
  const [tab, setTab] = useState<string>("open")
  // The currently selected ticket — shown in the right detail pane.
  const [selected, setSelected] = useState<string | null>(ticketParam ?? null)

  // Deep-link: /tickets?ticket=<id|code> selects that ticket (e.g. from
  // Incidents). Switch to "All" so the row is visible regardless of status, and
  // scroll it into view once rendered.
  useEffect(() => {
    if (!ticketParam) return
    setSelected(ticketParam)
    setTab("all")
    const id = window.setTimeout(() => {
      document
        .querySelector(`[data-ticket="${ticketParam}"]`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" })
    }, 250)
    return () => window.clearTimeout(id)
  }, [ticketParam])

  const { data } = useQuery({
    queryKey: ["tickets"],
    queryFn: () => sf.get<Page<Ticket>>("/tickets/"),
    refetchInterval: POLL.medium,
  })

  const tickets = data?.data ?? []
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: tickets.length }
    for (const t of tickets) c[t.status] = (c[t.status] ?? 0) + 1
    return c
  }, [tickets])
  const visible =
    tab === "all" ? tickets : tickets.filter((t) => t.status === tab)
  const selectedTicket = tickets.find(
    (t) => t.id === selected || t.code === selected,
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        icon={<TicketIcon size={22} />}
        title="Maintenance Alert Center"
        description="Bonafide ticketing for maintenance alerts — serialized tickets, parts & inventory, SOP guidance, and an acknowledgement + note trail."
      />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          {TABS.map((t) => (
            <TabsTrigger key={t.key} value={t.key}>
              {t.label}
              <span className="ml-1.5 rounded bg-muted px-1.5 text-[11px] text-muted-foreground">
                {counts[t.key] ?? 0}
              </span>
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {/* master-detail: ticket list (left) + detail pane (right) */}
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <div>
          {!data ? (
            <Loading />
          ) : visible.length === 0 ? (
            <p className="py-12 text-center text-sm text-muted-foreground">No tickets.</p>
          ) : (
            <ul className="space-y-2">
              {visible.map((tk) => {
                const active = selected === tk.id || selected === tk.code
                return (
                  <li key={tk.id}>
                    <button
                      type="button"
                      data-ticket={active ? selected : undefined}
                      onClick={() => setSelected(tk.id)}
                      className={cn(
                        "flex w-full flex-wrap items-center gap-3 rounded-lg p-3 text-left transition-colors",
                        active ? "bg-accent" : "hover:bg-accent/50",
                      )}
                    >
                      <span className="font-mono text-xs text-muted-foreground">
                        {tk.code}
                      </span>
                      <StatusBadge value={tk.severity} />
                      <span className="min-w-0 flex-1 truncate text-sm font-medium">
                        {tk.title}
                      </span>
                      {tk.machine_code && (
                        <span className="hidden text-xs text-muted-foreground sm:inline">
                          {tk.machine_code}
                        </span>
                      )}
                      {tk.status === "acknowledged" && tk.acknowledged_by && (
                        <span className="hidden items-center gap-1 text-[11px] text-muted-foreground sm:flex">
                          <CheckCircle2 size={12} className="text-emerald-400" />
                          {tk.acknowledged_by}
                        </span>
                      )}
                      <StatusChip status={tk.status} />
                      <ChevronRight size={15} className="shrink-0 text-muted-foreground" />
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>

        {/* detail pane */}
        <div className="lg:sticky lg:top-20 lg:self-start">
          {selectedTicket ? (
            <div className="max-h-[calc(100vh-9rem)] overflow-y-auto rounded-lg bg-card p-4">
              <TicketDetailView id={selectedTicket.id} />
            </div>
          ) : (
            <div className="flex h-48 items-center justify-center rounded-lg bg-card text-sm text-muted-foreground">
              Select a ticket to view its details.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ---- @-mention helpers ---------------------------------------------------
function MentionText({
  text,
  refs,
}: {
  text: string
  refs: Map<string, TicketReference>
}) {
  const navigate = useNavigate()
  const parts = text.split(/(@[A-Za-z0-9-]+)/g)
  return (
    <span className="whitespace-pre-wrap break-words">
      {parts.map((p, i) => {
        if (p.startsWith("@")) {
          const code = p.slice(1)
          const ref = refs.get(code)
          if (ref) {
            const cls =
              "mx-0.5 rounded bg-primary/10 px-1 py-0.5 font-mono text-[11px] text-primary"
            if (ref.kind === "sop") {
              return (
                <button
                  type="button"
                  key={i}
                  className={cn(cls, "hover:underline")}
                  onClick={() => navigate({ to: "/sops", search: { sop: ref.code } })}
                >
                  @{ref.code}
                </button>
              )
            }
            return (
              <span key={i} className={cls} title={ref.title}>
                @{ref.code}
              </span>
            )
          }
        }
        return <span key={i}>{p}</span>
      })}
    </span>
  )
}

function MentionTextarea({
  value,
  onChange,
  references,
  placeholder,
}: {
  value: string
  onChange: (v: string) => void
  references: TicketReference[]
  placeholder?: string
}) {
  const ref = useRef<HTMLTextAreaElement>(null)
  const [query, setQuery] = useState<string | null>(null)

  const matches =
    query === null
      ? []
      : references
          .filter(
            (r) =>
              r.code.toLowerCase().includes(query.toLowerCase()) ||
              r.title.toLowerCase().includes(query.toLowerCase()),
          )
          .slice(0, 6)

  const handle = (v: string) => {
    onChange(v)
    const caret = ref.current?.selectionStart ?? v.length
    const before = v.slice(0, caret)
    const m = before.match(/@([\w-]*)$/)
    setQuery(m ? m[1] : null)
  }

  const insert = (code: string) => {
    const el = ref.current
    const caret = el?.selectionStart ?? value.length
    const before = value.slice(0, caret).replace(/@([\w-]*)$/, `@${code} `)
    const after = value.slice(caret)
    onChange(before + after)
    setQuery(null)
    requestAnimationFrame(() => el?.focus())
  }

  return (
    <div className="relative">
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => handle(e.target.value)}
        placeholder={placeholder}
        rows={3}
        className="w-full resize-y rounded-md border bg-muted/50 p-2 text-sm outline-none focus:ring-1 focus:ring-primary"
      />
      {matches.length > 0 && (
        <ul className="absolute z-50 mt-1 w-full overflow-hidden rounded-md border bg-popover shadow-lg">
          {matches.map((r) => (
            <li key={r.id}>
              <button
                type="button"
                onClick={() => insert(r.code)}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-accent"
              >
                <span className="rounded bg-muted px-1 py-0.5 font-mono text-[10px] uppercase text-muted-foreground">
                  {r.kind}
                </span>
                <span className="font-mono text-primary">@{r.code}</span>
                <span className="truncate text-muted-foreground">{r.title}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const AUDIENCES = [
  { key: "what_happened", label: "Overview" },
  { key: "executive_summary", label: "Risk" },
  { key: "operator_detail", label: "Operator" },
] as const

function TicketDetailView({ id }: { id: string }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [note, setNote] = useState("")
  const [ackNote, setAckNote] = useState("")

  const { data: t } = useQuery({
    queryKey: ["ticket", id],
    queryFn: () => sf.get<TicketDetail>(`/tickets/${id}`),
    refetchInterval: POLL.medium,
  })
  const { data: refList } = useQuery({
    queryKey: ["ticket-refs"],
    queryFn: () => sf.get<TicketReference[]>("/tickets/references"),
  })
  const refMap = useMemo(() => {
    const m = new Map<string, TicketReference>()
    for (const r of refList ?? []) m.set(r.code, r)
    return m
  }, [refList])

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["ticket", id] })
    qc.invalidateQueries({ queryKey: ["tickets"] })
  }
  const acknowledge = useMutation({
    mutationFn: () =>
      sf.post(`/tickets/${id}/acknowledge`, { note: ackNote, tz: LOCAL_TZ }),
    onSuccess: () => {
      setAckNote("")
      invalidate()
    },
  })
  const addNote = useMutation({
    mutationFn: () => sf.post(`/tickets/${id}/notes`, { message: note, tz: LOCAL_TZ }),
    onSuccess: () => {
      setNote("")
      invalidate()
    },
  })
  const setStatus = useMutation({
    mutationFn: (status: string) => sf.post(`/tickets/${id}/status`, { status }),
    onSuccess: invalidate,
  })

  if (!t) return <Loading />

  return (
      <div className="space-y-5">
        <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          {t.machine_code && (
            <span>
              Machine <b className="text-foreground">{t.machine_code}</b>
              {t.machine_name ? ` · ${t.machine_name}` : ""}
            </span>
          )}
          {t.incident_title &&
            (t.incident_id ? (
              <button
                type="button"
                onClick={() => navigate({ to: "/incidents" })}
                className="flex items-center gap-1 text-primary hover:underline"
              >
                <TriangleAlert size={12} /> {t.incident_title}
              </button>
            ) : (
              <span className="flex items-center gap-1">
                <TriangleAlert size={12} /> {t.incident_title}
              </span>
            ))}
          <span>Opened {fmtTime(t.created_at, LOCAL_TZ)}</span>
        </div>

        {/* Audience-aware explanation */}
        <div className="rounded-lg border p-3">
          <Tabs defaultValue="what_happened">
            <TabsList>
              {AUDIENCES.map((a) => (
                <TabsTrigger
                  key={a.key}
                  value={a.key}
                  className="dark:text-white data-[state=active]:!bg-white data-[state=active]:!text-black dark:data-[state=active]:!bg-white dark:data-[state=active]:!text-black"
                >
                  {a.label}
                </TabsTrigger>
              ))}
            </TabsList>
            {AUDIENCES.map((a) => (
              <TabsContent key={a.key} value={a.key} className="mt-3 text-sm">
                {t[a.key as keyof TicketDetail] as string}
              </TabsContent>
            ))}
          </Tabs>
          <div className="mt-3 rounded-md bg-muted/50 p-3 text-sm">
            <p className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
              Remediation
            </p>
            <MentionText text={t.remediation} refs={refMap} />
          </div>
          {t.sop_code && (
            <Button
              size="sm"
              variant="outline"
              className="mt-3 !bg-white !text-black hover:!bg-white/90"
              onClick={() =>
                navigate({
                  to: "/sops",
                  search: { sop: t.sop_code!, section: t.sop_anchor ?? undefined },
                })
              }
            >
              <BookOpen size={14} /> View {t.sop_code}
              {t.sop_anchor ? ` · ${t.sop_anchor.replace(/-/g, " ")}` : ""}
              <ExternalLink size={12} />
            </Button>
          )}
        </div>

        {/* Parts & materials */}
        <div className="rounded-lg border">
          <div className="flex items-center gap-2 border-b px-3 py-2 text-sm font-semibold">
            <Package size={15} /> Parts & Materials
          </div>
          <div className="divide-y">
            {t.parts.length === 0 && (
              <p className="px-3 py-3 text-xs text-muted-foreground">
                No parts listed for this ticket.
              </p>
            )}
            {t.parts.map((p) => (
              <div key={p.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2.5 text-sm">
                <span className="min-w-0 flex-1 font-medium">
                  {p.name}
                  {p.sku && (
                    <span className="ml-1 font-mono text-[11px] text-muted-foreground">
                      {p.sku}
                    </span>
                  )}
                </span>
                <span className="text-xs text-muted-foreground">
                  Need <b className="text-foreground">{p.qty_needed}</b> · On hand{" "}
                  <b className={cn("text-foreground", !p.in_stock && "text-rose-400")}>
                    {p.on_hand} {p.unit}
                  </b>
                </span>
                <span className="text-xs text-muted-foreground">
                  {p.supplier_name ?? "—"}
                  {p.supplier_status && p.supplier_status !== "ok" && (
                    <span className="ml-1 text-amber-400">({p.supplier_status})</span>
                  )}{" "}
                  · {p.lead_time_days}d lead
                </span>
                <span className="flex items-center gap-1 text-xs">
                  <Clock size={12} className="text-muted-foreground" />
                  order by{" "}
                  <b className="text-foreground">
                    {p.order_by ? new Date(p.order_by).toLocaleDateString() : "—"}
                  </b>
                </span>
                {p.in_stock ? (
                  <Badge
                    variant="outline"
                    className="border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                  >
                    In stock
                  </Badge>
                ) : (
                  <Badge
                    variant="outline"
                    className="border-rose-500/30 bg-rose-500/10 text-rose-400"
                  >
                    Reorder ({p.shortfall} short)
                  </Badge>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Acknowledgement */}
        <div className="rounded-lg border p-3">
          <p className="mb-2 text-sm font-semibold">Acknowledgement</p>
          {t.acknowledged_by ? (
            <div className="flex items-center gap-2 rounded-md bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
              <CheckCircle2 size={15} />
              <span>
                Acknowledged by <b>{t.acknowledged_by}</b> ·{" "}
                {fmtTime(t.acknowledged_at, t.acknowledged_tz)}
              </span>
            </div>
          ) : (
            <div className="space-y-2">
              <MentionTextarea
                value={ackNote}
                onChange={setAckNote}
                references={refList ?? []}
                placeholder="Optional note, e.g. “Need to order more of Part XYZ…” (type @ to reference an SOP or ticket)"
              />
              <Button
                size="sm"
                onClick={() => acknowledge.mutate()}
                disabled={acknowledge.isPending}
              >
                <CheckCircle2 size={14} /> Acknowledge as {user?.email}
              </Button>
            </div>
          )}
        </div>

        {/* Activity / notes timeline */}
        <div className="rounded-lg border p-3">
          <p className="mb-3 text-sm font-semibold">Activity & Notes</p>
          <ol className="space-y-3">
            {t.logs.map((log: TicketLog) => (
              <li key={log.id} className="flex gap-3 text-sm">
                <span
                  className={cn(
                    "mt-1.5 size-2 shrink-0 rounded-full",
                    log.kind === "acknowledgement"
                      ? "bg-emerald-400"
                      : log.kind === "note"
                        ? "bg-primary"
                        : log.kind === "status_change"
                          ? "bg-violet-400"
                          : "bg-amber-400",
                  )}
                />
                <div className="min-w-0 flex-1">
                  <MentionText text={log.message} refs={refMap} />
                  <p className="mt-0.5 text-[11px] text-muted-foreground">
                    {log.author_email ? `${log.author_email} · ` : "system · "}
                    {fmtTime(log.created_at, log.tz ?? LOCAL_TZ)}
                  </p>
                </div>
              </li>
            ))}
          </ol>

          <div className="mt-4 space-y-2 border-t pt-3">
            <MentionTextarea
              value={note}
              onChange={setNote}
              references={refList ?? []}
              placeholder="Add a note… type @ to reference an SOP, ticket or knowledge base"
            />
            <div className="flex items-center justify-between">
              <Button
                size="sm"
                variant="outline"
                onClick={() => addNote.mutate()}
                disabled={!note.trim() || addNote.isPending}
              >
                Add note
              </Button>
              <div className="flex gap-2">
                {t.status !== "in_progress" && t.status !== "resolved" && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="!bg-white !text-black hover:!bg-white/90"
                    onClick={() => setStatus.mutate("in_progress")}
                  >
                    Start work
                  </Button>
                )}
                {t.status !== "resolved" && t.status !== "closed" && (
                  <Button size="sm" onClick={() => setStatus.mutate("resolved")}>
                    Mark resolved
                  </Button>
                )}
                {t.status === "resolved" && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setStatus.mutate("closed")}
                  >
                    Close
                  </Button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
  )
}
