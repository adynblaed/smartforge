import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Terminal } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { cn } from "@/lib/utils"
import { sf } from "@/smartforge/api"
import { POLL } from "@/smartforge/constants"
import { Loading, PageHeader } from "@/smartforge/components"

export const Route = createFileRoute("/_layout/logs")({
  validateSearch: (search: Record<string, unknown>): { service?: string } => ({
    service: typeof search.service === "string" ? search.service : undefined,
  }),
  component: LogsPage,
  head: () => ({ meta: [{ title: "Logs - Smart Forge" }] }),
})

interface LogLine {
  ts: string
  level: string
  message: string
}

// The console always sits on a dark (#0b0f17) surface, so its text uses fixed
// light colors (zinc) in EVERY theme — theme tokens turn dark in light mode and
// would be unreadable here. These match the dark-mode appearance.
const LEVEL_STYLE: Record<string, string> = {
  INFO: "text-sky-400",
  WARN: "text-amber-400",
  ERROR: "text-rose-400",
  DEBUG: "text-zinc-400",
}

function LogsPage() {
  const { service: initialService } = Route.useSearch()
  const { data: services } = useQuery({
    queryKey: ["log-services"],
    queryFn: () => sf.get<{ data: string[]; count: number }>("/logs/services"),
  })
  const [service, setService] = useState<string | null>(initialService ?? null)
  const active = service ?? services?.data[0] ?? null

  const { data: logs } = useQuery({
    queryKey: ["logs", active],
    queryFn: () => sf.get<{ service: string; data: LogLine[] }>(`/logs/${active}`),
    enabled: !!active,
    refetchInterval: POLL.medium,
  })

  // Auto-scroll the console to the newest line.
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" })
  }, [logs])

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        icon={<Terminal size={20} />}
        title="Logs"
        description="Per-service troubleshooting console — a bounded window of recent log lines, not a live event firehose."
      />

      <div className="grid gap-4 lg:grid-cols-[200px_minmax(0,1fr)]">
        {/* services / processes */}
        <aside className="space-y-1">
          {!services && <Loading />}
          {services?.data.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setService(s)}
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-accent",
                s === active ? "bg-accent font-medium" : "text-muted-foreground",
              )}
            >
              <span
                className={cn(
                  "size-2 rounded-full",
                  s === active ? "bg-emerald-400" : "bg-muted-foreground/40",
                )}
              />
              {s}
            </button>
          ))}
        </aside>

        {/* terminal console */}
        <div className="overflow-hidden rounded-lg border bg-[#0b0f17]">
          <div className="flex items-center gap-2 border-b border-border px-3 py-2 font-mono text-xs text-zinc-400">
            <span className="flex gap-1.5">
              <span className="size-2.5 rounded-full bg-rose-500/70" />
              <span className="size-2.5 rounded-full bg-amber-500/70" />
              <span className="size-2.5 rounded-full bg-emerald-500/70" />
            </span>
            <span className="ml-2">{active ? `${active} · journald` : "—"}</span>
          </div>
          <div className="h-[60vh] overflow-auto p-3 font-mono text-xs leading-relaxed">
            {logs?.data.map((l, i) => (
              <div key={i} className="flex gap-2 whitespace-pre-wrap">
                <span className="shrink-0 text-zinc-400/70">
                  {l.ts.slice(11, 19)}
                </span>
                <span className={cn("w-12 shrink-0 font-semibold", LEVEL_STYLE[l.level])}>
                  {l.level}
                </span>
                <span className="text-zinc-100/90">{l.message}</span>
              </div>
            ))}
            {logs?.data.length === 0 && (
              <p className="text-zinc-400">No recent log lines.</p>
            )}
            <div ref={endRef} />
          </div>
        </div>
      </div>
    </div>
  )
}
