#!/usr/bin/env python3
"""Full catalog + repo validation for overnight-safe runs.

Purpose
=======

One entry point that exhaustively re-runs every guarantee this repo
makes on itself, collects every failure (does not fail-fast), and
writes a machine-parseable report + a human log. Safe to run
unattended: no network calls, no writes outside ``logs/validation/``,
no changes to committed state.

What it runs (in order)
-----------------------

* env_snapshot          - python, git SHA, catalog counts
* hygiene_gates         - the 5 ``scripts/check-*.sh`` gates
* ruff_check            - ``ruff check .``
* ruff_format           - ``ruff format --check .``
* mypy_src              - ``mypy src`` (strict)
* pytest_full           - ``pytest -q --no-cov`` (full suite, incl. the
                          new L1/L4/L10 catalog tests)
* rule_deep             - schema + id-unique + provenance-pin +
                          action_type ref for every rule in
                          ``catalog/`` and ``collected/``
* profile_deep          - schema + strict resolve against real known
                          rule ids + extends dag for every profile
* action_type_deep      - schema + argument_schema is valid draft-2020-12
                          + shadow default => promotion_gate present
* remediation_deep      - schema + action_type_id points to an existing
                          action-type
* risk_classification   - ordering invariant (deny -> hil -> auto)
                          + every action_type_id reference is real
* source_manifests      - every ``rule-catalog/sources/*/manifest.yaml``
                          pins a real 40-hex revision (not all-zero)
* cross_check_azure     - (if /tmp/azure-policy-clone at pinned SHA)
                          every imported azure-builtin rule maps back
                          to a real upstream policy definition GUID
* cross_check_kube      - (if /tmp/kube-bench-clone at pinned SHA)
                          every imported kube-bench rule maps back to
                          a real upstream check id

Report
------

``logs/validation/<UTC timestamp>/report.json``  - one entry per step
``logs/validation/<UTC timestamp>/report.log``   - human-readable log
``logs/validation/<UTC timestamp>/pytest.out``   - full pytest output
``logs/validation/<UTC timestamp>/mypy.out``     - full mypy output

Exit code: 0 when every step passes; 1 when at least one step
recorded a failure (details in ``report.json``).

Usage
-----

    .venv/bin/python scripts/validate-catalog-full.py

Optional::

    --skip pytest,mypy_src          # skip named steps
    --only rule_deep,profile_deep   # run only named steps
    --report-dir logs/my-run        # override report directory
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, SchemaError

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_ROOT = REPO_ROOT / "rule-catalog"
CATALOG_DIRS = [CATALOG_ROOT / "catalog", CATALOG_ROOT / "collected"]
PROFILES_DIR = CATALOG_ROOT / "profiles"
ACTION_TYPES_DIR = CATALOG_ROOT / "action-types"
REMEDIATION_DIR = CATALOG_ROOT / "remediation"
RISK_CLASSIFICATION = CATALOG_ROOT / "risk-classification.yaml"
SOURCES_DIR = CATALOG_ROOT / "sources"
SCHEMA_ROOT = REPO_ROOT / "src" / "fdai" / "shared" / "contracts"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ZERO_SHA = "0" * 40
_FDAI_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")

# ---------------------------------------------------------------------------
# Result plumbing
# ---------------------------------------------------------------------------


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
    report_dir: Path = field(default_factory=lambda: Path())

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
        # duration may be missing if the fn built the result manually.
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_schema(rel: str) -> Draft202012Validator:
    data = json.loads((SCHEMA_ROOT / rel).read_text(encoding="utf-8"))
    validator = Draft202012Validator(data)
    validator.check_schema(data)  # raises SchemaError if the schema itself is bad
    return validator


def _run_subprocess(cmd: list[str], log_path: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603 - fixed argv list, no shell
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


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def step_env_snapshot(runner: Runner) -> StepResult:
    stats: dict[str, Any] = {
        "python_version": sys.version.split()[0],
        "cwd": str(REPO_ROOT),
    }
    for cmd, key in [
        (["git", "rev-parse", "HEAD"], "repo_head_sha"),
        (["git", "status", "--porcelain"], "repo_dirty_files"),
    ]:
        rc, out = _run_subprocess(cmd)
        if rc == 0:
            stats[key] = out.strip().splitlines() if key.endswith("files") else out.strip()
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
        "scripts/check-english-only.sh",
        "scripts/check-punctuation.sh",
        "scripts/check-guids.sh",
        "scripts/check-translations.sh",
        "scripts/check-core-imports.sh",
    ]
    findings: list[str] = []
    for s in scripts:
        rc, out = _run_subprocess(["bash", s])
        if rc != 0:
            findings.append(f"{s}: rc={rc}\n{out.strip()}")
    return StepResult(
        name="hygiene_gates",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={"gates": len(scripts)},
    )


def step_ruff_check(runner: Runner) -> StepResult:
    rc, out = _run_subprocess([".venv/bin/ruff", "check", "."])
    return StepResult(
        name="ruff_check",
        ok=rc == 0,
        duration_s=0.0,
        findings=[out.strip()] if rc != 0 else [],
    )


def step_ruff_format(runner: Runner) -> StepResult:
    rc, out = _run_subprocess([".venv/bin/ruff", "format", "--check", "."])
    return StepResult(
        name="ruff_format",
        ok=rc == 0,
        duration_s=0.0,
        findings=[out.strip()] if rc != 0 else [],
    )


def step_mypy_src(runner: Runner) -> StepResult:
    rc, out = _run_subprocess([".venv/bin/mypy", "src"], log_path=runner.report_dir / "mypy.out")
    return StepResult(
        name="mypy_src",
        ok=rc == 0,
        duration_s=0.0,
        findings=[out.strip()[-4000:]] if rc != 0 else [],
    )


def step_pytest_full(runner: Runner) -> StepResult:
    rc, out = _run_subprocess(
        [".venv/bin/pytest", "-q", "--no-cov"],
        log_path=runner.report_dir / "pytest.out",
    )
    stats: dict[str, Any] = {}
    m = re.search(r"(\d+)\s+passed", out)
    if m:
        stats["passed"] = int(m.group(1))
    m = re.search(r"(\d+)\s+failed", out)
    if m:
        stats["failed"] = int(m.group(1))
    m = re.search(r"(\d+)\s+skipped", out)
    if m:
        stats["skipped"] = int(m.group(1))
    m = re.search(r"(\d+)\s+xfailed", out)
    if m:
        stats["xfailed"] = int(m.group(1))
    return StepResult(
        name="pytest_full",
        ok=rc == 0,
        duration_s=0.0,
        stats=stats,
        findings=[out.strip()[-4000:]] if rc != 0 else [],
    )


# --- deep catalog invariants -----------------------------------------------


def _iter_rule_files() -> Iterable[Path]:
    for root in CATALOG_DIRS:
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.yaml")):
            yield p


def step_rule_deep(runner: Runner) -> StepResult:
    rule_validator = _load_schema("rule/schema.json")
    # action-type files use `name` as their stable id per
    # `shared/contracts/ontology/action-type.json`.
    action_type_ids: set[str] = set()
    if ACTION_TYPES_DIR.is_dir():
        for p in ACTION_TYPES_DIR.glob("*.yaml"):
            data = _load_yaml(p)
            if isinstance(data, dict) and "name" in data:
                action_type_ids.add(str(data["name"]))

    findings: list[str] = []
    ids: Counter[str] = Counter()
    checked = 0
    provenance_placeholder_hits = 0
    bad_id_pattern = 0
    for path in _iter_rule_files():
        data = _load_yaml(path)
        if data is None:
            findings.append(f"{path.relative_to(REPO_ROOT)}: file is empty")
            continue
        # schema
        errs = sorted(rule_validator.iter_errors(data), key=lambda e: list(e.path))
        if errs:
            first = errs[0]
            where = ".".join(str(p) for p in first.absolute_path) or "<root>"
            findings.append(f"{path.relative_to(REPO_ROOT)}: schema[{where}]: {first.message}")
            continue
        rid = str(data.get("id", ""))
        ids[rid] += 1
        # id pattern
        if not _FDAI_ID_RE.fullmatch(rid):
            bad_id_pattern += 1
            findings.append(f"{path.relative_to(REPO_ROOT)}: id {rid!r} fails FDAI id regex")
        # provenance pin: reject the all-zero placeholder for imported rules
        prov = data.get("provenance") or {}
        ref = str(prov.get("resolved_ref", ""))
        rel = str(path.relative_to(REPO_ROOT))
        if rel.startswith("rule-catalog/collected/"):
            if ref == _ZERO_SHA:
                provenance_placeholder_hits += 1
                findings.append(f"{rel}: provenance.resolved_ref is the all-zero placeholder")
            elif not _SHA_RE.fullmatch(ref):
                findings.append(
                    f"{rel}: provenance.resolved_ref {ref!r} is not a 40-hex commit SHA"
                )
        # action_type_id (if remediation declares one) MUST exist
        remediation = data.get("remediation") or {}
        at = remediation.get("action_type_id")
        if at and str(at) not in action_type_ids:
            findings.append(f"{rel}: remediation.action_type_id {at!r} not found in action-types/")
        checked += 1

    duplicates = {k: v for k, v in ids.items() if v > 1}
    if duplicates:
        findings.append(f"duplicate rule ids across catalog: {sorted(duplicates)[:20]}")

    return StepResult(
        name="rule_deep",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={
            "checked": checked,
            "unique_ids": len(ids),
            "duplicate_ids": len(duplicates),
            "provenance_placeholder_hits": provenance_placeholder_hits,
            "bad_id_pattern": bad_id_pattern,
        },
    )


def step_profile_deep(runner: Runner) -> StepResult:
    # Lazy import - we only need core.rule_catalog_profiles here, and the
    # module lives under src/fdai (importable because .venv sets PYTHONPATH).
    from fdai.core.rule_catalog_profiles import (  # noqa: PLC0415
        ProfileRegistry,
        ProfileResolutionError,
    )

    profile_schema = _load_schema("profile/schema.json")
    known_rule_ids: set[str] = set()
    for path in _iter_rule_files():
        data = _load_yaml(path)
        if isinstance(data, dict) and "id" in data:
            known_rule_ids.add(str(data["id"]))

    findings: list[str] = []
    schema_bad = 0
    resolve_bad = 0
    for path in sorted(PROFILES_DIR.rglob("*.yaml")):
        data = _load_yaml(path)
        if data is None:
            continue
        errs = sorted(profile_schema.iter_errors(data), key=lambda e: list(e.path))
        if errs:
            schema_bad += 1
            first = errs[0]
            where = ".".join(str(p) for p in first.absolute_path) or "<root>"
            findings.append(f"{path.relative_to(REPO_ROOT)}: schema[{where}]: {first.message}")

    try:
        registry = ProfileRegistry.from_directories(upstream=PROFILES_DIR)
    except ProfileResolutionError as exc:
        return StepResult(
            name="profile_deep",
            ok=False,
            duration_s=0.0,
            findings=[f"registry load: {exc}"],
        )

    checked = 0
    for profile in registry.all():
        try:
            registry.resolve(profile.id, known_rule_ids=known_rule_ids)
        except ProfileResolutionError as exc:
            resolve_bad += 1
            findings.append(f"{profile.id}: {exc}")
        checked += 1

    # extends
    known_pids = {p.id for p in registry.all()}
    for profile in registry.all():
        for parent in profile.extends:
            if parent not in known_pids:
                findings.append(f"{profile.id}: extends unknown profile {parent!r}")

    return StepResult(
        name="profile_deep",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={
            "profiles_checked": checked,
            "known_rule_ids": len(known_rule_ids),
            "schema_bad": schema_bad,
            "resolve_bad": resolve_bad,
        },
    )


def step_action_type_deep(runner: Runner) -> StepResult:
    at_schema = _load_schema("ontology/action-type.json")
    findings: list[str] = []
    ids: Counter[str] = Counter()
    shadow_without_gate = 0
    bad_arg_schema = 0
    checked = 0
    if not ACTION_TYPES_DIR.is_dir():
        return StepResult(
            name="action_type_deep",
            ok=True,
            duration_s=0.0,
            skipped=True,
            skipped_reason="action-types directory not present",
        )
    for path in sorted(ACTION_TYPES_DIR.glob("*.yaml")):
        try:
            data = _load_yaml(path)
        except yaml.YAMLError as exc:
            findings.append(f"{path.relative_to(REPO_ROOT)}: not valid YAML: {exc}")
            continue
        if data is None:
            continue
        errs = sorted(at_schema.iter_errors(data), key=lambda e: list(e.path))
        if errs:
            first = errs[0]
            where = ".".join(str(p) for p in first.absolute_path) or "<root>"
            findings.append(f"{path.relative_to(REPO_ROOT)}: schema[{where}]: {first.message}")
            continue
        # action-type files use `name` as their stable id.
        name = data.get("name")
        if not isinstance(name, str):
            findings.append(f"{path.relative_to(REPO_ROOT)}: missing string `name` field")
            continue
        ids[name] += 1
        # shadow default MUST have a promotion_gate
        if data.get("default_mode") == "shadow" and not data.get("promotion_gate"):
            shadow_without_gate += 1
            findings.append(
                f"{path.relative_to(REPO_ROOT)}: default_mode=shadow requires a promotion_gate"
            )
        # argument_schema, if present, MUST be a valid draft-2020-12 schema
        arg = data.get("argument_schema")
        if arg is not None:
            try:
                Draft202012Validator.check_schema(arg)
            except SchemaError as exc:
                bad_arg_schema += 1
                findings.append(
                    f"{path.relative_to(REPO_ROOT)}: argument_schema invalid: {exc.message}"
                )
        checked += 1
    duplicates = {k: v for k, v in ids.items() if v > 1}
    if duplicates:
        findings.append(f"duplicate action-type ids: {sorted(duplicates)}")
    return StepResult(
        name="action_type_deep",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={
            "checked": checked,
            "unique_ids": len(ids),
            "shadow_without_gate": shadow_without_gate,
            "bad_argument_schema": bad_arg_schema,
        },
    )


def step_remediation_deep(runner: Runner) -> StepResult:
    if not REMEDIATION_DIR.is_dir():
        return StepResult(
            name="remediation_deep",
            ok=True,
            duration_s=0.0,
            skipped=True,
            skipped_reason="remediation directory not present",
        )
    action_type_ids: set[str] = set()
    if ACTION_TYPES_DIR.is_dir():
        for p in ACTION_TYPES_DIR.glob("*.yaml"):
            data = _load_yaml(p)
            if isinstance(data, dict) and "name" in data:
                action_type_ids.add(str(data["name"]))
    findings: list[str] = []
    checked = 0
    for path in sorted(REMEDIATION_DIR.rglob("*.yaml")):
        data = _load_yaml(path)
        if data is None:
            continue
        # Playbook-style remediation may declare action_type_id at the top
        # level or per step; we walk both for a best-effort reference check.
        refs: list[str] = []
        if isinstance(data, dict):
            top = data.get("action_type_id")
            if isinstance(top, str):
                refs.append(top)
            for step in data.get("steps") or []:
                if isinstance(step, dict) and isinstance(step.get("action_type_id"), str):
                    refs.append(step["action_type_id"])
        for ref in refs:
            if ref not in action_type_ids:
                findings.append(f"{path.relative_to(REPO_ROOT)}: unknown action_type_id {ref!r}")
        checked += 1
    return StepResult(
        name="remediation_deep",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={"checked": checked, "known_action_types": len(action_type_ids)},
    )


def step_risk_classification(runner: Runner) -> StepResult:
    if not RISK_CLASSIFICATION.is_file():
        return StepResult(
            name="risk_classification",
            ok=True,
            duration_s=0.0,
            skipped=True,
            skipped_reason="risk-classification.yaml not present",
        )
    data = _load_yaml(RISK_CLASSIFICATION)
    findings: list[str] = []
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        return StepResult(
            name="risk_classification",
            ok=False,
            duration_s=0.0,
            findings=["risk-classification.yaml: missing or invalid `rules` list"],
        )
    order = {"deny": 0, "hil": 1, "auto": 2}
    prev = -1
    for entry in data["rules"]:
        decision = str(entry.get("decision", ""))
        rank = order.get(decision, 3)
        if rank < prev:
            findings.append(
                f"{entry.get('id')}: decision {decision!r} appears after a weaker one"
                " (must be deny -> hil -> auto)"
            )
        prev = max(prev, rank)
    return StepResult(
        name="risk_classification",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={"rules": len(data["rules"])},
    )


def step_source_manifests(runner: Runner) -> StepResult:
    if not SOURCES_DIR.is_dir():
        return StepResult(
            name="source_manifests",
            ok=True,
            duration_s=0.0,
            skipped=True,
            skipped_reason="sources/ not present",
        )
    findings: list[str] = []
    checked = 0
    for manifest in sorted(SOURCES_DIR.glob("*/manifest.yaml")):
        data = _load_yaml(manifest)
        rel = manifest.relative_to(REPO_ROOT)
        if not isinstance(data, dict):
            findings.append(f"{rel}: malformed manifest")
            continue
        pin = ((data.get("fetch") or {}).get("revision")) or data.get("revision")
        if pin is None:
            # Not every source is a git repo; leave it alone.
            checked += 1
            continue
        source_id = str(data.get("id") or manifest.parent.name)
        collected_here = CATALOG_ROOT / "collected" / source_id
        has_imports = collected_here.is_dir() and any(collected_here.rglob("*.yaml"))
        pin_s = str(pin)
        if pin_s == _ZERO_SHA:
            if has_imports:
                findings.append(
                    f"{rel}: revision is the all-zero placeholder but"
                    f" collected/{source_id}/ has imported rules"
                )
            # else: source declared but not yet imported - placeholder is expected.
        elif not _SHA_RE.fullmatch(pin_s):
            findings.append(f"{rel}: revision {pin_s!r} is not a 40-hex commit SHA")
        checked += 1
    return StepResult(
        name="source_manifests",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={"checked": checked},
    )


def step_cross_check_azure(runner: Runner) -> StepResult:
    clone = Path("/tmp/azure-policy-clone/azure-policy")
    manifest = SOURCES_DIR / "azure-policy-builtin" / "manifest.yaml"
    if not clone.is_dir() or not manifest.is_file():
        return StepResult(
            name="cross_check_azure",
            ok=True,
            duration_s=0.0,
            skipped=True,
            skipped_reason="azure-policy clone or manifest not present",
        )
    pinned = None
    data = _load_yaml(manifest)
    if isinstance(data, dict):
        pinned = ((data.get("fetch") or {}).get("revision")) or data.get("revision")
    if pinned is None:
        return StepResult(
            name="cross_check_azure",
            ok=False,
            duration_s=0.0,
            findings=["azure manifest has no revision"],
        )
    rc, out = _run_subprocess(["git", "-C", str(clone), "rev-parse", "HEAD"])
    if rc != 0 or out.strip() != str(pinned):
        return StepResult(
            name="cross_check_azure",
            ok=True,
            duration_s=0.0,
            skipped=True,
            skipped_reason=f"clone HEAD {out.strip()!r} != manifest {pinned!r}",
        )
    # Build the upstream GUID set once.
    upstream: set[str] = set()
    defs_dir = clone / "built-in-policies" / "policyDefinitions"
    for p in defs_dir.rglob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict):
            name = doc.get("name")
            if isinstance(name, str):
                upstream.add(name.lower())
    findings: list[str] = []
    checked = 0
    orphans = 0
    az_root = CATALOG_ROOT / "collected" / "azure-builtin"
    if not az_root.is_dir():
        return StepResult(
            name="cross_check_azure",
            ok=True,
            duration_s=0.0,
            skipped=True,
            skipped_reason="no imported azure-builtin rules on disk",
        )
    for p in az_root.rglob("*.yaml"):
        data = _load_yaml(p)
        if not isinstance(data, dict):
            continue
        prov = data.get("provenance") or {}
        origin = str((prov.get("source") or {}).get("id") or prov.get("upstream_id") or "")
        # Fallback: extract GUID from source_ref
        m = re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", origin.lower()
        )
        if not m:
            checked += 1
            continue
        guid = m.group(0)
        if guid not in upstream:
            orphans += 1
            if len(findings) < 20:
                findings.append(f"{p.relative_to(REPO_ROOT)}: upstream GUID {guid} not found")
        checked += 1
    if orphans:
        findings.append(f"total orphan azure rules: {orphans}")
    return StepResult(
        name="cross_check_azure",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={"checked": checked, "upstream_guids": len(upstream), "orphans": orphans},
    )


def step_cross_check_kube(runner: Runner) -> StepResult:
    clone = Path("/tmp/kube-bench-clone/kube-bench")
    manifest = SOURCES_DIR / "kube-bench" / "manifest.yaml"
    if not clone.is_dir() or not manifest.is_file():
        return StepResult(
            name="cross_check_kube",
            ok=True,
            duration_s=0.0,
            skipped=True,
            skipped_reason="kube-bench clone or manifest not present",
        )
    pinned = None
    data = _load_yaml(manifest)
    if isinstance(data, dict):
        pinned = ((data.get("fetch") or {}).get("revision")) or data.get("revision")
    rc, out = _run_subprocess(["git", "-C", str(clone), "rev-parse", "HEAD"])
    if pinned is None or rc != 0 or out.strip() != str(pinned):
        return StepResult(
            name="cross_check_kube",
            ok=True,
            duration_s=0.0,
            skipped=True,
            skipped_reason=f"clone HEAD {out.strip()!r} != manifest {pinned!r}",
        )
    # Collect upstream check ids: kube-bench cfg/**/*.yaml, groups[*].checks[*].id
    upstream: set[str] = set()
    cfg_root = clone / "cfg"
    for p in cfg_root.rglob("*.yaml"):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(doc, dict):
            continue
        for group in doc.get("groups") or []:
            if not isinstance(group, dict):
                continue
            for chk in group.get("checks") or []:
                if isinstance(chk, dict) and isinstance(chk.get("id"), (str, int)):
                    upstream.add(str(chk["id"]))
    findings: list[str] = []
    checked = 0
    orphans = 0
    kb_root = CATALOG_ROOT / "collected" / "kube-bench"
    if not kb_root.is_dir():
        return StepResult(
            name="cross_check_kube",
            ok=True,
            duration_s=0.0,
            skipped=True,
            skipped_reason="no imported kube-bench rules on disk",
        )
    for p in kb_root.rglob("*.yaml"):
        data = _load_yaml(p)
        if not isinstance(data, dict):
            continue
        prov = data.get("provenance") or {}
        cid = str((prov.get("source") or {}).get("id") or prov.get("upstream_id") or "")
        if not cid:
            checked += 1
            continue
        if cid not in upstream:
            orphans += 1
            if len(findings) < 20:
                findings.append(f"{p.relative_to(REPO_ROOT)}: upstream id {cid!r} not found")
        checked += 1
    if orphans:
        findings.append(f"total orphan kube-bench rules: {orphans}")
    return StepResult(
        name="cross_check_kube",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={"checked": checked, "upstream_ids": len(upstream), "orphans": orphans},
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


ALL_STEPS: list[tuple[str, Callable[[Runner], StepResult]]] = [
    ("env_snapshot", step_env_snapshot),
    ("hygiene_gates", step_hygiene_gates),
    ("ruff_check", step_ruff_check),
    ("ruff_format", step_ruff_format),
    ("mypy_src", step_mypy_src),
    ("pytest_full", step_pytest_full),
    ("rule_deep", step_rule_deep),
    ("profile_deep", step_profile_deep),
    ("action_type_deep", step_action_type_deep),
    ("remediation_deep", step_remediation_deep),
    ("risk_classification", step_risk_classification),
    ("source_manifests", step_source_manifests),
    ("cross_check_azure", step_cross_check_azure),
    ("cross_check_kube", step_cross_check_kube),
]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--only", default="", help="Comma-separated step names to run")
    p.add_argument("--skip", default="", help="Comma-separated step names to skip")
    p.add_argument(
        "--report-dir",
        default=None,
        help="Directory to write report.{json,log} into (default: logs/validation/<ts>)",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    only = {n.strip() for n in args.only.split(",") if n.strip()}
    skip = {n.strip() for n in args.skip.split(",") if n.strip()}
    unknown = (only | skip) - {name for name, _ in ALL_STEPS}
    if unknown:
        print(f"unknown step names: {sorted(unknown)}", file=sys.stderr)
        return 2

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    report_dir = (
        Path(args.report_dir) if args.report_dir else REPO_ROOT / "logs" / "validation" / ts
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    runner = Runner(report_dir=report_dir)

    # Ensure ruff / mypy / pytest are installed - fail early otherwise.
    for tool in [".venv/bin/ruff", ".venv/bin/mypy", ".venv/bin/pytest"]:
        if not (REPO_ROOT / tool).is_file():
            print(f"missing {tool} - run `uv sync --extra dev` first", file=sys.stderr)
            return 2
    if not shutil.which("git"):
        print("git not found on PATH", file=sys.stderr)
        return 2

    for name, fn in ALL_STEPS:
        if only and name not in only:
            continue
        if name in skip:
            runner.steps.append(
                StepResult(
                    name=name, ok=True, duration_s=0.0, skipped=True, skipped_reason="--skip"
                )
            )
            continue
        runner.run(name, fn)

    runner.write_report()
    print(f"\nreport written to {report_dir}")
    failed = sum(1 for s in runner.steps if not s.ok and not s.skipped)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
