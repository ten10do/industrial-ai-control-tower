import { useEffect, useState } from 'react'
import { websocketUrl } from './api'
import type { Telemetry } from './types'

export type ConnectionState =
  | 'CONNECTING'
  | 'CONNECTED'
  | 'RECONNECTING'
  | 'DISCONNECTED'
  | 'ERROR'

const BUFFER_LIMIT = 300
const MAX_RETRIES = 6

export function useTelemetryStream(deviceId: string, initial: Telemetry[] = []) {
  const [points, setPoints] = useState<Telemetry[]>(() => initial.slice(-BUFFER_LIMIT))
  const [connection, setConnection] = useState<ConnectionState>('CONNECTING')
  const initialTimestamp = initial.length ? initial[initial.length - 1].timestamp : undefined

  useEffect(() => {
    if (initial.length) setPoints(initial.slice(-BUFFER_LIMIT))
  }, [deviceId, initialTimestamp]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let socket: WebSocket | undefined
    let retryTimer: number | undefined
    let disposed = false
    let attempts = 0

    const connect = () => {
      if (disposed) return
      setConnection(attempts ? 'RECONNECTING' : 'CONNECTING')
      socket = new WebSocket(websocketUrl(deviceId))
      socket.onopen = () => {
        attempts = 0
        setConnection('CONNECTED')
      }
      socket.onmessage = (event) => {
        try {
          const point = JSON.parse(String(event.data)) as Telemetry
          setPoints((current) => [...current, point].slice(-BUFFER_LIMIT))
        } catch {
          setConnection('ERROR')
        }
      }
      socket.onerror = () => setConnection('ERROR')
      socket.onclose = () => {
        if (disposed) return
        if (attempts >= MAX_RETRIES) {
          setConnection('DISCONNECTED')
          return
        }
        attempts += 1
        setConnection('RECONNECTING')
        retryTimer = window.setTimeout(connect, Math.min(1000 * 2 ** (attempts - 1), 10_000))
      }
    }

    connect()
    return () => {
      disposed = true
      if (retryTimer) window.clearTimeout(retryTimer)
      socket?.close()
    }
  }, [deviceId])

  return { points, connection, latest: points.length ? points[points.length - 1] : undefined }
}

export { BUFFER_LIMIT }
