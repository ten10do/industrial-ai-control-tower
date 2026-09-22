import type {
  Alarm,
  ApiErrorPayload,
  Approval,
  AssetNode,
  AssetTree,
  ConfigurationAuditEvent,
  ConfigurationDetail,
  ConfigurationStatus,
  ConfigurationSummary,
  ConnectivityDevice,
  ConnectivitySummary,
  Device,
  Diagnosis,
  IncidentDetail,
  IncidentSummary,
  KnowledgeDocument,
  ObservabilityMetrics,
  ObservabilityRun,
  ObservabilityRunTrace,
  PublishResult,
  ReadyStatus,
  Telemetry,
  ValidationResult,
  Workflow,
  WorkflowSummary,
  WorkflowTrace,
  WorkOrder,
} from './types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly traceId?: string,
    readonly details?: ApiErrorPayload,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    throw new ApiError('Backend unavailable. Check the Control Tower connection.', 0, 'NETWORK_ERROR')
  }
  const body = (await response.json().catch(() => ({}))) as ApiErrorPayload
  if (!response.ok) {
    const message =
      body.error?.message ??
      (response.status === 503 ? 'Capability unavailable.' : `Request failed (${response.status}).`)
    throw new ApiError(
      message,
      response.status,
      body.error?.code ?? `HTTP_${response.status}`,
      body.error?.trace_id,
      body,
    )
  }
  return body as T
}

