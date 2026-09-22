import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BUFFER_LIMIT, useTelemetryStream } from './useTelemetryStream'
import type { Telemetry } from './types'

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  constructor(readonly url: string) { FakeWebSocket.instances.push(this) }
  close() { this.onclose?.() }
}

function point(index: number): Telemetry {
  return { id: String(index), schema_version: '1.0', timestamp: new Date(index * 1000).toISOString(), device_id: 'MOTOR-001', temperature_c: index, bearing_temperature_c: index, vibration_mm_s: index, current_a: index, voltage_v: 400, rpm: 1450, load_pct: 70, power_kw: 4, operating_state: 'RUNNING', fault_state: 'NORMAL', ingested_at: new Date(index * 1000).toISOString() }
}

function Probe({ initial = [] }: { initial?: Telemetry[] }) {
  const stream = useTelemetryStream('MOTOR-001', initial)
  return <div><span>{stream.connection}</span><span data-testid="count">{stream.points.length}</span></div>
}

beforeEach(() => {
  FakeWebSocket.instances = []
  vi.useFakeTimers()
  vi.stubGlobal('WebSocket', FakeWebSocket)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('telemetry WebSocket lifecycle', () => {
  it('connects, receives messages, and bounds the chart buffer', () => {
    render(<Probe initial={Array.from({ length: BUFFER_LIMIT }, (_, index) => point(index))} />)
    const socket = FakeWebSocket.instances[0]
    act(() => socket.onopen?.())
    expect(screen.getByText('CONNECTED')).toBeInTheDocument()
    act(() => socket.onmessage?.(new MessageEvent('message', { data: JSON.stringify(point(999)) })))
    expect(screen.getByTestId('count')).toHaveTextContent(String(BUFFER_LIMIT))
  })

  it('shows reconnecting and opens one replacement connection after backoff', () => {
    render(<Probe />)
    act(() => FakeWebSocket.instances[0].onclose?.())
    expect(screen.getByText('RECONNECTING')).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(1000))
    expect(FakeWebSocket.instances).toHaveLength(2)
  })

  it('marks malformed messages as an error', () => {
    render(<Probe />)
    act(() => FakeWebSocket.instances[0].onmessage?.(new MessageEvent('message', { data: '{bad' })))
    expect(screen.getByText('ERROR')).toBeInTheDocument()
  })
})
