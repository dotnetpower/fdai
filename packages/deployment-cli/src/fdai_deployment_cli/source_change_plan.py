"""Classify a clean Git diff into the narrowest safe source deployment lane."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.image_targets import select_image_targets
from fdai_deployment_cli.runtime_release import RUNTIME_SERVICES

_COMMIT = re.compile(r"[0-9a-f]{40}")
_MAX_CHANGED_PATHS = 20_000
_HIGHER_LANE_PREFIXES = (
    "alembic/",
    "infra/",
    "lifecycle/",
    "packages/deployment-cli/",
    "scripts/deployment/azure/",
    "service-migrations/",
)
_HIGHER_LANE_EXACT = frozenset({"alembic.ini", "azure.yaml"})
_NO_DEPLOY_PREFIXES = (
    ".github/",
    ".vscode/",
    "docs/",
    "examples/",
    "mocks/",
    "site/",
    "tests/",
    "tools/",
)
_RUNTIME_EXCEPTION_PATHS = frozenset({"docs/internals/sregym-absorption-ledger.json"})
_RUNTIME_EXCEPTION_PREFIXES = ("services/core-control-plane/tests/scenarios/",)


def source_change_plan(
    changed_paths: Iterable[str],
    *,
    base_commit: str,
    head_commit: str,
) -> dict[str, object]:
    """Return a no-effect deployment route for one exact commit range."""
    if _COMMIT.fullmatch(base_commit) is None or _COMMIT.fullmatch(head_commit) is None:
        raise ValueError("source change plan requires exact commit ids")
    paths = tuple(sorted({path.removeprefix("./") for path in changed_paths if path}))
    if len(paths) > _MAX_CHANGED_PATHS or any(
        path.startswith("/") or ".." in Path(path).parts or "\x00" in path for path in paths
    ):
        raise ValueError("source change plan paths are invalid or exceed their bound")
    runtime_paths = tuple(path for path in paths if not _is_no_deploy_path(path))

    higher_lane = tuple(
        path
        for path in runtime_paths
        if path in _HIGHER_LANE_EXACT or path.startswith(_HIGHER_LANE_PREFIXES)
    )
    console_paths = tuple(path for path in runtime_paths if path.startswith("console/"))
    image_targets = select_image_targets(runtime_paths)
    unsupported = tuple(
        target.target
        for target in image_targets
        if target.service not in RUNTIME_SERVICES or target.target != target.service
    )
    services = tuple(
        target.service
        for target in image_targets
        if target.service in RUNTIME_SERVICES and target.target == target.service
    )
    services = tuple(dict.fromkeys(services))

    if higher_lane:
        lane, reason = "higher-lane-required", "deployment_contract_changed"
    elif unsupported:
        lane, reason = "full-release-required", "unsupported_hot_path_target"
    elif console_paths and services:
        lane, reason = "split-update-required", "console_and_service_changed"
    elif console_paths:
        lane, reason = "console-update", "console_changed"
    elif len(services) == 1:
        lane, reason = "single-service-update", "one_service_changed"
    elif len(services) > 1:
        lane, reason = "multi-service-update", "multiple_services_changed"
    elif paths and not runtime_paths:
        lane, reason = "no-deploy", "non_runtime_files_changed"
    elif paths:
        lane, reason = "higher-lane-required", "unclassified_runtime_impact"
    else:
        lane, reason = "no-deploy", "no_files_changed"

    result: dict[str, object] = {
        "schema_version": "fdai.source-change-plan.v1",
        "base_commit": base_commit,
        "head_commit": head_commit,
        "lane": lane,
        "reason_code": reason,
        "changed_path_count": len(paths),
        "changed_paths_digest": canonical_digest({"paths": list(paths)}),
        "services": list(services),
        "image_targets": [target.target for target in image_targets],
        "unsupported_hot_path_targets": list(unsupported),
        "console_changed": bool(console_paths),
        "higher_lane_paths": list(higher_lane),
        "mutation_performed": False,
        "deployment_ready": False,
    }
    result["plan_digest"] = canonical_digest(result)
    return result


def plan_git_changes(source_root: Path, base: str, head: str = "HEAD") -> dict[str, object]:
    """Resolve an exact local diff and classify it without contacting Azure."""
    root = source_root.resolve(strict=True)
    if root.is_symlink():
        raise ValueError("source change plan requires a non-symlink checkout")
    base_commit = _git(root, "rev-parse", "--verify", f"{base}^{{commit}}").strip()
    head_commit = _git(root, "rev-parse", "--verify", f"{head}^{{commit}}").strip()
    if _COMMIT.fullmatch(base_commit) is None or _COMMIT.fullmatch(head_commit) is None:
        raise ValueError("source change plan could not resolve exact commits")
    output = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "diff",
            "--name-only",
            "-z",
            "--diff-filter=ACMRD",
            base_commit,
            head_commit,
        ],
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout
    paths = [value.decode("utf-8") for value in output.split(b"\0") if value]
    return source_change_plan(paths, base_commit=base_commit, head_commit=head_commit)


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout


def _is_no_deploy_path(path: str) -> bool:
    if path in _RUNTIME_EXCEPTION_PATHS or path.startswith(_RUNTIME_EXCEPTION_PREFIXES):
        return False
    return path.startswith(_NO_DEPLOY_PREFIXES) or "/tests/" in path or "/docs/" in path
