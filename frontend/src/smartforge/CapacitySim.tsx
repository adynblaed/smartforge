import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { sf } from "./api"
import { BarTrend, KpiTile, Panel, healthHex, makeTrendSeries, metricTrend } from "./components"
import type { Machine, Page } from "./types"

// Routable KPI tile wrapper + 24h trend helper.
const STAT_CLS =
  "block rounded-xl outline-none transition hover:brightness-110 focus-visible:ring-2 focus-visible:ring-ring"
const trend = (seed: string, good: "up" | "down" = "up") => {
  const t = makeTrendSeries(seed, good)
  return { trend: t.data, trendColor: t.color }
}

// Scheduling & capacity planning + a per-machine run simulator. Lives here so the
// whole flow (approve a config → simulate runs) sits on one Optimizations page.

interface Capacity {
  total_machines: number
  available: number
  in_maintenance: number
  maintenance_windows: { machine: string; state: string }[]
}
export interface SimResult {
  proposed_schedule: {
    job: string
    quantity: number
    assigned_machine: string | null
    priority: number
  }[]
  capacity_units: number
  demand_units: number
  capacity_conflicts: string[]
  load_balancing: string
}

const BASE_CYCLE: Record<string, number> = {
  cnc_mill: 45,
  robotic_arm: 30,
  hydraulic_press: 20,
}
const PROFILES = {
  baseline: { label: "Baseline", speed: 1.0, availability: 88 },
  optimized: { label: "Optimized", speed: 1.25, availability: 95 },
  aggressive: { label: "Aggressive", speed: 1.35, availability: 92 },
} as const

function projectRun(m: Machine, speed: number, availability: number, shiftHours: number) {
  const cycle = (BASE_CYCLE[m.machine_type] ?? 40) / speed
  const healthF = Math.max(0.5, m.health_score / 100)
  const avail = availability / 100
  const performance = Math.min(1, 0.78 * speed)
  const quality = Math.max(0.7, 0.99 - Math.max(0, speed - 1) * 0.4) * healthF
  const theoretical = (shiftHours * 3600) / cycle
  const units = Math.round(theoretical * avail * quality)
  const oee = avail * performance * quality * 100
  return { units, oee, cycle }
}

function Slider({
  label,
  value,
  min,
  max,
  step,
  display,
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  step: number
  display: string
  onChange: (v: number) => void
}) {
  return (
    <div className="rounded-md border p-3">
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-semibold tabular-nums">{display}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-primary"
      />
    </div>
  )
}

