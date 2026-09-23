import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FormEvent, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from './api'
import {
  AgentStepTrack,
  ApiErrorPanel,
  AsyncPanel,
  DiagnosisPanel,
  EvidencePanel,
  formatLatency,
  formatPercent,
  formatTime,
  formatTokens,
  KeyValue,
  MetricCard,
  ResourceLink,
  SensorEvidencePanel,
  StatusBadge,
  TagList,
  TelemetryChart,
  ValidationIssueList,
  validationIssues,
  WorkflowPanel,
} from './components'
import type {
  Approval,
  AssetNode,
  AssetTreeNode,
  AssetType,
  ConnectivityDevice,
  Device,
  DeviceConfigurationState,
  ObservabilityRun,
  ValidationIssue,
} from './types'
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
  const [severity, setSeverity] = useState('ALL')
  const [device, setDevice] = useState('')
  const dashboard = useQuery({ queryKey: ['incident-dashboard'], queryFn: api.incidentDashboard, refetchInterval: 15_000 })
  const metrics = useQuery({ queryKey: ['incident-metrics'], queryFn: api.incidentMetrics, refetchInterval: 30_000 })
  const rows = dashboard.data?.incidents ?? []
  const filtered = rows.filter((item) =>
    (status === 'ALL' || item.status === status) &&
    (severity === 'ALL' || item.severity === severity) &&
    (!device || (item.device_id ?? '').toLowerCase().includes(device.toLowerCase())),
  )
  const summary = dashboard.data?.summary
  const waitingApproval = rows.filter((item) => item.workflow_status === 'WAITING_APPROVAL').length
  const today = new Date().toISOString().slice(0, 10)
  const resolvedToday = rows.filter((item) => (item.resolved_at ?? '').slice(0, 10) === today).length
  const m = metrics.data
  return <>
    <PageHeader eyebrow="Incident Operations Center" title="Incident Center" detail="Observation and decision support: correlated alarms, diagnoses, and the human decision path into the existing approval flow. This center never executes equipment control." />
    <AsyncPanel loading={dashboard.isPending} error={dashboard.error}>
      <section className="metrics-grid">
        <MetricCard label="Active Incident" value={summary?.active ?? 0} detail={`${summary?.unacknowledged ?? 0} unacknowledged`} />
        <MetricCard label="Critical" value={summary?.critical ?? 0} detail="Active incidents at CRITICAL severity" />
        <MetricCard label="Waiting Approval" value={waitingApproval} detail="Held by safety policy for a human decision" />
        <MetricCard label="Resolved Today" value={resolvedToday} detail="Incidents reaching RESOLVED today" />
      </section>
      <div className="filters">
        <label>Status<select value={status} onChange={(event) => setStatus(event.target.value)}><option>ALL</option><option>OPEN</option><option>ACKNOWLEDGED</option><option>INVESTIGATING</option><option>UNDER_ANALYSIS</option><option>ACTION_PENDING</option><option>WORK_ORDER_CREATED</option><option>MITIGATED</option><option>RESOLVED</option><option>CLOSED</option></select></label>
        <label>Severity<select value={severity} onChange={(event) => setSeverity(event.target.value)}><option>ALL</option><option>CRITICAL</option><option>MAJOR</option><option>WARNING</option><option>MINOR</option><option>INFO</option></select></label>
        <label>Device<input value={device} onChange={(event) => setDevice(event.target.value)} placeholder="Device ID contains…" /></label>
      </div>
      <AsyncPanel loading={false} error={metrics.error} >
        {m && <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Operational metrics</p><h2>Response performance</h2></div><span>Computed over incident lifecycle timestamps</span></div><div className="detail-grid"><KeyValue label="MTTA (mean time to acknowledge)" value={`${Math.round(m.mtta_seconds)} s`} /><KeyValue label="MTTR (mean time to resolve)" value={`${Math.round(m.mttr_seconds)} s`} /><KeyValue label="Alarm compression (alarms per incident)" value={m.alarm_compression.toFixed(1)} /></div></section>}
      </AsyncPanel>
      <AsyncPanel loading={false} error={undefined} empty={!filtered.length} emptyText="No incidents match the selected filters.">
        <div className="table-wrap"><table><thead><tr><th>Incident</th><th>Severity</th><th>Device</th><th>Asset</th><th>Status</th><th>Created</th><th>Last Alarm</th><th>Workflow</th></tr></thead><tbody>{filtered.map((item) => <tr key={item.incident_id}><td><Link to={`/incidents/${item.incident_id}`}><strong>{item.title}</strong></Link><small>{item.incident_id}</small></td><td><StatusBadge value={item.severity || 'UNKNOWN'} /></td><td>{item.device_id || '—'}</td><td>{item.asset_name || '—'}</td><td><StatusBadge value={item.status} /></td><td>{formatTime(item.created_at)}</td><td>{item.last_alarm_at ? formatTime(item.last_alarm_at) : '—'}</td><td><StatusBadge value={item.workflow_status || 'NOT STARTED'} /></td></tr>)}</tbody></table></div>
      </AsyncPanel>
    </AsyncPanel>
  </>
}

const canAcknowledge = (status: string) => status === 'OPEN'
const canInvestigate = (status: string) => status === 'ACKNOWLEDGED' || status === 'REOPENED'
const canStartWorkflow = (status: string) => ['OPEN', 'ACKNOWLEDGED', 'INVESTIGATING'].includes(status)
const canResolve = (status: string) => status === 'MITIGATED'

