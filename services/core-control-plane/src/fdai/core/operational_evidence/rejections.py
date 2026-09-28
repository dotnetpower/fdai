"""Map gate and preflight reasons onto the fail-closed rejection matrix."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from fdai_service_contracts.decision_evidence import LiveEvidenceClaimRejectionReason
from fdai_service_contracts.operational_evidence import OperationalEvidenceRejectionClass

from fdai.core.readiness.decision_evidence import DecisionEvidenceReadinessReason

_R = OperationalEvidenceRejectionClass
_CLAIM_CLASSES: dict[LiveEvidenceClaimRejectionReason, OperationalEvidenceRejectionClass] = {
    LiveEvidenceClaimRejectionReason.AUTHORITY_MISMATCH: _R.SYNTHETIC_LIVE,
    LiveEvidenceClaimRejectionReason.CONFLICTING: _R.CONFLICTING,
    LiveEvidenceClaimRejectionReason.INCOMPLETE: _R.PARTIAL,
    LiveEvidenceClaimRejectionReason.METHOD_MISMATCH: _R.REPLAY_SUBSTITUTED,
    LiveEvidenceClaimRejectionReason.NOT_YET_RECORDED: _R.STALE,
    LiveEvidenceClaimRejectionReason.POLICY_MISMATCH: _R.REPLAY_SUBSTITUTED,
    LiveEvidenceClaimRejectionReason.PRODUCER_MISMATCH: _R.REPLAY_SUBSTITUTED,
    LiveEvidenceClaimRejectionReason.PURPOSE_MISMATCH: _R.CROSS_SCOPE,
    LiveEvidenceClaimRejectionReason.SCOPE_MISMATCH: _R.CROSS_SCOPE,
    LiveEvidenceClaimRejectionReason.SOURCE_MISMATCH: _R.SYNTHETIC_LIVE,
    LiveEvidenceClaimRejectionReason.SOURCE_REVISION_MISMATCH: _R.REPLAY_SUBSTITUTED,
    LiveEvidenceClaimRejectionReason.STALE: _R.STALE,
    LiveEvidenceClaimRejectionReason.SYNTHETIC: _R.SYNTHETIC_LIVE,
}
_GATE_CLASSES: dict[DecisionEvidenceReadinessReason, OperationalEvidenceRejectionClass] = {
    DecisionEvidenceReadinessReason.BUNDLE_MISMATCH: _R.REPLAY_SUBSTITUTED,
    DecisionEvidenceReadinessReason.PROOF_MISMATCH: _R.REPLAY_SUBSTITUTED,
    DecisionEvidenceReadinessReason.PROOF_NOT_CURRENT: _R.STALE,
    DecisionEvidenceReadinessReason.UNTRUSTED_VERIFIER: _R.REVOKED,
}
_PRIORITY = (
    _R.CONFLICTING,
    _R.REVOKED,
    _R.SYNTHETIC_LIVE,
    _R.CROSS_SCOPE,
    _R.REPLAY_SUBSTITUTED,
    _R.PARTIAL,
    _R.STALE,
)


@dataclass(frozen=True, slots=True)
class ReadbackRejection:
    """A verifier-detected failure that becomes one content-free rejection record."""

    rejection_class: OperationalEvidenceRejectionClass
    reason_codes: tuple[str, ...]
    conflict_evidence_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.reason_codes:
            raise ValueError("readback rejection requires at least one reason code")
        if (self.rejection_class is OperationalEvidenceRejectionClass.CONFLICTING) != bool(
            self.conflict_evidence_digests
        ):
            raise ValueError("readback conflict digests do not match the rejection class")


def reject(
    rejection_class: OperationalEvidenceRejectionClass,
    *reasons: str,
    conflicts: Iterable[str] = (),
) -> ReadbackRejection:
    """Build one readback rejection with ordered unique reasons and conflict digests."""

    return ReadbackRejection(
        rejection_class=rejection_class,
        reason_codes=tuple(sorted(set(reasons))),
        conflict_evidence_digests=tuple(sorted(set(conflicts))),
    )


def strongest_class(
    classes: Iterable[OperationalEvidenceRejectionClass],
) -> OperationalEvidenceRejectionClass:
    """Return the deterministic most severe class; conflict is never averaged away."""

    present = set(classes)
    for candidate in _PRIORITY:
        if candidate in present:
            return candidate
    raise ValueError("no rejection class to rank")


def class_for_claim_reasons(
    reasons: Iterable[str],
) -> OperationalEvidenceRejectionClass | None:
    """Map preflight rejection details onto one recorded class."""

    classes = [
        _CLAIM_CLASSES[LiveEvidenceClaimRejectionReason(reason)]
        for reason in reasons
        if reason in LiveEvidenceClaimRejectionReason._value2member_map_
    ]
    return strongest_class(classes) if classes else None


def class_for_gate_reason(
    reason: DecisionEvidenceReadinessReason,
) -> OperationalEvidenceRejectionClass | None:
    """Return the recorded class, or nothing for unavailable and self-verified outcomes."""

    return _GATE_CLASSES.get(reason)


__all__ = [
    "ReadbackRejection",
    "class_for_claim_reasons",
    "class_for_gate_reason",
    "reject",
    "strongest_class",
]
