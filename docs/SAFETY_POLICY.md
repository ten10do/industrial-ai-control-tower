# Deterministic Safety Policy

Policy version: `safety-policy-v1`.

The Safety Review Agent provides semantic hazard analysis; `app/workflow/policy.py` is the final
authority and may be stricter than the model. No LLM output can weaken or bypass it.

## Decisions

- `BLOCKED`: diagnosis status other than `FAULT`, insufficient knowledge evidence, a plan step
  citing missing/foreign evidence, or any Safety Review violation.
- `REQUIRES_APPROVAL`: grounded plans with immutable Diagnosis severity `HIGH`/`CRITICAL`, or any
  `STOP`, `ISOLATE`, `LOCKOUT_TAGOUT`, `DISASSEMBLE`, `REPLACE`, or `RESTART` action.
- `AUTO_ALLOWED`: only a grounded low-risk plan outside the approval rules. This authorizes creation
  of a draft work order, not equipment execution.

Allowed action types are `OBSERVE`, `INSPECT`, `MEASURE`, `TEST`, `ADJUST`, `STOP`, `ISOLATE`,
`LOCKOUT_TAGOUT`, `DISASSEMBLE`, `REPLACE`, `RESTART`, and `ESCALATE`.

Every plan step must contain at least one evidence ID and every ID must exist in that workflow's
current knowledge snapshot. Otherwise the policy emits `UNSUPPORTED_PLAN_STEP:<position>` and
blocks. Safety Review can only add violations and therefore cannot weaken or bypass these rules.

The tracked 80-scenario evaluation hard gates are: unsafe action auto-pass 0%, unsupported
actionable step 0%, and approval routing at least 95%.
