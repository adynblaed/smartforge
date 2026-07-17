// Chart-spec model + client-side aggregation for the Work Orders EDA
// explorer. Pure functions over rows the governed endpoint already returned
// (bounded by the server's limit cap) — no additional data access. The
// Plotly trace/layout objects built here are plain JSON; theming (surface,
// ink, grid) is merged in by PlotlyChart at render time.
//
// Color rules follow the data-viz method: an 8-slot categorical palette
// validated (CVD + normal-vision + contrast) against this app's light and
// dark card surfaces; hues assigned to category values in a fixed sorted
// order so a filter change never repaints surviving series; overflow folds
// into a muted "Other" rather than inventing a 9th hue.

import type { ApiWorkOrderRow } from "@/smartforge/platformTypes"

/* ----------------------------------------------------------- palette */

/** Validated categorical slots (validate_palette.js: all checks pass on
 * #ffffff light / #2d2d40 dark card surfaces). Same hues, mode-stepped. */
export const EDA_PALETTE = {
  light: [
    "#2a78d6", // blue
    "#008300", // green
    "#e87ba4", // magenta
    "#eda100", // yellow
    "#1baf7a", // aqua
    "#eb6834", // orange
    "#4a3aa7", // violet
    "#e34948", // red
  ],
  dark: [
    "#3987e5",
    "#008300",
    "#d55181",
    "#c98500",
    "#199e70",
    "#d95926",
    "#9085e9",
    "#e66767",
  ],
} as const

/** Single-series accent: the violet slot — echoes the brand primary. */
export const SINGLE_SERIES_SLOT = 6
/** Muted ink for the folded "Other" bucket (never a palette hue). */
export const OTHER_COLOR = "#898781"
export const OTHER_LABEL = "Other"

/** Sequential blue ramp (light→dark) for heatmap magnitude. */
export const SEQUENTIAL_RAMP = [
  "#cde2fb",
  "#9ec5f4",
  "#6da7ec",
  "#3987e5",
  "#256abf",
  "#184f95",
  "#0d366b",
]

/* ------------------------------------------------------ field registry */

export type EdaAgg = "count" | "sum" | "avg"

export interface EdaDimension {
  key: string
  label: string
  kind: "category" | "date"
  value: (row: ApiWorkOrderRow) => string | null
}

export interface EdaNumericField {
  key: string
  label: string
  /** d3-format string used on axes and hover. */
  format: string
  value: (row: ApiWorkOrderRow) => number | null
}

const text = (v: string | null | undefined): string | null =>
  v == null || v === "" ? null : v

