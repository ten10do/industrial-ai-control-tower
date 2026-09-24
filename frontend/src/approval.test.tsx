import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'
import { OPERATOR_IDENTITY, withAuth } from './authTestUtils'
import { ApprovalDetailPage } from './pages'
import type { Approval, Workflow } from './types'

const timestamp = '2026-09-21T00:00:00Z'
const approval: Approval = { approval_id: 'approval-1', workflow_run_id: 'workflow-1', maintenance_plan_id: 'plan-1', status: 'PENDING', actor: null, reason: null, plan_version: 1, plan_hash: 'hash', created_at: timestamp, decided_at: null }
const workflow: Workflow = {
  workflow_run_id: 'workflow-1', incident_id: 'incident-1', diagnosis_id: 'diagnosis-1', device_id: 'MOTOR-001', status: 'WAITING_APPROVAL', current_stage: 'WAITING_APPROVAL', workflow_version: 'maintenance-decision-workflow-v1', policy_version: 'safety-policy-v1', provider: 'openai_compatible', model: 'deepseek-flash', created_at: timestamp, updated_at: timestamp,
  state: { diagnosis: { id: 'diagnosis-1', status: 'FAULT', fault_type: 'BEARING_WEAR', confidence: .9, severity: 'HIGH', model_version: 'diagnosis-v1.1' }, sensor_evidence: [], knowledge_context: { retrieval_run_id: 'retrieval-1', sufficiency: 'SUFFICIENT', evidence: [] }, triage_result: { problem_summary: 'Bearing wear' }, maintenance_plan: { objective: 'Inspect bearing', steps: [{ action: 'Lock out and inspect bearing', action_type: 'LOCKOUT_TAGOUT', evidence_ids: ['ev-1'] }] }, safety_review: { hazards: ['ROTATING_EQUIPMENT'], violations: [] }, policy_decision: { decision: 'REQUIRES_APPROVAL', policy_version: 'safety-policy-v1', reasons: ['HIGH_SEVERITY'] }, approval: null, work_order_id: null, current_stage: 'WAITING_APPROVAL', status: 'WAITING_APPROVAL', errors: [] },
}

function renderApproval() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(withAuth(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/approvals/approval-1']}><Routes><Route path="/approvals/:approvalId" element={<ApprovalDetailPage />} /><Route path="/work-orders/:workOrderId" element={<div>work order destination</div>} /></Routes></MemoryRouter></QueryClientProvider>, OPERATOR_IDENTITY))
}

async function readyForm() {
  await screen.findByRole('heading', { name: 'Record operator decision' })
  fireEvent.change(screen.getByLabelText('Decision reason'), { target: { value: 'Evidence and hazards reviewed.' } })
}

afterEach(() => { vi.restoreAllMocks() })

describe('approval interaction', () => {
  it('approves once and disables double submit while pending', async () => {
    vi.spyOn(api, 'approval').mockResolvedValue(approval)
    vi.spyOn(api, 'workflow').mockResolvedValue(workflow)
    vi.spyOn(api, 'knowledgeDocuments').mockResolvedValue([])
    let resolveDecision!: (value: Workflow) => void
    const decide = vi.spyOn(api, 'decide').mockReturnValue(new Promise((resolve) => { resolveDecision = resolve }))
    renderApproval(); await readyForm()
    const button = screen.getByRole('button', { name: 'Approve plan' })
    fireEvent.click(button)
    const pendingButton = (await screen.findAllByRole('button', { name: 'SUBMITTING…' }))[0]
    expect(pendingButton).toBeDisabled()
    fireEvent.click(pendingButton)
    expect(decide).toHaveBeenCalledTimes(1)
    resolveDecision(workflow)
  })

  it('submits a real reject decision with the operator reason', async () => {
    vi.spyOn(api, 'approval').mockResolvedValue(approval)
    vi.spyOn(api, 'workflow').mockResolvedValue(workflow)
    vi.spyOn(api, 'knowledgeDocuments').mockResolvedValue([])
    const decide = vi.spyOn(api, 'decide').mockResolvedValue({ ...workflow, status: 'REJECTED' })
    renderApproval(); await readyForm()
    fireEvent.click(screen.getByRole('button', { name: 'Reject plan' }))
    await waitFor(() => expect(decide).toHaveBeenCalledWith('approval-1', 'reject', 'control-tower-operator', 'Evidence and hazards reviewed.'))
  })

  it('blocks empty reasons and explains stale approval conflicts', async () => {
    vi.spyOn(api, 'approval').mockResolvedValue(approval)
    vi.spyOn(api, 'workflow').mockResolvedValue(workflow)
    vi.spyOn(api, 'knowledgeDocuments').mockResolvedValue([])
    const decide = vi.spyOn(api, 'decide').mockRejectedValue(new ApiError('stale', 409, 'STALE_APPROVAL'))
    renderApproval(); await screen.findByRole('heading', { name: 'Record operator decision' })
    fireEvent.click(screen.getByRole('button', { name: 'Approve plan' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Decision reason must contain at least 3 characters.')
    await readyForm(); fireEvent.click(screen.getByRole('button', { name: 'Approve plan' }))
    expect(await screen.findByText('Approval is no longer valid for the current plan.')).toBeInTheDocument()
    expect(decide).toHaveBeenCalledTimes(1)
  })
})
