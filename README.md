# Industrial AI Control Tower

An industrial telemetry and synthetic fault-diagnosis platform, built phase by phase toward a
larger decision-support system.

## Problem

Industrial facilities generate large volumes of telemetry, alarms, and maintenance knowledge, but critical decisions still rely on fragmented systems and human triage. This project builds a control tower that combines real-time monitoring, anomaly detection, fault diagnosis, industrial knowledge retrieval, multi-agent collaboration, safety review, human approval, and work-order generation in one auditable decision-support system.

## Architecture

The target architecture is documented in [`docs/architecture/SYSTEM_ARCHITECTURE.md`](docs/architecture/SYSTEM_ARCHITECTURE.md). It consists of:

- **Frontend:** React / TypeScript / Vite
- **Backend:** FastAPI service layer
- **Diagnosis Engine:** versioned scikit-learn models over bounded telemetry windows
- **Agent Orchestrator:** LangGraph workflow with PostgreSQL checkpoints and human interrupts
- **Data Layer:** PostgreSQL + pgvector, Redis, Audit/Event Storage
- **Industrial Integration:** MQTT, OPC UA, Equipment Simulator
- **Observability:** Structured logging, Prometheus, OpenTelemetry, Grafana

## Core Capabilities (Target)

- Real-time device monitoring
- Alarm aggregation and incident creation
- AI-assisted diagnosis with evidence retrieval
- Multi-agent planning and safety review
- Human-in-the-loop approval
- Maintenance work-order generation and feedback

## Technology Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11+, FastAPI, Pydantic, SQLAlchemy, Alembic |
| Diagnosis | NumPy, scikit-learn, joblib |
| Frontend | React, TypeScript, Vite |
| Agent | LangGraph, typed structured outputs, provider abstraction |
| Persistence | PostgreSQL, Redis |
| Vector Store | PostgreSQL + pgvector; versioned local retrieval artifact |
| Industrial | MQTT, OPC UA (future) |
| DevOps | Docker, Docker Compose, GitHub Actions |
| Observability | Structured logging, Prometheus, OpenTelemetry (future) |

## Repository Structure

```text
industrial-ai-control-tower/
├── backend/              # FastAPI application
├── frontend/             # React + TypeScript + Vite application
├── simulator/            # Industrial equipment simulator (Phase 1)
├── ml/                   # Reproducible dataset, training, and evaluation pipeline
├── docs/                 # Architecture, ADRs, contracts
│   ├── architecture/
│   ├── adr/
│   ├── contracts/
│   ├── DOMAIN_MODEL.md
│   ├── AGENT_CONTRACTS.md
│   ├── API_CONTRACT.md
│   ├── TESTING_STRATEGY.md
│   ├── SIMULATOR.md
│   └── ROADMAP.md
├── tests/                # Cross-service tests
├── scripts/              # Utility scripts
├── infra/                # Infrastructure definitions
├── .github/workflows/    # CI/CD
├── docker-compose.yml
├── .env.example
└── README.md
```

## Quick Start

1. Copy `.env.example` to `.env` and adjust values.
2. Start the platform (the backend applies Alembic migrations, ingests the versioned knowledge
   index, and loads the frozen diagnosis model):
   ```bash
   docker compose up -d postgres redis mosquitto backend
   ```
   Phase 5 is disabled by default. It requires `WORKFLOW_ENABLED=true`,
   `AGENT_PROVIDER=openai_compatible`, `AGENT_MODEL`, and an environment-only `AGENT_API_KEY` for
   real-model operation. `AGENT_PROVIDER=test` is deterministic test-only mode and does not satisfy
   the real-LLM gate.
3. Register `MOTOR-001`, then start the simulator demo:
   ```bash
   curl -X POST http://localhost:8000/api/v1/devices \
     -H "Content-Type: application/json" \
     -d '{"device_id":"MOTOR-001","device_type":"IndustrialMotor","name":"Demo motor"}'
   docker compose --profile demo up -d simulator
   ```
4. Install and run the frontend:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

## Development

See [`docs/architecture/SYSTEM_ARCHITECTURE.md`](docs/architecture/SYSTEM_ARCHITECTURE.md) and the ADRs in [`docs/adr/`](docs/adr/) for design context.

## Documentation

