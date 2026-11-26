"""Repository-tool steps run by the full catalog validator."""

from __future__ import annotations

import re
import sys
from typing import Any

from .common import (
    ACTION_TYPES_DIR,
    CATALOG_DIRS,
    PROFILES_DIR,
    REMEDIATION_DIR,
    REPO_ROOT,
    Runner,
    StepResult,
    run_subprocess,
)


def step_env_snapshot(runner: Runner) -> StepResult:
    stats: dict[str, Any] = {
        "python_version": sys.version.split()[0],
        "cwd": str(REPO_ROOT),
    }
    for command, key in [
        (["git", "rev-parse", "HEAD"], "repo_head_sha"),
        (["git", "status", "--porcelain"], "repo_dirty_files"),
    ]:
        return_code, output = run_subprocess(command)
        if return_code == 0:
            stats[key] = output.strip().splitlines() if key.endswith("files") else output.strip()
    counts = {}
    for root in CATALOG_DIRS:
        if root.is_dir():
            counts[str(root.relative_to(REPO_ROOT))] = sum(1 for _ in root.rglob("*.yaml"))
    counts[str(PROFILES_DIR.relative_to(REPO_ROOT))] = (
        sum(1 for _ in PROFILES_DIR.rglob("*.yaml")) if PROFILES_DIR.is_dir() else 0
    )
    counts[str(ACTION_TYPES_DIR.relative_to(REPO_ROOT))] = (
        sum(1 for _ in ACTION_TYPES_DIR.glob("*.yaml")) if ACTION_TYPES_DIR.is_dir() else 0
    )
    counts[str(REMEDIATION_DIR.relative_to(REPO_ROOT))] = (
        sum(1 for _ in REMEDIATION_DIR.rglob("*.yaml")) if REMEDIATION_DIR.is_dir() else 0
    )
    stats["catalog_yaml_counts"] = counts
    return StepResult(name="env_snapshot", ok=True, duration_s=0.0, stats=stats)


def step_hygiene_gates(runner: Runner) -> StepResult:
    scripts = [
        "scripts/quality/repository/check-punctuation.sh",
        "scripts/quality/repository/check-guids.sh",
        "scripts/quality/localization/check-translations.sh",
        "scripts/quality/architecture/check-core-imports.sh",
        "scripts/quality/localization/check-catalog-parity.sh",
    ]
    findings: list[str] = []
    for script in scripts:
        return_code, output = run_subprocess(["bash", script])
        if return_code != 0:
            findings.append(f"{script}: rc={return_code}\n{output.strip()}")
    return StepResult(
        name="hygiene_gates",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={"gates": len(scripts)},
    )


def step_ruff_check(runner: Runner) -> StepResult:
    return_code, output = run_subprocess([".venv/bin/ruff", "check", "."])
    return StepResult(
        name="ruff_check",
        ok=return_code == 0,
        duration_s=0.0,
        findings=[output.strip()] if return_code != 0 else [],
    )


def step_ruff_format(runner: Runner) -> StepResult:
    return_code, output = run_subprocess([".venv/bin/ruff", "format", "--check", "."])
    return StepResult(
        name="ruff_format",
        ok=return_code == 0,
        duration_s=0.0,
        findings=[output.strip()] if return_code != 0 else [],
    )


def step_mypy_src(runner: Runner) -> StepResult:
    return_code, output = run_subprocess(
        [".venv/bin/mypy", "src"], log_path=runner.report_dir / "mypy.out"
    )
    return StepResult(
        name="mypy_src",
        ok=return_code == 0,
        duration_s=0.0,
        findings=[output.strip()[-4000:]] if return_code != 0 else [],
    )


def step_pytest_full(runner: Runner) -> StepResult:
    return_code, output = run_subprocess(
        [".venv/bin/pytest", "-q", "--no-cov"],
        log_path=runner.report_dir / "pytest.out",
    )
    stats: dict[str, Any] = {}
    for label in ("passed", "failed", "skipped", "xfailed"):
        match = re.search(rf"(\d+)\s+{label}", output)
        if match:
            stats[label] = int(match.group(1))
    return StepResult(
        name="pytest_full",
        ok=return_code == 0,
        duration_s=0.0,
        stats=stats,
        findings=[output.strip()[-4000:]] if return_code != 0 else [],
    )
