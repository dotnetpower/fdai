#!/usr/bin/env python3
"""Validate authority-neutral promotion verdicts for every Pantheon workflow.

The inventory records why each current workflow remains in shadow. It does not retain
operational measurements, change a workflow mode, grant execution authority, or replace the
future authoritative promotion registry. A new or changed WorkflowSpec must receive a fresh,
exactly bound verdict before this gate passes.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import fields
from datetime import date
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]
CATALOG_REF = "services/core-control-plane/src/fdai/agents/_framework/workflows.py"
MANIFEST_REF = "config/workflow-promotion-verdicts.json"
SCHEMA_REF = "config/workflow-promotion-verdicts.schema.json"
OWNER_REFS = frozenset(
    {
        "docs/roadmap/agents/agent-workflows.md",
        "docs/roadmap/agents/agent-workflow-rollout.md",
    }
)
PERMANENT_SHADOW_WORKFLOW = "retrospective-what-if"
_DEFERRED_BLOCKERS = frozenset(
    {
        "runtime_shadow_duration_missing",
        "kpi_baseline_missing",
        "guard_metrics_not_evaluated",
        "policy_escape_observation_missing",
    }
)
_TEST_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _load_json(path: Path, label: str) -> dict[str, Any]:
    """Load one JSON object or raise a bounded validation error."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unavailable or invalid: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{label} MUST be a JSON object")
    return raw


def _load_catalog(root: Path) -> tuple[Any, ...]:
    """Load the metadata-only WorkflowSpec registry without importing the agent package."""

    path = root / CATALOG_REF
    module_name = "_fdai_workflow_promotion_catalog"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"unable to load workflow catalog: {CATALOG_REF}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    workflows = getattr(module, "WORKFLOWS", None)
    if not isinstance(workflows, tuple) or not workflows:
        raise ValueError("workflow catalog MUST expose a non-empty WORKFLOWS tuple")
    return workflows


def _definition_digest(workflow: Any) -> str:
    """Bind a verdict to every field of one exact WorkflowSpec."""

    payload = {field.name: getattr(workflow, field.name) for field in fields(workflow)}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_path(root: Path, reference: str) -> Path | None:
    relative = reference.partition("::")[0]
    candidate = Path(relative)
    if candidate.is_absolute():
        return None
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved


def _test_selector_exists(root: Path, selector: str) -> bool:
    relative, separator, test_name = selector.partition("::")
    if not separator or not _TEST_NAME.fullmatch(test_name):
        return False
    path = _repo_path(root, relative)
    if path is None or not path.is_file():
        return False
    pattern = re.compile(rf"^(?:async )?def {re.escape(test_name)}\(", re.MULTILINE)
    return pattern.search(path.read_text(encoding="utf-8")) is not None


