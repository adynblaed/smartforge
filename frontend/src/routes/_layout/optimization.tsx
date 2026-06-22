import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { LineChart, Pencil } from "lucide-react"
import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { sf } from "@/smartforge/api"
import { CapacityPlanner, type SimResult, SimulationStudio } from "@/smartforge/CapacitySim"
import { PageHeader, Panel, StatusBadge } from "@/smartforge/components"
import type {
  Machine,
  MachineConfiguration,
  Page,
  Recommendation,
} from "@/smartforge/types"

export const Route = createFileRoute("/_layout/optimization")({
  validateSearch: (
    s: Record<string, unknown>,
  ): { profile?: string; machine?: string } => ({
    profile: typeof s.profile === "string" ? s.profile : undefined,
    machine: typeof s.machine === "string" ? s.machine : undefined,
  }),
  component: OptimizationPage,
  head: () => ({ meta: [{ title: "Optimizations - SmartForge" }] }),
})

function OptimizationPage() {
  const { profile, machine } = Route.useSearch()
  const qc = useQueryClient()
  const { data: machines } = useQuery({
    queryKey: ["machines"],
    queryFn: () => sf.get<Page<Machine>>("/machines/"),
  })
  const { data: configs } = useQuery({
    queryKey: ["configs"],
    queryFn: () => sf.get<Page<MachineConfiguration>>("/machine-configurations"),
  })
  const { data: recs } = useQuery({
    queryKey: ["recommendations"],
    queryFn: () => sf.get<Page<Recommendation>>("/recommendations"),
  })

  const approve = useMutation({
    mutationFn: (id: string) =>
      sf.post(`/machine-configurations/${id}/approve`),
    onSettled: () => qc.invalidateQueries({ queryKey: ["configs"] }),
  })
  const decide = useMutation({
    mutationFn: ({ id, accept }: { id: string; accept: boolean }) =>
      sf.post(
        `/recommendations/${id}/decision?accept=${accept}${accept ? "&outcome_impact=5" : ""}`,
      ),
    onSettled: () => qc.invalidateQueries({ queryKey: ["recommendations"] }),
  })

  // What-If scheduling sim — triggered from the section header (top-right).
  const [sim, setSim] = useState<SimResult | null>(null)
  const runWhatIf = useMutation({
    mutationFn: () => sf.post<SimResult>("/planning/simulate"),
    onSuccess: setSim,
  })

  const nameOf = (id: string | null) =>
    machines?.data.find((m) => m.id === id)?.code ?? "—"

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Optimizations"
        description="Configuration tracking, continuous improvement, and scheduling & capacity simulation — approve a config and run it, all in one place."
        actions={
          // Pre-load the optimized profile into the on-page Simulation Studio.
          <Button asChild variant="outline">
            <Link to="/optimization" search={{ profile: "optimized" }}>
              <LineChart size={16} /> Run capacity simulation
            </Link>
          </Button>
        }
      />

      <Panel title="Configuration Optimization">
        <div className="space-y-6">
          {machines?.data.map((m) => (
            <MachineConfigRow
              key={m.id}
              machine={m}
              configs={configs?.data ?? []}
              onApprove={(id) => approve.mutate(id)}
              approving={approve.isPending}
            />
          ))}
        </div>
      </Panel>

      <Panel title="Continuous Improvement Feed">
        <ul className="divide-y">
          {recs?.data.map((r) => (
            <li key={r.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <StatusBadge value={r.status} />
                  <span className="text-sm font-medium">{r.title}</span>
                  <span className="text-xs text-muted-foreground">
                    {nameOf(r.machine_id)} · {Math.round(r.confidence * 100)}% conf
                  </span>
                </div>
                {r.detail && (
                  <p className="mt-1 text-xs text-muted-foreground">{r.detail}</p>
                )}
                {r.outcome_impact != null && (
                  <p className="mt-1 text-xs text-success">
                    Outcome impact: +{r.outcome_impact}%
                  </p>
                )}
              </div>
              {r.status === "pending" && (
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => decide.mutate({ id: r.id, accept: true })}>
                    Accept
                  </Button>
                  <Button size="sm" variant="outline"
                    onClick={() => decide.mutate({ id: r.id, accept: false })}>
                    Reject
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      </Panel>

      {/* Scenario planning branched out from configuration management. */}
      <div className="mt-2 flex flex-wrap items-start justify-between gap-3 border-t pt-6">
        <div>
          <h2 className="text-lg font-semibold">What If — Scenario Planning</h2>
          <p className="text-sm text-muted-foreground">
            Run profiled what-if scenarios across scheduling, capacity, and per-machine
            production runs.
          </p>
        </div>
        <Button onClick={() => runWhatIf.mutate()} disabled={runWhatIf.isPending}>
          {runWhatIf.isPending ? "Running…" : "Run what-if schedule"}
        </Button>
      </div>

      <Panel title="Scheduling & Capacity">
        <CapacityPlanner sim={sim} running={runWhatIf.isPending} />
      </Panel>

      <SimulationStudio profile={profile} focusMachine={machine} />
    </div>
  )
}

const EDIT_FIELDS = [
  { k: "speed", label: "Speed", weight: 0.55 },
  { k: "feed_rate", label: "Feed rate", weight: 0.25 },
  { k: "temperature", label: "Temp", weight: -0.3 },
  { k: "pressure", label: "Pressure", weight: -0.15 },
] as const

type EditKey = (typeof EDIT_FIELDS)[number]["k"]

function MachineConfigRow({
  machine,
  configs,
  onApprove,
  approving,
}: {
  machine: Machine
  configs: MachineConfiguration[]
  onApprove: (id: string) => void
  approving: boolean
}) {
  const mine = configs.filter((c) => c.machine_id === machine.id)
  const current = mine.find((c) => c.is_current)
  const recommended = mine.find((c) => c.is_recommended && !c.approved)
  const [editing, setEditing] = useState(false)

  return (
    <div className="rounded-lg border p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="font-medium">{machine.code}</span>
        {recommended && (
          <span className="text-sm text-success">
            +{recommended.performance_delta.toFixed(1)}% projected
          </span>
        )}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {editing ? (
          <ConfigEditor current={current} />
        ) : (
          <ConfigCard label="Current" cfg={current} />
        )}
        <ConfigCard label="Recommended" cfg={recommended} highlight />
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {recommended && (
          <Button size="sm" onClick={() => onApprove(recommended.id)} disabled={approving}>
            Approve recommended config
          </Button>
        )}
        <Button size="sm" variant="outline" onClick={() => setEditing((e) => !e)}>
          <Pencil size={14} /> {editing ? "Done editing" : "Edit Config"}
        </Button>
      </div>
    </div>
  )
}

// Inline what-if editor: edit current config values and preview the estimated
// per-stat change + projected performance impact (not persisted).
function ConfigEditor({ current }: { current?: MachineConfiguration }) {
  const [draft, setDraft] = useState<Record<EditKey, number>>({
    speed: 0,
    feed_rate: 0,
    temperature: 0,
    pressure: 0,
  })
  useEffect(() => {
    if (current)
      setDraft({
        speed: current.speed,
        feed_rate: current.feed_rate,
        temperature: current.temperature,
        pressure: current.pressure,
      })
  }, [current])

  if (!current) {
    return (
      <div className="rounded-md border p-3 text-xs text-muted-foreground">
        No current config to edit.
      </div>
    )
  }

  const pct = (k: EditKey) => {
    const cur = Number(current[k]) || 0
    return cur ? ((draft[k] - cur) / cur) * 100 : 0
  }
  const projected = EDIT_FIELDS.reduce((a, f) => a + pct(f.k) * f.weight, 0)

  return (
    <div className="rounded-md border border-primary/50 p-3 text-sm">
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className="uppercase tracking-wide text-muted-foreground">Edit current</span>
        <span className={projected >= 0 ? "text-success" : "text-danger"}>
          {projected >= 0 ? "+" : ""}
          {projected.toFixed(1)}% projected
        </span>
      </div>
      <div className="space-y-1.5">
        {EDIT_FIELDS.map((f) => {
          const change = pct(f.k)
          return (
            <div key={f.k} className="grid grid-cols-[1fr_84px_52px] items-center gap-2 text-xs">
              <span className="text-muted-foreground">{f.label}</span>
              <input
                type="number"
                step="any"
                value={draft[f.k]}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, [f.k]: Number(e.target.value) }))
                }
                className="w-full rounded border bg-muted/50 px-2 py-1 text-right tabular-nums outline-none focus:ring-1 focus:ring-primary"
              />
              <span
                className={cn(
                  "text-right tabular-nums",
                  change > 0 ? "text-success" : change < 0 ? "text-danger" : "text-muted-foreground",
                )}
              >
                {change > 0 ? "+" : ""}
                {change.toFixed(0)}%
              </span>
            </div>
          )
        })}
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">
        Estimated impact preview — edits are not saved.
      </p>
    </div>
  )
}

function ConfigCard({
  label,
  cfg,
  highlight,
}: {
  label: string
  cfg?: MachineConfiguration
  highlight?: boolean
}) {
  return (
    <div className={`rounded-md border p-3 text-sm ${highlight ? "border-primary/50" : ""}`}>
      <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      {cfg ? (
        <dl className="grid grid-cols-2 gap-1 text-xs">
          <Row k="Speed" v={cfg.speed} />
          <Row k="Temp" v={cfg.temperature} />
          <Row k="Pressure" v={cfg.pressure} />
          <Row k="Feed rate" v={cfg.feed_rate} />
          <Row k="Tooling" v={cfg.tooling_profile ?? "—"} />
          <Row k="Material" v={cfg.material_type ?? "—"} />
        </dl>
      ) : (
        <p className="text-xs text-muted-foreground">None</p>
      )}
    </div>
  )
}

function Row({ k, v }: { k: string; v: string | number }) {
  return (
    <>
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="text-right tabular-nums">{v}</dd>
    </>
  )
}
