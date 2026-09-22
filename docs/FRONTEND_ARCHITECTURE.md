# Frontend Architecture

## Scope

Phase 6 is an operator-facing, read-heavy React application over the real Phase 2–5 services. It
does not calculate diagnoses, reimplement `safety-policy-v1`, execute work orders, or expose an
industrial write path.

## Runtime structure

```text
BrowserRouter
└── AppShell
    ├── readiness status (/ready)
    ├── navigation
    └── route page
        ├── TanStack Query server state
        ├── typed REST client
        └── one per-device telemetry WebSocket where needed
```

- `src/api.ts` owns the environment-based REST and WebSocket base URLs and normalizes the backend
  error contract into `ApiError`.
- `src/types.ts` mirrors the public backend contracts. Components do not use untyped API payloads.
- TanStack Query owns server state, cache invalidation, bounded polling, and mutation state.
- React local state is limited to filters, dialogs, form values, and the bounded live sample buffer.
- `BrowserRouter` provides refreshable deep links for devices, incidents, workflows, approvals,
  and work orders. Nginx falls back to `index.html` for nested routes.

## Real-time telemetry

REST supplies at most 300 historical samples for a selected 5, 15, or 60 minute range. Device
detail then opens exactly one `/ws/devices/{device_id}/telemetry` connection. The hook exposes
`CONNECTING`, `CONNECTED`, `RECONNECTING`, `DISCONNECTED`, and `ERROR`, retries at a capped
exponential interval, closes during unmount, and retains only the latest 300 samples.

Charts are lightweight SVG components. Each chart uses one physical unit instead of combining
incompatible signals on one axis. No charting dependency was needed.

## Trust and safety

- Diagnosis and policy decisions are displayed exactly as returned by the backend.
- LLM Safety Review and Deterministic Safety Policy are visually and semantically separate.
- The Agent trace displays structured outputs, references, tool-call records, latency, provider,
  model, prompt version, and tokens. It never requests or displays hidden reasoning.
- Knowledge excerpts are untrusted plain text. The UI never calls `dangerouslySetInnerHTML`.
- Only public `VITE_API_BASE_URL` and `VITE_WS_BASE_URL` values enter the client bundle. Provider,
  database, and MQTT credentials remain backend environment values.

## Failure isolation

Every asynchronous panel has Loading, Empty, Error, and Success states. Network failures keep the
shell available; `/ready` identifies degraded dependencies. `503` is presented as a capability
failure, `409 APPROVAL_ALREADY_DECIDED` as a concurrent decision, and `409 STALE_APPROVAL` as an
invalidated plan. A React error boundary prevents a component exception from producing a blank
page.

## Tests

Vitest and Testing Library cover API errors, diagnosis/evidence/workflow components, plain-text
evidence safety, approval validation and mutations, double-submit prevention, stale approval,
and WebSocket connect/message/reconnect/error/buffer behavior. The final browser gate uses the
real Docker backend and is separate from component mocks.
