"""Resolve the authoritative outcome one dispatched workflow action reported.

A dispatched action is not a completed action. This module owns the single
place a dispatched step's outcome becomes provable: it prefers authoritative
resolver evidence over caller-supplied context claims, re-verifies the outcome
against its effect receipt, and carries the finalized safeguard bundle digest
that a successful outcome MUST be bound to.

Nothing here executes, approves, or verifies an effect on its own. An outage,
a missing receipt, or a missing bundle digest resolves to an explicit waiting
disposition so the Process stays held instead of advancing on weak evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from fdai.core.workflow.workflow_runtime import (
    WorkflowOutcomeResolver,
    WorkflowOutcomeVerifier,
)


class ActionOutcomeDisposition(StrEnum):
    """Whether one dispatched action outcome is provable yet.

    The waiting members carry the exact step reason the executor records, so
    the distinction between missing outcome evidence and an unusable verifier
    stays visible in the Process event stream.
    """

    RESOLVED = "resolved"
    WAITING_FOR_OUTCOME = "waiting_for_action_outcome"
    WAITING_FOR_VERIFIER = "waiting_for_action_outcome_verifier"


@dataclass(frozen=True, slots=True)
class ActionOutcomeResolution:
    """One resolved action outcome and the safeguard evidence behind it."""

    disposition: ActionOutcomeDisposition
    outcome: str | None = None
    safeguard_bundle_digest: str | None = None


_WAITING_FOR_OUTCOME = ActionOutcomeResolution(
    disposition=ActionOutcomeDisposition.WAITING_FOR_OUTCOME,
)
_WAITING_FOR_VERIFIER = ActionOutcomeResolution(
    disposition=ActionOutcomeDisposition.WAITING_FOR_VERIFIER,
)


def reported_bundle_digest(context: Mapping[str, str], step_id: str) -> str | None:
    """Return the safeguard bundle digest the dispatch context reported."""

    return context.get(f"action.{step_id}.safeguard_bundle_digest", "").strip() or None


async def resolve_action_outcome(
    verifier: WorkflowOutcomeVerifier,
    *,
    process_id: str,
    step_id: str,
    proposal_ref: str,
    context: Mapping[str, str],
) -> ActionOutcomeResolution:
    """Resolve and re-verify the outcome one dispatched action step reported.

    A resolver-backed verifier owns the evidence outright, so its resolution
    replaces every caller-supplied context claim. Without a resolver the
    context claim is admitted only when it carries a terminal status, an
    effect receipt, and - for a success claim - a safeguard bundle digest.
    """

    status = context.get(f"action.{step_id}.status")
    receipt_ref = context.get(f"action.{step_id}.receipt_ref", "").strip()
    bundle_digest = reported_bundle_digest(context, step_id)
    outcome = "succeeded" if status == "verified" else "failed"
    try:
        if isinstance(verifier, WorkflowOutcomeResolver):
            resolved = await verifier.resolve(
                process_id=process_id,
                step_id=step_id,
                proposal_ref=proposal_ref,
            )
            if resolved is None:
                return _WAITING_FOR_OUTCOME
            outcome = resolved.outcome
            receipt_ref = resolved.receipt_ref
            bundle_digest = resolved.safeguard_bundle_digest
        elif (
            status not in {"verified", "failed"}
            or not receipt_ref
            or (status == "verified" and not bundle_digest)
        ):
            return _WAITING_FOR_OUTCOME
        accepted = await verifier.verify(
            process_id=process_id,
            step_id=step_id,
            proposal_ref=proposal_ref,
            outcome=outcome,
            receipt_ref=receipt_ref,
        )
    except Exception:  # noqa: BLE001 - verifier outage holds the Process
        accepted = False
    if not accepted:
        return _WAITING_FOR_VERIFIER
    return ActionOutcomeResolution(
        disposition=ActionOutcomeDisposition.RESOLVED,
        outcome=outcome,
        safeguard_bundle_digest=bundle_digest,
    )


__all__ = [
    "ActionOutcomeDisposition",
    "ActionOutcomeResolution",
    "reported_bundle_digest",
    "resolve_action_outcome",
]
