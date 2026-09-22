import type {
  Alarm,
  ApiErrorPayload,
  Approval,
  Device,
  Diagnosis,
  IncidentDetail,
  IncidentSummary,
  KnowledgeDocument,
  ReadyStatus,
  Telemetry,
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
}

export function websocketUrl(deviceId: string): string {
  const configured = (import.meta.env.VITE_WS_BASE_URL ?? '').replace(/\/$/, '')
  const base = configured || `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`
  return `${base}/ws/devices/${encodeURIComponent(deviceId)}/telemetry`
}
