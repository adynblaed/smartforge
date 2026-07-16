import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  CalendarClock,
  CalendarDays,
  Check,
  ChevronRight,
  Pencil,
  X,
} from "lucide-react"
import type { ReactNode } from "react"
import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { cn } from "@/lib/utils"
import { sf } from "@/smartforge/api"
import {
  KpiTile,
  metricTrend,
  OrderStatusBadge,
  PageHeader,
  StatusBadge,
  userDisplayName,
} from "@/smartforge/components"
import type {
  InventoryItem,
  Machine,
  MaterialReorder,
  Page,
  PurchaseOrder,
  Supplier,
} from "@/smartforge/types"

// A panel that collapses/expands its body, so the page reads as a stack of
// scannable sections with the actionable ones (PO ops, risk, reorders) on top.
function CollapsiblePanel({
  title,
  count,
  defaultOpen = true,
  children,
}: {
  title: string
  count?: number
  defaultOpen?: boolean
  children: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <Card>
      <CardHeader className="space-y-0 p-0">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center justify-between gap-2 px-6 py-4 text-left"
        >
          <CardTitle className="flex items-center gap-2 text-base">
            <ChevronRight
              size={16}
              className={cn(
                "text-muted-foreground transition-transform",
                open && "rotate-90",
              )}
            />
            {title}
            {count !== undefined && (
              <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-normal text-muted-foreground">
                {count}
              </span>
            )}
          </CardTitle>
        </button>
      </CardHeader>
      {open && <CardContent>{children}</CardContent>}
    </Card>
  )
}

export const Route = createFileRoute("/_layout/supply-chain")({
  component: SupplyChainPage,
  head: () => ({ meta: [{ title: "Supply Chain - SmartForge" }] }),
})

interface Risks {
  low_stock_materials: InventoryItem[]
  delayed_suppliers: { id: string; name: string; status: string }[]
  suggested_reorders: string[]
}

// Which row the shared right-hand detail pane is showing.
type Sel =
  | { kind: "po"; id: string }
  | { kind: "inventory"; id: string }
  | { kind: "supplier"; id: string }
  | { kind: "reorder"; id: string } // id = SKU

// Routable KPI tile wrapper.
const SC_STAT_CLS =
  "block rounded-xl outline-none transition hover:brightness-110 focus-visible:ring-2 focus-visible:ring-ring"

// ---- Scheduled reorders -----------------------------------------------------
// There is no dedicated reorder entity in the backend — reorders are *derived*
// from below-threshold inventory. We schedule them deterministically (today vs.
// the upcoming week) and let the operator approve / adjust / cancel each one
// (tracked client-side, so the page is the system of action for the demo).

type ReorderAction = "approve" | "adjust" | "cancel"
type ReorderStatus = "pending" | "approved" | "adjusted" | "cancelled"

interface ReorderState {
  status: ReorderStatus
  qty: number
  reason?: string
}

interface ScheduledReorder {
  item: InventoryItem
  /** Machine/line the material feeds — derived from the SKU/name. */
  machineName: string
  machineCode: string
  line: string
  /** Suggested order quantity to bring stock back to par. */
  suggestedQty: number
  /** 0 = today, 1-6 = day offset within the upcoming week. */
  dayOffset: number
  date: Date
}

const ACTION_NOUN: Record<ReorderAction, string> = {
  approve: "Approval",
  adjust: "Edit",
  cancel: "Cancellation",
}

// Stable string hash → used to spread non-critical reorders across the week.
function hashStr(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return Math.abs(h)
}

// SKU/material → the machine type it's most relevant to.
const SKU_RELEVANCE: { re: RegExp; type: string }[] = [
  { re: /enc|joint|jnt|encoder|arm|robot/i, type: "robotic_arm" },
  { re: /hyd|seal|press|air|filter|flt/i, type: "hydraulic_press" },
]

function buildSchedule(
  items: InventoryItem[],
  machines: Machine[],
): ScheduledReorder[] {
  // Friendly "Line A/B/C…" labels for the distinct line ids.
  const lineLabel = new Map<string, string>()
  machines.forEach((m) => {
    if (m.line_id && !lineLabel.has(m.line_id))
      lineLabel.set(
        m.line_id,
        `Line ${String.fromCharCode(65 + lineLabel.size)}`,
      )
  })
  const cnc = machines.find((m) => m.machine_type === "cnc_mill")

  return items.map((item) => {
    const hay = `${item.sku} ${item.name}`
    let machine: Machine | undefined
    for (const r of SKU_RELEVANCE) {
      if (r.re.test(hay)) {
        machine = machines.find((m) => m.machine_type === r.type)
        if (machine) break
      }
    }
    machine = machine ?? cnc ?? machines[0]

    const ratio =
      item.reorder_threshold > 0 ? item.quantity / item.reorder_threshold : 0
    // Critically low (≤ half of par) → reorder today; the rest across the week.
    const dayOffset = ratio <= 0.5 ? 0 : 1 + (hashStr(item.sku) % 6)
    const date = new Date()
    date.setHours(0, 0, 0, 0)
    date.setDate(date.getDate() + dayOffset)

    return {
      item,
      machineName: machine?.name ?? "Unassigned",
      machineCode: machine?.code ?? "—",
      line:
        machine?.line_id && lineLabel.has(machine.line_id)
          ? lineLabel.get(machine.line_id)!
          : "Unassigned",
      suggestedQty: Math.max(
        item.reorder_threshold * 2 - item.quantity,
        item.reorder_threshold,
      ),
      dayOffset,
      date,
    }
  })
}

