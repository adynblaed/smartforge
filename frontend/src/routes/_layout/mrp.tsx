import { useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { RefreshCw, RotateCcw, X } from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useFeatures } from "@/hooks/useFeatures"
import { cn } from "@/lib/utils"
import { sf } from "@/smartforge/api"
import { HEX, KpiTile, PageHeader, Panel } from "@/smartforge/components"
import { SYNC_REFRESH_DELAY_MS } from "@/smartforge/constants"
import { genealogyLevelLabel } from "@/smartforge/explorer"
import {
  buildGrid,
  cellState,
  effectiveSupply,
  formatPlanDate,
  type MrpItemGrid,
  netSeries,
  PLAN_CELL_CLASS,
  planQty,
  type SupplyOverrides,
  summarize,
} from "@/smartforge/mrp"
import { formatWhen } from "@/smartforge/platform"
import type {
  ApiWorkOrderRow,
  MrpPlanRow,
  WarehouseRowsResponse,
} from "@/smartforge/platformTypes"
import {
  MiniTable,
  REFRESH_SLOW,
  Section,
  usePlatform,
} from "@/smartforge/platformUi"
import { queueTableSync } from "@/smartforge/SyncNowButton"

export const Route = createFileRoute("/_layout/mrp")({
  component: MrpPage,
  head: () => ({ meta: [{ title: "MRP - SmartForge" }] }),
})

// The certified time-phased plan: item × date grain, ordered so the pivot
// is stable. 1000 covers the horizon (items × ~15 buckets) comfortably.
const PLAN_PATH =
  "/warehouse/datasets/mrp_supply_plan?limit=1000&order_by=plan_date&order_dir=asc"

function MrpPage() {
  const plan = usePlatform<WarehouseRowsResponse<MrpPlanRow>>(
    ["mrp-supply-plan"],
    PLAN_PATH,
    REFRESH_SLOW,
  )
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Material Requirements Planner"
        description="Time-phased material requirements planning from the governed supply plan: demand, scheduled supply, and projected net inventory per item per day."
        actions={
          <Badge variant="outline" className="text-xs">
            certified · mrp_supply_plan (v1)
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

// The omega tables the MRP mart derives from — one click queues them all
// (the server's sync worker drains sequentially, so no trigger conflicts).
const MRP_SOURCE_TABLES = [
  "OMEGA.MRP_PEGGING",
  "OMEGA.INVENTORY_ITEMS",
  "OMEGA.SALES_ORDER_LINES",
  "OMEGA.WORK_ORDERS",
]

function MrpSyncButton() {
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState(false)
  const syncSources = async () => {
    setBusy(true)
    try {
      for (const table of MRP_SOURCE_TABLES) await queueTableSync(table)
      toast.success(`Queued ${MRP_SOURCE_TABLES.length} MRP source tables`)
      // The plan mart rebuilds after the pipeline lands; refresh then
      // (longer than the single-table delay — four tables queue here).
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["data-platform"] })
      }, SYNC_REFRESH_DELAY_MS * 2.5)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Sync failed")
    } finally {
      setBusy(false)
    }
  }
  return (
    <Button
      variant="outline"
      size="sm"
      disabled={busy}
      title={`Sync the MRP source tables (${MRP_SOURCE_TABLES.join(", ")})`}
      onClick={syncSources}
    >
      <RefreshCw className={cn("size-3.5", busy && "animate-spin")} /> Sync
    </Button>
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
  // Grid entity → drill-down correlation (Supply Planning Tables below).
  const [selectedItem, setSelectedItem] = useState<string | null>(null)
  const { enabled: featureEnabled } = useFeatures()
  const canSync = featureEnabled("platform_ops")

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
            {canSync && <MrpSyncButton />}
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
                    selected={selectedItem === item.itemNo}
                    onSelect={() =>
                      setSelectedItem((current) =>
                        current === item.itemNo ? null : item.itemNo,
                      )
                    }
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
            {grid.items.length} items · {grid.dates.length}-day horizon. Click
            an item row to open its Supply Planning Tables below.
          </p>
        </div>
      </Panel>

      <SupplyPlanningTables
        item={selectedItem}
        rows={rows}
        onClear={() => setSelectedItem(null)}
      />
    </div>
  )
}

/* ------------------------------------------------ supply planning tables */

const PLAN_STATUS_CLASS: Record<MrpPlanRow["plan_status"], string> = {
  shortage: "text-danger",
  below_safety: "text-warning",
  covered: "text-success",
}

