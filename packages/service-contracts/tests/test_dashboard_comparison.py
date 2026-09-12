"""Sealed comparisons stay separate, expiring, and authority-free."""

from datetime import UTC, datetime, timedelta

import pytest
from fdai_service_contracts.dashboard_comparison import (
    DashboardComparisonSnapshot,
    dashboard_comparison_id,
)

NOW = datetime(2026, 9, 12, tzinfo=UTC)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _arm(arm: str, report: str, provenance: str, receipt: str) -> dict[str, object]:
    return {
        "arm": arm,
        "sample_count": 30,
        "metrics": [
            {
                "metric_id": "mttr_seconds",
                "absolute_value": 120.0,
                "sample_size": 30,
                "confidence_level_basis_points": 9_500,
                "lower_bound": 100.0,
                "upper_bound": 150.0,
            }
        ],
        "guards": [
            {
                "guard_id": "unverified_success_claim_rate",
                "observed_basis_points": 0,
                "sample_size": 30,
                "breached": False,
            }
        ],
        "report_digest": _digest(report),
        "provenance_digest": _digest(provenance),
        "evidence_receipt_digest": _digest(receipt),
        "window_start": NOW - timedelta(hours=2),
        "window_end": NOW - timedelta(hours=1),
    }


def _facts(**updates: object) -> dict[str, object]:
    return {
        "cohort_id": "example-comparison",
        "cohort_receipt_digest": _digest("a"),
        "cohort_admission_receipt_digest": _digest("b"),
        "measurement_protocol_version": "1.0.0",
        "measurement_protocol_digest": _digest("c"),
        "fdai_revision": "a" * 40,
        "baseline": _arm("baseline", "1", "2", "3"),
        "treatment": _arm("treatment", "4", "5", "6"),
        "evidence_cutoff": NOW - timedelta(hours=1),
        "published_at": NOW,
        "valid_until": NOW + timedelta(minutes=10),
        "admission_receipt_refs": (_digest("3"), _digest("6"), _digest("b")),
        "verification_bundle_refs": (_digest("d"),),
        **updates,
    }


def _snapshot(**updates: object) -> DashboardComparisonSnapshot:
    facts = _facts(**updates)
    return DashboardComparisonSnapshot.model_validate(
        {**facts, "publication_id": dashboard_comparison_id(**facts)}
    )


def test_strict_state_round_trip_preserves_both_arms() -> None:
    snapshot = _snapshot()
    state = {"revision": 1, "snapshot": snapshot.model_dump(mode="json")}
    assert DashboardComparisonSnapshot.from_state(state, evaluated_at=NOW) == snapshot
    assert snapshot.baseline.metrics[0].absolute_value == 120
    assert snapshot.baseline.window_basis == "evidence_event_to_cutoff"
    assert snapshot.execution_authority is False


def test_auto_resolution_comparison_cannot_exceed_one() -> None:
    arm = _arm("baseline", "1", "2", "3")
    arm["metrics"] = [
        {
            "metric_id": "auto_resolution_rate",
            "absolute_value": 1.2,
            "sample_size": 30,
            "confidence_level_basis_points": 9500,
            "lower_bound": 1.1,
            "upper_bound": 1.3,
        }
    ]
    with pytest.raises(ValueError, match="remain in"):
        _snapshot(baseline=arm)


@pytest.mark.parametrize("evaluated_at", [NOW - timedelta(seconds=1), NOW + timedelta(minutes=10)])
def test_stale_or_future_publication_is_unavailable(evaluated_at) -> None:
    state = {"revision": 1, "snapshot": _snapshot().model_dump(mode="json")}
    with pytest.raises(ValueError, match="not current"):
        DashboardComparisonSnapshot.from_state(state, evaluated_at=evaluated_at)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("valid_until", NOW),
        ("published_at", NOW - timedelta(hours=3)),
        ("published_at", 0),
        ("published_at", NOW.replace(tzinfo=None)),
        ("evidence_cutoff", NOW),
        ("fdai_revision", "main"),
        ("artifact_origin", "repository"),
        ("synthetic", True),
        ("synthetic", "false"),
        ("execution_authority", True),
        ("execution_authority", 0),
        ("promotion_authority", True),
        ("baseline", _arm("treatment", "1", "2", "3")),
        ("cohort_admission_receipt_digest", _digest("3")),
        ("verification_bundle_refs", (_digest("d"), _digest("d"))),
    ],
)
def test_invalid_or_authority_bearing_comparisons_are_rejected(field, value) -> None:
    with pytest.raises(ValueError):
        _snapshot(**{field: value})


def test_digest_seals_expiry_and_metric_values() -> None:
    snapshot = _snapshot()
    raw = snapshot.model_dump(mode="json")
    raw["valid_until"] = (NOW + timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError, match="digest"):
        DashboardComparisonSnapshot.model_validate(raw)


@pytest.mark.parametrize("revision", [True, 0, -1, "1"])
def test_state_revision_is_strictly_positive(revision) -> None:
    with pytest.raises(ValueError, match="revision"):
        DashboardComparisonSnapshot.from_state(
            {"revision": revision, "snapshot": _snapshot().model_dump(mode="json")},
            evaluated_at=NOW,
        )


def test_state_parser_rejects_missing_defaulted_source_fields() -> None:
    raw = _snapshot().model_dump(mode="json")
    raw.pop("artifact_origin")
    with pytest.raises(ValueError, match="fields"):
        DashboardComparisonSnapshot.from_state({"revision": 1, "snapshot": raw}, evaluated_at=NOW)
