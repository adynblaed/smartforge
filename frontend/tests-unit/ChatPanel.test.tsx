import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { ChatPanel } from "@/smartforge/ChatPanel"
import type { AskResponse } from "@/smartforge/types"

const answer: AskResponse = {
  answer: "Check the spindle bearings.",
  sources: [{ document_id: "1", title: "CNC Guide", kind: "manual" }],
  suggested_actions: ["Open a work order"],
  confidence: 0.9,
  session_id: null,
}

describe("ChatPanel", () => {
  it("shows suggestions and sends a question, rendering the answer + sources", async () => {
    const ask = vi.fn().mockResolvedValue(answer)
    render(<ChatPanel ask={ask} suggestions={["Why is vibration high?"]} />)
    // Suggestion chip is shown initially.
    expect(screen.getByText("Why is vibration high?")).toBeInTheDocument()

    const input = screen.getByPlaceholderText("Ask a question…")
    fireEvent.change(input, { target: { value: "What is wrong?" } })
    fireEvent.submit(input.closest("form")!)

    expect(ask).toHaveBeenCalledWith("What is wrong?")
    await waitFor(() =>
      expect(
        screen.getByText("Check the spindle bearings."),
      ).toBeInTheDocument(),
    )
    expect(screen.getByText(/CNC Guide/)).toBeInTheDocument()
    expect(screen.getByText("Open a work order")).toBeInTheDocument()
  })

  it("shows an escalation button on low-confidence answers", async () => {
    const ask = vi.fn().mockResolvedValue({ ...answer, confidence: 0.3 })
    const onEscalate = vi.fn()
    render(<ChatPanel ask={ask} onEscalate={onEscalate} />)
    const input = screen.getByPlaceholderText("Ask a question…")
    fireEvent.change(input, { target: { value: "Where is my order?" } })
    fireEvent.submit(input.closest("form")!)
    const btn = await screen.findByText("Talk to a human")
    fireEvent.click(btn)
    expect(onEscalate).toHaveBeenCalled()
  })

  it("renders an error message when ask rejects", async () => {
    const ask = vi.fn().mockRejectedValue(new Error("boom"))
    render(<ChatPanel ask={ask} />)
    const input = screen.getByPlaceholderText("Ask a question…")
    fireEvent.change(input, { target: { value: "hi" } })
    fireEvent.submit(input.closest("form")!)
    await waitFor(() =>
      expect(
        screen.getByText(/couldn't reach the assistant/i),
      ).toBeInTheDocument(),
    )
  })
})
