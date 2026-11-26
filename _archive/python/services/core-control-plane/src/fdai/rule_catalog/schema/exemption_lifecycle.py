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

import hashlib
import json
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


@dataclass(frozen=True, slots=True)
class ExemptionAssignmentBinding:
    """Exact reviewed assignment target used by an expiry command."""

    assignment_id: str
    assignment_version: str
    scope_ref: str

    def __post_init__(self) -> None:
        if not self.assignment_id.strip():
            raise ValueError("assignment_id MUST be non-empty")
        if not self.assignment_version.strip():
            raise ValueError("assignment_version MUST be non-empty")
        if not self.scope_ref.strip():
            raise ValueError("scope_ref MUST be non-empty")


@dataclass(frozen=True, slots=True)
class ExemptionExpiryCommand:
    """Versioned proposal to reapply one assignment after exact exemption expiry."""

    schema_version: str
    idempotency_key: str
    exemption_id: str
    active_exemption_revision: str
    expired_exemption_revision: str
    assignment_id: str
    assignment_version: str
    rule_id: str
    scope_ref: str
    scope: dict[str, str | None]
    expires_at: datetime
    issued_at: datetime

    def action_params(self) -> dict[str, object]:
        """Return the closed argument object validated by the registered ActionType."""

        return {
            "exemption_id": self.exemption_id,
            "active_exemption_revision": self.active_exemption_revision,
            "expired_exemption_revision": self.expired_exemption_revision,
            "assignment_id": self.assignment_id,
            "assignment_version": self.assignment_version,
            "rule_id": self.rule_id,
            "scope_ref": self.scope_ref,
            "scope": dict(self.scope),
            "expires_at": self.expires_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ExemptionExpiryDigestItem:
    """One exact exemption revision named in the ahead-of-expiry digest."""

    exemption_id: str
    exemption_revision: str
    rule_id: str
    requested_by: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ExemptionExpiryDigest:
    """Bounded notification payload with no decision or execution authority."""

    schema_version: str
    generated_at: datetime
    items: tuple[ExemptionExpiryDigestItem, ...]


def exemption_revision(exemption: Exemption, *, state: ExemptionState | None = None) -> str:
    """Return a stable content revision for the selected exemption state."""

    value = exemption if state is None else exemption.model_copy(update={"state": state})
    payload = json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def build_exemption_expiry_command(
    exemption: Exemption,
    binding: ExemptionAssignmentBinding,
    *,
    issued_at: datetime,
) -> ExemptionExpiryCommand:
    """Build a replay-stable command without granting reapply authority."""

    if issued_at.tzinfo is None:
        raise ValueError("expiry command issued_at MUST include timezone")
    if exemption.state is not ExemptionState.ACTIVE:
        raise ValueError("expiry command requires an active exemption snapshot")
    if exemption.expires_at > issued_at:
        raise ValueError("expiry command cannot be issued before expires_at")

    active_revision = exemption_revision(exemption)
    expired_revision = exemption_revision(exemption, state=ExemptionState.EXPIRED)
    identity = ":".join(
        (
            exemption.id,
            active_revision,
            expired_revision,
            binding.assignment_id,
            binding.assignment_version,
        )
    )
    idempotency_key = f"exemption-expiry:{hashlib.sha256(identity.encode()).hexdigest()}"
    return ExemptionExpiryCommand(
        schema_version="1.0.0",
        idempotency_key=idempotency_key,
        exemption_id=exemption.id,
        active_exemption_revision=active_revision,
        expired_exemption_revision=expired_revision,
        assignment_id=binding.assignment_id,
        assignment_version=binding.assignment_version,
        rule_id=exemption.rule_id,
        scope_ref=binding.scope_ref,
        scope={
            "subscription_id": str(exemption.scope.subscription_id),
            "resource_group": exemption.scope.resource_group,
            "resource_ref": exemption.scope.resource_ref,
        },
        expires_at=exemption.expires_at,
        issued_at=issued_at,
    )


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
    "ExemptionAssignmentBinding",
    "ExemptionExpiryCommand",
    "ExemptionExpiryDigest",
    "ExemptionExpiryDigestItem",
    "ExemptionLifecycleAction",
    "ExemptionLifecycleDecision",
    "build_exemption_expiry_command",
    "exemption_revision",
    "plan_exemption_lifecycle",
]
