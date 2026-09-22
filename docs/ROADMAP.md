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

**Status:** Complete (Phase 5.3 release gate passed)

Integrate agents into a LangGraph orchestrator with human-in-the-loop checkpoints.

**Deliverables:**

- Orchestrator workflow
- Diagnosis → Knowledge → Planning → Safety → Approval → WorkOrder flow
- Approval service
- Agent run persistence and observability

**Delivered:** typed LangGraph state, Triage/Planning/Safety agents behind one provider interface,
PostgreSQL checkpoint interrupt/resume, evidence grounding, `safety-policy-v1`, idempotent approval
and draft work-order persistence, 80-case semantic evaluation, retry/failure injection, restart
recovery, the one-shot 30-case Real LLM Blind Gate, and final real-provider integration.

## Phase 6 — Frontend

**Status:** Complete (Phase 6 release gate passed)

Build the operator-facing dashboard and approval UI.

**Deliverables:**

- Device list and detail views
- Alarm and incident views
- Diagnostic evidence display
- Approval workflow UI
- Work order views

**Implemented:** typed real API client, router/deep links, global readiness, Dashboard, device
history plus reconnecting bounded WebSocket charts, diagnosis/sensor/knowledge evidence, structured
Agent trace without chain-of-thought, deterministic policy display, real Approve/Reject mutations,
and non-executing work-order views.

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
