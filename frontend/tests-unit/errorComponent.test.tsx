import { fireEvent, render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"

// ErrorComponent only needs <Link>; stub it so no router context is required.
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, to }: { children?: ReactNode; to?: string }) => (
    <a href={to}>{children}</a>
  ),
}))

import ErrorComponent, {
  ErrorFallbackCard,
  safeErrorMessage,
} from "@/components/Common/ErrorComponent"
import { ApiError } from "@/smartforge/api"

describe("safeErrorMessage", () => {
  it("falls back to a generic line when there is no message", () => {
    expect(safeErrorMessage(undefined)).toBe(
      "Something went wrong. Please try again.",
    )
    expect(safeErrorMessage(new Error(""))).toBe(
      "Something went wrong. Please try again.",
    )
    expect(safeErrorMessage({ weird: true })).toBe(
      "Something went wrong. Please try again.",
    )
  })

  it("passes short messages through and truncates long ones", () => {
    expect(safeErrorMessage(new Error("boom"))).toBe("boom")
    const long = "x".repeat(500)
    const out = safeErrorMessage(new Error(long))
    expect(out).toHaveLength(201) // 200 chars + ellipsis
    expect(out.endsWith("…")).toBe(true)
  })
})

describe("ErrorComponent", () => {
  it("renders the error message and Go Home link", () => {
    render(<ErrorComponent error={new Error("kaboom")} />)
    expect(screen.getByTestId("error-component")).toBeInTheDocument()
    expect(screen.getByText("kaboom")).toBeInTheDocument()
    expect(screen.getByText("Go Home")).toBeInTheDocument()
    // No reset prop -> no Try again button.
    expect(screen.queryByText("Try again")).not.toBeInTheDocument()
  })

  it("calls reset when Try again is clicked", () => {
    const reset = vi.fn()
    render(<ErrorComponent error={new Error("kaboom")} reset={reset} />)
    fireEvent.click(screen.getByText("Try again"))
    expect(reset).toHaveBeenCalledTimes(1)
  })

  it("describes a 503 ApiError with title, hint, and reference code", () => {
    const err = new ApiError(
      503,
      "503 Service Unavailable",
      "warehouse not provisioned",
      "req-abc-123",
    )
    render(<ErrorComponent error={err} />)
    expect(screen.getByText("Service unavailable")).toBeInTheDocument()
    expect(
      screen.getByText(
        "A backing service is down or not provisioned yet — see the runbooks or retry shortly.",
      ),
    ).toBeInTheDocument()
    // The safe technical message is still shown, smaller.
    expect(screen.getByText("503 Service Unavailable")).toBeInTheDocument()
    expect(screen.getByText("Reference: req-abc-123")).toBeInTheDocument()
    // A 503 is operational, not a bug — no bug-report line.
    expect(screen.queryByText(/This is likely a bug/)).not.toBeInTheDocument()
  })

  it("flags a 500 ApiError as a likely bug", () => {
    const err = new ApiError(
      500,
      "500 Internal Server Error",
      undefined,
      "req-bug-1",
    )
    render(<ErrorComponent error={err} />)
    expect(screen.getByText("Something broke")).toBeInTheDocument()
    expect(screen.getByText("Reference: req-bug-1")).toBeInTheDocument()
    expect(
      screen.getByText(
        "This is likely a bug — include the reference when reporting.",
      ),
    ).toBeInTheDocument()
  })

  it("uses the default copy and no reference line for plain errors", () => {
    render(<ErrorComponent error={new Error("kaboom")} />)
    expect(screen.getByText("Unexpected error")).toBeInTheDocument()
    expect(screen.queryByText(/^Reference:/)).not.toBeInTheDocument()
  })
})

describe("ErrorFallbackCard", () => {
  it("renders the message and resets the boundary on Try again", () => {
    const reset = vi.fn()
    render(
      <ErrorFallbackCard
        error={new Error("render blew up")}
        resetErrorBoundary={reset}
      />,
    )
    expect(screen.getByTestId("error-fallback-card")).toBeInTheDocument()
    expect(screen.getByText("render blew up")).toBeInTheDocument()
    fireEvent.click(screen.getByText("Try again"))
    expect(reset).toHaveBeenCalledTimes(1)
  })

  it("describes ApiErrors with status copy and reference code", () => {
    const err = new ApiError(
      503,
      "503 Service Unavailable",
      "lake offline",
      "req-77",
    )
    render(<ErrorFallbackCard error={err} resetErrorBoundary={vi.fn()} />)
    expect(screen.getByText("Service unavailable")).toBeInTheDocument()
    expect(
      screen.getByText(
        "A backing service is down or not provisioned yet — see the runbooks or retry shortly.",
      ),
    ).toBeInTheDocument()
    expect(screen.getByText("Reference: req-77")).toBeInTheDocument()
  })

  it("shows the bug-report line for a 500", () => {
    const err = new ApiError(500, "500 Internal Server Error")
    render(<ErrorFallbackCard error={err} resetErrorBoundary={vi.fn()} />)
    expect(screen.getByText("Something broke")).toBeInTheDocument()
    expect(
      screen.getByText(
        "This is likely a bug — include the reference when reporting.",
      ),
    ).toBeInTheDocument()
    // No requestId on this error -> no reference line.
    expect(screen.queryByText(/^Reference:/)).not.toBeInTheDocument()
  })
})
