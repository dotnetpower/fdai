"""Tests for trusted benchmark entry-point discovery."""

from __future__ import annotations

from importlib.metadata import EntryPoint

import pytest

from fdai.benchmarking import (
    BENCHMARK_API_VERSION,
    BenchmarkBindings,
    BenchmarkPluginError,
    bind_benchmark_providers,
    discover_benchmark_plugins,
    load_benchmark_plugin,
)
from fdai.composition import Container
from fdai.shared.providers.metric import StaticMetricProvider

_FACTORIES: dict[str, object] = {}


class _Adapter:
    adapter_id = "example"

    async def start(self) -> None: ...

    async def next_task(self):  # type: ignore[no-untyped-def]
        return None

    async def submit(self, submission) -> None:  # type: ignore[no-untyped-def]
        return None

    async def close(self) -> None: ...


class _Plugin:
    plugin_id = "example"
    api_version = BENCHMARK_API_VERSION

    def create_bindings(self) -> BenchmarkBindings:
        return BenchmarkBindings(adapter=_Adapter())


def _factory() -> _Plugin:
    return _Plugin()


def _raising_factory() -> _Plugin:
    raise RuntimeError("provider detail")


def _points(*names: str) -> tuple[EntryPoint, ...]:
    _FACTORIES["factory"] = _factory
    return tuple(
        EntryPoint(name=name, value=f"{__name__}:_factory", group="fdai.benchmark_adapters")
        for name in names
    )


def test_discovers_plugins_in_deterministic_order() -> None:
    assert discover_benchmark_plugins(entry_point_source=lambda: _points("zeta", "alpha")) == (
        "alpha",
        "zeta",
    )


@pytest.mark.parametrize("operation", ("discover", "load"))
def test_normalizes_plugin_registry_failure(operation: str) -> None:
    def broken_source():  # type: ignore[no-untyped-def]
        raise RuntimeError("registry secret")

    with pytest.raises(BenchmarkPluginError, match="plugin discovery failed") as error:
        if operation == "discover":
            discover_benchmark_plugins(entry_point_source=broken_source)
        else:
            load_benchmark_plugin("example", entry_point_source=broken_source)

    assert isinstance(error.value.__cause__, RuntimeError)
    assert "registry secret" not in str(error.value)


def test_loads_exact_compatible_plugin() -> None:
    plugin = load_benchmark_plugin("example", entry_point_source=lambda: _points("example"))

    assert plugin.plugin_id == "example"
    assert plugin.create_bindings().adapter.adapter_id == "example"


def test_rejects_duplicate_plugin_names() -> None:
    with pytest.raises(BenchmarkPluginError, match="duplicate"):
        discover_benchmark_plugins(entry_point_source=lambda: _points("example", "example"))


def test_rejects_plugin_id_mismatch() -> None:
    with pytest.raises(BenchmarkPluginError, match="does not match"):
        load_benchmark_plugin("other", entry_point_source=lambda: _points("other"))


def test_rejects_incompatible_api_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_Plugin, "api_version", "2.0")

    with pytest.raises(BenchmarkPluginError, match="expected '1.0'"):
        load_benchmark_plugin("example", entry_point_source=lambda: _points("example"))


def test_normalizes_plugin_import_failure() -> None:
    point = EntryPoint(
        name="broken",
        value="missing_benchmark_module:create_plugin",
        group="fdai.benchmark_adapters",
    )

    with pytest.raises(BenchmarkPluginError, match="failed to load") as error:
        load_benchmark_plugin("broken", entry_point_source=lambda: (point,))

    assert isinstance(error.value.__cause__, ModuleNotFoundError)


def test_normalizes_plugin_factory_failure() -> None:
    point = EntryPoint(
        name="broken",
        value=f"{__name__}:_raising_factory",
        group="fdai.benchmark_adapters",
    )

    with pytest.raises(BenchmarkPluginError, match="factory failed") as error:
        load_benchmark_plugin("broken", entry_point_source=lambda: (point,))

    assert isinstance(error.value.__cause__, RuntimeError)
    assert "provider detail" not in str(error.value)


def test_binding_replaces_only_declared_provider_seams(container: Container) -> None:
    metric_provider = StaticMetricProvider(())

    bound = bind_benchmark_providers(
        container,
        BenchmarkBindings(adapter=_Adapter(), metric_provider=metric_provider),
    )

    assert bound is not container
    assert bound.metric_provider is metric_provider
    assert bound.log_query_provider is container.log_query_provider
    assert bound.trace_query_provider is container.trace_query_provider
    assert bound.inventory is container.inventory
    assert bound.capability_runtime is container.capability_runtime


@pytest.mark.parametrize(
    "provider_field",
    ("metric_provider", "log_query_provider", "trace_query_provider", "inventory"),
)
def test_bindings_reject_invalid_provider(provider_field: str) -> None:
    with pytest.raises(TypeError, match=f"{provider_field} MUST implement"):
        BenchmarkBindings(  # type: ignore[arg-type]
            adapter=_Adapter(),
            **{provider_field: object()},
        )
