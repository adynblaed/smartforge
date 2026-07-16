import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router"
import {
  Activity,
  Bot,
  Boxes,
  ChevronRight,
  ScrollText,
  Thermometer,
  Ticket,
  Zap,
} from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { cn } from "@/lib/utils"
import { sf } from "@/smartforge/api"
import { ChatPanel } from "@/smartforge/ChatPanel"
import {
  healthColor,
  healthHex,
  Loading,
  MiniArea,
  PageHeader,
  Panel,
  StatusBadge,
} from "@/smartforge/components"
import { POLL } from "@/smartforge/constants"
import {
  createForgeSession,
  deleteForgeSession,
  forgeSessionEmpty,
  forgeSessionKey,
} from "@/smartforge/forgeChat"
import { MachineMiniView } from "@/smartforge/MachineMiniView"
import type {
  Alert,
  AskResponse,
  Machine,
  Page,
  TelemetryEvent,
} from "@/smartforge/types"
import {
  type TelemetryTick,
  useTelemetryStream,
} from "@/smartforge/useRealtime"

export const Route = createFileRoute("/_layout/machines")({
  component: MachinesPage,
  head: () => ({ meta: [{ title: "Machines - SmartForge" }] }),
})

function MachinesPage() {
  const { ticks, connected } = useTelemetryStream()
  const { data: machines, isLoading } = useQuery({
    queryKey: ["machines"],
    queryFn: () => sf.get<Page<Machine>>("/machines/"),
    refetchInterval: connected ? POLL.slow : POLL.realtimeFallback,
  })

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Machine Health Console"
        description="Live telemetry, health scores, and AI troubleshooting."
        actions={
          connected ? (
            <span className="sf-pulse-soft text-xs font-medium text-success">
              ● live
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">○ polling</span>
          )
        }
      />

      {isLoading && <Loading label="Loading machines…" />}

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {machines?.data.map((m) => (
          <MachineCard
            key={m.id}
            machine={m}
            tick={ticks[m.id]}
            live={connected}
          />
        ))}
      </div>

      <Leaderboard machines={machines?.data ?? []} ticks={ticks} />
      <AlertCenter />
    </div>
  )
}

