import { Activity } from "lucide-react"

import { HEX } from "./components"

// Shared dashboard widgets used by the Factory Simulation panels and the
// Datasources global cards — kept in one place so they stay consistent.

const ECG_CYCLE: [number, number][] = [
  [0, 18],
  [28, 18],
  [33, 14],
  [37, 18],
  [46, 18],
  [49, 5],
  [52, 30],
  [55, 18],
  [63, 18],
  [68, 12],
  [73, 18],
  [100, 18],
]
// Two cycles so the scroll loop is seamless (animated via the `.sf-ecg` class).
export const ECG_POINTS = [
  ...ECG_CYCLE,
  ...ECG_CYCLE.map(([x, y]) => [x + 100, y] as [number, number]),
]
  .map(([x, y]) => `${x},${y}`)
  .join(" ")

/** Scrolling ECG "heartbeat" strip. Pass `label` to override the bpm readout. */
export function Heartbeat({
  color,
  bpm,
  label,
}: {
  color: string
  bpm: number
  label?: string
}) {
  const duration = Math.max(0.9, (60 / Math.max(30, bpm)) * 2.2)
  return (
    <div className="relative h-9 overflow-hidden rounded-md border border-border bg-black/70">
      {/* decorative — the bpm readout beside it carries the value */}
      <svg
        viewBox="0 0 200 36"
        preserveAspectRatio="none"
        aria-hidden="true"
        className="sf-ecg absolute inset-y-0 left-0 h-full w-[200%]"
        style={{ animationDuration: `${duration}s` }}
      >
        <polyline
          points={ECG_POINTS}
          fill="none"
          stroke={color}
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <span
        className="absolute right-1.5 top-0.5 flex items-center gap-1 text-[9px] font-semibold tabular-nums"
        style={{ color }}
      >
        <Activity size={9} /> {label ?? `${bpm} bpm`}
      </span>
    </div>
  )
}

export type GaugeUnit = "%" | "$" | "d" | ""

/** Semicircular gauge. Auto-colors by fill when no `color` is given. */
export function Gauge({
  value,
  max,
  label,
  color,
  suffix,
}: {
  value: number
  max: number
  label: string
  color?: string
  suffix?: GaugeUnit
}) {
  const v = Number.isFinite(value) ? value : 0
  const frac = Math.max(0, Math.min(1, max > 0 ? v / max : 0))
  const arc = Math.PI * 18
  const stroke =
    color ?? (frac > 0.66 ? HEX.success : frac > 0.33 ? HEX.info : HEX.warning)
  const display =
    suffix === "$"
      ? `$${Math.round(v).toLocaleString()}`
      : suffix === "%"
        ? `${Math.round(v)}%`
        : suffix === "d"
          ? `${Math.round(v)}d`
          : Math.round(v).toLocaleString()
  return (
    <div className="flex flex-col items-center rounded-md border bg-muted/30 p-1">
      <svg
        viewBox="0 0 48 28"
        className="w-full"
        role="img"
        aria-label={`${label}: ${display}`}
      >
        <path
          d="M6,24 A18,18 0 0 1 42,24"
          fill="none"
          className="stroke-muted"
          strokeWidth={4}
          strokeLinecap="round"
        />
        <path
          d="M6,24 A18,18 0 0 1 42,24"
          fill="none"
          stroke={stroke}
          strokeWidth={4}
          strokeLinecap="round"
          strokeDasharray={`${frac * arc} ${arc}`}
        />
        <text
          x="24"
          y="23"
          textAnchor="middle"
          className="fill-foreground"
          style={{ fontSize: 9, fontWeight: 700 }}
        >
          {display}
        </text>
      </svg>
      <span className="text-[8px] leading-none text-muted-foreground">
        {label}
      </span>
    </div>
  )
}
