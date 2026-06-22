import { describe, expect, it } from "vitest"

import { sf, wsUrl } from "@/smartforge/api"

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
