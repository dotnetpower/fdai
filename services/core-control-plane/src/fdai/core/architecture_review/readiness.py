"""Shared structural and production readiness evaluation for ARB."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import yaml

PRODUCTION_GATE_REF = "architecture-review.production-ready"
_ALLOWED_ARTIFACT_STATUSES = {"ready", "conditional", "blocked"}
_ALLOWED_BLOCKER_STATUSES = {"open", "accepted", "resolved"}
_ALLOWED_ACCEPTANCE_KINDS = {"risk", "exception"}
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
_MAX_EVIDENCE_BODY_BYTES = 4 * 1024 * 1024


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


@dataclass(frozen=True, slots=True)
class ProductionEvidenceBinding:
    """Typed metadata for one required production evidence item."""

    item: str
    uri: str
    sha256: str
    scope_ref: str
    revision: str
    approved_by: str
    approved_at: datetime
    expires_at: datetime
    freshness_seconds: int


@dataclass(frozen=True, slots=True)
class ProductionEvidenceAttestation:
    """Provider evidence as observed before approval, plus authenticated authority metadata."""

    uri: str
    body: bytes
    scope_ref: str
    revision: str
    observed_at: datetime
    authorized_approvers: tuple[str, ...]
    authentication_ref: str
    synthetic: bool = False

    def __post_init__(self) -> None:
        if not self.uri.strip() or not self.scope_ref.strip() or not self.revision.strip():
            raise ValueError("production evidence attestation identity MUST be non-empty")
        if not self.body or len(self.body) > _MAX_EVIDENCE_BODY_BYTES:
            raise ValueError("production evidence attestation body MUST be bounded and non-empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("production evidence observed_at MUST be timezone-aware")
        if not self.authorized_approvers or any(
            not approver.strip() for approver in self.authorized_approvers
        ):
            raise ValueError("production evidence authorized approvers MUST be non-empty")
        if len(self.authorized_approvers) != len(set(self.authorized_approvers)):
            raise ValueError("production evidence authorized approvers MUST be unique")
        if not self.authentication_ref.strip():
            raise ValueError("production evidence authentication_ref MUST be non-empty")


class ProductionEvidenceProvider(Protocol):
    """Retrieve one governed evidence body without granting decision authority."""

    async def retrieve(
        self,
        binding: ProductionEvidenceBinding,
    ) -> ProductionEvidenceAttestation: ...


class ArchitectureReviewProductionGateEvaluator:
    """Evaluate the ARB production gate with provider evidence at a bounded time."""

    def __init__(
        self,
        *,
        manifest_path: Path,
        repo_root: Path,
        evidence_provider: ProductionEvidenceProvider | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._manifest_path = manifest_path
        self._repo_root = repo_root
        self._evidence_provider = evidence_provider
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def evaluate(self, *, rule_id: str, step_id: str, process_id: str) -> bool:
        del step_id, process_id
        if rule_id != PRODUCTION_GATE_REF:
            return False
        try:
            raw = yaml.safe_load(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return False
        try:
            validate_contract(raw, repo_root=self._repo_root, require_production_ready=False)
        except ValueError:
            return False
        if self._evidence_provider is None:
            return False
        evaluated_at = self._clock()
        attestations: dict[str, ProductionEvidenceAttestation] = {}
        try:
            for binding in _production_evidence_bindings(raw):
                attestations[binding.item] = await self._evidence_provider.retrieve(binding)
        except (OSError, RuntimeError, ValueError):
            return False
        return evaluate_readiness(
            raw,
            repo_root=self._repo_root,
            evaluated_at=evaluated_at,
            evidence_attestations=attestations,
        ).production_ready


def evaluate_readiness(
    raw: Any,
    *,
    repo_root: Path,
    evaluated_at: datetime | None = None,
    evidence_attestations: Mapping[str, ProductionEvidenceAttestation] | None = None,
) -> ArchitectureReviewReadiness:
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
        validate_contract(
            raw,
            repo_root=repo_root,
            require_production_ready=True,
            evaluated_at=evaluated_at,
            evidence_attestations=evidence_attestations,
        )
    except ValueError as exc:
        return ArchitectureReviewReadiness(
            structure_valid=True,
            production_ready=False,
            failures=_production_failures(str(exc)),
        )
    return ArchitectureReviewReadiness(structure_valid=True, production_ready=True)


def validate_contract(
    raw: Any,
    repo_root: Path,
    require_production_ready: bool,
    evaluated_at: datetime | None = None,
    evidence_attestations: Mapping[str, ProductionEvidenceAttestation] | None = None,
) -> None:
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
    accepted_blockers: list[dict[str, Any]] = []
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
        if blocker["status"] == "accepted" and blocker["severity"] in {"critical", "high"}:
            accepted_blockers.append(blocker)

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
    evaluation_moment = evaluated_at or datetime.now().astimezone()
    if evaluation_moment.tzinfo is None:
        raise ValueError("evaluated_at must be timezone-aware")
    required_owner_slots = {str(slot) for slot in required_owners}
    for blocker in accepted_blockers:
        _validate_accepted_blocker(
            blocker,
            repo_root=repo_root,
            required_owner_slots=required_owner_slots,
            owner_bindings=owner_bindings,
            evaluated_at=evaluation_moment,
            require_registered_owner=require_production_ready,
        )

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
        expired_evidence = [
            str(item)
            for item, binding in evidence_bindings.items()
            if _evidence_expired(binding, item=str(item), evaluated_at=evaluation_moment)
        ]
        if expired_evidence:
            failures.append(f"expired production evidence: {', '.join(expired_evidence)}")
        attestation_failures = _evidence_attestation_failures(
            required_evidence=required_evidence,
            evidence_bindings=evidence_bindings,
            attestations=evidence_attestations or {},
            evaluated_at=evaluation_moment,
        )
        failures.extend(attestation_failures)
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
    for field in ("uri", "scope_ref", "revision", "approved_by"):
        if not isinstance(binding.get(field), str) or not binding[field].strip():
            raise ValueError(f"evidence_bindings.{item}.{field} must be a non-empty string")
    digest = binding.get("sha256")
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        raise ValueError(f"evidence_bindings.{item}.sha256 must be 64 lowercase hex characters")
    approved_at = _timestamp(binding.get("approved_at"))
    if approved_at is None:
        raise ValueError(f"evidence_bindings.{item}.approved_at must be an ISO 8601 timestamp")
    expires_at = _timestamp(binding.get("expires_at"))
    if expires_at is None:
        raise ValueError(f"evidence_bindings.{item}.expires_at must be an ISO 8601 timestamp")
    if expires_at <= approved_at:
        raise ValueError(f"evidence_bindings.{item}.expires_at must be after approved_at")
    freshness_seconds = binding.get("freshness_seconds")
    if (
        isinstance(freshness_seconds, bool)
        or not isinstance(freshness_seconds, int)
        or not 1 <= freshness_seconds <= 31_536_000
    ):
        raise ValueError(
            f"evidence_bindings.{item}.freshness_seconds must be between 1 and 31536000"
        )


def _production_evidence_bindings(raw: Any) -> tuple[ProductionEvidenceBinding, ...]:
    root = _mapping(raw, "document")
    review = _mapping(root.get("architecture_review"), "architecture_review")
    gate = _mapping(review.get("production_gate"), "production_gate")
    raw_bindings = _mapping(gate.get("evidence_bindings"), "evidence_bindings")
    bindings: list[ProductionEvidenceBinding] = []
    for item in sorted(raw_bindings):
        raw_binding = _mapping(raw_bindings[item], f"evidence_bindings.{item}")
        approved_at = _timestamp(raw_binding.get("approved_at"))
        expires_at = _timestamp(raw_binding.get("expires_at"))
        freshness_seconds = raw_binding.get("freshness_seconds")
        if (
            approved_at is None
            or expires_at is None
            or isinstance(freshness_seconds, bool)
            or not isinstance(freshness_seconds, int)
        ):
            raise ValueError(f"evidence_bindings.{item} is not structurally valid")
        bindings.append(
            ProductionEvidenceBinding(
                item=item,
                uri=str(raw_binding["uri"]),
                sha256=str(raw_binding["sha256"]),
                scope_ref=str(raw_binding["scope_ref"]),
                revision=str(raw_binding["revision"]),
                approved_by=str(raw_binding["approved_by"]),
                approved_at=approved_at,
                expires_at=expires_at,
                freshness_seconds=freshness_seconds,
            )
        )
    return tuple(bindings)


def _evidence_attestation_failures(
    *,
    required_evidence: list[Any],
    evidence_bindings: dict[str, Any],
    attestations: Mapping[str, ProductionEvidenceAttestation],
    evaluated_at: datetime,
) -> list[str]:
    failures: list[str] = []
    for item_value in required_evidence:
        item = str(item_value)
        raw_binding = evidence_bindings.get(item)
        if raw_binding is None:
            continue
        attestation = attestations.get(item)
        if attestation is None:
            failures.append(f"unattested production evidence: {item}")
            continue
        binding = next(
            candidate
            for candidate in _production_evidence_bindings_from_mapping({item: raw_binding})
        )
        reason = _evidence_attestation_failure(binding, attestation, evaluated_at=evaluated_at)
        if reason is not None:
            failures.append(f"invalid production evidence {item}: {reason}")
    return failures


def _production_evidence_bindings_from_mapping(
    raw_bindings: Mapping[str, Any],
) -> tuple[ProductionEvidenceBinding, ...]:
    wrapped = {
        "architecture_review": {"production_gate": {"evidence_bindings": dict(raw_bindings)}}
    }
    return _production_evidence_bindings(wrapped)


def _evidence_attestation_failure(
    binding: ProductionEvidenceBinding,
    attestation: ProductionEvidenceAttestation,
    *,
    evaluated_at: datetime,
) -> str | None:
    if attestation.uri != binding.uri:
        return "uri mismatch"
    if hashlib.sha256(attestation.body).hexdigest() != binding.sha256:
        return "body digest mismatch"
    if attestation.scope_ref != binding.scope_ref:
        return "scope mismatch"
    if attestation.revision != binding.revision:
        return "revision mismatch"
    if binding.approved_by not in attestation.authorized_approvers:
        return "approver is not authorized"
    observed_at = attestation.observed_at.astimezone(UTC)
    evaluation_moment = evaluated_at.astimezone(UTC)
    if observed_at > binding.approved_at.astimezone(UTC):
        return "body observation follows approval"
    if observed_at > evaluation_moment:
        return "body observation is after evaluation"
    if (evaluation_moment - observed_at).total_seconds() > binding.freshness_seconds:
        return "body is stale"
    if attestation.synthetic:
        return "synthetic evidence is not production evidence"
    return None


def _validate_accepted_blocker(
    blocker: dict[str, Any],
    *,
    repo_root: Path,
    required_owner_slots: set[str],
    owner_bindings: dict[str, Any],
    evaluated_at: datetime,
    require_registered_owner: bool,
) -> None:
    blocker_id = str(blocker["id"])
    owner_slot = str(blocker["owner_slot"])
    if owner_slot not in required_owner_slots:
        raise ValueError(
            f"blocker {blocker_id} accepted critical/high status requires a registered owner slot"
        )
    if require_registered_owner and owner_slot not in owner_bindings:
        raise ValueError(
            f"blocker {blocker_id} accepted critical/high status requires an owner binding"
        )
    acceptance = _mapping(blocker.get("acceptance"), f"blocker {blocker_id}.acceptance")
    kind = acceptance.get("kind")
    if kind not in _ALLOWED_ACCEPTANCE_KINDS:
        raise ValueError(f"blocker {blocker_id}.acceptance.kind must be risk or exception")
    if kind == "risk":
        _validate_accepted_risk(
            blocker_id,
            acceptance,
            repo_root=repo_root,
            evaluated_at=evaluated_at,
        )
        return
    _validate_accepted_exception(blocker_id, acceptance, evaluated_at=evaluated_at)


def _validate_accepted_risk(
    blocker_id: str,
    acceptance: dict[str, Any],
    *,
    repo_root: Path,
    evaluated_at: datetime,
) -> None:
    for field in ("mitigation", "residual_risk", "reviewed_by"):
        if not isinstance(acceptance.get(field), str) or not acceptance[field].strip():
            raise ValueError(f"blocker {blocker_id}.acceptance.{field} must be a non-empty string")
    review_date = _timestamp(acceptance.get("review_date"))
    if review_date is None:
        raise ValueError(
            f"blocker {blocker_id}.acceptance.review_date must be an ISO 8601 timestamp"
        )
    evidence = _non_empty_list(
        acceptance.get("evidence"),
        f"blocker {blocker_id}.acceptance.evidence",
    )
    _validate_evidence_paths(repo_root, evidence, f"blocker {blocker_id}.acceptance.evidence")
    if review_date < evaluated_at:
        raise ValueError(f"blocker {blocker_id} accepted risk review is stale")


def _validate_accepted_exception(
    blocker_id: str,
    acceptance: dict[str, Any],
    *,
    evaluated_at: datetime,
) -> None:
    for field in ("scope", "reason", "compensating_controls", "approved_by", "audit_ref"):
        if not isinstance(acceptance.get(field), str) or not acceptance[field].strip():
            raise ValueError(f"blocker {blocker_id}.acceptance.{field} must be a non-empty string")
    effective_from = _timestamp(acceptance.get("effective_from"))
    if effective_from is None:
        raise ValueError(
            f"blocker {blocker_id}.acceptance.effective_from must be an ISO 8601 timestamp"
        )
    effective_to = _timestamp(acceptance.get("effective_to"))
    if effective_to is None:
        raise ValueError(
            f"blocker {blocker_id}.acceptance.effective_to must be an ISO 8601 timestamp"
        )
    if effective_to <= effective_from:
        raise ValueError(
            f"blocker {blocker_id}.acceptance.effective_to must be after effective_from"
        )
    if not effective_from <= evaluated_at < effective_to:
        raise ValueError(f"blocker {blocker_id} accepted exception is not currently effective")


def _evidence_expired(raw: Any, *, item: str, evaluated_at: datetime) -> bool:
    binding = _mapping(raw, f"evidence_bindings.{item}")
    expires_at = _timestamp(binding.get("expires_at"))
    if expires_at is None:
        raise ValueError(f"evidence_bindings.{item}.expires_at must be an ISO 8601 timestamp")
    return expires_at <= evaluated_at


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _production_failures(message: str) -> tuple[str, ...]:
    prefix = "production readiness failed:\n"
    if not message.startswith(prefix):
        return (message,)
    return tuple(line.removeprefix("- ") for line in message[len(prefix) :].splitlines())


__all__ = [
    "ArchitectureReviewProductionGateEvaluator",
    "ArchitectureReviewReadiness",
    "PRODUCTION_GATE_REF",
    "ProductionEvidenceAttestation",
    "ProductionEvidenceBinding",
    "ProductionEvidenceProvider",
    "evaluate_readiness",
    "validate_contract",
]