def validate_document(document: dict[str, Any], root: Path = ROOT) -> list[str]:
    """Return all inventory errors without changing workflow or promotion state."""

    errors: list[str] = []
    try:
        schema = _load_json(root / SCHEMA_REF, SCHEMA_REF)
    except ValueError as exc:
        return [str(exc)]

    validator = Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(document), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        errors.append(f"{MANIFEST_REF}:{location}: {error.message}")
    if errors:
        return errors

    try:
        reviewed_on = date.fromisoformat(document["reviewed_on"])
    except (TypeError, ValueError):
        errors.append(f"{MANIFEST_REF}: reviewed_on MUST be an ISO 8601 date")
    else:
        if reviewed_on.isoformat() != document["reviewed_on"]:
            errors.append(f"{MANIFEST_REF}: reviewed_on MUST use YYYY-MM-DD")

    catalog_path = root / CATALOG_REF
    if not catalog_path.is_file():
        return [*errors, f"missing workflow catalog: {CATALOG_REF}"]
    if document["catalog_digest"] != _file_digest(catalog_path):
        errors.append(f"{MANIFEST_REF}: catalog_digest does not match {CATALOG_REF}")

    try:
        workflows = _load_catalog(root)
    except (OSError, TypeError, ValueError) as exc:
        return [*errors, str(exc)]
    catalog = {workflow.id: workflow for workflow in workflows}
    if len(catalog) != len(workflows):
        errors.append(f"{CATALOG_REF}: workflow ids MUST be unique")

    verdicts = document["verdicts"]
    records = {item["workflow_id"]: item for item in verdicts}
    if len(records) != len(verdicts):
        errors.append(f"{MANIFEST_REF}: workflow verdict ids MUST be unique")

    missing = sorted(set(catalog) - set(records))
    unexpected = sorted(set(records) - set(catalog))
    if missing:
        errors.append(f"{MANIFEST_REF}: missing workflow verdicts: {', '.join(missing)}")
    if unexpected:
        errors.append(f"{MANIFEST_REF}: unexpected workflow verdicts: {', '.join(unexpected)}")

    for workflow_id in sorted(set(catalog) & set(records)):
        workflow = catalog[workflow_id]
        record = records[workflow_id]
        if workflow.default_mode != "shadow":
            errors.append(f"{CATALOG_REF}: {workflow_id} no longer defaults to shadow")
        if record["workflow_name"] != workflow.name:
            errors.append(f"{MANIFEST_REF}: {workflow_id} workflow_name is stale")
        if record["definition_digest"] != _definition_digest(workflow):
            errors.append(f"{MANIFEST_REF}: {workflow_id} definition_digest is stale")
        if record["trace_ref"] != workflow.trace_ref:
            errors.append(f"{MANIFEST_REF}: {workflow_id} trace_ref is stale")
        if not _test_selector_exists(root, record["trace_ref"]):
            errors.append(f"{MANIFEST_REF}: {workflow_id} trace_ref does not resolve")

        evidence_refs = set(record["evidence_refs"])
        if not OWNER_REFS <= evidence_refs:
            errors.append(f"{MANIFEST_REF}: {workflow_id} omits a workflow owner reference")
        if record["trace_ref"] not in evidence_refs:
            errors.append(f"{MANIFEST_REF}: {workflow_id} omits its trace evidence reference")
        for reference in record["evidence_refs"]:
            path = _repo_path(root, reference)
            if path is None or not path.is_file():
                errors.append(
                    f"{MANIFEST_REF}: {workflow_id} evidence reference does not exist: {reference}"
                )

        status = record["evidence_status"]
        blockers = frozenset(record["blocking_reasons"])
        if workflow_id == PERMANENT_SHADOW_WORKFLOW:
            if record["verdict"] != "permanent_shadow":
                errors.append(f"{MANIFEST_REF}: {workflow_id} MUST remain permanently shadow")
            expected_status = {
                "shadow_duration": "not_applicable",
                "kpi_baseline": "not_applicable",
                "guard_regression": "not_applicable",
                "policy_escapes": "not_applicable",
                "trace": "implementation_only",
            }
            if status != expected_status or blockers != {"judge_only_workflow"}:
                errors.append(
                    f"{MANIFEST_REF}: {workflow_id} permanent-shadow evidence is inconsistent"
                )
        else:
            if record["verdict"] != "deferred":
                errors.append(f"{MANIFEST_REF}: {workflow_id} lacks a safe deferral")
            expected_status = {
                "shadow_duration": "missing",
                "kpi_baseline": "missing",
                "guard_regression": "not_evaluated",
                "policy_escapes": "unknown",
                "trace": "implementation_only",
            }
            if status != expected_status or blockers != _DEFERRED_BLOCKERS:
                errors.append(f"{MANIFEST_REF}: {workflow_id} deferral evidence is inconsistent")

    summary = document["summary"]
    actual_deferred = sum(item["verdict"] == "deferred" for item in verdicts)
    actual_permanent = sum(item["verdict"] == "permanent_shadow" for item in verdicts)
    expected_summary = {
        "workflow_count": len(workflows),
        "deferred": actual_deferred,
        "permanent_shadow": actual_permanent,
    }
    if summary != expected_summary:
        errors.append(f"{MANIFEST_REF}: summary does not match the verdict inventory")
    return errors


def validate(root: Path = ROOT) -> list[str]:
    """Load and validate the repository workflow promotion verdict inventory."""

    try:
        document = _load_json(root / MANIFEST_REF, MANIFEST_REF)
    except ValueError as exc:
        return [str(exc)]
    return validate_document(document, root)


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"workflow-promotion-verdicts: ERROR: {error}", file=sys.stderr)
        return 1
    print("workflow-promotion-verdicts: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
