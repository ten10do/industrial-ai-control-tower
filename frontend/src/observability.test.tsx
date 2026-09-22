import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'
import { ObservabilityPage } from './pages'
import type {
  ObservabilityMetrics,
  ObservabilityRun,
  ObservabilityRunTrace,
} from './types'

const timestamp = '2026-09-22T04:00:00Z'

const metrics: ObservabilityMetrics = {
  total_runs: 12,
  runs_running: 1,
  runs_waiting_approval: 2,
  runs_today: 8,
  completed_runs: 9,
  success_count: 8,
  failure_count: 1,
  blocked_count: 0,
  cancelled_count: 0,
  success_rate: 8 / 9,
  avg_latency_ms: 2400,
  p95_latency_ms: 5100,
  avg_step_latency_ms: 620,
  step_status_counts: { SUCCESS: 24, FAILED: 1 },
  token_usage: {
    input_tokens: 200000,
    output_tokens: 150000,
    total_tokens: 350000,
    steps_with_token_data: 3,
    steps_total: 4,
  },
  by_agent: [
    {
      agent_name: 'planning',
      steps_total: 8,
      failures: 1,
      avg_latency_ms: 800,
      p95_latency_ms: 1200,
      total_tokens: 150000,
      schema_retries: 0,
    },
  ],
}

const run: ObservabilityRun = {
  run_id: 'abcdef12-3456-4789-9abc-def012345678',
  workflow_run_id: 'workflow-1',
  workflow_name: 'maintenance-decision-workflow-v1',
  device_id: 'MOTOR-001',
  trace_id: 'trace-1',
  provider: 'openai_compatible',
  model: 'deepseek-flash',
  status: 'SUCCESS',
  start_time: timestamp,
  end_time: timestamp,
  latency_ms: 2400,
  step_count: 3,
  total_tokens: 30,
  result: { outcome: 'SUCCESS' },
  error_message: null,
}

const trace: ObservabilityRunTrace = {
  run,
  steps: [
    {
      step_id: 'step-1',
      agent_name: 'triage',
      sequence: 0,
      status: 'SUCCESS',
      start_time: timestamp,
      end_time: timestamp,
      latency_ms: 300,
      input_summary: 'agent=triage diagnosis=diagnosis-1',
      output_summary: 'problem_summary=Review diagnosed BEARING_WEAR condition.',
      error: null,
      provider: 'test',
      model: 'deterministic-test-provider-v1',
      prompt_version: 'triage-prompt-v1',
      metrics: {
        step_id: 'step-1',
        agent_name: 'triage',
        input_tokens: 10,
        output_tokens: null,
        total_tokens: 10,
        latency_ms: 300,
        request_count: 1,
        schema_retries: 0,
        token_data_available: true,
      },
    },
    {
      step_id: 'step-2',
      agent_name: 'planning',
      sequence: 1,
      status: 'SUCCESS',
      start_time: timestamp,
      end_time: timestamp,
      latency_ms: 800,
      input_summary: 'agent=planning diagnosis=diagnosis-1',
      output_summary: 'objective=Confirm and address BEARING_WEAR steps=1',
      error: null,
      provider: 'test',
      model: 'deterministic-test-provider-v1',
      prompt_version: 'planning-prompt-v1',
      metrics: {
        step_id: 'step-2',
        agent_name: 'planning',
        input_tokens: 20,
        output_tokens: null,
        total_tokens: 20,
        latency_ms: 800,
        request_count: 1,
        schema_retries: 0,
        token_data_available: true,
      },
    },
    {
      step_id: 'step-3',
      agent_name: 'safety_review',
      sequence: 2,
      status: 'SUCCESS',
      start_time: timestamp,
      end_time: timestamp,
      latency_ms: 250,
      input_summary: 'agent=safety_review diagnosis=diagnosis-1',
      output_summary: 'hazards=1 violations=0',
      error: null,
      provider: 'test',
      model: 'deterministic-test-provider-v1',
      prompt_version: 'safety-review-prompt-v1',
      metrics: null,
    },
  ],
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ObservabilityPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('agent observability dashboard', () => {
  it('reports run, success-rate, latency, and token overview metrics', async () => {
    vi.spyOn(api, 'observabilityMetrics').mockResolvedValue(metrics)
    vi.spyOn(api, 'observabilityRuns').mockResolvedValue([run])
    renderPage()
    expect(await screen.findByText('88.9%')).toBeInTheDocument()
    expect(screen.getByText('8 of 9 completed runs')).toBeInTheDocument()
    expect(screen.getByText('p95 5.10 s')).toBeInTheDocument()
    expect(screen.getAllByText('2.40 s').length).toBeGreaterThan(0)
    expect(screen.getByText('350,000')).toBeInTheDocument()
    expect(screen.getByText('3 of 4 steps reported usage')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Per-agent aggregation' })).toBeInTheDocument()
    expect(screen.getByText('Schema retries')).toBeInTheDocument()
  })

  it('does not fabricate token totals when the provider reported nothing', async () => {
    vi.spyOn(api, 'observabilityMetrics').mockResolvedValue({
      ...metrics,
      token_usage: {
        input_tokens: null,
        output_tokens: null,
        total_tokens: null,
        steps_with_token_data: 0,
        steps_total: 3,
      },
      success_rate: null,
      completed_runs: 0,
    })
    vi.spyOn(api, 'observabilityRuns').mockResolvedValue([])
    renderPage()
    expect(await screen.findByText('Not reported')).toBeInTheDocument()
    expect(screen.getByText('0 of 3 steps reported usage')).toBeInTheDocument()
    expect(screen.getAllByText('Not available').length).toBeGreaterThan(0)
  })

  it('loads a run trace on selection and shows ordered steps with latency and tokens', async () => {
    vi.spyOn(api, 'observabilityMetrics').mockResolvedValue(metrics)
    vi.spyOn(api, 'observabilityRuns').mockResolvedValue([run])
    const detail = vi.spyOn(api, 'observabilityRun').mockResolvedValue(trace)
    renderPage()
    const selector = await screen.findByRole('button', { name: 'abcdef12' })
    fireEvent.click(selector)
    await waitFor(() => expect(detail).toHaveBeenCalledWith(run.run_id))
    expect(await screen.findByText('Step 1')).toBeInTheDocument()
    expect(screen.getByText('Step 3')).toBeInTheDocument()
    expect(screen.getByText('300 ms')).toBeInTheDocument()
    expect(screen.getByText('250 ms')).toBeInTheDocument()
    expect(screen.getByText('10 total')).toBeInTheDocument()
    expect(screen.getByText('Not reported')).toBeInTheDocument()
    expect(screen.getByText('Open authoritative workflow')).toBeInTheDocument()
  })

  it('explains an unavailable observability capability instead of failing silently', async () => {
    vi.spyOn(api, 'observabilityMetrics').mockRejectedValue(
      new ApiError('Capability unavailable.', 503, 'HTTP_503'),
    )
    vi.spyOn(api, 'observabilityRuns').mockResolvedValue([])
    renderPage()
    expect(await screen.findByText('Capability unavailable')).toBeInTheDocument()
  })
})
