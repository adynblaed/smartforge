// Visual EDA over the rows the Work Orders explorer already fetched from
// the certified work_orders contract (v1): preset views everyone reads
// the same way (status mix, machine load, cost Pareto, due timeline…) plus
// free-form chart building. Aggregation is client-side over the governed,
// capped result set — the charts never take a separate data path.
//
// The chart view (preset + spec) is CONTROLLED by the parent so switching
// between the Table and Charts tabs (which unmounts this component)
// restores the exact same chart on return.

import {
  ChartColumn,
  ChartColumnBig,
  ChartLine,
  ChartPie,
  ChartScatter,
  Grid3x3,
  type LucideIcon,
  SquareActivity,
} from "lucide-react"
import { useMemo } from "react"

import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  buildChart,
  CHART_KINDS,
  type ChartKind,
  EDA_DIMENSIONS,
  EDA_NUMERIC_FIELDS,
  EDA_PRESETS,
  type EdaSpec,
} from "@/smartforge/eda"
import { PlotlyChart, useChartTheme } from "@/smartforge/PlotlyChart"
import type { ApiWorkOrderRow } from "@/smartforge/platformTypes"

const NONE = "__none__"

/** The persisted chart view: active preset key ("" = free-form) + spec. */
export interface ChartView {
  preset: string
  spec: EdaSpec
}

export const DEFAULT_CHART_VIEW: ChartView = {
  preset: EDA_PRESETS[0].key,
  spec: EDA_PRESETS[0].spec,
}

/** Icon per chart form — the clickable style gallery under the presets. */
const KIND_ICONS: Record<ChartKind, LucideIcon> = {
  bar: ChartColumnBig,
  line: ChartLine,
  scatter: ChartScatter,
  histogram: ChartColumn,
  box: SquareActivity,
  donut: ChartPie,
  heatmap: Grid3x3,
}

/** Measure choice serialized into one select: count | sum:field | avg:field. */
const measureValue = (spec: EdaSpec): string =>
  spec.agg === "count" ? "count" : `${spec.agg}:${spec.num}`

const applyMeasure = (spec: EdaSpec, value: string): EdaSpec => {
  if (value === "count") return { ...spec, agg: "count", num: "" }
  const [agg, num] = value.split(":")
  return { ...spec, agg: agg as EdaSpec["agg"], num }
}

