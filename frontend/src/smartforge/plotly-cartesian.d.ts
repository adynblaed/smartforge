// Minimal surface of the plotly.js cartesian partial bundle (the full
// @types/plotly.js package tracks the complete build; we only render/purge
// and pass plain JSON trace/layout objects built in eda.ts).
declare module "plotly.js-cartesian-dist-min" {
  export type PlotlyJson = Record<string, unknown>

  const Plotly: {
    /** Idempotent render: creates or diffs the plot in place. */
    react(
      root: HTMLElement,
      data: PlotlyJson[],
      layout?: PlotlyJson,
      config?: PlotlyJson,
    ): Promise<unknown>
    /** Recompute size after a container resize. */
    Plots: { resize(root: HTMLElement): void }
    /** Release WebGL/DOM resources on unmount. */
    purge(root: HTMLElement): void
  }
  export default Plotly
}
