# Phase 5 Multi-Agent Decision Architecture

## Scope and authority

Phase 5 is a decision-support workflow. It produces a recommendation and a `DRAFT` work order;
it has no PLC, OPC UA write, stop, restart, or maintenance-execution capability. LangGraph owns
orchestration, conditional routing, durable checkpoints, and human interrupts. Existing diagnosis,
knowledge retrieval, deterministic policy, approval persistence, and work-order persistence remain
ordinary services.

Only three responsibilities use a model provider:

- Triage Agent: summarizes the already-bound Diagnosis v1.1 problem state.
- Planning Agent: proposes only taxonomy-constrained, evidence-cited steps.
- Safety Review Agent: identifies semantic hazards but cannot make the final decision.

## State and transitions

`WorkflowState` is a Pydantic contract containing identifiers, immutable diagnosis and evidence
snapshots, each structured agent output, policy/approval state, versions, attempts, errors, and
timestamps. The implemented transitions are:

```text
CREATED -> PRECONDITION
  -> BLOCKED (insufficient knowledge or diagnosis status other than FAULT)
  -> TRIAGED -> PLAN_READY -> SAFETY_REVIEW
  -> BLOCKED
  -> REQUIRES_APPROVAL -> WAITING_APPROVAL -> APPROVED -> WORK_ORDER_CREATED
                                         \-> REJECTED
  -> AUTO_ALLOWED -> WORK_ORDER_CREATED
```

The service never emits `MAINTENANCE_COMPLETED`, `FAULT_RESOLVED`, or `DEVICE_REPAIRED`.
Incident states used in Phase 5 are `OPEN`, `UNDER_ANALYSIS`, `ACTION_PENDING`, and
`WORK_ORDER_CREATED`; only future verified maintenance feedback may close an incident.

## Persistence and recovery

PostgreSQL stores `workflow_runs`, plans, approvals, work orders, agent runs, and LangGraph's
checkpoint tables. Alembic revision `20260920_04` owns the complete schema, including the exact
checkpoint migrations used by `langgraph-checkpoint-postgres` 3.1.2. A stable workflow UUID is the
LangGraph `thread_id`.

The approval node calls LangGraph `interrupt()` before processing a decision. Resume uses
`Command(resume=...)` with the same thread ID. The node may restart from its beginning, so approval,
work-order, and workflow identities are protected by unique constraints, row locks, and stable
idempotency keys. Duplicate workflow triggers are serialized with a PostgreSQL transaction-level
advisory lock.

## Model provider and trust boundary

All three agents use `AgentModelProvider`. `OpenAICompatibleProvider` sends the output contract as
an OpenAI-compatible function/tool JSON Schema and validates returned arguments with the expected
Pydantic model. The configured DeepSeek Flash endpoint supports this native tool schema but rejects
forced `tool_choice` in thinking mode, so the schema is supplied without forcing a named tool.
Missing calls, missing arguments, wrong types, and malformed arguments fail closed. One bounded
schema retry is allowed by default; the provider never repairs model text with regex or string
rewrites. `TestProvider` is explicitly deterministic and is only evidence for unit,
graph-transition, and failure-injection testing; it is never reported as a real LLM.

Prompts separate `SYSTEM INSTRUCTIONS`, structured diagnosis, sensor evidence, prior structured
outputs, and `UNTRUSTED RETRIEVED EVIDENCE`. Retrieved text cannot add tools, change the diagnosed
fault, disable policy, or cross the execution boundary. All registered agent tools are read-only;
the current workflow binds required inputs directly and makes no runtime tool calls.

## Retry and failure semantics

Timeouts, network errors, and provider HTTP 5xx responses are retried by the graph. Invalid native
structured output is handled separately by the provider with a bounded schema retry. Maximum
attempts, schema attempts, exponential backoff base, and node timeout are environment-configured.
Safety blocks, insufficient evidence, rejection, and cancellation are not retried. Exhausted
failures set the workflow to `FAILED`; they never synthesize a plan or approval.

## Observability

`agent_runs` records agent name, workflow/trace, provider, model, prompt version, references,
read-only tool calls, latency, token usage, status, and sanitized error. `GET
/api/v1/workflow-metrics` exposes the Phase 5 foundation counters and aggregate latencies. Provider
prices are intentionally not hard-coded.
