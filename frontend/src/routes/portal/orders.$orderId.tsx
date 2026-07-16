import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowLeft } from "lucide-react"
import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { sf, wsUrl } from "@/smartforge/api"
import { PageHeader, Panel } from "@/smartforge/components"
import { POLL } from "@/smartforge/constants"
import type { CustomerOrder } from "@/smartforge/types"

export const Route = createFileRoute("/portal/orders/$orderId")({
  component: OrderDetail,
  head: () => ({ meta: [{ title: "Order - SmartForge" }] }),
})

const STAGES = [
  "received",
  "scheduled",
  "in_production",
  "inspection",
  "complete",
  "shipped",
]

function OrderDetail() {
  const { orderId } = Route.useParams()
  const { data, refetch } = useQuery({
    queryKey: ["customer-order", orderId],
    queryFn: () => sf.get<CustomerOrder>(`/customer/orders/${orderId}`),
    refetchInterval: POLL.fast,
  })
  const [live, setLive] = useState(false)

  // Real-time updates via WebSocket, with the polling above as a fallback.
  useEffect(() => {
    let ws: WebSocket | null = null
    let closed = false
    try {
      ws = new WebSocket(wsUrl("/ws/orders"))
      ws.onopen = () => {
        if (!closed) setLive(true)
      }
      ws.onmessage = (e) => {
        if (closed) return
        try {
          const msg = JSON.parse(e.data)
          if (msg.order_id === orderId) refetch()
        } catch {
          /* keepalive */
        }
      }
      ws.onclose = () => {
        if (!closed) setLive(false)
      }
    } catch {
      setLive(false)
    }
    return () => {
      closed = true
      if (ws) {
        ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null
        ws.close()
      }
    }
  }, [orderId, refetch])

  const idx = data ? STAGES.indexOf(data.stage) : -1

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={data ? `Order ${data.order_number}` : "Order"}
        description="Live production status and estimated completion."
        actions={
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted-foreground">
              {live ? "● live" : "○ polling"}
            </span>
            <Button asChild variant="ghost" size="sm">
              <Link to="/portal">
                <ArrowLeft size={16} /> Back to orders
              </Link>
            </Button>
          </div>
        }
      />

      {data && (
        <Panel
          title="Production Stages"
          action={
            data.delayed ? (
              <span className="text-xs font-medium text-danger">Delayed</span>
            ) : (
              <span className="text-xs text-success">On track</span>
            )
          }
        >
          <div className="mb-6 flex items-center justify-between text-sm">
            <span>
              {data.part_type} × {data.quantity}
            </span>
            <span className="text-muted-foreground">
              Est. completion:{" "}
              {data.estimated_completion
                ? new Date(data.estimated_completion).toLocaleDateString()
                : "—"}
            </span>
          </div>

          <ol className="relative space-y-4 border-l pl-6">
            {STAGES.map((s, i) => (
              <li key={s} className="relative">
                <span
                  className={`absolute -left-[1.65rem] mt-0.5 h-3 w-3 rounded-full ${
                    i <= idx ? "bg-primary" : "bg-muted"
                  }`}
                />
                <div
                  className={`text-sm capitalize ${
                    i === idx ? "font-semibold" : "text-muted-foreground"
                  }`}
                >
                  {s.replace("_", " ")}
                  {i === idx && " — current"}
                </div>
              </li>
            ))}
          </ol>

          {data.delayed && data.delay_reason && (
            <p className="mt-4 text-sm text-danger">
              Notice: {data.delay_reason}
            </p>
          )}
        </Panel>
      )}
    </div>
  )
}
