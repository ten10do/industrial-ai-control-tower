"""Secret scan behaviour: a real secret fails, a placeholder passes.

The scanner is deterministic and file-driven, so the interesting cases are
proved on temporary files rather than on the repository. The final test then
runs it against the repository itself, which is the assertion that actually
matters: the tree this phase commits must be clean.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Loaded by path rather than imported: ``scripts`` sits beside ``backend`` and
#: is not an installed package, and making it one would change how CI invokes it.
_SCANNER_PATH = REPO_ROOT / "scripts" / "security_scan.py"
_spec = importlib.util.spec_from_file_location("security_scan_under_test", _SCANNER_PATH)
assert _spec is not None and _spec.loader is not None
scanner: Any = importlib.util.module_from_spec(_spec)
#: Registered before execution so the dataclasses inside the module can resolve
#: their own ``__module__``.
sys.modules[_spec.name] = scanner
_spec.loader.exec_module(scanner)

is_placeholder = scanner.is_placeholder
looks_like_credential = scanner.looks_like_credential
scan_line = scanner.scan_line
scan_paths = scanner.scan_paths
scan_repository = scanner.scan_repository
scanner_main = scanner.main

#: Built at run time rather than written as literals. A realistic secret has to
#: exist somewhere for these tests to mean anything, and the one place it must
#: not exist is a tracked file: the repository sweep at the end of this module
#: would find it, and the scanner would be reporting its own fixture. The
#: visible prefixes are kept under the scanner's 16-character floor so these two
#: definitions are themselves invisible to it.
REAL_API_KEY = "sk-d1cf" + uuid4().hex + uuid4().hex
REAL_PASSWORD = "SuperSecret" + uuid4().hex

#: A separator-free all-caps token, assembled at run time for exactly the same
#: reason as ``REAL_API_KEY``: written as a literal it would itself be a finding
#: in this file, which the repository sweep below would then report.
BASE32_SECRET = "MZXW" + uuid4().hex.upper()[:28]


def _write(directory: Path, name: str, content: str) -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Line level
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "line",
    [
        f"AGENT_API_KEY={REAL_API_KEY}",
        f"POSTGRES_PASSWORD={REAL_PASSWORD}",
        f'JWT_SECRET_KEY = "{REAL_API_KEY}"',
        f"AUTH_TOKEN: {REAL_API_KEY}",
    ],
)
def test_a_real_secret_assignment_is_reported(line: str) -> None:
    assert scan_line(line), f"expected a finding for: {line}"


def test_a_credential_inside_a_connection_string_is_reported() -> None:
    findings = scan_line(f'url = "postgresql://ops:{REAL_PASSWORD}@db:5432/app"')

    assert findings == [("url", "://ops:***@")]


@pytest.mark.parametrize(
    "line",
    [
        "POSTGRES_PASSWORD=change-me-in-dotenv",
        "AGENT_API_KEY=",
        "SECURITY_JWT_SECRET=",
        "MQTT_PASSWORD=",
        "API_KEY=<your-api-key>",
        "TOKEN=${SERVICE_TOKEN:-}",
        "PASSWORD=example",
        "DATABASE_URL=postgresql://postgres:change-me-in-dotenv@localhost:5432/app",
    ],
)
def test_a_placeholder_or_an_empty_value_passes(line: str) -> None:
    assert scan_line(line) == [], f"expected no finding for: {line}"


@pytest.mark.parametrize(
    "line",
    [
        "password_hash=password_hash",
        "password: str",
        "api_key = settings.agent_api_key",
        'SECRET_MATERIAL_REJECTED = "SECRET_MATERIAL_REJECTED"',
        "token_ttl_seconds: int = 3600",
        "# PASSWORD is injected from outside the repository",
    ],
)
def test_code_rather_than_a_literal_passes(line: str) -> None:
    assert scan_line(line) == [], f"expected no finding for: {line}"


def test_the_entropy_floor_is_what_separates_a_name_from_a_secret() -> None:
    assert looks_like_credential(REAL_API_KEY) is True
    assert looks_like_credential("aaaaaaaaaaaaaaaa") is False
    assert looks_like_credential("short") is False


def test_a_long_identifier_is_excluded_by_its_shape_rather_than_its_entropy() -> None:
    """The two rules are separate on purpose, and this is why.

    ``some_variable_name`` clears the entropy floor, so entropy alone would
    report it. It is the all-lowercase-snake shape rule that keeps it out of the
    findings. Stating that here means the next person to touch the scanner knows
    which rule is load bearing.
    """

    assert looks_like_credential("some_variable_name") is True
    assert scan_line("db_password = some_variable_name") == []


def test_an_environment_variable_name_is_excluded_but_a_base32_secret_is_not() -> None:
    """A name and a secret can look alike; the separator is what separates them.

    ``SECURITY_BOOTSTRAP_PASSWORD`` is the name ``os.environ`` is asked for, so
    reporting it would be noise. A separator-free all-caps string is what a
    base32 secret looks like, so it must still be reported. This test is the
    boundary of the SCREAMING_SNAKE clause: it exists to keep the next person
    from widening that rule into "anything in capitals is a name".
    """

    assert scan_line('PASSWORD_ENV = "SECURITY_BOOTSTRAP_PASSWORD"') == []
    assert looks_like_credential("SECURITY_BOOTSTRAP_PASSWORD") is True
    assert scan_line(f'api_key = "{BASE32_SECRET}"') == [("assignment", "api_key")]


def test_the_placeholder_allow_list_covers_the_shipped_template() -> None:
    assert is_placeholder("change-me-in-dotenv") is True
    assert is_placeholder("") is True
    assert is_placeholder("${POSTGRES_PASSWORD:-change-me}") is True
    assert is_placeholder(REAL_PASSWORD) is False


# --------------------------------------------------------------------------- #
# File level
# --------------------------------------------------------------------------- #


def test_a_file_with_a_real_secret_fails(tmp_path: Path) -> None:
    bad = _write(tmp_path, "settings.py", f'API_KEY = "{REAL_API_KEY}"\n')

    findings = scan_paths([bad], tmp_path)

    assert [finding.rule for finding in findings] == ["assignment"]


def test_a_file_with_only_placeholders_passes(tmp_path: Path) -> None:
    good = _write(
        tmp_path,
        ".env.example",
        "POSTGRES_PASSWORD=change-me-in-dotenv\nAGENT_API_KEY=\nTOKEN=${TOKEN:-}\n",
    )

    assert scan_paths([good], tmp_path) == []


def test_a_non_scannable_file_is_skipped(tmp_path: Path) -> None:
    binary = _write(tmp_path, "archive.bin", f"API_KEY={REAL_API_KEY}\n")

    assert scan_paths([binary], tmp_path) == []


def test_the_cli_exits_non_zero_when_a_secret_is_present(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path, "config.yaml", f"api_key: {REAL_API_KEY}\n")

    code = scanner_main(["--root", str(tmp_path), "--path", str(tmp_path / "config.yaml")])

    assert code == 1
    assert '"finding_count": 1' in capsys.readouterr().out


def test_the_cli_exits_zero_on_a_clean_tree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path, "config.yaml", "api_key: ${API_KEY:-placeholder}\n")

    code = scanner_main(["--root", str(tmp_path), "--path", str(tmp_path / "config.yaml")])

    assert code == 0
    assert '"status": "clean"' in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# The repository itself
# --------------------------------------------------------------------------- #


def test_the_repository_contains_no_literal_credential() -> None:
    """The gate that matters: the committed tree must scan clean."""

    findings = scan_repository(REPO_ROOT)

    assert findings == [], f"literal credentials found: {[f.as_dict() for f in findings]}"
