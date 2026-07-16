import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"

import { Button } from "@/components/ui/button"
import { sf } from "@/smartforge/api"
import { Loading, PageHeader, Panel } from "@/smartforge/components"
import { POLL } from "@/smartforge/constants"
import type { CustomerOrder, Page } from "@/smartforge/types"

export const Route = createFileRoute("/portal/")({
  component: PortalDashboard,
  head: () => ({ meta: [{ title: "My Orders - SmartForge" }] }),
})

const STAGES = [
  "received",
  "scheduled",
  "in_production",
  "inspection",
  "complete",
  "shipped",
]

function StageTimeline({ stage }: { stage: string }) {
  const idx = STAGES.indexOf(stage)
  return (
    <div className="flex items-center gap-1">
      {STAGES.map((s, i) => (
        <div key={s} className="flex flex-1 flex-col items-center gap-1">
          <div
            className={`h-2 w-full rounded-full ${
              i <= idx ? "bg-primary" : "bg-muted"
            }`}
          />
          <span
            className={`text-[10px] capitalize ${
              i === idx
                ? "font-semibold text-foreground"
                : "text-muted-foreground"
            }`}
          >
            {s.replace("_", " ")}
          </span>
        </div>
      ))}
    </div>
  )
}

function PortalDashboard() {
  const { data, isLoading } = useQuery({
    queryKey: ["customer-orders"],
    queryFn: () => sf.get<Page<CustomerOrder>>("/customer/orders"),
    refetchInterval: POLL.fast, // real-time order status without page refresh
  })

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Your Orders"
        description="Live production status and estimated completion."
      />

      <div className="grid gap-4">
        {isLoading && <Loading label="Loading your orders…" />}
        {data?.data.map((o) => (
          <Panel
            key={o.id}
            title={`Order ${o.order_number}`}
            action={
              o.delayed ? (
                <span className="text-xs font-medium text-danger">Delayed</span>
              ) : (
                <span className="text-xs text-success">On track</span>
              )
            }
          >
            <div className="mb-4 flex items-center justify-between text-sm">
              <span>
                {o.part_type} × {o.quantity}
              </span>
              <span className="text-muted-foreground">
                ETA:{" "}
                {o.estimated_completion
                  ? new Date(o.estimated_completion).toLocaleDateString()
                  : "—"}
              </span>
            </div>
            <StageTimeline stage={o.stage} />
            {o.delayed && o.delay_reason && (
              <p className="mt-3 text-sm text-danger">
                Notice: {o.delay_reason}
              </p>
            )}
            <div className="mt-4">
              <Button asChild size="sm" variant="outline">
                <Link to="/portal/orders/$orderId" params={{ orderId: o.id }}>
                  View live status
                </Link>
              </Button>
            </div>
          </Panel>
        ))}
        {data?.data.length === 0 && (
          <p className="text-sm text-muted-foreground">No active orders.</p>
        )}
      </div>
    </div>
  )
}
