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

export type ApiErrorPayload = {
  error?: { code?: string; message?: string; trace_id?: string }
  status?: string
  dependencies?: Record<string, string>
}
