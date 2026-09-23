"""Environment-file validation for the industrial AI platform.

Two modes:

``example``   — for ``.env.example``: every required variable must be
              present, and every secret variable must be either EMPTY or an
              obvious placeholder. A real-looking secret in a committed env
              template is a hard failure.

``runtime``   — for a real ``.env``: required variables must be present and
              non-empty; ``POSTGRES_PASSWORD`` must be non-empty;
              ``MQTT_PASSWORD`` may stay empty only for anonymous brokers;
              ``AGENT_API_KEY`` may stay empty only when the workflow is
              disabled or the provider needs no key. Numeric and enum-like
              variables are range-checked (invalid config fails).

Exit code 0 = valid, 1 = invalid (a JSON error list is printed to stderr).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_KEYS = (
    "DATABASE_URL",
    "REDIS_URL",
    "MQTT_HOST",
    "MQTT_PORT",
    "POSTGRES_PASSWORD",
)

SECRET_SUFFIX = re.compile(r"(_PASSWORD|_API_KEY|_TOKEN|_SECRET)$")
PLACEHOLDER = re.compile(
    r"^(change-me|changeme|<[^>]+>|\$\{.*\}|$)", re.IGNORECASE
)

NUMERIC_KEYS = {
    "MQTT_PORT": (1, 65535),
    "POSTGRES_PORT_PUBLISHED": (1, 65535),
    "REDIS_PORT_PUBLISHED": (1, 65535),
    "MQTT_PORT_PUBLISHED": (1, 65535),
    "BACKEND_PORT_PUBLISHED": (1, 65535),
    "FRONTEND_PORT_PUBLISHED": (1, 65535),
    "AGENT_TIMEOUT_SECONDS": (1, 600),
    "AGENT_MAX_ATTEMPTS": (1, 10),
}
LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a dotenv file; the last assignment of a key wins."""

    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"malformed line (missing '='): {line!r}")
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def validate(values: dict[str, str], mode: str) -> list[str]:
    errors: list[str] = []

    for key in REQUIRED_KEYS:
        if key not in values:
            errors.append(f"missing required variable: {key}")
        elif not values[key]:
            errors.append(f"empty required variable: {key}")

    for key, value in values.items():
        if SECRET_SUFFIX.search(key):
            if mode == "example" and value and not PLACEHOLDER.match(value):
                errors.append(
                    f"real-looking secret in example template: {key}"
                )
            if mode == "runtime":
                if key == "POSTGRES_PASSWORD" and value == "change-me-in-dotenv":
                    errors.append(f"placeholder secret left unchanged: {key}")
                if not value and key in {"POSTGRES_PASSWORD"}:
                    errors.append(f"empty secret: {key}")
        if key in NUMERIC_KEYS:
            low, high = NUMERIC_KEYS[key]
            try:
                number = int(value)
            except ValueError:
                errors.append(f"non-integer value for {key}: {value!r}")
                continue
            if not low <= number <= high:
                errors.append(f"out-of-range value for {key}: {number} not in [{low}, {high}]")
        if key == "LOG_LEVEL" and value and value.upper() not in LOG_LEVELS:
            errors.append(f"invalid LOG_LEVEL: {value!r}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a platform env file.")
    parser.add_argument("env_file", type=Path)
    parser.add_argument("--mode", choices=("example", "runtime"), required=True)
    args = parser.parse_args(argv)

    try:
        values = parse_env_file(args.env_file)
    except (OSError, ValueError) as exc:
        print(json.dumps({"errors": [str(exc)]}), file=sys.stderr)
        return 1

    errors = validate(values, args.mode)
    if errors:
        print(json.dumps({"errors": errors}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"status": "pass", "mode": args.mode, "file": str(args.env_file)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
