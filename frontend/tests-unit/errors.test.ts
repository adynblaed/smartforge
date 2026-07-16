import { describe, expect, it } from "vitest"

import { ApiError } from "@/smartforge/api"
import { apiErrorInfo, describeStatus } from "@/smartforge/errors"

describe("describeStatus", () => {
  it.each([
    [400, "Invalid request", false],
    [422, "Invalid request", false],
    [401, "Session expired", false],
    [403, "No access", false],
    [404, "Not found", false],
    [409, "Conflict", false],
    [429, "Rate limited", false],
    [500, "Something broke", true],
    [503, "Service unavailable", false],
    [504, "Query timed out", false],
  ] as const)("maps %i to %j (isBug=%s)", (status, title, isBug) => {
    const desc = describeStatus(status)
    expect(desc.title).toBe(title)
    expect(desc.isBug).toBe(isBug)
    expect(desc.hint.length).toBeGreaterThan(0)
  })

  it("gives actionable hints for the common cases", () => {
    expect(describeStatus(400).hint).toBe(
      "The request didn't pass validation — adjust and retry.",
    )
    expect(describeStatus(401).hint).toBe("Sign in again to continue.")
    expect(describeStatus(403).hint).toBe(
      "Your role doesn't permit this action.",
    )
    expect(describeStatus(404).hint).toBe(
      "This resource doesn't exist or was removed.",
    )
    expect(describeStatus(409).hint).toBe(
      "The action clashed with the current state — refresh and retry.",
    )
    expect(describeStatus(429).hint).toBe(
      "Too many requests — wait a moment and retry.",
    )
    expect(describeStatus(500).hint).toBe(
      "This looks like a bug on our side — please report it with the reference code below.",
    )
    expect(describeStatus(503).hint).toBe(
      "A backing service is down or not provisioned yet — see the runbooks or retry shortly.",
    )
    expect(describeStatus(504).hint).toBe(
      "The query exceeded its time budget — narrow the filters and retry.",
    )
  })

  it("falls back to the unexpected-error copy for undefined and unmapped statuses", () => {
    for (const status of [undefined, 418, 502]) {
      const desc = describeStatus(status)
      expect(desc.title).toBe("Unexpected error")
      expect(desc.hint).toBe(
        "If this keeps happening, report it with the details below.",
      )
      expect(desc.isBug).toBe(true)
    }
  })
})

describe("apiErrorInfo", () => {
  it("extracts status and requestId from an sf ApiError", () => {
    const err = new ApiError(503, "503 Service Unavailable", "db down", "req-1")
    expect(apiErrorInfo(err)).toEqual({ status: 503, requestId: "req-1" })
  })

  it("leaves requestId undefined when the error has none", () => {
    expect(apiErrorInfo(new ApiError(404, "404 Not Found"))).toEqual({
      status: 404,
      requestId: undefined,
    })
  })

  it("matches the generated client's ApiError shape structurally", () => {
    // Mimic src/client/core/ApiError without importing generated code.
    const err = Object.assign(new Error("Internal Server Error"), {
      name: "ApiError",
      status: 500,
      statusText: "Internal Server Error",
      body: {},
    })
    expect(apiErrorInfo(err)).toEqual({ status: 500, requestId: undefined })
  })

  it("returns undefined for anything that is not an ApiError", () => {
    expect(apiErrorInfo(new Error("boom"))).toBeUndefined()
    expect(apiErrorInfo("string error")).toBeUndefined()
    expect(apiErrorInfo(undefined)).toBeUndefined()
    expect(
      apiErrorInfo(Object.assign(new Error("x"), { name: "ApiError" })),
    ).toBeUndefined() // no numeric status
  })
})
