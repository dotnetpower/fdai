#!/usr/bin/env python3
"""Validate clean-checkout inputs shared by local verification and CI."""

from __future__ import annotations

import ast
import json
import shlex
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
REQUIRED_TRACKED_PATHS = (
    "scripts/lib/framework-surface.txt",
    "console/package-lock.json",
    "cli/package-lock.json",
)
SHARED_RUNNERS = (
    "scripts/quality/ci/run-python-tests.sh",
    "scripts/quality/ci/run-operator-surfaces.sh",
)
RUNNER_ENTRY_POINTS = (
    ".github/workflows/ci.yml",
    "Makefile",
    "scripts/verify.sh",
)


def _tracked_paths() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return {path for path in result.stdout.decode().split("\0") if path}


def _docker_copy_sources() -> tuple[str, ...]:
    sources: list[str] = []
    logical_line = ""
    for raw_line in (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        logical_line = f"{logical_line} {stripped}".strip()
        if logical_line.endswith("\\"):
            logical_line = logical_line[:-1].rstrip()
            continue
        parts = shlex.split(logical_line)
        logical_line = ""
        if (
            not parts
            or parts[0].upper() != "COPY"
            or any(part.startswith("--from=") for part in parts[1:])
        ):
            continue
        operands = [part for part in parts[1:] if not part.startswith("--")]
        sources.extend(operands[:-1])
    return tuple(sources)


def _validate_build_context() -> list[str]:
    errors: list[str] = []
    tracked = _tracked_paths()
    for path in REQUIRED_TRACKED_PATHS:
        if path not in tracked:
            errors.append(f"required clean-checkout input is not tracked: {path}")

    docker_sources = _docker_copy_sources()
    for source in docker_sources:
        if any(character in source for character in "*?["):
            continue
        if not (REPO_ROOT / source.rstrip("/")).exists():
            errors.append(f"Dockerfile COPY source is missing: {source}")

    dockerignore = {
        line.strip()
        for line in (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    if "tests/" in dockerignore:
        errors.append(".dockerignore must not exclude tests/ before its scenarios exception")
    for rule in ("tests/*", "!tests/scenarios/"):
        if rule not in dockerignore:
            errors.append(f".dockerignore is missing required rule: {rule}")

    manifest_path = REPO_ROOT / "resolved-models.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"resolved-models.json is not valid JSON: {exc}")
        else:
            if not isinstance(manifest, dict) or not isinstance(manifest.get("capabilities"), list):
                errors.append("resolved-models.json must be an object with a capabilities array")
    return errors


def _validate_shared_runners() -> list[str]:
    errors: list[str] = []
    for entry_point in RUNNER_ENTRY_POINTS:
        content = (REPO_ROOT / entry_point).read_text(encoding="utf-8")
        for runner in SHARED_RUNNERS:
            if runner not in content:
                errors.append(f"{entry_point} does not delegate to {runner}")
        if "--cov=src/fdai/core" in content:
            errors.append(f"{entry_point} duplicates the safety-core coverage target list")
    return errors


def _contains_guard_call(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id == "_requires_live_db"
        for child in ast.walk(node)
    )


def _validate_live_db_guards() -> list[str]:
    errors: list[str] = []
    for path in sorted((REPO_ROOT / "tests/persistence").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_requires_live_db"
            for node in tree.body
        ):
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_") or not _contains_guard_call(node):
                continue
            executable_body = node.body
            if (
                executable_body
                and isinstance(executable_body[0], ast.Expr)
                and isinstance(executable_body[0].value, ast.Constant)
                and isinstance(executable_body[0].value.value, str)
            ):
                executable_body = executable_body[1:]
            if not executable_body or not _contains_guard_call(executable_body[0]):
                relative = path.relative_to(REPO_ROOT)
                errors.append(f"{relative}:{node.lineno} must call _requires_live_db() first")
    return errors


def main() -> int:
    errors = [
        *_validate_build_context(),
        *_validate_shared_runners(),
        *_validate_live_db_guards(),
    ]
    if errors:
        for error in errors:
            print(f"ci-contracts: ERROR: {error}")
        return 1
    print("ci-contracts: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
