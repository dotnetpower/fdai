from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime

import pytest
from fdai.core.rca.telemetry_evidence import (
    TelemetryEvidenceDisposition,
    TelemetryEvidenceReceipt,
    TelemetryEvidenceRecipe,
    TelemetryLookbackProfile,
    TelemetryMechanism,
    build_telemetry_evidence_need,
    build_telemetry_evidence_receipt,
)

_CUTOFF = datetime(2026, 9, 16, 12, tzinfo=UTC)
_DIGEST = f"sha256:{'a' * 64}"


def _recipe() -> TelemetryEvidenceRecipe:
    return TelemetryEvidenceRecipe(
        recipe_id="requests.failed",
        version="1.0.0",
        mechanism=TelemetryMechanism.FAILED_REQUESTS,
        output_schema_digest=_DIGEST,
        estimated_cost_units=10,
        default_lookback=TelemetryLookbackProfile.FIFTEEN_MINUTES,
        supports_no_data_refutation=True,
    )


def _receipt(**overrides: object) -> TelemetryEvidenceReceipt:
    need = build_telemetry_evidence_need(
        incident_id="incident:one",
        resource_ref="resource:one",
        evidence_cutoff=_CUTOFF,
        recipe=_recipe(),
        max_query_count=2,
        max_cost_units=20,
        idempotency_key="incident:one:round:1",
    )
    values: dict[str, object] = {
        "need": need,
        "observed_until": _CUTOFF,
        "disposition": TelemetryEvidenceDisposition.COMPLETE,
        "route_count": 2,
        "queried_route_count": 2,
        "row_count": 1,
        "latency_ms": 12,
        "estimated_cost_units": 10,
        "actual_cost_units": 8,
        "fact_tokens": ("count:1",),
        "complete": True,
        "truncated": False,
    }
    values.update(overrides)
    return build_telemetry_evidence_receipt(**values)  # type: ignore[arg-type]


def test_need_is_recipe_bound_and_has_no_raw_query_surface() -> None:
    need = build_telemetry_evidence_need(
        incident_id="incident:one",
        resource_ref="resource:one",
        evidence_cutoff=_CUTOFF,
        recipe=_recipe(),
        max_query_count=2,
        max_cost_units=20,
        idempotency_key="incident:one:round:1",
    )

    names = {item.name for item in fields(need)}
    assert not names.intersection({"kql", "query", "workspace_id", "table", "endpoint"})
    assert need.recipe_id == "requests.failed"
    assert need.query_execution_authority is False


def test_complete_no_data_is_distinct_from_unavailable() -> None:
    no_data = _receipt(
        disposition=TelemetryEvidenceDisposition.COMPLETE_NO_DATA,
        row_count=0,
        fact_tokens=(),
    )
    unavailable = _receipt(
        disposition=TelemetryEvidenceDisposition.UNAVAILABLE,
        observed_until=None,
        route_count=0,
        queried_route_count=0,
        row_count=0,
        fact_tokens=(),
        complete=False,
    )

    assert no_data.complete is True
    assert unavailable.complete is False
    assert no_data.disposition is not unavailable.disposition


@pytest.mark.parametrize(
    ("disposition", "complete", "truncated"),
    [
        (TelemetryEvidenceDisposition.PARTIAL, True, False),
        (TelemetryEvidenceDisposition.COMPLETE, False, False),
        (TelemetryEvidenceDisposition.TRUNCATED, False, False),
    ],
)
def test_disposition_flags_cannot_misrepresent_completeness(
    disposition: TelemetryEvidenceDisposition,
    complete: bool,
    truncated: bool,
) -> None:
    with pytest.raises(ValueError):
        _receipt(disposition=disposition, complete=complete, truncated=truncated)


def test_complete_receipt_requires_all_routes() -> None:
    with pytest.raises(ValueError, match="every resolved route"):
        _receipt(queried_route_count=1)


def test_receipt_digest_detects_tampering() -> None:
    receipt = _receipt()

    with pytest.raises(ValueError, match="digest does not match"):
        replace(receipt, row_count=2)


def test_need_identity_detects_recipe_or_budget_substitution() -> None:
    need = build_telemetry_evidence_need(
        incident_id="incident:one",
        resource_ref="resource:one",
        evidence_cutoff=_CUTOFF,
        recipe=_recipe(),
        max_query_count=2,
        max_cost_units=20,
        idempotency_key="incident:one:round:1",
    )

    with pytest.raises(ValueError, match="need id does not match"):
        replace(need, recipe_version="2.0.0")
    with pytest.raises(ValueError, match="need id does not match"):
        replace(need, max_cost_units=21)
