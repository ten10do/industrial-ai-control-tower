import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FormEvent, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from './api'
import {
  ApiErrorPanel,
  AsyncPanel,
  DiagnosisPanel,
  EvidencePanel,
  formatTime,
  KeyValue,
  MetricCard,
  ResourceLink,
  SensorEvidencePanel,
  StatusBadge,
  TagList,
  TelemetryChart,
  WorkflowPanel,
} from './components'
import type { Approval, Device } from './types'
import { useTelemetryStream } from './useTelemetryStream'

const activeIncident = (status: string) => !['WORK_ORDER_CREATED', 'REJECTED', 'CANCELLED'].includes(status)

export function PageHeader({ eyebrow, title, detail }: { eyebrow: string; title: string; detail: string }) {
  return <header className="page-header"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1></div><p>{detail}</p></header>
}

export function OverviewPage() {
  const devices = useQuery({ queryKey: ['devices'], queryFn: api.devices })
  const alarms = useQuery({ queryKey: ['alarms'], queryFn: () => api.alarms() })
  const incidents = useQuery({ queryKey: ['incidents'], queryFn: () => api.incidents() })
  const approvals = useQuery({ queryKey: ['approvals'], queryFn: api.approvals, refetchInterval: 10_000 })
  const workOrders = useQuery({ queryKey: ['work-orders'], queryFn: api.workOrders })
  const workflows = useQuery({ queryKey: ['workflows'], queryFn: api.workflows })
  const telemetry = useQuery({ queryKey: ['telemetry-latest', 'MOTOR-001'], queryFn: () => api.latestTelemetry('MOTOR-001'), retry: false })
  const queries = [devices, alarms, incidents, approvals, workOrders, workflows]
  const error = queries.find((query) => query.error)?.error
  const loading = queries.some((query) => query.isPending)
  const live = telemetry.data
  return <>
    <PageHeader eyebrow="Overview" title="Operations at a glance" detail="Live equipment state, active decisions, and maintenance outcomes from the real platform APIs." />
    <AsyncPanel loading={loading} error={error}>
      <section className="metrics-grid">
        <MetricCard label="Total devices" value={devices.data?.length ?? 0} />
        <MetricCard label="Running devices" value={devices.data?.filter((item) => item.status === 'ACTIVE').length ?? 0} />
        <MetricCard label="Active alarms" value={alarms.data?.filter((item) => item.status === 'ACTIVE').length ?? 0} />
        <MetricCard label="Open incidents" value={incidents.data?.filter((item) => activeIncident(item.status)).length ?? 0} />
        <MetricCard label="Pending approvals" value={approvals.data?.length ?? 0} />
        <MetricCard label="Open work orders" value={workOrders.data?.filter((item) => item.status === 'DRAFT').length ?? 0} />
      </section>
      <div className="dashboard-grid">
        <section className="panel span-2"><div className="panel-heading"><div><p className="eyebrow">Device health</p><h2>Fleet state</h2></div><Link to="/devices">View fleet →</Link></div><div className="device-health-list">{devices.data?.map((device) => <ResourceLink key={device.device_id} to={`/devices/${device.device_id}`}><span><strong>{device.device_id}</strong><small>{device.name}</small></span><StatusBadge value={device.status} /></ResourceLink>)}</div></section>
        <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Live motor summary</p><h2>MOTOR-001</h2></div><StatusBadge value={live?.fault_state || (telemetry.isError ? 'UNAVAILABLE' : 'CONNECTING')} /></div>{live ? <div className="compact-metrics"><KeyValue label="Temperature" value={`${live.temperature_c.toFixed(1)} °C`} /><KeyValue label="Bearing" value={`${live.bearing_temperature_c.toFixed(1)} °C`} /><KeyValue label="Vibration" value={`${live.vibration_mm_s.toFixed(2)} mm/s`} /><KeyValue label="Current" value={`${live.current_a.toFixed(1)} A`} /><KeyValue label="RPM" value={`${live.rpm} rpm`} /><KeyValue label="Load / power" value={`${live.load_pct.toFixed(1)}% / ${live.power_kw.toFixed(1)} kW`} /></div> : <div className="panel-state">Live motor telemetry unavailable.</div>}</section>
        <RecentTable title="Recent incidents" rows={(incidents.data || []).slice(0, 5).map((item) => ({ id: item.incident_id, to: `/incidents/${item.incident_id}`, primary: item.title, secondary: `${item.device_id} · ${item.fault_type || 'Unclassified'}`, status: item.status }))} empty="No active incidents." />
        <RecentTable title="Pending approvals" rows={(approvals.data || []).slice(0, 5).map((item) => ({ id: item.approval_id, to: `/approvals/${item.approval_id}`, primary: `Plan version ${item.plan_version}`, secondary: formatTime(item.created_at), status: item.status }))} empty="No pending approvals." />
        <RecentTable title="Recent workflows" rows={(workflows.data || []).slice(0, 5).map((item) => ({ id: item.workflow_run_id, to: `/workflows/${item.workflow_run_id}`, primary: item.device_id, secondary: item.current_stage, status: item.status }))} empty="No workflows recorded." />
      </div>
    </AsyncPanel>
  </>
}