| Document | Purpose |
|----------|---------|
| [`docs/architecture/SYSTEM_ARCHITECTURE.md`](docs/architecture/SYSTEM_ARCHITECTURE.md) | System context, components, data flow, trust boundaries |
| [`docs/DOMAIN_MODEL.md`](docs/DOMAIN_MODEL.md) | Core entities and lifecycles |
| [`docs/AGENT_CONTRACTS.md`](docs/AGENT_CONTRACTS.md) | Input/output schemas and failure semantics for agents |
| [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) | API namespaces, error contract, status values |
| [`docs/TESTING_STRATEGY.md`](docs/TESTING_STRATEGY.md) | Test levels and CI requirements |
| [`docs/SIMULATOR.md`](docs/SIMULATOR.md) | Simulator model, telemetry schema, MQTT topics |
| [`docs/DATA_PLATFORM.md`](docs/DATA_PLATFORM.md) | PostgreSQL schema, indexes, Redis and retention |
| [`docs/INGESTION_PIPELINE.md`](docs/INGESTION_PIPELINE.md) | Validation and delivery semantics |
| [`docs/ML_PIPELINE.md`](docs/ML_PIPELINE.md) | Phase 3 dataset, features, models, evaluation, and serving |
| [`docs/KNOWLEDGE_RAG.md`](docs/KNOWLEDGE_RAG.md) | Phase 4 query, retrieval, evidence, sufficiency, and failure contracts |
| [`docs/KNOWLEDGE_CORPUS.md`](docs/KNOWLEDGE_CORPUS.md) | Corpus provenance, parsing, hashes, and reindex procedure |
| [`docs/MULTI_AGENT_ARCHITECTURE.md`](docs/MULTI_AGENT_ARCHITECTURE.md) | Phase 5 typed workflow, checkpoints, providers, and trust boundaries |
| [`docs/SAFETY_POLICY.md`](docs/SAFETY_POLICY.md) | Versioned deterministic safety and grounding rules |
| [`docs/HUMAN_APPROVAL.md`](docs/HUMAN_APPROVAL.md) | Interrupt/resume, identity, stale plans, and concurrency |
| [`docs/FRONTEND_ARCHITECTURE.md`](docs/FRONTEND_ARCHITECTURE.md) | Phase 6 routes, state, data flow, and browser trust boundaries |
| [`docs/CONTROL_TOWER_UI.md`](docs/CONTROL_TOWER_UI.md) | Operator views, evidence presentation, and approval behavior |
| [`docs/DEMO_GUIDE.md`](docs/DEMO_GUIDE.md) | End-to-end Control Tower demonstration procedure |
| [`docs/evaluation/PHASE5_AGENT_EVALUATION.md`](docs/evaluation/PHASE5_AGENT_EVALUATION.md) | Tracked 80-scenario semantic evaluation |
| [`docs/evaluation/PHASE4_RAG_EVALUATION.md`](docs/evaluation/PHASE4_RAG_EVALUATION.md) | Frozen 60-query retrieval evaluation and pipeline selection |
| [`docs/evaluation/PHASE4_ERROR_ANALYSIS.md`](docs/evaluation/PHASE4_ERROR_ANALYSIS.md) | Retrieval errors, safety failures, and limitations |
| [`docs/evaluation/PHASE3_MODEL_EVALUATION.md`](docs/evaluation/PHASE3_MODEL_EVALUATION.md) | Frozen-test metrics and limitations |
| [`docs/evaluation/EXPOSED_TEST_V1_ANALYSIS.md`](docs/evaluation/EXPOSED_TEST_V1_ANALYSIS.md) | Root cause of the original Normal false positives |
| [`docs/evaluation/PHASE3_1_BLIND_EVALUATION.md`](docs/evaluation/PHASE3_1_BLIND_EVALUATION.md) | One-shot v1.1 blind acceptance metrics |
| [`PHASE_3_1_FINAL_REPORT.md`](PHASE_3_1_FINAL_REPORT.md) | Phase 3.1 closure, live-chain evidence, and readiness decision |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Phase-by-phase roadmap |

## Testing

- Backend: `pytest`
- ML smoke suite: `cd ml && pytest`
- Full benchmark: generate, train, then run the frozen-test evaluation as documented in
  [`docs/ML_PIPELINE.md`](docs/ML_PIPELINE.md)
- Frontend: `npm run test`
- Phase 6 frontend: `cd frontend && npm test && npm run lint && npm run build`
- Full verification: see CI workflow

## Roadmap

| Phase | Focus |
|-------|-------|
| Phase 0 | Repository Foundation & Architecture Design |
| Phase 1 | Industrial Simulator |
| Phase 2 | Backend / Data Platform |
| Phase 3 | AI Diagnosis Engine |
| Phase 4 | Industrial RAG |
| Phase 5 | Multi-Agent Workflow |
| Phase 6 | Frontend |
| Phase 7 | Production Engineering |
| Phase 8 | Evaluation & Hardening |

## Safety Principles

- LLMs are not allowed to directly control industrial equipment.
- Any execution path that affects physical systems must pass through a deterministic Safety Gate, policy rules, human approval, and an explicit execution boundary.
- Evidence is required for diagnosis and planning; the system must return `INSUFFICIENT_EVIDENCE` when evidence is inadequate.
- All critical agent actions are auditable without logging secrets or API keys.

## Current Project Status

**Current Phase: Phase 6 complete**

The Phase 6 operator interface is implemented over the real Phase 2–5 APIs: fleet overview,
historical and WebSocket telemetry, ML and sensor evidence, cited knowledge, structured Agent
traces, deterministic policy, human approval, and non-executing work orders. See
[`docs/DEMO_GUIDE.md`](docs/DEMO_GUIDE.md). The isolated Docker, real-provider browser, full
regression, migration, dependency, and security gates passed on 2026-09-22. Phase 7 has not begun.
