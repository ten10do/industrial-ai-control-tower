# Phase Roadmap

## Phase 0 — Repository Foundation & Architecture Design

**Status:** In progress

Establish repository structure, architecture documentation, ADRs, domain model, agent contracts, API contracts, testing strategy, Docker foundation, CI, and minimal skeletons.

**Exit criteria:**

- Repository structure is reasonable and documented.
- Backend and frontend skeletons build, test, and lint successfully.
- Docker Compose configuration is valid.
- Architecture documentation is complete.

## Phase 1 — Industrial Simulator

Build a minimal equipment simulator that produces telemetry over MQTT and OPC UA for offline development and testing.

**Deliverables:**

- Simulator service with configurable device models
- MQTT telemetry publisher
- OPC UA server stub
- Seed data and scenario definitions

## Phase 2 — Backend / Data Platform

Implement the FastAPI backend with domain services and persistence.

**Deliverables:**

- PostgreSQL schema and Alembic migrations
- Device, Telemetry, Alarm, Incident services
- Redis integration
- API endpoints under `/api/v1/`
- Authentication and authorization foundation

## Phase 3 — ML Diagnosis Engine

Build a reproducible, explainable telemetry diagnosis engine without LLMs or agents.

**Deliverables:**

- Scenario-group dataset generation and frozen evaluation split
- Versioned telemetry-window feature pipeline with leakage gates
- Statistical anomaly detection and calibrated fault classification baselines
- Severity and sensor/feature evidence
- Integrity-checked serving artifact, online inference, persistence, and REST APIs

## Phase 4 — Industrial RAG

**Status:** Complete (Phase 4 gate passed)

Implement knowledge retrieval over industrial manuals.

**Deliverables:**

- Document ingestion pipeline
- Vector store integration
- Hybrid retrieval (keyword + embedding)
- Reranker and citation generation
- RAG evaluation suite

**Delivered:** 13 provenance-tracked documents, 2,149 parsed rows / 2,146 unique stable chunks, pgvector persistence,
four measured retrieval pipelines, deterministic citations/sufficiency, 60-query frozen evaluation,
and Diagnosis v1.1 context integration. No LLM or agent workflow is included.

## Phase 5 — Multi-Agent Workflow

**Status:** Partial / not ready (real runtime LLM gate not run)

Integrate agents into a LangGraph orchestrator with human-in-the-loop checkpoints.

**Deliverables:**

- Orchestrator workflow
- Diagnosis → Knowledge → Planning → Safety → Approval → WorkOrder flow
- Approval service
- Agent run persistence and observability

**Delivered:** typed LangGraph state, Triage/Planning/Safety agents behind one provider interface,
PostgreSQL checkpoint interrupt/resume, evidence grounding, `safety-policy-v1`, idempotent approval
and draft work-order persistence, 80-case semantic evaluation, retry/failure injection, and restart
recovery. No provider API key was available, so `REAL_LLM_NOT_RUN` prevents a full Phase 5 pass.

## Phase 6 — Frontend

Build the operator-facing dashboard and approval UI.

**Deliverables:**

- Device list and detail views
- Alarm and incident views
- Diagnostic evidence display
- Approval workflow UI
- Work order views

## Phase 7 — Production Engineering

Harden the platform for deployment and operations.

**Deliverables:**

- Docker Compose production configuration
- Prometheus metrics and OpenTelemetry traces
- Grafana dashboards
- Logging and alerting
- Secrets management strategy

## Phase 8 — Evaluation & Hardening

Comprehensive evaluation, safety testing, and regression hardening.

**Deliverables:**

- End-to-end test suite
- Safety red-team evaluation
- Performance and load testing
- Documentation and runbook finalization
- Production readiness review
