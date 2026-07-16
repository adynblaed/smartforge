// Time-phased MRP grid logic: pivots the certified api_mrp_supply_plan rows
// (item × plan-date grain) into the planning-sheet layout — per item, a
// Demand / Supply / Projected-net row across the date horizon — plus the
// client-side what-if recompute. Pure functions, unit-tested in
// tests-unit/mrp.test.ts; the page never writes anything back.

import type { MrpPlanRow } from "@/smartforge/platformTypes"

export type PlanCellState = "shortage" | "below_safety" | "covered"

export interface MrpItemGrid {
  itemNo: string
  description: string
  itemType: string
  uom: string
  openingQty: number
  safetyStock: number
  /** Aligned with the grid's `dates` array; 0 where no bucket exists. */
  demand: number[]
  supply: number[]
}

export interface MrpGrid {
  /** Sorted ISO dates (yyyy-mm-dd) covering every item's buckets. */
  dates: string[]
  items: MrpItemGrid[]
}

const isoDate = (value: string) => value.slice(0, 10)

/** Pivot flat plan rows into items × dates with demand/supply series. */
export function buildGrid(rows: MrpPlanRow[]): MrpGrid {
  const dates = Array.from(
    new Set(rows.map((r) => isoDate(r.plan_date))),
  ).sort()
  const index = new Map(dates.map((d, i) => [d, i]))
  const items = new Map<string, MrpItemGrid>()
  for (const row of rows) {
    let item = items.get(row.item_no)
    if (!item) {
      item = {
        itemNo: row.item_no,
        description: row.item_description ?? "",
        itemType: row.item_type ?? "",
        uom: row.uom ?? "",
        openingQty: row.opening_qty ?? 0,
        safetyStock: row.safety_stock ?? 0,
        demand: dates.map(() => 0),
        supply: dates.map(() => 0),
      }
      items.set(row.item_no, item)
    }
    const at = index.get(isoDate(row.plan_date))
    if (at !== undefined) {
      item.demand[at] += row.demand_qty ?? 0
      item.supply[at] += row.supply_qty ?? 0
    }
  }
  return {
    dates,
    items: Array.from(items.values()).sort((a, b) =>
      a.itemNo.localeCompare(b.itemNo),
    ),
  }
}

/**
 * Net inventory rolls forward: each day = prior day's net − demand + supply,
 * seeded from the opening balance — identical math to the warehouse mart's
 * window sum, recomputed locally so what-if supply edits react instantly.
 */
export function netSeries(
  item: MrpItemGrid,
  supplyOverride?: number[],
): number[] {
  const supply = supplyOverride ?? item.supply
  const net: number[] = []
  let running = item.openingQty
  for (let i = 0; i < item.demand.length; i++) {
    running = running - item.demand[i] + (supply[i] ?? 0)
    net.push(running)
  }
  return net
}

export function cellState(net: number, safetyStock: number): PlanCellState {
  if (net < 0) return "shortage"
  if (net < safetyStock) return "below_safety"
  return "covered"
}

/** Tailwind classes per state (semantic tokens shared with the badges). */
export const PLAN_CELL_CLASS: Record<PlanCellState, string> = {
  shortage: "bg-danger/15 text-danger",
  below_safety: "bg-warning/15 text-warning",
  covered: "bg-success/10 text-success",
}

export interface MrpSummary {
  shortageDays: number
  itemsShort: number
  belowSafetyDays: number
}

/** What-if supply overrides keyed `itemNo:dateIndex` (client-side only). */
export type SupplyOverrides = Record<string, number>

export function effectiveSupply(
  item: MrpItemGrid,
  overrides: SupplyOverrides,
): number[] {
  return item.supply.map(
    (value, i) => overrides[`${item.itemNo}:${i}`] ?? value,
  )
}

export function summarize(
  items: MrpItemGrid[],
  overrides: SupplyOverrides = {},
): MrpSummary {
  let shortageDays = 0
  let belowSafetyDays = 0
  const short = new Set<string>()
  for (const item of items) {
    for (const net of netSeries(item, effectiveSupply(item, overrides))) {
      if (net < 0) {
        shortageDays++
        short.add(item.itemNo)
      } else if (net < item.safetyStock) {
        belowSafetyDays++
      }
    }
  }
  return { shortageDays, itemsShort: short.size, belowSafetyDays }
}

/** Compact date header, e.g. "2026-07-16" -> "16 Jul". */
export function formatPlanDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  })
}
