"""Independent recovery postcondition verification."""

from __future__ import annotations

from typing import Protocol

from fdai.core.recovery.models import (
    ProbeVerdict,
    RecoveryPlanRecord,
    RecoveryProbeKind,
    RecoveryProbeResult,
    RecoveryVerification,
    RecoveryVerificationOutcome,
)


class RecoveryEvidenceCollector(Protocol):
    async def collect(
        self,
        plan: RecoveryPlanRecord,
    ) -> tuple[tuple[RecoveryProbeResult, ...], bool]: ...


def verify_recovery_postconditions(
    probe_results: tuple[RecoveryProbeResult, ...],
    *,
    telemetry_complete: bool,
) -> RecoveryVerification:
    by_kind = {item.kind: item for item in probe_results}
    if len(by_kind) != len(probe_results):
        raise ValueError("recovery probe kinds MUST be unique")
    missing = set(RecoveryProbeKind) - set(by_kind)
    if (
        missing
        or not telemetry_complete
        or any(item.verdict is ProbeVerdict.UNKNOWN for item in probe_results)
    ):
        return RecoveryVerification(
            outcome=RecoveryVerificationOutcome.UNSCORABLE,
            probe_results=probe_results,
            telemetry_complete=telemetry_complete,
            reason="recovery evidence is incomplete or unknown",
        )
    passed = sum(item.verdict is ProbeVerdict.PASSED for item in probe_results)
    if passed == len(RecoveryProbeKind):
        outcome = RecoveryVerificationOutcome.RECOVERED
        reason = "all recovery postconditions passed"
    elif passed == 0:
        outcome = RecoveryVerificationOutcome.NOT_RECOVERED
        reason = "no recovery postcondition passed"
    else:
        outcome = RecoveryVerificationOutcome.PARTIALLY_RECOVERED
        reason = "some recovery postconditions failed"
    return RecoveryVerification(
        outcome=outcome,
        probe_results=probe_results,
        telemetry_complete=telemetry_complete,
        reason=reason,
    )


__all__ = ["RecoveryEvidenceCollector", "verify_recovery_postconditions"]
