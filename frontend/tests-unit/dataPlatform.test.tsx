import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import {
  FreshnessBadge,
  formatLag,
  formatRunDuration,
  formatWhen,
  freshnessClass,
  freshnessCounts,
  kpiLabel,
  RunStatusBadge,
  runStatusClass,
  summarizeRuns,
} from "@/smartforge/platform"
import type {
  ReplicationRun,
  ReplicationTableRun,
} from "@/smartforge/platformTypes"

describe("formatLag", () => {
  it("handles missing lag", () => {
    expect(formatLag(null)).toBe("—")
    expect(formatLag(undefined)).toBe("—")
  })

  it("formats sub-minute and minute lags", () => {
    expect(formatLag(0.4)).toBe("<1m")
    expect(formatLag(42)).toBe("42m")
    expect(formatLag(59.4)).toBe("59m")
  })

  it("formats hour and day lags", () => {
    expect(formatLag(60)).toBe("1h")
    expect(formatLag(204)).toBe("3h 24m")
    expect(formatLag(60 * 24)).toBe("1d")
    expect(formatLag(60 * 24 * 2 + 60 * 5)).toBe("2d 5h")
  })
})

describe("freshnessClass", () => {
  it("maps freshness statuses to semantic tokens", () => {
    expect(freshnessClass("fresh")).toContain("success")
    expect(freshnessClass("warning")).toContain("warning")
    expect(freshnessClass("stale")).toContain("danger")
    expect(freshnessClass("never_loaded")).toContain("muted")
  })

  it("falls back to muted for unknown statuses", () => {
    expect(freshnessClass(undefined)).toContain("muted")
    expect(freshnessClass("bogus")).toContain("muted")
  })
})

describe("runStatusClass", () => {
  it("maps run statuses to semantic tokens", () => {
    expect(runStatusClass("succeeded")).toContain("success")
    expect(runStatusClass("passed")).toContain("success")
    expect(runStatusClass("failed")).toContain("danger")
    expect(runStatusClass("running")).toContain("info")
    expect(runStatusClass("something_else")).toContain("muted")
  })
})

describe("formatRunDuration", () => {
  it("handles missing start", () => {
    expect(formatRunDuration(null, null)).toBe("—")
  })

  it("marks open-ended runs as running", () => {
    expect(formatRunDuration("2026-07-15T10:00:00Z", null)).toBe("running")
  })

  it("formats short and long durations", () => {
    expect(
      formatRunDuration("2026-07-15T10:00:00Z", "2026-07-15T10:00:04.200Z"),
    ).toBe("4.2s")
    expect(
      formatRunDuration("2026-07-15T10:00:00Z", "2026-07-15T10:03:20Z"),
    ).toBe("3m 20s")
    expect(
      formatRunDuration("2026-07-15T10:00:00Z", "2026-07-15T10:05:00Z"),
    ).toBe("5m")
  })
})

describe("formatWhen", () => {
  it("handles null and unparseable input", () => {
    expect(formatWhen(null)).toBe("—")
    expect(formatWhen("not-a-date")).toBe("not-a-date")
  })

  it("renders ISO timestamps as a local string", () => {
    const iso = "2026-07-15T10:00:00Z"
    expect(formatWhen(iso)).toBe(new Date(iso).toLocaleString())
  })
})

describe("kpiLabel", () => {
  it("prettifies snake_case KPI keys", () => {
    expect(kpiLabel("quality_pass_rate_30d")).toBe("Quality Pass Rate 30d")
    expect(kpiLabel("open_work_orders")).toBe("Open Work Orders")
  })
})

describe("freshnessCounts", () => {
  it("buckets rows by status and ignores unknowns", () => {
    const rows = [
      { status: "fresh" as const },
      { status: "fresh" as const },
      { status: "warning" as const },
      { status: "stale" as const },
      { status: "never_loaded" as const },
    ]
    expect(freshnessCounts(rows)).toEqual({
      fresh: 2,
      warning: 1,
      stale: 1,
      never_loaded: 1,
    })
    expect(freshnessCounts([])).toEqual({
      fresh: 0,
      warning: 0,
      stale: 0,
      never_loaded: 0,
    })
  })
})

describe("summarizeRuns", () => {
  const run = (run_id: string): ReplicationRun => ({
    run_id,
    kind: "incremental",
    status: "succeeded",
    started_at: "2026-07-15T10:00:00Z",
    completed_at: "2026-07-15T10:01:00Z",
    detail: null,
  })
  const tableRun = (
    run_id: string,
    loaded: number | null,
    extracted: number | null = null,
  ): ReplicationTableRun => ({
    run_id,
    load_id: "L1",
    source_schema: "OMEGA",
    source_table: "ORDERS",
    strategy: "incremental_cursor",
    status: "succeeded",
    source_scn: 1,
    cursor_lower: null,
    cursor_upper: null,
    rows_extracted: extracted,
    rows_written_to_lake: null,
    rows_loaded_to_postgres: loaded,
    rows_rejected: 0,
    error: null,
    started_at: "2026-07-15T10:00:00Z",
    completed_at: "2026-07-15T10:00:30Z",
  })

  it("aggregates per-run table counts and row totals", () => {
    const out = summarizeRuns(
      [run("a"), run("b")],
      [tableRun("a", 100), tableRun("a", 50), tableRun("b", null, 7)],
    )
    expect(out[0]).toMatchObject({ run_id: "a", tables: 2, rows: 150 })
    // falls back to rows_extracted when the load count is missing
    expect(out[1]).toMatchObject({ run_id: "b", tables: 1, rows: 7 })
  })

  it("keeps runs with no table runs at zero", () => {
    const out = summarizeRuns([run("solo")], [])
    expect(out[0]).toMatchObject({ tables: 0, rows: 0 })
  })
})

describe("FreshnessBadge", () => {
  it("renders the status with underscores humanized", () => {
    render(<FreshnessBadge status="never_loaded" />)
    expect(screen.getByText("never loaded")).toBeInTheDocument()
  })

  it("renders unknown when status is missing", () => {
    render(<FreshnessBadge />)
    expect(screen.getByText("unknown")).toBeInTheDocument()
  })
})

describe("RunStatusBadge", () => {
  it("renders the run status text", () => {
    render(<RunStatusBadge status="succeeded" />)
    expect(screen.getByText("succeeded")).toBeInTheDocument()
  })
})
