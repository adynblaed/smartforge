// High-level size comparison of the warehouse datasets (marts + certified
// contracts): one embedded Plotly chart with Bar / Donut / Scatter forms
// and a Columns / Rows metric toggle. EVERY dataset is always represented:
// columns exist for all of them (the default comparison), while row
// estimates come from planner statistics and are zero for plain views —
// the hover says so instead of silently dropping the dataset. Colors
// follow the same validated categorical palette as the Work Orders charts
// (fixed assignment per dataset name — never repainted by sorting).

import {
  ChartColumnBig,
  ChartPie,
  ChartScatter,
  type LucideIcon,
} from "lucide-react"
import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import {
  colorForCategories,
  OTHER_COLOR,
  type PlotlyJson,
} from "@/smartforge/eda"
import { PlotlyChart, useChartTheme } from "@/smartforge/PlotlyChart"
import type { WarehouseDataset } from "@/smartforge/platformTypes"

type SizeChartKind = "bar" | "donut" | "scatter"
type SizeMetric = "columns" | "rows"

const KINDS: { value: SizeChartKind; label: string; icon: LucideIcon }[] = [
  { value: "bar", label: "Bar", icon: ChartColumnBig },
  { value: "donut", label: "Donut", icon: ChartPie },
  { value: "scatter", label: "Scatter", icon: ChartScatter },
]

const rowsOf = (d: WarehouseDataset): number => Math.max(0, d.row_estimate ?? 0)

const hoverNote = (d: WarehouseDataset): string =>
  d.row_estimate == null
    ? "rows: no estimate (view)"
    : `rows (est.): ${rowsOf(d).toLocaleString()}`

export function DatasetSizeChart({
  datasets,
}: {
  datasets: WarehouseDataset[]
}) {
  const [kind, setKind] = useState<SizeChartKind>("donut")
  const [metric, setMetric] = useState<SizeMetric>("columns")
  const theme = useChartTheme()

  const built = useMemo((): { traces: PlotlyJson[]; layout: PlotlyJson } => {
    // Every dataset, always — sorted heaviest-first on the active metric.
    const sizeOf = (d: WarehouseDataset) =>
      metric === "rows" ? rowsOf(d) : d.column_count
    const compared = [...datasets].sort((a, b) => sizeOf(b) - sizeOf(a))
    const names = compared.map((d) => d.dataset)
    const colors = colorForCategories(names, theme.palette)
    const colorList = names.map((n) => colors.get(n) ?? OTHER_COLOR)
    const values = compared.map(sizeOf)
    const metricLabel = metric === "rows" ? "rows (estimated)" : "total columns"
    const notes = compared.map(hoverNote)

    if (kind === "bar")
      return {
        traces: [
          {
            type: "bar",
            x: names,
            y: values,
            marker: { color: colorList, line: { width: 0 } },
            customdata: compared.map((d, i) => [d.column_count, notes[i]]),
            hovertemplate:
              `%{x}<br>${metricLabel}: %{y:,.0f}` +
              "<br>columns: %{customdata[0]}" +
              "<br>%{customdata[1]}<extra></extra>",
          },
        ],
        layout: {
          bargap: 0.25,
          showlegend: false,
          xaxis: { type: "category", tickangle: -35 },
          yaxis: { title: { text: metricLabel }, rangemode: "tozero" },
        },
      }
    if (kind === "donut") {
      // Zero-value slices are invisible in a donut; keep every dataset
      // visible by flooring at 1 for the share (the hover stays honest).
      const shares = values.map((v) => Math.max(1, v))
      return {
        traces: [
          {
            type: "pie",
            hole: 0.55,
            sort: false,
            labels: names,
            values: shares,
            marker: { colors: colorList, line: { width: 2 } },
            textinfo: "percent",
            textposition: "inside",
            automargin: true,
            customdata: compared.map((_d, i) => [values[i], notes[i]]),
            hovertemplate:
              `%{label}<br>${metricLabel}: %{customdata[0]:,.0f} (%{percent})` +
              "<br>%{customdata[1]}<extra></extra>",
          },
        ],
        layout: { showlegend: true },
      }
    }
    return {
      traces: [
        {
          type: "scatter",
          mode: "markers",
          x: compared.map((d) => d.column_count),
          y: compared.map(rowsOf),
          text: names,
          marker: { color: colorList, size: 10, opacity: 0.85 },
          customdata: notes,
          hovertemplate:
            "%{text}<br>columns: %{x}" + "<br>%{customdata}<extra></extra>",
        },
      ],
      layout: {
        showlegend: false,
        xaxis: { title: { text: "total columns" }, rangemode: "tozero" },
        yaxis: { title: { text: "rows (estimated)" }, rangemode: "tozero" },
      },
    }
  }, [datasets, kind, metric, theme.palette])

  if (datasets.length === 0) return null

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-1.5 rounded-lg border bg-muted/30 p-1.5">
        {KINDS.map((k) => (
          <Button
            key={k.value}
            size="sm"
            variant={kind === k.value ? "default" : "ghost"}
            className="h-7 gap-1.5 px-2.5 text-xs"
            aria-pressed={kind === k.value}
            title={`Compare dataset sizes as a ${k.label.toLowerCase()} chart`}
            onClick={() => setKind(k.value)}
          >
            <k.icon className="size-3.5" />
            {k.label}
          </Button>
        ))}
        {kind !== "scatter" && (
          <div className="ml-2 flex items-center gap-1 rounded-md border bg-card p-0.5">
            {(["columns", "rows"] as const).map((m) => (
              <Button
                key={m}
                size="sm"
                variant={metric === m ? "secondary" : "ghost"}
                className="h-6 px-2 text-xs capitalize"
                aria-pressed={metric === m}
                onClick={() => setMetric(m)}
              >
                {m}
              </Button>
            ))}
          </div>
        )}
        <span className="ml-auto pr-1 text-xs text-muted-foreground">
          dataset size comparison · all {datasets.length} datasets
        </span>
      </div>
      <PlotlyChart
        traces={built.traces}
        layout={built.layout}
        height={320}
        ariaLabel={`${kind} chart comparing warehouse dataset sizes by ${metric}`}
      />
    </div>
  )
}