// Drill-down for one grid entity: its governed MRP plan records plus the
// related work orders, in the same read-only table grammar as the Work
// Orders Explorer (certified contracts, bounded queries, no writes).
function SupplyPlanningTables({
  item,
  rows,
  onClear,
}: {
  item: string | null
  rows: MrpPlanRow[]
  onClear: () => void
}) {
  const planRows = useMemo(
    () => rows.filter((r) => r.item_no === item),
    [rows, item],
  )
  const workOrders = useQuery({
    queryKey: ["mrp", "item-work-orders", item],
    queryFn: () =>
      sf.get<WarehouseRowsResponse<ApiWorkOrderRow>>(
        `/warehouse/datasets/work_orders?item_no=${encodeURIComponent(
          item ?? "",
        )}&order_by=due_at&order_dir=asc&limit=100`,
      ),
    enabled: !!item,
    retry: false,
  })

  return (
    <Panel
      title="Supply Planning Tables"
      action={
        item ? (
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-xs">
              item {item}
            </Badge>
            <Button
              variant="ghost"
              size="icon"
              className="size-7"
              aria-label="Clear selection"
              onClick={onClear}
            >
              <X className="size-3.5" />
            </Button>
          </div>
        ) : undefined
      }
    >
      {!item ? (
        <div className="rounded-lg border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
          Click any item in the Supply Planning Grid above to see its MRP
          records and the work orders driving them.
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <h3 className="text-sm font-medium">MRP records</h3>
            <MiniTable
              rows={planRows}
              rowKey={(r) => r.plan_row_key}
              empty="No plan records for this item."
              cols={[
                {
                  key: "date",
                  label: "Plan date",
                  render: (r) => formatPlanDate(r.plan_date),
                },
                {
                  key: "demand",
                  label: "Demand",
                  align: "right",
                  render: (r) => planQty(r.demand_qty).toLocaleString(),
                },
                {
                  key: "supply",
                  label: "Supply",
                  align: "right",
                  render: (r) => planQty(r.supply_qty).toLocaleString(),
                },
                {
                  key: "wos",
                  label: "Supply WOs",
                  align: "right",
                  render: (r) => planQty(r.supply_work_orders).toLocaleString(),
                },
                {
                  key: "net",
                  label: "Projected net",
                  align: "right",
                  render: (r) => (
                    <span
                      className={cn(
                        "font-semibold",
                        PLAN_STATUS_CLASS[r.plan_status],
                      )}
                    >
                      {planQty(r.projected_balance).toLocaleString()}
                    </span>
                  ),
                },
                {
                  key: "safety",
                  label: "Safety",
                  align: "right",
                  render: (r) => planQty(r.safety_stock).toLocaleString(),
                },
                {
                  key: "status",
                  label: "Status",
                  render: (r) => (
                    <span className={PLAN_STATUS_CLASS[r.plan_status]}>
                      {r.plan_status.replace(/_/g, " ")}
                      {r.exception_desc && (
                        <span className="ml-1 text-xs text-muted-foreground">
                          · {r.exception_desc}
                        </span>
                      )}
                    </span>
                  ),
                },
              ]}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <h3 className="text-sm font-medium">Related work orders</h3>
            <Section query={workOrders}>
              {(res) => (
                <>
                  <MiniTable
                    rows={res.data}
                    rowKey={(row) => row.work_order_uid}
                    empty="No work orders reference this item."
                    cols={[
                      {
                        key: "wo",
                        label: "Work Order",
                        render: (row) => (
                          <div>
                            <div className="font-medium">{row.wo_number}</div>
                            <div
                              className="max-w-[220px] truncate text-xs text-muted-foreground"
                              title={row.title ?? undefined}
                            >
                              {row.title}
                            </div>
                          </div>
                        ),
                      },
                      {
                        key: "genealogy",
                        label: "Genealogy",
                        render: (row) => (
                          <Badge variant="outline" className="text-xs">
                            {genealogyLevelLabel(row.genealogy_depth)}
                          </Badge>
                        ),
                      },
                      {
                        key: "qty",
                        label: "Qty",
                        align: "right",
                        render: (row) =>
                          `${Number(row.qty_completed ?? 0)}/${Number(row.qty_ordered ?? 0)}`,
                      },
                      {
                        key: "status",
                        label: "Status",
                        render: (row) => row.status ?? "—",
                      },
                      {
                        key: "machine",
                        label: "Machine",
                        render: (row) => row.machine_code ?? "—",
                      },
                      {
                        key: "due",
                        label: "Due",
                        render: (row) => formatWhen(row.due_at),
                      },
                    ]}
                  />
                  <p className="text-xs text-muted-foreground">
                    {res.count.toLocaleString()} work orders for {item} ·
                    certified contract work_orders (v1)
                  </p>
                </>
              )}
            </Section>
          </div>
        </div>
      )}
    </Panel>
  )
}

function ItemRows({
  item,
  selected,
  onSelect,
  overrides,
  onSupplyEdit,
}: {
  item: MrpItemGrid
  selected: boolean
  onSelect: () => void
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
      {/* demand row (carries the item identity; click = drill down) */}
      <tr
        className={cn(
          "cursor-pointer border-t-2 border-border hover:bg-accent/40",
          selected && "bg-primary/10",
        )}
        onClick={onSelect}
        title={`Open Supply Planning Tables for ${item.itemNo}`}
      >
        <td
          className={cn(
            "sticky left-0 z-10 border-r bg-background px-2 py-1 font-medium shadow-[inset_3px_0_0] shadow-primary/60",
            selected && "bg-primary/15",
          )}
        >
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
