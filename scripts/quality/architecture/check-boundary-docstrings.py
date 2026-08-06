#!/usr/bin/env python3
"""Report structured architectural boundary docstring gaps in reviewed scopes."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_SCOPES = "scripts/quality/architecture/.boundary-docstring-scopes"
_DEFAULT_EXCLUSIONS = "scripts/quality/architecture/.boundary-docstring-exclusions"
_REQUIRED_SECTIONS = (
    "Responsibility",
    "Boundary",
    "Authority and state",
    "Dependencies",
    "Deployment",
)


@dataclass(frozen=True, slots=True)
class Scope:
    mode: str
    path: str
    justification: str


@dataclass(frozen=True, slots=True)
class Exclusion:
    path: str
    justification: str


class ConfigError(ValueError):
    """A reviewed scope or exclusion file is malformed."""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--scopes", default=_DEFAULT_SCOPES)
    parser.add_argument("--exclusions", default=_DEFAULT_EXCLUSIONS)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        scopes = _load_scopes(root / args.scopes)
        exclusions = _load_exclusions(root / args.exclusions)
    except ConfigError as exc:
        print(f"check-boundary-docstrings: invalid configuration: {exc}")
        return 2

    scope_paths = {scope.path for scope in scopes}
    stale: list[str] = []
    findings: list[tuple[Scope, tuple[str, ...]]] = []
    used_exclusions: set[str] = set()
    for scope in scopes:
        path = root / scope.path
        if not path.is_file():
            stale.append(f"{scope.path}: reviewed scope file is missing")
            continue
        gaps = _docstring_gaps(path)
        if scope.path in exclusions:
            if gaps:
                used_exclusions.add(scope.path)
            else:
                stale.append(f"{scope.path}: exclusion is no longer needed")
            continue
        if gaps:
            findings.append((scope, gaps))

    for path in exclusions:
        if path not in scope_paths:
            stale.append(f"{path}: exclusion is outside reviewed scopes")
        elif not (root / path).is_file():
            stale.append(f"{path}: excluded file is missing")
        elif path not in used_exclusions and not any(item.startswith(path) for item in stale):
            stale.append(f"{path}: exclusion is stale")

    enforced = 0
    reported = 0
    for scope, gaps in findings:
        label = "ERROR" if scope.mode == "enforce" else "WARNING"
        print(f"boundary-docstring: {label}: {scope.path}: {', '.join(gaps)}")
        if scope.mode == "enforce":
            enforced += 1
        else:
            reported += 1
    for message in sorted(set(stale)):
        print(f"boundary-docstring: ERROR: stale exclusion: {message}")
    if enforced or stale:
        print(
            "check-boundary-docstrings: FAILED "
            f"(enforced={enforced} reported={reported} stale={len(set(stale))})"
        )
        return 1
    print(
        "check-boundary-docstrings: OK "
        f"(reviewed={len(scopes)} reported={reported} excluded={len(used_exclusions)})"
    )
    return 0


def _docstring_gaps(path: Path) -> tuple[str, ...]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return ("module cannot be parsed",)
    docstring = ast.get_docstring(tree, clean=False)
    if not docstring or not docstring.strip():
        return ("module docstring is missing or empty",)
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in docstring.splitlines():
        stripped = raw.strip()
        match = next(
            (
                section
                for section in _REQUIRED_SECTIONS
                if stripped.casefold() == f"{section}:".casefold()
            ),
            None,
        )
        if match is not None:
            current = match
            sections.setdefault(match, [])
        elif current is not None:
            sections[current].append(stripped)
    gaps: list[str] = []
    for section in _REQUIRED_SECTIONS:
        if section not in sections:
            gaps.append(f"missing section '{section}'")
        elif not any(sections[section]):
            gaps.append(f"empty section '{section}'")
    return tuple(gaps)


def _load_scopes(path: Path) -> tuple[Scope, ...]:
    if not path.is_file():
        raise ConfigError(f"scope file is missing: {path}")
    records: list[Scope] = []
    for line_number, content, justification in _reviewed_lines(path):
        parts = content.split("|", 1)
        if len(parts) != 2 or parts[0] not in {"report", "enforce"} or not parts[1]:
            raise ConfigError(f"{path}:{line_number}: expected report|path or enforce|path")
        records.append(Scope(parts[0], _safe_path(parts[1], path, line_number), justification))
    if len({record.path for record in records}) != len(records):
        raise ConfigError(f"{path}: duplicate reviewed path")
    return tuple(records)


def _load_exclusions(path: Path) -> dict[str, Exclusion]:
    if not path.exists():
        return {}
    records: dict[str, Exclusion] = {}
    for line_number, content, justification in _reviewed_lines(path):
        relative = _safe_path(content, path, line_number)
        if relative in records:
            raise ConfigError(f"{path}:{line_number}: duplicate exclusion")
        records[relative] = Exclusion(relative, justification)
    return records


def _reviewed_lines(path: Path) -> tuple[tuple[int, str, str], ...]:
    records: list[tuple[int, str, str]] = []
    comments: list[str] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw.strip()
        if not stripped:
            comments.clear()
            continue
        if stripped.startswith("#"):
            comments.append(stripped.removeprefix("#").strip())
            continue
        if not comments or not any(comments):
            raise ConfigError(f"{path}:{line_number}: entry requires a preceding justification")
        records.append((line_number, stripped, " ".join(comments)))
        comments.clear()
    return tuple(records)


def _safe_path(value: str, source: Path, line_number: int) -> str:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.suffix != ".py":
        raise ConfigError(f"{source}:{line_number}: expected a safe relative Python path")
    return candidate.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