export const api = {
  health: () => request<{ status: string }>('/health'),
  ready: () => request<ReadyStatus>('/ready'),
  devices: () => request<Device[]>('/api/v1/devices?limit=200'),
  device: (id: string) => request<Device>(`/api/v1/devices/${encodeURIComponent(id)}`),
  telemetry: (id: string, start: string) =>
    request<{ items: Telemetry[]; next_cursor: string | null }>(
      `/api/v1/devices/${encodeURIComponent(id)}/telemetry?limit=300&start=${encodeURIComponent(start)}`,
    ),
  latestTelemetry: (id: string) =>
    request<Telemetry>(`/api/v1/devices/${encodeURIComponent(id)}/telemetry/latest`),
  latestDiagnosis: (id: string) =>
    request<Diagnosis>(`/api/v1/devices/${encodeURIComponent(id)}/diagnoses/latest`),
  alarms: (id?: string) =>
    request<Alarm[]>(`/api/v1/alarms?limit=200${id ? `&device_id=${encodeURIComponent(id)}` : ''}`),
  incidents: (status?: string) =>
    request<IncidentSummary[]>(`/api/v1/incidents?limit=100${status ? `&status=${status}` : ''}`),
  incident: (id: string) => request<IncidentDetail>(`/api/v1/incidents/${id}`),
  workflows: () => request<WorkflowSummary[]>('/api/v1/workflows?limit=100'),
  workflow: (id: string) => request<Workflow>(`/api/v1/workflows/${id}`),
  workflowTrace: (id: string) => request<WorkflowTrace>(`/api/v1/workflows/${id}/trace`),
  approvals: () => request<Approval[]>('/api/v1/approvals/pending'),
  approval: (id: string) => request<Approval>(`/api/v1/approvals/${id}`),
  decide: (id: string, decision: 'approve' | 'reject', actor: string, reason: string) =>
    request<Workflow>(`/api/v1/approvals/${id}/${decision}`, {
      method: 'POST',
      headers: { 'X-Development-Actor': actor },
      body: JSON.stringify({ reason }),
    }),
  workOrders: () => request<WorkOrder[]>('/api/v1/work-orders?limit=100'),
  workOrder: (id: string) => request<WorkOrder>(`/api/v1/work-orders/${id}`),
  knowledgeDocuments: () => request<KnowledgeDocument[]>('/api/v1/knowledge/documents?limit=200'),
  observabilityRuns: () => request<ObservabilityRun[]>('/api/observability/runs?limit=50'),
  observabilityMetrics: () => request<ObservabilityMetrics>('/api/observability/metrics'),
  observabilityRun: (id: string) =>
    request<ObservabilityRunTrace>(`/api/observability/runs/${encodeURIComponent(id)}`),
  connectivitySummary: () => request<ConnectivitySummary>('/api/v1/connectivity/summary'),
  connectivityDevices: () => request<ConnectivityDevice[]>('/api/v1/connectivity/devices'),
  startConnectivityDevice: (id: string) =>
    request<ConnectivityDevice>(`/api/v1/connectivity/devices/${encodeURIComponent(id)}/start`, {
      method: 'POST',
    }),
  stopConnectivityDevice: (id: string) =>
    request<ConnectivityDevice>(`/api/v1/connectivity/devices/${encodeURIComponent(id)}/stop`, {
      method: 'POST',
    }),
  assetTree: () => request<AssetTree>('/api/v1/assets/tree'),
  assets: () => request<AssetNode[]>('/api/v1/assets'),
  createAsset: (payload: { name: string; asset_type: string; parent_id?: string | null }) =>
    request<AssetNode>('/api/v1/assets', { method: 'POST', body: JSON.stringify(payload) }),
  deleteAsset: (assetId: string) =>
    request<void>(`/api/v1/assets/${encodeURIComponent(assetId)}`, { method: 'DELETE' }),
  attachDevice: (assetId: string, deviceId: string) =>
    request<void>(
      `/api/v1/assets/${encodeURIComponent(assetId)}/devices/${encodeURIComponent(deviceId)}`,
      { method: 'PUT' },
    ),
  detachDevice: (assetId: string, deviceId: string) =>
    request<void>(
      `/api/v1/assets/${encodeURIComponent(assetId)}/devices/${encodeURIComponent(deviceId)}`,
      { method: 'DELETE' },
    ),
  deviceConfigurations: (deviceId: string) =>
    request<ConfigurationSummary[]>(
      `/api/v1/devices/${encodeURIComponent(deviceId)}/configurations`,
    ),
  deviceConfiguration: (deviceId: string, version: number) =>
    request<ConfigurationDetail>(
      `/api/v1/devices/${encodeURIComponent(deviceId)}/configurations/${version}`,
    ),
  createDeviceConfiguration: (deviceId: string, payload: Record<string, unknown>, actor: string) =>
    request<ConfigurationDetail>(
      `/api/v1/devices/${encodeURIComponent(deviceId)}/configurations`,
      { method: 'POST', body: JSON.stringify(payload), headers: actorHeader(actor) },
    ),
  updateDeviceConfiguration: (
    deviceId: string,
    version: number,
    payload: Record<string, unknown>,
    actor: string,
  ) =>
    request<ConfigurationDetail>(
      `/api/v1/devices/${encodeURIComponent(deviceId)}/configurations/${version}`,
      { method: 'PATCH', body: JSON.stringify(payload), headers: actorHeader(actor) },
    ),
  deleteDeviceConfiguration: (deviceId: string, version: number) =>
    request<void>(
      `/api/v1/devices/${encodeURIComponent(deviceId)}/configurations/${version}`,
      { method: 'DELETE' },
    ),
  validateDeviceConfiguration: (deviceId: string, version: number) =>
    request<ValidationResult>(
      `/api/v1/devices/${encodeURIComponent(deviceId)}/configurations/${version}/validate`,
      { method: 'POST' },
    ),
  cloneDeviceConfiguration: (deviceId: string, version: number, actor: string) =>
    request<ConfigurationDetail>(
      `/api/v1/devices/${encodeURIComponent(deviceId)}/configurations/${version}/clone`,
      { method: 'POST', headers: actorHeader(actor) },
    ),
  publishDeviceConfiguration: (deviceId: string, version: number, actor: string) =>
    request<PublishResult>(
      `/api/v1/devices/${encodeURIComponent(deviceId)}/configurations/${version}/publish`,
      { method: 'POST', headers: actorHeader(actor) },
    ),
  configurationStatus: (deviceId: string) =>
    request<ConfigurationStatus>(
      `/api/v1/devices/${encodeURIComponent(deviceId)}/configuration-status`,
    ),
  applyConfiguration: (deviceId: string, actor: string) =>
    request<ConfigurationStatus>(
      `/api/v1/devices/${encodeURIComponent(deviceId)}/configuration-status/apply`,
      { method: 'POST', headers: actorHeader(actor) },
    ),
  configurationAudit: (deviceId: string) =>
    request<ConfigurationAuditEvent[]>(
      `/api/v1/devices/${encodeURIComponent(deviceId)}/configuration-audit?limit=100`,
    ),
}

/**
 * Descriptive actor metadata only. The backend treats this as a label, never as
 * authentication, and an absent header defaults to `system`.
 */
function actorHeader(actor: string): Record<string, string> {
  const trimmed = actor.trim()
  return trimmed ? { 'X-Actor': trimmed } : {}
}

export function websocketUrl(deviceId: string): string {
  const configured = (import.meta.env.VITE_WS_BASE_URL ?? '').replace(/\/$/, '')
  const base = configured || `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`
  return `${base}/ws/devices/${encodeURIComponent(deviceId)}/telemetry`
}
