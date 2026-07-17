// Postgres NUMERIC crosses the JSON boundary as a string, whatever the
// TypeScript row contracts declare. These tests pin the coercion at every
// aggregation boundary — without it, MRP nets concatenate ("28" +
// "0120.0000") and chart measures are silently skipped by isFinite guards.
import { describe, expect, it } from "vitest"

import { buildChart, EDA_PALETTE } from "@/smartforge/eda"
import { buildWorkOrderGraph } from "@/smartforge/graphLayout"
import { buildGrid, netSeries, planQty } from "@/smartforge/mrp"
import type { ApiWorkOrderRow, MrpPlanRow } from "@/smartforge/platformTypes"

const planRow = (patch: Record<string, unknown>): MrpPlanRow =>
  ({
    plan_row_key: "k",
    item_no: "ITEM-1",
    item_description: null,
    item_type: null,
    uom: "Ea",
    plan_date: "2026-07-17",
    demand_qty: 0,
    supply_qty: 0,
    supply_work_orders: 0,
    opening_qty: 0,
    projected_balance: 0,
    safety_stock: 0,
    mrp_lead_time_days: null,
    plan_status: "covered",
    exception_desc: null,
    plan_horizon_end: null,
    ...patch,
  }) as MrpPlanRow

describe("planQty", () => {
  it("coerces NUMERIC strings and defaults junk to 0", () => {
    expect(planQty("120.0000")).toBe(120)
    expect(planQty(7)).toBe(7)
    expect(planQty(null)).toBe(0)
    expect(planQty("not-a-number")).toBe(0)
  })
})

describe("buildGrid with NUMERIC-string payloads", () => {
  it("does arithmetic, never string concatenation", () => {
    const grid = buildGrid([
      planRow({
        opening_qty: "28.0000",
        demand_qty: "120.0000",
        supply_qty: "120.0000",
        safety_stock: "36.0000",
      }),
    ] as unknown as MrpPlanRow[])
    const item = grid.items[0]
    expect(item.openingQty).toBe(28)
    expect(item.demand[0]).toBe(120)
    // net = 28 - 120 + 120 = 28 (NOT "280120.0000")
    expect(netSeries(item)[0]).toBe(28)
  })
})

const woRow = (patch: Record<string, unknown>): ApiWorkOrderRow =>
  ({
    work_order_uid: "u1",
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
    status: "OR",
    priority: null,
    current_operation: null,
    sales_order_no: null,
    sales_order_line: null,
    machine_code: null,
    scheduled_at: null,
    due_at: null,
    completed_at: null,
    is_closed: false,
    labor_hours: null,
    cost_total: 100,
    load_id: null,
    extracted_at: null,
    ...patch,
  }) as ApiWorkOrderRow

describe("chart measures with NUMERIC-string payloads", () => {
  it("sums string costs instead of skipping them", () => {
    const rows = [
      woRow({ work_order_uid: "a", cost_total: "100.5000" }),
      woRow({ work_order_uid: "b", cost_total: "49.5000" }),
    ] as unknown as ApiWorkOrderRow[]
    const built = buildChart(
      rows,
      {
        kind: "bar",
        dim: "item_no",
        dim2: "",
        num: "cost_total",
        num2: "",
        agg: "sum",
      },
      EDA_PALETTE.dark,
    )
    expect(built.ready).toBe(true)
    const trace = built.traces[0] as { y: number[] }
    expect(trace.y[0]).toBe(150)
  })
})

describe("graph sizing with NUMERIC-string payloads", () => {
  it("scales node size from string cost magnitudes", () => {
    const g = buildWorkOrderGraph([
      woRow({ work_order_uid: "big", cost_total: "90000.0000" }),
      woRow({ work_order_uid: "small", cost_total: "10.0000" }),
    ] as unknown as ApiWorkOrderRow[])
    expect(g.sizeMetric).toBe("cost")
    const size = new Map(g.nodes.map((n) => [n.uid, n.size]))
    const big = size.get("big")
    const small = size.get("small")
    if (big === undefined || small === undefined) throw new Error("missing")
    expect(big).toBeGreaterThan(small)
  })
})
