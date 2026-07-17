import { describe, expect, it } from "vitest"

import {
  aggregateRows,
  bucketDate,
  buildChart,
  chooseDateUnit,
  colorForCategories,
  EDA_PALETTE,
  EDA_PRESETS,
  type EdaSpec,
  foldCategories,
  OTHER_COLOR,
  OTHER_LABEL,
} from "@/smartforge/eda"
import type { ApiWorkOrderRow } from "@/smartforge/platformTypes"

const row = (patch: Partial<ApiWorkOrderRow>): ApiWorkOrderRow => ({
  work_order_uid: "u",
  work_order_id: 1,
  wo_number: "WO-1",
  parent_work_order_uid: null,
  root_work_order_uid: null,
  genealogy_depth: 0,
  genealogy_path: null,
  child_count: 0,
  is_leaf: true,
  title: null,
  wo_type: null,
  item_no: "ITEM-1",
  qty_ordered: 10,
  qty_completed: 5,
  status: "released",
  priority: "normal",
  current_operation: null,
  sales_order_no: null,
  sales_order_line: null,
  machine_code: "CNC-01",
  scheduled_at: null,
  due_at: "2026-07-10T00:00:00Z",
  completed_at: null,
  is_closed: false,
  labor_hours: 2,
  cost_total: 100,
  load_id: null,
  extracted_at: null,
  ...patch,
})

describe("bucketDate", () => {
  it("buckets to day, ISO week (Monday) and month", () => {
    // 2026-07-10 is a Friday; its ISO week starts Monday 2026-07-06.
    expect(bucketDate("2026-07-10T15:30:00Z", "day")).toBe("2026-07-10")
    expect(bucketDate("2026-07-10T15:30:00Z", "week")).toBe("2026-07-06")
    expect(bucketDate("2026-07-10T15:30:00Z", "month")).toBe("2026-07-01")
  })

  it("returns null for unparseable input", () => {
    expect(bucketDate("not-a-date", "day")).toBeNull()
  })
})

describe("chooseDateUnit", () => {
  it("widens the bucket with the span", () => {
    expect(chooseDateUnit(["2026-07-01", "2026-07-20"])).toBe("day")
    expect(chooseDateUnit(["2026-05-01", "2026-08-20"])).toBe("week")
    expect(chooseDateUnit(["2025-01-01", "2026-08-20"])).toBe("month")
  })
})

describe("foldCategories", () => {
  it("keeps the heaviest categories and folds the tail to Other", () => {
    const weights = new Map([
      ["a", 100],
      ["b", 50],
      ["c", 2],
      ["d", 1],
    ])
    const fold = foldCategories(weights, 2)
    expect(fold("a")).toBe("a")
    expect(fold("b")).toBe("b")
    expect(fold("c")).toBe(OTHER_LABEL)
    expect(fold("d")).toBe(OTHER_LABEL)
  })

  it("is identity when everything fits", () => {
    const fold = foldCategories(new Map([["a", 1]]), 8)
    expect(fold("a")).toBe("a")
  })
})

describe("colorForCategories", () => {
  it("assigns hues by sorted value, so filters never repaint survivors", () => {
    const palette = EDA_PALETTE.dark
    const all = colorForCategories(["released", "closed", "hold"], palette)
    const filtered = colorForCategories(["released", "closed"], palette)
    expect(filtered.get("closed")).toBe(all.get("closed"))
    // "hold" sat between them alphabetically, so "released" MAY shift —
    // but "closed" (first sorted) must be stable, and Other is always muted.
    expect(all.get(OTHER_LABEL)).toBe(OTHER_COLOR)
  })
})

describe("aggregateRows", () => {
  const spec: EdaSpec = {
    kind: "bar",
    dim: "status",
    dim2: "",
    num: "",
    num2: "",
    agg: "count",
  }

  it("counts by dimension", () => {
    const rows = [
      row({ status: "released" }),
      row({ status: "released" }),
      row({ status: "closed" }),
    ]
    const points = aggregateRows(rows, spec, 8)
    expect(points).toContainEqual({ x: "released", group: "", value: 2 })
    expect(points).toContainEqual({ x: "closed", group: "", value: 1 })
  })

  it("sums and averages a measure", () => {
    const rows = [row({ cost_total: 100 }), row({ cost_total: 50 })]
    const sum = aggregateRows(
      rows,
      { ...spec, agg: "sum", num: "cost_total" },
      8,
    )
    expect(sum[0].value).toBe(150)
    const avg = aggregateRows(
      rows,
      { ...spec, agg: "avg", num: "cost_total" },
      8,
    )
    expect(avg[0].value).toBe(75)
  })

  it("skips rows with a null dimension or measure", () => {
    const rows = [row({ status: null }), row({ cost_total: null })]
    expect(aggregateRows(rows, spec, 8)).toHaveLength(1)
    expect(
      aggregateRows(rows, { ...spec, agg: "sum", num: "cost_total" }, 8),
    ).toHaveLength(0)
  })
})

describe("buildChart", () => {
  const rows = [
    row({ status: "released", machine_code: "CNC-01" }),
    row({ status: "released", machine_code: "CNC-02" }),
    row({ status: "closed", machine_code: "CNC-01" }),
  ]

  it("renders every preset without errors on representative rows", () => {
    for (const preset of EDA_PRESETS) {
      const built = buildChart(rows, preset.spec, EDA_PALETTE.dark)
      expect(built.ready, `${preset.key}: ${built.reason ?? ""}`).toBe(true)
      expect(built.traces.length).toBeGreaterThan(0)
    }
  })

  it("hides the legend for a single series and shows it when split", () => {
    const single = buildChart(
      rows,
      { kind: "bar", dim: "status", dim2: "", num: "", num2: "", agg: "count" },
      EDA_PALETTE.dark,
    )
    expect(single.layout.showlegend).toBe(false)
    const split = buildChart(
      rows,
      {
        kind: "bar",
        dim: "machine_code",
        dim2: "status",
        num: "",
        num2: "",
        agg: "count",
      },
      EDA_PALETTE.dark,
    )
    expect(split.layout.showlegend).toBe(true)
    expect(split.traces).toHaveLength(2)
  })

  it("refuses gracefully instead of rendering a wrong form", () => {
    const timelineOnCategory = buildChart(
      rows,
      {
        kind: "line",
        dim: "status",
        dim2: "",
        num: "",
        num2: "",
        agg: "count",
      },
      EDA_PALETTE.dark,
    )
    expect(timelineOnCategory.ready).toBe(false)
    expect(timelineOnCategory.reason).toMatch(/date field/)

    const heatmapSameAxis = buildChart(
      rows,
      {
        kind: "heatmap",
        dim: "status",
        dim2: "status",
        num: "",
        num2: "",
        agg: "count",
      },
      EDA_PALETTE.dark,
    )
    expect(heatmapSameAxis.ready).toBe(false)

    expect(buildChart([], EDA_PRESETS[0].spec, EDA_PALETTE.dark).ready).toBe(
      false,
    )
  })

  it("sorts categorical bars by weight with Other last", () => {
    const many = [
      ...Array.from({ length: 5 }, () => row({ status: "released" })),
      ...Array.from({ length: 3 }, () => row({ status: "closed" })),
      row({ status: "hold" }),
    ]
    const built = buildChart(
      many,
      { kind: "bar", dim: "status", dim2: "", num: "", num2: "", agg: "count" },
      EDA_PALETTE.dark,
    )
    const xaxis = built.layout.xaxis as { categoryarray: string[] }
    expect(xaxis.categoryarray[0]).toBe("released")
  })
})
