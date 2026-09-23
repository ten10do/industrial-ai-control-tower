"""Deployment validation for the industrial AI platform.

Checks, in order:

1. Containers — all five long-running services must be ``running`` according
   to the Docker CLI. When the Docker daemon is unavailable the script does
   not fake a result: it reports ``DOCKER_DAEMON_UNAVAILABLE`` and, unless
   ``--require-docker`` is passed, keeps validating the HTTP surface.
2. Health — ``GET /health`` must answer 200 ``{"status": "ok"}``.
3. Readiness — ``GET /ready`` must answer 200.
4. Database migration — ``alembic_version`` in the database must equal the
   head revision derived from ``backend/alembic/versions``.
5. Key APIs — ``/metrics`` (Prometheus exposition), ``/api/v1/platform/metrics``
   and ``/api/v1/incidents/dashboard`` (JSON).

Output is a single JSON object on stdout; the exit code is 0 when
``status`` is ``pass`` and 1 when it is ``fail``:

    {"status": "pass", "services": {"backend": "ok", ...}, "checks": {...}}
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

SERVICES = ("postgres", "redis", "mosquitto", "backend", "frontend")
DOCKER_DAEMON_UNAVAILABLE = "DOCKER_DAEMON_UNAVAILABLE"

DEFAULT_BACKEND_URL = "http://localhost:8000"
REPO_ROOT = Path(__file__).resolve().parents[1]


def fetch(url: str, timeout: float = 5.0) -> tuple[int, bytes | None, str | None]:
    """GET ``url``; return (status, body, content_type) or a synthetic 000."""

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, response.read(), response.headers.get("content-type")
    except urllib.error.HTTPError as exc:
        return exc.code, None, None
    except (urllib.error.URLError, OSError, TimeoutError):
        return 0, None, None


def check_health(backend_url: str) -> str:
    status, body, _ = fetch(f"{backend_url}/health")
    if status != 200:
        return "error"
    try:
        return "ok" if json.loads(body or b"{}").get("status") == "ok" else "error"
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "error"


def check_ready(backend_url: str) -> str:
    status, _, _ = fetch(f"{backend_url}/ready")
    return "ok" if status == 200 else "error"


def check_metrics(backend_url: str) -> str:
    status, body, content_type = fetch(f"{backend_url}/metrics")
    if status != 200 or not content_type or "text/plain" not in content_type:
        return "error"
    return "ok" if body and b"telemetry_ingest_total" in body else "error"


def check_platform_metrics(backend_url: str) -> str:
    status, body, _ = fetch(f"{backend_url}/api/v1/platform/metrics")
    if status != 200:
        return "error"
    try:
        payload = json.loads(body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "error"
    return "ok" if {"system", "pipeline", "incident"} <= set(payload) else "error"


def check_dashboard(backend_url: str) -> str:
    status, body, _ = fetch(f"{backend_url}/api/v1/incidents/dashboard")
    if status != 200:
        return "error"
    try:
        payload = json.loads(body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "error"
    return "ok" if "summary" in payload and "incidents" in payload else "error"


def check_containers(docker_bin: str = "docker") -> dict[str, str]:
    """Return per-service container states, or the daemon marker."""

    try:
        completed = subprocess.run(
            [docker_bin, "ps", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
    except FileNotFoundError:
        return {"docker": "unavailable", **{name: "unknown" for name in SERVICES}}
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return {"docker": DOCKER_DAEMON_UNAVAILABLE, **{name: "unknown" for name in SERVICES}}

    running: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = entry.get("Names") or entry.get("Name") or ""
        state = entry.get("State") or ""
        for service in SERVICES:
            if service in name:
                running[service] = "running" if state == "running" else state
    return {
        "docker": "ok",
        **{name: running.get(name, "absent") for name in SERVICES},
    }


def _migration_head(versions_dir: Path) -> str | None:
    """Derive the head revision from the alembic versions directory."""

    revisions: dict[str, str | None] = {}
    for path in versions_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        match = re.search(r"^revision(?::\s*str)?\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
        if not match:
            continue
        revision = match.group(1)
        down = re.search(r"^down_revision(?::[^=]*)?\s*=\s*(?:['\"]([^'\"]*)['\"]|None)", text, re.M)
        revisions[revision] = down.group(1) if down and down.group(1) else None

    referenced = {down for down in revisions.values() if down}
    heads = [revision for revision, down in revisions.items() if revision not in referenced]
    if len(heads) != 1:
        return None
    return heads[0]


def check_migration_head(database_url: str | None) -> str:
    """Compare the stored ``alembic_version`` with the derived head revision."""

    if not database_url:
        return "skipped"
    head = _migration_head(REPO_ROOT / "backend" / "alembic" / "versions")
    if head is None:
        return "error"

    try:
        import asyncio

        import asyncpg
    except ImportError:
        return "skipped"

    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )

    async def _read() -> str | None:
        conn = await asyncpg.connect(sync_url, timeout=5)
        try:
            return await conn.fetchval("SELECT version_num FROM alembic_version")
        finally:
            await conn.close()

    try:
        stored = asyncio.run(_read())
    except Exception:
        return "error"
    if stored is None:
        return "error"
    return "ok" if stored == head else f"drift:{stored}"


def run_check(args: argparse.Namespace) -> dict[str, object]:
    services = check_containers(args.docker_bin)
    docker_state = services.pop("docker", "unknown")

    http_checks = {
        "health": check_health(args.backend_url),
        "ready": check_ready(args.backend_url),
        "metrics": check_metrics(args.backend_url),
        "platform_metrics": check_platform_metrics(args.backend_url),
        "incidents_dashboard": check_dashboard(args.backend_url),
    }
    migration = check_migration_head(args.database_url)

    container_states = [
        state for name, state in services.items() if name in SERVICES
    ]
    containers_ok = all(state == "running" for state in container_states)
    containers_valid = containers_ok or (
        docker_state == DOCKER_DAEMON_UNAVAILABLE and not args.require_docker
    )

    passed = containers_valid and all(state == "ok" for state in http_checks.values()) and (
        migration in {"ok", "skipped"}
    )

    return {
        "status": "pass" if passed else "fail",
        "docker": docker_state,
        "services": services,
        "checks": {**http_checks, "migration_head": migration},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the platform deployment.")
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--docker-bin", default="docker")
    parser.add_argument(
        "--require-docker",
        action="store_true",
        help="Treat an unavailable Docker daemon as a failure.",
    )
    args = parser.parse_args(argv)

    report = run_check(args)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