function RecentTable({ title, rows, empty }: { title: string; rows: Array<{ id: string; to: string; primary: string; secondary: string; status: string }>; empty: string }) {
  return <section className="panel"><div className="panel-heading"><h2>{title}</h2></div>{rows.length ? <div className="recent-list">{rows.map((row) => <ResourceLink key={row.id} to={row.to}><span><strong>{row.primary}</strong><small>{row.secondary}</small></span><StatusBadge value={row.status} /></ResourceLink>)}</div> : <div className="panel-state">{empty}</div>}</section>
}

function DeviceRow({ device }: { device: Device }) {
  const latest = useQuery({ queryKey: ['telemetry-latest', device.device_id], queryFn: () => api.latestTelemetry(device.device_id), retry: false })
  return <tr><td><Link to={`/devices/${device.device_id}`}><strong>{device.device_id}</strong></Link><small>{device.name}</small></td><td>{device.device_type}</td><td><StatusBadge value={device.status} /></td><td>{formatTime(latest.data?.timestamp)}</td><td><StatusBadge value={latest.data?.fault_state || (latest.isPending ? 'CHECKING' : 'NO DATA')} /></td></tr>
}

export function DevicesPage() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('ALL')
  const query = useQuery({ queryKey: ['devices'], queryFn: api.devices })
  const filtered = (query.data || []).filter((device) => (status === 'ALL' || device.status === status) && `${device.device_id} ${device.name}`.toLowerCase().includes(search.toLowerCase()))
  return <><PageHeader eyebrow="Equipment" title="Device fleet" detail="Registered equipment with live ingestion state and current reported fault condition." /><div className="filters"><label>Search<input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Device ID or name" /></label><label>Status<select value={status} onChange={(event) => setStatus(event.target.value)}><option>ALL</option><option>ACTIVE</option><option>INACTIVE</option><option>DECOMMISSIONED</option></select></label></div><AsyncPanel loading={query.isPending} error={query.error} empty={!filtered.length} emptyText="No devices match the selected filters."><div className="table-wrap"><table><thead><tr><th>Device</th><th>Type</th><th>Registry status</th><th>Latest telemetry</th><th>Fault state</th></tr></thead><tbody>{filtered.map((device) => <DeviceRow key={device.device_id} device={device} />)}</tbody></table></div></AsyncPanel></>
}