export function IncidentDetailPage() {
  const { incidentId = '' } = useParams()
  const queryClient = useQueryClient()
  const incident = useQuery({ queryKey: ['incident', incidentId], queryFn: () => api.incident(incidentId) })
  const bridge = useQuery({ queryKey: ['incident-bridge', incidentId], queryFn: () => api.incidentWorkflowContext(incidentId), refetchInterval: 10_000 })
  const workflowId = incident.data?.workflow_run_id
  const workflow = useQuery({ queryKey: ['workflow', workflowId], queryFn: () => api.workflow(workflowId!), enabled: !!workflowId, refetchInterval: (query) => query.state.data?.status === 'WAITING_APPROVAL' ? 10_000 : false })
  const trace = useQuery({ queryKey: ['workflow-trace', workflowId], queryFn: () => api.workflowTrace(workflowId!), enabled: !!workflowId })
  const documents = useQuery({ queryKey: ['knowledge-documents'], queryFn: api.knowledgeDocuments, retry: false })
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['incident', incidentId] }),
      queryClient.invalidateQueries({ queryKey: ['incident-bridge', incidentId] }),
      queryClient.invalidateQueries({ queryKey: ['incident-dashboard'] }),
    ])
  }
  const acknowledge = useMutation({ mutationFn: () => api.acknowledgeIncident(incidentId), onSuccess: refresh })
  const investigate = useMutation({ mutationFn: () => api.startInvestigation(incidentId), onSuccess: refresh })
  const resolve = useMutation({ mutationFn: () => api.resolveIncident(incidentId), onSuccess: refresh })
  const startWorkflow = useMutation({ mutationFn: () => api.startIncidentWorkflow(incidentId), onSuccess: refresh })
  const actionError = acknowledge.error || investigate.error || resolve.error || startWorkflow.error
  const busy = acknowledge.isPending || investigate.isPending || resolve.isPending || startWorkflow.isPending
  const data = incident.data
  const status = data?.status ?? ''
  const workflowStarted = !!workflowId || (bridge.data?.workflow_exists ?? false)
  return <><PageHeader eyebrow="Incident detail" title={data?.title || 'Incident'} detail={incidentId} /><AsyncPanel loading={incident.isPending} error={incident.error}>{data && <>
    <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Overview</p><h2>{data.device_id || 'Unassigned device'}</h2></div><StatusBadge value={data.status} /></div><div className="detail-grid"><KeyValue label="Status" value={<StatusBadge value={data.status} />} /><KeyValue label="Severity" value={<StatusBadge value={data.severity || 'UNKNOWN'} />} /><KeyValue label="Priority" value={<StatusBadge value={data.priority} />} /><KeyValue label="Device" value={data.device_id || '—'} /><KeyValue label="Asset" value={data.asset?.name || 'Unassigned'} /><KeyValue label="Created" value={formatTime(data.created_at)} /><KeyValue label="Updated" value={formatTime(data.updated_at)} /><KeyValue label="Description" value={data.description || 'No operator description.'} /></div><div className="button-row"><button className="button-primary" type="button" disabled={busy || !canAcknowledge(status)} onClick={() => acknowledge.mutate()}>Acknowledge</button><button className="button-primary" type="button" disabled={busy || !canInvestigate(status)} onClick={() => investigate.mutate()}>Start Investigation</button><button className="button-primary" type="button" disabled={busy || !canStartWorkflow(status) || workflowStarted} onClick={() => startWorkflow.mutate()}>Start Workflow</button><button className="button-primary" type="button" disabled={busy || !canResolve(status)} onClick={() => resolve.mutate()}>Resolve</button></div>{startWorkflow.error && <ApiErrorPanel error={startWorkflow.error} title="Workflow was not started" />}{actionError && !startWorkflow.error && <ApiErrorPanel error={actionError} title="Action was not accepted" />}{bridge.data?.approval_required && <div className="notice notice-warning" role="status"><strong>Waiting approval</strong><span>The decision workflow is holding for a human decision. The system recommends; the operator approves.</span></div>}<ResourceLink to={`/devices/${data.device_id}`}>Open device context</ResourceLink></section>
    <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Alarm timeline</p><h2>Correlated alarm instances</h2></div><span>{data.alarms?.length ?? 0} linked · newest first</span></div>{data.alarms?.length ? <ol className="alarm-list">{data.alarms.map((alarm, index) => <li key={alarm.id} className="alarm-timeline-row"><span className="alarm-timeline-index">{index + 1}</span><StatusBadge value={alarm.severity} /><div><strong>{alarm.rule_id}</strong><span>{alarm.message}</span></div><KeyValue label="Started" value={formatTime(alarm.started_at)} /><KeyValue label="Occurrences" value={alarm.occurrence_count ?? 1} /><StatusBadge value={alarm.status} /></li>)}</ol> : <div className="panel-state">No alarms are linked to this incident.</div>}</section>
    <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Diagnosis evidence</p><h2>Machine diagnosis</h2></div><StatusBadge value={data.diagnosis.status || 'UNKNOWN'} /></div><div className="detail-grid"><KeyValue label="Fault type" value={data.diagnosis.fault_type || 'Unclassified'} /><KeyValue label="Confidence" value={data.diagnosis.confidence == null ? 'Not reported' : formatPercent(data.diagnosis.confidence)} /><KeyValue label="Severity" value={<StatusBadge value={data.diagnosis.severity || 'UNKNOWN'} />} /><KeyValue label="Diagnosed at" value={formatTime(data.diagnosis.created_at)} /></div><p className="footnote">Read-only. Diagnosis records are produced by the ML pipeline and are never edited from the Incident Center.</p></section>
    {data.diagnosis?.evidence?.length ? <SensorEvidencePanel evidence={data.diagnosis.evidence} /> : null}
    {workflow.data ? <><EvidencePanel evidence={workflow.data.state.knowledge_context.evidence} documents={documents.data || []} /><WorkflowPanel workflow={workflow.data} agentRuns={trace.data?.agent_runs || []} />{workflow.data.state.approval && <ResourceLink to={`/approvals/${workflow.data.state.approval.approval_id}`}>Open approval decision</ResourceLink>}{workflow.data.state.work_order_id && <ResourceLink to={`/work-orders/${workflow.data.state.work_order_id}`}>Open work order</ResourceLink>}</> : workflowId ? <AsyncPanel loading={workflow.isPending} error={workflow.error}><span /></AsyncPanel> : <section className="panel"><div className="panel-state">No Agent workflow has been started for this incident. Starting one creates a workflow run and runs the existing decision graph; a work order is only ever created after a human approval.</div></section>}
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

function RunHistoryRow({ run, selected, onSelect }: { run: ObservabilityRun; selected: boolean; onSelect: (runId: string) => void }) {
  return <tr className={selected ? 'is-selected' : undefined}><td><button className="link-button" type="button" aria-pressed={selected} onClick={() => onSelect(run.run_id)}>{run.run_id.slice(0, 8)}</button><small>{run.run_id}</small></td><td>{run.workflow_name}<small>{run.device_id || 'Device not recorded'}</small></td><td><StatusBadge value={run.status} /></td><td>{formatLatency(run.latency_ms)}</td><td>{formatTime(run.start_time)}</td></tr>
}

export function ObservabilityPage() {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const metrics = useQuery({ queryKey: ['observability-metrics'], queryFn: api.observabilityMetrics, refetchInterval: 15_000 })
  const runs = useQuery({ queryKey: ['observability-runs'], queryFn: api.observabilityRuns, refetchInterval: 15_000 })
  const trace = useQuery({ queryKey: ['observability-run', selectedRunId], queryFn: () => api.observabilityRun(selectedRunId as string), enabled: !!selectedRunId })
  const summary = metrics.data
  const usage = summary?.token_usage
  return <>
    <PageHeader eyebrow="Agent observability" title="Agent workflow tracing" detail="Trace, metrics, and execution analysis for the existing multi-agent workflow. Read-only observation; the decision path is unchanged." />
    <AsyncPanel loading={metrics.isPending} error={metrics.error}>
      {summary && <section className="metrics-grid">
        <MetricCard label="Agent runs today" value={summary.runs_today} detail={`${summary.total_runs} recorded in total`} />
        <MetricCard label="Success rate" value={formatPercent(summary.success_rate)} detail={`${summary.success_count} of ${summary.completed_runs} completed runs`} />
        <MetricCard label="Average latency" value={formatLatency(summary.avg_latency_ms)} detail={`p95 ${formatLatency(summary.p95_latency_ms)}`} />
        <MetricCard label="Token usage" value={formatTokens(usage)} detail={usage ? `${usage.steps_with_token_data} of ${usage.steps_total} steps reported usage` : undefined} />
        <MetricCard label="Failed runs" value={summary.failure_count} detail={`${summary.blocked_count} blocked · ${summary.cancelled_count} cancelled`} />
        <MetricCard label="Awaiting approval" value={summary.runs_waiting_approval} detail={`${summary.runs_running} running`} />
      </section>}
      <AsyncPanel loading={runs.isPending} error={runs.error} empty={!runs.data?.length} emptyText="No Agent runs have been traced yet. Run a workflow from an incident to populate this view.">
        <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Run history</p><h2>Recent agent runs</h2></div><span>{runs.data?.length || 0} runs · select a run to inspect its trace</span></div><div className="table-wrap"><table className="run-history-table"><thead><tr><th>Run ID</th><th>Workflow</th><th>Status</th><th>Duration</th><th>Time</th></tr></thead><tbody>{runs.data?.map((run) => <RunHistoryRow key={run.run_id} run={run} selected={run.run_id === selectedRunId} onSelect={setSelectedRunId} />)}</tbody></table></div></section>
      </AsyncPanel>
      {selectedRunId && <AsyncPanel loading={trace.isPending} error={trace.error}>
        {trace.data && <>
          <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Trace detail</p><h2>Agent step chain</h2></div><StatusBadge value={trace.data.run.status} /></div>
            <div className="detail-grid"><KeyValue label="Run ID" value={trace.data.run.run_id} /><KeyValue label="Workflow" value={trace.data.run.workflow_name} /><KeyValue label="Workflow run" value={trace.data.run.workflow_run_id || 'Not linked'} /><KeyValue label="Device" value={trace.data.run.device_id || 'Not recorded'} /><KeyValue label="Provider / model" value={`${trace.data.run.provider || '—'} / ${trace.data.run.model || '—'}`} /><KeyValue label="Trace ID" value={trace.data.run.trace_id || 'Not available'} /><KeyValue label="Started" value={formatTime(trace.data.run.start_time)} /><KeyValue label="Ended" value={trace.data.run.end_time ? formatTime(trace.data.run.end_time) : 'Still open'} /><KeyValue label="Duration" value={formatLatency(trace.data.run.latency_ms)} /><KeyValue label="Steps" value={trace.data.run.step_count} /></div>
            {trace.data.run.error_message && <div className="notice notice-error"><strong>Run failed</strong><span>{trace.data.run.error_message}</span></div>}
            {trace.data.run.workflow_run_id && <ResourceLink to={`/workflows/${trace.data.run.workflow_run_id}`}>Open authoritative workflow</ResourceLink>}
          </section>
          <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Agent steps</p><h2>Per-step latency, status, and tokens</h2></div><span>Derived from the persisted agent audit trail</span></div><AgentStepTrack steps={trace.data.steps} /></section>
        </>}
      </AsyncPanel>}
      {summary && summary.by_agent.length > 0 && <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Execution analysis</p><h2>Per-agent aggregation</h2></div><span>Step status: {Object.entries(summary.step_status_counts).map(([key, value]) => `${key} ${value}`).join(' · ') || 'No steps recorded'}</span></div><div className="table-wrap"><table><thead><tr><th>Agent</th><th>Steps</th><th>Failures</th><th>Avg latency</th><th>p95 latency</th><th>Tokens</th><th>Schema retries</th></tr></thead><tbody>{summary.by_agent.map((item) => <tr key={item.agent_name}><td><strong>{item.agent_name.replace(/_/g, ' ')}</strong></td><td>{item.steps_total}</td><td>{item.failures}</td><td>{formatLatency(item.avg_latency_ms)}</td><td>{formatLatency(item.p95_latency_ms)}</td><td>{item.total_tokens == null ? 'Not reported' : item.total_tokens}</td><td>{item.schema_retries == null ? 'Not reported' : item.schema_retries}</td></tr>)}</tbody></table></div></section>}
    </AsyncPanel>
  </>
}

function ConnectivityRow({
  device,
  busy,
  onStart,
  onStop,
}: {
  device: ConnectivityDevice
  busy: boolean
  onStart: (deviceId: string) => void
  onStop: (deviceId: string) => void
}) {
  const controllable = device.enabled && device.polled
  const failures = device.read_errors + device.samples_rejected
  return <tr>
    <td><strong>{device.device_id}</strong><small>{device.endpoint || (device.polled ? 'No endpoint configured' : 'Push ingestion')}</small></td>
    <td>{device.protocol}</td>
    <td><StatusBadge value={device.state} /></td>
    <td>{device.polled ? `${device.poll_interval_ms} ms` : 'Not polled'}<small>{device.state_mode === 'derived' ? 'Derived state labels' : 'Static state labels'}</small></td>
    <td>{formatTime(device.last_success)}</td>
    <td>{device.samples_ingested} ingested<small>{failures} failed · {device.reconnect_attempts} reconnects</small></td>
    <td>{device.message || (device.polled ? 'No recent error' : 'Handled by the MQTT consumer')}</td>
    <td><div className="button-row"><button className="button-primary" type="button" disabled={busy || !controllable} onClick={() => onStart(device.device_id)}>Start</button><button className="button-danger" type="button" disabled={busy || !controllable} onClick={() => onStop(device.device_id)}>Stop</button></div></td>
  </tr>
}

export function ConnectivityPage() {
  const queryClient = useQueryClient()
  const summary = useQuery({ queryKey: ['connectivity-summary'], queryFn: api.connectivitySummary, refetchInterval: 10_000 })
  const devices = useQuery({ queryKey: ['connectivity-devices'], queryFn: api.connectivityDevices, refetchInterval: 10_000 })
  const invalidate = async () => {
    await Promise.all([queryClient.invalidateQueries({ queryKey: ['connectivity-summary'] }), queryClient.invalidateQueries({ queryKey: ['connectivity-devices'] })])
  }
  const start = useMutation({ mutationFn: api.startConnectivityDevice, onSuccess: invalidate })
  const stop = useMutation({ mutationFn: api.stopConnectivityDevice, onSuccess: invalidate })
  const busy = start.isPending || stop.isPending
  const data = summary.data
  const states = data?.states ?? {}
  return <>
    <PageHeader eyebrow="Industrial connectivity" title="Protocol gateway" detail="Adapter lifecycle and ingestion health for every configured industrial device. Start and stop change gateway polling only; nothing here commands plant equipment." />
    {data && !data.gateway_available && <div className="notice notice-warning" role="status"><strong>Gateway unavailable</strong><span>{data.gateway_error || 'The protocol gateway is disabled in this deployment. Set GATEWAY_ENABLED to load a device definition file.'}</span></div>}
    <AsyncPanel loading={summary.isPending} error={summary.error}>
      {data && <section className="metrics-grid">
        <MetricCard label="Configured devices" value={data.device_count} detail={`${data.enabled_device_count} enabled`} />
        <MetricCard label="Connected" value={states.CONNECTED ?? 0} detail={`${states.DEGRADED ?? 0} degraded · ${states.RECONNECTING ?? 0} reconnecting`} />
        <MetricCard label="Failed" value={states.ERROR ?? 0} detail={`${states.DISABLED ?? 0} disabled · ${states.STOPPED ?? 0} stopped`} />
        <MetricCard label="Samples ingested" value={data.total_samples_ingested} detail={`${data.total_samples_rejected} rejected by the contract`} />
        <MetricCard label="Configuration" value={data.config_file || 'Not loaded'} detail={data.loaded_at ? `Loaded ${formatTime(data.loaded_at)}` : 'Gateway disabled'} />
      </section>}
      <AsyncPanel loading={devices.isPending} error={devices.error} empty={!devices.data?.length} emptyText="No devices are configured for the protocol gateway.">
        <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Device connectivity</p><h2>Adapter lifecycle</h2></div><span>{devices.data?.length || 0} devices · read-only adapters</span></div><div className="table-wrap"><table><thead><tr><th>Device</th><th>Protocol</th><th>State</th><th>Polling</th><th>Last success</th><th>Samples</th><th>Last message</th><th>Polling control</th></tr></thead><tbody>{devices.data?.map((device) => <ConnectivityRow key={device.device_id} device={device} busy={busy} onStart={(id) => start.mutate(id)} onStop={(id) => stop.mutate(id)} />)}</tbody></table></div></section>
      </AsyncPanel>
      {start.error && <ApiErrorPanel error={start.error} title="Start was not accepted" />}
      {stop.error && <ApiErrorPanel error={stop.error} title="Stop was not accepted" />}
      <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Scope</p><h2>What this page does and does not do</h2></div></div><div className="detail-grid"><KeyValue label="Protocol reading" value="OPC UA, Modbus TCP, and simulator devices are polled by the gateway; MQTT keeps its existing push path." /><KeyValue label="Ingestion" value="Every polled sample is normalized and submitted to the same ingestion boundary the MQTT consumer uses." /><KeyValue label="Control" value="Start and stop toggle gateway polling. No write, setpoint, or actuator command exists in the adapter registry." /></div></section>
    </AsyncPanel>
  </>
}

export function NotFoundPage() {
  return <section className="fatal-error"><p className="eyebrow">404</p><h1>Resource not found</h1><p>The requested Control Tower route or resource does not exist.</p><Link to="/">Return to overview</Link></section>
}

function AssetDeviceRow({ device, selected, onSelect }: { device: DeviceConfigurationState; selected: boolean; onSelect: (deviceId: string) => void }) {
  const desired = device.published_version
  return <button className={`asset-device${selected ? ' is-selected' : ''}`} type="button" aria-pressed={selected} onClick={() => onSelect(device.device_id)}>
    <span><strong>{device.device_id}</strong><small>{device.name}</small></span>
    <span className="asset-device-state">
      <StatusBadge value={desired == null ? 'NOT CONFIGURED' : device.apply_status} />
      <small>{desired == null ? 'No published configuration' : `desired v${desired} · applied ${device.applied_version == null ? 'none' : `v${device.applied_version}`}`}</small>
    </span>
  </button>
}

function AssetNodeView({ node, depth, selectedDeviceId, onSelectDevice }: { node: AssetTreeNode; depth: number; selectedDeviceId: string | null; onSelectDevice: (deviceId: string) => void }) {
  return <div className="asset-node" data-depth={depth}>
    <div className="asset-node-head"><StatusBadge value={node.asset_type} /><strong>{node.name}</strong><small>{node.devices.length} device{node.devices.length === 1 ? '' : 's'}</small></div>
    {node.description && <p className="asset-node-note">{node.description}</p>}
    {node.devices.map((device) => <AssetDeviceRow key={device.device_id} device={device} selected={device.device_id === selectedDeviceId} onSelect={onSelectDevice} />)}
    {node.children.map((child) => <AssetNodeView key={child.id} node={child} depth={depth + 1} selectedDeviceId={selectedDeviceId} onSelectDevice={onSelectDevice} />)}
  </div>
}

function AssetCreateForm({ sites, onCreated }: { sites: AssetNode[]; onCreated: () => Promise<void> }) {
  const [name, setName] = useState('')
  const [assetType, setAssetType] = useState<AssetType>('SITE')
  const [parentId, setParentId] = useState('')
  const create = useMutation({
    mutationFn: () => api.createAsset({ name: name.trim(), asset_type: assetType, parent_id: assetType === 'LINE' ? parentId || null : null }),
    onSuccess: async () => { setName(''); setParentId(''); await onCreated() },
  })
  return <section className="panel asset-create">
    <div className="panel-heading"><div><p className="eyebrow">Asset hierarchy</p><h2>Add a location</h2></div></div>
    <form onSubmit={(event) => { event.preventDefault(); if (name.trim()) create.mutate() }}>
      <label>Name<input value={name} onChange={(event) => setName(event.target.value)} placeholder="Plant A or Line 1" /></label>
      <label>Type<select value={assetType} onChange={(event) => setAssetType(event.target.value as AssetType)}><option value="SITE">SITE</option><option value="LINE">LINE</option></select></label>
      {assetType === 'LINE' && <label>Parent site<select value={parentId} onChange={(event) => setParentId(event.target.value)}><option value="">Select a site</option>{sites.map((site) => <option key={site.id} value={site.id}>{site.name}</option>)}</select></label>}
      <button className="button-primary" type="submit" disabled={create.isPending || !name.trim()}>Add {assetType === 'SITE' ? 'site' : 'line'}</button>
    </form>
    {create.error && <ApiErrorPanel error={create.error} title="Location was not created" />}
  </section>
}

type DriftTextArgs = { desired: number | null; applied: number | null; applyStatus: string; error: string | null }

function driftText({ desired, applied, applyStatus, error }: DriftTextArgs) {
  if (desired == null) return 'No version is published for this device, so the runtime has nothing to converge on.'
  const running = applied == null ? 'no version' : `v${applied}`
  if (applyStatus === 'FAILED') return `v${desired} is published but the runtime is running ${running}. ${error || 'The runtime rejected the configuration.'}`
  if (applyStatus === 'APPLYING') return `v${desired} is being applied. The runtime still reports ${running} until the attempt settles.`
  if (applyStatus === 'PENDING') return `v${desired} is published and has not been applied in this process. ${error || ''}`.trim()
  return `v${desired} is published and the runtime reports ${running}.`
}

function DeviceConfigurationPanel({ deviceId, attachedNodeId, lines, onChanged }: { deviceId: string; attachedNodeId: string | null; lines: AssetNode[]; onChanged: () => Promise<void> }) {
  const queryClient = useQueryClient()
  const [actor, setActor] = useState('control-tower-operator')
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null)
  const [editor, setEditor] = useState<string | null>(null)
  const [payloadError, setPayloadError] = useState('')
  const [notice, setNotice] = useState('')
  const [attachTarget, setAttachTarget] = useState('')

  const configurations = useQuery({ queryKey: ['configurations', deviceId], queryFn: () => api.deviceConfigurations(deviceId), refetchInterval: 15_000 })
  const status = useQuery({ queryKey: ['configuration-status', deviceId], queryFn: () => api.configurationStatus(deviceId), refetchInterval: 15_000 })
  const audit = useQuery({ queryKey: ['configuration-audit', deviceId], queryFn: () => api.configurationAudit(deviceId), refetchInterval: 15_000 })

  const rows = configurations.data ?? []
  const draft = rows.find((row) => row.status === 'DRAFT' || row.status === 'VALIDATED')
  const published = rows.find((row) => row.status === 'PUBLISHED')
  const activeVersion = selectedVersion ?? draft?.version ?? published?.version ?? rows[0]?.version ?? null
  const detail = useQuery({ queryKey: ['configuration', deviceId, activeVersion], queryFn: () => api.deviceConfiguration(deviceId, activeVersion as number), enabled: activeVersion !== null })

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['configurations', deviceId] }),
      queryClient.invalidateQueries({ queryKey: ['configuration-status', deviceId] }),
      queryClient.invalidateQueries({ queryKey: ['configuration-audit', deviceId] }),
      queryClient.invalidateQueries({ queryKey: ['configuration', deviceId] }),
      onChanged(),
    ])
  }
  const editorText = editor ?? (detail.data ? JSON.stringify(detail.data.configuration, null, 2) : '')

  const parsePayload = (): Record<string, unknown> | null => {
    try {
      const parsed = JSON.parse(editorText) as unknown
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setPayloadError('The configuration payload must be a JSON object.')
        return null
      }
      setPayloadError('')
      return parsed as Record<string, unknown>
    } catch (error) {
      setPayloadError(`Invalid JSON: ${(error as Error).message}`)
      return null
    }
  }

  const createDraft = useMutation({
    mutationFn: (payload: Record<string, unknown>) => api.createDeviceConfiguration(deviceId, payload, actor),
    onSuccess: async (created) => { setSelectedVersion(created.version); setEditor(null); setNotice(`Draft v${created.version} created.`); await refresh() },
  })
  const saveDraft = useMutation({
    mutationFn: (args: { version: number; payload: Record<string, unknown> }) => api.updateDeviceConfiguration(deviceId, args.version, args.payload, actor),
    onSuccess: async (updated) => { setNotice(`Draft v${updated.version} saved.`); await refresh() },
  })
  const validateVersion = useMutation({
    mutationFn: (version: number) => api.validateDeviceConfiguration(deviceId, version),
    onSuccess: async (result) => { setNotice(result.valid ? `v${activeVersion} passed validation.` : `v${activeVersion} failed validation with ${result.errors.length} issue(s).`); await refresh() },
  })
  const publishVersion = useMutation({
    mutationFn: (version: number) => api.publishDeviceConfiguration(deviceId, version, actor),
    onSuccess: async (result) => { setNotice(result.status.in_sync ? `v${result.configuration.version} published and applied.` : `v${result.configuration.version} published, but the runtime is not running it.`); await refresh() },
  })
  const cloneVersion = useMutation({
    mutationFn: (version: number) => api.cloneDeviceConfiguration(deviceId, version, actor),
    onSuccess: async (created) => { setSelectedVersion(created.version); setEditor(null); setNotice(`Draft v${created.version} cloned from the selected snapshot.`); await refresh() },
  })
  const deleteVersion = useMutation({
    mutationFn: (version: number) => api.deleteDeviceConfiguration(deviceId, version),
    onSuccess: async () => { setSelectedVersion(null); setEditor(null); setNotice('Draft deleted.'); await refresh() },
  })
  const applyPublished = useMutation({
    mutationFn: () => api.applyConfiguration(deviceId, actor),
    onSuccess: async (result) => { setNotice(result.in_sync ? 'Runtime reconverged with the published version.' : 'Apply attempt finished without converging.'); await refresh() },
  })
  const attach = useMutation({
    mutationFn: (nodeId: string) => api.attachDevice(nodeId, deviceId),
    onSuccess: async () => { setNotice('Device attached to the asset.'); await refresh() },
  })
  const detach = useMutation({
    mutationFn: (nodeId: string) => api.detachDevice(nodeId, deviceId),
    onSuccess: async () => { setNotice('Device detached from the asset.'); await refresh() },
  })

  const busy = createDraft.isPending || saveDraft.isPending || validateVersion.isPending || publishVersion.isPending || cloneVersion.isPending || deleteVersion.isPending || applyPublished.isPending || attach.isPending || detach.isPending
  const canEdit = !!draft
  const state = status.data
  const inlineIssues = (detail.data?.validation_result as { errors?: ValidationIssue[] } | undefined)?.errors ?? []
  const savingError = createDraft.error || saveDraft.error
  const actionError = validateVersion.error || publishVersion.error || cloneVersion.error || deleteVersion.error || applyPublished.error || attach.error || detach.error
  const submitting = (event: FormEvent, action: 'create' | 'save' | 'validate' | 'publish' | 'clone' | 'delete' | 'apply') => {
    event.preventDefault()
    // Only the two actions that write the editor buffer consume it. Validating,
    // publishing, cloning, and deleting act on a stored version, so they must not be
    // blocked by the state of the editor.
    if (action === 'apply') { applyPublished.mutate(); return }
    if (action === 'validate') { if (activeVersion != null) validateVersion.mutate(activeVersion); return }
    if (action === 'delete') { if (draft) deleteVersion.mutate(draft.version); return }
    if (action === 'clone') { if (activeVersion != null) cloneVersion.mutate(activeVersion); return }
    if (action === 'publish') { if (draft) publishVersion.mutate(draft.version); return }
    const payload = parsePayload()
    if (!payload) return
    if (action === 'create') createDraft.mutate(payload)
    if (action === 'save' && draft) saveDraft.mutate({ version: draft.version, payload })
  }

  return <>
    <section className="panel">
      <div className="panel-heading">
        <div><p className="eyebrow">Device configuration</p><h2>{deviceId}</h2></div>
        <StatusBadge value={state ? (state.in_sync ? 'IN SYNC' : state.apply_status) : 'NOT CONFIGURED'} />
      </div>
      <div className="detail-grid">
        <KeyValue label="Desired version" value={state?.desired_version ?? 'None published'} />
        <KeyValue label="Applied version" value={state?.applied_version ?? 'Not applied'} />
        <KeyValue label="Apply status" value={<StatusBadge value={state?.apply_status} />} />
        <KeyValue label="Source of truth" value={state?.source ?? 'none'} />
        <KeyValue label="Protocol" value={state?.protocol ?? 'Not published'} />
        <KeyValue label="Runtime state" value={state?.runtime_state ?? 'Unknown in this process'} />
        <KeyValue label="Last apply attempt" value={formatTime(state?.last_apply_at)} />
        <KeyValue label="Asset" value={attachedNodeId ? lines.find((node) => node.id === attachedNodeId)?.name || attachedNodeId : 'Unassigned'} />
      </div>
      {state && !state.in_sync && <div className="notice notice-warning" role="status"><strong>Desired and applied differ</strong><span>{driftText({ desired: state.desired_version, applied: state.applied_version, applyStatus: state.apply_status, error: state.last_apply_error })}</span></div>}
      <div className="button-row">
        <button className="button-primary" type="button" disabled={busy || !state?.desired_version} onClick={(event) => submitting(event, 'apply')}>Retry apply</button>
      </div>
      <form className="asset-attach" onSubmit={(event) => { event.preventDefault(); if (attachTarget) attach.mutate(attachTarget) }}>
        <label>Attach to line<select value={attachTarget} onChange={(event) => setAttachTarget(event.target.value)}><option value="">Select a line</option>{lines.map((line) => <option key={line.id} value={line.id}>{line.name}</option>)}</select></label>
        <button className="button-primary" type="submit" disabled={busy || !attachTarget}>Attach</button>
        <button className="button-danger" type="button" disabled={busy || !attachedNodeId} onClick={() => attachedNodeId && detach.mutate(attachedNodeId)}>Detach</button>
      </form>
    </section>

    <section className="panel">
      <div className="panel-heading">
        <div><p className="eyebrow">Draft workflow</p><h2>{draft ? `Editing draft v${draft.version}` : activeVersion ? `Snapshot v${activeVersion} (read-only)` : 'No configuration yet'}</h2></div>
        <span>{detail.data ? `Protocol ${detail.data.protocol} · ${detail.data.status}` : 'Select a version'}</span>
      </div>
      <label>Operator identity<input value={actor} onChange={(event) => setActor(event.target.value)} disabled={busy} /></label>
      <label>Configuration payload (JSON)<textarea className="config-editor" value={editorText} onChange={(event) => setEditor(event.target.value)} spellCheck={false} aria-describedby="config-payload-error" disabled={busy} /></label>
      {payloadError && <span className="field-error" id="config-payload-error" role="alert">{payloadError}</span>}
      <div className="button-row">
        <button className="button-primary" type="button" disabled={busy || !editorText} onClick={(event) => submitting(event, 'create')}>New draft from editor</button>
        <button className="button-primary" type="button" disabled={busy || !canEdit} onClick={(event) => submitting(event, 'save')}>Save draft</button>
        <button className="button-primary" type="button" disabled={busy || activeVersion == null} onClick={(event) => submitting(event, 'validate')}>Validate</button>
        <button className="button-primary" type="button" disabled={busy || activeVersion == null} onClick={(event) => submitting(event, 'clone')}>Clone into new draft</button>
        <button className="button-primary" type="button" disabled={busy || !canEdit} onClick={(event) => submitting(event, 'publish')}>Publish</button>
        <button className="button-danger" type="button" disabled={busy || !canEdit} onClick={(event) => submitting(event, 'delete')}>Delete draft</button>
      </div>
      <p className="footnote">Published and archived versions are immutable. A change is always a new version, and rolling back means cloning an older snapshot into a new draft and publishing that. A new draft is created from the editor buffer, so when no version exists yet the payload has to be supplied here rather than generated.</p>
      {notice && <div className="notice" role="status"><strong>Result</strong><span>{notice}</span></div>}
      {savingError && <><ApiErrorPanel error={savingError} title="Configuration was not stored" /><ValidationIssueList issues={validationIssues(savingError)} /></>}
      {actionError && <><ApiErrorPanel error={actionError} title="Action was not accepted" /><ValidationIssueList issues={validationIssues(actionError)} /></>}
      {!actionError && inlineIssues.length > 0 && <ValidationIssueList issues={inlineIssues} />}
    </section>

    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">Version history</p><h2>Immutable snapshots</h2></div><span>{rows.length} version(s)</span></div>
      {rows.length ? <div className="table-wrap"><table><thead><tr><th>Version</th><th>Status</th><th>Protocol</th><th>Created by</th><th>Created</th><th>Published</th><th>Inspect</th></tr></thead><tbody>
        {rows.map((row) => <tr key={row.version} className={row.version === activeVersion ? 'is-selected' : undefined}>
          <td><strong>v{row.version}</strong></td>
          <td><StatusBadge value={row.status} /></td>
          <td>{row.protocol}</td>
          <td>{row.created_by}</td>
          <td>{formatTime(row.created_at)}</td>
          <td>{formatTime(row.published_at)}</td>
          <td><button className="link-button" type="button" aria-pressed={row.version === activeVersion} onClick={() => { setSelectedVersion(row.version); setEditor(null); setNotice('') }}>Open</button></td>
        </tr>)}
      </tbody></table></div> : <div className="panel-state">This device has no configuration versions.</div>}
    </section>

    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">Audit history</p><h2>Configuration lifecycle</h2></div><span>{audit.data?.length ?? 0} events</span></div>
      {audit.data?.length ? <div className="table-wrap"><table><thead><tr><th>Event</th><th>Version</th><th>Status</th><th>Actor</th><th>Time</th><th>Detail</th></tr></thead><tbody>
        {audit.data.map((event) => <tr key={event.event_id}>
          <td><strong>{event.event_type.replace('CONFIG_', '').replace(/_/g, ' ')}</strong></td>
          <td>{event.config_version == null ? '—' : `v${event.config_version}`}</td>
          <td><StatusBadge value={event.status} /></td>
          <td>{event.actor}</td>
          <td>{formatTime(event.timestamp)}</td>
          <td>{event.summary}</td>
        </tr>)}
      </tbody></table></div> : <div className="panel-state">No configuration events recorded.</div>}
    </section>
  </>
}