function Leaderboard({
  machines,
  ticks,
}: {
  machines: Machine[]
  ticks: Record<string, { health_score?: number }>
}) {
  const ranked = [...machines]
    .map((m) => ({ m, health: ticks[m.id]?.health_score ?? m.health_score }))
    .sort((a, b) => b.health - a.health)
  return (
    <Panel title="Machine Health Leaderboard">
      <ol className="space-y-1.5">
        {ranked.map(({ m, health }, i) => (
          <li key={m.id}>
            <Link
              to="/factory-map"
              search={{ machine: m.id }}
              className="flex items-center justify-between gap-3 rounded-lg border bg-card px-3 py-2 text-sm transition-colors hover:bg-accent"
            >
              <span className="flex min-w-0 items-center gap-3">
                <span
                  className={cn(
                    "flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-bold",
                    i === 0
                      ? "bg-amber-400/20 text-amber-400"
                      : i === 1
                        ? "bg-slate-300/20 text-slate-300"
                        : i === 2
                          ? "bg-orange-400/20 text-orange-400"
                          : "text-muted-foreground",
                  )}
                >
                  {i + 1}
                </span>
                <span className="font-medium">{m.code}</span>
                <span className="hidden truncate text-xs capitalize text-muted-foreground sm:inline">
                  {m.machine_type.replace("_", " ")}
                </span>
              </span>
              <span className="flex shrink-0 items-center gap-3">
                <span className="hidden text-xs text-muted-foreground md:inline">
                  downtime risk {Math.round(100 - health)}%
                </span>
                <span className="h-1.5 w-16 overflow-hidden rounded-full bg-muted sm:w-24">
                  <span
                    className="block h-full rounded-full"
                    style={{
                      width: `${Math.round(health)}%`,
                      background: healthHex(health),
                    }}
                  />
                </span>
                <span
                  className={cn(
                    "w-7 text-right font-semibold",
                    healthColor(health),
                  )}
                >
                  {Math.round(health)}
                </span>
                <ChevronRight size={15} className="text-muted-foreground" />
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </Panel>
  )
}

function MachineCard({
  machine: m,
  tick,
  live,
}: {
  machine: Machine
  tick?: TelemetryTick
  live: boolean
}) {
  const health = tick?.health_score ?? m.health_score
  const status = tick?.status ?? m.status
  const { data: telemetry } = useQuery({
    queryKey: ["telemetry", m.id],
    queryFn: () =>
      sf.get<Page<TelemetryEvent>>(`/machines/${m.id}/telemetry?limit=24`),
    refetchInterval: live ? POLL.medium : POLL.realtimeFallback,
  })
  // Oldest → newest for the sparkline (API returns newest first).
  const series = [...(telemetry?.data ?? [])]
    .reverse()
    .map((t) => ({ t: t.temperature }))
  // Fall back to the latest polled telemetry row when the WS tick is absent.
  const latest = telemetry?.data?.[0]
  const temp = tick?.temperature ?? latest?.temperature
  const vib = tick?.vibration ?? latest?.vibration

  return (
    <Panel title={m.code} action={<StatusBadge value={status} />}>
      <div className="space-y-3">
        <div className="h-40 overflow-hidden rounded-lg border bg-gradient-to-b from-muted/40 to-background">
          <MachineMiniView
            type={m.machine_type}
            running={status === "running"}
            accent={healthHex(health)}
          />
        </div>
        <div className="flex items-end justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{m.name}</p>
            <p className="text-xs capitalize text-muted-foreground">
              {m.machine_type.replace("_", " ")}
            </p>
          </div>
          <div className={`text-3xl font-semibold ${healthColor(health)}`}>
            {Math.round(health)}
          </div>
        </div>
        {series.length > 1 && (
          <div>
            <p className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
              Recent temperature
            </p>
            <MiniArea data={series} dataKey="t" color={healthHex(health)} />
          </div>
        )}
        <div className="grid grid-cols-3 gap-2 text-xs">
          <Metric
            icon={<Thermometer size={14} />}
            label="Temp"
            value={temp != null ? `${temp.toFixed(0)}°C` : "—"}
          />
          <Metric
            icon={<Activity size={14} />}
            label="Vib"
            value={vib != null ? vib.toFixed(2) : "—"}
          />
          <Metric
            icon={<Zap size={14} />}
            label="Runtime"
            value={`${m.runtime_hours.toFixed(0)}h`}
          />
        </div>
        <MachineTerminal
          code={m.code}
          rows={telemetry?.data ?? []}
          fault={m.last_fault_code}
        />
        <MachineAsk machine={m} />
        <div className="grid grid-cols-2 gap-2">
          <Button asChild variant="outline" size="sm">
            <Link to="/factory-map" search={{ machine: m.id }}>
              <Boxes size={16} /> Visit Simulation
            </Link>
          </Button>
          <Button asChild variant="outline" size="sm">
            <Link to="/sops" search={{ machine: m.code }}>
              <ScrollText size={16} /> View SOPs
            </Link>
          </Button>
        </div>
      </div>
    </Panel>
  )
}

// Per-machine console: a terminal that reports this machine's faults + recent
// telemetry as log lines (reuses the Logs console styling).
const TLEVEL: Record<string, string> = {
  INFO: "text-sky-400",
  WARN: "text-amber-400",
  ERROR: "text-rose-400",
}

function MachineTerminal({
  code,
  rows,
  fault,
}: {
  code: string
  rows: TelemetryEvent[]
  fault?: string | null
}) {
  const lines = [...rows]
    .slice(0, 24)
    .reverse()
    .map((t) => {
      const level = t.fault_code
        ? "ERROR"
        : t.vibration > 0.6 || t.temperature > 85
          ? "WARN"
          : "INFO"
      const msg = t.fault_code
        ? `fault ${t.fault_code} · temp ${t.temperature.toFixed(0)}°C · vib ${t.vibration.toFixed(2)}`
        : `nominal · temp ${t.temperature.toFixed(0)}°C · vib ${t.vibration.toFixed(2)}`
      return { ts: t.created_at, level, msg }
    })

  return (
    <div className="overflow-hidden rounded-md bg-[#0b0f17]">
      <div className="flex items-center gap-1.5 px-2 py-1 font-mono text-[10px] text-zinc-400">
        <span className="flex gap-1">
          <span className="size-1.5 rounded-full bg-rose-500/70" />
          <span className="size-1.5 rounded-full bg-amber-500/70" />
          <span className="size-1.5 rounded-full bg-emerald-500/70" />
        </span>
        <span className="ml-1">{code} · console</span>
        {fault && (
          <span className="ml-auto text-rose-400">● fault {fault}</span>
        )}
      </div>
      <div className="h-36 overflow-auto px-2 pb-2 font-mono text-[10px] leading-relaxed">
        {lines.length === 0 && (
          <p className="text-zinc-400/70">awaiting telemetry…</p>
        )}
        {lines.map((l, i) => (
          <div key={i} className="flex gap-1.5 whitespace-pre-wrap">
            <span className="shrink-0 text-zinc-400/60">
              {l.ts ? l.ts.slice(11, 19) : "--:--:--"}
            </span>
            <span className={cn("w-9 shrink-0 font-semibold", TLEVEL[l.level])}>
              {l.level}
            </span>
            <span className="text-zinc-100/85">{l.msg}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function Metric({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode
  label: string
  value: string
}) {
  return (
    <div className="rounded-md border p-2">
      <div className="flex items-center gap-1 text-muted-foreground">
        {icon}
        {label}
      </div>
      <div className="mt-1 font-medium tabular-nums">{value}</div>
    </div>
  )
}

// Readable MM/DD/YYYY stamp for the machine chat title.
function dateStamp(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0")
  return `${p(d.getMonth() + 1)}/${p(d.getDate())}/${d.getFullYear()}`
}

function MachineAsk({ machine }: { machine: Machine }) {
  const [open, setOpen] = useState(false)
  // A shared ForgeAI session created for this machine chat — named + dated so it
  // can be resumed/continued from the ForgeAI page. Created when the dialog opens;
  // discarded on close if nothing was asked.
  const [sessionId, setSessionId] = useState<string | null>(null)

  const handleOpenChange = (next: boolean) => {
    if (next) {
      setSessionId(
        createForgeSession(`${dateStamp(new Date())} - ${machine.name} Chat`),
      )
    } else if (sessionId) {
      if (forgeSessionEmpty(sessionId)) deleteForgeSession(sessionId)
      setSessionId(null)
    }
    setOpen(next)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="w-full">
          <Bot size={16} /> Ask ForgeAI About {machine.code}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>ForgeAI — {machine.name}</DialogTitle>
        </DialogHeader>
        <div className="h-[480px]">
          {sessionId && (
            <ChatPanel
              key={sessionId}
              placeholder={`Ask about ${machine.code}…`}
              suggestions={[
                "Why is the health score dropping?",
                "What does the current fault code mean?",
                "When should this machine be serviced?",
              ]}
              ask={(q) =>
                sf.post<AskResponse>(`/machines/${machine.id}/ask`, {
                  question: q,
                })
              }
              persistKey={forgeSessionKey(sessionId)}
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function AlertCenter() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { data } = useQuery({
    queryKey: ["alerts"],
    queryFn: () => sf.get<Page<Alert>>("/alerts/?status=active"),
    refetchInterval: POLL.fast,
  })
  // "Clear" resolves the alert (drops it from the active queue).
  const clear = useMutation({
    mutationFn: (id: string) => sf.post(`/alerts/${id}/resolve`),
    onSettled: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  })
  // "Ticket" generates a full serialized maintenance ticket from the alert and
  // opens it in the ticketing center.
  const ticket = useMutation({
    mutationFn: (id: string) =>
      sf.post<{ id: string }>(`/tickets/from-alert/${id}`),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["alerts"] })
      qc.invalidateQueries({ queryKey: ["tickets"] })
      navigate({ to: "/tickets", search: { ticket: res.id } })
    },
  })

  return (
    <Panel
      title="Maintenance Alert Center"
      action={
        <Link
          to="/tickets"
          className="text-xs font-medium text-primary hover:underline"
        >
          Open ticketing center →
        </Link>
      }
    >
      <ul className="divide-y">
        {data?.data.length === 0 && (
          <li className="py-3 text-sm text-muted-foreground">
            No active alerts.
          </li>
        )}
        {data?.data.map((a) => (
          <li
            key={a.id}
            className="flex flex-wrap items-center justify-between gap-3 py-3"
          >
            {/* Clicking the alert (not the action buttons) jumps to its source
                machine in the Factory Simulation. */}
            <button
              type="button"
              onClick={() =>
                navigate({
                  to: "/factory-map",
                  search: { machine: a.machine_id },
                })
              }
              aria-label={`Go to the source machine for alert: ${a.message}`}
              className="group -mx-2 flex min-w-0 flex-1 items-start gap-2 rounded-md px-2 py-1 text-left transition-colors hover:bg-accent"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <StatusBadge value={a.severity} />
                  <span className="text-sm font-medium">{a.message}</span>
                </div>
                {a.recommended_action && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    → {a.recommended_action}{" "}
                    {a.suggested_window && <em>({a.suggested_window})</em>}
                  </p>
                )}
              </div>
              <ChevronRight
                size={15}
                className="mt-0.5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5"
              />
            </button>
            <div className="flex gap-2">
              <Button
                size="sm"
                disabled={ticket.isPending}
                onClick={() => ticket.mutate(a.id)}
              >
                <Ticket size={14} /> Ticket
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={clear.isPending}
                onClick={() => clear.mutate(a.id)}
              >
                Clear
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  )
}
