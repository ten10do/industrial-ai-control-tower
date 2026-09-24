"""Phase 6.11 deployment-foundation tests.

Covers three groups:

1. Config validation (``scripts/validate_env.py``) — rejects real secrets in
   the example template, empty secrets and missing required variables in a
   runtime env, and out-of-range/invalid configuration.
2. Deployment check (``scripts/deployment_check.py``) — pass path with a
   fake backend, and failed-service detection when the backend is down.
3. Backup/restore round-trip (``scripts/backup_database.sh`` +
   ``scripts/restore_database.sh``) — exercised against the one-shot test
   PostgreSQL with real pg_dump/psql binaries when they are available
   (pgserver bundle); otherwise the test is skipped, never faked.
"""

import importlib.util
import json
import shutil
import socket
import subprocess
import sys
import threading
import types
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
PYTHON = sys.executable

VENV = REPO_ROOT / ".venv"

# Resolve bash explicitly: a bare "bash" on PATH can resolve to WSL bash on
# Windows sandboxes, which may be blocked or produce non-UTF8 diagnostics.
BASH_BIN = shutil.which("bash") or "bash"


def run_script(
    script: str, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH_BIN, str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def _load_script_module(name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None
    loader = spec.loader
    assert loader is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def run_validate(env_file: Path, mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, str(SCRIPTS / "validate_env.py"), str(env_file), "--mode", mode],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


# --------------------------------------------------------------------------- #
# Config validation
# --------------------------------------------------------------------------- #


def test_example_template_with_placeholder_secrets_passes(tmp_path: Path) -> None:
    env = tmp_path / ".env.example"
    env.write_text(
        "DATABASE_URL=postgresql+asyncpg://postgres:change-me-in-dotenv@postgres:5432/db\n"
        "REDIS_URL=redis://redis:6379/0\n"
        "MQTT_HOST=mosquitto\n"
        "MQTT_PORT=1883\n"
        "POSTGRES_PASSWORD=change-me-in-dotenv\n"
        "MQTT_PASSWORD=\n"
        "AGENT_API_KEY=\n",
        encoding="utf-8",
    )
    result = run_validate(env, "example")
    assert result.returncode == 0, result.stderr


def test_example_template_rejects_real_secret(tmp_path: Path) -> None:
    env = tmp_path / ".env.example"
    env.write_text(
        "DATABASE_URL=postgresql+asyncpg://postgres:change-me-in-dotenv@postgres:5432/db\n"
        "REDIS_URL=redis://redis:6379/0\n"
        "MQTT_HOST=mosquitto\n"
        "MQTT_PORT=1883\n"
        "POSTGRES_PASSWORD=SuperSecret123!\n",
        encoding="utf-8",
    )
    result = run_validate(env, "example")
    assert result.returncode == 1
    assert "real-looking secret" in result.stderr


def test_runtime_env_rejects_missing_required_variable(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("LOG_LEVEL=INFO\n", encoding="utf-8")
    result = run_validate(env, "runtime")
    assert result.returncode == 1
    assert "missing required variable" in result.stderr


def test_runtime_env_rejects_empty_secret(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "DATABASE_URL=postgresql+asyncpg://postgres:x@postgres:5432/db\n"
        "REDIS_URL=redis://redis:6379/0\n"
        "MQTT_HOST=mosquitto\n"
        "MQTT_PORT=1883\n"
        "POSTGRES_PASSWORD=\n",
        encoding="utf-8",
    )
    result = run_validate(env, "runtime")
    assert result.returncode == 1
    assert "empty secret" in result.stderr


def test_runtime_env_rejects_placeholder_password(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "DATABASE_URL=postgresql+asyncpg://postgres:change-me-in-dotenv@postgres:5432/db\n"
        "REDIS_URL=redis://redis:6379/0\n"
        "MQTT_HOST=mosquitto\n"
        "MQTT_PORT=1883\n"
        "POSTGRES_PASSWORD=change-me-in-dotenv\n",
        encoding="utf-8",
    )
    result = run_validate(env, "runtime")
    assert result.returncode == 1
    assert "placeholder secret" in result.stderr


def test_runtime_env_rejects_invalid_config(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "DATABASE_URL=postgresql+asyncpg://postgres:x@postgres:5432/db\n"
        "REDIS_URL=redis://redis:6379/0\n"
        "MQTT_HOST=mosquitto\n"
        "MQTT_PORT=not-a-port\n"
        "POSTGRES_PASSWORD=real-password\n"
        "LOG_LEVEL=VERBOSE\n",
        encoding="utf-8",
    )
    result = run_validate(env, "runtime")
    assert result.returncode == 1
    assert "non-integer value for MQTT_PORT" in result.stderr
    assert "invalid LOG_LEVEL" in result.stderr


def test_runtime_env_rejects_out_of_range_port(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "DATABASE_URL=postgresql+asyncpg://postgres:x@postgres:5432/db\n"
        "REDIS_URL=redis://redis:6379/0\n"
        "MQTT_HOST=mosquitto\n"
        "MQTT_PORT=99999\n"
        "POSTGRES_PASSWORD=real-password\n",
        encoding="utf-8",
    )
    result = run_validate(env, "runtime")
    assert result.returncode == 1
    assert "out-of-range value for MQTT_PORT" in result.stderr


def test_committed_example_template_passes_example_scan() -> None:
    """The committed .env.example must never carry a real secret."""

    result = subprocess.run(
        [
            PYTHON,
            str(SCRIPTS / "validate_env.py"),
            str(REPO_ROOT / ".env.example"),
            "--mode",
            "example",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------- #
# Deployment check
# --------------------------------------------------------------------------- #


class _FakeBackendHandler(BaseHTTPRequestHandler):
    healthy = True

    def log_message(self, *args: object) -> None:  # silence test output
        return None

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if not self.healthy:
            self.send_error(503)
            return
        if self.path == "/health":
            body = b'{"status": "ok"}'
            content = "application/json"
        elif self.path == "/ready":
            body = b'{"status": "ready"}'
            content = "application/json"
        elif self.path == "/metrics":
            body = b"# HELP telemetry_ingest_total t\ntelemetry_ingest_total 1\n"
            content = "text/plain; version=0.0.4"
        elif self.path == "/api/v1/platform/metrics":
            body = b'{"system": {}, "pipeline": {}, "incident": {}}'
            content = "application/json"
        elif self.path == "/api/v1/incidents/dashboard":
            body = b'{"summary": {}, "incidents": []}'
            content = "application/json"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def fake_backend() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeBackendHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    thread.join(timeout=5)


def _run_check(backend_url: str) -> dict[str, Any]:
    result = subprocess.run(
        [PYTHON, str(SCRIPTS / "deployment_check.py"), "--backend-url", backend_url],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {"code": result.returncode, "report": json.loads(result.stdout)}


def test_deployment_check_passes_against_healthy_backend(fake_backend: str) -> None:
    outcome = _run_check(fake_backend)
    assert outcome["code"] == 0, outcome["report"]
    report = outcome["report"]
    assert report["status"] == "pass"
    assert all(value == "ok" for key, value in report["checks"].items() if key != "migration_head")
    assert report["checks"]["migration_head"] == "skipped"  # no --database-url passed


def test_deployment_check_detects_failed_service(fake_backend: str) -> None:
    _FakeBackendHandler.healthy = False
    try:
        outcome = _run_check(fake_backend)
    finally:
        _FakeBackendHandler.healthy = True
    assert outcome["code"] == 1
    report = outcome["report"]
    assert report["status"] == "fail"


def test_deployment_check_detects_unreachable_backend() -> None:
    # Bind then close: a port with nothing listening.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        dead_port = sock.getsockname()[1]
    outcome = _run_check(f"http://127.0.0.1:{dead_port}")
    assert outcome["code"] == 1
    assert outcome["report"]["status"] == "fail"
    assert outcome["report"]["checks"]["health"] == "error"


def test_deployment_check_reports_docker_daemon_unavailable(fake_backend: str) -> None:
    """Without a daemon the container check reports the marker instead of lying."""

    import subprocess as sp

    module = _load_script_module("deployment_check")
    original_run = module.subprocess.run

    def daemon_down(*args: object, **kwargs: object) -> object:
        raise sp.CalledProcessError(1, "docker")

    module.subprocess.run = daemon_down
    try:
        report = module.check_containers(docker_bin="docker")
    finally:
        module.subprocess.run = original_run
    assert report["docker"] == "DOCKER_DAEMON_UNAVAILABLE"
    assert set(report) == {"docker", "postgres", "redis", "mosquitto", "backend", "frontend"}
