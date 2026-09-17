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

## Phase 3 — AI Diagnosis Engine

Introduce the Diagnosis Agent and Safety Agent with structured outputs and evidence policy.

**Deliverables:**

- Diagnosis Agent skeleton with provider abstraction
- Safety Agent with deterministic policy engine
- Evidence sufficiency gate
- Agent evaluation harness

## Phase 4 — Industrial RAG

Implement knowledge retrieval over industrial manuals.

**Deliverables:**

- Document ingestion pipeline
- Vector store integration
- Hybrid retrieval (keyword + embedding)
- Reranker and citation generation
- RAG evaluation suite

## Phase 5 — Multi-Agent Workflow

Integrate agents into a LangGraph orchestrator with human-in-the-loop checkpoints.

**Deliverables:**

- Orchestrator workflow
- Diagnosis → Knowledge → Planning → Safety → Approval → WorkOrder flow
- Approval service
- Agent run persistence and observability

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
