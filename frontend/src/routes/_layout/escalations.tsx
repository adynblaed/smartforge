import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { sf } from "@/smartforge/api"
import { PageHeader, Panel, StatusBadge } from "@/smartforge/components"
import { POLL } from "@/smartforge/constants"
import type { Escalation, Page } from "@/smartforge/types"

export const Route = createFileRoute("/_layout/escalations")({
  component: EscalationsPage,
  head: () => ({ meta: [{ title: "Escalations - SmartForge" }] }),
})

function EscalationsPage() {
  const { data } = useQuery({
    queryKey: ["escalations"],
    queryFn: () => sf.get<Page<Escalation>>("/customer/escalations"),
    refetchInterval: POLL.medium,
  })

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Customer Escalations"
        description="AI-to-human handoffs awaiting a support response."
      />
      <Panel title="Open & Resolved Escalations">
        <ul className="divide-y">
          {data?.data.map((e) => (
            <EscalationRow key={e.id} esc={e} />
          ))}
          {data?.data.length === 0 && (
            <li className="py-3 text-sm text-muted-foreground">
              No escalations — low-confidence customer answers appear here.
            </li>
          )}
        </ul>
      </Panel>
    </div>
  )
}

function EscalationRow({ esc }: { esc: Escalation }) {
  const qc = useQueryClient()
  const [response, setResponse] = useState("")
  const respond = useMutation({
    mutationFn: () =>
      sf.post(`/customer/escalations/${esc.id}/respond`, {
        human_response: response,
        assigned_team: esc.assigned_team,
      }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["escalations"] }),
  })

  return (
    <li className="py-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <StatusBadge value={esc.status === "resolved" ? "running" : "high"} />
          <span className="text-sm font-medium">{esc.question}</span>
        </div>
        <span className="text-xs text-muted-foreground">
          {Math.round(esc.ai_confidence * 100)}% AI confidence ·{" "}
          {esc.assigned_team}
        </span>
      </div>
      {esc.reason && (
        <p className="mt-1 text-xs text-muted-foreground">
          Reason: {esc.reason}
        </p>
      )}
      {esc.status === "resolved" ? (
        <p className="mt-2 rounded-md bg-muted p-2 text-sm">
          <span className="font-medium">Response: </span>
          {esc.human_response}
        </p>
      ) : (
        <form
          className="mt-2 flex gap-2"
          onSubmit={(ev) => {
            ev.preventDefault()
            if (response.trim()) respond.mutate()
          }}
        >
          <Input
            value={response}
            onChange={(ev) => setResponse(ev.target.value)}
            placeholder="Write a human response…"
          />
          <Button type="submit" disabled={respond.isPending}>
            Send
          </Button>
        </form>
      )}
    </li>
  )
}
