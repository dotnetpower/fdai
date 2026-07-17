"""Shared paths, loading, subprocess, and report primitives."""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_ROOT = REPO_ROOT / "rule-catalog"
CATALOG_DIRS = [CATALOG_ROOT / "catalog", CATALOG_ROOT / "collected"]
PROFILES_DIR = CATALOG_ROOT / "profiles"
ACTION_TYPES_DIR = CATALOG_ROOT / "action-types"
REMEDIATION_DIR = CATALOG_ROOT / "remediation"
RISK_CLASSIFICATION = CATALOG_ROOT / "risk-classification.yaml"
SOURCES_DIR = CATALOG_ROOT / "sources"
SCHEMA_ROOT = REPO_ROOT / "src" / "fdai" / "shared" / "contracts"


@dataclass
class StepResult:
    name: str
    ok: bool
    duration_s: float
    findings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    skipped: bool = False
    skipped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Runner:
    steps: list[StepResult] = field(default_factory=list)
    report_dir: Path = field(default_factory=Path)

    def run(self, name: str, fn: Callable[[Runner], StepResult]) -> StepResult:
        print(f"[{name}] running ...", flush=True)
        t0 = time.monotonic()
        try:
            result = fn(self)
        except Exception as exc:  # pragma: no cover - defensive top-level catch
            result = StepResult(
                name=name,
                ok=False,
                duration_s=time.monotonic() - t0,
                findings=[f"unhandled exception: {exc!r}"],
            )
        if result.duration_s == 0.0:
            result.duration_s = time.monotonic() - t0
        result.name = name
        self.steps.append(result)
        status = "SKIP" if result.skipped else ("PASS" if result.ok else "FAIL")
        print(
            f"[{name}] {status} in {result.duration_s:.1f}s ({len(result.findings)} finding(s))",
            flush=True,
        )
        return result

    def write_report(self) -> None:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "repo_root": str(REPO_ROOT),
            "total_steps": len(self.steps),
            "failed": sum(1 for s in self.steps if not s.ok and not s.skipped),
            "passed": sum(1 for s in self.steps if s.ok and not s.skipped),
            "skipped": sum(1 for s in self.steps if s.skipped),
            "steps": [s.to_dict() for s in self.steps],
        }
        (self.report_dir / "report.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        lines: list[str] = [
            "FDAI catalog validation report",
            f"generated_at: {summary['generated_at']}",
            f"repo_root:    {summary['repo_root']}",
            f"total:        {summary['total_steps']}"
            f"  passed: {summary['passed']}"
            f"  failed: {summary['failed']}"
            f"  skipped: {summary['skipped']}",
            "",
        ]
        for step in self.steps:
            status = "SKIP" if step.skipped else ("PASS" if step.ok else "FAIL")
            lines.append(
                f"[{status}] {step.name}  ({step.duration_s:.1f}s)"
                + (f"  # {step.skipped_reason}" if step.skipped_reason else "")
            )
            if step.stats:
                for k, v in step.stats.items():
                    lines.append(f"    {k}: {v}")
            if step.findings:
                for finding in step.findings[:50]:
                    lines.append(f"    - {finding}")
                if len(step.findings) > 50:
                    lines.append(f"    ... (+{len(step.findings) - 50} more)")
            lines.append("")
        (self.report_dir / "report.log").write_text("\n".join(lines), encoding="utf-8")


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_schema(rel: str) -> Draft202012Validator:
    data = json.loads((SCHEMA_ROOT / rel).read_text(encoding="utf-8"))
    validator = Draft202012Validator(data)
    validator.check_schema(data)
    return validator


def run_subprocess(cmd: list[str], log_path: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = proc.stdout + proc.stderr
    if log_path is not None:
        log_path.write_text(output, encoding="utf-8")
    return proc.returncode, output


def iter_rule_files() -> Iterable[Path]:
    for root in CATALOG_DIRS:
        if not root.is_dir():
            continue
        yield from sorted(root.rglob("*.yaml"))
