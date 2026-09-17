"""Explicit optional commerce recovery composition without importing its package into Core."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any

from fdai.agents import AnomalyActionSource
from fdai.core.control_loop import ControlLoop
from fdai.shared.providers.state_store import StateStore


@dataclass(frozen=True, slots=True)
class AcceptanceRuntimeBindings:
    """Exact source and Thor transport bindings; activation grants no mutation authority."""

    sources: dict[str, AnomalyActionSource]
    execute: Callable[[dict[str, Any]], Awaitable[bool]]


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
