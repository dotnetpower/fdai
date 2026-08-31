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
