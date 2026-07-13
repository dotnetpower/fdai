"""Tests for the core chaos scenario factory contract."""

from __future__ import annotations

import pathlib

import pytest

from fdai.core.chaos.factory import (
    ScenarioFactory,
    UnavailableInjectorError,
    UnavailableProbeError,
)
from fdai.core.chaos.injector import NoSignalProbe
from fdai.core.chaos.scenario_catalog import CatalogEntry


class _FakeInjector:
    fault_type = "fake"

    async def inject(self, *, target, params):  # noqa: D401
        return None

    async def stop(self, *, target):  # noqa: D401
        return None


def _entry(scenario_id: str, injector: str, signal: str = "pod_restart") -> CatalogEntry:
    spec = {
        "id": scenario_id,
        "version": 1,
        "provenance": {"source": "synthesized", "synthesis_method": "deterministic"},
        "category": "compute",
        "target_type": "pod",
        "fault_family": "stop",
        "intensity": "mild",
        "duration_seconds": 360,
        "expected_signal": signal,
        "injector": injector,
        "blast_radius_cap": 1,
        "rollback_note": "n/a",
        "gates": {"shadow_status": "pending", "enforce_status": None},
        "requires_hardware": False,
        "gpu_domain": None,
    }
    return CatalogEntry(
        id=scenario_id,
        source_path=pathlib.Path("/tmp/x.yaml"),  # noqa: S108 - synthetic marker, never opened
        spec=spec,
    )


def _inj_builder(entry, ctx):
    return _FakeInjector()


def _probe_builder(entry, ctx):
    return NoSignalProbe()


def test_empty_factory_reports_zero_executable() -> None:
    f = ScenarioFactory()
    e = _entry("chaos.a.p", "chaos-mesh:PodChaos")
    assert not f.is_executable(e)
    assert f.executable_entries([e]) == []


def test_exact_injector_registration_makes_entry_executable() -> None:
    f = ScenarioFactory()
    f.register_injector("chaos-mesh:PodChaos", _inj_builder)
    f.register_probe("pod_restart", _probe_builder)
    e = _entry("chaos.a.p", "chaos-mesh:PodChaos", "pod_restart")
    assert f.is_executable(e)
    inj, pr = f.build(e, {})
    assert isinstance(inj, _FakeInjector)
    assert isinstance(pr, NoSignalProbe)


def test_prefix_injector_registration_matches_any_kind() -> None:
    f = ScenarioFactory()
    f.register_injector("chaos-mesh", _inj_builder)
    f.register_probe("pod_restart", _probe_builder)
    for kind in ("PodChaos", "StressChaos", "NetworkChaos", "IOChaos"):
        assert f.is_executable(_entry("chaos.a.p", f"chaos-mesh:{kind}"))


def test_exact_beats_prefix() -> None:
    """Exact registration takes precedence over prefix so a per-kind
    adapter can override the generic one."""
    prefix_called = 0
    exact_called = 0

    def prefix(entry, ctx):
        nonlocal prefix_called
        prefix_called += 1
        return _FakeInjector()

    def exact(entry, ctx):
        nonlocal exact_called
        exact_called += 1
        return _FakeInjector()

    f = ScenarioFactory()
    f.register_injector("chaos-mesh", prefix)
    f.register_injector("chaos-mesh:PodChaos", exact)
    f.register_probe("pod_restart", _probe_builder)
    e = _entry("chaos.a.p", "chaos-mesh:PodChaos")
    f.build(e, {})
    assert (exact_called, prefix_called) == (1, 0)
    # Another kind still falls back to the prefix builder.
    f.build(_entry("chaos.a.p2", "chaos-mesh:StressChaos"), {})
    assert (exact_called, prefix_called) == (1, 1)


def test_needs_injector_is_never_executable() -> None:
    f = ScenarioFactory()
    f.register_injector("chaos-mesh", _inj_builder)
    f.register_probe("pod_restart", _probe_builder)
    e = _entry("chaos.a.p", "needs-injector")
    assert not f.is_executable(e)
    with pytest.raises(UnavailableInjectorError, match="needs-injector"):
        f.build(e, {})


def test_cross_csp_reference_is_never_executable() -> None:
    """Borrowed catalog data (e.g. AWS FIS on an Azure stack) must never
    dispatch to an injector even if a builder for the string exists.
    Both `needs-injector` and `cross-csp-reference` are opt-out markers."""
    f = ScenarioFactory()
    # Deliberately register a builder for cross-csp-reference to confirm
    # the opt-out marker beats the registry.
    f.register_injector("cross-csp-reference", _inj_builder)
    f.register_probe("pod_restart", _probe_builder)
    e = _entry("chaos.aws.foo", "cross-csp-reference")
    assert not f.is_executable(e)
    with pytest.raises(UnavailableInjectorError, match="cross-csp-reference"):
        f.build(e, {})


def test_unknown_injector_raises() -> None:
    f = ScenarioFactory()
    f.register_probe("pod_restart", _probe_builder)
    e = _entry("chaos.a.p", "no-such-family:Foo")
    with pytest.raises(UnavailableInjectorError, match="no injector builder"):
        f.build(e, {})


def test_missing_probe_raises_distinct_error() -> None:
    f = ScenarioFactory()
    f.register_injector("chaos-mesh", _inj_builder)
    e = _entry("chaos.a.p", "chaos-mesh:PodChaos", signal="unmapped_signal")
    with pytest.raises(UnavailableProbeError, match="no probe builder"):
        f.build(e, {})


def test_registered_injectors_and_probes_are_reported() -> None:
    f = ScenarioFactory()
    f.register_injector("chaos-mesh", _inj_builder)
    f.register_injector("kubectl:scale", _inj_builder)
    f.register_probe("pod_restart", _probe_builder)
    assert "chaos-mesh:*" in f.registered_injectors()
    assert "kubectl:scale" in f.registered_injectors()
    assert "pod_restart" in f.registered_probes()


def test_empty_string_registrations_are_rejected() -> None:
    f = ScenarioFactory()
    with pytest.raises(ValueError, match="injector_ref"):
        f.register_injector("", _inj_builder)
    with pytest.raises(ValueError, match="expected_signal"):
        f.register_probe("", _probe_builder)


def test_build_passes_context_through_to_builders() -> None:
    seen: dict = {}

    def inj(entry, ctx):
        seen["inj_ctx"] = ctx
        return _FakeInjector()

    def pr(entry, ctx):
        seen["probe_ctx"] = ctx
        return NoSignalProbe()

    f = ScenarioFactory()
    f.register_injector("chaos-mesh", inj)
    f.register_probe("pod_restart", pr)
    e = _entry("chaos.a.p", "chaos-mesh:PodChaos")
    my_ctx = {"kubectl_context": "foo", "workload_namespace": "bar"}
    f.build(e, my_ctx)
    # Copy semantics: the factory does not mutate the caller's dict.
    assert seen["inj_ctx"] == my_ctx
    assert seen["probe_ctx"] == my_ctx
    assert seen["inj_ctx"] is not my_ctx
