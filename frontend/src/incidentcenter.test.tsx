import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'
import { OPERATOR_IDENTITY, withAuth } from './authTestUtils'
import { IncidentDetailPage, IncidentsPage } from './pages'
import type {
  Alarm,
  Diagnosis,
  IncidentDashboard,
  IncidentDetail,
  IncidentMetrics,
  IncidentSummary,
  IncidentWorkflowBridge,
  Workflow,
} from './types'

const timestamp = '2026-09-23T08:00:00Z'

const alarm: Alarm = {
  id: 'alarm-1',
  device_id: 'MOTOR-001',
  telemetry_id: null,
  rule_id: 'temperature_high',
  severity: 'CRITICAL',
  status: 'ACTIVE',
  message: 'Temperature above 90C',
  started_at: timestamp,
  cleared_at: null,
  acknowledged_at: null,
  last_triggered_at: timestamp,
  occurrence_count: 3,
}

const dashboard: IncidentDashboard = {
  summary: { active: 2, critical: 1, unacknowledged: 1 },
  incidents: [
    {
      incident_id: 'incident-1',
      title: 'Bearing alarm cluster',
      status: 'OPEN',
      severity: 'CRITICAL',
      priority: 'URGENT',
      device_id: 'MOTOR-001',
      asset_name: 'Plant A',
      workflow_status: 'WAITING_APPROVAL',
      created_at: timestamp,
      last_alarm_at: timestamp,
      resolved_at: null,
    },
    {
      incident_id: 'incident-2',
      title: 'Vibration drift',
      status: 'RESOLVED',
      severity: 'MINOR',
      priority: 'LOW',
      device_id: 'MOTOR-002',
      asset_name: 'Plant B',
      workflow_status: null,
      created_at: timestamp,
      last_alarm_at: null,
      resolved_at: timestamp,
    },
  ],
}

const summaryRow: IncidentSummary = {
  incident_id: 'incident-1',
  device_id: 'MOTOR-001',
  diagnosis_id: 'diagnosis-1',
  title: 'Bearing alarm cluster',
  status: 'OPEN',
  priority: 'URGENT',
  created_at: timestamp,
  updated_at: timestamp,
  diagnosis_status: 'FAULT',
  fault_type: 'BEARING_WEAR',
  severity: 'CRITICAL',
  workflow_run_id: null,
  workflow_status: 'WAITING_APPROVAL',
  work_order_id: null,
}

const detail: IncidentDetail = {
  ...summaryRow,
  description: 'Correlated condition on the line.',
  alarms: [alarm],
  device: { device_id: 'MOTOR-001', device_type: 'MOTOR', name: 'Motor 001', status: 'ACTIVE' },
  asset: { id: 'asset-1', name: 'Plant A', asset_type: 'SITE', parent_id: null },
  workflow: null,
  diagnosis: {
    id: 'diagnosis-1',
    device_id: 'MOTOR-001',
    window_start: timestamp,
    window_end: timestamp,
    status: 'FAULT',
    fault_type: 'BEARING_WEAR',
    anomaly_score: 0.7,
    confidence: 0.9,
    severity: 'HIGH',
    evidence: [],
    model_version: 'diagnosis-v1.1',
    feature_version: 'features-v1',
    trace_id: 'trace-1',
    created_at: timestamp,
  } satisfies Diagnosis,
}

const bridge: IncidentWorkflowBridge = {
  incident_id: 'incident-1',
  workflow_exists: false,
  workflow_run_id: null,
  workflow_status: null,
  approval_required: false,
}

const metrics: IncidentMetrics = { mtta_seconds: 120, mttr_seconds: 3600, alarm_compression: 8.5 }

function renderCenter() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    withAuth(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/incidents']}>
          <Routes>
            <Route path="/incidents" element={<IncidentsPage />} />
            <Route path="/incidents/:incidentId" element={<IncidentDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
      OPERATOR_IDENTITY,
    ),
  )
}

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    withAuth(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/incidents/incident-1']}>
          <Routes>
            <Route path="/incidents" element={<IncidentsPage />} />
            <Route path="/incidents/:incidentId" element={<IncidentDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
      OPERATOR_IDENTITY,
    ),
  )
}

afterEach(() => { vi.restoreAllMocks() })

