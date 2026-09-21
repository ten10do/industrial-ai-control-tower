# Phase 5 Agent Contracts

Only responsibilities requiring language-model reasoning are agents. Diagnosis v1.1, knowledge
retrieval/sufficiency, deterministic policy, repositories, approval, and work-order persistence are
ordinary services.

Every agent is called through `AgentModelProvider`, receives a typed `AgentInvocation`, and returns
a Pydantic-validated structured output. Provider, model, prompt version, latency, token usage, and
status are audited. The default temperature is low and all allowed tools are read-only.

## Triage Agent (`triage-prompt-v3`)

Input: immutable Diagnosis v1.1 snapshot, sensor evidence, knowledge evidence/sufficiency, and
device-bound context.

Output: only `problem_summary`. Diagnosis status, fault type, severity, confidence, knowledge
sufficiency, and routing remain immutable structured inputs owned by deterministic code. An
`INSUFFICIENT_EVIDENCE` knowledge result or any diagnosis status other than `FAULT` is blocked by
the precondition gate before Triage is called.

## Planning Agent (`planning-prompt-v3`)

Input: only the bound diagnosis, sensor evidence, current knowledge evidence, device context, and
triage result.

Output: objective and 1–5 typed steps. Each step contains only a human-readable action, an allowed
action type, and one or more evidence IDs. The deterministic validator rejects any ID outside the
current context. Persisted legacy `tools_required` and `estimated_risk` columns are populated from
deterministic system facts rather than model output.

## Safety Review Agent (`safety-review-prompt-v3`)

Input: the same bound context plus the structured plan.

Output: hazards and violations only. This review may block a plan but cannot lower diagnosis
severity, recommend approval, or auto-allow work. `safety-policy-v1` always makes the final
decision and may be stricter.

## Failure contract

Provider timeout, network errors, and HTTP 5xx may retry within configured graph bounds. Native
tool-schema output that is missing or fails strict Pydantic validation may receive one bounded
schema retry (`AGENT_SCHEMA_MAX_ATTEMPTS=2` by default); it is never repaired with regex or string
rewrites. Policy block, insufficient evidence, rejection, and cancellation do not retry.
Exhaustion becomes `FAILED`; there is no fabricated plan, automatic approval, or device action
fallback.

Retrieved document text is enclosed in an explicit `UNTRUSTED RETRIEVED EVIDENCE` section. It can
support citations but cannot change system instructions, add tools, weaken safety, or authorize an
execution boundary.