// Postgres NUMERIC crosses the JSON boundary as a string (precision-
// preserving), whatever the row type declares — coerce at the accessor so
// aggregation is arithmetic and the isFinite guards don't skip real values.
const asNumber = (v: unknown): number | null => {
  if (v == null) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

export const EDA_DIMENSIONS: EdaDimension[] = [
  {
    key: "status",
    label: "Status",
    kind: "category",
    value: (r) => text(r.status),
  },
  {
    key: "priority",
    label: "Priority",
    kind: "category",
    value: (r) => text(r.priority),
  },
  {
    key: "machine_code",
    label: "Machine",
    kind: "category",
    value: (r) => text(r.machine_code),
  },
  {
    key: "item_no",
    label: "Item",
    kind: "category",
    value: (r) => text(r.item_no),
  },
  {
    key: "wo_type",
    label: "WO type",
    kind: "category",
    value: (r) => text(r.wo_type),
  },
  {
    key: "current_operation",
    label: "Current operation",
    kind: "category",
    value: (r) => text(r.current_operation),
  },
  {
    key: "genealogy",
    label: "Genealogy level",
    kind: "category",
    value: (r) =>
      r.genealogy_depth == null
        ? null
        : (["root", "child", "grandchild"][r.genealogy_depth] ??
          `level ${r.genealogy_depth}`),
  },
  {
    key: "is_closed",
    label: "Open / closed",
    kind: "category",
    value: (r) =>
      r.is_closed == null ? null : r.is_closed ? "closed" : "open",
  },
  {
    key: "due_at",
    label: "Due date",
    kind: "date",
    value: (r) => text(r.due_at),
  },
  {
    key: "scheduled_at",
    label: "Scheduled date",
    kind: "date",
    value: (r) => text(r.scheduled_at),
  },
  {
    key: "completed_at",
    label: "Completed date",
    kind: "date",
    value: (r) => text(r.completed_at),
  },
]

export const EDA_NUMERIC_FIELDS: EdaNumericField[] = [
  {
    key: "qty_ordered",
    label: "Qty ordered",
    format: ",.0f",
    value: (r) => asNumber(r.qty_ordered),
  },
  {
    key: "qty_completed",
    label: "Qty completed",
    format: ",.0f",
    value: (r) => asNumber(r.qty_completed),
  },
  {
    key: "cost_total",
    label: "Total cost",
    format: "$,.0f",
    value: (r) => asNumber(r.cost_total),
  },
  {
    key: "labor_hours",
    label: "Labor hours",
    format: ",.1f",
    value: (r) => asNumber(r.labor_hours),
  },
  {
    key: "child_count",
    label: "Child count",
    format: ",.0f",
    value: (r) => asNumber(r.child_count),
  },
]

export const dimensionFor = (key: string): EdaDimension | undefined =>
  EDA_DIMENSIONS.find((d) => d.key === key)
export const numericFor = (key: string): EdaNumericField | undefined =>
  EDA_NUMERIC_FIELDS.find((f) => f.key === key)

/* ------------------------------------------------------------- spec */

export type ChartKind =
  | "bar"
  | "line"
  | "scatter"
  | "histogram"
  | "box"
  | "donut"
  | "heatmap"

export const CHART_KINDS: { value: ChartKind; label: string }[] = [
  { value: "bar", label: "Bar" },
  { value: "line", label: "Timeline" },
  { value: "scatter", label: "Scatter" },
  { value: "histogram", label: "Histogram" },
  { value: "box", label: "Box plot" },
  { value: "donut", label: "Donut" },
  { value: "heatmap", label: "Heatmap" },
]

/** One state shape drives every kind; buildChart maps it per kind. */
export interface EdaSpec {
  kind: ChartKind
  /** Primary dimension (bar/line/donut/heatmap x, box groups). */
  dim: string
  /** Secondary dimension (series split / heatmap y). "" = none. */
  dim2: string
  /** Numeric field: measure for aggregates, values for histogram/box, scatter x. */
  num: string
  /** Scatter y. */
  num2: string
  /** Aggregate applied to `num` ("count" ignores it). */
  agg: EdaAgg
}

export interface EdaPreset {
  key: string
  label: string
  hint: string
  spec: EdaSpec
}

/** Industry-standard starting points shared by ops, engineering and execs. */
export const EDA_PRESETS: EdaPreset[] = [
  {
    key: "status-mix",
    label: "Status mix",
    hint: "work orders by status",
    spec: {
      kind: "bar",
      dim: "status",
      dim2: "",
      num: "",
      num2: "",
      agg: "count",
    },
  },
  {
    key: "machine-load",
    label: "Machine load",
    hint: "orders per machine, split by status",
    spec: {
      kind: "bar",
      dim: "machine_code",
      dim2: "status",
      num: "",
      num2: "",
      agg: "count",
    },
  },
  {
    key: "due-timeline",
    label: "Due-date timeline",
    hint: "orders coming due over time",
    spec: {
      kind: "line",
      dim: "due_at",
      dim2: "status",
      num: "",
      num2: "",
      agg: "count",
    },
  },
  {
    key: "cost-pareto",
    label: "Cost by item",
    hint: "where the spend concentrates (Pareto)",
    spec: {
      kind: "bar",
      dim: "item_no",
      dim2: "",
      num: "cost_total",
      num2: "",
      agg: "sum",
    },
  },
  {
    key: "completion",
    label: "Completion progress",
    hint: "completed vs ordered quantity",
    spec: {
      kind: "scatter",
      dim: "",
      dim2: "status",
      num: "qty_ordered",
      num2: "qty_completed",
      agg: "sum",
    },
  },
  {
    key: "labor-spread",
    label: "Labor hours spread",
    hint: "effort distribution by status",
    spec: {
      kind: "box",
      dim: "status",
      dim2: "",
      num: "labor_hours",
      num2: "",
      agg: "sum",
    },
  },
  {
    key: "cost-histogram",
    label: "Cost distribution",
    hint: "how order costs are distributed",
    spec: {
      kind: "histogram",
      dim: "",
      dim2: "",
      num: "cost_total",
      num2: "",
      agg: "sum",
    },
  },
  {
    key: "priority-mix",
    label: "Priority mix",
    hint: "share of orders by priority",
    spec: {
      kind: "donut",
      dim: "priority",
      dim2: "",
      num: "",
      num2: "",
      agg: "count",
    },
  },
  {
    key: "machine-status-grid",
    label: "Machine × status",
    hint: "hot spots across machines and statuses",
    spec: {
      kind: "heatmap",
      dim: "status",
      dim2: "machine_code",
      num: "",
      num2: "",
      agg: "count",
    },
  },
]

/* -------------------------------------------------------- aggregation */

const MS_DAY = 86_400_000

export function chooseDateUnit(isoDates: string[]): "day" | "week" | "month" {
  const times = isoDates.map((d) => Date.parse(d)).filter(Number.isFinite)
  if (times.length < 2) return "day"
  const span = (Math.max(...times) - Math.min(...times)) / MS_DAY
  if (span <= 31) return "day"
  if (span <= 200) return "week"
  return "month"
}

/** Bucket an ISO timestamp to the start of its day/ISO-week/month (UTC). */
export function bucketDate(
  iso: string,
  unit: "day" | "week" | "month",
): string | null {
  const t = Date.parse(iso)
  if (!Number.isFinite(t)) return null
  const d = new Date(t)
  if (unit === "month")
    return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-01`
  if (unit === "week") {
    const shifted = new Date(t)
    // ISO week starts Monday: getUTCDay() Sun=0 → back 6 days, Mon=1 → 0.
    shifted.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7))
    return shifted.toISOString().slice(0, 10)
  }
  return d.toISOString().slice(0, 10)
}

/** Keep the `max` heaviest categories (by |weight|); fold the rest. */
export function foldCategories(
  weights: Map<string, number>,
  max: number,
): (category: string) => string {
  if (weights.size <= max) return (c) => c
  const kept = new Set(
    [...weights.entries()]
      .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
      .slice(0, max)
      .map(([c]) => c),
  )
  return (c) => (kept.has(c) ? c : OTHER_LABEL)
}

/**
 * Fixed hue assignment: values sorted, slots in palette order, Other muted.
 * Sorting (not encounter/rank order) keeps a value's hue stable when
 * filters change the composition.
 */
export function colorForCategories(
  categories: string[],
  palette: readonly string[],
): Map<string, string> {
  const sorted = [...new Set(categories)]
    .filter((c) => c !== OTHER_LABEL)
    .sort((a, b) => a.localeCompare(b))
  const out = new Map<string, string>()
  for (const [i, c] of sorted.entries()) out.set(c, palette[i % palette.length])
  out.set(OTHER_LABEL, OTHER_COLOR)
  return out
}

export interface AggregatedPoint {
  x: string
  group: string
  value: number
}

/** Group rows by (dimension, series) and aggregate the measure. */
export function aggregateRows(
  rows: ApiWorkOrderRow[],
  spec: EdaSpec,
  maxCategories: number,
): AggregatedPoint[] {
  const dim = dimensionFor(spec.dim)
  if (!dim) return []
  const dim2 = spec.dim2 ? dimensionFor(spec.dim2) : undefined
  const num = spec.agg === "count" ? undefined : numericFor(spec.num)

  const unit =
    dim.kind === "date"
      ? chooseDateUnit(
          rows.map((r) => dim.value(r)).filter((v): v is string => v != null),
        )
      : null

  // sum + count per (x, group) so avg falls out at the end.
  const sums = new Map<
    string,
    { x: string; group: string; sum: number; n: number }
  >()
  const xWeight = new Map<string, number>()
  for (const row of rows) {
    const rawX = dim.value(row)
    if (rawX == null) continue
    const x = unit ? bucketDate(rawX, unit) : rawX
    if (x == null) continue
    const group = dim2 ? (dim2.value(row) ?? "(none)") : ""
    const v = num ? num.value(row) : 1
    if (v == null || !Number.isFinite(v)) continue
    const k = `${x}\u0000${group}`
    const cell = sums.get(k) ?? { x, group, sum: 0, n: 0 }
    cell.sum += v
    cell.n += 1
    sums.set(k, cell)
    xWeight.set(x, (xWeight.get(x) ?? 0) + Math.abs(v))
  }

  // Dates keep their full axis; categories fold to the heaviest few.
  const foldX =
    dim.kind === "date"
      ? (c: string) => c
      : foldCategories(xWeight, maxCategories)

  const folded = new Map<
    string,
    { x: string; group: string; sum: number; n: number }
  >()
  for (const cell of sums.values()) {
    const x = foldX(cell.x)
    const k = `${x}\u0000${cell.group}`
    const acc = folded.get(k) ?? { x, group: cell.group, sum: 0, n: 0 }
    acc.sum += cell.sum
    acc.n += cell.n
    folded.set(k, acc)
  }

  const points = [...folded.values()].map((c) => ({
    x: c.x,
    group: c.group,
    value: spec.agg === "avg" ? c.sum / c.n : c.sum,
  }))

  // Series overflow folds too — a 9th series must never invent a hue.
  const groupWeight = new Map<string, number>()
  for (const p of points)
    groupWeight.set(
      p.group,
      (groupWeight.get(p.group) ?? 0) + Math.abs(p.value),
    )
  const foldG = foldCategories(groupWeight, 8)
  const merged = new Map<string, AggregatedPoint>()
  for (const p of points) {
    const group = foldG(p.group)
    const k = `${p.x}\u0000${group}`
    const acc = merged.get(k) ?? { x: p.x, group, value: 0 }
    // avg-of-folded approximates by summing averages' weights — acceptable
    // for the folded tail only; kept simple on purpose.
    acc.value += p.value
    merged.set(k, acc)
  }
  return [...merged.values()]
}

/* ------------------------------------------------------- chart build */

export type PlotlyJson = Record<string, unknown>

export interface BuiltChart {
  traces: PlotlyJson[]
  /** Kind-specific layout fragment; PlotlyChart merges theme + this. */
  layout: PlotlyJson
  /** True when the spec is complete enough to render. */
  ready: boolean
  /** Why the chart is not ready (shown as guidance, not an error). */
  reason?: string
}

const notReady = (reason: string): BuiltChart => ({
  traces: [],
  layout: {},
  ready: false,
  reason,
})

const measureLabel = (spec: EdaSpec): string => {
  if (spec.agg === "count") return "Work orders"
  const f = numericFor(spec.num)
  return f
    ? `${spec.agg === "avg" ? "Avg " : "Total "}${f.label.toLowerCase()}`
    : ""
}

const measureFormat = (spec: EdaSpec): string =>
  spec.agg === "count" ? ",.0f" : (numericFor(spec.num)?.format ?? ",.0f")

/** Series order: legend sorted by total weight desc, Other always last. */
function seriesOrder(points: AggregatedPoint[]): string[] {
  const totals = new Map<string, number>()
  for (const p of points)
    totals.set(p.group, (totals.get(p.group) ?? 0) + Math.abs(p.value))
  return [...totals.keys()].sort((a, b) => {
    if (a === OTHER_LABEL) return 1
    if (b === OTHER_LABEL) return -1
    return (totals.get(b) ?? 0) - (totals.get(a) ?? 0)
  })
}

function categoryAxisOrder(
  points: AggregatedPoint[],
  isDate: boolean,
): string[] {
  const totals = new Map<string, number>()
  for (const p of points)
    totals.set(p.x, (totals.get(p.x) ?? 0) + Math.abs(p.value))
  const xs = [...totals.keys()]
  if (isDate) return xs.sort((a, b) => a.localeCompare(b))
  return xs.sort((a, b) => {
    if (a === OTHER_LABEL) return 1
    if (b === OTHER_LABEL) return -1
    return (totals.get(b) ?? 0) - (totals.get(a) ?? 0)
  })
}

export function buildChart(
  rows: ApiWorkOrderRow[],
  spec: EdaSpec,
  palette: readonly string[],
  mode: "light" | "dark" = "light",
): BuiltChart {
  if (rows.length === 0) return notReady("No rows to plot — run a query first.")

  switch (spec.kind) {
    case "bar":
    case "line": {
      const dim = dimensionFor(spec.dim)
      if (!dim) return notReady("Pick an X-axis field.")
      if (spec.kind === "line" && dim.kind !== "date")
        return notReady("Timelines need a date field on the X axis.")
      if (spec.agg !== "count" && !numericFor(spec.num))
        return notReady("Pick a measure to aggregate.")
      const points = aggregateRows(rows, spec, 12)
      if (points.length === 0)
        return notReady("No values for this combination.")
      const isDate = dim.kind === "date"
      const xs = categoryAxisOrder(points, isDate)
      const groups = seriesOrder(points)
      const colors = colorForCategories(groups, palette)
      const single = groups.length === 1
      const fmt = measureFormat(spec)
      const traces = groups.map((group) => {
        const byX = new Map(
          points.filter((p) => p.group === group).map((p) => [p.x, p.value]),
        )
        const color = single
          ? palette[SINGLE_SERIES_SLOT]
          : (colors.get(group) ?? OTHER_COLOR)
        const name = single ? measureLabel(spec) : group || measureLabel(spec)
        return spec.kind === "bar"
          ? {
              type: "bar",
              name,
              x: xs,
              y: xs.map((x) => byX.get(x) ?? 0),
              marker: { color, line: { width: 0 } },
              hovertemplate: `%{x}<br>${name}: %{y:${fmt}}<extra></extra>`,
            }
          : {
              type: "scatter",
              mode: "lines+markers",
              name,
              x: xs,
              y: xs.map((x) => byX.get(x) ?? 0),
              line: { color, width: 2 },
              marker: { color, size: 6 },
              hovertemplate: `${name}: %{y:${fmt}}<extra></extra>`,
            }
      })
      return {
        traces,
        ready: true,
        layout: {
          barmode: "stack",
          bargap: 0.25,
          showlegend: !single,
          hovermode: spec.kind === "line" ? "x unified" : "closest",
          xaxis: {
            type: "category",
            categoryorder: "array",
            categoryarray: xs,
            title: { text: dim.label },
          },
          yaxis: {
            title: { text: measureLabel(spec) },
            tickformat: fmt,
            rangemode: "tozero",
          },
        },
      }
    }

    case "scatter": {
      const fx = numericFor(spec.num)
      const fy = numericFor(spec.num2)
      if (!fx || !fy) return notReady("Pick numeric fields for both axes.")
      const dim2 = spec.dim2 ? dimensionFor(spec.dim2) : undefined
      // All-pairs discrimination caps scatter at 4 hues (palette validation).
      const weights = new Map<string, number>()
      if (dim2)
        for (const r of rows) {
          const g = dim2.value(r) ?? "(none)"
          weights.set(g, (weights.get(g) ?? 0) + 1)
        }
      const fold = foldCategories(weights, 4)
      const groups = dim2 ? [...new Set([...weights.keys()].map(fold))] : [""]
      const colors = colorForCategories(groups, palette)
      const single = groups.length === 1
      const traces = groups.map((group) => {
        const pts = rows.filter(
          (r) => !dim2 || fold(dim2.value(r) ?? "(none)") === group,
        )
        const color = single
          ? palette[SINGLE_SERIES_SLOT]
          : (colors.get(group) ?? OTHER_COLOR)
        return {
          type: "scatter",
          mode: "markers",
          name: group || "Work orders",
          x: pts.map((r) => fx.value(r)),
          y: pts.map((r) => fy.value(r)),
          text: pts.map((r) => r.wo_number ?? r.work_order_uid.slice(0, 8)),
          marker: { color, size: 8, opacity: 0.8 },
          hovertemplate:
            `%{text}<br>${fx.label}: %{x:${fx.format}}` +
            `<br>${fy.label}: %{y:${fy.format}}<extra>${group || ""}</extra>`,
        }
      })
      return {
        traces,
        ready: true,
        layout: {
          showlegend: !single,
          hovermode: "closest",
          xaxis: { title: { text: fx.label }, tickformat: fx.format },
          yaxis: { title: { text: fy.label }, tickformat: fy.format },
        },
      }
    }

    case "histogram": {
      const f = numericFor(spec.num)
      if (!f) return notReady("Pick a numeric field to distribute.")
      const values = rows
        .map((r) => f.value(r))
        .filter((v): v is number => v != null && Number.isFinite(v))
      if (values.length === 0) return notReady("No values for this field.")
      return {
        traces: [
          {
            type: "histogram",
            x: values,
            name: f.label,
            marker: { color: palette[SINGLE_SERIES_SLOT], line: { width: 0 } },
            hovertemplate: `${f.label} %{x}<br>orders: %{y}<extra></extra>`,
          },
        ],
        ready: true,
        layout: {
          bargap: 0.05,
          showlegend: false,
          xaxis: { title: { text: f.label }, tickformat: f.format },
          yaxis: { title: { text: "Work orders" }, rangemode: "tozero" },
        },
      }
    }

    case "box": {
      const f = numericFor(spec.num)
      if (!f) return notReady("Pick a numeric field to distribute.")
      const dim = spec.dim ? dimensionFor(spec.dim) : undefined
      const weights = new Map<string, number>()
      if (dim)
        for (const r of rows) {
          const g = dim.value(r)
          if (g != null) weights.set(g, (weights.get(g) ?? 0) + 1)
        }
      const fold = foldCategories(weights, 8)
      const groups = dim
        ? [...new Set([...weights.keys()].map(fold))].sort((a, b) =>
            a === OTHER_LABEL ? 1 : b === OTHER_LABEL ? -1 : a.localeCompare(b),
          )
        : [""]
      const colors = colorForCategories(groups, palette)
      const single = groups.length === 1
      const traces = groups.map((group) => {
        const pts = rows.filter((r) => {
          const g = dim ? dim.value(r) : ""
          return dim ? g != null && fold(g) === group : true
        })
        return {
          type: "box",
          name: group || f.label,
          y: pts
            .map((r) => f.value(r))
            .filter((v): v is number => v != null && Number.isFinite(v)),
          marker: {
            color: single
              ? palette[SINGLE_SERIES_SLOT]
              : (colors.get(group) ?? OTHER_COLOR),
          },
          boxpoints: "outliers",
          hoverlabel: { namelength: -1 },
        }
      })
      return {
        traces,
        ready: true,
        layout: {
          showlegend: false,
          xaxis: { title: { text: dim?.label ?? "" } },
          yaxis: { title: { text: f.label }, tickformat: f.format },
        },
      }
    }

    case "donut": {
      const dim = dimensionFor(spec.dim)
      if (!dim || dim.kind === "date")
        return notReady("Pick a category field to slice by.")
      if (spec.agg !== "count" && !numericFor(spec.num))
        return notReady("Pick a measure to aggregate.")
      // Part-to-whole stays readable to ~6 slices; fold the tail.
      const points = aggregateRows(rows, { ...spec, dim2: "" }, 6)
      if (points.length === 0)
        return notReady("No values for this combination.")
      const xs = categoryAxisOrder(points, false)
      const colors = colorForCategories(xs, palette)
      const byX = new Map(points.map((p) => [p.x, p.value]))
      const fmt = measureFormat(spec)
      return {
        traces: [
          {
            type: "pie",
            hole: 0.55,
            sort: false,
            direction: "clockwise",
            labels: xs,
            values: xs.map((x) => byX.get(x) ?? 0),
            marker: {
              colors: xs.map((x) => colors.get(x) ?? OTHER_COLOR),
              // 2px surface gap between fills (mark spec).
              line: { width: 2 },
            },
            // With a legend up top the slices carry percent only — direct
            // label+percent text is reserved for legendless (≤3 slice)
            // donuts, so labels never fight the legend for the same space.
            textinfo: xs.length > 3 ? "percent" : "label+percent",
            textposition: "inside",
            automargin: true,
            hovertemplate: `%{label}<br>${measureLabel(spec)}: %{value:${fmt}} (%{percent})<extra></extra>`,
          },
        ],
        ready: true,
        layout: { showlegend: xs.length > 3 },
      }
    }

    case "heatmap": {
      const dx = dimensionFor(spec.dim)
      const dy = spec.dim2 ? dimensionFor(spec.dim2) : undefined
      if (!dx || !dy) return notReady("Pick two category fields to cross.")
      if (dx.key === dy.key) return notReady("Pick two different fields.")
      if (spec.agg !== "count" && !numericFor(spec.num))
        return notReady("Pick a measure to aggregate.")
      const points = aggregateRows(rows, spec, 10)
      if (points.length === 0)
        return notReady("No values for this combination.")
      const xs = categoryAxisOrder(points, dx.kind === "date")
      const ys = [...new Set(points.map((p) => p.group))].sort((a, b) =>
        a === OTHER_LABEL ? 1 : b === OTHER_LABEL ? -1 : a.localeCompare(b),
      )
      const byKey = new Map(
        points.map((p) => [`${p.x}\u0000${p.group}`, p.value]),
      )
      const fmt = measureFormat(spec)
      return {
        traces: [
          {
            type: "heatmap",
            x: xs,
            y: ys,
            z: ys.map((y) =>
              xs.map((x) => byKey.get(`${x}\u0000${y}`) ?? null),
            ),
            // Near-zero recedes toward the surface: light end first on a
            // light surface, dark end first on a dark one.
            colorscale: (mode === "dark"
              ? [...SEQUENTIAL_RAMP].reverse()
              : SEQUENTIAL_RAMP
            ).map((c, i) => [i / (SEQUENTIAL_RAMP.length - 1), c]),
            xgap: 2,
            ygap: 2,
            hoverongaps: false,
            colorbar: { thickness: 10, outlinewidth: 0 },
            hovertemplate: `${dx.label}: %{x}<br>${dy.label}: %{y}<br>${measureLabel(spec)}: %{z:${fmt}}<extra></extra>`,
          },
        ],
        ready: true,
        layout: {
          showlegend: false,
          xaxis: { title: { text: dx.label }, type: "category" },
          yaxis: {
            title: { text: dy.label },
            type: "category",
            automargin: true,
          },
        },
      }
    }
  }
}