describe('incident center list', () => {
  it('renders header metrics and the incident table', async () => {
    vi.spyOn(api, 'incidentDashboard').mockResolvedValue(dashboard)
    vi.spyOn(api, 'incidentMetrics').mockResolvedValue(metrics)
    renderCenter()
    expect(await screen.findByText('Bearing alarm cluster')).toBeInTheDocument()
    expect(screen.getByText('Vibration drift')).toBeInTheDocument()
    expect(screen.getByText('Plant A')).toBeInTheDocument()
    expect(screen.getByLabelText('Status: WAITING_APPROVAL')).toBeInTheDocument()
    expect(screen.getByText(/MTTA/)).toBeInTheDocument()
    expect(screen.getByText('8.5')).toBeInTheDocument()
  })

  it('filters incidents by severity', async () => {
    vi.spyOn(api, 'incidentDashboard').mockResolvedValue(dashboard)
    vi.spyOn(api, 'incidentMetrics').mockResolvedValue(metrics)
    renderCenter()
    await screen.findByText('Bearing alarm cluster')
    fireEvent.change(screen.getByLabelText('Severity'), { target: { value: 'CRITICAL' } })
    expect(screen.getByText('Bearing alarm cluster')).toBeInTheDocument()
    expect(screen.queryByText('Vibration drift')).not.toBeInTheDocument()
  })

  it('navigates from a row to the incident detail', async () => {
    vi.spyOn(api, 'incidentDashboard').mockResolvedValue(dashboard)
    vi.spyOn(api, 'incidentMetrics').mockResolvedValue(metrics)
    vi.spyOn(api, 'incident').mockResolvedValue(detail)
    vi.spyOn(api, 'incidentWorkflowContext').mockResolvedValue(bridge)
    renderCenter()
    fireEvent.click(await screen.findByText('Bearing alarm cluster'))
    expect(await screen.findByText('Correlated alarm instances')).toBeInTheDocument()
  })
})

describe('incident detail', () => {
  it('displays overview, alarm timeline, and diagnosis evidence', async () => {
    vi.spyOn(api, 'incident').mockResolvedValue(detail)
    vi.spyOn(api, 'incidentWorkflowContext').mockResolvedValue(bridge)
    renderDetail()
    expect(await screen.findByText('Correlated alarm instances')).toBeInTheDocument()
    expect(screen.getByText('temperature_high')).toBeInTheDocument()
    expect(screen.getByText('BEARING_WEAR')).toBeInTheDocument()
    expect(screen.getByText('Plant A')).toBeInTheDocument()
    expect(screen.getByText('Start Workflow')).toBeEnabled()
  })

  it('acknowledges an open incident through the lifecycle command', async () => {
    vi.spyOn(api, 'incident').mockResolvedValue(detail)
    vi.spyOn(api, 'incidentWorkflowContext').mockResolvedValue(bridge)
    const acknowledge = vi.spyOn(api, 'acknowledgeIncident').mockResolvedValue({})
    renderDetail()
    const button = await screen.findByRole('button', { name: 'Acknowledge' })
    expect(button).toBeEnabled()
    fireEvent.click(button)
    await waitFor(() => expect(acknowledge).toHaveBeenCalledWith('incident-1'))
  })

  it('shows the waiting-approval notice when the bridge reports a pending gate', async () => {
    vi.spyOn(api, 'incident').mockResolvedValue({ ...detail, workflow_run_id: 'workflow-1' })
    vi.spyOn(api, 'incidentWorkflowContext').mockResolvedValue({ ...bridge, workflow_exists: true, workflow_run_id: 'workflow-1', workflow_status: 'WAITING_APPROVAL', approval_required: true })
    const workflow = {
      workflow_run_id: 'workflow-1', incident_id: 'incident-1', diagnosis_id: 'diagnosis-1', device_id: 'MOTOR-001', status: 'WAITING_APPROVAL', current_stage: 'WAITING_APPROVAL', workflow_version: 'v1', policy_version: 'safety-policy-v1', provider: 'test', model: 'test-model', created_at: timestamp, updated_at: timestamp,
      state: { diagnosis: { id: 'diagnosis-1', status: 'FAULT', fault_type: 'BEARING_WEAR', confidence: 0.9, severity: 'HIGH', model_version: 'diagnosis-v1.1' }, sensor_evidence: [], knowledge_context: { retrieval_run_id: null, sufficiency: 'SUFFICIENT', evidence: [] }, triage_result: null, maintenance_plan: null, safety_review: null, policy_decision: null, approval: null, work_order_id: null, current_stage: 'WAITING_APPROVAL', status: 'WAITING_APPROVAL', errors: [] },
    } satisfies Workflow
    vi.spyOn(api, 'workflow').mockResolvedValue(workflow)
    vi.spyOn(api, 'workflowTrace').mockResolvedValue({ workflow, agent_runs: [] })
    vi.spyOn(api, 'knowledgeDocuments').mockResolvedValue([])
    renderDetail()
    expect(await screen.findByText('Waiting approval')).toBeInTheDocument()
    expect(screen.getByText(/the operator approves/i)).toBeInTheDocument()
  })
})
