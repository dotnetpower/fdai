"""Explicit optional commerce recovery composition without importing its package into Core."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import entry_points
from typing import Any, Protocol

from fdai.agents import AnomalyActionSource, EventBusBridge
from fdai.core.control_loop import ControlLoop
from fdai.core.executor.post_release_closure_store import PostReleaseClosureStore
from fdai.shared.providers.state_store import StateStore

ActionObservation = Callable[[Mapping[str, Any]], Awaitable[bool | Mapping[str, Any]]]


class VerifiedIncidentResolver(Protocol):
    """Resolve one exact Incident after independent acceptance-effect verification."""

    async def __call__(
        self,
        *,
        action_idempotency_key: str,
        correlation_id: str,
        resource_id: str,
        event_type: str,
        verified_at: datetime,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class AcceptanceRuntimeBindings:
    """Exact source and Thor transport bindings; activation grants no mutation authority."""

    sources: dict[str, AnomalyActionSource]
    execute: Callable[[dict[str, Any]], Awaitable[bool]]
    observe: ActionObservation | None = None
    resolve: Callable[[Mapping[str, Any]], Awaitable[bool]] | None = None


def chain_acceptance_observer(
    primary: ActionObservation | None,
    fallback: ActionObservation | None,
) -> ActionObservation | None:
    """Return an acceptance-first observer while preserving the existing fallback."""
    if primary is None:
        return fallback

    async def observe(payload: Mapping[str, Any]) -> bool | Mapping[str, Any]:
        result = await primary(payload)
        if result:
            return result
        return await fallback(payload) if fallback is not None else False

    return observe


def bind_acceptance_effect_resolution(
    *,
    bridge: EventBusBridge,
    resolver: Callable[[Mapping[str, Any]], Awaitable[bool]] | None,
) -> int:
    """Bind exact verified-effect Incident resolution without changing topic ownership."""
    if resolver is None:
        return 0

    async def resolve_effect(_topic: str, payload: Mapping[str, Any]) -> None:
        await resolver(payload)

    bridge.subscribe(
        "object.recovery-effect-observation",
        "aks-commerce-incident-reconciler",
        resolve_effect,
    )
    return 1


def build_acceptance_runtime_bindings(
    *,
    environment: Mapping[str, str],
    loop: ControlLoop,
    store: StateStore,
    fallback: Callable[[dict[str, Any]], Awaitable[bool]] | None,
    resolve_verified_incident: VerifiedIncidentResolver | None = None,
) -> AcceptanceRuntimeBindings | None:
    """Load exactly one installed provider only when its reviewed observation config is present."""
    if not environment.get("FDAI_AKS_ACCEPTANCE_JSON", "").strip():
        return None
    matches = tuple(
        item
        for item in entry_points(group="fdai.acceptance_recovery")
        if item.name == "aks-commerce"
    )
    if len(matches) != 1:
        raise RuntimeError("configured acceptance recovery requires exactly one installed provider")
    factory = matches[0].load()
    if not callable(factory):
        raise RuntimeError("acceptance recovery provider is not callable")
    bindings = factory(
        environment=environment,
        loop=loop,
        store=store,
        fallback=fallback,
        resolve_verified_incident=resolve_verified_incident,
    )
    if (
        not isinstance(bindings, AcceptanceRuntimeBindings)
        or not bindings.sources
        or not callable(bindings.execute)
    ):
        raise RuntimeError("acceptance recovery provider returned invalid bindings")
    return bindings


def wrap_acceptance_closure_store(
    *,
    environment: Mapping[str, str],
    delegate: PostReleaseClosureStore,
    store: StateStore,
) -> PostReleaseClosureStore:
    """Bind optional exact-target context retention without changing the atomic closure owner."""
    if not environment.get("FDAI_AKS_ACCEPTANCE_JSON", "").strip():
        return delegate
    matches = tuple(
        item
        for item in entry_points(group="fdai.acceptance_recovery")
        if item.name == "aks-commerce-closure"
    )
    if len(matches) != 1:
        raise RuntimeError("configured acceptance closure requires exactly one installed provider")
    factory = matches[0].load()
    if not callable(factory):
        raise RuntimeError("acceptance closure provider is not callable")
    result = factory(environment=environment, delegate=delegate, store=store)
    if not isinstance(result, PostReleaseClosureStore):
        raise RuntimeError("acceptance closure provider does not implement the closure contract")
    return result
