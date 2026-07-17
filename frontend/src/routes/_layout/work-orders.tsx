import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { sf } from "@/smartforge/api"
import { PageHeader, Panel, StatusBadge } from "@/smartforge/components"
import { POLL } from "@/smartforge/constants"
import type { Page, WorkOrder } from "@/smartforge/types"

export const Route = createFileRoute("/_layout/work-orders")({
  component: WorkOrdersPage,
  head: () => ({ meta: [{ title: "Work Orders - SmartForge" }] }),
})

function WorkOrdersPage() {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ["work-orders"],
    queryFn: () => sf.get<Page<WorkOrder>>("/work-orders/"),
    refetchInterval: POLL.medium,
  })
  const act = useMutation({
    mutationFn: ({ id, path }: { id: string; path: string }) =>
      sf.post(`/work-orders/${id}/${path}`),
    onError: (error) =>
      toast.error(
        error instanceof Error ? error.message : "Work order action failed",
      ),
    onSettled: () => qc.invalidateQueries({ queryKey: ["work-orders"] }),
  })

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Work Order Queue"
        description="AI-generated maintenance work orders with Fiix sync."
      />
      <Panel title="Work Orders">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-muted-foreground">
              <tr className="border-b">
                <th className="py-2 pr-4">Fault</th>
                <th className="py-2 pr-4">Severity</th>
                <th className="py-2 pr-4">Priority</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">Fiix</th>
                <th className="py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data?.data.map((w) => (
                <tr key={w.id} className="border-b">
                  <td className="py-2 pr-4">
                    <div className="font-medium">{w.fault_type}</div>
                    <div className="text-xs text-muted-foreground">
                      {w.recommended_task}
                    </div>
                  </td>
                  <td className="py-2 pr-4">
                    <StatusBadge value={w.severity} />
                  </td>
                  <td className="py-2 pr-4">P{w.priority}</td>
                  <td className="py-2 pr-4">
                    <StatusBadge value={w.status} />
                  </td>
                  <td className="py-2 pr-4 text-xs">
                    {w.fiix_id ?? w.fiix_sync_state}
                  </td>
                  <td className="py-2">
                    <div className="flex gap-2">
                      {w.status === "draft" && (
                        <>
                          <Button
                            size="sm"
                            onClick={() =>
                              act.mutate({
                                id: w.id,
                                path: "approve?approve=true",
                              })
                            }
                          >
                            Approve
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() =>
                              act.mutate({
                                id: w.id,
                                path: "approve?approve=false",
                              })
                            }
                          >
                            Reject
                          </Button>
                        </>
                      )}
                      {w.status === "approved" &&
                        w.fiix_sync_state !== "synced" && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() =>
                              act.mutate({ id: w.id, path: "sync-fiix" })
                            }
                          >
                            Sync Fiix
                          </Button>
                        )}
                    </div>
                  </td>
                </tr>
              ))}
              {data?.data.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-4 text-muted-foreground">
                    No work orders yet — they are drafted from machine alerts.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}
