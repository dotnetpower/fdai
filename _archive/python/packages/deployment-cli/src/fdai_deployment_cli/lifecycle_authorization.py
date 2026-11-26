"""Local lifecycle authorization receipts and phase-fenced automatic apply guards."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.lifecycle_plan import LifecyclePlan, PlanAdmissionDecision

LifecyclePhase = Literal["infrastructure", "workload"]

_SUPPORTED_PHASES = frozenset({"infrastructure", "workload"})
_PREFIXED_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} MUST include timezone information")


def exact_plan_digest_for(plan: LifecyclePlan) -> str:
    """Return the ``sha256:<hex>`` digest of a Plan's canonical signed payload bytes."""

    if not plan.signed_payload:
        raise ValueError("plan signed_payload MUST NOT be empty")
    return f"sha256:{hashlib.sha256(plan.signed_payload).hexdigest()}"


@dataclass(frozen=True, slots=True, kw_only=True)
class LifecyclePhaseCompletionReceipt:
    """Recorded completion receipt for an earlier fenced Plan phase."""

    plan_id: str
    exact_plan_digest: str
    fencing_generation: int
    phase: LifecyclePhase
    authorization_receipt_digest: str
    completed_at: datetime

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise ValueError("plan_id MUST NOT be empty")
        if _PREFIXED_SHA256.fullmatch(self.exact_plan_digest) is None:
            raise ValueError("exact_plan_digest MUST be sha256:<64 hex>")
        if (
            isinstance(self.fencing_generation, bool)
            or not isinstance(self.fencing_generation, int)
            or self.fencing_generation < 1
        ):
            raise ValueError("fencing_generation MUST be a positive integer")
        if self.phase not in _SUPPORTED_PHASES:
            raise ValueError("phase is unsupported")
        if _PREFIXED_SHA256.fullmatch(self.authorization_receipt_digest) is None:
            raise ValueError("authorization_receipt_digest MUST be sha256:<64 hex>")
        _require_aware(self.completed_at, "completed_at")

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": "fdai.lifecycle-phase-completion-receipt.v1",
            "plan_id": self.plan_id,
            "exact_plan_digest": self.exact_plan_digest,
            "fencing_generation": self.fencing_generation,
            "phase": self.phase,
            "authorization_receipt_digest": self.authorization_receipt_digest,
            "completed_at": self.completed_at.isoformat(),
        }

    @property
    def digest(self) -> str:
        return f"sha256:{canonical_digest(self.to_mapping())}"


@dataclass(frozen=True, slots=True, kw_only=True)
class LifecycleAuthorizationReceipt:
    """Local lifecycle authorization receipt binding exact plan digest, inputs, and phase fence."""

    plan_id: str
    exact_plan_digest: str
    fencing_generation: int
    phase: LifecyclePhase
    target_release_id: str
    target_release_digest: str
    configuration_revision_digest: str
    window_starts_at: datetime
    window_ends_at: datetime
    issued_at: datetime
    prerequisite_phase_receipt_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.plan_id or not self.target_release_id:
            raise ValueError("plan_id and target_release_id MUST NOT be empty")
        if _PREFIXED_SHA256.fullmatch(self.exact_plan_digest) is None:
            raise ValueError("exact_plan_digest MUST be sha256:<64 hex>")
        if (
            isinstance(self.fencing_generation, bool)
            or not isinstance(self.fencing_generation, int)
            or self.fencing_generation < 1
        ):
            raise ValueError("fencing_generation MUST be a positive integer")
        if self.phase not in _SUPPORTED_PHASES:
            raise ValueError("phase is unsupported")
        if _HEX_SHA256.fullmatch(self.target_release_digest) is None:
            raise ValueError("target_release_digest MUST be 64 lowercase hex characters")
        if _HEX_SHA256.fullmatch(self.configuration_revision_digest) is None:
            raise ValueError("configuration_revision_digest MUST be 64 lowercase hex characters")
        if (
            self.prerequisite_phase_receipt_digest is not None
            and _PREFIXED_SHA256.fullmatch(self.prerequisite_phase_receipt_digest) is None
        ):
            raise ValueError("prerequisite_phase_receipt_digest MUST be sha256:<64 hex>")
        _require_aware(self.window_starts_at, "window_starts_at")
        _require_aware(self.window_ends_at, "window_ends_at")
        _require_aware(self.issued_at, "issued_at")
        if self.window_starts_at >= self.window_ends_at:
            raise ValueError("window_starts_at MUST precede window_ends_at")

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": "fdai.lifecycle-authorization-receipt.v1",
            "plan_id": self.plan_id,
            "exact_plan_digest": self.exact_plan_digest,
            "fencing_generation": self.fencing_generation,
            "phase": self.phase,
            "target_release_id": self.target_release_id,
            "target_release_digest": self.target_release_digest,
            "configuration_revision_digest": self.configuration_revision_digest,
            "window_starts_at": self.window_starts_at.isoformat(),
            "window_ends_at": self.window_ends_at.isoformat(),
            "issued_at": self.issued_at.isoformat(),
            "prerequisite_phase_receipt_digest": self.prerequisite_phase_receipt_digest,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> LifecycleAuthorizationReceipt:
        if raw.get("schema_version") != "fdai.lifecycle-authorization-receipt.v1":
            raise ValueError("unsupported lifecycle authorization receipt schema")
        prereq = raw.get("prerequisite_phase_receipt_digest")
        if prereq is not None and not isinstance(prereq, str):
            raise ValueError("prerequisite_phase_receipt_digest MUST be a string or null")
        phase = raw.get("phase")
        if phase not in ("infrastructure", "workload"):
            raise ValueError("phase is unsupported")
        fencing = raw.get("fencing_generation")
        if isinstance(fencing, bool) or not isinstance(fencing, int):
            raise ValueError("fencing_generation MUST be an integer")
        return cls(
            plan_id=str(raw["plan_id"]),
            exact_plan_digest=str(raw["exact_plan_digest"]),
            fencing_generation=fencing,
            phase=phase,
            target_release_id=str(raw["target_release_id"]),
            target_release_digest=str(raw["target_release_digest"]),
            configuration_revision_digest=str(raw["configuration_revision_digest"]),
            window_starts_at=datetime.fromisoformat(str(raw["window_starts_at"])),
            window_ends_at=datetime.fromisoformat(str(raw["window_ends_at"])),
            issued_at=datetime.fromisoformat(str(raw["issued_at"])),
            prerequisite_phase_receipt_digest=prereq,
        )

    @property
    def digest(self) -> str:
        return f"sha256:{canonical_digest(self.to_mapping())}"