export function AssetsConfigPage() {
  const queryClient = useQueryClient()
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null)
  const tree = useQuery({ queryKey: ['asset-tree'], queryFn: api.assetTree, refetchInterval: 15_000 })
  const assets = useQuery({ queryKey: ['assets'], queryFn: api.assets })
  const treeData = tree.data
  const inventory = useMemo(() => {
    const collected: DeviceConfigurationState[] = []
    const walk = (node: AssetTreeNode) => { collected.push(...node.devices); node.children.forEach(walk) }
    treeData?.sites.forEach(walk)
    return [...collected, ...(treeData?.unassigned_devices ?? [])]
  }, [treeData])
  const sites = (assets.data ?? []).filter((node) => node.asset_type === 'SITE')
  const lines = (assets.data ?? []).filter((node) => node.asset_type === 'LINE')
  const activeDeviceId = selectedDeviceId ?? inventory[0]?.device_id ?? null
  const activeDevice = inventory.find((device) => device.device_id === activeDeviceId)
  const refreshTree = async () => {
    await Promise.all([queryClient.invalidateQueries({ queryKey: ['asset-tree'] }), queryClient.invalidateQueries({ queryKey: ['assets'] })])
  }
  const totalConfigured = inventory.filter((device) => device.published_version != null).length
  const totalDrifted = inventory.filter((device) => device.published_version != null && !device.in_sync).length
  return <>
    <PageHeader eyebrow="Assets and configuration" title="Asset and device configuration" detail="Versioned device configuration with an explicit desired-versus-applied split. Publishing records intent; the runtime reports what it is actually running." />
    <AsyncPanel loading={tree.isPending || assets.isPending} error={tree.error || assets.error}>
      <section className="metrics-grid">
        <MetricCard label="Asset nodes" value={(assets.data ?? []).length} detail={`${sites.length} sites · ${lines.length} lines`} />
        <MetricCard label="Devices in hierarchy" value={inventory.length} detail={`${treeData?.unassigned_devices.length ?? 0} unassigned`} />
        <MetricCard label="Configured devices" value={totalConfigured} detail={`${inventory.length - totalConfigured} without a published version`} />
        <MetricCard label="Runtime drift" value={totalDrifted} detail={totalDrifted ? 'Published version not running' : 'Every published version is applied'} />
      </section>
      <div className="dashboard-grid">
        <section className="panel">
          <div className="panel-heading"><div><p className="eyebrow">Asset hierarchy</p><h2>Sites, lines, and devices</h2></div><span>{inventory.length} devices</span></div>
          {treeData?.sites.length ? treeData.sites.map((site) => <AssetNodeView key={site.id} node={site} depth={0} selectedDeviceId={activeDeviceId} onSelectDevice={setSelectedDeviceId} />) : <div className="panel-state">No site has been created yet.</div>}
          <div className="asset-unassigned">
            <p className="eyebrow">Unassigned devices</p>
            {treeData?.unassigned_devices.length ? treeData.unassigned_devices.map((device) => <AssetDeviceRow key={device.device_id} device={device} selected={device.device_id === activeDeviceId} onSelect={setSelectedDeviceId} />) : <div className="panel-state">Every registered device is attached to a line.</div>}
          </div>
        </section>
        <AssetCreateForm sites={sites} onCreated={refreshTree} />
      </div>
      {activeDeviceId ? <DeviceConfigurationPanel key={activeDeviceId} deviceId={activeDeviceId} attachedNodeId={activeDevice?.asset_node_id ?? null} lines={lines} onChanged={refreshTree} /> : <section className="panel"><div className="panel-state">No device is registered yet, so there is nothing to configure. Devices are registered through the device registry, not from this page.</div></section>}
      <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Scope</p><h2>What this page does and does not do</h2></div></div><div className="detail-grid"><KeyValue label="Device identity" value="Device master records live in the existing device registry. This page attaches them to locations and versions their acquisition configuration; it never creates a second device identity." /><KeyValue label="Configuration" value="Only the acquisition definition the gateway already consumes is versioned. Publishing asks the runtime to apply it and reports the outcome truthfully, including failure." /><KeyValue label="Control" value="No PLC write, register write, or actuator command exists anywhere on this path." /></div></section>
    </AsyncPanel>
  </>
}
