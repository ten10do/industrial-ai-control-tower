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

### Agent Evaluation Tests

- Scope: Diagnosis, Knowledge, Planning, Safety agents.
- Tool: Custom evaluation harness with labeled datasets and deterministic safety test cases.
- Characteristics: measure correctness, evidence sufficiency, and safety veto behavior.
- Phase: introduced in Phase 3 and Phase 5.

### RAG Evaluation Tests

- Scope: Knowledge retrieval relevance, citation accuracy, evidence sufficiency.
- Tool: RAGAS or custom metrics.
- Characteristics: evaluate retrieval and generation quality against annotated industrial documents.
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

## Phase 0 Tests

Phase 0 validates engineering structure only:

- Backend skeleton test: `test_health_endpoint`
- Frontend skeleton test: `App` renders title
- Build verification for both backend and frontend
- Lint and type check for both stacks
