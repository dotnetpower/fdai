"""Scheduled exemption lifecycle sweep for the Core runtime.

The worker runs the existing idempotent coordinator on an interval and delivers the ahead-of-expiry
digest through the workload's notification router. It publishes no expiry command and mutates no
catalog, so it carries no activation, approval, or execution authority. Delivery is retried by the
coordinator's claim state, and a repeated digest reuses one audit id, so a restart or a second
replica never sends it twice.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from fdai.core.notifications.router import RouteOutcome, RoutingResult
from fdai.delivery.exemption_lifecycle import ExemptionLifecycleCoordinator
from fdai.rule_catalog.schema.exemption import (
    Exemption,
    load_exemption_from_mapping,
    parse_exemption_json,
)
from fdai.rule_catalog.schema.exemption_lifecycle import ExemptionExpiryDigest
from fdai.shared.providers.notifications.base import (
    NotificationMessage,
    Severity,
    TrustTier,
)
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger("fdai.runtime.exemption_lifecycle")

DIGEST_CATEGORY = "operational_alert"
_MAX_LISTED_ITEMS = 20
_DELIVERED = frozenset(
    {RouteOutcome.DELIVERED, RouteOutcome.DELIVERED_ON_FALLBACK, RouteOutcome.DELIVERED_ALL}
)


def load_catalog_exemptions(catalog_root: Path) -> tuple[Exemption, ...]:
    """Load the installed exemptions, failing closed on any invalid or duplicate file.

    Startup already validated the whole governance catalog; this reads only the exemptions.
    """

    directory = catalog_root / "exemptions"
    if not directory.is_dir():
        return ()
    loaded: dict[str, Exemption] = {}
    for path in sorted(directory.glob("*.json")):
        exemption = load_exemption_from_mapping(parse_exemption_json(path.read_text("utf-8")))
        if exemption.id in loaded:
            raise ValueError(f"duplicate exemption id in {path.name}")
        loaded[exemption.id] = exemption
    return tuple(loaded.values())


class _Router(Protocol):
    async def dispatch(self, message: NotificationMessage) -> RoutingResult: ...


class RouterExemptionLifecycleNotifier:
    """Deliver the expiry digest as one idempotent operational alert."""

    def __init__(self, router: _Router) -> None:
        self._router = router

    async def notify_expiry_digest(self, *, digest: ExemptionExpiryDigest) -> None:
        message = build_digest_message(digest)
        result = await self._router.dispatch(message)
        if result.outcome not in _DELIVERED:
            raise RuntimeError(f"exemption expiry digest was not delivered: {result.outcome.value}")


def build_digest_message(digest: ExemptionExpiryDigest) -> NotificationMessage:
    """Build the bounded alert; the audit id is stable for the exact exemption revisions."""

    items = sorted(digest.items, key=lambda item: item.exemption_id)
    identity = hashlib.sha256(
        "\n".join(f"{item.exemption_id}:{item.exemption_revision}" for item in items).encode()
    ).hexdigest()[:32]
    lines = [
        f"- `{item.exemption_id}` for rule `{item.rule_id}` expires {item.expires_at.isoformat()}"
        for item in items[:_MAX_LISTED_ITEMS]
    ]
    if len(items) > _MAX_LISTED_ITEMS:
        lines.append(f"- and {len(items) - _MAX_LISTED_ITEMS} more")
    return NotificationMessage(
        category=DIGEST_CATEGORY,
        trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
        correlation_id=f"exemption-expiry-digest:{identity}",
        title=f"{len(items)} exemption(s) expire soon",
        body_markdown=(
            "These exemptions are approaching their expiry. Review them before they lapse; "
            "this notice requires no action to proceed.\n\n" + "\n".join(lines)
        ),
        severity=Severity.WARN,
        audit_id=f"exemption-expiry-digest:{identity}",
        metadata={"purpose": "exemption-expiry-digest", "item_count": str(len(items))},
    )


class ExemptionLifecycleWorker:
    """Run the lifecycle coordinator until stopped; a failed sweep never stops the loop."""

    def __init__(
        self,
        coordinator: ExemptionLifecycleCoordinator,
        *,
        interval_seconds: float,
    ) -> None:
        if not 1.0 <= interval_seconds <= 86_400.0:
            raise ValueError("exemption lifecycle interval MUST be between 1 second and 24 hours")
        self._coordinator = coordinator
        self._interval = interval_seconds

    async def run_once(self) -> None:
        try:
            result = await self._coordinator.run_once()
        except Exception as exc:  # noqa: BLE001 - the next tick retries; claim state is durable
            _LOGGER.warning(
                "exemption_lifecycle_sweep_failed", extra={"error_kind": type(exc).__name__}
            )
            return
        _LOGGER.info(
            "exemption_lifecycle_sweep_completed",
            extra={
                "evaluated": result.evaluated,
                "alerted": result.alerted,
                "expired_due": result.expired_due,
            },
        )

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._interval)
            except TimeoutError:
                continue


def build_exemption_lifecycle_worker(
    *,
    exemptions: Sequence[Exemption],
    audit_store: StateStore,
    notification_router: _Router,
    alert_lead_days: int,
    environment: Mapping[str, str],
) -> ExemptionLifecycleWorker | None:
    """Compose the worker, or none when no exemption exists or the operator disabled it."""

    if environment.get("FDAI_EXEMPTION_LIFECYCLE_ENABLED", "true").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return None
    if not exemptions:
        return None
    interval = float(environment.get("FDAI_EXEMPTION_LIFECYCLE_INTERVAL_SECONDS", "3600"))
    coordinator = ExemptionLifecycleCoordinator(
        exemptions=exemptions,
        notifier=RouterExemptionLifecycleNotifier(notification_router),
        audit_store=audit_store,
        alert_lead_days=alert_lead_days,
    )
    return ExemptionLifecycleWorker(coordinator, interval_seconds=interval)


async def build_runtime_exemption_lifecycle_worker(
    container: Any,
    http_client: Any,
    state_store: StateStore,
    environment: Mapping[str, str],
) -> ExemptionLifecycleWorker | None:
    """Compose the worker from the installed catalog and the workload's own notification router."""

    from fdai.delivery.notifications.local_binding import resolve_local_notification_endpoints
    from fdai.runtime.configuration import _resolve_catalog_root
    from fdai.runtime.delivery import _build_notification_router

    exemptions = load_catalog_exemptions(_resolve_catalog_root())
    if not exemptions:
        return None
    try:
        router = _build_notification_router(
            state_store,
            http_client=http_client,
            endpoint_overrides=await resolve_local_notification_endpoints(
                environment=environment,
                state_store=state_store,
                key_material=environment.get("FDAI_STATE_STORE_DSN", "").strip() or None,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - an optional sweep never blocks Core startup
        _LOGGER.error("exemption_lifecycle_unavailable", extra={"error_kind": type(exc).__name__})
        return None
    return build_exemption_lifecycle_worker(
        exemptions=exemptions,
        audit_store=state_store,
        notification_router=router,
        alert_lead_days=container.config.rule_governance.exemption_alert_lead_days,
        environment=environment,
    )
