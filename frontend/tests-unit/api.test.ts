import { afterEach, describe, expect, it, vi } from "vitest"

import { ApiError, sf, wsUrl } from "@/smartforge/api"

describe("smartforge api wrapper", () => {
  it("exposes a base url", () => {
    expect(typeof sf.base).toBe("string")
    expect(sf.base.length).toBeGreaterThan(0)
  })

  it("derives a ws:// url from the http base for telemetry", () => {
    const url = wsUrl("/ws/telemetry")
    expect(url.startsWith("ws://") || url.startsWith("wss://")).toBe(true)
    expect(url).toContain("/api/v1/ws/telemetry")
  })

  it("derives a ws url for orders", () => {
    expect(wsUrl("/ws/orders")).toContain("/ws/orders")
  })

  it("exposes get/post helpers", () => {
    expect(typeof sf.get).toBe("function")
    expect(typeof sf.post).toBe("function")
  })
})

describe("ApiError", () => {
  it("carries status and optional detail with a status-shaped message", () => {
    const err = new ApiError(500, "500 Internal Server Error", "db down")
    expect(err).toBeInstanceOf(Error)
    expect(err.name).toBe("ApiError")
    expect(err.status).toBe(500)
    expect(err.detail).toBe("db down")
    expect(err.message).toBe("500 Internal Server Error")
  })

  it("allows detail to be omitted", () => {
    const err = new ApiError(404, "404 Not Found")
    expect(err.status).toBe(404)
    expect(err.detail).toBeUndefined()
  })
})

describe("sf request failures", () => {
  const stubFetch = (
    status: number,
    statusText: string,
    body?: unknown,
    headers?: Record<string, string>,
  ) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        return new Response(body === undefined ? "" : JSON.stringify(body), {
          status,
          statusText,
          headers: { "Content-Type": "application/json", ...headers },
        })
      }),
    )
  }

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("rejects with an ApiError carrying status and server detail", async () => {
    stubFetch(500, "Internal Server Error", { detail: "db down" })
    const err = await sf.get("/items").catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    const apiErr = err as ApiError
    expect(apiErr.status).toBe(500)
    expect(apiErr.detail).toBe("db down")
    // Message stays backward-compatible with the old plain-Error format.
    expect(apiErr.message).toBe("500 Internal Server Error")
  })

  it("rejects with an ApiError even when the body is not JSON", async () => {
    stubFetch(502, "Bad Gateway")
    const err = await sf.get("/items").catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(502)
    expect((err as ApiError).detail).toBeUndefined()
    expect((err as ApiError).message).toBe("502 Bad Gateway")
  })

  it("throws a typed unauthorized ApiError for portal auth failures", async () => {
    // /customer paths skip the login redirect, so the error is observable.
    stubFetch(401, "Unauthorized", { detail: "invalid token" })
    const err = await sf.get("/customer/orders").catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(401)
    // Legacy message shape kept for message-based auth handling.
    expect((err as ApiError).message).toBe("Unauthorized (401)")
  })

  it("captures X-Request-ID from failed responses", async () => {
    stubFetch(
      500,
      "Internal Server Error",
      { detail: "db down" },
      {
        "X-Request-ID": "abc-123",
      },
    )
    const err = await sf.get("/items").catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).requestId).toBe("abc-123")
  })

  it("leaves requestId undefined when the header is absent", async () => {
    stubFetch(500, "Internal Server Error", { detail: "db down" })
    const err = await sf.get("/items").catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).requestId).toBeUndefined()
  })

  it("captures the request id on upload and unauthorized failures too", async () => {
    stubFetch(
      422,
      "Unprocessable Entity",
      { detail: "bad csv" },
      {
        "X-Request-ID": "upl-9",
      },
    )
    const uploadErr = await sf
      .upload("/items/import", new FormData())
      .catch((e: unknown) => e)
    expect((uploadErr as ApiError).requestId).toBe("upl-9")

    stubFetch(
      401,
      "Unauthorized",
      { detail: "invalid token" },
      {
        "X-Request-ID": "auth-7",
      },
    )
    // /customer paths skip the login redirect, so the error is observable.
    const authErr = await sf.get("/customer/orders").catch((e: unknown) => e)
    expect((authErr as ApiError).requestId).toBe("auth-7")
  })

  it("prefers the server detail in upload error messages", async () => {
    stubFetch(422, "Unprocessable Entity", { detail: "bad csv" })
    const err = await sf
      .upload("/items/import", new FormData())
      .catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(422)
    expect((err as ApiError).detail).toBe("bad csv")
    expect((err as ApiError).message).toBe("bad csv")
  })
})
