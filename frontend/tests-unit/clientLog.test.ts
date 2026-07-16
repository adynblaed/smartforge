import { afterEach, describe, expect, it, vi } from "vitest"

import {
  installGlobalErrorLogging,
  logClientError,
} from "@/smartforge/clientLog"

describe("logClientError", () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("logs Errors with the structured prefix", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {})
    const err = new Error("boom")
    logClientError("query", err)
    expect(spy).toHaveBeenCalledWith("[smartforge]", "query", "boom", err)
  })

  it("does not throw on weird inputs", () => {
    vi.spyOn(console, "error").mockImplementation(() => {})
    expect(() => logClientError("scope", undefined)).not.toThrow()
    expect(() => logClientError("scope", "plain string")).not.toThrow()
    expect(() => logClientError("scope", { some: "object" })).not.toThrow()
    expect(() =>
      logClientError("scope", {
        toString() {
          throw new Error("hostile toString")
        },
      }),
    ).not.toThrow()
  })

  it("redacts bearer tokens from logged messages", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {})
    logClientError("query", new Error("failed with Bearer abc.def-123"))
    const loggedMessage = spy.mock.calls[0]?.[2] as string
    expect(loggedMessage).not.toContain("abc.def-123")
    expect(loggedMessage).toContain("Bearer [redacted]")
  })

  it("never throws even if console.error itself throws", () => {
    vi.spyOn(console, "error").mockImplementation(() => {
      throw new Error("console is broken")
    })
    expect(() => logClientError("scope", new Error("boom"))).not.toThrow()
  })
})

describe("installGlobalErrorLogging", () => {
  it("registers window handlers exactly once", () => {
    const spy = vi.spyOn(window, "addEventListener")
    installGlobalErrorLogging()
    const first = spy.mock.calls.filter(
      ([type]) => type === "error" || type === "unhandledrejection",
    ).length
    installGlobalErrorLogging()
    const second = spy.mock.calls.filter(
      ([type]) => type === "error" || type === "unhandledrejection",
    ).length
    expect(first).toBe(2)
    expect(second).toBe(2) // idempotent: no duplicate registration
    spy.mockRestore()
  })
})
