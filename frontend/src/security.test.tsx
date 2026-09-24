/**
 * Phase 6.12 frontend security tests.
 *
 * Four claims are checked, in the order they matter.
 *
 * 1. The token is held behind a storage abstraction that degrades safely.
 * 2. The API client attaches the credential, and treats a rejected credential
 *    (401) differently from a refused permission (403).
 * 3. The route guard keeps an anonymous visitor out of the shell, and the shell
 *    is only painted once the backend has confirmed who is calling.
 * 4. The interface withholds an action the caller cannot perform, and still
 *    surfaces the server's refusal when it happens anyway, because the hiding is
 *    cosmetic and the server is the authority.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'
import { AppShell } from './AppShell'
import { AuthProvider, RequireAuth } from './auth'
import {
  AUTH_TOKEN_KEY,
  createTokenStorage,
  getToken,
  setToken,
} from './authStorage'
import {
  OPERATOR_IDENTITY,
  OPERATOR_WITHOUT_REVIEW,
  VIEWER_IDENTITY,
  resetAuthStorage,
  withAuth,
} from './authTestUtils'
import { ApprovalDetailPage, IncidentDetailPage, LoginPage } from './pages'
import type {
  Approval,
  Identity,
  IncidentDetail,
  IncidentWorkflowBridge,
  IssuedToken,
  Workflow,
} from './types'

const timestamp = '2026-09-24T08:00:00Z'

const incident: IncidentDetail = {
  incident_id: 'incident-1',
  device_id: 'MOTOR-001',
  diagnosis_id: 'diagnosis-1',
  title: 'Bearing alarm cluster',
  status: 'ACKNOWLEDGED',
  priority: 'URGENT',
  created_at: timestamp,
  updated_at: timestamp,
  diagnosis_status: 'FAULT',
  fault_type: 'BEARING_WEAR',
  severity: 'CRITICAL',
  workflow_run_id: null,
  workflow_status: null,
  work_order_id: null,
  description: 'Correlated condition on the line.',
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
  },
  alarms: [],
  device: { device_id: 'MOTOR-001', device_type: 'MOTOR', name: 'Motor 001', status: 'ACTIVE' },
  asset: null,
  workflow: null,
}

const bridge: IncidentWorkflowBridge = {
  incident_id: 'incident-1',
  workflow_exists: false,
  workflow_run_id: null,
  workflow_status: null,
  approval_required: false,
}

const approval: Approval = {
  approval_id: 'approval-1',
  workflow_run_id: 'workflow-1',
  maintenance_plan_id: 'plan-1',
  status: 'PENDING',
  actor: null,
  reason: null,
  plan_version: 1,
  plan_hash: 'hash',
  created_at: timestamp,
  decided_at: null,
}

const workflow: Workflow = {
  workflow_run_id: 'workflow-1',
  incident_id: 'incident-1',
  diagnosis_id: 'diagnosis-1',
  device_id: 'MOTOR-001',
  status: 'WAITING_APPROVAL',
  current_stage: 'WAITING_APPROVAL',
  workflow_version: 'maintenance-decision-workflow-v1',
  policy_version: 'safety-policy-v1',
  provider: 'openai_compatible',
  model: 'deepseek-flash',
  created_at: timestamp,
  updated_at: timestamp,
  state: {
    diagnosis: {
      id: 'diagnosis-1',
      status: 'FAULT',
      fault_type: 'BEARING_WEAR',
      confidence: 0.9,
      severity: 'HIGH',
      model_version: 'diagnosis-v1.1',
    },
    sensor_evidence: [],
    knowledge_context: { retrieval_run_id: 'retrieval-1', sufficiency: 'SUFFICIENT', evidence: [] },
    triage_result: { problem_summary: 'Bearing wear' },
    maintenance_plan: {
      objective: 'Inspect bearing',
      steps: [{ action: 'Lock out and inspect bearing', action_type: 'LOCKOUT_TAGOUT', evidence_ids: ['ev-1'] }],
    },
    safety_review: { hazards: ['ROTATING_EQUIPMENT'], violations: [] },
    policy_decision: {
      decision: 'REQUIRES_APPROVAL',
      policy_version: 'safety-policy-v1',
      reasons: ['HIGH_SEVERITY'],
    },
    approval: null,
    work_order_id: null,
    current_stage: 'WAITING_APPROVAL',
    status: 'WAITING_APPROVAL',
    errors: [],
  },
}

function client() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
}

function renderIncident(identity: Identity | null) {
  return render(
    withAuth(
      <QueryClientProvider client={client()}>
        <MemoryRouter initialEntries={['/incidents/incident-1']}>
          <Routes>
            <Route path="/incidents/:incidentId" element={<IncidentDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
      identity,
    ),
  )
}

function renderApproval(identity: Identity | null) {
  return render(
    withAuth(
      <QueryClientProvider client={client()}>
        <MemoryRouter initialEntries={['/approvals/approval-1']}>
          <Routes>
            <Route path="/approvals/:approvalId" element={<ApprovalDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
      identity,
    ),
  )
}

function renderSignIn() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<RequireAuth />}>
            <Route path="/" element={<div>operations shell</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  )
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function sentHeaders(fetchMock: ReturnType<typeof vi.fn>) {
  return (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<string, string>
}

function fakeBacking() {
  const data = new Map<string, string>()
  return {
    get length() {
      return data.size
    },
    clear: () => data.clear(),
    getItem: (key: string) => data.get(key) ?? null,
    key: (index: number) => [...data.keys()][index] ?? null,
    removeItem: (key: string) => {
      data.delete(key)
    },
    setItem: (key: string, value: string) => {
      data.set(key, value)
    },
  }
}

function blockedBacking() {
  const refuse = () => {
    throw new Error('storage is blocked')
  }
  return { get length() { return 0 }, clear: refuse, getItem: refuse, key: refuse, removeItem: refuse, setItem: refuse }
}

beforeEach(() => {
  resetAuthStorage()
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('token storage abstraction', () => {
  it('round-trips a token through a Web Storage backing', () => {
    const backing = fakeBacking()
    const store = createTokenStorage(backing as unknown as Storage)
    expect(store.read()).toBeNull()
    store.write('token-1')
    expect(backing.getItem(AUTH_TOKEN_KEY)).toBe('token-1')
    expect(store.read()).toBe('token-1')
    store.clear()
    expect(store.read()).toBeNull()
  })

  it('falls back to an in-memory store when no backing exists', () => {
    const store = createTokenStorage(null)
    store.write('token-2')
    expect(store.read()).toBe('token-2')
  })

  it('does not throw, and stores nothing, when the backing refuses', () => {
    const store = createTokenStorage(blockedBacking() as unknown as Storage)
    expect(() => store.write('token-3')).not.toThrow()
    expect(store.read()).toBeNull()
    expect(() => store.clear()).not.toThrow()
  })

  it('treats an empty stored value as no token', () => {
    const backing = fakeBacking()
    backing.setItem(AUTH_TOKEN_KEY, '')
    expect(createTokenStorage(backing as unknown as Storage).read()).toBeNull()
  })
})

describe('credential handling in the API client', () => {
  it('attaches the stored token to a protected request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]))
    vi.stubGlobal('fetch', fetchMock)
    setToken('token-abc')
    await api.devices()
    expect(sentHeaders(fetchMock).Authorization).toBe('Bearer token-abc')
  })

  it('sends no credential on the sign-in call', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ access_token: 'new', token_type: 'bearer', expires_in: 60, expires_at: timestamp, user_id: 'u', username: 'operator', roles: [] }),
    )
    vi.stubGlobal('fetch', fetchMock)
    setToken('previous-token')
    await api.login('operator', 'a-long-enough-password')
    expect(sentHeaders(fetchMock).Authorization).toBeUndefined()
  })

  it('discards the credential the server rejects', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ error: { code: 'INVALID_TOKEN', message: 'nope' } }, 401)),
    )
    setToken('expired-token')
    await expect(api.devices()).rejects.toMatchObject({ status: 401, code: 'INVALID_TOKEN' })
    expect(getToken()).toBeNull()
  })

  it('keeps the session when the refusal is about permission, not identity', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ error: { code: 'PERMISSION_DENIED', message: 'no' } }, 403)),
    )
    setToken('valid-token')
    await expect(api.devices()).rejects.toMatchObject({ status: 403, code: 'PERMISSION_DENIED' })
    expect(getToken()).toBe('valid-token')
  })

  it('keeps an existing session when a second sign-in is rejected', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ error: { code: 'INVALID_CREDENTIALS', message: 'no' } }, 401)),
    )
    setToken('valid-token')
    await expect(api.login('operator', 'wrong')).rejects.toMatchObject({ status: 401 })
    expect(getToken()).toBe('valid-token')
  })
})

describe('sign-in', () => {
  it('stores the issued token and adopts the identity the backend reports', async () => {
    const issued: IssuedToken = {
      access_token: 'issued-token',
      token_type: 'bearer',
      expires_in: 3600,
      expires_at: timestamp,
      user_id: OPERATOR_IDENTITY.user_id,
      username: OPERATOR_IDENTITY.username,
      roles: ['OPERATOR'],
    }
    const login = vi.spyOn(api, 'login').mockResolvedValue(issued)
    const me = vi.spyOn(api, 'me').mockResolvedValue(OPERATOR_IDENTITY)
    renderSignIn()
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'operator' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'a-long-enough-password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('operations shell')).toBeInTheDocument()
    expect(login).toHaveBeenCalledWith('operator', 'a-long-enough-password')
    // Authority is read back from the server, never from the sign-in response.
    expect(me).toHaveBeenCalledTimes(1)
    expect(getToken()).toBe('issued-token')
  })

  it('reports a rejected sign-in and stores no credential', async () => {
    vi.spyOn(api, 'login').mockRejectedValue(
      new ApiError('Invalid username or password.', 401, 'INVALID_CREDENTIALS'),
    )
    renderSignIn()
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'operator' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password.')
    expect(getToken()).toBeNull()
  })
})

describe('route guard', () => {
  it('sends an anonymous visitor to the sign-in page', async () => {
    render(
      <AuthProvider>
        <MemoryRouter initialEntries={['/incidents']}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<RequireAuth />}>
              <Route path="/incidents" element={<div>incident centre</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthProvider>,
    )
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByText('incident centre')).not.toBeInTheDocument()
  })

  it('restores a session from a stored token before painting the shell', async () => {
    setToken('stored-token')
    const me = vi.spyOn(api, 'me').mockResolvedValue(OPERATOR_IDENTITY)
    render(
      <AuthProvider>
        <MemoryRouter initialEntries={['/']}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<RequireAuth />}>
              <Route path="/" element={<div>operations shell</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthProvider>,
    )
    expect(screen.getByText('Restoring session…')).toBeInTheDocument()
    expect(await screen.findByText('operations shell')).toBeInTheDocument()
    expect(me).toHaveBeenCalledTimes(1)
  })

  it('forgets a stored token the backend no longer accepts', async () => {
    setToken('stale-token')
    vi.spyOn(api, 'me').mockRejectedValue(new ApiError('The access token is not valid.', 401, 'INVALID_TOKEN'))
    render(
      <AuthProvider>
        <MemoryRouter initialEntries={['/']}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<RequireAuth />}>
              <Route path="/" element={<div>operations shell</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthProvider>,
    )
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(getToken()).toBeNull()
  })
})

describe('incident page permissions', () => {
  it('offers every lifecycle action to an operator', async () => {
    vi.spyOn(api, 'incident').mockResolvedValue(incident)
    vi.spyOn(api, 'incidentWorkflowContext').mockResolvedValue(bridge)
    renderIncident(OPERATOR_IDENTITY)
    expect(await screen.findByRole('button', { name: 'Acknowledge' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start Workflow' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Resolve' })).toBeInTheDocument()
  })

  it('withholds the acting actions from a viewer and says why', async () => {
    vi.spyOn(api, 'incident').mockResolvedValue(incident)
    vi.spyOn(api, 'incidentWorkflowContext').mockResolvedValue(bridge)
    renderIncident(VIEWER_IDENTITY)
    expect(await screen.findByText('Bearing alarm cluster')).toBeInTheDocument()
    // Reading is unaffected: the gating removes actions, not information.
    expect(screen.getByText('BEARING_WEAR')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Start Workflow' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Resolve' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Acknowledge' })).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('can read this incident but not act on it')
  })

  it('surfaces the server refusal even though the action was offered', async () => {
    vi.spyOn(api, 'incident').mockResolvedValue(incident)
    vi.spyOn(api, 'incidentWorkflowContext').mockResolvedValue(bridge)
    vi.spyOn(api, 'startIncidentWorkflow').mockRejectedValue(
      new ApiError('This identity is not allowed to perform that operation.', 403, 'PERMISSION_DENIED'),
    )
    renderIncident(OPERATOR_IDENTITY)
    fireEvent.click(await screen.findByRole('button', { name: 'Start Workflow' }))
    expect(
      await screen.findByText('This identity is not allowed to perform that operation.'),
    ).toBeInTheDocument()
  })
})

describe('approval page permissions', () => {
  beforeEach(() => {
    vi.spyOn(api, 'approval').mockResolvedValue(approval)
    vi.spyOn(api, 'workflow').mockResolvedValue(workflow)
    vi.spyOn(api, 'knowledgeDocuments').mockResolvedValue([])
  })

  it('lets an operator who may review record a decision', async () => {
    renderApproval(OPERATOR_IDENTITY)
    expect(await screen.findByRole('button', { name: 'Approve plan' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reject plan' })).toBeInTheDocument()
  })

  it('withholds the decision form from an operator without approval.review', async () => {
    renderApproval(OPERATOR_WITHOUT_REVIEW)
    expect(await screen.findByRole('heading', { name: 'Record operator decision' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve plan' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reject plan' })).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('needs the approval.review permission')
  })

  it('does not misreport a pending approval as already decided', async () => {
    renderApproval(OPERATOR_WITHOUT_REVIEW)
    await screen.findByRole('heading', { name: 'Record operator decision' })
    // The missing authority is the reason, so the approval state must not be
    // reported as the reason.
    expect(screen.queryByText(/This approval is no longer actionable/)).not.toBeInTheDocument()
  })
})

describe('shell session controls', () => {
  it('shows the signed-in identity and signs out on request', async () => {
    setToken('token-xyz')
    vi.spyOn(api, 'ready').mockResolvedValue({ status: 'ready', dependencies: {} })
    render(
      withAuth(
        <QueryClientProvider client={client()}>
          <MemoryRouter><AppShell /></MemoryRouter>
        </QueryClientProvider>,
        OPERATOR_IDENTITY,
      ),
    )

    expect(await screen.findByText('Signed in as operator')).toBeInTheDocument()
    expect(screen.getByText('OPERATOR')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(getToken()).toBeNull()
    expect(await screen.findByText('No active session')).toBeInTheDocument()
  })
})