export function DeviceDetailPage() {
  const { deviceId = '' } = useParams()
  const [range, setRange] = useState(15)
  const start = useMemo(() => new Date(Date.now() - range * 60_000).toISOString(), [range])
  const device = useQuery({ queryKey: ['device', deviceId], queryFn: () => api.device(deviceId) })
  const history = useQuery({ queryKey: ['telemetry', deviceId, range], queryFn: () => api.telemetry(deviceId, start) })
  const diagnosis = useQuery({ queryKey: ['diagnosis-latest', deviceId], queryFn: () => api.latestDiagnosis(deviceId), retry: false })
  const alarms = useQuery({ queryKey: ['alarms', deviceId], queryFn: () => api.alarms(deviceId) })
  const activeAlarms = (alarms.data || []).filter((item) => item.status === 'ACTIVE')
  const visibleAlarms = activeAlarms.slice(0, 10)
  const { points, latest, connection } = useTelemetryStream(deviceId, history.data?.items || [])
  const error = device.error || history.error
  return <><PageHeader eyebrow="Device detail" title={device.data?.device_id || deviceId} detail={device.data?.name || 'Real-time and historical equipment telemetry.'} /><AsyncPanel loading={device.isPending || history.isPending} error={error}>
    <section className="device-header panel"><div><StatusBadge value={latest?.operating_state || device.data?.status} /><StatusBadge value={latest?.fault_state || 'NO DATA'} /></div><div className="detail-grid"><KeyValue label="Current fault" value={latest?.fault_state || 'Not available'} /><KeyValue label="Last telemetry" value={formatTime(latest?.timestamp)} /><KeyValue label="Live connection" value={<StatusBadge value={connection} />} /></div>{connection !== 'CONNECTED' && <div className="notice notice-warning">Live connection lost or reconnecting. Historical REST data remains visible.</div>}</section>
    {latest && <section className="metrics-grid"><MetricCard label="Temperature" value={`${latest.temperature_c.toFixed(1)} °C`} /><MetricCard label="Bearing temperature" value={`${latest.bearing_temperature_c.toFixed(1)} °C`} /><MetricCard label="Vibration" value={`${latest.vibration_mm_s.toFixed(2)} mm/s`} /><MetricCard label="Current / voltage" value={`${latest.current_a.toFixed(1)} A`} detail={`${latest.voltage_v.toFixed(0)} V`} /><MetricCard label="RPM" value={`${latest.rpm} rpm`} /><MetricCard label="Load / power" value={`${latest.load_pct.toFixed(1)}%`} detail={`${latest.power_kw.toFixed(1)} kW`} /></section>}
    <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Historical + live telemetry</p><h2>Bounded trends</h2></div><label>Range<select value={range} onChange={(event) => setRange(Number(event.target.value))}><option value={5}>Last 5 min</option><option value={15}>Last 15 min</option><option value={60}>Last 1 hour</option></select></label></div><div className="charts-grid"><TelemetryChart points={points} metric="temperature_c" label="Temperature" unit="°C" /><TelemetryChart points={points} metric="bearing_temperature_c" label="Bearing temperature" unit="°C" /><TelemetryChart points={points} metric="vibration_mm_s" label="Vibration" unit="mm/s" /><TelemetryChart points={points} metric="current_a" label="Current" unit="A" /><TelemetryChart points={points} metric="rpm" label="Speed" unit="rpm" /><TelemetryChart points={points} metric="load_pct" label="Load" unit="%" /></div><p className="footnote">REST supplies the selected history; one device-level WebSocket appends live samples. The browser retains at most 300 points.</p></section>
    <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Alarm events</p><h2>Active alarms</h2></div><span>Alarm ≠ Diagnosis · {activeAlarms.length} active{activeAlarms.length > visibleAlarms.length ? ', latest 10 shown' : ''}</span></div>{visibleAlarms.length ? <div className="alarm-list">{visibleAlarms.map((alarm) => <article key={alarm.id}><StatusBadge value={alarm.severity} /><div><strong>{alarm.rule_id}</strong><span>{alarm.message}</span></div><KeyValue label="Started" value={formatTime(alarm.started_at)} /><StatusBadge value={alarm.status} /></article>)}</div> : <div className="panel-state">No active alarms.</div>}</section>
    {diagnosis.data ? <DiagnosisPanel diagnosis={diagnosis.data} /> : diagnosis.error instanceof ApiError && diagnosis.error.status !== 404 ? <ApiErrorPanel error={diagnosis.error} /> : <section className="panel"><div className="panel-state">No diagnosis is available for this device.</div></section>}
  </AsyncPanel></>
}

export function IncidentsPage() {
  const [status, setStatus] = useState('ALL')
  const query = useQuery({ queryKey: ['incidents', status], queryFn: () => api.incidents(status === 'ALL' ? undefined : status) })
  return <><PageHeader eyebrow="Decision lifecycle" title="Incidents" detail="Abnormal diagnoses linked to evidence, workflows, approvals, and maintenance plans." /><div className="filters"><label>Status<select value={status} onChange={(event) => setStatus(event.target.value)}><option>ALL</option><option>OPEN</option><option>UNDER_ANALYSIS</option><option>ACTION_PENDING</option><option>WORK_ORDER_CREATED</option></select></label></div><AsyncPanel loading={query.isPending} error={query.error} empty={!query.data?.length} emptyText="No incidents in this lifecycle state."><div className="table-wrap"><table><thead><tr><th>Incident</th><th>Device</th><th>Status</th><th>Created</th><th>Diagnosis / severity</th><th>Workflow</th></tr></thead><tbody>{query.data?.map((item) => <tr key={item.incident_id}><td><Link to={`/incidents/${item.incident_id}`}><strong>{item.title}</strong></Link><small>{item.incident_id}</small></td><td>{item.device_id}</td><td><StatusBadge value={item.status} /></td><td>{formatTime(item.created_at)}</td><td>{item.fault_type || 'Unclassified'} <StatusBadge value={item.severity} /></td><td><StatusBadge value={item.workflow_status || 'NOT STARTED'} /></td></tr>)}</tbody></table></div></AsyncPanel></>
}

