"""Shared structural and production readiness evaluation for ARB."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

PRODUCTION_GATE_REF = "architecture-review.production-ready"
_ALLOWED_ARTIFACT_STATUSES = {"ready", "conditional", "blocked"}
_ALLOWED_BLOCKER_STATUSES = {"open", "accepted", "resolved"}
_ALLOWED_DESIGN_STATUSES = {"draft", "conditional", "approved"}
_ALLOWED_PRODUCTION_STATUSES = {"blocked", "conditional", "ready"}
_ALLOWED_SEVERITIES = {"critical", "high", "medium", "low"}
_REQUIRED_TOP_LEVEL = {
    "version",
    "review_id",
    "implementation_target",
    "decision_request",
    "design_review_status",
    "production_approval_status",
    "artifacts",
    "blockers",
    "production_gate",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ArchitectureReviewReadiness:
    """ARB health split into configuration structure and production readiness."""

    structure_valid: bool
    production_ready: bool
    failures: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "structure_valid": self.structure_valid,
            "production_ready": self.production_ready,
            "failures": list(self.failures),
        }


class ArchitectureReviewProductionGateEvaluator:
    """Evaluate the ARB production gate from the current manifest."""

    def __init__(self, *, manifest_path: Path, repo_root: Path) -> None:
        self._manifest_path = manifest_path
        self._repo_root = repo_root

    async def evaluate(self, *, rule_id: str, step_id: str, process_id: str) -> bool:
        del step_id, process_id
        if rule_id != PRODUCTION_GATE_REF:
            return False
        try:
            raw = yaml.safe_load(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return False
        return evaluate_readiness(raw, repo_root=self._repo_root).production_ready


def evaluate_readiness(raw: Any, *, repo_root: Path) -> ArchitectureReviewReadiness:
    """Return structural health and production readiness without conflating them."""
    try:
        validate_contract(raw, repo_root=repo_root, require_production_ready=False)
    except ValueError as exc:
        return ArchitectureReviewReadiness(
            structure_valid=False,
            production_ready=False,
            failures=(str(exc),),
        )
    try:
        validate_contract(raw, repo_root=repo_root, require_production_ready=True)
    except ValueError as exc:
        return ArchitectureReviewReadiness(
            structure_valid=True,
            production_ready=False,
            failures=_production_failures(str(exc)),
        )
    return ArchitectureReviewReadiness(structure_valid=True, production_ready=True)


def validate_contract(raw: Any, repo_root: Path, require_production_ready: bool) -> None:
    """Validate the ARB manifest and optionally require every production gate."""
    root = _mapping(raw, "document")
    review = _mapping(root.get("architecture_review"), "architecture_review")
    missing = _REQUIRED_TOP_LEVEL - review.keys()
    if missing:
        raise ValueError(f"architecture_review is missing: {', '.join(sorted(missing))}")

    if review["design_review_status"] not in _ALLOWED_DESIGN_STATUSES:
        raise ValueError("design_review_status is invalid")
    if review["production_approval_status"] not in _ALLOWED_PRODUCTION_STATUSES:
        raise ValueError("production_approval_status is invalid")

    artifact_ids: set[str] = set()
    artifacts = _non_empty_list(review["artifacts"], "artifacts")
    for index, raw_artifact in enumerate(artifacts):
        artifact = _mapping(raw_artifact, f"artifacts[{index}]")
        artifact_id = artifact.get("id")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ValueError(f"artifacts[{index}].id must be a non-empty string")
        if artifact_id in artifact_ids:
            raise ValueError(f"duplicate artifact id: {artifact_id}")
        artifact_ids.add(artifact_id)
        if artifact.get("status") not in _ALLOWED_ARTIFACT_STATUSES:
            raise ValueError(f"artifact {artifact_id} has an invalid status")
        if artifact.get("required_for") not in {"design", "production"}:
            raise ValueError(f"artifact {artifact_id} has an invalid required_for value")
        evidence = _non_empty_list(artifact.get("evidence"), f"artifact {artifact_id}.evidence")
        _validate_evidence_paths(repo_root, evidence, f"artifact {artifact_id}.evidence")

    blocker_ids: set[str] = set()
    blockers = _non_empty_list(review["blockers"], "blockers")
    for index, raw_blocker in enumerate(blockers):
        blocker = _mapping(raw_blocker, f"blockers[{index}]")
        blocker_id = blocker.get("id")
        if not isinstance(blocker_id, str) or not blocker_id:
            raise ValueError(f"blockers[{index}].id must be a non-empty string")
        if blocker_id in blocker_ids:
            raise ValueError(f"duplicate blocker id: {blocker_id}")
        blocker_ids.add(blocker_id)
        if blocker.get("severity") not in _ALLOWED_SEVERITIES:
            raise ValueError(f"blocker {blocker_id} has an invalid severity")
        if blocker.get("status") not in _ALLOWED_BLOCKER_STATUSES:
            raise ValueError(f"blocker {blocker_id} has an invalid status")
        for field in ("owner_slot", "resolution"):
            if not isinstance(blocker.get(field), str) or not blocker[field].strip():
                raise ValueError(f"blocker {blocker_id}.{field} must be a non-empty string")

    gate = _mapping(review["production_gate"], "production_gate")
    required_owners = _non_empty_list(gate.get("required_owner_slots"), "required_owner_slots")
    required_evidence = _non_empty_list(gate.get("required_evidence"), "required_evidence")
    owner_bindings = _mapping(gate.get("owner_bindings"), "owner_bindings")
    evidence_bindings = _mapping(gate.get("evidence_bindings"), "evidence_bindings")
    unknown_owner_bindings = owner_bindings.keys() - set(required_owners)
    if unknown_owner_bindings:
        raise ValueError(f"unknown owner bindings: {', '.join(sorted(unknown_owner_bindings))}")
    unknown_evidence_bindings = evidence_bindings.keys() - set(required_evidence)
    if unknown_evidence_bindings:
        raise ValueError(
            f"unknown evidence bindings: {', '.join(sorted(unknown_evidence_bindings))}"
        )
    for slot, binding in owner_bindings.items():
        _validate_owner_binding(slot, binding)
    for item, binding in evidence_bindings.items():
        _validate_evidence_binding(item, binding)

    if require_production_ready:
        failures: list[str] = []
        if review["design_review_status"] != "approved":
            failures.append("design_review_status must be approved")
        if review["production_approval_status"] != "ready":
            failures.append("production_approval_status must be ready")
        unresolved = [
            str(blocker["id"])
            for blocker in blockers
            if blocker["severity"] in {"critical", "high"} and blocker["status"] == "open"
        ]
        if unresolved:
            failures.append(f"unresolved critical/high blockers: {', '.join(unresolved)}")
        missing_owners = [str(slot) for slot in required_owners if slot not in owner_bindings]
        if missing_owners:
            failures.append(f"missing owner bindings: {', '.join(missing_owners)}")
        missing_evidence = [
            str(item) for item in required_evidence if item not in evidence_bindings
        ]
        if missing_evidence:
            failures.append(f"missing production evidence: {', '.join(missing_evidence)}")
        production_not_ready = [
            str(artifact["id"])
            for artifact in artifacts
            if artifact["required_for"] == "production" and artifact["status"] != "ready"
        ]
        if production_not_ready:
            failures.append(f"production artifacts not ready: {', '.join(production_not_ready)}")
        if failures:
            raise ValueError("production readiness failed:\n- " + "\n- ".join(failures))


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def _non_empty_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    return value


def _validate_evidence_paths(repo_root: Path, evidence: list[Any], label: str) -> None:
    for raw_path in evidence:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError(f"{label} contains an invalid evidence path")
        relative_path = raw_path.split("#", maxsplit=1)[0]
        if not (repo_root / relative_path).exists():
            raise ValueError(f"{label} references missing evidence: {relative_path}")


def _validate_owner_binding(slot: str, raw: Any) -> None:
    binding = _mapping(raw, f"owner_bindings.{slot}")
    for field in ("subject", "escalation"):
        if not isinstance(binding.get(field), str) or not binding[field].strip():
            raise ValueError(f"owner_bindings.{slot}.{field} must be a non-empty string")


def _validate_evidence_binding(item: str, raw: Any) -> None:
    binding = _mapping(raw, f"evidence_bindings.{item}")
    for field in ("uri", "approved_by"):
        if not isinstance(binding.get(field), str) or not binding[field].strip():
            raise ValueError(f"evidence_bindings.{item}.{field} must be a non-empty string")
    digest = binding.get("sha256")
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        raise ValueError(f"evidence_bindings.{item}.sha256 must be 64 lowercase hex characters")
    if not _valid_timestamp(binding.get("approved_at")):
        raise ValueError(f"evidence_bindings.{item}.approved_at must be an ISO 8601 timestamp")


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _production_failures(message: str) -> tuple[str, ...]:
    prefix = "production readiness failed:\n"
    if not message.startswith(prefix):
        return (message,)
    return tuple(line.removeprefix("- ") for line in message[len(prefix) :].splitlines())


__all__ = [
    "ArchitectureReviewProductionGateEvaluator",
    "ArchitectureReviewReadiness",
    "PRODUCTION_GATE_REF",
    "evaluate_readiness",
    "validate_contract",
]
