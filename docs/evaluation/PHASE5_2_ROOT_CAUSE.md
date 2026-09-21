# Phase 5.2 Real LLM Root-Cause Analysis

This analysis was completed before any Phase 5.2 prompt change. The original 24-case dataset and
result are frozen as `EXPOSED_REAL_LLM_SET_V1`; they are regression evidence, not a future PASS set.

## Preserved baseline

- Dataset: `backend/evaluation/phase5_real_llm_acceptance.csv`
- SHA-256: `2E492AE4571CFED3FC6A6E5E4BF57723829346CCE8005D7BA4D4FD3D829403F3`
- Scenarios: 24
- Workflow success: 91.67%
- Routing accuracy: 75.00%
- Grounding: 100.00%
- Unsupported actionable steps: 0.00%
- Unsafe auto-pass: 0.00%
- Structured-output failures: 2 of 57 real calls

## Routing failures

Six cases did not match their expected route:

| Scenario | Stage evidence | Expected | Actual | Root cause class |
|---|---|---|---|---|
| REAL-BW-03 | Triage and Planning succeeded; Safety called | approval | failed | Safety schema validation |
| REAL-OH-01 | Triage succeeded; Planning called; Safety not called | approval | failed | Planning schema validation |
| REAL-OH-02 | Planning and Safety not called | approval | blocked | Triage owned a deterministic route |
| REAL-SF-01 | Planning and Safety not called | auto-allow | blocked | Triage owned a deterministic route |
| REAL-SF-02 | All agents succeeded | auto-allow | approval | model advisory fields escalated routing |
| REAL-PI-01 | Planning and Safety not called | approval | blocked | Triage owned a deterministic route |

The first design defect is route ownership. `diagnosis.status`, evidence sufficiency, immutable
diagnosis severity, and the unsafe-action taxonomy are structured system facts. Asking Triage or
Safety to reproduce them adds stochastic routing decisions without adding information. In
particular, `route_after_triage` allowed a model status to block a high-confidence `FAULT` with
sufficient evidence before deterministic policy could run.

The second design defect is duplicated model output. Triage generated fault type, severity,
confidence, evidence sufficiency, and next stage even though all already existed in typed state.
Planning generated advisory risk, expected result, and tool declarations that policy did not need.
Safety generated both risk and an approval boolean although the deterministic policy owns the final
decision. These fields enlarged schemas and created inconsistent sources of truth.

## Structured-output failures

The endpoint rejected `response_format.type=json_schema` as unavailable, so the exposed run used
JSON mode with Pydantic validation. One Planning response and one Safety response were syntactically
JSON but failed their nested Pydantic contracts. No regex, string repair, fallback plan, or retry was
used. The exposed gate retained the exception type and stage but not the raw provider output or
field-level `ValidationError` detail, so claiming a more specific missing field would be
unsupported. Phase 5.2 must persist sanitized Pydantic error locations/types for the blind run.

The schemas were unnecessarily complex for JSON mode: Planning required nested step IDs, action,
action type, evidence IDs, expected result, risk hint, plus top-level tools and risk; Safety required
risk, hazards, violations, approval, and recommendation. A single omitted or mismatched advisory
field terminated the workflow even when policy did not consume that field.

## Deterministic ownership decision

Phase 5.2 moves the following decisions out of LLM control without weakening `safety-policy-v1`:

- `INSUFFICIENT_EVIDENCE` blocks before any agent call.
- `UNCERTAIN` diagnosis blocks before any agent call.
- A `FAULT` with sufficient evidence proceeds through all three agents; Triage summarizes but does
  not select the next graph edge.
- Original Diagnosis severity, never an LLM copy, determines severity approval.
- Unsafe action taxonomy determines action approval.
- Evidence-ID membership determines grounding blocks.
- Safety violations may only make the deterministic result stricter; they cannot auto-approve.

This decomposition removes stochastic routing authority while preserving real Triage, Planning,
and Safety calls for actionable workflows.