export function IncidentDetailPage() {
  const { incidentId = '' } = useParams()
  const incident = useQuery({ queryKey: ['incident', incidentId], queryFn: () => api.incident(incidentId) })
  const workflowId = incident.data?.workflow_run_id
  const workflow = useQuery({ queryKey: ['workflow', workflowId], queryFn: () => api.workflow(workflowId!), enabled: !!workflowId, refetchInterval: (query) => query.state.data?.status === 'WAITING_APPROVAL' ? 10_000 : false })
  const trace = useQuery({ queryKey: ['workflow-trace', workflowId], queryFn: () => api.workflowTrace(workflowId!), enabled: !!workflowId })
  const documents = useQuery({ queryKey: ['knowledge-documents'], queryFn: api.knowledgeDocuments, retry: false })
  const data = incident.data
  return <><PageHeader eyebrow="Incident detail" title={data?.title || 'Incident'} detail={incidentId} /><AsyncPanel loading={incident.isPending} error={incident.error}>{data && <>
    <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Incident header</p><h2>{data.device_id}</h2></div><StatusBadge value={data.status} /></div><div className="detail-grid"><KeyValue label="Priority" value={<StatusBadge value={data.priority} />} /><KeyValue label="Created" value={formatTime(data.created_at)} /><KeyValue label="Updated" value={formatTime(data.updated_at)} /><KeyValue label="Description" value={data.description || 'No operator description.'} /></div><ResourceLink to={`/devices/${data.device_id}`}>Open device context</ResourceLink></section>
    <DiagnosisPanel diagnosis={data.diagnosis} />
    <SensorEvidencePanel evidence={data.diagnosis.evidence} />
    {workflow.data ? <><EvidencePanel evidence={workflow.data.state.knowledge_context.evidence} documents={documents.data || []} /><WorkflowPanel workflow={workflow.data} agentRuns={trace.data?.agent_runs || []} />{workflow.data.state.approval && <ResourceLink to={`/approvals/${workflow.data.state.approval.approval_id}`}>Open approval decision</ResourceLink>}{workflow.data.state.work_order_id && <ResourceLink to={`/work-orders/${workflow.data.state.work_order_id}`}>Open work order</ResourceLink>}</> : workflowId ? <AsyncPanel loading={workflow.isPending} error={workflow.error}><span /></AsyncPanel> : <section className="panel"><div className="panel-state">No Agent workflow has been started for this incident.</div></section>}
  </>}</AsyncPanel></>
}

export function WorkflowDetailPage() {
  const { workflowRunId = '' } = useParams()
  const trace = useQuery({ queryKey: ['workflow-trace', workflowRunId], queryFn: () => api.workflowTrace(workflowRunId), refetchInterval: 10_000 })
  const documents = useQuery({ queryKey: ['knowledge-documents'], queryFn: api.knowledgeDocuments, retry: false })
  return <><PageHeader eyebrow="Workflow detail" title="Agent decision workflow" detail={workflowRunId} /><AsyncPanel loading={trace.isPending} error={trace.error}>{trace.data && <><WorkflowPanel workflow={trace.data.workflow} agentRuns={trace.data.agent_runs} /><EvidencePanel evidence={trace.data.workflow.state.knowledge_context.evidence} documents={documents.data || []} /><ResourceLink to={`/incidents/${trace.data.workflow.incident_id}`}>Open source incident</ResourceLink></>}</AsyncPanel></>
}

function ApprovalRow({ approval }: { approval: Approval }) {
  const workflow = useQuery({ queryKey: ['workflow', approval.workflow_run_id], queryFn: () => api.workflow(approval.workflow_run_id) })
  return <tr><td><Link to={`/approvals/${approval.approval_id}`}><strong>{workflow.data?.device_id || 'Loading device…'}</strong></Link><small>{approval.approval_id}</small></td><td>{workflow.data?.state.diagnosis.fault_type || '—'}</td><td><StatusBadge value={workflow.data?.state.diagnosis.severity || 'CHECKING'} /></td><td>{workflow.data?.state.policy_decision?.reasons.join(', ') || '—'}</td><td>{formatTime(approval.created_at)}</td><td>v{approval.plan_version}</td></tr>
}

