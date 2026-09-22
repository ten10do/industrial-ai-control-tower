import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'
import { AssetsConfigPage } from './pages'
import type {
  AssetTree,
  ConfigurationAuditEvent,
  ConfigurationDetail,
  ConfigurationStatus,
  ConfigurationSummary,
} from './types'

const timestamp = '2026-09-22T04:00:00Z'

const tree: AssetTree = {
  sites: [
    {
      id: 'site-1',
      name: 'Plant A',
      asset_type: 'SITE',
      parent_id: null,
      description: 'Main production plant',
      devices: [],
      children: [
        {
          id: 'line-1',
          name: 'Line 1',
          asset_type: 'LINE',
          parent_id: 'site-1',
          description: '',
          children: [],
          devices: [
            {
              device_id: 'MOTOR-001',
              name: 'Mill motor',
              device_type: 'MOTOR',
              status: 'ACTIVE',
              asset_node_id: 'line-1',
              metadata: {},
              protocol: 'modbus_tcp',
              published_version: 2,
              applied_version: 1,
              apply_status: 'FAILED',
              in_sync: false,
            },
          ],
        },
      ],
    },
  ],
  unassigned_devices: [
    {
      device_id: 'MOTOR-002',
      name: 'Conveyor motor',
      device_type: 'MOTOR',
      status: 'ACTIVE',
      asset_node_id: null,
      metadata: {},
      protocol: null,
      published_version: null,
      applied_version: null,
      apply_status: 'PENDING',
      in_sync: false,
    },
  ],
}

const history: ConfigurationSummary[] = [
  { version: 3, status: 'DRAFT', protocol: 'modbus_tcp', created_by: 'operator.one', created_at: timestamp, validated_at: null, published_at: null, archived_at: null },
  { version: 2, status: 'PUBLISHED', protocol: 'modbus_tcp', created_by: 'operator.one', created_at: timestamp, validated_at: timestamp, published_at: timestamp, archived_at: null },
  { version: 1, status: 'ARCHIVED', protocol: 'modbus_tcp', created_by: 'operator.one', created_at: timestamp, validated_at: timestamp, published_at: timestamp, archived_at: timestamp },
]

const status: ConfigurationStatus = {
  device_id: 'MOTOR-001',
  desired_version: 2,
  applied_version: 1,
  apply_status: 'FAILED',
  source: 'database',
  last_apply_at: timestamp,
  last_apply_error: 'connection refused: localhost:5021',
  in_sync: false,
  protocol: 'modbus_tcp',
  runtime_state: 'CONNECTED',
}

const draftDetail: ConfigurationDetail = {
  id: 'cfg-3',
  device_id: 'MOTOR-001',
  version: 3,
  status: 'DRAFT',
  protocol: 'modbus_tcp',
  configuration: { device_id: 'MOTOR-001', protocol: 'modbus_tcp', poll_interval_ms: 1000 },
  validation_result: {},
  validation_error: null,
  created_by: 'operator.one',
  created_at: timestamp,
  updated_at: timestamp,
  validated_at: null,
  published_at: null,
  archived_at: null,
}

const audit: ConfigurationAuditEvent[] = [
  { event_id: 'ev-2', device_id: 'MOTOR-001', event_type: 'CONFIG_APPLY_FAILED', config_version: 2, timestamp, actor: 'operator.one', status: 'FAILED', summary: 'v2 was not applied' },
  { event_id: 'ev-1', device_id: 'MOTOR-001', event_type: 'CONFIG_DRAFT_CREATED', config_version: 3, timestamp, actor: 'operator.one', status: 'SUCCESS', summary: 'draft v3 created' },
]

