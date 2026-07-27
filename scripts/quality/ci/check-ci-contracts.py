#!/usr/bin/env python3
"""Validate clean-checkout inputs shared by local verification and CI."""

from __future__ import annotations

import ast
import json
import re
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
REQUIRED_ACTION_REFS = {
    "Azure/functions-action": "v1.5.6",
    "actions/attest": "v4.2.0",
    "actions/checkout": "v7.0.1",
    "actions/configure-pages": "v6.0.0",
    "actions/deploy-pages": "v5.0.0",
    "actions/download-artifact": "v8.0.1",
    "actions/github-script": "v9.0.0",
    "actions/setup-node": "v7.0.0",
    "actions/setup-python": "v7.0.0",
    "actions/upload-artifact": "v7.0.1",
    "actions/upload-pages-artifact": "v5.0.0",
    "astral-sh/setup-uv": "v8.3.2",
    "docker/build-push-action": "53b7df96c91f9c12dcc8a07bcb9ccacbed38856a",
    "docker/login-action": "abd2ef45e78c5afb21d64d4ca52ee8550d9572c7",
    "docker/setup-buildx-action": "bb05f3f5519dd87d3ba754cc423b652a5edd6d2c",
    "gitleaks/gitleaks-action": "v3.0.0",
    "hashicorp/setup-terraform": "v4.0.1",
    "pypa/gh-action-pip-audit": "v1.1.0",
    "pypa/gh-action-pypi-publish": "v1.14.1",
}
ACTION_REF_RE = re.compile(r"uses:\s*(?P<action>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@(?P<ref>[^\s#]+)")
UV_SETUP_BLOCK_RE = re.compile(r"(?ms)^\s+- name: Set up uv \(Python 3\.13\).*?(?=^\s+- name:|\Z)")
BASE_IMAGE_REGISTRY_ARG = "BASE_IMAGE_REGISTRY"
BASE_IMAGE_PREFIX = "${" + BASE_IMAGE_REGISTRY_ARG + "}/"


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


def _validate_base_images() -> list[str]:
    """Keep every external base image mirror-overridable and digest-pinned.

    A disconnected tenant builds from an internal registry mirror, so the
    registry host MUST be a build argument. The digest MUST stay in the file so
    the override can redirect where bytes come from but never which bytes are
    accepted.
    """
    errors: list[str] = []
    lines = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
    if not any(line.strip().startswith(f"ARG {BASE_IMAGE_REGISTRY_ARG}=") for line in lines):
        errors.append(f"Dockerfile must declare ARG {BASE_IMAGE_REGISTRY_ARG} with a default")
    stages: set[str] = set()
    for line in lines:
        parts = line.strip().split()
        if len(parts) < 2 or parts[0].upper() != "FROM":
            continue
        reference = parts[1]
        if len(parts) >= 4 and parts[2].upper() == "AS":
            stages.add(parts[3])
        if reference in stages:
            continue
        if not reference.startswith(BASE_IMAGE_PREFIX):
            errors.append(
                f"Dockerfile base image {reference} must be prefixed with {BASE_IMAGE_PREFIX}"
            )
        if "@sha256:" not in reference:
            errors.append(f"Dockerfile base image {reference} must be digest-pinned")
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


def _validate_python_test_partitioning() -> list[str]:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    runner = (REPO_ROOT / "scripts" / "quality" / "ci" / "run-python-tests.sh").read_text(
        encoding="utf-8"
    )
    required_workflow_fragments = (
        "pytest regression shard ${{ matrix.shard }}/3",
        "FDAI_PYTEST_MODE: coverage",
        "FDAI_PYTEST_MODE: integration",
        "behavior source citation precision",
    )
    errors = [
        f"ci.yml is missing partition contract: {fragment}"
        for fragment in required_workflow_fragments
        if fragment not in workflow
    ]
    for mode in ("all)", "full)", "coverage)", "integration)"):
        if mode not in runner:
            errors.append(f"run-python-tests.sh is missing mode branch: {mode}")
    return errors


def _validate_action_runtime_versions() -> list[str]:
    errors: list[str] = []
    for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        content = path.read_text(encoding="utf-8")
        relative = path.relative_to(REPO_ROOT)
        for match in ACTION_REF_RE.finditer(content):
            action = match.group("action")
            actual_ref = match.group("ref")
            expected_ref = REQUIRED_ACTION_REFS.get(action)
            if expected_ref is None:
                errors.append(f"{relative} uses unapproved remote action {action}@{actual_ref}")
            elif actual_ref != expected_ref:
                errors.append(f"{relative} uses {action}@{actual_ref}; expected {expected_ref}")
    return errors


def _validate_uv_cache_writers() -> list[str]:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    blocks = UV_SETUP_BLOCK_RE.findall(workflow)
    if not blocks:
        return ["ci.yml has no setup-uv cache blocks"]
    errors = [
        "every ci.yml setup-uv block must restore the shared cache"
        for block in blocks
        if "enable-cache: true" not in block
    ]
    writer_count = sum("save-cache: false" not in block for block in blocks)
    if writer_count != 1:
        errors.append(f"ci.yml must have exactly one setup-uv cache writer; found {writer_count}")
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
        *_validate_base_images(),
        *_validate_shared_runners(),
        *_validate_python_test_partitioning(),
        *_validate_action_runtime_versions(),
        *_validate_uv_cache_writers(),
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