export function ApprovalsPage() {
  const query = useQuery({ queryKey: ['approvals'], queryFn: api.approvals, refetchInterval: 10_000 })
  return <><PageHeader eyebrow="Human-in-the-loop" title="Approval center" detail="Plans held by deterministic safety-policy-v1 pending an accountable operator decision." /><AsyncPanel loading={query.isPending} error={query.error} empty={!query.data?.length} emptyText="No pending approvals."><div className="table-wrap"><table><thead><tr><th>Device / approval</th><th>Fault</th><th>Severity</th><th>Risk</th><th>Created</th><th>Plan</th></tr></thead><tbody>{query.data?.map((approval) => <ApprovalRow key={approval.approval_id} approval={approval} />)}</tbody></table></div></AsyncPanel></>
}

export function ApprovalDetailPage() {
  const { approvalId = '' } = useParams()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [actor, setActor] = useState('control-tower-operator')
  const [reason, setReason] = useState('')
  const [formError, setFormError] = useState('')
  const approval = useQuery({ queryKey: ['approval', approvalId], queryFn: () => api.approval(approvalId) })
  const workflow = useQuery({ queryKey: ['workflow', approval.data?.workflow_run_id], queryFn: () => api.workflow(approval.data!.workflow_run_id), enabled: !!approval.data })
  const documents = useQuery({ queryKey: ['knowledge-documents'], queryFn: api.knowledgeDocuments, retry: false })
  const mutation = useMutation({
    mutationFn: (decision: 'approve' | 'reject') => api.decide(approvalId, decision, actor.trim(), reason.trim()),
    onSuccess: async (result) => {
      await Promise.all([queryClient.invalidateQueries({ queryKey: ['approvals'] }), queryClient.invalidateQueries({ queryKey: ['approval', approvalId] }), queryClient.invalidateQueries({ queryKey: ['workflow', result.workflow_run_id] }), queryClient.invalidateQueries({ queryKey: ['work-orders'] })])
      if (result.state.work_order_id) navigate(`/work-orders/${result.state.work_order_id}`)
    },
    onError: async () => { await Promise.all([approval.refetch(), workflow.refetch()]) },
  })
  const submit = (event: FormEvent, decision: 'approve' | 'reject') => {
    event.preventDefault()
    if (actor.trim().length < 2) { setFormError('Operator identity is required.'); return }
    if (reason.trim().length < 3) { setFormError('Decision reason must contain at least 3 characters.'); return }
    setFormError('')
    mutation.mutate(decision)
  }
  const state = workflow.data?.state
  const stale = mutation.error instanceof ApiError && mutation.error.code === 'STALE_APPROVAL'
  const canDecide = approval.data?.status === 'PENDING' && workflow.data?.status === 'WAITING_APPROVAL' && !stale
  return <><PageHeader eyebrow="Approval detail" title="Operator decision" detail={approvalId} /><AsyncPanel loading={approval.isPending || workflow.isPending} error={approval.error || workflow.error}>{approval.data && workflow.data && <>
    <DiagnosisPanel diagnosis={workflow.data.state.diagnosis} />
    <SensorEvidencePanel evidence={workflow.data.state.sensor_evidence} />
    <EvidencePanel evidence={state?.knowledge_context.evidence || []} documents={documents.data || []} />
    <WorkflowPanel workflow={workflow.data} />
    <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Maintenance plan</p><h2>{state?.maintenance_plan?.objective || 'Plan unavailable'}</h2></div><span>Version {approval.data.plan_version}</span></div><ol className="plan-list">{state?.maintenance_plan?.steps.map((step, index) => <li key={`${step.action}-${index}`}><span>{index + 1}</span><div><strong>{step.action_type}</strong><p>{step.action}</p><small>Evidence: {step.evidence_ids.join(', ')}</small></div></li>)}</ol></section>
    <section className="panel approval-form"><div><p className="eyebrow">Human approval gate</p><h2>Record operator decision</h2><p>This action authorizes creation of a planned maintenance work order. It does not execute physical maintenance.</p>{!canDecide && !mutation.isPending && <div className="notice notice-warning">Decision recorded: {approval.data.status}. This approval is no longer actionable.</div>}</div>{mutation.error && <ApiErrorPanel error={mutation.error} title="Decision was not accepted" />}<form><label>Operator identity<input value={actor} onChange={(event) => setActor(event.target.value)} disabled={mutation.isPending || !canDecide} /></label><label>Decision reason<textarea value={reason} onChange={(event) => setReason(event.target.value)} disabled={mutation.isPending || !canDecide} aria-describedby="decision-error" /></label>{formError && <span className="field-error" id="decision-error" role="alert">{formError}</span>}<div className="button-row"><button className="button-primary" type="submit" disabled={mutation.isPending || !canDecide} onClick={(event) => submit(event, 'approve')}>{mutation.isPending ? 'SUBMITTING…' : 'Approve plan'}</button><button className="button-danger" type="submit" disabled={mutation.isPending || !canDecide} onClick={(event) => submit(event, 'reject')}>{mutation.isPending ? 'SUBMITTING…' : 'Reject plan'}</button></div></form></section>
  </>}</AsyncPanel></>
}

