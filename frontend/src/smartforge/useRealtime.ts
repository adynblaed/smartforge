import { useEffect, useRef, useState } from "react"
import { wsUrl } from "./api"
import { WS_RECONNECT_MS } from "./constants"

export interface TelemetryTick {
  machine_id: string
  code?: string
  health_score?: number
  status?: string
  temperature?: number
  vibration?: number
}

/**
 * Subscribe to live telemetry over WebSocket. Returns the latest tick keyed by
 * machine_id. If the socket can't connect, callers should rely on React Query
 * polling (refetchInterval) as the fallback — `connected` reflects WS state.
 */
export function useTelemetryStream(): {
  ticks: Record<string, TelemetryTick>
  connected: boolean
} {
  const [ticks, setTicks] = useState<Record<string, TelemetryTick>>({})
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    let closed = false
    let retry: ReturnType<typeof setTimeout> | undefined

    const connect = () => {
      if (closed) return
      try {
        const ws = new WebSocket(wsUrl("/ws/telemetry"))
        wsRef.current = ws
        ws.onopen = () => {
          if (!closed) setConnected(true)
        }
        ws.onmessage = (e) => {
          if (closed) return
          try {
            const tick = JSON.parse(e.data) as TelemetryTick
            if (tick.machine_id)
              setTicks((prev) => ({ ...prev, [tick.machine_id]: tick }))
          } catch {
            /* keepalive / non-JSON */
          }
        }
        ws.onclose = () => {
          if (closed) return
          setConnected(false)
          retry = setTimeout(connect, WS_RECONNECT_MS)
        }
        ws.onerror = () => ws.close()
      } catch {
        if (!closed) retry = setTimeout(connect, WS_RECONNECT_MS)
      }
    }
    connect()

    return () => {
      closed = true
      if (retry) clearTimeout(retry)
      const ws = wsRef.current
      if (ws) {
        // Detach handlers so a late close/error can't reconnect or setState.
        ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null
        ws.close()
        wsRef.current = null
      }
    }
  }, [])

  return { ticks, connected }
}
