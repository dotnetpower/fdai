"""Trusted installed-plugin discovery for external evaluation adapters."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from importlib.metadata import EntryPoint, entry_points
from typing import Protocol, runtime_checkable

from fdai_evaluation_sdk import EVALUATION_API_VERSION, EvaluationAdapter

EVALUATION_ADAPTER_ENTRY_POINT_GROUP = "fdai.evaluation.adapters"


class EvaluationPluginError(RuntimeError):
    """An installed evaluation adapter is missing, ambiguous, or incompatible."""


@runtime_checkable
class EvaluationAdapterPlugin(Protocol):
    """Reviewed factory surface implemented by independently installed drivers."""

    plugin_id: str
    api_version: str

    def create_adapter(self) -> EvaluationAdapter: ...


EntryPointSource = Callable[[], Iterable[EntryPoint]]


def discover_evaluation_adapters(
    *,
    entry_point_source: EntryPointSource | None = None,
) -> tuple[str, ...]:
    """Return unique installed adapter names in deterministic order."""

    points = _read_entry_points(entry_point_source)
    names = [point.name for point in points]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise EvaluationPluginError(
            f"duplicate evaluation adapter entry points: {', '.join(duplicates)}"
        )
    return tuple(sorted(names))


def load_evaluation_adapter(
    name: str,
    *,
    entry_point_source: EntryPointSource | None = None,
) -> EvaluationAdapter:
    """Load one exact API-compatible adapter from its trusted factory."""

    if not name.strip() or any(ord(character) < 32 for character in name):
        raise EvaluationPluginError("evaluation adapter name MUST be a non-empty identifier")
    matches = tuple(point for point in _read_entry_points(entry_point_source) if point.name == name)
    if not matches:
        raise EvaluationPluginError(f"evaluation adapter {name!r} is not installed")
    if len(matches) > 1:
        raise EvaluationPluginError(f"evaluation adapter {name!r} has duplicate entry points")
    try:
        factory = matches[0].load()
        plugin = factory()
    except Exception as exc:
        raise EvaluationPluginError(f"evaluation adapter {name!r} failed to load") from exc
    if not isinstance(plugin, EvaluationAdapterPlugin):
        raise EvaluationPluginError(f"evaluation adapter {name!r} has an invalid factory")
    if plugin.plugin_id != name:
        raise EvaluationPluginError(
            f"evaluation adapter id {plugin.plugin_id!r} does not match entry point {name!r}"
        )
    if plugin.api_version != EVALUATION_API_VERSION:
        raise EvaluationPluginError(
            f"evaluation adapter {name!r} uses API {plugin.api_version!r}; "
            f"expected {EVALUATION_API_VERSION!r}"
        )
    try:
        adapter = plugin.create_adapter()
    except Exception as exc:
        raise EvaluationPluginError(f"evaluation adapter {name!r} factory failed") from exc
    if not isinstance(adapter, EvaluationAdapter):
        raise EvaluationPluginError(f"evaluation adapter {name!r} has an invalid contract")
    return adapter


def _installed_entry_points() -> tuple[EntryPoint, ...]:
    return tuple(entry_points(group=EVALUATION_ADAPTER_ENTRY_POINT_GROUP))


def _read_entry_points(source: EntryPointSource | None) -> tuple[EntryPoint, ...]:
    try:
        return tuple((source or _installed_entry_points)())
    except Exception as exc:
        raise EvaluationPluginError("evaluation adapter discovery failed") from exc


__all__ = [
    "EVALUATION_ADAPTER_ENTRY_POINT_GROUP",
    "EvaluationAdapterPlugin",
    "EvaluationPluginError",
    "discover_evaluation_adapters",
    "load_evaluation_adapter",
]
