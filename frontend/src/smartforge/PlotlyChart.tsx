// Theme-aware Plotly host. Plotly needs literal colors (it can't read CSS
// custom properties), so the surface/ink/grid tokens are resolved from the
// live theme at render time and the plot re-themes on the root class change
// (covers dark ⇄ light ⇄ future, whichever wins). The cartesian partial
// bundle keeps the payload to the trace types the EDA explorer offers.

import Plotly, { type PlotlyJson } from "plotly.js-cartesian-dist-min"
import { useEffect, useMemo, useRef, useState } from "react"

import { EDA_PALETTE } from "@/smartforge/eda"

/**
 * Resolve any CSS color to numeric rgb via a 1×1 canvas. The theme tokens
 * are oklch() and Chrome serializes computed colors in oklch form, which
 * Plotly's color parser rejects (silently falling back to its light-mode
 * defaults) — the canvas round-trip normalizes everything to numbers.
 */
function resolveRgb(
  raw: string,
  ctx: CanvasRenderingContext2D,
  fallback: [number, number, number],
): [number, number, number] {
  ctx.clearRect(0, 0, 1, 1)
  ctx.fillStyle = "#000000"
  ctx.fillStyle = raw
  ctx.fillRect(0, 0, 1, 1)
  const d = ctx.getImageData(0, 0, 1, 1).data
  return d[3] === 0 ? fallback : [d[0], d[1], d[2]]
}

export interface ChartTheme {
  mode: "light" | "dark"
  palette: readonly string[]
  surface: string
  ink: string
  mutedInk: string
  grid: string
}

function readChartTheme(): ChartTheme {
  const root = document.documentElement
  const mode: "light" | "dark" = root.classList.contains("dark")
    ? "dark"
    : "light"
  const canvas = document.createElement("canvas")
  canvas.width = 1
  canvas.height = 1
  const ctx = canvas.getContext("2d", { willReadFrequently: true })
  const styles = getComputedStyle(root)
  const dark = mode === "dark"
  const token = (name: string, fallback: [number, number, number]) => {
    const value = styles.getPropertyValue(name).trim()
    return value && ctx ? resolveRgb(value, ctx, fallback) : fallback
  }
  const surface = token("--card", dark ? [45, 45, 64] : [255, 255, 255])
  const ink = token("--foreground", dark ? [255, 255, 255] : [11, 11, 11])
  const mutedInk = token("--muted-foreground", [137, 135, 129])
  const rgb = (c: [number, number, number]) => `rgb(${c[0]},${c[1]},${c[2]})`
  return {
    mode,
    palette: EDA_PALETTE[mode],
    surface: rgb(surface),
    ink: rgb(ink),
    mutedInk: rgb(mutedInk),
    // Recessive hairline derived from the ink, NOT --border: this app's
    // dark theme is deliberately borderless (--border alpha 0), but a
    // chart still needs a faint grid to be readable.
    grid: `rgba(${ink[0]},${ink[1]},${ink[2]},${dark ? 0.14 : 0.1})`,
  }
}

/** Subscribe to the resolved theme; re-reads tokens when the root class
 * flips (the ThemeProvider stamps `dark`/`future` there). */
export function useChartTheme(): ChartTheme {
  const [theme, setTheme] = useState<ChartTheme>(readChartTheme)
  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(readChartTheme()))
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    })
    return () => observer.disconnect()
  }, [])
  return theme
}

function baseLayout(theme: ChartTheme, height: number): PlotlyJson {
  const axis = {
    gridcolor: theme.grid,
    linecolor: theme.grid,
    zerolinecolor: theme.grid,
    tickfont: { color: theme.mutedInk, size: 11 },
    title: { font: { color: theme.mutedInk, size: 12 } },
    automargin: true,
  }
  return {
    height,
    // Opaque paper matching the card surface: on-screen it blends with the
    // panel, and PNG exports come out clean on any background instead of
    // transparent (which artifacts in viewers and slides). The plot area
    // itself stays transparent so the paper shows through.
    paper_bgcolor: theme.surface,
    plot_bgcolor: "rgba(0,0,0,0)",
    font: {
      family: 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
      color: theme.ink,
      size: 12,
    },
    // Generous margins: the horizontal legend lives fully inside the top
    // margin band (y > 1), so it can never overlap the plot marks.
    margin: { t: 64, r: 24, b: 56, l: 64 },
    xaxis: axis,
    yaxis: axis,
    legend: {
      orientation: "h",
      yanchor: "bottom",
      y: 1.06,
      x: 0,
      font: { color: theme.mutedInk, size: 11 },
      itemsizing: "constant",
    },
    hoverlabel: {
      bgcolor: theme.surface,
      bordercolor: theme.grid,
      font: { color: theme.ink, size: 12 },
    },
    colorway: [...theme.palette],
  }
}

const PLOTLY_CONFIG: PlotlyJson = {
  displaylogo: false,
  responsive: true,
  // Toolbar always visible: zoom in/out + reset let the user frame the
  // chart before exporting; scale-2 PNG keeps exports crisp.
  displayModeBar: true,
  modeBarButtonsToRemove: ["lasso2d", "select2d"],
  toImageButtonOptions: {
    filename: "smartforge-work-orders",
    format: "png",
    scale: 2,
  },
}

/** Deep-merge b into a (plain JSON objects only — arrays replace). */
function mergeLayout(a: PlotlyJson, b: PlotlyJson): PlotlyJson {
  const out: PlotlyJson = { ...a }
  for (const [key, value] of Object.entries(b)) {
    const prev = out[key]
    out[key] =
      value &&
      prev &&
      typeof value === "object" &&
      typeof prev === "object" &&
      !Array.isArray(value) &&
      !Array.isArray(prev)
        ? mergeLayout(prev as PlotlyJson, value as PlotlyJson)
        : value
  }
  return out
}

export function PlotlyChart({
  traces,
  layout,
  height = 360,
  ariaLabel,
}: {
  traces: PlotlyJson[]
  layout: PlotlyJson
  height?: number
  ariaLabel: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const theme = useChartTheme()

  const merged = useMemo(
    () => mergeLayout(baseLayout(theme, height), layout),
    [theme, height, layout],
  )

  useEffect(() => {
    const el = ref.current
    if (!el) return
    Plotly.react(el, traces, merged, PLOTLY_CONFIG)
    // Tab panels mount before flex settles, so the first layout can size
    // against a too-wide parent — pushing the modebar off-canvas and the
    // plot out of frame. One post-layout resize snaps it to the real box.
    const kick = requestAnimationFrame(() => {
      if (el.clientWidth > 0) Plotly.Plots.resize(el)
    })
    return () => cancelAnimationFrame(kick)
  }, [traces, merged])

  // Track container (not just window) resizes — the sidebar collapses.
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(() => {
      if (el.clientWidth > 0) Plotly.Plots.resize(el)
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const el = ref.current
    return () => {
      if (el) Plotly.purge(el)
    }
  }, [])

  return (
    <div
      ref={ref}
      role="img"
      aria-label={ariaLabel}
      // min-w-0: as a flex/tab child the div must be allowed to shrink,
      // or the plot (and its modebar) overflows the panel to the right.
      className="w-full min-w-0 overflow-hidden rounded-md"
      style={{ minHeight: height }}
    />
  )
}
