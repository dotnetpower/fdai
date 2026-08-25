"""Incident lifecycle assembly for the headless control-plane process."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from psycopg import OperationalError

from fdai.core.incident import (
    IncidentAutoOpenPolicy,
    IncidentLifecycleNotice,
    IncidentLifecycleWorkflow,
    IncidentOntologyProjector,
    IncidentRegistry,
    incident_severity,
    link_ticket_receipt,
    open_detected_incident_candidate,
)
from fdai.runtime.delivery import _build_incident_notifier
from fdai.shared.providers.ontology_instance import OntologyInstanceStore
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.tool import ToolCallReceipt, ToolCallRequest


class ReplayIncidentNotifier(Protocol):
    """Incident notifier that can replay durable startup transitions."""

    async def notify(self, notice: IncidentLifecycleNotice) -> object | None: ...

    async def replay(self, entries: tuple[Mapping[str, Any], ...]) -> int: ...


IncidentNotifierBuilder = Callable[..., ReplayIncidentNotifier]
OpenIncidentCandidate = Callable[[dict[str, Any]], Awaitable[bool]]
ObserveToolReceipt = Callable[[ToolCallRequest, ToolCallReceipt], Awaitable[None]]
_LOGGER = logging.getLogger("fdai.startup")


@dataclass(frozen=True, slots=True)
class IncidentNotificationReplayWorker:
    """Replay durable A2 notices without blocking unrelated runtime readiness."""

    notifier: ReplayIncidentNotifier
    entries: tuple[Mapping[str, Any], ...]
    retry_interval_seconds: float = 30.0

    async def run(self, stop: asyncio.Event) -> None:
        """Retry transient delivery failures until replay succeeds or shutdown wins."""
        if self.retry_interval_seconds <= 0:
            raise ValueError("incident notification replay retry interval MUST be positive")
        while not stop.is_set():
            try:
                delivered = await self.notifier.replay(self.entries)
            except asyncio.CancelledError:
                raise
            except (
                ConnectionError,
                OSError,
                OperationalError,
                TimeoutError,
                httpx.HTTPError,
            ) as exc:
                _LOGGER.warning(
                    "incident_notification_replay_retry",
                    extra={"entry_count": len(self.entries), "error_type": type(exc).__name__},
                )
                try:
                    async with asyncio.timeout(self.retry_interval_seconds):
                        await stop.wait()
                except TimeoutError:
                    continue
            except Exception:
                _LOGGER.exception(
                    "incident_notification_replay_aborted",
                    extra={"entry_count": len(self.entries)},
                )
                await stop.wait()
                return
            else:
                _LOGGER.info(
                    "incident_notification_replay_complete",
                    extra={"entry_count": len(self.entries), "delivered_count": delivered},
                )
                await stop.wait()
                return


@dataclass(frozen=True, slots=True)
class IncidentRuntime:
    """Rehydrated incident state and callbacks consumed by runtime assembly."""

    registry: IncidentRegistry
    entries: tuple[Mapping[str, Any], ...]
    notification_replay_worker: IncidentNotificationReplayWorker
    open_incident_candidate: OpenIncidentCandidate
    observe_tool_receipt: ObserveToolReceipt

    async def bind_projection(self, store: OntologyInstanceStore) -> None:
        """Project rehydrated incidents before accepting later mutations."""

        await self.registry.bind_projection(
            IncidentOntologyProjector(store=store),
            entries=self.entries,
        )


async def build_incident_runtime(
    *,
    state_store: StateStore,
    runtime_values: Mapping[str, object],
    http_client: httpx.AsyncClient | None,
    notifier_builder: IncidentNotifierBuilder = _build_incident_notifier,
) -> IncidentRuntime:
    """Rehydrate incidents and bind lifecycle callbacks before consumer startup."""

    policy = IncidentAutoOpenPolicy(
        enabled=runtime_values["incident.auto_open.enabled"] is True,
        minimum_severity=incident_severity(runtime_values["incident.auto_open.min_severity"]),
    )
    registry = IncidentRegistry(state_store=state_store)
    entries = await state_store.read_incident_transitions()
    registry.rehydrate(entries)
    notifier = notifier_builder(state_store, http_client=http_client)
    notification_replay_worker = IncidentNotificationReplayWorker(
        notifier=notifier,
        entries=entries,
    )
    workflow = IncidentLifecycleWorkflow(
        registry=registry,
        notifier=notifier,
        allowed_agent_principals={"Huginn", "Heimdall", "Forseti"},
    )

    async def open_incident_candidate(candidate: dict[str, Any]) -> bool:
        result = await open_detected_incident_candidate(
            workflow=workflow,
            candidate=candidate,
            policy=policy,
        )
        return result is not None

    async def observe_tool_receipt(
        request: ToolCallRequest,
        receipt: ToolCallReceipt,
    ) -> None:
        incident_id = request.metadata.get("incident_id") or request.arguments.get("incident_id")
        provider = request.metadata.get("ticket_provider") or request.arguments.get(
            "ticket_provider"
        )
        if not incident_id or not provider:
            return
        await link_ticket_receipt(
            registry=registry,
            request=request,
            receipt=receipt,
            actor_oid="Thor",
        )

    return IncidentRuntime(
        registry=registry,
        entries=entries,
        notification_replay_worker=notification_replay_worker,
        open_incident_candidate=open_incident_candidate,
        observe_tool_receipt=observe_tool_receipt,
    )


__all__ = [
    "IncidentNotifierBuilder",
    "IncidentNotificationReplayWorker",
    "IncidentRuntime",
    "ObserveToolReceipt",
    "OpenIncidentCandidate",
    "ReplayIncidentNotifier",
    "build_incident_runtime",
]
