import { describe, expect, it } from "vitest"

import {
  buildGrid,
  cellState,
  effectiveSupply,
  formatPlanDate,
  netSeries,
  summarize,
} from "@/smartforge/mrp"
import type { MrpPlanRow } from "@/smartforge/platformTypes"

function planRow(overrides: Partial<MrpPlanRow>): MrpPlanRow {
  return {
    plan_row_key: `${overrides.item_no ?? "X"}:${overrides.plan_date ?? "2026-07-16"}`,
    item_no: "10370",
    item_description: "18 GA, CRS, 48 x 84",
    item_type: "SHEET",
    uom: "Ea",
    plan_date: "2026-07-16",
    demand_qty: 0,
    supply_qty: 0,
    supply_work_orders: 0,
    opening_qty: 1200,
    projected_balance: 0,
    safety_stock: 500,
    mrp_lead_time_days: 5,
    plan_status: "covered",
    exception_desc: null,
    plan_horizon_end: null,
    ...overrides,
  }
}

const ROWS: MrpPlanRow[] = [
  planRow({ plan_date: "2026-07-17", demand_qty: 380 }),
  planRow({ plan_date: "2026-07-18", demand_qty: 320 }),
  planRow({ plan_date: "2026-07-19", supply_qty: 800 }),
  planRow({
    item_no: "10017",
    item_description: ".090 AL",
    opening_qty: 60,
    safety_stock: 0,
    plan_date: "2026-07-18",
    demand_qty: 90,
  }),
]

describe("buildGrid", () => {
  it("pivots item×date rows into aligned demand/supply series", () => {
    const grid = buildGrid(ROWS)
    expect(grid.dates).toEqual(["2026-07-17", "2026-07-18", "2026-07-19"])
    expect(grid.items.map((i) => i.itemNo)).toEqual(["10017", "10370"])
    const sheet = grid.items.find((i) => i.itemNo === "10370")
    expect(sheet?.demand).toEqual([380, 320, 0])
    expect(sheet?.supply).toEqual([0, 0, 800])
    expect(sheet?.openingQty).toBe(1200)
    expect(sheet?.safetyStock).toBe(500)
  })
})

describe("netSeries", () => {
  it("rolls net forward: prior − demand + supply, seeded from on-hand", () => {
    const grid = buildGrid(ROWS)
    const sheet = grid.items.find((i) => i.itemNo === "10370")
    if (!sheet) throw new Error("missing item")
    // 1200 − 380 = 820; 820 − 320 = 500... wait: 820 − 320 = 500 exactly;
    // then +800 = 1300.
    expect(netSeries(sheet)).toEqual([820, 500, 1300])
  })
})

describe("cellState", () => {
  it("classifies exactly like the warehouse mart", () => {
    expect(cellState(-1, 0)).toBe("shortage")
    expect(cellState(499, 500)).toBe("below_safety")
    expect(cellState(500, 500)).toBe("covered")
    expect(cellState(0, 0)).toBe("covered")
  })
})

describe("what-if overrides", () => {
  it("replaces supply locally and recomputes the summary", () => {
    const grid = buildGrid(ROWS)
    const aluminum = grid.items.find((i) => i.itemNo === "10017")
    if (!aluminum) throw new Error("missing item")
    // Base: 60 − 90 = −30 on day 2, and the net STAYS negative on day 3
    // (nets roll forward) -> two shortage days, one item short.
    expect(summarize([aluminum])).toEqual({
      shortageDays: 2,
      itemsShort: 1,
      belowSafetyDays: 0,
    })
    // What-if: 100 units of supply on that day resolves the shortage.
    const overrides = { "10017:1": 100 }
    expect(effectiveSupply(aluminum, overrides)).toEqual([0, 100, 0])
    expect(summarize([aluminum], overrides)).toEqual({
      shortageDays: 0,
      itemsShort: 0,
      belowSafetyDays: 0,
    })
  })
})

describe("formatPlanDate", () => {
  it("renders a compact day-month header", () => {
    expect(formatPlanDate("2026-07-16")).toMatch(/16/)
    expect(formatPlanDate("not-a-date")).toBe("not-a-date")
  })
})
