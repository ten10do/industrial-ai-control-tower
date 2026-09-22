# Phase 6 Demo Guide

This guide runs the real simulator, MQTT ingestion, Diagnosis v1.1, knowledge index, real Agent
provider, deterministic policy, approval, and work-order UI. It creates an isolated Compose project
and does not reuse or remove another project's volumes.

## 1. Configure the runtime

Copy `.env.example` to an ignored `.env`. Set `WORKFLOW_ENABLED=true`,
`AGENT_PROVIDER=openai_compatible`, the provider-advertised `AGENT_MODEL`, `AGENT_BASE_URL`, and an
environment-only `AGENT_API_KEY`. Do not place the key in any `VITE_*` variable or commit `.env`.

## 2. Build and start an isolated stack

```bash
docker compose --env-file .env -p phase6_ui build
docker compose --env-file .env -p phase6_ui up -d postgres redis mosquitto backend frontend
curl http://localhost/ready
```

Use `BACKEND_PORT_PUBLISHED` and `FRONTEND_PORT_PUBLISHED` in `.env` when the defaults are occupied.
Readiness must show PostgreSQL/Redis healthy and Diagnosis, Knowledge, and Agent Runtime available.

## 3. Register and observe the motor

```bash
curl -X POST http://localhost:8000/api/v1/devices \
  -H "Content-Type: application/json" \
  -d '{"device_id":"MOTOR-001","device_type":"IndustrialMotor","name":"Demo motor"}'
docker compose --env-file .env -p phase6_ui --profile demo up -d simulator
```

Open `http://localhost/`, then `/devices/MOTOR-001`. Confirm historical REST data and a
`CONNECTED` WebSocket state.

## 4. Inject a synthetic bearing fault

Stop the normal simulator and start the development-only synthetic scenario:

```bash
docker compose --env-file .env -p phase6_ui stop simulator
docker compose --env-file .env -p phase6_ui run -d --name phase6-bearing-demo simulator \
  python -m simulator --mqtt-broker-host mosquitto --device-id MOTOR-001 \
  --fault-type BEARING_WEAR --fault-start-tick 5 --fault-duration 120 --sample-interval 0.2
```

This controls only the synthetic simulator. It does not create an OPC UA, PLC, actuator, or real
equipment write path. Observe vibration and bearing temperature change, then identify the latest
persisted `FAULT` diagnosis.

## 5. Create and process the decision chain

Create an incident from that diagnosis with `POST /api/v1/incidents`, then start its workflow with
`POST /api/v1/incidents/{incident_id}/workflows`. Open the incident URL and verify Diagnosis,
Sensor Evidence, Knowledge Evidence, Agent Workflow, LLM Safety Review, and the deterministic
`safety-policy-v1` result.

Open Approval Center, select the pending record, enter an operator identity and reason, and choose
Approve. The browser must display the resulting real Work Order. Repeat with a new incident and
choose Reject; the workflow must be `REJECTED` and no work order may exist for it.

## 6. Evidence to record

Record the connected identifiers for both paths: `device_id`, `incident_id`, `diagnosis_id`,
`workflow_run_id`, `approval_id`, and approved `work_order_id`. Also capture the final rejected
workflow and verify its work-order count is zero.

## 7. Stop without deleting data

```bash
docker compose --env-file .env -p phase6_ui stop
```

Do not use `down -v` if the isolated demo data must be retained.
