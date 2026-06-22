import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useTelemetryStream } from "@/smartforge/useRealtime"

class MockWebSocket {
  static instances: MockWebSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  close = vi.fn()
  constructor(public url: string) {
    MockWebSocket.instances.push(this)
  }
}

beforeEach(() => {
  MockWebSocket.instances = []
  vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("useTelemetryStream", () => {
  it("opens a socket and reports connected on open", () => {
    const { result } = renderHook(() => useTelemetryStream())
    expect(MockWebSocket.instances.length).toBe(1)
    expect(result.current.connected).toBe(false)
    act(() => {
      MockWebSocket.instances[0].onopen?.()
    })
    expect(result.current.connected).toBe(true)
  })

  it("updates ticks keyed by machine_id on message", () => {
    const { result } = renderHook(() => useTelemetryStream())
    act(() => {
      MockWebSocket.instances[0].onmessage?.({
        data: JSON.stringify({
          machine_id: "m1",
          code: "cnc-01",
          health_score: 82,
          status: "running",
          temperature: 70,
        }),
      })
    })
    expect(result.current.ticks.m1).toMatchObject({
      code: "cnc-01",
      health_score: 82,
      status: "running",
    })
  })

  it("ignores non-JSON keepalive frames", () => {
    const { result } = renderHook(() => useTelemetryStream())
    act(() => {
      MockWebSocket.instances[0].onmessage?.({ data: "not json" })
    })
    expect(Object.keys(result.current.ticks)).toHaveLength(0)
  })

  it("closes the socket on unmount", () => {
    const { unmount } = renderHook(() => useTelemetryStream())
    const ws = MockWebSocket.instances[0]
    unmount()
    expect(ws.close).toHaveBeenCalled()
  })
})
