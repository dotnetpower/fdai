"""Channel registry + dispatch loop.

The registry is a keyed bag of channel adapters bound at composition
time. The router picks a route via the matrix, then walks
``primary → fallback[0] → …`` until either one channel returns
``delivered=True`` or the list is exhausted, at which point it escalates
to the HIL sink.

Every dispatch (success, fallback, or escalate) writes exactly one audit
entry, matching the safety invariant "every autonomous action MUST leave
an audit entry" from
[`.github/instructions/coding-conventions.instructions.md`]
(../../../../.github/instructions/coding-conventions.instructions.md#safety).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from aiopspilot.shared.providers.notifications.base import (
    ChannelDeliveryError,
    DeliveryReceipt,
    HilEscalationSink,
    NotificationChannel,
    NotificationMessage,
    TrustTier,
)
from aiopspilot.shared.providers.state_store import StateStore

from .matrix import (
    NotificationMatrix,
    RouteSpec,
)


class RouteOutcome(StrEnum):
    """Terminal outcome of one :meth:`NotificationRouter.dispatch` call."""

    DELIVERED = "delivered"
    """One of the channels returned ``delivered=True``."""

    DELIVERED_ON_FALLBACK = "delivered_on_fallback"
    """Primary failed, a fallback succeeded."""

    ESCALATED_TO_HIL = "escalated_to_hil"
    """Every configured channel failed; the message went to the HIL sink."""

    ROUTE_UNRESOLVED = "route_unresolved"
    """A channel-id in the route did not resolve in the registry. Router
    audits the fault and escalates (fail-toward-safety)."""

    TRUST_MISMATCH = "trust_mismatch"
    """A channel in the route does not declare the message's trust tier.
    Router audits + escalates rather than downgrade."""


@dataclass(frozen=True, slots=True)
class RoutingResult:
    """What :meth:`NotificationRouter.dispatch` returns.

    Callers use this to write their own follow-up audit / metric emission
    on top of the router's built-in audit entry.
    """

    outcome: RouteOutcome
    route: RouteSpec
    attempted_channel_ids: tuple[str, ...]
    """Channel-ids the router actually tried, in order."""

    delivered_channel_id: str | None = None
    """Populated on :attr:`RouteOutcome.DELIVERED` /
    :attr:`RouteOutcome.DELIVERED_ON_FALLBACK`."""

    receipts: tuple[DeliveryReceipt, ...] = ()
    """Every :class:`DeliveryReceipt` the adapters returned (in order).
    Excludes attempts that raised :class:`ChannelDeliveryError`."""

    escalation_reason: str | None = None
    """Populated when ``outcome`` is one of the escalation values."""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChannelRegistry:
    """Bag of channel adapters keyed by ``channel_id``.

    The router treats every value uniformly through the
    :class:`NotificationChannel` structural type. The composition root
    is responsible for ensuring an adapter registered under
    ``teams-hil-prd`` really is a Teams adapter (channel-id naming
    convention + adapter's ``channel_kind`` attribute).
    """

    channels: Mapping[str, NotificationChannel] = field(default_factory=dict)

    def resolve(self, channel_id: str) -> NotificationChannel | None:
        return self.channels.get(channel_id)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class NotificationRouter:
    """Dispatches messages according to the matrix + registry.

    Not a Protocol — it is core-owned business logic. Composition wires
    an instance with three seams:

    - :class:`ChannelRegistry` (adapters),
    - :class:`~aiopspilot.shared.providers.state_store.StateStore` (audit),
    - :class:`HilEscalationSink` (fail-safe queue).
    """

    def __init__(
        self,
        *,
        matrix: NotificationMatrix,
        registry: ChannelRegistry,
        audit_store: StateStore,
        hil_sink: HilEscalationSink,
        actor: str = "aiopspilot.core.notifications.router",
    ) -> None:
        self._matrix = matrix
        self._registry = registry
        self._audit_store = audit_store
        self._hil_sink = hil_sink
        self._actor = actor

    async def dispatch(self, message: NotificationMessage) -> RoutingResult:
        """Route ``message`` through the matrix, honouring fallback + escalate.

        Guarantees:

        - Every configured channel is tried at most once, in order.
        - Trust-tier ⊆ channel.trust_tiers is enforced per channel; a
          non-matching channel is skipped (and audited).
        - A missing channel-id in the registry is treated as a
          delivery failure, not a crash.
        - Every dispatch writes exactly one audit entry, then returns
          the :class:`RoutingResult`.
        """
        route = self._matrix.resolve(message.category)
        attempted: list[str] = []
        receipts: list[DeliveryReceipt] = []
        skip_reasons: list[str] = []

        for channel_id in route.channel_ids:
            attempted.append(channel_id)
            channel = self._registry.resolve(channel_id)
            if channel is None:
                skip_reasons.append(f"{channel_id}:unresolved")
                continue

            if not _tier_allowed(channel.trust_tiers, message.trust_tier):
                skip_reasons.append(f"{channel_id}:trust_mismatch")
                continue

            try:
                receipt = await channel.send(message)
            except ChannelDeliveryError as exc:
                skip_reasons.append(f"{channel_id}:raised:{type(exc).__name__}")
                continue

            receipts.append(receipt)
            if receipt.delivered:
                outcome = (
                    RouteOutcome.DELIVERED
                    if channel_id == route.primary
                    else RouteOutcome.DELIVERED_ON_FALLBACK
                )
                await self._audit_dispatch(
                    message=message,
                    route=route,
                    outcome=outcome,
                    attempted=attempted,
                    receipts=receipts,
                    delivered_channel_id=channel_id,
                    escalation_reason=None,
                    skip_reasons=skip_reasons,
                )
                return RoutingResult(
                    outcome=outcome,
                    route=route,
                    attempted_channel_ids=tuple(attempted),
                    delivered_channel_id=channel_id,
                    receipts=tuple(receipts),
                )

            skip_reasons.append(f"{channel_id}:not_delivered:{receipt.error or 'no error text'}")

        # All channels exhausted → escalate.
        outcome = _escalate_outcome(route, receipts, skip_reasons)
        reason = _escalation_reason(outcome, route, skip_reasons)
        await self._hil_sink.escalate(message, reason)
        await self._audit_dispatch(
            message=message,
            route=route,
            outcome=outcome,
            attempted=attempted,
            receipts=receipts,
            delivered_channel_id=None,
            escalation_reason=reason,
            skip_reasons=skip_reasons,
        )
        return RoutingResult(
            outcome=outcome,
            route=route,
            attempted_channel_ids=tuple(attempted),
            delivered_channel_id=None,
            receipts=tuple(receipts),
            escalation_reason=reason,
        )

    # ------------------------------------------------------------------
    # audit helper
    # ------------------------------------------------------------------

    async def _audit_dispatch(
        self,
        *,
        message: NotificationMessage,
        route: RouteSpec,
        outcome: RouteOutcome,
        attempted: list[str],
        receipts: list[DeliveryReceipt],
        delivered_channel_id: str | None,
        escalation_reason: str | None,
        skip_reasons: list[str],
    ) -> None:
        entry = {
            "actor": self._actor,
            "action_kind": "notification.route",
            "outcome": outcome.value,
            "category": message.category,
            "trust_tier": message.trust_tier.value,
            "correlation_id": message.correlation_id,
            "audit_id": message.audit_id,
            "route_category": route.category,
            "route_primary": route.primary,
            "route_fallback": list(route.fallback),
            "route_on_all_fail": route.on_all_fail.value,
            "attempted_channel_ids": list(attempted),
            "delivered_channel_id": delivered_channel_id,
            "receipts": [_receipt_dict(r) for r in receipts],
            "skip_reasons": skip_reasons,
            "escalation_reason": escalation_reason,
            "recorded_at": datetime.now(tz=UTC).isoformat(),
        }
        await self._audit_store.append_audit_entry(entry)


# ---------------------------------------------------------------------------
# helpers (module-level so they stay pure and unit-testable)
# ---------------------------------------------------------------------------


def _tier_allowed(channel_tiers: frozenset[TrustTier], required: TrustTier) -> bool:
    """Return True iff the channel is authorised for the message tier.

    An empty ``channel_tiers`` frozenset is treated as "accepts any" so
    the base :class:`~aiopspilot.shared.providers.notifications.NotificationChannel`
    contract stays usable for adapters that declare their scope elsewhere.
    Config-driven forks SHOULD populate the frozenset explicitly.
    """
    if not channel_tiers:
        return True
    return required in channel_tiers


def _receipt_dict(receipt: DeliveryReceipt) -> dict[str, str | bool | None]:
    return {
        "channel_kind": receipt.channel_kind.value,
        "channel_id": receipt.channel_id,
        "delivered": receipt.delivered,
        "provider_message_id": receipt.provider_message_id,
        "error": receipt.error,
    }


def _escalate_outcome(
    route: RouteSpec,
    receipts: list[DeliveryReceipt],
    skip_reasons: list[str],
) -> RouteOutcome:
    # If every attempted channel was unresolved or trust-mismatched
    # (i.e. we never got a delivery attempt), surface that specific
    # failure mode. Otherwise it is a plain "all channels down".
    if not receipts:
        if any(r.endswith(":trust_mismatch") for r in skip_reasons):
            return RouteOutcome.TRUST_MISMATCH
        if all(r.endswith(":unresolved") for r in skip_reasons) and skip_reasons:
            return RouteOutcome.ROUTE_UNRESOLVED
    return RouteOutcome.ESCALATED_TO_HIL


def _escalation_reason(
    outcome: RouteOutcome,
    route: RouteSpec,
    skip_reasons: list[str],
) -> str:
    if outcome is RouteOutcome.ROUTE_UNRESOLVED:
        return (
            f"route {route.category!r}: every channel id in "
            f"{list(route.channel_ids)} is unresolved in the registry"
        )
    if outcome is RouteOutcome.TRUST_MISMATCH:
        return (
            f"route {route.category!r}: no channel in "
            f"{list(route.channel_ids)} declares the required trust tier"
        )
    return f"route {route.category!r}: all channels exhausted (reasons={skip_reasons})"


__all__ = [
    "ChannelRegistry",
    "NotificationRouter",
    "RouteOutcome",
    "RoutingResult",
]
