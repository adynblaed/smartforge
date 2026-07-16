import { createFileRoute } from "@tanstack/react-router"
import { RotateCcw } from "lucide-react"
import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { HEX, KpiTile, PageHeader, Panel } from "@/smartforge/components"
import {
  buildGrid,
  cellState,
  effectiveSupply,
  formatPlanDate,
  type MrpItemGrid,
  netSeries,
  PLAN_CELL_CLASS,
  type SupplyOverrides,
  summarize,
} from "@/smartforge/mrp"
import { formatWhen } from "@/smartforge/platform"
import type {
  MrpPlanRow,
  WarehouseRowsResponse,
} from "@/smartforge/platformTypes"
import { REFRESH_SLOW, Section, usePlatform } from "@/smartforge/platformUi"

export const Route = createFileRoute("/_layout/mrp")({
  component: MrpPage,
  head: () => ({ meta: [{ title: "MRP - SmartForge" }] }),
})

// The certified time-phased plan: item × date grain, ordered so the pivot
// is stable. 1000 covers the horizon (items × ~15 buckets) comfortably.
const PLAN_PATH =
  "/warehouse/datasets/api.api_mrp_supply_plan?limit=1000&order_by=plan_date&order_dir=asc"

function MrpPage() {
  const plan = usePlatform<WarehouseRowsResponse<MrpPlanRow>>(
    ["mrp-supply-plan"],
    PLAN_PATH,
    REFRESH_SLOW,
  )
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="MRP"
        description="Time-phased material requirements planning from the governed supply plan: demand, scheduled supply, and projected net inventory per item per day."
        actions={
          <Badge variant="outline" className="text-xs">
            certified · api.api_mrp_supply_plan
          </Badge>
        }
      />
      <Section query={plan}>
        {(res) => (
          <MrpPlanner rows={res.data} generatedAt={res.meta.generated_at} />
        )}
      </Section>
    </div>
  )
}

