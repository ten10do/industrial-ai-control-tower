import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'
import { ConnectivityPage } from './pages'
import type { ConnectivityDevice, ConnectivitySummary } from './types'

const timestamp = '2026-09-22T04:00:00Z'

const modbusDevice: ConnectivityDevice = {
  device_id: 'MOTOR-002',
  protocol: 'modbus_tcp',
  enabled: true,
  state: 'CONNECTED',
  state_mode: 'static',
  polled: true,
  poll_interval_ms: 1000,
  endpoint: 'localhost:5020',
  last_success: timestamp,
  last_error: null,
  message: null,
  consecutive_failures: 0,
  reconnect_attempts: 0,
  samples_ingested: 42,
  samples_rejected: 0,
  read_errors: 0,
}

const mqttDevice: ConnectivityDevice = {
  device_id: 'MOTOR-004',
  protocol: 'mqtt',
  enabled: true,
  state: 'CONNECTED',
  state_mode: 'static',
  polled: false,
  poll_interval_ms: 1000,
  endpoint: null,
  last_success: null,
  last_error: null,
  message: null,
  consecutive_failures: 0,
  reconnect_attempts: 0,
  samples_ingested: 0,
  samples_rejected: 0,
  read_errors: 0,
}

const summary: ConnectivitySummary = {
  gateway_enabled: true,
  gateway_available: true,
  gateway_error: null,
  config_file: 'gateway_devices.yaml',
  loaded_at: timestamp,
  device_count: 2,
  enabled_device_count: 2,
  states: { CONNECTED: 2 },
  total_samples_ingested: 42,
  total_samples_rejected: 0,
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ConnectivityPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('protocol gateway connectivity dashboard', () => {
  it('reports inventory, connection, and ingestion metrics', async () => {
    vi.spyOn(api, 'connectivitySummary').mockResolvedValue(summary)
    vi.spyOn(api, 'connectivityDevices').mockResolvedValue([modbusDevice, mqttDevice])
    renderPage()
    expect(await screen.findByText('gateway_devices.yaml')).toBeInTheDocument()
    expect(screen.getByText('2 enabled')).toBeInTheDocument()
    expect(screen.getByText('Samples ingested')).toBeInTheDocument()
    expect(screen.getByText('0 rejected by the contract')).toBeInTheDocument()
    expect(screen.getByText('MOTOR-002')).toBeInTheDocument()
    expect(screen.getByText('localhost:5020')).toBeInTheDocument()
    expect(screen.getByText('42 ingested')).toBeInTheDocument()
  })

  it('explains an unavailable gateway without inventing devices', async () => {
    vi.spyOn(api, 'connectivitySummary').mockResolvedValue({
      ...summary,
      gateway_available: false,
      gateway_error: 'gateway configuration is empty',
      config_file: null,
      loaded_at: null,
      device_count: 0,
      enabled_device_count: 0,
      states: {},
      total_samples_ingested: 0,
    })
    vi.spyOn(api, 'connectivityDevices').mockResolvedValue([])
    renderPage()
    expect(await screen.findByText('Gateway unavailable')).toBeInTheDocument()
    expect(screen.getByText('gateway configuration is empty')).toBeInTheDocument()
    expect(
      screen.getByText('No devices are configured for the protocol gateway.'),
    ).toBeInTheDocument()
  })

  it('does not offer polling control for a pushed protocol', async () => {
    vi.spyOn(api, 'connectivitySummary').mockResolvedValue(summary)
    vi.spyOn(api, 'connectivityDevices').mockResolvedValue([mqttDevice])
    renderPage()
    await screen.findByText('MOTOR-004')
    expect(screen.getByText('Not polled')).toBeInTheDocument()
    expect(screen.getByText('Handled by the MQTT consumer')).toBeInTheDocument()
    for (const button of screen.getAllByRole('button')) {
      expect(button).toBeDisabled()
    }
  })

  it('starts polling for a polled device on request', async () => {
    const start = vi
      .spyOn(api, 'startConnectivityDevice')
      .mockResolvedValue({ ...modbusDevice, state: 'STARTING' })
    vi.spyOn(api, 'connectivitySummary').mockResolvedValue(summary)
    vi.spyOn(api, 'connectivityDevices').mockResolvedValue([modbusDevice])
    renderPage()
    await screen.findByText('MOTOR-002')
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await waitFor(() => expect(start).toHaveBeenCalled())
    expect(start.mock.calls[0][0]).toBe('MOTOR-002')
  })

  it('states that no endpoint can command equipment', async () => {
    vi.spyOn(api, 'connectivitySummary').mockResolvedValue(summary)
    vi.spyOn(api, 'connectivityDevices').mockResolvedValue([modbusDevice])
    renderPage()
    expect(await screen.findByText(/actuator command exists/)).toBeInTheDocument()
    expect(screen.getByText(/same ingestion boundary the MQTT consumer uses/)).toBeInTheDocument()
  })
})
