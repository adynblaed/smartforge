import { createFileRoute } from "@tanstack/react-router"
import { toast } from "sonner"

import { sf } from "@/smartforge/api"
import { ChatPanel } from "@/smartforge/ChatPanel"
import { PageHeader } from "@/smartforge/components"
import { ESCALATION_CONFIDENCE } from "@/smartforge/constants"
import type { AskResponse } from "@/smartforge/types"

export const Route = createFileRoute("/portal/ask")({
  component: PortalAsk,
  head: () => ({ meta: [{ title: "Order Assistant - SmartForge" }] }),
})

function PortalAsk() {
  const escalate = async (question: string) => {
    await sf.post("/customer/escalate", {
      question,
      ai_confidence: ESCALATION_CONFIDENCE,
    })
    toast.success("Your question was sent to our support team.")
  }

  return (
    <div className="flex h-[calc(100vh-9rem)] flex-col gap-4">
      <PageHeader
        title="Order Assistant"
        description="Ask about your order status, production stage, or delivery."
      />
      <div className="flex-1">
        <ChatPanel
          placeholder="When will my order be done?"
          suggestions={[
            "When will my order be done?",
            "Is my part in production?",
            "Has my order shipped?",
            "Is there a delay?",
          ]}
          ask={(q) => sf.post<AskResponse>("/customer/ask", { question: q })}
          onEscalate={escalate}
        />
      </div>
    </div>
  )
}
