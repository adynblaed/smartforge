import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ChevronDown, ChevronRight, PackageCheck } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { cn } from "@/lib/utils"
import { sf } from "@/smartforge/api"
import {
  HEX,
  KpiTile,
  Loading,
  metricTrend,
  OrderStatusBadge,
  orderStatusColor,
  PageHeader,
  Panel,
} from "@/smartforge/components"
import { POLL } from "@/smartforge/constants"
import type {
  InventoryItem,
  Page,
  PurchaseOrder,
  Supplier,
} from "@/smartforge/types"

export const Route = createFileRoute("/_layout/order-tracker")({
  validateSearch: (search: Record<string, unknown>): { po?: string } => ({
    po: typeof search.po === "string" ? search.po : undefined,
  }),
  component: OrderTrackerPage,
  head: () => ({ meta: [{ title: "Order Tracker - SmartForge" }] }),
})

// Formal lifecycle stages a purchase order moves through.
const STAGES = ["draft", "open", "received"] as const

// Plain-language explanation of a PO's latest status.
function statusExplanation(status: string): string {
  switch (status) {
    case "received":
      return "Goods for this purchase order have been received at Plant 1 — Receiving Dock and verified against the order. Inventory has been updated to reflect the delivery."
    case "open":
      return "This purchase order has been issued to the supplier and is in transit to the receiving dock. Awaiting delivery and goods receipt."
    case "draft":
      return "This purchase order is a draft, pending procurement approval before it is issued to the supplier."
    case "closed":
      return "This purchase order is closed and fully reconciled — no further action is required."
    default:
      return "Status details are unavailable for this purchase order."
  }
}

// Unified order-status color (Approved/Closed/received = green, open = blue,
// draft/in-review = yellow, denied = red).
const statusColor = orderStatusColor

// Routable stat tile wrapper (shared KPI affordance).
const STAT_CLS =
  "block rounded-xl outline-none transition hover:brightness-110 focus-visible:ring-2 focus-visible:ring-ring"

function OrderTrackerPage() {
  const { po: focusPo } = Route.useSearch()

  const { data, isLoading } = useQuery({
    queryKey: ["purchase-orders"],
    queryFn: () => sf.get<Page<PurchaseOrder>>("/purchase-orders"),
    refetchInterval: POLL.medium,
  })
  const { data: inv } = useQuery({
    queryKey: ["inventory"],
    queryFn: () => sf.get<Page<InventoryItem>>("/inventory"),
  })
  const { data: suppliers } = useQuery({
    queryKey: ["suppliers"],
    queryFn: () => sf.get<Page<Supplier>>("/suppliers"),
  })

  const pos = data?.data ?? []
  const itemById = new Map((inv?.data ?? []).map((i) => [i.id, i]))
  const supplierById = new Map(
    (suppliers?.data ?? []).map((s) => [s.id, s.name]),
  )

  const total = pos.reduce((a, p) => a + p.amount, 0)
  const count = (s: string) => pos.filter((p) => p.status === s).length
  const ready = pos.filter((p) => p.shop_floor_ready).length

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Order Tracker"
        description="The system of record for every purchase order surfaced in Global Operations — tracked through its lifecycle and cross-linked to supply chain and quoting."
      />

      {isLoading && <Loading label="Loading purchase orders…" />}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Link to="/supply-chain" className={STAT_CLS}>
          <KpiTile
            label="Purchase Orders"
            value={pos.length}
            {...metricTrend("pocount")}
          />
        </Link>
        <Link to="/supply-chain" className={STAT_CLS}>
          <KpiTile
            label="Total Value"
            value={`$${Math.round(total).toLocaleString()}`}
            accent={HEX.info}
            {...metricTrend("povalue")}
          />
        </Link>
        <Link to="/supply-chain" className={STAT_CLS}>
          <KpiTile
            label="Open"
            value={count("open")}
            accent={HEX.info}
            {...metricTrend("poopen")}
          />
        </Link>
        <Link to="/supply-chain" className={STAT_CLS}>
          <KpiTile
            label="Received"
            value={count("received")}
            accent={HEX.success}
            {...metricTrend("poreceived")}
          />
        </Link>
        <Link to="/supply-chain" className={STAT_CLS}>
          <KpiTile
            label="Shop-floor Ready"
            value={ready}
            accent={HEX.warning}
            {...metricTrend("poready")}
          />
        </Link>
      </div>

      <Panel title="Purchase Orders">
        <div className="space-y-3">
          {pos.length === 0 && (
            <p className="text-sm text-muted-foreground">No purchase orders.</p>
          )}
          {pos.map((po) => (
            <PORow
              key={po.id}
              po={po}
              item={
                po.inventory_item_id
                  ? itemById.get(po.inventory_item_id)
                  : undefined
              }
              supplierName={
                po.supplier_id ? supplierById.get(po.supplier_id) : undefined
              }
              focused={po.id === focusPo}
            />
          ))}
        </div>
      </Panel>
    </div>
  )
}

