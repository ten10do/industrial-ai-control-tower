export type Device = {
  id: string
  device_id: string
  device_type: string
  name: string
  status: string
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type Telemetry = {
  id: string
  schema_version: string
  timestamp: string
  device_id: string
  temperature_c: number
  bearing_temperature_c: number
  vibration_mm_s: number
  current_a: number
  voltage_v: number
  rpm: number
  load_pct: number
  power_kw: number
  operating_state: string
  fault_state: string
  ingested_at: string
}

export type SensorEvidence = {
  signal: string
  observation: number
  normal_baseline: number
  deviation: number
  trend: string
}

export type Diagnosis = {
  id: string
  device_id: string
  window_start: string
  window_end: string
  status: string
  fault_type: string | null
  anomaly_score: number | null
  confidence: number | null
  severity: string | null
  evidence: SensorEvidence[]
  model_version: string | null
  feature_version: string | null
  trace_id: string | null
  created_at: string
}

export type Alarm = {
  id: string
  device_id: string
  telemetry_id: string | null
  rule_id: string
  severity: string
  status: string
  message: string
  started_at: string
  cleared_at: string | null
  acknowledged_at: string | null
  last_triggered_at: string | null
  occurrence_count: number
}

export type IncidentSummary = {
  incident_id: string
  device_id: string
  diagnosis_id: string
  title: string
  status: string
  priority: string
  created_at: string
  updated_at: string
  diagnosis_status: string
  fault_type: string | null
  severity: string | null
  workflow_run_id: string | null
  workflow_status: string | null
  work_order_id: string | null
}

export type IncidentDetail = IncidentSummary & {
  description: string
  diagnosis: Diagnosis
  alarms?: Alarm[]
  device?: { device_id: string; device_type: string; name: string; status: string } | null
  asset?: { id: string; name: string; asset_type: string; parent_id: string | null } | null
  workflow?: { workflow_run_id: string; status: string; current_stage: string } | null
}

export type IncidentDashboardSummary = {
  active: number
  critical: number
  unacknowledged: number
}

export type IncidentDashboardItem = {
  incident_id: string
  title: string
  status: string
  severity: string | null
  priority: string
  device_id: string | null
  asset_name: string | null
  workflow_status: string | null
  created_at: string
  last_alarm_at: string | null
  resolved_at: string | null
}

export type IncidentDashboard = {
  summary: IncidentDashboardSummary
  incidents: IncidentDashboardItem[]
}

export type IncidentWorkflowBridge = {
  incident_id: string
  workflow_exists: boolean
  workflow_run_id: string | null
  workflow_status: string | null
  approval_required: boolean
}

export type IncidentMetrics = {
  mtta_seconds: number
  mttr_seconds: number
  alarm_compression: number
}

export type KnowledgeEvidence = {
  evidence_id: string
  document_id: string
  chunk_id: string
  text: string
  source: string
  page: number | null
  section: string | null
}

export type KnowledgeDocument = {
  document_id: string
  title: string
  vendor: string
  document_type: string
  equipment_type: string
  model: string | null
  revision: string | null
  publication_date: string | null
  source: string
  source_type: string
  license_note: string
  corpus_version: string
  page_count: number
  chunk_count: number
  ingested_at: string
}

export type MaintenanceStep = {
  action: string
  action_type: string
  evidence_ids: string[]
}

export type WorkflowState = {
  diagnosis: {
    id: string
    status: string
    fault_type: string | null
    confidence: number | null
    severity: string | null
    model_version: string | null
  }
  sensor_evidence: SensorEvidence[]
  knowledge_context: {
    retrieval_run_id: string | null
    sufficiency: string
    evidence: KnowledgeEvidence[]
  }
  triage_result: { problem_summary: string } | null
  maintenance_plan: { objective: string; steps: MaintenanceStep[] } | null
  safety_review: { hazards: string[]; violations: string[] } | null
  policy_decision: { decision: string; policy_version: string; reasons: string[] } | null
  approval: {
    approval_id: string
    status: string
    actor: string | null
    reason: string | null
    plan_version: number
    decided_at: string | null
  } | null
  work_order_id: string | null
  current_stage: string
  status: string
  errors: Array<{ stage: string; code: string; message: string }>
}

export type Workflow = {
  workflow_run_id: string
  incident_id: string
  diagnosis_id: string
  device_id: string
  status: string
  current_stage: string
  workflow_version: string
  policy_version: string
  provider: string
  model: string
  state: WorkflowState
  created_at: string
  updated_at: string
}

export type WorkflowSummary = Omit<Workflow, 'state' | 'workflow_version'>

export type AgentRun = {
  agent_run_id: string
  agent: string
  provider: string | null
  model: string | null
  prompt_version: string | null
  input_ref: string | null
  output_ref: string | null
  status: string
  latency_ms: number | null
  input_tokens: number | null
  output_tokens: number | null
  structured_output: Record<string, unknown>
  tool_calls: Array<Record<string, unknown>>
  request_count: number | null
  schema_retries: number | null
  error: string | null
  timestamp: string
}

export type WorkflowTrace = { workflow: Workflow; agent_runs: AgentRun[] }

export type Approval = {
  approval_id: string
  workflow_run_id: string
  maintenance_plan_id: string
  status: string
  actor: string | null
  reason: string | null
  plan_version: number
  plan_hash: string
  created_at: string
  decided_at: string | null
}

export type WorkOrder = {
  work_order_id: string
  workflow_run_id: string
  device_id: string
  incident_id: string
  diagnosis_id: string
  title: string
  priority: string
  plan: { objective?: string; steps?: MaintenanceStep[] }
  evidence_refs: string[]
  safety_requirements: string[]
  approval_id: string | null
  status: string
  created_at: string
  fault_type: string | null
  approval_actor: string | null
  approval_decided_at: string | null
}

export type ReadyStatus = {
  status: string
  dependencies: Record<string, string>
}

export type AgentStepMetric = {
  step_id: string
  agent_name: string
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
  latency_ms: number | null
  request_count: number | null
  schema_retries: number | null
  token_data_available: boolean
}

export type AgentStep = {
  step_id: string
  agent_name: string
  sequence: number
  status: string
  start_time: string
  end_time: string
  latency_ms: number | null
  input_summary: string | null
  output_summary: string | null
  error: string | null
  provider: string | null
  model: string | null
  prompt_version: string | null
  metrics: AgentStepMetric | null
}

export type ObservabilityRun = {
  run_id: string
  workflow_run_id: string | null
  workflow_name: string
  device_id: string | null
  trace_id: string | null
  provider: string | null
  model: string | null
  status: string
  start_time: string
  end_time: string | null
  latency_ms: number | null
  step_count: number
  total_tokens: number | null
  result: Record<string, unknown>
  error_message: string | null
}

export type ObservabilityRunTrace = {
  run: ObservabilityRun
  steps: AgentStep[]
}

export type AgentBreakdown = {
  agent_name: string
  steps_total: number
  failures: number
  avg_latency_ms: number | null
  p95_latency_ms: number | null
  total_tokens: number | null
  schema_retries: number | null
}

export type TokenUsage = {
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
  steps_with_token_data: number
  steps_total: number
}

export type ObservabilityMetrics = {
  total_runs: number
  runs_running: number
  runs_waiting_approval: number
  runs_today: number
  completed_runs: number
  success_count: number
  failure_count: number
  blocked_count: number
  cancelled_count: number
  success_rate: number | null
  avg_latency_ms: number | null
  p95_latency_ms: number | null
  avg_step_latency_ms: number | null
  step_status_counts: Record<string, number>
  token_usage: TokenUsage
  by_agent: AgentBreakdown[]
}

export type ApiErrorPayload = {
  error?: {
    code?: string
    message?: string
    trace_id?: string
    /** Structured failure detail, currently used to carry validation issues. */
    details?: { errors?: ValidationIssue[] }
  }
  status?: string
  dependencies?: Record<string, string>
}

export type ConnectivityDevice = {
  device_id: string
  protocol: string
  enabled: boolean
  state: string
  state_mode: 'static' | 'derived'
  polled: boolean
  poll_interval_ms: number
  endpoint: string | null
  last_success: string | null
  last_error: string | null
  message: string | null
  consecutive_failures: number
  reconnect_attempts: number
  samples_ingested: number
  samples_rejected: number
  read_errors: number
}

export type ConnectivitySummary = {
  gateway_enabled: boolean
  gateway_available: boolean
  gateway_error: string | null
  config_file: string | null
  loaded_at: string | null
  device_count: number
  enabled_device_count: number
  states: Record<string, number>
  total_samples_ingested: number
  total_samples_rejected: number
}

/**
 * Asset hierarchy and versioned device configuration.
 *
 * Device identity is not duplicated here: `device_id` refers to the existing device
 * registry. Only location, versioned configuration, and runtime apply state are
 * represented, and desired and applied versions are separate fields on purpose.
 */

export type AssetType = 'SITE' | 'LINE'

export type AssetNode = {
  id: string
  name: string
  asset_type: string
  parent_id: string | null
  description: string
  metadata: Record<string, unknown>
  device_count: number
  created_at: string
  updated_at: string
}

/** A device registry row enriched with its configuration and apply state. */
export type DeviceConfigurationState = {
  device_id: string
  name: string
  device_type: string
  status: string
  asset_node_id: string | null
  metadata: Record<string, unknown>
  protocol: string | null
  published_version: number | null
  applied_version: number | null
  apply_status: string
  in_sync: boolean
}

export type AssetTreeNode = {
  id: string
  name: string
  asset_type: string
  parent_id: string | null
  description: string
  devices: DeviceConfigurationState[]
  children: AssetTreeNode[]
}

export type AssetTree = {
  sites: AssetTreeNode[]
  unassigned_devices: DeviceConfigurationState[]
}

export type ValidationIssue = {
  field: string
  code: string
  message: string
}

export type ValidationResult = {
  valid: boolean
  errors: ValidationIssue[]
  checked_at: string | null
}

export type ConfigurationSummary = {
  version: number
  status: string
  protocol: string
  created_by: string
  created_at: string
  validated_at: string | null
  published_at: string | null
  archived_at: string | null
}

export type ConfigurationDetail = ConfigurationSummary & {
  id: string
  device_id: string
  configuration: Record<string, unknown>
  validation_result: Record<string, unknown>
  validation_error: string | null
  updated_at: string
}

/** Desired versus applied configuration. `in_sync` is false whenever they differ. */
export type ConfigurationStatus = {
  device_id: string
  desired_version: number | null
  applied_version: number | null
  apply_status: string
  source: string
  last_apply_at: string | null
  last_apply_error: string | null
  in_sync: boolean
  protocol: string | null
  runtime_state: string | null
}

export type ConfigurationAuditEvent = {
  event_id: string
  device_id: string
  event_type: string
  config_version: number | null
  timestamp: string
  actor: string
  status: string
  summary: string
}

export type PublishResult = {
  configuration: ConfigurationDetail
  status: ConfigurationStatus
}
