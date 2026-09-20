# Testing Strategy

## Goal

Ensure the Industrial AI Control Tower is correct, safe, observable, and maintainable across all phases.

## Test Levels

### Unit Tests

- Scope: individual functions, service methods, and Pydantic models.
- Tool: pytest (backend), vitest (frontend).
- Characteristics: fast, deterministic, no external services.
- Phase 0: backend `/health` test; frontend `App` render test.

### Integration Tests

- Scope: API endpoints, database repositories, Redis interactions.
- Tool: pytest with TestClient, testcontainers where appropriate.
- Characteristics: exercise real dependencies in controlled environments.
- Phase: introduced in Phase 2 when persistence layer is implemented.

### Contract Tests

- Scope: API contracts between frontend and backend, and between backend and agents.
- Tool: schemathesis or manual Pydantic model validation.
- Characteristics: verify request/response shapes and error semantics.
- Phase: introduced in Phase 2.

### Model Evaluation Tests

- Scope: dataset isolation, leakage, window features, anomaly detection, fault classification,
  calibration, serialization, compatibility, and online diagnosis.
- Tool: pytest smoke tests plus `industrial_ml.evaluation` for the frozen benchmark.
- Characteristics: CI uses tiny deterministic fixtures; the full 200-scenario benchmark is a
  deliberate release gate and is not retrained on every pull request.
- Phase: introduced in Phase 3. Agent evaluation remains Phase 5 work.

### RAG Evaluation Tests

- Scope: Knowledge retrieval relevance, citation accuracy, evidence sufficiency.
- Tool: deterministic custom evaluator over the versioned corpus and query set.
- Characteristics: development queries are used for tuning; the 60-query frozen split is a
  one-shot release gate. It reports Hit@1/3, Recall@5, MRR, nDCG@5, latency, supported acceptance,
  unsupported rejection, and False Sufficient Rate. Phase 4 evaluates retrieval, not generation.
- Phase: introduced in Phase 4.

### E2E Tests

- Scope: Full user flows from telemetry ingestion to work-order creation.
- Tool: Playwright.
- Characteristics: exercise frontend, backend, and simulated industrial sources together.
- Phase: introduced in Phase 6.

### Safety Tests

- Scope: Verify that LLMs cannot bypass approval, that safety policies are enforced, and that execution boundaries are respected.
- Tool: Adversarial test suites, red-teaming prompts, deterministic policy unit tests.
- Characteristics: must pass before any production deployment.
- Phase: introduced in Phase 3 and hardened in Phase 8.

### Regression Tests

- Scope: Previously fixed bugs and critical paths.
- Tool: pytest + CI.
- Characteristics: grow over time; must pass on every change.
- Phase: ongoing from Phase 2.

## CI Requirements

- All tests run on every pull request.
- Failing tests block merge.
- Skipping tests, deleting tests, or using `|| true` to mask failures is prohibited.
- Code coverage is reported but not used as a gate in early phases.
- ML CI must never present tiny-fixture metrics as the formal benchmark.

## Phase 3 Gates

- Scenario/seed group isolation and forbidden-label feature checks.
- Deterministic dataset generation, training smoke test, artifact save/load, and compatibility.
- Real Compose gate: Simulator → MQTT → Backend → model → PostgreSQL → REST.
- Restart warmup from PostgreSQL and explicit unavailable/failed model behavior.

## Phase 4 Gates

- Source provenance, hashes, stable chunk identity, duplicate handling, and embedding metadata.
- Frozen BM25/dense/hybrid/reranker comparison and explicit default selection.
- Citation traceability, metadata filtering, deterministic sufficiency, and OOD refusal.
- Real Compose gate: Diagnosis v1.1 → KnowledgeQuery → evidence → REST → retrieval audit.
- Knowledge-index failure remains isolated from telemetry and diagnosis readiness.
- Frozen test is evaluated only after model and thresholds are selected from train/validation.

## Phase 0 Tests

Phase 0 validates engineering structure only:

- Backend skeleton test: `test_health_endpoint`
- Frontend skeleton test: `App` renders title
- Build verification for both backend and frontend
- Lint and type check for both stacks