function PORow({
  po,
  item,
  supplierName,
  focused,
}: {
  po: PurchaseOrder
  item?: InventoryItem
  supplierName?: string
  focused: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(focused)
  // Which cross-reference category is expanded inline (stays on this PO screen).
  const [cat, setCat] = useState<string | null>(null)
  const toggleCat = (c: string) => setCat((p) => (p === c ? null : c))
  useEffect(() => {
    if (focused) {
      setOpen(true)
      ref.current?.scrollIntoView({ behavior: "smooth", block: "center" })
    }
  }, [focused])

  const color = statusColor(po.status)
  const stageIdx = STAGES.indexOf(po.status as (typeof STAGES)[number])

  return (
    <div
      ref={ref}
      className={cn(
        "overflow-hidden rounded-xl border transition-colors",
        focused ? "border-primary ring-2 ring-primary/40" : "bg-card",
      )}
    >
      {/* collapsed header (click to expand the formal PO) */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full flex-wrap items-center justify-between gap-3 p-4 text-left hover:bg-accent/40"
      >
        <div className="flex items-center gap-3">
          {open ? (
            <ChevronDown size={16} className="text-muted-foreground" />
          ) : (
            <ChevronRight size={16} className="text-muted-foreground" />
          )}
          <span
            className="flex size-9 items-center justify-center rounded-lg"
            style={{ background: `${color}22`, color }}
          >
            <PackageCheck size={18} />
          </span>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-base font-semibold">{po.po_number}</span>
              <OrderStatusBadge status={po.status} />
            </div>
            <div className="text-xs text-muted-foreground">
              {supplierName ?? "supplier"}
            </div>
          </div>
        </div>
        <div className="text-right">
          <div className="text-lg font-semibold tabular-nums">
            ${po.amount.toLocaleString()}
          </div>
          <div className="text-xs text-muted-foreground">
            {po.shop_floor_ready ? "shop-floor ready" : "in transit"}
          </div>
        </div>
      </button>

      {open && (
        <div className="border-t p-4">
          {/* lifecycle stepper */}
          <div className="flex items-center">
            {STAGES.map((stage, i) => (
              <div
                key={stage}
                className="flex flex-1 items-center last:flex-none"
              >
                <div className="flex flex-col items-center">
                  <div
                    className="flex size-6 items-center justify-center rounded-full text-[10px] font-bold text-white"
                    style={{
                      background: i <= stageIdx ? color : "var(--muted)",
                    }}
                  >
                    {i + 1}
                  </div>
                  <span className="mt-1 text-[10px] capitalize text-muted-foreground">
                    {stage}
                  </span>
                </div>
                {i < STAGES.length - 1 && (
                  <div
                    className="mx-1 h-0.5 flex-1"
                    style={{
                      background: i < stageIdx ? color : "var(--border)",
                    }}
                  />
                )}
              </div>
            ))}
          </div>

          {/* formal, officialized PO / receipt with a bill of materials */}
          <POReceipt po={po} item={item} supplierName={supplierName} />

          {/* cross references — expand inline (no navigation away from the PO) */}
          <div className="mt-4">
            <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
              <RefTile
                label="Material"
                value={item?.sku ?? (po.inventory_item_id ? "linked" : "—")}
                enabled={Boolean(po.inventory_item_id)}
                active={cat === "material"}
                onClick={() => toggleCat("material")}
              />
              <RefTile
                label="Job"
                value={po.job_id ? po.job_id.slice(0, 8) : "—"}
                enabled={Boolean(po.job_id)}
                active={cat === "job"}
                onClick={() => toggleCat("job")}
              />
              <RefTile
                label="Customer Order"
                value={
                  po.customer_order_id ? po.customer_order_id.slice(0, 8) : "—"
                }
                enabled={Boolean(po.customer_order_id)}
                active={cat === "order"}
                onClick={() => toggleCat("order")}
              />
              <RefTile
                label="Status"
                value={po.status}
                valueColor={statusColor(po.status)}
                enabled
                active={cat === "status"}
                onClick={() => toggleCat("status")}
              />
            </div>

            {cat && (
              <div className="mt-2 rounded-lg border bg-background p-3 text-xs">
                {cat === "material" && (
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <Field label="SKU" value={item?.sku ?? "—"} />
                    <Field
                      label="Material"
                      value={item?.name ?? "Linked material"}
                    />
                    <Field
                      label="On hand"
                      value={item ? `${item.quantity} ${"units"}` : "—"}
                    />
                    <Field
                      label="Stock status"
                      value={item?.below_threshold ? "Below threshold" : "OK"}
                    />
                    <div className="col-span-2 sm:col-span-4">
                      <Link
                        to="/supply-chain"
                        className="font-medium text-primary hover:underline"
                      >
                        Open in Supply Chain →
                      </Link>
                    </div>
                  </div>
                )}
                {cat === "job" && (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <Field label="Job ID" value={po.job_id ?? "—"} />
                    <Field label="Linked" value="Production job" />
                    <Field
                      label="PO status"
                      value={
                        po.shop_floor_ready ? "Shop-floor ready" : "In progress"
                      }
                    />
                    <div className="sm:col-span-3">
                      <Link
                        to="/quotes"
                        className="font-medium text-primary hover:underline"
                      >
                        Open in Quoting →
                      </Link>
                    </div>
                  </div>
                )}
                {cat === "order" && (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <Field
                      label="Customer Order ID"
                      value={po.customer_order_id ?? "—"}
                    />
                    <Field label="Linked" value="Customer order" />
                    <Field
                      label="PO value"
                      value={`$${po.amount.toLocaleString()}`}
                    />
                    <div className="sm:col-span-3">
                      <Link
                        to="/quotes"
                        className="font-medium text-primary hover:underline"
                      >
                        Open in Quoting →
                      </Link>
                    </div>
                  </div>
                )}
                {cat === "status" && (
                  <div className="space-y-3">
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                      <Field label="Current status" value={po.status} />
                      <Field
                        label="Stage"
                        value={`${Math.max(stageIdx + 1, 1)} of ${STAGES.length}`}
                      />
                      <Field
                        label="Shop floor"
                        value={po.shop_floor_ready ? "Ready" : "Pending"}
                      />
                    </div>
                    <p className="leading-relaxed text-muted-foreground">
                      {statusExplanation(po.status)}
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-0.5 break-words font-medium">{value}</div>
    </div>
  )
}

function POReceipt({
  po,
  item,
  supplierName,
}: {
  po: PurchaseOrder
  item?: InventoryItem
  supplierName?: string
}) {
  const docType =
    po.status === "received"
      ? "GOODS RECEIPT"
      : po.status === "open"
        ? "PURCHASE ORDER"
        : "DRAFT PURCHASE ORDER"
  const date = po.created_at
    ? new Date(po.created_at).toLocaleDateString()
    : "—"
  // Simulate a believable bill-of-materials line from the linked material.
  const qty = Math.max(1, Math.round(po.amount / 480))
  const unitPrice = po.amount / qty
  const note =
    po.status === "received"
      ? "Goods received and verified against this PO. Inventory updated."
      : po.status === "open"
        ? "Issued to supplier. Awaiting delivery to the receiving dock."
        : "Draft — pending procurement approval before issue."

  return (
    <div className="mt-4 rounded-lg border bg-background p-4 text-xs dark:border-white/15">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b pb-3 dark:border-white/20">
        <div>
          <div className="text-sm font-bold tracking-wide">{docType}</div>
          <div className="text-muted-foreground">
            SmartForge Manufacturing · Plant 1
          </div>
        </div>
        <div className="text-right">
          <div className="font-mono text-sm font-semibold">{po.po_number}</div>
          <div className="text-muted-foreground">{date}</div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 py-3 sm:grid-cols-3">
        <ReceiptField label="Supplier" value={supplierName ?? "—"} />
        <ReceiptField label="Ship to" value="Plant 1 — Receiving Dock" />
        <ReceiptField label="Status" value={po.status} />
      </div>

      <table className="w-full">
        <thead className="text-left text-muted-foreground">
          <tr className="border-y dark:border-white/20">
            <th className="py-1.5 pr-2">Item</th>
            <th className="py-1.5 pr-2">Description</th>
            <th className="py-1.5 pr-2 text-right">Qty</th>
            <th className="py-1.5 pr-2 text-right">Unit</th>
            <th className="py-1.5 text-right">Amount</th>
          </tr>
        </thead>
        <tbody>
          <tr className="border-b dark:border-white/10">
            <td className="py-1.5 pr-2 font-mono">{item?.sku ?? "MISC-001"}</td>
            <td className="py-1.5 pr-2">{item?.name ?? "Procured material"}</td>
            <td className="py-1.5 pr-2 text-right tabular-nums">{qty}</td>
            <td className="py-1.5 pr-2 text-right tabular-nums">
              ${unitPrice.toFixed(2)}
            </td>
            <td className="py-1.5 text-right tabular-nums">
              ${po.amount.toLocaleString()}
            </td>
          </tr>
        </tbody>
      </table>

      <div className="mt-2 flex justify-end">
        <div className="w-48 space-y-1">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Subtotal</span>
            <span className="tabular-nums">${po.amount.toLocaleString()}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Tax / handling</span>
            <span className="tabular-nums">$0.00</span>
          </div>
          <div className="flex justify-between border-t pt-1 font-semibold dark:border-white/20">
            <span>Total</span>
            <span className="tabular-nums">${po.amount.toLocaleString()}</span>
          </div>
        </div>
      </div>

      <p className="mt-3 border-t pt-2 text-[11px] text-muted-foreground dark:border-white/10">
        {note}
      </p>
    </div>
  )
}

function ReceiptField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-0.5 font-medium capitalize">{value}</div>
    </div>
  )
}

// A cross-reference tile. Enabled tiles expand inline (they no longer navigate
// to a new page); disabled tiles are static.
function RefTile({
  label,
  value,
  valueColor,
  enabled,
  active,
  onClick,
}: {
  label: string
  value: string
  valueColor?: string
  enabled: boolean
  active?: boolean
  onClick?: () => void
}) {
  const body = (
    <>
      <div className="flex items-center justify-between text-muted-foreground">
        <span>{label}</span>
        {enabled && (
          <ChevronDown
            size={12}
            className={cn("transition-transform", active && "rotate-180")}
          />
        )}
      </div>
      <div
        className="mt-0.5 truncate font-semibold capitalize tabular-nums"
        style={valueColor ? { color: valueColor } : undefined}
      >
        {value}
      </div>
    </>
  )
  if (!enabled)
    return <div className="rounded-md border bg-muted/30 p-2">{body}</div>
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md border bg-muted/30 p-2 text-left transition-colors hover:border-primary hover:bg-accent",
        active && "border-primary bg-accent",
      )}
    >
      {body}
    </button>
  )
}
