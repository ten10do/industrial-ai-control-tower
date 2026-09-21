# Human Approval and Recovery

High-risk workflows persist an Approval and pause at a real LangGraph interrupt. The API is:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/approvals/pending` | Pending decisions |
| GET | `/api/v1/approvals/{approval_id}` | Decision, actor, plan version/hash |
| POST | `/api/v1/approvals/{approval_id}/approve` | Resume and create a draft work order |
| POST | `/api/v1/approvals/{approval_id}/reject` | Resume to `REJECTED`; no work order |

Decision requests require `X-Development-Actor` and a non-trivial reason. This header is the
documented Phase 5 development identity boundary, not production authentication.

Approvals bind both `plan_version` and a SHA-256 plan hash. If either differs from the current plan,
the API returns `409 STALE_APPROVAL`. A row lock serializes concurrent approve/reject requests;
the first decision wins and an opposite decision receives `409 APPROVAL_ALREADY_DECIDED`.
Repeating the same decision is idempotent.

After approval, exactly one `DRAFT` work order is associated with the workflow. Its payload states
`execution_authorized: false`. Cancelling a workflow is allowed only in `CREATED`, `TRIAGING`,
`PLANNING`, or `WAITING_APPROVAL`; a cancelled workflow cannot later be approved.

Recovery procedure: restart the backend without removing the PostgreSQL volume, verify the
workflow remains `WAITING_APPROVAL`, then submit the decision to the same approval ID. The graph
resumes with the persisted thread ID and the unique work-order constraint enforces exactly once.