const fmtSchedDate = (d: Date) =>
  d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  })

const REORDER_BADGE: Record<
  Exclude<ReorderStatus, "pending">,
  { label: string; color: string }
> = {
  approved: { label: "Approved", color: "var(--success)" },
  adjusted: { label: "Adjusted", color: "var(--info)" },
  cancelled: { label: "Cancelled", color: "var(--danger)" },
}

function SupplyChainPage() {
  const { data: inv } = useQuery({
    queryKey: ["inventory"],
    queryFn: () => sf.get<Page<InventoryItem>>("/inventory"),
  })
  const { data: risks } = useQuery({
    queryKey: ["sc-risks"],
    queryFn: () => sf.get<Risks>("/supply-chain/risks"),
  })
  const { data: pos } = useQuery({
    queryKey: ["purchase-orders"],
    queryFn: () => sf.get<Page<PurchaseOrder>>("/purchase-orders"),
  })
  const { data: suppliers } = useQuery({
    queryKey: ["suppliers"],
    queryFn: () => sf.get<Page<Supplier>>("/suppliers"),
  })
  const { data: machines } = useQuery({
    queryKey: ["machines"],
    queryFn: () => sf.get<Page<Machine>>("/machines"),
  })

  const supplierById = new Map(
    (suppliers?.data ?? []).map((s) => [s.id, s.name]),
  )
  const supplierFull = new Map((suppliers?.data ?? []).map((s) => [s.id, s]))
  const itemById = new Map((inv?.data ?? []).map((i) => [i.id, i]))
  const poById = new Map((pos?.data ?? []).map((p) => [p.id, p]))
  const [poView, setPoView] = useState<"list" | "board">("list")
  // Selected row → shown in the right detail pane (master-detail like Tickets).
  const [sel, setSel] = useState<Sel | null>(null)

  // Scheduled reorders derived from below-threshold inventory + machine context.
  const schedule = useMemo(
    () => buildSchedule(risks?.low_stock_materials ?? [], machines?.data ?? []),
    [risks?.low_stock_materials, machines?.data],
  )
  const todayReorders = schedule.filter((s) => s.dayOffset === 0)
  const weekReorders = schedule
    .filter((s) => s.dayOffset > 0)
    .sort((a, b) => a.dayOffset - b.dayOffset)

  // Persisted reorder decisions (approve / adjust / cancel) — one per SKU.
  const { data: reorderData } = useQuery({
    queryKey: ["reorders"],
    queryFn: () => sf.get<Page<MaterialReorder>>("/supply-chain/reorders"),
  })
  const persisted = new Map((reorderData?.data ?? []).map((r) => [r.sku, r]))

  const [dialog, setDialog] = useState<{
    action: ReorderAction
    sku: string
  } | null>(null)
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { user } = useAuth()
  const username = userDisplayName(user)
  const queryClient = useQueryClient()

  const actionMutation = useMutation({
    mutationFn: (body: {
      sku: string
      action: ReorderAction
      quantity: number
      reason?: string
      machine_code?: string
      line?: string
      scheduled_for?: string
      inventory_item_id?: string
    }) => sf.post<MaterialReorder>("/supply-chain/reorders", body),
    onSuccess: (row, vars) => {
      queryClient.invalidateQueries({ queryKey: ["reorders"] })
      const verb =
        vars.action === "approve"
          ? "approved"
          : vars.action === "cancel"
            ? "cancelled"
            : "edited"
      showSuccessToast(`Reorder for ${row.sku} ${verb} by ${username}.`)
      setDialog(null)
    },
    onError: () =>
      showErrorToast("Could not save the reorder action. Please retry."),
  })

  const reorderState = (r: ScheduledReorder): ReorderState => {
    const p = persisted.get(r.item.sku)
    return p
      ? { status: p.status, qty: p.quantity, reason: p.reason ?? undefined }
      : { status: "pending", qty: r.suggestedQty }
  }

  const dialogReorder = dialog
    ? schedule.find((s) => s.item.sku === dialog.sku)
    : undefined

  const applyAction = (
    action: ReorderAction,
    sku: string,
    qty: number,
    reason?: string,
  ) => {
    const r = schedule.find((s) => s.item.sku === sku)
    actionMutation.mutate({
      sku,
      action,
      quantity: qty,
      reason,
      machine_code: r?.machineCode,
      line: r?.line,
      scheduled_for: r?.date.toISOString(),
      inventory_item_id: r?.item.id,
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Supply Chain"
        description="Inventory, supplier risk, reorder recommendations, and live PO operations linked to the Order Tracker."
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <Link to="/order-tracker" className={SC_STAT_CLS}>
          <KpiTile
            label="SKUs Tracked"
            value={inv?.count ?? 0}
            {...metricTrend("skus")}
          />
        </Link>
        <Link to="/order-tracker" className={SC_STAT_CLS}>
          <KpiTile
            label="Below Threshold"
            value={risks?.low_stock_materials.length ?? 0}
            accent="var(--warning)"
            {...metricTrend("belowthreshold")}
          />
        </Link>
        <Link to="/order-tracker" className={SC_STAT_CLS}>
          <KpiTile
            label="Delayed Suppliers"
            value={risks?.delayed_suppliers.length ?? 0}
            accent="var(--danger)"
            {...metricTrend("delayedsuppliers")}
          />
        </Link>
      </div>

      {/* master-detail: tables (left) + a shared detail pane (right) */}
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,400px)]">
        <div className="space-y-6">
          <CollapsiblePanel
            title="Supplier Risk"
            count={suppliers?.data.length}
          >
            <ul className="space-y-1">
              {suppliers?.data.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => setSel({ kind: "supplier", id: s.id })}
                    className={cn(
                      "-mx-2 flex w-full items-center justify-between rounded-md px-2 py-2 text-left text-sm transition-colors",
                      sel?.kind === "supplier" && sel.id === s.id
                        ? "bg-accent"
                        : "hover:bg-accent/50",
                    )}
                  >
                    <span>{s.name}</span>
                    <span className="flex items-center gap-3 text-xs text-muted-foreground">
                      <span>{s.lead_time_days}d lead</span>
                      <StatusBadge
                        value={s.status === "ok" ? "running" : "high"}
                      />
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </CollapsiblePanel>

          <CollapsiblePanel title="Scheduled Reorders" count={schedule.length}>
            {schedule.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                All materials above threshold — nothing scheduled.
              </p>
            ) : (
              <div className="space-y-5">
                <ReorderSection
                  icon={<CalendarDays size={15} className="text-info" />}
                  title="Today"
                  subtitle={fmtSchedDate(new Date())}
                  reorders={todayReorders}
                  reorderState={reorderState}
                  onAction={(action, sku) => setDialog({ action, sku })}
                  onSelect={(sku) => setSel({ kind: "reorder", id: sku })}
                  selectedSku={sel?.kind === "reorder" ? sel.id : null}
                />
                <ReorderSection
                  icon={
                    <CalendarClock
                      size={15}
                      className="text-muted-foreground"
                    />
                  }
                  title="Upcoming Week"
                  subtitle={`${weekReorders.length} scheduled`}
                  reorders={weekReorders}
                  reorderState={reorderState}
                  onAction={(action, sku) => setDialog({ action, sku })}
                  onSelect={(sku) => setSel({ kind: "reorder", id: sku })}
                  selectedSku={sel?.kind === "reorder" ? sel.id : null}
                  showDate
                />
              </div>
            )}
          </CollapsiblePanel>

          <CollapsiblePanel title="Inventory" count={inv?.count}>
            <table className="w-full text-sm">
              <thead className="text-left text-muted-foreground">
                <tr className="border-b">
                  <th className="py-2 pr-4">SKU</th>
                  <th className="py-2 pr-4">Material</th>
                  <th className="py-2 pr-4">Qty</th>
                  <th className="py-2 pr-4">Reorder At</th>
                  <th className="py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {inv?.data.map((i) => (
                  <tr
                    key={i.id}
                    onClick={() => setSel({ kind: "inventory", id: i.id })}
                    className={cn(
                      "cursor-pointer border-b transition-colors hover:bg-accent/40",
                      sel?.kind === "inventory" &&
                        sel.id === i.id &&
                        "bg-accent",
                    )}
                  >
                    <td className="py-2 pr-4 font-medium">{i.sku}</td>
                    <td className="py-2 pr-4">{i.name}</td>
                    <td className="py-2 pr-4 tabular-nums">{i.quantity}</td>
                    <td className="py-2 pr-4 tabular-nums">
                      {i.reorder_threshold}
                    </td>
                    <td className="py-2">
                      <StatusBadge
                        value={i.below_threshold ? "high" : "running"}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CollapsiblePanel>

          <CollapsiblePanel
            title="PO Operations"
            count={pos?.data.length}
            defaultOpen={false}
          >
            <div className="mb-3 inline-flex rounded-lg border bg-muted/30 p-0.5 text-xs">
              {(
                [
                  ["list", "List"],
                  ["board", "Status board"],
                ] as const
              ).map(([k, label]) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => setPoView(k)}
                  className={cn(
                    "rounded-md px-3 py-1 font-medium transition-colors",
                    poView === k
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>

            {poView === "list" ? (
              <div className="space-y-2">
                {pos?.data.map((p) => (
                  <POOpRow
                    key={p.id}
                    po={p}
                    active={sel?.kind === "po" && sel.id === p.id}
                    onSelect={() => setSel({ kind: "po", id: p.id })}
                  />
                ))}
                {(pos?.data.length ?? 0) === 0 && (
                  <p className="text-sm text-muted-foreground">
                    No purchase orders.
                  </p>
                )}
              </div>
            ) : (
              <POStatusBoard
                pos={pos?.data ?? []}
                supplierById={supplierById}
                selectedId={sel?.kind === "po" ? sel.id : null}
                onSelect={(id) => setSel({ kind: "po", id })}
              />
            )}
          </CollapsiblePanel>
        </div>

        {/* shared detail pane */}
        <aside className="lg:sticky lg:top-20 lg:self-start">
          <SupplyDetail
            sel={sel}
            po={sel?.kind === "po" ? poById.get(sel.id) : undefined}
            item={sel?.kind === "inventory" ? itemById.get(sel.id) : undefined}
            supplier={
              sel?.kind === "supplier" ? supplierFull.get(sel.id) : undefined
            }
            supplierName={
              sel?.kind === "po"
                ? poById.get(sel.id)?.supplier_id
                  ? supplierById.get(poById.get(sel.id)!.supplier_id!)
                  : undefined
                : undefined
            }
            itemForPo={
              sel?.kind === "po" && poById.get(sel.id)?.inventory_item_id
                ? itemById.get(poById.get(sel.id)!.inventory_item_id!)
                : undefined
            }
            itemSupplier={
              sel?.kind === "inventory" && itemById.get(sel.id)?.supplier_id
                ? supplierFull.get(itemById.get(sel.id)!.supplier_id!)
                : undefined
            }
            itemPOs={
              sel?.kind === "inventory"
                ? (pos?.data ?? []).filter(
                    (p) => p.inventory_item_id === sel.id,
                  )
                : undefined
            }
            itemReorder={
              sel?.kind === "inventory"
                ? persisted.get(itemById.get(sel.id)?.sku ?? "")
                : sel?.kind === "reorder"
                  ? persisted.get(sel.id)
                  : undefined
            }
            onReorder={(sku) => setDialog({ action: "approve", sku })}
            reorder={
              sel?.kind === "reorder"
                ? schedule.find((s) => s.item.sku === sel.id)
                : undefined
            }
            reorderState={(() => {
              if (sel?.kind !== "reorder") return undefined
              const r = schedule.find((s) => s.item.sku === sel.id)
              return r ? reorderState(r) : undefined
            })()}
            onReorderAction={(action, sku) => setDialog({ action, sku })}
          />
        </aside>
      </div>

      {dialogReorder && dialog && (
        <ReorderActionDialog
          action={dialog.action}
          reorder={dialogReorder}
          state={reorderState(dialogReorder)}
          username={username}
          pending={actionMutation.isPending}
          onClose={() => setDialog(null)}
          onConfirm={(qty, reason) =>
            applyAction(dialog.action, dialog.sku, qty, reason)
          }
        />
      )}
    </div>
  )
}

// ---- Scheduled reorder list + actions --------------------------------------
function ReorderSection({
  icon,
  title,
  subtitle,
  reorders,
  reorderState,
  onAction,
  onSelect,
  selectedSku,
  showDate,
}: {
  icon: ReactNode
  title: string
  subtitle: string
  reorders: ScheduledReorder[]
  reorderState: (r: ScheduledReorder) => ReorderState
  onAction: (action: ReorderAction, sku: string) => void
  onSelect: (sku: string) => void
  selectedSku: string | null
  showDate?: boolean
}) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        {icon}
        <span className="text-sm font-semibold">{title}</span>
        <span className="text-xs text-muted-foreground">· {subtitle}</span>
      </div>
      {reorders.length === 0 ? (
        <p className="px-1 text-sm text-muted-foreground">Nothing scheduled.</p>
      ) : (
        <ul className="space-y-2">
          {reorders.map((r) => (
            <ReorderRow
              key={r.item.sku}
              reorder={r}
              state={reorderState(r)}
              onAction={onAction}
              onSelect={onSelect}
              active={selectedSku === r.item.sku}
              showDate={showDate}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

function ReorderRow({
  reorder,
  state,
  onAction,
  onSelect,
  active,
  showDate,
}: {
  reorder: ScheduledReorder
  state: ReorderState
  onAction: (action: ReorderAction, sku: string) => void
  onSelect: (sku: string) => void
  active?: boolean
  showDate?: boolean
}) {
  const { item } = reorder
  const cancelled = state.status === "cancelled"
  const badge = state.status !== "pending" ? REORDER_BADGE[state.status] : null

  return (
    <li
      className={cn(
        "rounded-lg bg-muted/30 p-3 transition-colors",
        active && "ring-2 ring-primary/50",
        cancelled && "opacity-55",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* clicking the row opens the detail pane on the right (like Inventory) */}
        <button
          type="button"
          onClick={() => onSelect(item.sku)}
          className="-m-1 min-w-0 flex-1 rounded-md p-1 text-left transition-colors hover:bg-accent/40"
        >
          <div className="flex items-center gap-2">
            <span className="font-medium">{item.sku}</span>
            <span className="text-sm text-muted-foreground">{item.name}</span>
            {badge && (
              <span
                className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold"
                style={{
                  color: badge.color,
                  border: `1px solid ${badge.color}`,
                  backgroundColor: `color-mix(in oklab, ${badge.color} 16%, transparent)`,
                }}
              >
                {badge.label}
              </span>
            )}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>
              {reorder.machineName}{" "}
              <span className="text-muted-foreground/70">
                ({reorder.machineCode})
              </span>{" "}
              · {reorder.line}
            </span>
            <span className="tabular-nums">Order: {state.qty}</span>
            {showDate && (
              <span className="tabular-nums">{fmtSchedDate(reorder.date)}</span>
            )}
          </div>
          {state.reason && (
            <p className="mt-1 text-xs italic text-muted-foreground">
              “{state.reason}”
            </p>
          )}
        </button>

        {!cancelled && (
          <div className="flex shrink-0 items-center gap-1.5">
            {state.status !== "approved" && (
              <Button
                size="sm"
                variant="outline"
                className="h-8 gap-1.5 text-success hover:text-success"
                onClick={() => onAction("approve", item.sku)}
              >
                <Check size={14} /> Approve
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              className="h-8 gap-1.5"
              onClick={() => onAction("adjust", item.sku)}
            >
              <Pencil size={14} /> Edit
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-8 gap-1.5 text-danger hover:text-danger"
              onClick={() => onAction("cancel", item.sku)}
            >
              <X size={14} /> Cancel
            </Button>
          </div>
        )}
      </div>
    </li>
  )
}

function ReorderActionDialog({
  action,
  reorder,
  state,
  username,
  pending,
  onClose,
  onConfirm,
}: {
  action: ReorderAction
  reorder: ScheduledReorder
  state: ReorderState
  username: string
  pending?: boolean
  onClose: () => void
  onConfirm: (qty: number, reason?: string) => void
}) {
  const { item } = reorder
  const [qty, setQty] = useState(state.qty)
  const [reason, setReason] = useState(state.reason ?? "")
  const isCancel = action === "cancel"
  const isAdjust = action === "adjust"
  const title =
    action === "approve"
      ? "Approve reorder"
      : isCancel
        ? "Cancel reorder"
        : "Edit reorder"

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {item.sku} · {item.name} — {reorder.machineName} ({reorder.line})
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 text-sm">
          {isAdjust ? (
            <>
              <div>
                <label
                  htmlFor="reorder-qty"
                  className="mb-1 block text-xs font-medium text-muted-foreground"
                >
                  Order quantity
                </label>
                <input
                  id="reorder-qty"
                  type="number"
                  min={0}
                  value={qty}
                  onChange={(e) => setQty(Math.max(0, Number(e.target.value)))}
                  className="w-full rounded-md bg-muted/50 px-3 py-2 text-sm tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </div>
              <div>
                <label
                  htmlFor="reorder-reason"
                  className="mb-1 block text-xs font-medium text-muted-foreground"
                >
                  Reason for change
                </label>
                <textarea
                  id="reorder-reason"
                  rows={3}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="This part will be replaced by a new one, so we don't need as much for this order…"
                  className="w-full resize-none rounded-md bg-muted/50 px-3 py-2 text-sm outline-none placeholder:italic placeholder:text-muted-foreground/50 focus-visible:ring-2 focus-visible:ring-ring"
                />
              </div>
            </>
          ) : (
            <p className="text-muted-foreground">
              {isCancel
                ? "This reorder will be cancelled and removed from the schedule."
                : "This reorder will be approved and submitted for procurement."}{" "}
              <span className="text-foreground">
                Order quantity: {state.qty}.
              </span>
            </p>
          )}
        </div>

        <DialogFooter>
          <Button
            variant={isCancel ? "destructive" : "default"}
            disabled={pending}
            onClick={() =>
              onConfirm(
                isAdjust ? qty : state.qty,
                isAdjust ? reason : undefined,
              )
            }
          >
            Sign off on {ACTION_NOUN[action]} as {username}
          </Button>
          <Button variant="outline" onClick={onClose} disabled={pending}>
            Dismiss
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---- PO status board (tabbed by status, with dates + location) -------------
const PO_STATUS = ["draft", "open", "received"] as const

const fmtDate = (d: Date | null) =>
  d
    ? d.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : "—"

// Derive initiation + most-recent-move date and current location from status.
function poTimeline(po: PurchaseOrder) {
  const init = po.created_at ? new Date(po.created_at) : null
  const offsetDays = po.status === "received" ? 5 : po.status === "open" ? 2 : 0
  const move = init ? new Date(init.getTime() + offsetDays * 86_400_000) : null
  const location =
    po.status === "received"
      ? "Plant 1 — Receiving Dock"
      : po.status === "open"
        ? "In transit"
        : "Procurement"
  return { init, move, location }
}

function POStatusBoard({
  pos,
  supplierById,
  selectedId,
  onSelect,
}: {
  pos: PurchaseOrder[]
  supplierById: Map<string, string>
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const tabs = [
    { k: "all", label: "All", rows: pos },
    ...PO_STATUS.map((s) => ({
      k: s,
      label: s[0].toUpperCase() + s.slice(1),
      rows: pos.filter((p) => p.status === s),
    })),
  ]
  return (
    <Tabs defaultValue="all">
      <TabsList>
        {tabs.map((t) => (
          <TabsTrigger key={t.k} value={t.k}>
            {t.label}
            <span className="ml-1.5 rounded bg-muted px-1.5 text-[11px] text-muted-foreground">
              {t.rows.length}
            </span>
          </TabsTrigger>
        ))}
      </TabsList>
      {tabs.map((t) => (
        <TabsContent key={t.k} value={t.k} className="mt-3">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-muted-foreground">
                <tr className="border-b">
                  <th className="py-2 pr-4">PO</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">Initiated</th>
                  <th className="py-2 pr-4">Last move</th>
                  <th className="py-2 pr-4">Location</th>
                  <th className="py-2 pr-4">Supplier</th>
                  <th className="py-2 text-right">Amount</th>
                </tr>
              </thead>
              <tbody>
                {t.rows.map((p) => {
                  const { init, move, location } = poTimeline(p)
                  return (
                    <tr
                      key={p.id}
                      onClick={() => onSelect(p.id)}
                      className={cn(
                        "cursor-pointer border-b transition-colors hover:bg-accent/30",
                        selectedId === p.id && "bg-accent",
                      )}
                    >
                      <td className="py-2 pr-4 font-medium text-primary">
                        {p.po_number}
                      </td>
                      <td className="py-2 pr-4">
                        <OrderStatusBadge status={p.status} />
                      </td>
                      <td className="py-2 pr-4 tabular-nums text-muted-foreground">
                        {fmtDate(init)}
                      </td>
                      <td className="py-2 pr-4 tabular-nums text-muted-foreground">
                        {fmtDate(move)}
                      </td>
                      <td className="py-2 pr-4">{location}</td>
                      <td className="py-2 pr-4 text-muted-foreground">
                        {p.supplier_id
                          ? (supplierById.get(p.supplier_id) ?? "—")
                          : "—"}
                      </td>
                      <td className="py-2 text-right tabular-nums">
                        ${p.amount.toLocaleString()}
                      </td>
                    </tr>
                  )
                })}
                {t.rows.length === 0 && (
                  <tr>
                    <td
                      colSpan={7}
                      className="py-4 text-center text-sm text-muted-foreground"
                    >
                      No {t.k === "all" ? "" : t.label.toLowerCase()} purchase
                      orders.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </TabsContent>
      ))}
    </Tabs>
  )
}

function POOpRow({
  po,
  active,
  onSelect,
}: {
  po: PurchaseOrder
  active: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex w-full items-center justify-between gap-3 rounded-lg p-3 text-left text-sm transition-colors",
        active ? "bg-accent" : "hover:bg-accent/40",
      )}
    >
      <span className="flex items-center gap-2">
        <ChevronRight size={15} className="text-muted-foreground" />
        <span className="font-medium">{po.po_number}</span>
        <StatusBadge value={po.status} />
      </span>
      <span className="tabular-nums">${po.amount.toFixed(0)}</span>
    </button>
  )
}

function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-md border bg-muted/30 p-2">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-0.5 font-medium">{value}</div>
    </div>
  )
}

// The shared right-hand detail pane — renders a PO, inventory item, or supplier
// depending on the selected row (master-detail like the Tickets page).
function SupplyDetail({
  sel,
  po,
  item,
  supplier,
  supplierName,
  itemForPo,
  itemSupplier,
  itemPOs,
  itemReorder,
  onReorder,
  reorder,
  reorderState,
  onReorderAction,
}: {
  sel: Sel | null
  po?: PurchaseOrder
  item?: InventoryItem
  supplier?: Supplier
  supplierName?: string
  itemForPo?: InventoryItem
  itemSupplier?: Supplier
  itemPOs?: PurchaseOrder[]
  itemReorder?: MaterialReorder
  onReorder?: (sku: string) => void
  reorder?: ScheduledReorder
  reorderState?: ReorderState
  onReorderAction?: (action: ReorderAction, sku: string) => void
}) {
  if (!sel) {
    return (
      <div className="rounded-lg border bg-card p-6 text-sm text-muted-foreground">
        Select a row to view its details.
      </div>
    )
  }

  if (sel.kind === "reorder" && reorder && reorderState) {
    const st = reorderState
    const badge =
      st.status !== "pending"
        ? REORDER_BADGE[st.status as Exclude<ReorderStatus, "pending">]
        : null
    return (
      <div className="space-y-4 rounded-lg bg-card p-4">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <h3 className="text-lg font-semibold">{reorder.item.sku}</h3>
            <p className="text-sm text-muted-foreground">{reorder.item.name}</p>
          </div>
          {badge ? (
            <span
              className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold"
              style={{
                color: badge.color,
                border: `1px solid ${badge.color}`,
                backgroundColor: `color-mix(in oklab, ${badge.color} 16%, transparent)`,
              }}
            >
              {badge.label}
            </span>
          ) : (
            <span className="text-[11px] text-muted-foreground">Pending</span>
          )}
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <Field
            label="Machine"
            value={`${reorder.machineName} (${reorder.machineCode})`}
          />
          <Field label="Line" value={reorder.line} />
          <Field label="Order qty" value={st.qty.toLocaleString()} />
          <Field label="Scheduled" value={fmtSchedDate(reorder.date)} />
          <Field
            label="On hand"
            value={reorder.item.quantity.toLocaleString()}
          />
          <Field
            label="Reorder at"
            value={reorder.item.reorder_threshold.toLocaleString()}
          />
          {st.reason && (
            <div className="col-span-2">
              <Field label="Reason" value={st.reason} />
            </div>
          )}
          {itemReorder?.signed_off_by && (
            <div className="col-span-2">
              <Field label="Signed off by" value={itemReorder.signed_off_by} />
            </div>
          )}
        </div>

        {st.status !== "cancelled" && onReorderAction && (
          <div className="flex flex-wrap gap-2">
            {st.status !== "approved" && (
              <Button
                size="sm"
                className="gap-1.5"
                onClick={() => onReorderAction("approve", reorder.item.sku)}
              >
                <Check size={14} /> Approve
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5"
              onClick={() => onReorderAction("adjust", reorder.item.sku)}
            >
              <Pencil size={14} /> Edit
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5 text-danger hover:text-danger"
              onClick={() => onReorderAction("cancel", reorder.item.sku)}
            >
              <X size={14} /> Cancel
            </Button>
          </div>
        )}
      </div>
    )
  }

  if (sel.kind === "po" && po) {
    const { init, move, location } = poTimeline(po)
    return (
      <div className="space-y-4 rounded-lg bg-card p-4">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-lg font-semibold">{po.po_number}</h3>
          <OrderStatusBadge status={po.status} />
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <Field label="Supplier" value={supplierName ?? "—"} />
          <Field label="Material" value={itemForPo?.sku ?? "—"} />
          <Field label="Amount" value={`$${po.amount.toLocaleString()}`} />
          <Field label="Location" value={location} />
          <Field label="Initiated" value={fmtDate(init)} />
          <Field label="Last move" value={fmtDate(move)} />
          <Field label="Linked job" value={po.job_id ? "Yes" : "—"} />
          <Field
            label="Shop floor"
            value={po.shop_floor_ready ? "Ready" : "Pending"}
          />
        </div>
        <Link
          to="/order-tracker"
          search={{ po: po.id }}
          className="inline-block font-medium text-primary hover:underline"
        >
          Open in Order Tracker →
        </Link>
      </div>
    )
  }

  if (sel.kind === "inventory" && item) {
    const unit = item.unit ?? "ea"
    const shortfall = Math.max(item.reorder_threshold - item.quantity, 0)
    // Stock level relative to par (2× the reorder point); clamp to 0-100%.
    const par = Math.max(item.reorder_threshold * 2, 1)
    const pct = Math.min(100, Math.round((item.quantity / par) * 100))
    const barColor = item.below_threshold ? "var(--danger)" : "var(--success)"
    const reorderBadge =
      itemReorder && itemReorder.status !== "pending"
        ? REORDER_BADGE[itemReorder.status as Exclude<ReorderStatus, "pending">]
        : null

    return (
      <div className="space-y-4 rounded-lg bg-card p-4">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <h3 className="text-lg font-semibold">{item.sku}</h3>
            <p className="text-sm text-muted-foreground">{item.name}</p>
          </div>
          <StatusBadge value={item.below_threshold ? "high" : "running"} />
        </div>

        {/* Stock level — on-hand against the reorder point. */}
        <div>
          <div className="mb-1 flex items-baseline justify-between">
            <span className="text-xs uppercase tracking-wide text-muted-foreground">
              Stock level
            </span>
            <span className="text-sm font-semibold tabular-nums">
              {item.quantity.toLocaleString()}{" "}
              <span className="text-xs font-normal text-muted-foreground">
                {unit}
              </span>
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full transition-all"
              style={{ width: `${pct}%`, backgroundColor: barColor }}
            />
          </div>
          <div className="mt-1 flex justify-between text-[11px] text-muted-foreground">
            <span>Reorder at {item.reorder_threshold.toLocaleString()}</span>
            <span>Par {par.toLocaleString()}</span>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 text-xs">
          <Field
            label="Status"
            value={item.below_threshold ? "Below threshold" : "In stock"}
          />
          <Field
            label="Shortfall"
            value={shortfall ? shortfall.toLocaleString() : "—"}
          />
          <Field label="Material" value={item.material_type ?? "—"} />
          <Field label="Unit" value={unit} />
          <Field label="Supplier" value={itemSupplier?.name ?? "—"} />
          <Field
            label="Lead time"
            value={itemSupplier ? `${itemSupplier.lead_time_days} days` : "—"}
          />
        </div>

        {/* Linked purchase orders for this material. */}
        <div>
          <p className="mb-1.5 text-xs uppercase tracking-wide text-muted-foreground">
            Purchase orders
          </p>
          {itemPOs && itemPOs.length > 0 ? (
            <ul className="space-y-1">
              {itemPOs.map((p) => (
                <li key={p.id}>
                  <Link
                    to="/order-tracker"
                    search={{ po: p.id }}
                    className="-mx-1 flex items-center justify-between gap-2 rounded-md px-1 py-1 text-sm hover:bg-accent/50"
                  >
                    <span className="font-medium text-primary">
                      {p.po_number}
                    </span>
                    <span className="flex items-center gap-2">
                      <OrderStatusBadge status={p.status} />
                      <span className="tabular-nums text-muted-foreground">
                        ${p.amount.toLocaleString()}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">
              No linked purchase orders.
            </p>
          )}
        </div>

        {/* Reorder status + quick action for below-threshold materials. */}
        {item.below_threshold && (
          <div className="rounded-md bg-muted/40 p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs uppercase tracking-wide text-muted-foreground">
                Reorder
              </span>
              {reorderBadge ? (
                <span
                  className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold"
                  style={{
                    color: reorderBadge.color,
                    border: `1px solid ${reorderBadge.color}`,
                    backgroundColor: `color-mix(in oklab, ${reorderBadge.color} 16%, transparent)`,
                  }}
                >
                  {reorderBadge.label}
                </span>
              ) : (
                <span className="text-[11px] text-muted-foreground">
                  Not yet scheduled
                </span>
              )}
            </div>
            {itemReorder?.signed_off_by && (
              <p className="mt-1 text-[11px] text-muted-foreground">
                Signed off by {itemReorder.signed_off_by}
              </p>
            )}
            {onReorder && (
              <Button
                size="sm"
                className="mt-2 w-full gap-1.5"
                onClick={() => onReorder(item.sku)}
              >
                <Check size={14} />
                {reorderBadge?.label === "Approved"
                  ? "Re-approve reorder"
                  : "Approve reorder"}
              </Button>
            )}
          </div>
        )}
      </div>
    )
  }

  if (sel.kind === "supplier" && supplier) {
    return (
      <div className="space-y-4 rounded-lg bg-card p-4">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-lg font-semibold">{supplier.name}</h3>
          <StatusBadge value={supplier.status === "ok" ? "running" : "high"} />
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <Field label="Lead time" value={`${supplier.lead_time_days} days`} />
          <Field
            label="Status"
            value={supplier.status === "ok" ? "On track" : "Delayed"}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-lg border bg-card p-6 text-sm text-muted-foreground">
      Details unavailable.
    </div>
  )
}
