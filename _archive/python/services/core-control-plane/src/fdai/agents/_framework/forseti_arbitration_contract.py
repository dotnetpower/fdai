"""Small contract helpers for Forseti's arbitration-decision consumer."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from functools import lru_cache
from typing import Any

from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.shared.contracts.models import Autonomy

_ARBITRATION_DECISION_TOPIC = "object.arbitration-decision"


@lru_cache(maxsize=1)
def arbitration_owner() -> str | None:
    return load_pantheon().owner_of_topic(_ARBITRATION_DECISION_TOPIC)


def winning_domain_disposition_allows_resolution(
    decision: Mapping[str, Any],
    winning_domain: str,
) -> bool:
    dispositions = decision.get("dispositions")
    if not isinstance(dispositions, Mapping) or not winning_domain:
        return True
    return dispositions.get(winning_domain) == "win"


def autonomy_ceiling_for_risk_verdict(risk_verdict: str) -> str:
    return (
        Autonomy.ENFORCE_AUTO.value
        if risk_verdict == "auto"
        else Autonomy.ENFORCE_HIL.value
        if risk_verdict == "hil"
        else Autonomy.SHADOW_ONLY.value
    )


def arbitration_action_idempotency_key(
    correlation_id: str,
    action_type: str,
    selected_option_id: str,
    resource_id: str,
    proposal_id: str = "",
) -> str:
    return stable_idempotency_key(
        "forseti-arbitration-action",
        correlation_id,
        action_type,
        selected_option_id,
        resource_id,
        proposal_id,
    )


def remember_arbitration_winner(
    arbitrations: MutableMapping[str, str],
    correlation_id: str,
    winning_domain: str,
    max_resources: int,
) -> None:
    arbitrations[correlation_id] = winning_domain
    if len(arbitrations) > max_resources:
        arbitrations.pop(next(iter(arbitrations)))


__all__ = [
    "arbitration_owner",
    "arbitration_action_idempotency_key",
    "autonomy_ceiling_for_risk_verdict",
    "remember_arbitration_winner",
    "winning_domain_disposition_allows_resolution",
]
