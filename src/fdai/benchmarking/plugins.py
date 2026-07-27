"""Trusted installed-plugin discovery for benchmark adapters."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from importlib.metadata import EntryPoint, entry_points
from typing import Protocol, runtime_checkable

from fdai.benchmarking.bindings import BenchmarkBindings

BENCHMARK_API_VERSION = "1.0"
BENCHMARK_ENTRY_POINT_GROUP = "fdai.benchmark_adapters"


class BenchmarkPluginError(RuntimeError):
    """Installed benchmark plugin is missing, ambiguous, or incompatible."""


@runtime_checkable
class BenchmarkPlugin(Protocol):
    """Reviewed plugin factory surface loaded from a Python entry point."""

    plugin_id: str
    api_version: str

    def create_bindings(self) -> BenchmarkBindings: ...


EntryPointSource = Callable[[], Iterable[EntryPoint]]


def discover_benchmark_plugins(
    *, entry_point_source: EntryPointSource | None = None
) -> tuple[str, ...]:
    """Return unique installed plugin names in deterministic order."""

    points = tuple((entry_point_source or _installed_entry_points)())
    names = [point.name for point in points]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise BenchmarkPluginError(
            f"duplicate benchmark plugin entry points: {', '.join(duplicates)}"
        )
    return tuple(sorted(names))


def load_benchmark_plugin(
    name: str,
    *,
    entry_point_source: EntryPointSource | None = None,
) -> BenchmarkPlugin:
    """Load one exact, API-compatible benchmark plugin factory."""

    if not name.strip() or any(ord(character) < 32 for character in name):
        raise BenchmarkPluginError("benchmark plugin name MUST be a non-empty identifier")
    points = tuple((entry_point_source or _installed_entry_points)())
    matches = tuple(point for point in points if point.name == name)
    if not matches:
        raise BenchmarkPluginError(f"benchmark plugin {name!r} is not installed")
    if len(matches) > 1:
        raise BenchmarkPluginError(f"benchmark plugin {name!r} has duplicate entry points")

    factory = matches[0].load()
    if not callable(factory):
        raise BenchmarkPluginError(f"benchmark plugin {name!r} does not expose a factory")
    plugin = factory()
    if not isinstance(plugin, BenchmarkPlugin):
        raise BenchmarkPluginError(f"benchmark plugin {name!r} has an invalid contract")
    if plugin.plugin_id != name:
        raise BenchmarkPluginError(
            f"benchmark plugin id {plugin.plugin_id!r} does not match entry point {name!r}"
        )
    if plugin.api_version != BENCHMARK_API_VERSION:
        raise BenchmarkPluginError(
            f"benchmark plugin {name!r} uses API {plugin.api_version!r}; "
            f"expected {BENCHMARK_API_VERSION!r}"
        )
    return plugin


def _installed_entry_points() -> tuple[EntryPoint, ...]:
    return tuple(entry_points(group=BENCHMARK_ENTRY_POINT_GROUP))


__all__ = [
    "BENCHMARK_API_VERSION",
    "BENCHMARK_ENTRY_POINT_GROUP",
    "BenchmarkPlugin",
    "BenchmarkPluginError",
    "discover_benchmark_plugins",
    "load_benchmark_plugin",
]
