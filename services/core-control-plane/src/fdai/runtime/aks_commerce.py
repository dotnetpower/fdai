"""Explicit optional commerce recovery composition without importing its package into Core."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any

from fdai.agents import AnomalyActionSource
from fdai.core.control_loop import ControlLoop
from fdai.core.executor.post_release_closure_store import PostReleaseClosureStore
from fdai.shared.providers.state_store import StateStore


@dataclass(frozen=True, slots=True)
class AcceptanceRuntimeBindings:
    """Exact source and Thor transport bindings; activation grants no mutation authority."""

    sources: dict[str, AnomalyActionSource]
    execute: Callable[[dict[str, Any]], Awaitable[bool]]
    observe: Callable[[Mapping[str, Any]], Awaitable[bool]] | None = None


def build_acceptance_runtime_bindings(
    *,
    environment: Mapping[str, str],
    loop: ControlLoop,
    store: StateStore,
    fallback: Callable[[dict[str, Any]], Awaitable[bool]] | None,
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
    bindings = factory(environment=environment, loop=loop, store=store, fallback=fallback)
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
