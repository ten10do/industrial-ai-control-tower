# Industrial AI Control Tower

A multi-agent AI decision platform for industrial equipment operation and maintenance.

## Problem

Industrial facilities generate large volumes of telemetry, alarms, and maintenance knowledge, but critical decisions still rely on fragmented systems and human triage. This project aims to build a control tower that combines real-time monitoring, anomaly detection, fault diagnosis, industrial knowledge retrieval, multi-agent collaboration, safety review, human approval, and work-order execution into one auditable, closed-loop system.

## Architecture

The target architecture is documented in [`docs/architecture/SYSTEM_ARCHITECTURE.md`](docs/architecture/SYSTEM_ARCHITECTURE.md). It consists of:

- **Frontend:** React / TypeScript / Vite
- **Backend:** FastAPI service layer
- **Agent Orchestrator:** LangGraph-based workflow (Phase 5+)
- **Data Layer:** PostgreSQL, Redis, Vector Store, Audit/Event Storage
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
| Frontend | React, TypeScript, Vite |
| Agent | LangGraph (future) |
| Persistence | PostgreSQL, Redis |
| Vector Store | Reserved for Phase 4+ |
| Industrial | MQTT, OPC UA (future) |
| DevOps | Docker, Docker Compose, GitHub Actions |
| Observability | Structured logging, Prometheus, OpenTelemetry (future) |

## Repository Structure

```text
industrial-ai-control-tower/
├── backend/              # FastAPI application
├── frontend/             # React + TypeScript + Vite application
├── simulator/            # Industrial equipment simulator (Phase 1+)
├── docs/                 # Architecture, ADRs, contracts
│   ├── architecture/
│   ├── adr/
│   ├── contracts/
│   ├── DOMAIN_MODEL.md
│   ├── AGENT_CONTRACTS.md
│   ├── API_CONTRACT.md
│   ├── TESTING_STRATEGY.md
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
2. Start infrastructure services (optional for Phase 0):
   ```bash
   docker compose up -d postgres redis
   ```
3. Install and run the backend:
   ```bash
   cd backend
   python -m venv .venv
   source .venv/Scripts/activate
   pip install -r requirements-dev.txt
   uvicorn app.main:app --reload
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
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Phase-by-phase roadmap |

## Testing

- Backend: `pytest`
- Frontend: `npm run test`
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

**Current Phase: Phase 0**

Phase 0 establishes the repository foundation, architecture documentation, and minimal skeletons. No production business logic is implemented yet.