function stubQueries() {
  vi.spyOn(api, 'assetTree').mockResolvedValue(tree)
  vi.spyOn(api, 'assets').mockResolvedValue([
    { id: 'site-1', name: 'Plant A', asset_type: 'SITE', parent_id: null, description: '', metadata: {}, device_count: 0, created_at: timestamp, updated_at: timestamp },
    { id: 'line-1', name: 'Line 1', asset_type: 'LINE', parent_id: 'site-1', description: '', metadata: {}, device_count: 1, created_at: timestamp, updated_at: timestamp },
  ])
  vi.spyOn(api, 'deviceConfigurations').mockResolvedValue(history)
  vi.spyOn(api, 'configurationStatus').mockResolvedValue(status)
  vi.spyOn(api, 'configurationAudit').mockResolvedValue(audit)
  vi.spyOn(api, 'deviceConfiguration').mockResolvedValue(draftDetail)
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AssetsConfigPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('asset and device configuration control tower', () => {
  it('renders the hierarchy and reports desired versus applied honestly', async () => {
    stubQueries()
    renderPage()

    expect((await screen.findAllByText('Plant A')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Line 1').length).toBeGreaterThan(0)
    expect(screen.getAllByText('MOTOR-001').length).toBeGreaterThan(0)
    expect(screen.getAllByText('MOTOR-002').length).toBeGreaterThan(0)

    // A published version the runtime never converged on must be stated, not hidden.
    expect(await screen.findByText('Desired and applied differ')).toBeInTheDocument()
    expect(screen.getByText(/v2 is published but the runtime is running v1/)).toBeInTheDocument()
    expect(screen.getByText(/connection refused: localhost:5021/)).toBeInTheDocument()
    expect(screen.getAllByText('No published configuration').length).toBeGreaterThan(0)
    expect(screen.getByText('Runtime drift')).toBeInTheDocument()
  })

  it('loads the selected version payload into the editor and shows history and audit', async () => {
    stubQueries()
    renderPage()

    const editor = (await screen.findByLabelText(/Configuration payload/)) as HTMLTextAreaElement
    await waitFor(() => expect(editor.value).toContain('"device_id": "MOTOR-001"'))
    expect(editor.value).toContain('"poll_interval_ms": 1000')

    expect(screen.getByText('Editing draft v3')).toBeInTheDocument()
    expect(screen.getByText('Immutable snapshots')).toBeInTheDocument()
    expect(screen.getAllByText('v3').length).toBeGreaterThan(0)
    expect(screen.getAllByText('v1').length).toBeGreaterThan(0)
    expect(screen.getByText('APPLY FAILED')).toBeInTheDocument()
    expect(screen.getByText('DRAFT CREATED')).toBeInTheDocument()
  })

  it('publishes the draft version and reports the resulting apply state', async () => {
    stubQueries()
    const publish = vi.spyOn(api, 'publishDeviceConfiguration').mockResolvedValue({
      configuration: { ...draftDetail, status: 'PUBLISHED', published_at: timestamp },
      status: { ...status, desired_version: 3, applied_version: 3, apply_status: 'APPLIED', in_sync: true, last_apply_error: null },
    })
    renderPage()

    await screen.findByText('Editing draft v3')
    fireEvent.click(screen.getByRole('button', { name: 'Publish' }))

    await waitFor(() => expect(publish).toHaveBeenCalled())
    expect(publish.mock.calls[0]).toEqual(['MOTOR-001', 3, 'control-tower-operator'])
    expect(await screen.findByText('v3 published and applied.')).toBeInTheDocument()
  })

  it('renders structured validation issues instead of a single sentence', async () => {
    stubQueries()
    vi.spyOn(api, 'publishDeviceConfiguration').mockRejectedValue(
      new ApiError(
        'configuration v3 failed validation and was not published',
        422,
        'CONFIGURATION_VALIDATION_FAILED',
        'trace-422',
        {
          error: {
            code: 'CONFIGURATION_VALIDATION_FAILED',
            message: 'configuration v3 failed validation and was not published',
            trace_id: 'trace-422',
            details: {
              errors: [
                { field: 'modbus_tcp.registers.power', code: 'MISSING_SIGNAL', message: 'power is missing' },
                { field: 'modbus_tcp.port', code: 'PROTOCOL_MAPPING_INVALID', message: 'port is out of range' },
              ],
            },
          },
        },
      ),
    )
    renderPage()

    await screen.findByText('Editing draft v3')
    fireEvent.click(screen.getByRole('button', { name: 'Publish' }))

    expect(await screen.findByText('MISSING_SIGNAL')).toBeInTheDocument()
    expect(screen.getByText('modbus_tcp.registers.power')).toBeInTheDocument()
    expect(screen.getByText('power is missing')).toBeInTheDocument()
    expect(screen.getByText('PROTOCOL_MAPPING_INVALID')).toBeInTheDocument()
    expect(screen.getByText('2 validation issues')).toBeInTheDocument()
    expect(screen.getByText('Trace trace-422')).toBeInTheDocument()
  })

  it('explains a refused action instead of claiming the runtime converged', async () => {
    stubQueries()
    vi.spyOn(api, 'applyConfiguration').mockRejectedValue(
      new ApiError('gateway runtime is not available in this process', 503, 'APPLY_UNAVAILABLE', 'trace-503'),
    )
    renderPage()

    await screen.findByText('Editing draft v3')
    fireEvent.click(screen.getByRole('button', { name: 'Retry apply' }))

    expect(await screen.findByText('Capability unavailable')).toBeInTheDocument()
  })

  it('retries the apply for the published version on request', async () => {
    stubQueries()
    const apply = vi.spyOn(api, 'applyConfiguration').mockResolvedValue({
      ...status,
      desired_version: 2,
      applied_version: 2,
      apply_status: 'APPLIED',
      in_sync: true,
      last_apply_error: null,
    })
    renderPage()

    await screen.findByText('Editing draft v3')
    fireEvent.click(screen.getByRole('button', { name: 'Retry apply' }))

    await waitFor(() => expect(apply).toHaveBeenCalled())
    expect(apply.mock.calls[0][0]).toBe('MOTOR-001')
    expect(await screen.findByText('Runtime reconverged with the published version.')).toBeInTheDocument()
  })

  it('states that device identity and control are out of scope for this page', async () => {
    stubQueries()
    renderPage()

    expect(await screen.findByText(/never creates a second device identity/)).toBeInTheDocument()
    expect(screen.getByText(/No PLC write, register write, or actuator command exists/)).toBeInTheDocument()
  })
})