function MrpPlanner({
  rows,
  generatedAt,
}: {
  rows: MrpPlanRow[]
  generatedAt: string
}) {
  const grid = useMemo(() => buildGrid(rows), [rows])
  const [overrides, setOverrides] = useState<SupplyOverrides>({})
  const [itemFilter, setItemFilter] = useState("")

  const visibleItems = useMemo(() => {
    const needle = itemFilter.trim().toLowerCase()
    if (!needle) return grid.items
    return grid.items.filter(
      (item) =>
        item.itemNo.toLowerCase().includes(needle) ||
        item.description.toLowerCase().includes(needle),
    )
  }, [grid.items, itemFilter])

  const summary = useMemo(
    () => summarize(visibleItems, overrides),
    [visibleItems, overrides],
  )
  const whatIfActive = Object.keys(overrides).length > 0

  return (
    <div className="flex flex-col gap-6">
      {/* summary cards, mirroring the planning-sheet KPIs */}
      <div className="grid gap-4 sm:grid-cols-3">
        <KpiTile
          label="Shortage Days"
          value={summary.shortageDays}
          hint="item-days with projected net below zero"
          accent={summary.shortageDays > 0 ? HEX.danger : HEX.success}
        />
        <KpiTile
          label="Items Short"
          value={summary.itemsShort}
          hint="distinct items with any shortage day"
          accent={summary.itemsShort > 0 ? HEX.danger : HEX.success}
        />
        <KpiTile
          label="Below Safety Stock"
          value={summary.belowSafetyDays}
          hint="item-days under the safety-stock floor"
          accent={summary.belowSafetyDays > 0 ? HEX.warning : HEX.success}
        />
      </div>

      <Panel
        title="Supply Planning Grid"
        action={
          <div className="flex items-center gap-2">
            <Input
              className="h-8 w-52"
              placeholder="Filter items…"
              value={itemFilter}
              onChange={(event) => setItemFilter(event.target.value)}
            />
            <Button
              variant="outline"
              size="sm"
              disabled={!whatIfActive}
              onClick={() => setOverrides({})}
            >
              <RotateCcw className="size-3.5" /> Reset what-if
            </Button>
          </div>
        }
      >
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <span className="inline-block size-3 rounded-sm bg-danger/30" />
              Shortage (net &lt; 0)
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block size-3 rounded-sm bg-warning/30" />
              Below safety stock
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block size-3 rounded-sm bg-success/25" />
              Covered
            </span>
            <span className="ml-auto">
              Supply cells accept local what-if edits — nothing is written back
              {whatIfActive && " · what-if active"}
            </span>
          </div>
          <div className="max-h-[36rem] overflow-auto rounded-md border">
            <table className="border-collapse text-xs">
              <thead className="sticky top-0 z-20 bg-muted/95 backdrop-blur">
                <tr>
                  {[
                    "Item",
                    "Description",
                    "UOM",
                    "On hand",
                    "Safety",
                    "Row",
                  ].map((label, i) => (
                    <th
                      key={label}
                      className={cn(
                        "whitespace-nowrap border-b border-r px-2 py-2 text-left font-semibold uppercase tracking-wide text-muted-foreground",
                        i === 0 && "sticky left-0 z-30 bg-muted/95",
                        (label === "On hand" || label === "Safety") &&
                          "text-right",
                      )}
                    >
                      {label}
                    </th>
                  ))}
                  {grid.dates.map((date) => (
                    <th
                      key={date}
                      className="whitespace-nowrap border-b border-r px-2 py-2 text-right font-semibold text-muted-foreground last:border-r-0"
                      title={date}
                    >
                      {formatPlanDate(date)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visibleItems.length === 0 && (
                  <tr>
                    <td
                      colSpan={6 + grid.dates.length}
                      className="px-3 py-8 text-center text-sm text-muted-foreground"
                    >
                      No items in the plan match this filter.
                    </td>
                  </tr>
                )}
                {visibleItems.map((item) => (
                  <ItemRows
                    key={item.itemNo}
                    item={item}
                    overrides={overrides}
                    onSupplyEdit={(dayIndex, value) =>
                      setOverrides((current) => {
                        const key = `${item.itemNo}:${dayIndex}`
                        const next = { ...current }
                        if (value === null) delete next[key]
                        else next[key] = value
                        return next
                      })
                    }
                  />
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-muted-foreground">
            Net inventory rolls forward: each day = prior net − demand + supply,
            seeded from current on-hand. Plan as of {formatWhen(generatedAt)} ·{" "}
            {grid.items.length} items · {grid.dates.length}-day horizon.
          </p>
        </div>
      </Panel>
    </div>
  )
}

function ItemRows({
  item,
  overrides,
  onSupplyEdit,
}: {
  item: MrpItemGrid
  overrides: SupplyOverrides
  onSupplyEdit: (dayIndex: number, value: number | null) => void
}) {
  const supply = effectiveSupply(item, overrides)
  const net = netSeries(item, supply)
  const infoCell = (content: string, extra?: string) => (
    <td className={cn("border-r px-2 py-1 text-muted-foreground", extra)}>
      {content}
    </td>
  )
  return (
    <>
      {/* demand row (carries the item identity) */}
      <tr className="border-t-2 border-border">
        <td className="sticky left-0 z-10 border-r bg-background px-2 py-1 font-medium shadow-[inset_3px_0_0] shadow-primary/60">
          {item.itemNo}
        </td>
        {infoCell(item.description, "max-w-[220px] truncate")}
        {infoCell(item.uom)}
        <td className="border-r px-2 py-1 text-right tabular-nums">
          {item.openingQty.toLocaleString()}
        </td>
        <td className="border-r px-2 py-1 text-right tabular-nums">
          {item.safetyStock.toLocaleString()}
        </td>
        {infoCell("Demand")}
        {item.demand.map((value, i) => (
          <td
            key={`d-${item.itemNo}-${item.demand.length - i}`}
            className="border-r px-2 py-1 text-right tabular-nums last:border-r-0"
          >
            {value ? value.toLocaleString() : "–"}
          </td>
        ))}
      </tr>
      {/* supply row (editable, local only) */}
      <tr>
        <td className="sticky left-0 z-10 border-r bg-background shadow-[inset_3px_0_0] shadow-primary/60" />
        <td className="border-r" />
        <td className="border-r" />
        <td className="border-r" />
        <td className="border-r" />
        {infoCell("Supply")}
        {supply.map((value, i) => (
          <td
            key={`s-${item.itemNo}-${supply.length - i}`}
            className="border-r p-0.5 text-right last:border-r-0"
          >
            <input
              className={cn(
                "h-6 w-16 rounded border bg-muted/40 px-1 text-right text-xs tabular-nums focus:outline-none focus:ring-1 focus:ring-ring",
                overrides[`${item.itemNo}:${i}`] !== undefined &&
                  "border-info text-info",
              )}
              inputMode="numeric"
              aria-label={`What-if supply for ${item.itemNo}`}
              value={value || ""}
              placeholder="+"
              onChange={(event) => {
                const digits = event.target.value.replace(/[^0-9]/g, "")
                onSupplyEdit(i, digits === "" ? 0 : Number(digits))
              }}
            />
          </td>
        ))}
      </tr>
      {/* projected net row */}
      <tr>
        <td className="sticky left-0 z-10 border-r bg-background shadow-[inset_3px_0_0] shadow-primary/60" />
        <td className="border-r" />
        <td className="border-r" />
        <td className="border-r" />
        <td className="border-r" />
        {infoCell("Net")}
        {net.map((value, i) => (
          <td
            key={`n-${item.itemNo}-${net.length - i}`}
            className={cn(
              "border-r px-2 py-1 text-right font-semibold tabular-nums last:border-r-0",
              PLAN_CELL_CLASS[cellState(value, item.safetyStock)],
            )}
          >
            {value.toLocaleString()}
          </td>
        ))}
      </tr>
    </>
  )
}
