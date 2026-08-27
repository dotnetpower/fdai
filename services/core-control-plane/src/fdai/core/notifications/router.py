"""Channel registry plus failover and durable fan-out dispatch.

The registry contains named adapters and binding enablement resolved at
composition time. Legacy A1/A3 routes retain ordered failover. A2/A4 fan-out
routes freeze their eligible target set and persist one delivery per channel.

Every dispatch (success, fallback, or escalate) writes exactly one audit
entry, matching the safety invariant "every autonomous action MUST leave
an audit entry" from
[`.github/instructions/coding-conventions.instructions.md`]
(../../../../.github/instructions/coding-conventions.instructions.md#safety).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum

from fdai.shared.providers.notifications.base import (
    ChannelAmbiguousError,
    ChannelDeliveryError,
    DeliveryReceipt,
    HilEscalationSink,
    NotificationChannel,
    NotificationMessage,
    TrustTier,
)
from fdai.shared.providers.state_store import StateStore

from .delivery import (
    ChannelDeliveryRecord,
    ChannelDeliveryState,
    DeliveryClaimStatus,
    InMemoryNotificationDeliveryStore,
    NotificationDeliveryStore,
    NotificationDispatchPlan,
)
from .matrix import (
    DeliveryMode,
    NotificationMatrix,
    RouteSpec,
)
from .renderer import NotificationCatalog, default_catalog


class RouteOutcome(StrEnum):
    """Outcome of one :meth:`NotificationRouter.dispatch` call."""

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

    DELIVERED_ALL = "delivered_all"
    PARTIALLY_DELIVERED = "partially_delivered"
    FAILED_ALL = "failed_all"
    NO_ELIGIBLE_CHANNELS = "no_eligible_channels"


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

    target_channel_ids: tuple[str, ...] = ()
    excluded_channels: Mapping[str, str] = field(default_factory=dict)
    deliveries: tuple[ChannelDeliveryRecord, ...] = ()
    terminal: bool = True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChannelBinding:
    """Operator enablement and validated configuration for one named channel."""

    channel_id: str
    enabled: bool = True
    configured: bool = True
    trust_tiers: frozenset[TrustTier] = field(default_factory=frozenset)


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
    bindings: Mapping[str, ChannelBinding] = field(default_factory=dict)

    def resolve(self, channel_id: str) -> NotificationChannel | None:
        return self.channels.get(channel_id)

    def binding(self, channel_id: str) -> ChannelBinding:
        configured = self.bindings.get(channel_id)
        if configured is not None:
            return configured
        return ChannelBinding(
            channel_id=channel_id,
            enabled=True,
            configured=channel_id in self.channels,
        )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class NotificationRouter:
    """Dispatches messages according to the matrix + registry.

    Not a Protocol - it is core-owned business logic. Composition wires
    an instance with three seams:

    - :class:`ChannelRegistry` (adapters),
    - :class:`~fdai.shared.providers.state_store.StateStore` (audit),
    - :class:`HilEscalationSink` (fail-safe queue).
    """

    def __init__(
        self,
        *,
        matrix: NotificationMatrix,
        registry: ChannelRegistry,
        audit_store: StateStore,
        hil_sink: HilEscalationSink,
        renderer: NotificationCatalog | None = None,
        delivery_store: NotificationDeliveryStore | None = None,
        actor: str = "fdai.core.notifications.router",
        max_parallelism: int = 4,
        lease_seconds: int = 60,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 0.25,
        confirmation_timeout_seconds: int = 300,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if (
            max_parallelism < 1
            or lease_seconds < 1
            or max_attempts < 1
            or retry_backoff_seconds < 0
            or confirmation_timeout_seconds < 1
        ):
            raise ValueError("notification delivery bounds are invalid")
        self._matrix = matrix
        self._registry = registry
        self._audit_store = audit_store
        self._hil_sink = hil_sink
        self._renderer = renderer if renderer is not None else default_catalog()
        self._delivery_store = (
            delivery_store if delivery_store is not None else InMemoryNotificationDeliveryStore()
        )
        self._actor = actor
        self._max_parallelism = max_parallelism
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._confirmation_timeout_seconds = confirmation_timeout_seconds
        self._sleep = sleep

    async def dispatch(self, message: NotificationMessage) -> RoutingResult:
        """Route ``message`` through failover or durable fan-out semantics.

        Guarantees:

        - Failover channels are tried at most once, in order.
        - Fan-out channels are isolated and retried within bounded attempts.
        - Trust-tier ⊆ channel.trust_tiers is enforced per channel; a
          non-matching channel is skipped (and audited).
        - A missing channel-id in the registry is treated as a
          delivery failure, not a crash.
        - Every dispatch writes exactly one audit entry, then returns
          the :class:`RoutingResult`.
        """
        route = self._matrix.resolve(message.category)
        if route.delivery_mode is DeliveryMode.FANOUT:
            return await self._dispatch_fanout(message, route)

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
                receipt = await channel.send(self._render(message, channel_id))
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

    async def _dispatch_fanout(
        self,
        message: NotificationMessage,
        route: RouteSpec,
    ) -> RoutingResult:
        audit_id = _dispatch_audit_id(message)
        targets, excluded = self._target_set(route, message.trust_tier)
        now = datetime.now(tz=UTC)
        plan = await self._delivery_store.create_plan(
            audit_id=audit_id,
            target_channel_ids=targets,
            excluded_channels=excluded,
            now=now,
        )

        if not plan.target_channel_ids:
            reason = f"route {route.category!r}: no enabled, configured, trust-allowed channels"
            await self._hil_sink.escalate(message, reason)
            result = RoutingResult(
                outcome=RouteOutcome.NO_ELIGIBLE_CHANNELS,
                route=route,
                attempted_channel_ids=(),
                escalation_reason=reason,
                target_channel_ids=(),
                excluded_channels=plan.excluded_channels,
                deliveries=(),
                terminal=True,
            )
            await self._audit_dispatch_result(message, result)
            return result

        semaphore = asyncio.Semaphore(self._max_parallelism)

        async def deliver(channel_id: str) -> None:
            async with semaphore:
                await self._deliver_target(
                    message=message,
                    audit_id=audit_id,
                    channel_id=channel_id,
                )

        results = await asyncio.gather(
            *(deliver(channel_id) for channel_id in plan.target_channel_ids),
            return_exceptions=True,
        )
        unexpected = next((item for item in results if isinstance(item, BaseException)), None)
        if unexpected is not None:
            raise unexpected

        snapshot = await self._delivery_store.snapshot(
            audit_id=audit_id,
            now=datetime.now(tz=UTC),
        )
        outcome = _fanout_outcome(snapshot)
        terminal_reason: str | None = None
        if outcome is RouteOutcome.FAILED_ALL and snapshot.terminal:
            terminal_reason = (
                f"route {route.category!r}: every fanout target reached terminal failure"
            )
            await self._hil_sink.escalate(message, terminal_reason)

        receipts = tuple(
            receipt
            for item in snapshot.deliveries
            if (receipt := _record_receipt(item, self._registry)) is not None
        )
        delivered = tuple(
            item.channel_id
            for item in snapshot.deliveries
            if item.state is ChannelDeliveryState.DELIVERED
        )
        result = RoutingResult(
            outcome=outcome,
            route=route,
            attempted_channel_ids=tuple(
                item.channel_id for item in snapshot.deliveries if item.attempts > 0
            ),
            delivered_channel_id=delivered[0] if delivered else None,
            receipts=receipts,
            escalation_reason=terminal_reason,
            target_channel_ids=snapshot.target_channel_ids,
            excluded_channels=snapshot.excluded_channels,
            deliveries=snapshot.deliveries,
            terminal=snapshot.terminal,
        )
        await self._audit_dispatch_result(message, result)
        return result

    def _target_set(
        self,
        route: RouteSpec,
        trust_tier: TrustTier,
    ) -> tuple[tuple[str, ...], dict[str, str]]:
        targets: list[str] = []
        excluded: dict[str, str] = {}
        for channel_id in route.channel_ids:
            binding = self._registry.binding(channel_id)
            if not binding.enabled:
                excluded[channel_id] = "disabled"
                continue
            if not binding.configured:
                excluded[channel_id] = "configuration_invalid"
                continue
            channel = self._registry.resolve(channel_id)
            if channel is None:
                excluded[channel_id] = "unresolved"
                continue
            if binding.trust_tiers and trust_tier not in binding.trust_tiers:
                excluded[channel_id] = "binding_trust_mismatch"
                continue
            if not _tier_allowed(channel.trust_tiers, trust_tier):
                excluded[channel_id] = "adapter_trust_mismatch"
                continue
            targets.append(channel_id)
        return tuple(targets), excluded

    async def _deliver_target(
        self,
        *,
        message: NotificationMessage,
        audit_id: str,
        channel_id: str,
    ) -> None:
        while True:
            now = datetime.now(tz=UTC)
            claim = await self._delivery_store.claim(
                audit_id=audit_id,
                channel_id=channel_id,
                now=now,
                lease_seconds=self._lease_seconds,
                max_attempts=self._max_attempts,
            )
            if claim.status is not DeliveryClaimStatus.CLAIMED:
                return
            token = claim.record.token
            if token is None:
                raise RuntimeError("claimed notification delivery has no token")
            channel = self._registry.resolve(channel_id)
            if channel is None:
                await self._record_retryable_failure(
                    audit_id=audit_id,
                    channel_id=channel_id,
                    token=token,
                    attempt=claim.record.attempts,
                    error="channel binding became unresolved",
                )
                continue
            try:
                receipt = await channel.send(self._render(message, channel_id))
            except ChannelAmbiguousError as exc:
                await self._delivery_store.record_result(
                    audit_id=audit_id,
                    channel_id=channel_id,
                    token=token,
                    state=ChannelDeliveryState.AMBIGUOUS,
                    at=datetime.now(tz=UTC),
                    error=str(exc),
                )
                return
            except ChannelDeliveryError as exc:
                await self._record_retryable_failure(
                    audit_id=audit_id,
                    channel_id=channel_id,
                    token=token,
                    attempt=claim.record.attempts,
                    error=str(exc),
                )
                continue

            if receipt.delivered:
                state = ChannelDeliveryState.DELIVERED
            elif receipt.accepted:
                state = ChannelDeliveryState.ACCEPTED
            else:
                await self._record_retryable_failure(
                    audit_id=audit_id,
                    channel_id=channel_id,
                    token=token,
                    attempt=claim.record.attempts,
                    error=receipt.error or "channel reported delivery failure",
                )
                continue
            await self._delivery_store.record_result(
                audit_id=audit_id,
                channel_id=channel_id,
                token=token,
                state=state,
                at=datetime.now(tz=UTC),
                confirmation_timeout_seconds=(
                    self._confirmation_timeout_seconds
                    if state is ChannelDeliveryState.ACCEPTED
                    else None
                ),
                provider_message_id=receipt.provider_message_id,
            )
            return

    async def _record_retryable_failure(
        self,
        *,
        audit_id: str,
        channel_id: str,
        token: str,
        attempt: int,
        error: str,
    ) -> None:
        delay = self._retry_backoff_seconds * (2 ** max(0, attempt - 1))
        await self._delivery_store.record_result(
            audit_id=audit_id,
            channel_id=channel_id,
            token=token,
            state=ChannelDeliveryState.RETRYABLE_FAILED,
            at=datetime.now(tz=UTC),
            retry_after_seconds=delay,
            error=error,
        )
        if delay:
            await self._sleep(delay)

    # ------------------------------------------------------------------
    # per-channel localization (Option C)
    # ------------------------------------------------------------------

    def _render(self, message: NotificationMessage, channel_id: str) -> NotificationMessage:
        """Localize ``title`` / ``body_markdown`` for the channel's locale.

        A message without a ``template_key`` - or one whose key the catalog
        cannot fully render - is sent as-is (its baked English title/body), so a
        missing or malformed key degrades to the English source rather than
        leaking the key string. The audit entry always uses the original
        (English) message, so only the channel-facing copy is localized - the L0
        record is intact.
        """
        if message.template_key is None or not self._renderer.has(message.template_key):
            return message
        title, body = self._renderer.render(
            message.template_key,
            message.params,
            self._matrix.locale_for(channel_id),
        )
        return replace(message, title=title, body_markdown=body)

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

    async def _audit_dispatch_result(
        self,
        message: NotificationMessage,
        result: RoutingResult,
    ) -> None:
        entry = {
            "actor": self._actor,
            "action_kind": "notification.route",
            "outcome": result.outcome.value,
            "category": message.category,
            "trust_tier": message.trust_tier.value,
            "correlation_id": message.correlation_id,
            "audit_id": message.audit_id,
            "route_category": result.route.category,
            "delivery_mode": result.route.delivery_mode.value,
            "declared_channel_ids": list(result.route.channel_ids),
            "target_channel_ids": list(result.target_channel_ids),
            "excluded_channels": dict(result.excluded_channels),
            "attempted_channel_ids": list(result.attempted_channel_ids),
            "deliveries": [_delivery_dict(item) for item in result.deliveries],
            "terminal": result.terminal,
            "escalation_reason": result.escalation_reason,
            "recorded_at": datetime.now(tz=UTC).isoformat(),
        }
        await self._audit_store.append_audit_entry(entry)


# ---------------------------------------------------------------------------
# helpers (module-level so they stay pure and unit-testable)
# ---------------------------------------------------------------------------


def _tier_allowed(channel_tiers: frozenset[TrustTier], required: TrustTier) -> bool:
    """Return True iff the channel is authorised for the message tier.

    An empty ``channel_tiers`` frozenset is treated as "accepts any" so
    the base :class:`~fdai.shared.providers.notifications.NotificationChannel`
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
        "accepted": receipt.accepted,
        "provider_message_id": receipt.provider_message_id,
        "error": receipt.error,
    }


