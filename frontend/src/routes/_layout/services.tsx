import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Database, ScrollText } from "lucide-react"
import { useEffect, useState } from "react"

import { cn } from "@/lib/utils"
import { sf } from "@/smartforge/api"
import { Loading, PageHeader, Panel } from "@/smartforge/components"

export const Route = createFileRoute("/_layout/services")({
  component: ServicesPage,
  head: () => ({ meta: [{ title: "Services - Smart Forge" }] }),
})

interface Service {
  name: string
  category: string
  status: string
  detail: string
  configurable: boolean
  /** When set, this service streams to the Logs console under this key. */
  log_service?: string
}

// Map a service status to an up/degraded/down health bucket for the heartbeat.
type Beat = "up" | "degraded" | "down"
function beatOf(status: string): Beat {
  if (["running", "connected", "configured"].includes(status)) return "up"
  if (["offline", "disabled"].includes(status)) return "down"
  return "degraded" // mock / idle
}

const BEAT_BG: Record<Beat, string> = {
  up: "bg-emerald-500",
  degraded: "bg-amber-500",
  down: "bg-rose-500",
}
const STATUS_TEXT: Record<Beat, string> = {
  up: "text-emerald-400",
  degraded: "text-amber-400",
  down: "text-rose-400",
}

// Services whose datastore powers the Database Tables (Datasources) page.
const UPSTREAM_CATEGORIES = ["Datastore", "Cache & Pub/Sub", "RAG"]

const SLOTS = 40 // heartbeat ticker width
const POLL_MS = 4000

function ServicesPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["services"],
    queryFn: () => sf.get<{ data: Service[]; count: number }>("/services/"),
    refetchInterval: POLL_MS,
  })

  // Live, client-side uptime history: append each poll's status per service so
  // the heartbeat ticker + observed-uptime % reflect real observed availability.
  const [history, setHistory] = useState<Record<string, Beat[]>>({})
  useEffect(() => {
    if (!data) return
    setHistory((prev) => {
      const next = { ...prev }
      for (const svc of data.data) {
        const arr = next[svc.name] ? [...next[svc.name]] : []
        arr.push(beatOf(svc.status))
        next[svc.name] = arr.slice(-SLOTS)
      }
      return next
    })
  }, [data])

  const services = data?.data ?? []
  const healthy = services.filter((s) => beatOf(s.status) === "up").length

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Services"
        description="Live uptime + heartbeat for every plugin, process and integration wired into the platform."
        actions={
          services.length > 0 && (
            <div className="flex items-center gap-2 rounded-lg border bg-card px-3 py-1.5 text-sm">
              <span className="relative flex size-2.5">
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-500/60" />
                <span className="relative inline-flex size-2.5 rounded-full bg-emerald-500" />
              </span>
              <span className="font-semibold tabular-nums">
                {healthy}/{services.length}
              </span>
              <span className="text-muted-foreground">operational</span>
            </div>
          )
        }
      />

      <Panel title="Platform Services">
        {isLoading && <Loading label="Probing services…" />}
        <div className="grid gap-3 lg:grid-cols-2">
          {services.map((svc) => (
            <ServiceMonitor
              key={svc.name}
              svc={svc}
              beats={history[svc.name] ?? [beatOf(svc.status)]}
            />
          ))}
        </div>
        <p className="mt-4 text-xs text-muted-foreground">
          Status is probed live ({POLL_MS / 1000}s heartbeat). Uptime is
          observed over this session; connection settings are managed via
          environment configuration.
        </p>
      </Panel>
    </div>
  )
}

function ServiceMonitor({ svc, beats }: { svc: Service; beats: Beat[] }) {
  const beat = beatOf(svc.status)
  const up = beats.filter((b) => b === "up").length
  const uptime = beats.length ? (up / beats.length) * 100 : 0
  const isUpstream = UPSTREAM_CATEGORIES.includes(svc.category)
  // Pad the ticker so it reads as a fixed-width strip, oldest → newest.
  const padded: (Beat | null)[] = [
    ...Array(Math.max(0, SLOTS - beats.length)).fill(null),
    ...beats,
  ]

  return (
    <div className="flex flex-col gap-3 rounded-lg border bg-card p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-medium">{svc.name}</div>
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
            {svc.category}
          </div>
        </div>
        <span
          className={cn(
            "flex shrink-0 items-center gap-1.5 text-xs font-medium capitalize",
            STATUS_TEXT[beat],
          )}
        >
          <span className={cn("size-2 rounded-full", BEAT_BG[beat])} />
          {svc.status}
        </span>
      </div>

      {/* heartbeat ticker */}
      <div className="flex h-7 items-end gap-[2px]">
        {padded.map((b, i) => (
          <span
            key={i}
            className={cn(
              "flex-1 rounded-sm",
              b === null ? "h-2 bg-muted" : "h-full",
              b && BEAT_BG[b],
              b === null ? "opacity-40" : "opacity-90",
            )}
          />
        ))}
      </div>

      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{svc.detail}</span>
        <span className="shrink-0 font-semibold tabular-nums">
          {uptime.toFixed(1)}% uptime
        </span>
      </div>

      {(svc.log_service || isUpstream) && (
        <div className="flex flex-wrap items-center gap-3 border-t pt-2 text-xs">
          {svc.log_service && (
            <Link
              to="/logs"
              search={{ service: svc.log_service }}
              className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
            >
              <ScrollText size={12} /> View logs
            </Link>
          )}
          {isUpstream && (
            <Link
              to="/datasources"
              className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
            >
              <Database size={12} /> Powers Database Tables
            </Link>
          )}
        </div>
      )}
    </div>
  )
}
