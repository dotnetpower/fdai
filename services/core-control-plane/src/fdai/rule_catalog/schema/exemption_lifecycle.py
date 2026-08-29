"""Exemption lifecycle - scheduled expiry mechanics + ahead-of-expiry alerting.

Pure decision core over the immutable governance catalog's exemptions
(rule-governance.md "Exemptions"): given the current moment and the
configured ahead-of-expiry alert lead time
(``AppConfig.rule_governance.exemption_alert_lead_days``), decide which
``active`` exemption needs an :attr:`ExemptionLifecycleAction.ALERT_AHEAD_OF_EXPIRY`
notification and which one is already past its ``expires_at`` and needs
:attr:`ExemptionLifecycleAction.EXPIRE` (the terminal state transition that
``scripts/governance/exemption-expire.py`` and
:class:`fdai.delivery.exemption_lifecycle.ExemptionLifecycleCoordinator`
apply).

No object-bus involvement (agent-pantheon.instructions.md: "object.override is
not a registered topic"): the exemption catalog is loaded directly at startup,
same as an assignment, and this module is the deterministic decision a
scheduled sweep (in-process coordinator or the standalone CLI) consults.

Pure and I/O-free.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from fdai.rule_catalog.schema.exemption import Exemption, ExemptionState


class ExemptionLifecycleAction(StrEnum):
    """The lifecycle action a scheduled sweep MUST take for one exemption."""

    ALERT_AHEAD_OF_EXPIRY = "alert_ahead_of_expiry"
    EXPIRE = "expire"


@dataclass(frozen=True, slots=True)
class ExemptionLifecycleDecision:
    """One deterministic lifecycle action for one exemption at ``at``."""

    exemption_id: str
    rule_id: str
    action: ExemptionLifecycleAction
    expires_at: datetime
    at: datetime


def plan_exemption_lifecycle(
    exemptions: Sequence[Exemption],
    *,
    now: datetime,
    alert_lead: timedelta,
) -> tuple[ExemptionLifecycleDecision, ...]:
    """Return every lifecycle decision due at ``now``.

    Only ``active`` exemptions are considered - an already ``expired`` or
    ``revoked`` exemption needs no further lifecycle action. For each active
    exemption:

    - ``expires_at <= now`` -> :attr:`ExemptionLifecycleAction.EXPIRE`.
    - otherwise, ``expires_at - now <= alert_lead`` ->
      :attr:`ExemptionLifecycleAction.ALERT_AHEAD_OF_EXPIRY`.
    - otherwise no decision (outside the alert window).

    Ordered by ``exemption_id`` for a stable, replayable sweep. Raises
    :class:`ValueError` on a naive clock or a non-positive lead time - both
    would make "ahead of expiry" ambiguous, so this fails closed rather than
    silently mis-scheduling an alert.
    """
    if now.tzinfo is None:
        raise ValueError("plan_exemption_lifecycle clock MUST be timezone-aware")
    if alert_lead <= timedelta(0):
        raise ValueError("plan_exemption_lifecycle alert_lead MUST be positive")

    decisions: list[ExemptionLifecycleDecision] = []
    for exemption in sorted(exemptions, key=lambda item: item.id):
        if exemption.state is not ExemptionState.ACTIVE:
            continue
        if exemption.expires_at <= now:
            action = ExemptionLifecycleAction.EXPIRE
        elif exemption.expires_at - now <= alert_lead:
            action = ExemptionLifecycleAction.ALERT_AHEAD_OF_EXPIRY
        else:
            continue
        decisions.append(
            ExemptionLifecycleDecision(
                exemption_id=exemption.id,
                rule_id=exemption.rule_id,
                action=action,
                expires_at=exemption.expires_at,
                at=now,
            )
        )
    return tuple(decisions)


__all__ = [
    "ExemptionLifecycleAction",
    "ExemptionLifecycleDecision",
    "plan_exemption_lifecycle",
]