def _delivery_dict(record: ChannelDeliveryRecord) -> dict[str, str | int | None]:
    return {
        "channel_id": record.channel_id,
        "state": record.state.value,
        "attempts": record.attempts,
        "provider_message_id": record.provider_message_id,
        "error": record.error,
    }


def _dispatch_audit_id(message: NotificationMessage) -> str:
    if message.audit_id:
        return message.audit_id
    material = f"{message.category}\0{message.correlation_id}".encode()
    return f"notification:{hashlib.sha256(material).hexdigest()}"


def _fanout_outcome(plan: NotificationDispatchPlan) -> RouteOutcome:
    delivered = sum(item.state is ChannelDeliveryState.DELIVERED for item in plan.deliveries)
    if delivered == len(plan.deliveries):
        return RouteOutcome.DELIVERED_ALL
    if delivered:
        return RouteOutcome.PARTIALLY_DELIVERED
    return RouteOutcome.FAILED_ALL


def _record_receipt(
    record: ChannelDeliveryRecord,
    registry: ChannelRegistry,
) -> DeliveryReceipt | None:
    channel = registry.resolve(record.channel_id)
    if channel is None:
        return None
    return DeliveryReceipt(
        channel_kind=channel.channel_kind,
        channel_id=record.channel_id,
        delivered=record.state is ChannelDeliveryState.DELIVERED,
        accepted=record.state is ChannelDeliveryState.ACCEPTED,
        provider_message_id=record.provider_message_id,
        error=record.error,
    )


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
    "ChannelBinding",
    "ChannelRegistry",
    "NotificationRouter",
    "RouteOutcome",
    "RoutingResult",
]
