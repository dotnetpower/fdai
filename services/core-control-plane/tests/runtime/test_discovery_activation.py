"""Runtime composition for governed discovery activation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.readiness import (
    DiscoveryActivationDecision,
    ProbeStatus,
    ReadinessDecision,
    StartupProbeResult,
    StartupReadinessReport,
)
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.runtime.discovery_activation import (
    DiscoveryActivationRuntime,
    _startup_group_evidence,
    build_discovery_activation_runtime,
)
from fdai.runtime.readiness import RuntimeReadinessState
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
_ROOT = Path(__file__).resolve().parents[4]


def _probe(probe_id: str) -> StartupProbeResult:
    return StartupProbeResult(
        probe_id=probe_id,
        status=ProbeStatus.PASSED,
        observed_at=_NOW - timedelta(minutes=1),
        expires_at=_NOW + timedelta(minutes=5),
        latency_ms=1,
    )


async def _enabled_runtime() -> DiscoveryActivationRuntime:
    store = InMemoryStateStore()
    await store.write_state(
        "runtime:collector-success:example-source:receipt",
        {
            "schema_version": "1.0.0",
            "source_id": "example-source",
            "resolved_revision": "abc123",
            "content_sha256": "0" * 64,
            "license": "Apache-2.0",
            "redistribution": "embeddable",
            "verified_rules": 3,
            "verified_at": (_NOW - timedelta(minutes=1)).isoformat(),
            "schema_validated": True,
            "provenance_validated": True,
        },
    )
    startup_state = RuntimeReadinessState(
        report=StartupReadinessReport(
            generated_at=_NOW,
            decision=ReadinessDecision.READY,
            results=tuple(
                _probe(probe_id)
                for probe_id in (
                    "model.cross-check.0.0",
                    "model.cross-check.1.0",
                    "policy.compile",
                    "audit.append",
                    "kafka.round-trip",
                )
            ),
        )
    )
    runtime = build_discovery_activation_runtime(
        state_store=store,
        runtime_settings=RuntimeSettingsService(
            store=store,
            env={
                "FDAI_DISCOVERY_ENABLED": "true",
                "FDAI_DISCOVERY_SHADOW_DECISION_THRESHOLD": "1",
                "FDAI_DISCOVERY_COLLECTOR_FRESHNESS_SECONDS": "600",
            },
        ),
        startup_readiness=startup_state,
    )
    runtime.clock = lambda: _NOW
    runtime.bind_shadow_decision_count(lambda: 1)
    return runtime


async def test_runtime_enables_only_after_all_current_evidence_is_joined() -> None:
    runtime = await _enabled_runtime()

    report = await runtime.evaluate()

    assert report.decision is DiscoveryActivationDecision.ENABLED
    assert runtime.is_enabled()


async def test_runtime_closes_an_enabled_gate_before_a_refresh_failure() -> None:
    class _FailingSettings:
        async def effective_values(self) -> dict[str, object]:
            raise RuntimeError("provider detail")

    runtime = await _enabled_runtime()
    await runtime.evaluate()
    runtime.runtime_settings = _FailingSettings()  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="provider detail"):
        await runtime.evaluate()

    assert not runtime.is_enabled()


def test_duplicate_probe_rows_cannot_satisfy_distinct_smoke_requirements() -> None:
    evidence = _startup_group_evidence(
        (_probe("audit.append"), _probe("audit.append")),
        probe_ids=("audit.append", "kafka.round-trip"),
        minimum_count=2,
    )

    assert evidence is None


def test_bootstrap_constructs_injects_and_supervises_discovery_activation() -> None:
    bootstrap = (_ROOT / "services/core-control-plane/src/fdai/runtime/bootstrap.py").read_text(
        encoding="utf-8"
    )
    pantheon = (
        _ROOT / "services/core-control-plane/src/fdai/runtime/bootstrap_pantheon.py"
    ).read_text(encoding="utf-8")
    tasks = (_ROOT / "services/core-control-plane/src/fdai/runtime/bootstrap_tasks.py").read_text(
        encoding="utf-8"
    )

    assert "build_discovery_activation_runtime(" in bootstrap
    assert "discovery_activation=discovery_activation_runtime" in bootstrap
    assert "bind_candidate_publication_gate(config.discovery_activation.is_enabled)" in pantheon
    assert "bind_shadow_decision_count(" in pantheon
    assert 'name="discovery-activation-refresh"' in tasks
    assert "discovery_activation_task," in tasks