export function SimulationStudio({
  profile,
  focusMachine,
}: {
  profile?: string
  focusMachine?: string
}) {
  const preset =
    PROFILES[(profile as keyof typeof PROFILES) ?? "baseline"] ?? PROFILES.baseline
  const [speed, setSpeed] = useState<number>(preset.speed)
  const [availability, setAvailability] = useState<number>(preset.availability)
  const [shiftHours, setShiftHours] = useState<number>(16)

  const { data } = useQuery({
    queryKey: ["machines"],
    queryFn: () => sf.get<Page<Machine>>("/machines/"),
  })
  const machines = data?.data ?? []
  const rows = useMemo(
    () => machines.map((m) => ({ m, ...projectRun(m, speed, availability, shiftHours) })),
    [machines, speed, availability, shiftHours],
  )
  const totalUnits = rows.reduce((a, r) => a + r.units, 0)
  const avgOee = rows.length ? rows.reduce((a, r) => a + r.oee, 0) / rows.length : 0
  const bottleneck = rows.reduce<(typeof rows)[number] | null>(
    (min, r) => (min === null || r.oee < min.oee ? r : min),
    null,
  )
  const chart = rows.map((r) => ({ name: r.m.code, units: r.units }))

  const applyPreset = (p: { speed: number; availability: number }) => {
    setSpeed(p.speed)
    setAvailability(p.availability)
  }

  return (
    <Panel
      title="Simulation Studio — per-machine run projection"
      action={
        <div className="flex gap-1">
          {Object.entries(PROFILES).map(([k, p]) => (
            <Button
              key={k}
              size="sm"
              variant={
                speed === p.speed && availability === p.availability ? "default" : "outline"
              }
              className="h-7 text-[11px]"
              onClick={() => applyPreset(p)}
            >
              {p.label}
            </Button>
          ))}
        </div>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-3">
          <Slider label="Line speed" value={speed} min={0.8} max={1.4} step={0.05}
            display={`${speed.toFixed(2)}×`} onChange={setSpeed} />
          <Slider label="Availability" value={availability} min={70} max={100} step={1}
            display={`${availability}%`} onChange={setAvailability} />
          <Slider label="Shift hours" value={shiftHours} min={8} max={24} step={8}
            display={`${shiftHours}h`} onChange={setShiftHours} />
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <Link to="/analytics" className={STAT_CLS}>
            <KpiTile label="Projected units / run" value={totalUnits.toLocaleString()} {...trend("opt-units", "up")} />
          </Link>
          <Link to="/analytics" className={STAT_CLS}>
            <KpiTile label="Avg OEE" value={`${avgOee.toFixed(1)}%`}
              accent={avgOee >= 80 ? "var(--success)" : avgOee >= 65 ? "var(--warning)" : "var(--danger)"}
              {...metricTrend("oee")} />
          </Link>
          <Link to="/machines" className={STAT_CLS}>
            <KpiTile label="Bottleneck" value={bottleneck?.m.code ?? "—"} accent="var(--warning)" {...trend("opt-bottleneck", "down")} />
          </Link>
        </div>

        {chart.length > 0 && <BarTrend data={chart} dataKey="units" xKey="name" />}

        <table className="w-full text-sm">
          <thead className="text-left text-muted-foreground">
            <tr className="border-b">
              <th className="py-2 pr-4">Machine</th>
              <th className="py-2 pr-4">Cycle (s)</th>
              <th className="py-2 pr-4">Projected units</th>
              <th className="py-2 pr-4">OEE</th>
              <th className="py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.m.id}
                className={cn(
                  "border-b",
                  r.m.id === focusMachine && "bg-primary/5",
                  bottleneck?.m.id === r.m.id && "bg-warning/5",
                )}
              >
                <td className="py-2 pr-4 font-medium">
                  {r.m.code}
                  <span className="ml-2 text-xs capitalize text-muted-foreground">
                    {r.m.machine_type.replace("_", " ")}
                  </span>
                </td>
                <td className="py-2 pr-4 tabular-nums">{r.cycle.toFixed(1)}</td>
                <td className="py-2 pr-4 tabular-nums">{r.units.toLocaleString()}</td>
                <td className="py-2 pr-4 font-semibold tabular-nums" style={{ color: healthHex(r.oee) }}>
                  {r.oee.toFixed(1)}%
                </td>
                <td className="py-2 text-xs">
                  {bottleneck?.m.id === r.m.id ? (
                    <span className="text-warning">Bottleneck</span>
                  ) : r.oee >= 80 ? (
                    <span className="text-success">On target</span>
                  ) : (
                    <span className="text-muted-foreground">Sub-target</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-xs text-muted-foreground">
          Preview model — projects each machine's run from line speed, availability,
          shift length and live health. Pick a profile or use “Simulate run” on a
          recommended configuration above.
        </p>
      </div>
    </Panel>
  )
}

// Controlled by the Optimizations page: the "Run what-if schedule" action lives
// in the section header (top-right); this renders the capacity snapshot + result.
export function CapacityPlanner({
  sim,
  running,
}: {
  sim: SimResult | null
  running: boolean
}) {
  const { data: cap } = useQuery({
    queryKey: ["capacity"],
    queryFn: () => sf.get<Capacity>("/planning/capacity"),
  })

  return (
    <div className="flex flex-col gap-6">
      <div className="mx-auto grid w-full max-w-3xl gap-4 sm:grid-cols-3">
        <Link to="/machines" className={STAT_CLS}>
          <KpiTile label="Machines" value={cap?.total_machines ?? 0} {...trend("cap-machines", "up")} />
        </Link>
        <Link to="/machines" className={STAT_CLS}>
          <KpiTile label="Available" value={cap?.available ?? 0} accent="var(--success)" {...trend("cap-available", "up")} />
        </Link>
        <Link to="/machines" className={STAT_CLS}>
          <KpiTile label="In Maintenance" value={cap?.in_maintenance ?? 0} accent="var(--warning)" {...trend("cap-maint", "down")} />
        </Link>
      </div>

      {running && (
        <p className="text-center text-sm text-muted-foreground">
          Running what-if schedule…
        </p>
      )}

      {sim && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <KpiTile label="Capacity (units)" value={sim.capacity_units} />
            <KpiTile
              label="Demand (units)"
              value={sim.demand_units}
              accent={sim.demand_units > sim.capacity_units ? "var(--danger)" : undefined}
            />
          </div>
          {sim.capacity_conflicts.length > 0 && (
            <Panel title="Capacity Conflicts">
              <ul className="list-disc pl-5 text-sm text-danger">
                {sim.capacity_conflicts.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </Panel>
          )}
          <Panel title="Proposed Schedule">
            <table className="w-full text-sm">
              <thead className="text-left text-muted-foreground">
                <tr className="border-b">
                  <th className="py-2 pr-4">Job</th>
                  <th className="py-2 pr-4">Qty</th>
                  <th className="py-2 pr-4">Machine</th>
                  <th className="py-2">Priority</th>
                </tr>
              </thead>
              <tbody>
                {sim.proposed_schedule.map((p, i) => (
                  <tr key={i} className="border-b">
                    <td className="py-2 pr-4">{p.job}</td>
                    <td className="py-2 pr-4">{p.quantity}</td>
                    <td className="py-2 pr-4">{p.assigned_machine ?? "—"}</td>
                    <td className="py-2">P{p.priority}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-3 text-xs text-muted-foreground">{sim.load_balancing}</p>
          </Panel>
        </>
      )}
    </div>
  )
}
