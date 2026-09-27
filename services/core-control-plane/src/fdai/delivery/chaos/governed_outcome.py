"""Receipts and detection-aware outcomes for governed chaos runs.

A tool-call receipt reports recovery: only a verified recovery is
``SUCCEEDED``. Detection is a separate verdict. A recovered run whose expected
signal never fired is a detection gap, so :class:`GovernedChaosOutcome` passes
only when the run both recovered and validated its signal. A durable outcome
record lets a replayed duplicate report the original verdict instead of
guessing it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fdai.core.chaos.contract import ExperimentOutcome
from fdai.core.chaos.run_state import ChaosRunSnapshot, ChaosRunState
from fdai.core.chaos.runner import GovernedChaosRunResult
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallReceipt


@dataclass(frozen=True, slots=True)
class GovernedChaosOutcome:
    """One governed run's receipt plus its separate recovery and detection verdicts."""

    receipt: ToolCallReceipt
    run_state: str | None
    recovered: bool
    experiment_outcome: str | None
    detected: bool | None

    @property
    def passed(self) -> bool:
        return (
            self.recovered
            and self.detected is True
            and self.experiment_outcome == ExperimentOutcome.VALIDATED.value
        )


def outcome_record_key(run_id: str) -> str:
    return f"chaos-run-outcome:{run_id}"


def outcome_record(result: GovernedChaosRunResult) -> dict[str, object]:
    """Return the durable detection and injection record written once a run is terminal.

    ``injected`` stays ``None`` when the run never reached the harness in this
    process, so a failed run without a known ``False`` keeps its targets claimed.
    """

    experiment = result.experiment
    return {
        "run_id": result.run_id,
        "state": result.state.state.value,
        "experiment_outcome": experiment.outcome.value if experiment is not None else None,
        "detected": experiment.detected if experiment is not None else None,
        "injected": experiment.injected if experiment is not None else None,
    }


def governed_outcome(result: GovernedChaosRunResult) -> GovernedChaosOutcome:
    experiment = result.experiment
    return GovernedChaosOutcome(
        receipt=governed_receipt(result),
        run_state=result.state.state.value,
        recovered=result.state.state is ChaosRunState.RECOVERED,
        experiment_outcome=experiment.outcome.value if experiment is not None else None,
        detected=experiment.detected if experiment is not None else None,
    )


def replayed_outcome(
    snapshot: ChaosRunSnapshot,
    record: Mapping[str, object] | None,
) -> GovernedChaosOutcome:
    """Echo a terminal run; detection stays unknown without its durable record."""

    matched = record is not None and record.get("run_id") == snapshot.run_id
    experiment_outcome = record.get("experiment_outcome") if matched and record else None
    detected = record.get("detected") if matched and record else None
    return GovernedChaosOutcome(
        receipt=replayed_receipt(snapshot),
        run_state=snapshot.state.value,
        recovered=snapshot.state is ChaosRunState.RECOVERED,
        experiment_outcome=experiment_outcome if isinstance(experiment_outcome, str) else None,
        detected=detected if isinstance(detected, bool) else None,
    )


def closed_outcome(snapshot: ChaosRunSnapshot) -> GovernedChaosOutcome:
    """Report a human-closed run; FDAI never verified its rollback, so it cannot pass."""

    receipt = ToolCallReceipt(
        outcome=ToolCallOutcome.FAILED,
        receipt_ref=snapshot.run_id,
        already_existed=True,
        rollback_succeeded=False,
        detail="closed:human_closure",
    )
    return refused_outcome(receipt, run_state=snapshot.state.value)


def refused_outcome(receipt: ToolCallReceipt, run_state: str | None) -> GovernedChaosOutcome:
    return GovernedChaosOutcome(
        receipt=receipt,
        run_state=run_state,
        recovered=False,
        experiment_outcome=None,
        detected=None,
    )


def replayed_receipt(snapshot: ChaosRunSnapshot) -> ToolCallReceipt:
    """Echo a terminal run without evaluating, injecting, or recovering again."""

    if snapshot.state is ChaosRunState.RECOVERED:
        return ToolCallReceipt(
            outcome=ToolCallOutcome.ALREADY_APPLIED,
            receipt_ref=snapshot.run_id,
            already_existed=True,
            detail="replayed:recovered",
        )
    if snapshot.state is ChaosRunState.DENIED:
        return ToolCallReceipt(
            outcome=ToolCallOutcome.PRECONDITION_FAILED,
            receipt_ref=snapshot.run_id,
            already_existed=True,
            detail="replayed:denied",
        )
    return ToolCallReceipt(
        outcome=ToolCallOutcome.FAILED,
        receipt_ref=snapshot.run_id,
        already_existed=True,
        rollback_succeeded=False,
        detail=f"replayed:{snapshot.state.value}",
    )


def governed_receipt(result: GovernedChaosRunResult) -> ToolCallReceipt:
    """Map a governed run to a receipt; only verified recovery can succeed."""

    state = result.state.state
    if state is ChaosRunState.DENIED:
        reasons = ",".join(result.eligibility.reasons) or "ineligible"
        return ToolCallReceipt(
            outcome=ToolCallOutcome.PRECONDITION_FAILED,
            receipt_ref=result.run_id,
            detail=f"denied:{reasons}",
        )
    recovered = state is ChaosRunState.RECOVERED
    experiment = result.experiment
    if experiment is None:
        return ToolCallReceipt(
            outcome=ToolCallOutcome.STOPPED,
            receipt_ref=result.run_id,
            rollback_succeeded=recovered,
            detail=f"resumed:{state.value}",
        )
    if state is ChaosRunState.FAILED:
        return ToolCallReceipt(
            outcome=ToolCallOutcome.FAILED,
            receipt_ref=result.run_id,
            rollback_succeeded=experiment.reverted,
            detail=f"failed:{experiment.outcome.value}",
        )
    if experiment.stop_reason is not None or experiment.outcome is ExperimentOutcome.ABORTED:
        reason = experiment.stop_reason or experiment.outcome.value
        return ToolCallReceipt(
            outcome=ToolCallOutcome.STOPPED,
            receipt_ref=result.run_id,
            rollback_succeeded=recovered,
            detail=f"stopped:{reason}:{state.value}",
        )
    if recovered:
        return ToolCallReceipt(
            outcome=ToolCallOutcome.SUCCEEDED,
            receipt_ref=result.run_id,
            detail=f"recovered:{experiment.outcome.value}",
        )
    if result.recovery is not None and not result.recovery.succeeded:
        cause = "recovery_incomplete"
    elif result.verification is not None:
        cause = result.verification.outcome.value
    else:
        cause = "unverified"
    return ToolCallReceipt(
        outcome=ToolCallOutcome.FAILED,
        receipt_ref=result.run_id,
        rollback_succeeded=False,
        detail=f"escalated:{cause}",
    )


__all__ = [
    "GovernedChaosOutcome",
    "closed_outcome",
    "governed_outcome",
    "governed_receipt",
    "outcome_record",
    "outcome_record_key",
    "refused_outcome",
    "replayed_outcome",
    "replayed_receipt",
]
