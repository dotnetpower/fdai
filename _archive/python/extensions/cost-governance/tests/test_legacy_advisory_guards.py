"""Coverage for fail-closed legacy advisory guards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fdai.core.verticals.cost_governance.legacy_advisory import (
    LegacyRollingCostAdvisoryProvider,
)
from fdai.shared.providers.cost_governance import CostAnalysisSample

_RELEASE = f"sha256:{'a' * 64}"
_NOW = datetime(2026, 8, 31, tzinfo=UTC)


def _sample(
    *,
    correlation_id: str,
    observed_at: datetime,
    release: str = _RELEASE,
    completeness: Decimal = Decimal("1"),
) -> CostAnalysisSample:
    return CostAnalysisSample(
        scope_id="scope-1",
        resource_id="resource-1",
        amount_usd=Decimal("10"),
        correlation_id=correlation_id,
        observed_at=observed_at,
        source_authority="cost-provider",
        completeness=completeness,
        ontology_release_digest=release,
    )


@pytest.mark.parametrize(
    "kwargs",
    (
        {"ontology_release_digest": ""},
        {"ontology_release_digest": _RELEASE, "anomaly_ratio": Decimal("1")},
        {"ontology_release_digest": _RELEASE, "baseline_window": 2},
        {"ontology_release_digest": _RELEASE, "baseline_window": 4, "max_samples": 3},
    ),
)
def test_legacy_advisory_rejects_invalid_configuration(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        LegacyRollingCostAdvisoryProvider(**kwargs)  # type: ignore[arg-type]


async def test_legacy_advisory_records_all_fail_closed_sample_reasons() -> None:
    provider = LegacyRollingCostAdvisoryProvider(
        ontology_release_digest=_RELEASE,
        clock=lambda: _NOW,
    )
    mismatch = _sample(correlation_id="mismatch", observed_at=_NOW, release=_RELEASE[:-1] + "b")
    incomplete = _sample(
        correlation_id="incomplete",
        observed_at=_NOW,
        completeness=Decimal("0.5"),
    )
    stale = _sample(correlation_id="stale", observed_at=_NOW - timedelta(days=3))
    accepted = _sample(correlation_id="accepted", observed_at=_NOW - timedelta(minutes=1))
    reordered = _sample(correlation_id="reordered", observed_at=_NOW - timedelta(minutes=2))

    assert await provider.analyze_cost_sample(mismatch) is None
    assert await provider.analyze_cost_sample(incomplete) is None
    assert await provider.analyze_cost_sample(stale) is None
    assert await provider.analyze_cost_sample(accepted) is None
    assert await provider.analyze_cost_sample(accepted) is None
    assert await provider.analyze_cost_sample(reordered) is None
    assert provider.diagnostics == {
        "ontology_mismatch": 1,
        "incomplete": 1,
        "stale": 1,
        "accepted": 1,
        "duplicate": 1,
        "reordered": 1,
    }


async def test_package_advisory_and_service_validation_branches() -> None:
    from dataclasses import replace
    from types import SimpleNamespace
    from typing import Any

    from fdai.shared.providers.cost_governance import (
        CostObservation,
        CostObservationPage,
        CostPackageActivation,
    )

    from fdai_cost_governance.advisory import RollingCostAdvisoryProvider
    from fdai_cost_governance.service import (
        CostAnalyzerService,
        CostCollectorService,
        CostJobConfig,
        observation_to_sample,
    )

    for bad_kw in (
        {"ontology_release_digest": ""},
        {"ontology_release_digest": _RELEASE, "baseline_window": 2},
    ):
        with pytest.raises(ValueError):
            RollingCostAdvisoryProvider(**bad_kw)  # type: ignore[arg-type]

    pkg_provider = RollingCostAdvisoryProvider(
        ontology_release_digest=_RELEASE,
        clock=lambda: _NOW,
    )
    assert (
        await pkg_provider.analyze_cost_sample(
            _sample(correlation_id="m", observed_at=_NOW, release="bad")
        )
        is None
    )
    hydrated = await pkg_provider.hydrate_cost_samples(
        (
            _sample(
                correlation_id="h-bad",
                observed_at=_NOW - timedelta(minutes=10),
                completeness=Decimal("0.5"),
            ),
            _sample(correlation_id="h1", observed_at=_NOW - timedelta(minutes=9)),
            _sample(correlation_id="h2", observed_at=_NOW - timedelta(minutes=8)),
            _sample(correlation_id="h3", observed_at=_NOW - timedelta(minutes=7)),
        )
    )
    assert len(hydrated) == 3
    assert (
        await pkg_provider.analyze_cost_sample(
            _sample(correlation_id="normal", observed_at=_NOW - timedelta(minutes=1))
        )
        is None
    )

    for cfg_kw in (
        {
            "package_id": "",
            "ontology_release_id": "r",
            "ontology_release_digest": _RELEASE,
            "known_service_ids": frozenset({"s"}),
        },
        {
            "package_id": "p",
            "ontology_release_id": "r",
            "ontology_release_digest": _RELEASE,
            "known_service_ids": frozenset(),
        },
        {
            "package_id": "p",
            "ontology_release_id": "r",
            "ontology_release_digest": _RELEASE,
            "known_service_ids": frozenset({"s"}),
            "max_pages": 0,
        },
    ):
        with pytest.raises(ValueError):
            CostJobConfig(**cfg_kw)  # type: ignore[arg-type]

    cfg = CostJobConfig(
        package_id="cost-governance",
        ontology_release_id="rel-1",
        ontology_release_digest=_RELEASE,
        known_service_ids=frozenset({"compute"}),
        max_bytes=500,
    )
    base_obs = CostObservation(
        observation_id="obs-1",
        package_id="cost-governance",
        scope_id="scope-1",
        service_id="compute",
        amount=Decimal("10"),
        currency="USD",
        event_start_at=_NOW - timedelta(hours=1),
        event_end_at=_NOW,
        observed_at=_NOW,
        recorded_at=_NOW,
        source_authority="azure",
        source_uri="cost-service:1",
        completeness=Decimal("1"),
        ontology_release_id="rel-1",
        ontology_release_digest=_RELEASE,
        evidence_digest=_RELEASE,
        retention_until=_NOW + timedelta(days=400),
    )
    sample = observation_to_sample(base_obs)
    assert sample.correlation_id == "obs-1"

    act = CostPackageActivation(
        vertical_id="cost-governance",
        package_id="cost-governance",
        available=True,
        enabled=True,
        availability_reasons=(),
        package_version="0.1.0",
        image_digest=_RELEASE,
        asset_manifest_digest=_RELEASE,
        semantic_profile_digest=_RELEASE,
        revision=1,
        effective_at=_NOW,
        ontology_release_id="rel-1",
        ontology_release_digest=_RELEASE,
        source_authority="store",
    )

    class _FakeCollectorDeps:
        def __init__(self) -> None:
            self.activations: list[CostPackageActivation | None] = [act, act, act]
            self.append_ok = True
            self.page = CostObservationPage(
                observations=(base_obs,),
                next_resume_token=None,
                complete=True,
                source_authority="azure",
                bytes_read=10,
                collected_at=_NOW,
            )

        async def read_cost_activation(self, package_id: str) -> CostPackageActivation | None:
            return self.activations.pop(0) if self.activations else act

        async def read_cost_cursor(self, package_id: str, scope_id: str) -> Any:
            return SimpleNamespace(
                revision=0,
                resume_token=None,
                analysis_revision=0,
                last_published_at=None,
                last_published_observation_id=None,
            )

        async def collect_cost_page(
            self, request: Any, *, resume_token: str | None
        ) -> CostObservationPage:
            return self.page

        async def append_cost_page(self, page: Any, **kwargs: Any) -> bool:
            return self.append_ok

    deps = _FakeCollectorDeps()
    deps.activations = [act, None]
    col = CostCollectorService(
        config=cfg,
        activation=deps,
        provider=deps,
        store=deps,  # type: ignore[arg-type]
        clock=lambda: _NOW,
    )
    assert (
        await col.collect(scope_id="scope-1", start_at=_NOW - timedelta(hours=1), end_at=_NOW)
    ).status == "disabled"

    deps.activations = [act, act, act]
    deps.append_ok = False
    assert (
        await col.collect(scope_id="scope-1", start_at=_NOW - timedelta(hours=1), end_at=_NOW)
    ).status == "cursor_conflict"

    bad_src_obs = replace(base_obs)
    object.__setattr__(bad_src_obs, "source_authority", " ")
    assert col._invalid_page((base_obs,), "scope-1", 600) == "byte_limit"
    assert col._invalid_page((base_obs, base_obs), "scope-1", 10) == "duplicate_page_fact"
    assert (
        col._invalid_page((replace(base_obs, scope_id="other"),), "scope-1", 10) == "scope_mismatch"
    )
    assert (
        col._invalid_page((replace(base_obs, ontology_release_id="other"),), "scope-1", 10)
        == "ontology_mismatch"
    )
    assert col._invalid_page((bad_src_obs,), "scope-1", 10) == "missing_source_authority"

    class _FakeAnalyzerDeps:
        def __init__(self) -> None:
            self.activations: list[CostPackageActivation | None] = [act, act]
            self.advance_ok = True
            self.observations: tuple[CostObservation, ...] = (base_obs,)

        async def read_cost_activation(self, package_id: str) -> CostPackageActivation | None:
            return self.activations.pop(0) if self.activations else act

        async def read_cost_cursor(self, package_id: str, scope_id: str) -> Any:
            return SimpleNamespace(
                revision=0,
                analysis_revision=0,
                last_published_at=None,
                last_published_observation_id=None,
            )

        async def read_cost_observations(self, **kwargs: Any) -> tuple[CostObservation, ...]:
            return self.observations

        async def publish_cost_sample(self, item: Any, *, activation_revision: int) -> None:
            return None

        async def advance_cost_analysis_cursor(self, **kwargs: Any) -> bool:
            return self.advance_ok

    adeps = _FakeAnalyzerDeps()
    analyzer = CostAnalyzerService(
        config=cfg,
        activation=adeps,
        store=adeps,  # type: ignore[arg-type]
        publisher=adeps,
        clock=lambda: _NOW,
    )
    adeps.activations = [act, None]
    assert (
        await analyzer.analyze(scope_id="scope-1", since=_NOW - timedelta(hours=1))
    ).status == "disabled"

    adeps.activations = [act, act]
    adeps.advance_ok = False
    assert (
        await analyzer.analyze(scope_id="scope-1", since=_NOW - timedelta(hours=1))
    ).status == "analysis_cursor_conflict"

    assert analyzer._invalid(base_obs, {"obs-1"}) == "duplicate"
    assert analyzer._invalid(replace(base_obs, service_id="other"), set()) == "unknown_service"
    assert (
        analyzer._invalid(replace(base_obs, ontology_release_id="other"), set())
        == "ontology_mismatch"
    )
    assert analyzer._invalid(replace(base_obs, currency="EUR"), set()) == "unsupported_currency"
    stale_obs = replace(
        base_obs,
        event_start_at=_NOW - timedelta(days=6),
        event_end_at=_NOW - timedelta(days=5),
        observed_at=_NOW - timedelta(days=5),
    )
    assert analyzer._invalid(stale_obs, set()) == "stale"
    assert analyzer._invalid(bad_src_obs, set()) == "missing_source_authority"