function FieldSelect({
  label,
  value,
  onChange,
  options,
  allowNone,
  width = "w-40",
}: {
  label: string
  value: string
  onChange: (value: string) => void
  options: { key: string; label: string }[]
  allowNone?: boolean
  width?: string
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <Select
        value={value === "" ? (allowNone ? NONE : "") : value}
        onValueChange={(v) => onChange(v === NONE ? "" : v)}
      >
        <SelectTrigger size="sm" className={width}>
          <SelectValue placeholder={label} />
        </SelectTrigger>
        <SelectContent>
          {allowNone && <SelectItem value={NONE}>none</SelectItem>}
          {options.map((o) => (
            <SelectItem key={o.key} value={o.key}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

export function WorkOrderCharts({
  rows,
  view,
  onViewChange,
}: {
  rows: ApiWorkOrderRow[]
  view: ChartView
  onViewChange: (view: ChartView) => void
}) {
  const { preset, spec } = view
  const theme = useChartTheme()

  const set = (patch: Partial<EdaSpec>) =>
    onViewChange({ preset: "", spec: { ...spec, ...patch } })

  const setKind = (kind: ChartKind) => {
    // Carry compatible choices; seed the rest so each kind starts sensible.
    const next: EdaSpec = { ...spec, kind }
    const dims = EDA_DIMENSIONS.filter((d) => d.kind === "category")
    const dates = EDA_DIMENSIONS.filter((d) => d.kind === "date")
    if (kind === "line" && !dates.some((d) => d.key === next.dim))
      next.dim = "due_at"
    if (
      (kind === "bar" || kind === "donut" || kind === "heatmap") &&
      !dims.some((d) => d.key === next.dim)
    )
      next.dim = "status"
    if (kind === "heatmap" && (!next.dim2 || next.dim2 === next.dim))
      next.dim2 = next.dim === "machine_code" ? "status" : "machine_code"
    if ((kind === "histogram" || kind === "box") && !next.num)
      next.num = "cost_total"
    if (kind === "scatter") {
      if (!next.num) next.num = "qty_ordered"
      if (!next.num2) next.num2 = "qty_completed"
    }
    onViewChange({ preset: "", spec: next })
  }

  const applyPreset = (key: string) => {
    const p = EDA_PRESETS.find((x) => x.key === key)
    if (!p) return
    onViewChange({ preset: key, spec: p.spec })
  }

  const built = useMemo(
    () => buildChart(rows, spec, theme.palette, theme.mode),
    [rows, spec, theme.palette, theme.mode],
  )

  const categoryDims = EDA_DIMENSIONS.filter((d) => d.kind === "category")
  const dateDims = EDA_DIMENSIONS.filter((d) => d.kind === "date")
  const measureOptions = [
    { key: "count", label: "Count of orders" },
    ...EDA_NUMERIC_FIELDS.flatMap((f) => [
      { key: `sum:${f.key}`, label: `Sum of ${f.label.toLowerCase()}` },
      { key: `avg:${f.key}`, label: `Avg of ${f.label.toLowerCase()}` },
    ]),
  ]

  const activePreset = EDA_PRESETS.find((p) => p.key === preset)

  return (
    <div className="flex flex-col gap-3">
      {/* preset gallery — the shared vocabulary across departments */}
      <div className="flex flex-wrap items-center gap-1.5">
        {EDA_PRESETS.map((p) => (
          <Button
            key={p.key}
            size="sm"
            variant={preset === p.key ? "default" : "outline"}
            className="h-7 px-2.5 text-xs"
            title={p.hint}
            onClick={() => applyPreset(p.key)}
          >
            {p.label}
          </Button>
        ))}
      </div>

      {/* chart-style gallery — click to swap the visual form; the series
          palette and value formats stay consistent across every form */}
      <div className="flex flex-wrap items-center gap-1.5 rounded-lg border bg-muted/30 p-1.5">
        {CHART_KINDS.map((k) => {
          const Icon = KIND_ICONS[k.value]
          const active = spec.kind === k.value
          return (
            <Button
              key={k.value}
              size="sm"
              variant={active ? "default" : "ghost"}
              className="h-8 gap-1.5 px-2.5 text-xs"
              aria-pressed={active}
              title={`Switch to ${k.label.toLowerCase()} chart`}
              onClick={() => setKind(k.value)}
            >
              <Icon className="size-3.5" />
              {k.label}
            </Button>
          )
        })}
      </div>

      {/* free-form controls, adapting to the chart form */}
      <div className="flex flex-wrap items-center gap-3">
        {(spec.kind === "bar" || spec.kind === "donut") && (
          <FieldSelect
            label={spec.kind === "donut" ? "slice by" : "x axis"}
            value={spec.dim}
            onChange={(v) => set({ dim: v })}
            options={spec.kind === "donut" ? categoryDims : EDA_DIMENSIONS}
          />
        )}
        {spec.kind === "line" && (
          <FieldSelect
            label="x axis"
            value={spec.dim}
            onChange={(v) => set({ dim: v })}
            options={dateDims}
          />
        )}
        {spec.kind === "heatmap" && (
          <>
            <FieldSelect
              label="x axis"
              value={spec.dim}
              onChange={(v) => set({ dim: v })}
              options={categoryDims}
            />
            <FieldSelect
              label="y axis"
              value={spec.dim2}
              onChange={(v) => set({ dim2: v })}
              options={categoryDims.filter((d) => d.key !== spec.dim)}
            />
          </>
        )}
        {(spec.kind === "bar" ||
          spec.kind === "line" ||
          spec.kind === "donut" ||
          spec.kind === "heatmap") && (
          <FieldSelect
            label="measure"
            value={measureValue(spec)}
            onChange={(v) =>
              onViewChange({ preset: "", spec: applyMeasure(spec, v) })
            }
            options={measureOptions}
            width="w-48"
          />
        )}
        {(spec.kind === "bar" || spec.kind === "line") && (
          <FieldSelect
            label="split by"
            value={spec.dim2}
            onChange={(v) => set({ dim2: v })}
            options={categoryDims.filter((d) => d.key !== spec.dim)}
            allowNone
          />
        )}
        {spec.kind === "scatter" && (
          <>
            <FieldSelect
              label="x axis"
              value={spec.num}
              onChange={(v) => set({ num: v })}
              options={EDA_NUMERIC_FIELDS}
            />
            <FieldSelect
              label="y axis"
              value={spec.num2}
              onChange={(v) => set({ num2: v })}
              options={EDA_NUMERIC_FIELDS.filter((f) => f.key !== spec.num)}
            />
            <FieldSelect
              label="color by"
              value={spec.dim2}
              onChange={(v) => set({ dim2: v })}
              options={categoryDims}
              allowNone
            />
          </>
        )}
        {(spec.kind === "histogram" || spec.kind === "box") && (
          <FieldSelect
            label="values"
            value={spec.num}
            onChange={(v) => set({ num: v })}
            options={EDA_NUMERIC_FIELDS}
          />
        )}
        {spec.kind === "box" && (
          <FieldSelect
            label="group by"
            value={spec.dim}
            onChange={(v) => set({ dim: v })}
            options={categoryDims}
            allowNone
          />
        )}
      </div>

      {built.ready ? (
        <PlotlyChart
          traces={built.traces}
          layout={built.layout}
          height={400}
          ariaLabel={
            activePreset
              ? `${activePreset.label} chart — ${activePreset.hint}`
              : `${spec.kind} chart of the filtered work orders`
          }
        />
      ) : (
        <div className="flex flex-col items-center gap-1.5 rounded-lg border border-dashed px-4 py-14 text-center">
          <ChartColumn size={20} className="text-muted-foreground" />
          <p className="text-sm text-muted-foreground">{built.reason}</p>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        {activePreset ? `${activePreset.label} — ${activePreset.hint}. ` : ""}
        Charts aggregate the {rows.length.toLocaleString()} rows matching the
        filters above (server-capped); exact values stay one tab away in the
        table view.
      </p>
    </div>
  )
}
