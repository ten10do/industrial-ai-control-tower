# Phase 5 Failure and Safety Analysis

## Injected and integration cases

| Case | Expected behavior | Verified behavior |
|---|---|---|
| Provider timeout | Retry only to configured maximum, then fail | 3 attempts; exception propagated |
| Invalid structured output | No retry | Pydantic validation failed on first call |
| Knowledge unavailable/insufficient | No plan or work order | `BLOCKED`, zero work orders |
| PostgreSQL checkpoint outage | Fail closed; no terminal success | Injected saver error propagated |
| Approval rejected | Terminal rejection | Idempotent `REJECTED`, zero work orders |
| Backend restart at interrupt | Recover from PostgreSQL checkpoint | Remained waiting, resumed successfully |
| Duplicate approval | Exactly one work order | Same work-order ID, database count 1 |
| Concurrent approve/reject | One terminal decision | Approve 200; reject 409; count 1 |
| Stale plan approval | Reject old approval | `409 STALE_APPROVAL` |
| Prompt injection in evidence | Treat as text | Delimited inside untrusted evidence block |
| LLM says restart is safe | Policy remains stricter | `REQUIRES_APPROVAL` |

The backend uses the database as the failure boundary. A temporary PostgreSQL outage makes
readiness fail and prevents side effects; recovery does not infer approval or create a work order.
Knowledge and provider failures never fall back to fabricated content.

## Known limitations

- The runtime real-LLM gate was not run because no API key was available.
- The 80-case set evaluates structured policy semantics with a deterministic provider, not field
  maintenance quality or natural-language quality.
- Diagnosis metrics are based on synthetic motor telemetry; the knowledge corpus is limited.
- Development identity headers are not production authentication or authorization.
- Metrics are an API/SQL foundation; Prometheus export and dashboards remain later work.
