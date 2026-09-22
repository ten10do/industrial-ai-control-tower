/* eslint-disable react-refresh/only-export-components */
import { Component, type ErrorInfo, type ReactNode, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from './api'
import type {
  AgentRun,
  AgentStep,
  Diagnosis,
  KnowledgeDocument,
  KnowledgeEvidence,
  SensorEvidence,
  Telemetry,
  TokenUsage,
  Workflow,
} from './types'

export function formatTime(value?: string | null) {
  if (!value) return 'Not available'
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'medium',
  }).format(new Date(value))
}

export function formatPercent(value?: number | null) {
  return value == null ? 'Not available' : `${(value * 100).toFixed(1)}%`
}

export function formatLatency(value?: number | null) {
  if (value == null) return 'Not available'
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${value.toFixed(0)} ms`
}

export function formatTokens(usage?: TokenUsage | null) {
  if (!usage || usage.total_tokens == null) return 'Not reported'
  return usage.total_tokens.toLocaleString()
}

export function StatusBadge({ value }: { value?: string | null }) {
  const status = value || 'UNKNOWN'
  const normalized = status.toLowerCase().replace(/_/g, '-')
  return (
    <span className={`status status-${normalized}`} aria-label={`Status: ${status}`}>
      <span aria-hidden="true">{['NORMAL', 'ACTIVE', 'CONNECTED', 'HEALTHY', 'SUCCESS'].includes(status) ? '●' : '◆'}</span>
      {status.replace(/_/g, ' ')}
    </span>
  )
}

export function ApiErrorPanel({ error, title = 'Unable to load data' }: { error: unknown; title?: string }) {
  const apiError = error instanceof ApiError ? error : undefined
  const capability = apiError?.status === 503
  const alreadyDecided = apiError?.status === 409 && apiError.code === 'APPROVAL_ALREADY_DECIDED'
  const stale = apiError?.status === 409 && apiError.code === 'STALE_APPROVAL'
  return (
    <div className="notice notice-error" role="alert">
      <strong>{capability ? 'Capability unavailable' : title}</strong>
      <span>
        {alreadyDecided
          ? 'This approval has already been decided.'
          : stale
            ? 'Approval is no longer valid for the current plan.'
            : apiError?.message || 'An unexpected interface error occurred.'}
      </span>
      {apiError?.traceId && <code>Trace {apiError.traceId}</code>}
    </div>
  )
}

export function AsyncPanel({
  loading,
  error,
  empty,
  emptyText,
  children,
}: {
  loading: boolean
  error: unknown
  empty?: boolean
  emptyText?: string
  children: ReactNode
}) {
  if (loading) return <div className="panel-state" aria-live="polite">Loading operational data…</div>
  if (error) return <ApiErrorPanel error={error} />
  if (empty) return <div className="panel-state">{emptyText || 'No records available.'}</div>
  return <>{children}</>
}

export function MetricCard({ label, value, detail }: { label: string; value: ReactNode; detail?: string }) {
  return (
    <article className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </article>
  )
}

type MetricKey = keyof Pick<
  Telemetry,
  | 'temperature_c'
  | 'bearing_temperature_c'
  | 'vibration_mm_s'
  | 'current_a'
  | 'rpm'
  | 'load_pct'
>

export function TelemetryChart({
  points,
  metric,
  label,
  unit,
}: {
  points: Telemetry[]
  metric: MetricKey
  label: string
  unit: string
}) {
  const values = points.map((point) => Number(point[metric])).filter(Number.isFinite)
  const min = values.length ? Math.min(...values) : 0
  const max = values.length ? Math.max(...values) : 1
  const spread = max - min || 1
  const coordinates = values
    .map((value, index) => `${(index / Math.max(values.length - 1, 1)) * 100},${92 - ((value - min) / spread) * 78}`)
    .join(' ')
  return (
    <article className="chart-card">
      <header><span>{label}</span><strong>{values.length ? values[values.length - 1].toFixed(metric === 'rpm' ? 0 : 1) : '—'} {unit}</strong></header>
      {values.length ? (
        <svg viewBox="0 0 100 100" role="img" aria-label={`${label} trend with ${values.length} samples`} preserveAspectRatio="none">
          <line x1="0" y1="92" x2="100" y2="92" className="chart-axis" />
          <polyline points={coordinates} className="chart-line" vectorEffect="non-scaling-stroke" />
        </svg>
      ) : <div className="panel-state">No telemetry in selected range.</div>}
      <footer><span>{min.toFixed(1)} {unit}</span><span>{values.length} points</span><span>{max.toFixed(1)} {unit}</span></footer>
    </article>
  )
}

export function DiagnosisPanel({ diagnosis }: { diagnosis: Diagnosis | Workflow['state']['diagnosis'] }) {
  const full = diagnosis as Diagnosis
  return (
    <section className="panel" aria-labelledby="diagnosis-title">
      <div className="panel-heading"><div><p className="eyebrow">ML diagnosis</p><h2 id="diagnosis-title">Diagnostic classification</h2></div><StatusBadge value={diagnosis.status} /></div>
      <div className="detail-grid">
        <KeyValue label="Fault type" value={diagnosis.fault_type || 'Unclassified'} />
        <KeyValue label="Confidence" value={formatPercent(diagnosis.confidence)} />
        <KeyValue label="Anomaly score" value={full.anomaly_score == null ? 'Not available' : full.anomaly_score.toFixed(3)} />
        <KeyValue label="Severity" value={<StatusBadge value={diagnosis.severity} />} />
        <KeyValue label="Model" value={diagnosis.model_version || 'Not available'} />
        <KeyValue label="Feature version" value={full.feature_version || 'Not available'} />
        <KeyValue label="Window start" value={formatTime(full.window_start)} />
        <KeyValue label="Window end" value={formatTime(full.window_end)} />
      </div>
    </section>
  )
}

export function SensorEvidencePanel({ evidence }: { evidence: SensorEvidence[] }) {
  return (
    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">Sensor evidence</p><h2>Measured deviations</h2></div><span>{evidence.length} signals</span></div>
      {evidence.length ? <div className="evidence-grid">{evidence.map((item) => (
        <article className="evidence-card" key={item.signal}>
          <strong>{item.signal.replace(/_/g, ' ')}</strong>
          <dl><dt>Observation</dt><dd>{item.observation.toFixed(2)}</dd><dt>Baseline</dt><dd>{item.normal_baseline.toFixed(2)}</dd><dt>Deviation</dt><dd>{item.deviation.toFixed(2)}</dd><dt>Trend</dt><dd>{item.trend}</dd></dl>
        </article>
      ))}</div> : <div className="panel-state">No sensor evidence recorded.</div>}
    </section>
  )
}

export function EvidencePanel({ evidence, documents }: { evidence: KnowledgeEvidence[]; documents: KnowledgeDocument[] }) {
  const [selected, setSelected] = useState<KnowledgeEvidence | null>(null)
  const documentFor = (item: KnowledgeEvidence) => documents.find((doc) => doc.document_id === item.document_id)
  return (
    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">Knowledge evidence</p><h2>Cited industrial guidance</h2></div><span>{evidence.length} citations</span></div>
      {evidence.length ? <div className="citation-list">{evidence.map((item) => {
        const doc = documentFor(item)
        return <button className="citation" key={item.evidence_id} onClick={() => setSelected(item)}>
          <span className="citation-mark">DOC</span>
          <span><strong>{doc?.title || item.document_id}</strong><small>Page {item.page ?? 'N/A'} · {item.section || 'Section not specified'}</small><span>{item.text}</span></span>
        </button>
      })}</div> : <div className="panel-state">No cited knowledge evidence.</div>}
      {selected && <div className="dialog-backdrop" role="presentation" onMouseDown={() => setSelected(null)}>
        <article className="evidence-dialog" role="dialog" aria-modal="true" aria-labelledby="evidence-dialog-title" onMouseDown={(event) => event.stopPropagation()}>
          {(() => { const doc = documentFor(selected); return <>
            <header><div><p className="eyebrow">Evidence viewer</p><h2 id="evidence-dialog-title">{doc?.title || selected.document_id}</h2></div><button aria-label="Close evidence viewer" onClick={() => setSelected(null)}>Close</button></header>
            <div className="detail-grid"><KeyValue label="Vendor" value={doc?.vendor || 'Not available'} /><KeyValue label="Document type" value={doc?.document_type || 'Not available'} /><KeyValue label="Revision" value={doc?.revision || 'Not available'} /><KeyValue label="Page" value={selected.page ?? 'Not available'} /><KeyValue label="Section" value={selected.section || 'Not available'} /><KeyValue label="Source" value={doc?.source_type || selected.source} /></div>
            <blockquote>{selected.text}</blockquote>
          </> })()}
        </article>
      </div>}
    </section>
  )
}

export function WorkflowPanel({ workflow, agentRuns = [] }: { workflow: Workflow; agentRuns?: AgentRun[] }) {
  const stages = ['Diagnosis', 'Knowledge', 'Triage', 'Planning', 'Safety Review', 'Policy Gate', 'Waiting Approval', 'WorkOrder']
  const state = workflow.state
  const completed = [true, true, !!state.triage_result, !!state.maintenance_plan, !!state.safety_review, !!state.policy_decision, !!state.approval, !!state.work_order_id]
  return (
    <>
      <section className="panel">
        <div className="panel-heading"><div><p className="eyebrow">Agent workflow</p><h2>Decision pipeline</h2></div><StatusBadge value={workflow.status} /></div>
        <ol className="workflow-track">{stages.map((stage, index) => <li className={completed[index] ? 'is-complete' : index === completed.findIndex((value) => !value) ? 'is-current' : ''} key={stage}><span>{completed[index] ? '✓' : '○'}</span><strong>{stage}</strong></li>)}</ol>
        <div className="detail-grid"><KeyValue label="Provider" value={workflow.provider} /><KeyValue label="Model" value={workflow.model} /><KeyValue label="Policy" value={workflow.policy_version} /><KeyValue label="Updated" value={formatTime(workflow.updated_at)} /></div>
      </section>
      <section className="panel safety-grid">
        <div><p className="eyebrow">LLM safety review</p><h2>Identified hazards</h2>{state.safety_review?.hazards.length ? <TagList values={state.safety_review.hazards} /> : <p className="muted">No hazards returned by the model.</p>}{state.safety_review?.violations.length ? <TagList values={state.safety_review.violations} /> : null}</div>
        <div className="policy-decision"><p className="eyebrow">Deterministic safety policy</p><h2><StatusBadge value={state.policy_decision?.decision} /></h2><strong>{state.policy_decision?.policy_version || workflow.policy_version}</strong><TagList values={state.policy_decision?.reasons || []} /></div>
      </section>
      <section className="panel">
        <div className="panel-heading"><div><p className="eyebrow">Structured agent trace</p><h2>Auditable model outputs</h2></div><span>No chain-of-thought exposed</span></div>
        {agentRuns.length ? <div className="trace-list">{agentRuns.map((run) => <details key={run.agent_run_id}><summary><strong>{run.agent}</strong><StatusBadge value={run.status} /><span>{run.latency_ms?.toFixed(0) || '—'} ms</span></summary><div className="detail-grid"><KeyValue label="Provider / model" value={`${run.provider || '—'} / ${run.model || '—'}`} /><KeyValue label="Prompt version" value={run.prompt_version || '—'} /><KeyValue label="Timestamp" value={formatTime(run.timestamp)} /><KeyValue label="Tokens" value={`${run.input_tokens ?? '—'} in / ${run.output_tokens ?? '—'} out`} /></div><pre>{JSON.stringify(run.structured_output, null, 2)}</pre>{run.tool_calls.length > 0 && <pre>{JSON.stringify(run.tool_calls, null, 2)}</pre>}</details>)}</div> : <div className="panel-state">No Agent runs recorded.</div>}
      </section>
    </>
  )
}

export function AgentStepTrack({ steps }: { steps: AgentStep[] }) {
  if (!steps.length) {
    return <div className="panel-state">No agent steps were recorded for this run.</div>
  }
  return (
    <ol className="agent-step-track" aria-label="Agent step chain">
      {steps.map((step, index) => (
        <li key={step.step_id} className={step.status === 'FAILED' ? 'is-failed' : 'is-success'}>
          <span className="step-index">Step {index + 1}</span>
          <strong>{step.agent_name.replace(/_/g, ' ')}</strong>
          <div className="step-status-row">
            <StatusBadge value={step.status} />
            <span>{formatLatency(step.latency_ms)}</span>
          </div>
          <dl>
            <dt>Tokens</dt>
            <dd>{step.metrics?.token_data_available ? `${step.metrics.total_tokens ?? '—'} total` : 'Not reported'}</dd>
            <dt>Provider</dt>
            <dd>{step.provider || 'Not available'}</dd>
            <dt>Model</dt>
            <dd>{step.model || 'Not available'}</dd>
            <dt>Started</dt>
            <dd>{formatTime(step.start_time)}</dd>
          </dl>
          {step.input_summary && <small>{step.input_summary}</small>}
          {step.output_summary && <small>{step.output_summary}</small>}
          {step.error && <div className="notice notice-error">{step.error}</div>}
        </li>
      ))}
    </ol>
  )
}

export function KeyValue({ label, value }: { label: string; value: ReactNode }) {
  return <div className="key-value"><span>{label}</span><strong>{value}</strong></div>
}

export function TagList({ values }: { values: string[] }) {
  return values.length ? <div className="tag-list">{values.map((value) => <span key={value}>{value.replace(/_/g, ' ')}</span>)}</div> : null
}

export function ResourceLink({ to, children }: { to: string; children: ReactNode }) {
  return <Link className="resource-link" to={to}>{children}<span aria-hidden="true">→</span></Link>
}

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(error: Error, info: ErrorInfo) { void error; void info }
  render() {
    return this.state.failed ? <main className="fatal-error"><h1>Control Tower panel unavailable</h1><p>A browser rendering error was isolated. Reload to retry.</p><button onClick={() => window.location.reload()}>Reload interface</button></main> : this.props.children
  }
}