export function WorkOrdersPage() {
  const query = useQuery({ queryKey: ['work-orders'], queryFn: api.workOrders })
  return <><PageHeader eyebrow="Maintenance planning" title="Work orders" detail="Approved planned work. These records do not claim that physical maintenance has been performed." /><AsyncPanel loading={query.isPending} error={query.error} empty={!query.data?.length} emptyText="No work orders have been created."><div className="table-wrap"><table><thead><tr><th>Work order</th><th>Device</th><th>Priority</th><th>Status</th><th>Fault</th><th>Created</th><th>Approval</th></tr></thead><tbody>{query.data?.map((order) => <tr key={order.work_order_id}><td><Link to={`/work-orders/${order.work_order_id}`}><strong>{order.title}</strong></Link><small>{order.work_order_id}</small></td><td>{order.device_id}</td><td><StatusBadge value={order.priority} /></td><td><StatusBadge value={order.status} /></td><td>{order.fault_type || '—'}</td><td>{formatTime(order.created_at)}</td><td>{order.approval_actor || 'Policy auto-allow'}</td></tr>)}</tbody></table></div></AsyncPanel></>
}

export function WorkOrderDetailPage() {
  const { workOrderId = '' } = useParams()
  const order = useQuery({ queryKey: ['work-order', workOrderId], queryFn: () => api.workOrder(workOrderId) })
  const data = order.data
  return <><PageHeader eyebrow="Work order detail" title={data?.title || 'Planned maintenance'} detail={workOrderId} /><AsyncPanel loading={order.isPending} error={order.error}>{data && <>
    <div className="notice notice-warning"><strong>Planning record only</strong><span>Work Order represents planned maintenance work and does not indicate that physical maintenance has been executed.</span></div>
    <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Work order</p><h2>{data.device_id}</h2></div><StatusBadge value={data.status} /></div><div className="detail-grid"><KeyValue label="Incident" value={data.incident_id} /><KeyValue label="Diagnosis" value={data.diagnosis_id} /><KeyValue label="Fault" value={data.fault_type || 'Not available'} /><KeyValue label="Priority" value={<StatusBadge value={data.priority} />} /><KeyValue label="Created" value={formatTime(data.created_at)} /><KeyValue label="Approval actor" value={data.approval_actor || 'Policy auto-allow'} /><KeyValue label="Approval time" value={formatTime(data.approval_decided_at)} /></div></section>
    <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Maintenance plan</p><h2>{data.plan.objective || 'Planned actions'}</h2></div></div><ol className="plan-list">{data.plan.steps?.map((step, index) => <li key={`${step.action}-${index}`}><span>{index + 1}</span><div><strong>{step.action_type}</strong><p>{step.action}</p><small>Evidence: {step.evidence_ids.join(', ')}</small></div></li>)}</ol></section>
    <section className="panel safety-grid"><div><p className="eyebrow">Evidence references</p><h2>Grounding</h2><TagList values={data.evidence_refs} /></div><div><p className="eyebrow">Safety requirements</p><h2>Execution constraints</h2><TagList values={data.safety_requirements} /></div></section>
    <div className="link-row"><ResourceLink to={`/incidents/${data.incident_id}`}>Open incident</ResourceLink><ResourceLink to={`/workflows/${data.workflow_run_id}`}>Open workflow</ResourceLink></div>
  </>}</AsyncPanel></>
}

export function NotFoundPage() {
  return <section className="fatal-error"><p className="eyebrow">404</p><h1>Resource not found</h1><p>The requested Control Tower route or resource does not exist.</p><Link to="/">Return to overview</Link></section>
}