def issue_lifecycle_authorization_receipt(
    plan: LifecyclePlan,
    *,
    phase: LifecyclePhase,
    window_starts_at: datetime,
    window_ends_at: datetime,
    issued_at: datetime,
    prerequisite_receipt: LifecyclePhaseCompletionReceipt | None = None,
) -> LifecycleAuthorizationReceipt:
    """Bind the exact signed Plan digest and optional earlier-phase receipt into a local receipt."""

    return LifecycleAuthorizationReceipt(
        plan_id=plan.plan_id,
        exact_plan_digest=exact_plan_digest_for(plan),
        fencing_generation=plan.fencing_generation,
        phase=phase,
        target_release_id=plan.target_release_id,
        target_release_digest=plan.target_release_digest,
        configuration_revision_digest=plan.configuration_revision_digest,
        window_starts_at=window_starts_at,
        window_ends_at=window_ends_at,
        issued_at=issued_at,
        prerequisite_phase_receipt_digest=(
            None if prerequisite_receipt is None else prerequisite_receipt.digest
        ),
    )


def evaluate_phase_authorization(
    plan: LifecyclePlan,
    *,
    phase: LifecyclePhase,
    authorization_receipt: LifecycleAuthorizationReceipt | None,
    trusted_now: datetime,
    require_earlier_phase: bool = False,
    earlier_phase_receipt: LifecyclePhaseCompletionReceipt | None = None,
) -> PlanAdmissionDecision:
    """Verify local lifecycle authorization receipt binding and earlier-phase fencing."""

    _require_aware(trusted_now, "trusted_now")
    expected_plan_digest = exact_plan_digest_for(plan)
    if require_earlier_phase:
        if earlier_phase_receipt is None:
            return PlanAdmissionDecision(
                False, "earlier_phase_receipt_missing", ("infrastructure",)
            )
        if (
            earlier_phase_receipt.plan_id != plan.plan_id
            or earlier_phase_receipt.exact_plan_digest != expected_plan_digest
            or earlier_phase_receipt.fencing_generation != plan.fencing_generation
            or earlier_phase_receipt.phase != "infrastructure"
        ):
            return PlanAdmissionDecision(
                False, "earlier_phase_receipt_mismatch", (earlier_phase_receipt.plan_id,)
            )
    if authorization_receipt is None:
        return PlanAdmissionDecision(False, "authorization_receipt_missing", (plan.plan_id,))
    if authorization_receipt.fencing_generation != plan.fencing_generation:
        return PlanAdmissionDecision(
            False, "phase_fencing_mismatch", (str(authorization_receipt.fencing_generation),)
        )
    if (
        authorization_receipt.plan_id != plan.plan_id
        or authorization_receipt.exact_plan_digest != expected_plan_digest
        or authorization_receipt.phase != phase
        or authorization_receipt.target_release_id != plan.target_release_id
        or authorization_receipt.target_release_digest != plan.target_release_digest
        or authorization_receipt.configuration_revision_digest != plan.configuration_revision_digest
    ):
        return PlanAdmissionDecision(False, "authorization_receipt_plan_mismatch", (plan.plan_id,))
    if (
        require_earlier_phase
        and earlier_phase_receipt is not None
        and authorization_receipt.prerequisite_phase_receipt_digest != earlier_phase_receipt.digest
    ):
        return PlanAdmissionDecision(False, "earlier_phase_receipt_mismatch", (plan.plan_id,))
    if not (
        authorization_receipt.window_starts_at <= trusted_now < authorization_receipt.window_ends_at
        and trusted_now < plan.expires_at
    ):
        return PlanAdmissionDecision(False, "authorization_receipt_window_closed", (plan.plan_id,))
    return PlanAdmissionDecision(True, "allowed", ())
