#!/usr/bin/env python3
"""Validate the machine-readable OI-01 source-to-store implementation audit."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
AUDIT_PATH = Path("config/continuous-operational-instance-graph-audit.json")
DESIGN_OWNER = Path("docs/roadmap/architecture/continuous-operational-instance-graph.md")
REQUIRED_STAGES = (
    "provider-push-ingress",
    "resumable-delta-cursor",
    "complete-reconciliation",
    "normalized-observation-ingress",
    "snapshot-promotion",
    "realtime-overlay",
    "ontology-projection",
    "topology-history",
    "graph-first-query",
    "bounded-live-read",
    "live-evidence-write-through",
    "adaptive-scheduling",
    "retention-holds",
    "typed-rollup",
    "archive-lifecycle",
)
REQUIRED_FAMILIES = frozenset({"collection", "projection", "query", "retention", "archive"})
ALLOWED_STATES = frozenset({"implemented", "in-progress", "not-started"})
ALLOWED_BINDING_STATES = frozenset({"bound", "partial", "unbound"})
OWNER_DOC_FRAGMENTS = (
    "## Source-to-store implementation audit",
    "| Source-to-store implementation audit | implemented |",
    "- [x] `OI-01` records a source-to-store implementation audit",
)


def _load(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("audit record MUST be a JSON object")
    return value


def _repo_file(root: Path, value: object, field: str, errors: list[str]) -> Path | None:
    if (
        not isinstance(value, str)
        or not value
        or Path(value).is_absolute()
        or ".." in Path(value).parts
    ):
        errors.append(f"{field} must be a non-empty repository-relative path")
        return None
    path = root / value
    if not path.is_file():
        errors.append(f"{field} references a missing file: {value}")
        return None
    return path


def _repo_symbol(path: Path | None, value: object, field: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value:
        errors.append(f"{field} must be a non-empty string")
        return
    if path is None:
        return
    text = path.read_text(encoding="utf-8")
    missing = [part for part in value.split(".") if part and part not in text]
    if missing:
        errors.append(f"{field} is not present in {path.relative_to(REPO_ROOT)}: {value}")


def _validate_stage(root: Path, value: object, index: int) -> tuple[str | None, list[str]]:
    prefix = f"stages[{index}]"
    errors: list[str] = []
    if not isinstance(value, Mapping):
        return None, [f"{prefix} must be an object"]
    stage_id = value.get("id")
    if not isinstance(stage_id, str) or not stage_id:
        errors.append(f"{prefix}.id must be a non-empty string")
        stage_id = None
    family = value.get("family")
    if family not in REQUIRED_FAMILIES:
        errors.append(f"{prefix}.family must name a required stage family")
    state = value.get("state")
    if state not in ALLOWED_STATES:
        errors.append(f"{prefix}.state must be one of {sorted(ALLOWED_STATES)}")

    owner = value.get("owner")
    if not isinstance(owner, Mapping):
        errors.append(f"{prefix}.owner must be an object")
    else:
        assigned = owner.get("status") == "assigned"
        if owner.get("status") not in {"assigned", "unassigned"}:
            errors.append(f"{prefix}.owner.status must be assigned or unassigned")
        if assigned:
            owner_path = _repo_file(root, owner.get("path"), f"{prefix}.owner.path", errors)
            _repo_symbol(owner_path, owner.get("symbol"), f"{prefix}.owner.symbol", errors)
        elif owner.get("path") is not None or owner.get("symbol") is not None:
            errors.append(f"{prefix}.owner unassigned state must use null path and symbol")
        if state in {"implemented", "in-progress"} and not assigned:
            errors.append(f"{prefix} implemented work must have an assigned owner")

    bindings = value.get("bindings")
    if not isinstance(bindings, list):
        errors.append(f"{prefix}.bindings must be an array")
    else:
        for binding_index, binding in enumerate(bindings):
            binding_prefix = f"{prefix}.bindings[{binding_index}]"
            if not isinstance(binding, Mapping):
                errors.append(f"{binding_prefix} must be an object")
                continue
            if binding.get("state") not in ALLOWED_BINDING_STATES:
                errors.append(f"{binding_prefix}.state must be bound, partial, or unbound")
            binding_path = _repo_file(
                root,
                binding.get("path"),
                f"{binding_prefix}.path",
                errors,
            )
            symbol = binding.get("symbol")
            if symbol is not None and (not isinstance(symbol, str) or not symbol):
                errors.append(f"{binding_prefix}.symbol must be null or a non-empty string")
            elif symbol is not None:
                _repo_symbol(binding_path, symbol, f"{binding_prefix}.symbol", errors)

    tests = value.get("tests")
    if not isinstance(tests, list):
        errors.append(f"{prefix}.tests must be an array")
    else:
        for test_index, test_path in enumerate(tests):
            _repo_file(root, test_path, f"{prefix}.tests[{test_index}]", errors)
        if state in {"implemented", "in-progress"} and not tests:
            errors.append(f"{prefix} implemented work must cite at least one focused test")
        if state == "not-started" and tests:
            errors.append(f"{prefix} not-started work must not claim focused tests")

    missing = value.get("missing_binding")
    if state == "implemented" and missing is not None:
        errors.append(f"{prefix} implemented work must use null missing_binding")
    if state in {"in-progress", "not-started"} and (
        not isinstance(missing, str) or not missing.strip()
    ):
        errors.append(f"{prefix} open work must name its exact missing binding")
    return stage_id, errors


def validate(root: Path = REPO_ROOT, audit_path: Path = AUDIT_PATH) -> list[str]:
    """Return deterministic violations for one repository audit record."""

    path = root / audit_path
    if not path.is_file():
        return [f"missing audit record: {audit_path.as_posix()}"]
    try:
        payload = _load(path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [f"invalid audit record: {exc}"]

    errors: list[str] = []
    if payload.get("schema_version") != "1.0.0":
        errors.append("schema_version must be 1.0.0")
    if payload.get("package_id") != "OI-01":
        errors.append("package_id must be OI-01")
    if payload.get("design_owner") != DESIGN_OWNER.as_posix():
        errors.append(f"design_owner must be {DESIGN_OWNER.as_posix()}")
    else:
        design_path = _repo_file(root, payload.get("design_owner"), "design_owner", errors)
        if design_path is not None:
            design_text = design_path.read_text(encoding="utf-8")
            for fragment in OWNER_DOC_FRAGMENTS:
                if fragment not in design_text:
                    errors.append(f"design_owner is missing the OI-01 ledger fragment: {fragment}")

    stages = payload.get("stages")
    if not isinstance(stages, list):
        return [*errors, "stages must be an array"]
    stage_ids: list[str] = []
    families: set[str] = set()
    for index, stage in enumerate(stages):
        stage_id, stage_errors = _validate_stage(root, stage, index)
        errors.extend(stage_errors)
        if stage_id is not None:
            stage_ids.append(stage_id)
        if isinstance(stage, Mapping) and isinstance(stage.get("family"), str):
            families.add(stage["family"])
    if tuple(stage_ids) != REQUIRED_STAGES:
        errors.append(f"stage ids must equal the ordered OI-01 inventory: {list(REQUIRED_STAGES)}")
    if len(stage_ids) != len(set(stage_ids)):
        errors.append("stage ids must be unique")
    if families != REQUIRED_FAMILIES:
        errors.append(f"stage families must equal {sorted(REQUIRED_FAMILIES)}")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Continuous operational instance graph audit: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
