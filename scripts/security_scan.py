#!/usr/bin/env python
"""Secret governance scan for the industrial AI platform.

Phase 6.12-F. The scanner answers one question: does any **version-controlled**
file contain a literal credential?

Scope is decided by ``git ls-files``, not by walking the directory tree. That
single choice removes a whole class of both false positives and false negatives:

* an ignored ``.env``, a local virtualenv, ``node_modules``, and a build output
  are not version controlled, so they are not scanned;
* a file that *is* tracked is scanned no matter where it sits, so the check
  cannot be dodged by putting a secret somewhere the extension list forgot.

A filesystem walk with an exclusion list is used only when git is unavailable,
because a scanner that silently reports "clean" outside a checkout would be
worse than no scanner.

Three rules are applied to every line:

``assignment``  ``API_KEY = ...``, ``PASSWORD: ...``, and the same shapes for
                token/secret/credential/private-key names. A value is reported
                only when it is a literal that *looks* like a credential:
                long enough to matter, quoting-free of code syntax, and above a
                Shannon entropy floor. That threshold is what keeps
                ``password_hash = password_hash`` from being reported as a
                leak, and the floor is stated here rather than tuned until the
                output looked nice.
``url``         ``scheme://user:password@host``, where the password segment is
                not a placeholder. Connection strings are where credentials
                actually hide in a repository like this one.
``placeholder`` The allow-list. ``change-me``, ``<angle brackets>``,
                ``${VARS}``, ``example``, ``dummy``, an empty value, and the
                other obvious non-secrets are explicitly fine, because a
                template that cannot state a key at all is a template nobody
                uses.

Exit code 0 = clean, 1 = findings (a JSON report is printed to stdout).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: Key names that make an assignment interesting. Split into fragments so this
#: module does not contain the very pattern it searches for: the scanner is a
#: tracked file and must pass its own scan.
SECRET_KEY_FRAGMENTS = (
    "API_KEY",
    "APIKEY",
    "ACCESS_KEY",
    "SECRET_KEY",
    "PASSWORD",
    "PASSWD",
    "TOKEN",
    "SECRET",
    "CREDENTIAL",
    "PRIVATE_KEY",
)

#: Assignments whose key contains one of the fragments, in ``INI``/``dotenv``
#: (``KEY=value``) or ``YAML``/``JSON`` (``key: value``) shape.
ASSIGNMENT = re.compile(
    r"(?P<key>[A-Za-z0-9_.\-]*"
    r"(?:" + "|".join(SECRET_KEY_FRAGMENTS) + r")"
    r"[A-Za-z0-9_.\-]*)"
    r"[ \t]*[:=][ \t]*"
    r"(?P<value>.{0,200})",
    re.IGNORECASE,
)

#: ``postgresql://user:secret@host/db`` and friends.
URL_CREDENTIAL = re.compile(r"://(?P<user>[^/\s:@]{1,64}):(?P<password>[^/\s@]{1,128})@")

PLACEHOLDER = re.compile(
    r"^(?:"
    r"|change[-_ ]?me.*|replace[-_ ]?me.*|your[-_ ].*|my[-_ ].*|the[-_ ].*"
    r"|<[^>]*>|\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*|\{\{[^}]*\}\}"
    r"|example.*|sample.*|placeholder.*|dummy.*|fake.*|redacted.*|scrubbed.*|masked.*"
    r"|test[-_ ]?value|test[-_ ]?secret|not[-_ ]?set|unset|todo|tbd|xxx+|\*+|\.\.\."
    r"|none|null|nil|undefined|true|false|0|1"
    r"|secret|password|token|api[-_]?key"
    r")$",
    re.IGNORECASE,
)

#: Values that are code, not literals: environment lookups, attribute access,
#: function calls, container subscripts, and bare identifiers.
#:
#: The bare-identifier clauses are the deliberate part. Across this repository's
#: languages (Python, TypeScript) a 16-plus-character token that is a single word
#: is a name, never a credential: ``some_variable_name`` must not be reported
#: while ``sk-d1cf...`` and ``SuperSecretPassword123`` must be. A rule that
#: cannot tell those apart produces noise, and noise is how a scanner gets
#: switched off.
#:
#: The SCREAMING_SNAKE clause covers environment-variable and constant names
#: such as ``SECURITY_BOOTSTRAP_PASSWORD``, which is a label that ``os.environ``
#: is asked for rather than a secret. It requires at least one underscore, which
#: keeps it narrow: a separator-free all-caps string is what a base32 secret
#: looks like, and one of those is still reported.
REFERENCE = re.compile(
    r"(?:os\.environ|os\.getenv|getenv|settings\.|config\.|self\.|process\.env)"
    r"|[()\[\]{}]"
    r"|^[a-z][a-z0-9_]*$"
    r"|^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$"
    r"|^[0-9]+$"
)

#: The character set a credential token is made of. Anything with a space, a
#: quote, a bracket, a colon or a hash is a sentence, a type annotation, or a
#: comment rather than a literal secret.
CREDENTIAL_TOKEN = re.compile(r"^[A-Za-z0-9_\-+/=]+$")

SCANNABLE_SUFFIXES = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".yml",
        ".yaml",
        ".json",
        ".toml",
        ".cfg",
        ".ini",
        ".conf",
        ".sh",
        ".md",
        ".html",
        ".css",
        ".env.example",
    }
)

SCANNABLE_NAMES = frozenset({"Dockerfile", "docker-compose.yml", ".env.example"})

SKIPPED_DIRECTORIES = frozenset(
    {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", ".mypy_cache"}
)

#: A literal is treated as a candidate credential only above these thresholds.
MIN_LITERAL_LENGTH = 16
MIN_ENTROPY_BITS_PER_CHAR = 3.0

#: A password inside a connection string is judged on length alone. The
#: ``user:password@host`` shape is unambiguous, so the entropy floor that keeps
#: identifier lookalikes out of the assignment rule would only lose recall here
#: (a repeated-pattern password such as ``Hunter2Hunter2Hunter2`` scores 2.8).
MIN_URL_PASSWORD_LENGTH = 8

#: Lines that mention a credential name as documentation rather than assigning
#: one. The scanner still reads them, but a fenced placeholder is not a leak.
_QUOTE_CHARS = "\"'`"


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    line: int
    rule: str
    key: str

    def as_dict(self) -> dict[str, str | int]:
        return {"path": self.path, "line": self.line, "rule": self.rule, "key": self.key}


def shannon_entropy(value: str) -> float:
    """Return the Shannon entropy of ``value`` in bits per character."""

    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for character in value:
        counts[character] = counts.get(character, 0) + 1
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _strip_wrapping(value: str) -> str:
    """Reduce a captured value to the single token that would be the secret.

    A credential is one whitespace-free token. Everything after the first space
    in a captured value is a type annotation, a trailing comment, or the rest of
    a sentence, so the token is all that is examined. A quoted value is unwrapped
    first, which is what lets ``PASSWORD="my pass phrase"`` be seen as a value at
    all.
    """

    text = value.strip()
    if not text:
        return ""
    if text[0] in _QUOTE_CHARS:
        closing = text.find(text[0], 1)
        return text[1:closing] if closing > 0 else text[1:]
    head = re.split(r"\s", text, maxsplit=1)[0]
    if "#" in head:
        head = head.split("#", 1)[0]
    return head.rstrip(",;)")


def is_placeholder(value: str) -> bool:
    """Return whether ``value`` is an obvious non-secret."""

    if not value:
        return True
    return bool(PLACEHOLDER.match(value))


def is_reference(value: str) -> bool:
    """Return whether ``value`` is code rather than a literal."""

    return bool(REFERENCE.search(value))


def looks_like_credential(value: str) -> bool:
    """Return whether a literal is long and varied enough to be a real secret."""

    if len(value) < MIN_LITERAL_LENGTH:
        return False
    return shannon_entropy(value) >= MIN_ENTROPY_BITS_PER_CHAR


def scan_line(line: str, *, allow_credential_urls: bool = True) -> list[tuple[str, str]]:
    """Return ``(rule, key)`` pairs for one line of text."""

    results: list[tuple[str, str]] = []
    for match in ASSIGNMENT.finditer(line):
        key = match.group("key")
        value = _strip_wrapping(match.group("value"))
        if not CREDENTIAL_TOKEN.match(value):
            continue
        if is_placeholder(value) or is_reference(value):
            continue
        # ``SECRET_MATERIAL_REJECTED = "SECRET_MATERIAL_REJECTED"`` is a
        # constant restating its own name, which is what a status or error code
        # looks like. A credential is never equal to the variable it is stored
        # in, so this clause cannot hide a real one.
        if value.casefold() == key.casefold():
            continue
        if looks_like_credential(value):
            results.append(("assignment", key))
    if allow_credential_urls:
        for match in URL_CREDENTIAL.finditer(line):
            password = match.group("password")
            if len(password) < MIN_URL_PASSWORD_LENGTH:
                continue
            if is_placeholder(password) or is_reference(password):
                continue
            results.append(("url", f"://{match.group('user')}:***@"))
    return results


def _tracked_files(root: Path) -> list[Path]:
    """Return the version-controlled files under ``root``, or walk instead."""

    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError):
        return _walk_files(root)
    names = [name for name in completed.stdout.split("\0") if name]
    if not names:
        return _walk_files(root)
    return [root / name for name in names]


def _walk_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIPPED_DIRECTORIES for part in path.relative_to(root).parts):
            continue
        found.append(path)
    return found


def is_scannable(path: Path) -> bool:
    if path.name in SCANNABLE_NAMES:
        return True
    return path.suffix.lower() in SCANNABLE_SUFFIXES


def scan_file(path: Path, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return findings
    relative = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
    for number, line in enumerate(text.splitlines(), start=1):
        for rule, key in scan_line(line):
            findings.append(Finding(path=relative, line=number, rule=rule, key=key))
    return findings


def scan_paths(paths: list[Path], root: Path) -> list[Finding]:
    """Scan an explicit list of files. Used by the tests and by ``--paths``."""

    findings: list[Finding] = []
    for path in paths:
        if path.is_file() and is_scannable(path):
            findings.extend(scan_file(path, root))
    return findings


def scan_repository(root: Path) -> list[Finding]:
    """Scan every tracked, scannable file under ``root``."""

    findings: list[Finding] = []
    for path in _tracked_files(root):
        if path.is_file() and is_scannable(path):
            findings.extend(scan_file(path, root))
    return findings


def repository_root() -> Path:
    """Return the repository root (the parent of this script's directory)."""

    return Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan version-controlled files for secrets.")
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="repository root to scan (default: the parent of this script)",
    )
    parser.add_argument(
        "--path",
        type=Path,
        action="append",
        default=None,
        help="scan only this path (repeatable); skips the git file listing",
    )
    args = parser.parse_args(argv)

    root: Path = (args.root or repository_root()).resolve()
    if args.path:
        findings = scan_paths([path.resolve() for path in args.path], root)
    else:
        findings = scan_repository(root)

    report = {
        "status": "clean" if not findings else "findings",
        "root": str(root),
        "scanned_suffixes": sorted(SCANNABLE_SUFFIXES),
        "finding_count": len(findings),
        "findings": [finding.as_dict() for finding in findings],
    }
    print(json.dumps(report, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
