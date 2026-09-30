"""Action-free Verdict vocabulary shared by the judge and the executor.

In the default observation-first profile, learned patterns and predictions remain advisory
evidence (#1541). Forseti still publishes a Verdict so Saga audits the judgment, Odin counts the
portfolio outcome, and replay stays complete. The Verdict names no ActionType, carries a
``shadow_only`` ceiling, and uses a reason that Thor treats as non-action, so no ActionRun,
approval, rollback, or executor call can follow from it. For a settled arbitration, Thor also
holds the correlation durably, so a later Verdict on it is refused after a restart exactly as a
reused correlation is refused on the governed path.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.agents._framework.topics import stable_idempotency_key
from fdai.shared.contracts.models import Autonomy

#: Reason recorded when learned or predicted input would otherwise reach an action path but the
#: governed execution add-on is not selected. The control loop records the same value.
GOVERNED_EXECUTION_UNSELECTED_REASON = "governed_execution_unselected"

#: Reasons that make an ActionType-free Verdict pure evidence rather than a dispatch request.
NON_ACTION_VERDICT_REASONS: frozenset[str] = frozenset(
    {
        "anomaly_action_unavailable",
        "arbitration_owner_unavailable",
        "no_rule_match",
        GOVERNED_EXECUTION_UNSELECTED_REASON,
    }
)


def is_non_action_verdict(verdict: Mapping[str, Any]) -> bool:
    """Return whether a Verdict names no ActionType and a reason that grants no action."""
    return not verdict.get("action_type") and verdict.get("reason") in NON_ACTION_VERDICT_REASONS


def is_advisory_arbitration_verdict(verdict: Mapping[str, Any]) -> bool:
    """Return whether an ActionType-free advisory Verdict settled a prediction-fed arbitration."""
    return (
        not verdict.get("action_type")
        and verdict.get("reason") == GOVERNED_EXECUTION_UNSELECTED_REASON
        and isinstance(verdict.get("arbitration"), Mapping)
    )


def advisory_verdict(
    *,
    correlation_id: str,
    idempotency_key: str = "",
    resource_id: str,
    advisory_source: str,
    arbitration_outcome: str = "",
) -> dict[str, Any]:
    """Build the action-free Verdict for learned or predicted input without the add-on.

    ``risk_verdict`` keeps the canonical ``hil`` value that every ActionType-free Verdict uses,
    so portfolio and audit consumers see a human-review classification. No consumer routes an
    ActionType-free Verdict to approval, and the ``shadow_only`` ceiling forbids enforcement.
    """
    return {
        "producer_principal": "Forseti",
        "correlation_id": correlation_id,
        "idempotency_key": idempotency_key
        or stable_idempotency_key(
            "forseti-advisory-verdict",
            correlation_id,
            advisory_source,
            resource_id,
            arbitration_outcome,
        ),
        "resource_id": resource_id,
        "action_type": "",
        "risk_verdict": "hil",
        "resolved_autonomy_ceiling": Autonomy.SHADOW_ONLY.value,
        "reason": GOVERNED_EXECUTION_UNSELECTED_REASON,
        "advisory_source": advisory_source,
        "quorum_required": 1,
        "initiator_principal": None,
    }


__all__ = [
    "GOVERNED_EXECUTION_UNSELECTED_REASON",
    "NON_ACTION_VERDICT_REASONS",
    "advisory_verdict",
    "is_advisory_arbitration_verdict",
    "is_non_action_verdict",
]
