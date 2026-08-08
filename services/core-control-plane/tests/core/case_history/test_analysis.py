from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fdai.core.case_history import CaseHistoryAnalyzer, CaseHistoryMaterializer
from fdai.core.case_history.testing import (
    InMemoryCaseHistoryArtifactStore,
    InMemoryCaseHistoryMetadataStore,
)
from fdai.core.learning import NoImprovement, PostTurnReviewInput, RuleCandidateHint
from fdai.shared.contracts.models import ForecastOutcome

T0 = datetime(2026, 7, 1, tzinfo=UTC)


def _outcome(
    index: int,
    label: str,
    *,
    detector_id: str = "capacity-linear",
    metric: str = "capacity_percent",
) -> ForecastOutcome:
    breach = T0 + timedelta(minutes=30) if label == "true_positive" else None
    return ForecastOutcome.model_validate(
        {
            "schema_version": "1.0.0",
            "outcome_id": UUID(int=index + 1),
            "idempotency_key": f"outcome-{index}",
            "correlation_id": f"corr-{index}",
            "prediction_id": UUID(int=index + 100),
            "detector_id": detector_id,
            "detector_version": "1.0.0",
            "access_scope_digest": "a" * 64,
            "target_digest": "b" * 64,
            "metric": metric,
            "feature_cutoff": T0,
            "horizon_started_at": T0,
            "horizon_ended_at": T0 + timedelta(hours=1),
            "direction": "rising",
            "threshold": 90.0,
            "predicted_value": 95.0,
            "interval_lower": 91.0,
            "interval_upper": 99.0,
            "observed_value": 94.0 if breach else 70.0,
            "actual_breach_at": breach,
            "label": label,
            "evidence_refs": [f"metric-window:{index}"],
            "telemetry_completeness": "complete",
            "closed_at": T0 + timedelta(hours=2, minutes=index),
            "mode": "shadow",
        }
    )


class _Reviewer:
    def __init__(self) -> None:
        self.inputs: list[PostTurnReviewInput] = []

    async def review(self, review_input: PostTurnReviewInput):
        self.inputs.append(review_input)
        return RuleCandidateHint(
            proposal_kind="threshold_adjustment",
            target_ref="capacity-linear",
            pattern="Use a seasonal baseline before changing the threshold.",
            evidence_refs=review_input.evidence_refs,
            confidence=0.8,
        )


async def _seed():
    metadata = InMemoryCaseHistoryMetadataStore()
    artifacts = InMemoryCaseHistoryArtifactStore()
    materializer = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    for index, label in enumerate(("false_positive", "false_positive", "true_positive")):
        outcome = _outcome(index, label)
        await materializer.seal_forecast_outcome(
            outcome,
            purpose="forecast-error-analysis",
            redaction_policy_version="1.0.0",
            retention_until=T0 + timedelta(days=30),
            deletion_due_at=T0 + timedelta(days=60),
        )
    return metadata, artifacts


async def _record_for_correlation(
    metadata: InMemoryCaseHistoryMetadataStore,
    correlation_id: str,
):
    records = await metadata.list_closed(
        access_scope_digest="a" * 64,
        purpose="forecast-error-analysis",
        outcome_labels=(),
        limit=500,
    )
    return next(record for record in records if record.correlation_id == correlation_id)


async def test_analyzer_supplies_failure_and_control_cases_with_evidence() -> None:
    metadata, artifacts = await _seed()
    reviewer = _Reviewer()
    analyzer = CaseHistoryAnalyzer(
        metadata=metadata,
        artifacts=artifacts,
        reviewer=reviewer,
    )
    hint = await analyzer.analyze(
        {
            "kind": "forecast_case_history",
            "access_scope_digest": "a" * 64,
            "purpose": "forecast-error-analysis",
            "detector_id": "capacity-linear",
            "metric": "capacity_percent",
        }
    )
    assert hint is not None
    assert len(reviewer.inputs) == 1
    body = reviewer.inputs[0].assistant_body or ""
    assert '"cohort":"failure"' in body
    assert '"cohort":"control"' in body
    assert set(hint.evidence_refs) == set(reviewer.inputs[0].evidence_refs)


async def test_analyzer_limits_after_detector_and_metric_filters() -> None:
    metadata = InMemoryCaseHistoryMetadataStore()
    artifacts = InMemoryCaseHistoryArtifactStore()
    materializer = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    for outcome in (
        _outcome(0, "false_positive"),
        _outcome(1, "true_positive"),
        _outcome(2, "false_positive", detector_id="latency-seasonal", metric="latency_ms"),
    ):
        await materializer.seal_forecast_outcome(
            outcome,
            purpose="forecast-error-analysis",
            redaction_policy_version="1.0.0",
            retention_until=T0 + timedelta(days=30),
            deletion_due_at=T0 + timedelta(days=60),
        )
    reviewer = _Reviewer()
    analyzer = CaseHistoryAnalyzer(
        metadata=metadata,
        artifacts=artifacts,
        reviewer=reviewer,
        failure_limit=1,
        control_limit=1,
    )

    hint = await analyzer.analyze(
        {
            "kind": "forecast_case_history",
            "access_scope_digest": "a" * 64,
            "purpose": "forecast-error-analysis",
            "detector_id": "capacity-linear",
            "metric": "capacity_percent",
        }
    )

    assert hint is not None
    assert len(reviewer.inputs) == 1
    assert '"detector_id":"latency-seasonal"' not in (reviewer.inputs[0].assistant_body or "")


async def test_analyzer_denies_cross_scope_history() -> None:
    metadata, artifacts = await _seed()

    class _NoCall:
        async def review(self, review_input: PostTurnReviewInput):
            raise AssertionError(f"reviewer must not run: {review_input.review_id}")

    analyzer = CaseHistoryAnalyzer(
        metadata=metadata,
        artifacts=artifacts,
        reviewer=_NoCall(),
    )
    assert (
        await analyzer.analyze(
            {
                "kind": "forecast_case_history",
                "access_scope_digest": "f" * 64,
                "purpose": "forecast-error-analysis",
                "detector_id": "capacity-linear",
                "metric": "capacity_percent",
            }
        )
        is None
    )


async def test_analyzer_rejects_artifact_from_another_case_identity() -> None:
    metadata, artifacts = await _seed()
    original = await _record_for_correlation(metadata, "corr-0")
    metadata._records[original.case_id][-1] = replace(  # noqa: SLF001
        original,
        case_id="forged-case-id",
    )

    class _NoCall:
        async def review(self, review_input: PostTurnReviewInput):
            raise AssertionError(f"reviewer must not run: {review_input.review_id}")

    analyzer = CaseHistoryAnalyzer(
        metadata=metadata,
        artifacts=artifacts,
        reviewer=_NoCall(),
    )
    assert (
        await analyzer.analyze(
            {
                "kind": "forecast_case_history",
                "access_scope_digest": "a" * 64,
                "purpose": "forecast-error-analysis",
                "detector_id": "capacity-linear",
                "metric": "capacity_percent",
            }
        )
        is None
    )


async def test_analyzer_abstains_when_artifact_is_missing() -> None:
    metadata, _artifacts = await _seed()
    analyzer = CaseHistoryAnalyzer(
        metadata=metadata,
        artifacts=InMemoryCaseHistoryArtifactStore(),
        reviewer=_Reviewer(),
    )
    assert (
        await analyzer.analyze(
            {
                "kind": "forecast_case_history",
                "access_scope_digest": "a" * 64,
                "purpose": "forecast-error-analysis",
                "detector_id": "capacity-linear",
                "metric": "capacity_percent",
            }
        )
        is None
    )


async def test_analyzer_abstains_when_any_selected_artifact_is_missing() -> None:
    metadata, artifacts = await _seed()
    failures = await metadata.list_closed(
        access_scope_digest="a" * 64,
        purpose="forecast-error-analysis",
        outcome_labels=("false_positive",),
        limit=10,
    )
    assert failures[0].storage_ref is not None
    await artifacts.delete(failures[0].storage_ref)
    analyzer = CaseHistoryAnalyzer(
        metadata=metadata,
        artifacts=artifacts,
        reviewer=_Reviewer(),
    )
    assert (
        await analyzer.analyze(
            {
                "kind": "forecast_case_history",
                "access_scope_digest": "a" * 64,
                "purpose": "forecast-error-analysis",
                "detector_id": "capacity-linear",
                "metric": "capacity_percent",
            }
        )
        is None
    )


async def test_analyzer_does_not_mix_metrics_for_same_detector() -> None:
    metadata, artifacts = await _seed()
    latest = await _record_for_correlation(metadata, "corr-0")
    metadata._records[latest.case_id][-1] = replace(latest, metric="latency_ms")
    reviewer = _Reviewer()
    analyzer = CaseHistoryAnalyzer(
        metadata=metadata,
        artifacts=artifacts,
        reviewer=reviewer,
    )
    await analyzer.analyze(
        {
            "kind": "forecast_case_history",
            "access_scope_digest": "a" * 64,
            "purpose": "forecast-error-analysis",
            "detector_id": "capacity-linear",
            "metric": "capacity_percent",
        }
    )
    assert reviewer.inputs
    assert '"metric":"latency_ms"' not in (reviewer.inputs[0].assistant_body or "")


async def test_analyzer_bounds_concurrent_artifact_fetches() -> None:
    metadata, artifacts = await _seed()

    class _MeasuredArtifacts:
        def __init__(self) -> None:
            self.active = 0
            self.maximum = 0

        async def get(self, storage_ref: str):
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            await asyncio.sleep(0)
            try:
                return await artifacts.get(storage_ref)
            finally:
                self.active -= 1

        async def put(self, storage_ref: str, content: bytes, *, digest: str):
            return await artifacts.put(storage_ref, content, digest=digest)

        async def delete(self, storage_ref: str):
            await artifacts.delete(storage_ref)

    measured = _MeasuredArtifacts()
    analyzer = CaseHistoryAnalyzer(
        metadata=metadata,
        artifacts=measured,
        reviewer=_Reviewer(),
        artifact_concurrency=2,
    )
    await analyzer.analyze(
        {
            "kind": "forecast_case_history",
            "access_scope_digest": "a" * 64,
            "purpose": "forecast-error-analysis",
            "detector_id": "capacity-linear",
            "metric": "capacity_percent",
        }
    )
    assert measured.maximum <= 2


async def test_analyzer_abstains_when_projection_returns_tombstone() -> None:
    metadata, artifacts = await _seed()
    record = await _record_for_correlation(metadata, "corr-0")
    tombstone = replace(
        record,
        storage_ref=None,
        artifact_size=0,
        deleted_at=T0 + timedelta(days=61),
    )

    class _StaleProjection:
        async def list_closed(
            self,
            *,
            access_scope_digest: str,
            purpose: str,
            outcome_labels: tuple[str, ...],
            detector_id: str | None = None,
            metric: str | None = None,
            limit: int,
        ):
            del access_scope_digest, purpose, detector_id, metric, limit
            return (tombstone,) if "false_positive" in outcome_labels else ()

    class _NoCall:
        async def review(self, review_input: PostTurnReviewInput):
            raise AssertionError(f"reviewer must not run: {review_input.review_id}")

    analyzer = CaseHistoryAnalyzer(
        metadata=_StaleProjection(),
        artifacts=artifacts,
        reviewer=_NoCall(),
    )
    assert (
        await analyzer.analyze(
            {
                "kind": "forecast_case_history",
                "access_scope_digest": "a" * 64,
                "purpose": "forecast-error-analysis",
                "detector_id": "capacity-linear",
                "metric": "capacity_percent",
            }
        )
        is None
    )


async def test_non_rule_proposal_is_not_routed() -> None:
    metadata, artifacts = await _seed()

    class _Abstain:
        async def review(self, review_input: PostTurnReviewInput):
            return NoImprovement(reason="no_change")

    analyzer = CaseHistoryAnalyzer(
        metadata=metadata,
        artifacts=artifacts,
        reviewer=_Abstain(),
    )
    assert (
        await analyzer.analyze(
            {
                "kind": "forecast_case_history",
                "access_scope_digest": "a" * 64,
                "purpose": "forecast-error-analysis",
                "detector_id": "capacity-linear",
                "metric": "capacity_percent",
            }
        )
        is None
    )


async def test_analyzer_rejects_reviewer_provenance_injection() -> None:
    metadata, artifacts = await _seed()

    class _ForgedReviewer:
        async def review(self, review_input: PostTurnReviewInput):
            return RuleCandidateHint(
                proposal_kind="threshold_adjustment",
                target_ref="capacity-linear",
                pattern="Unsupported external evidence.",
                evidence_refs=("case-history:other-scope:1:deadbeef",),
                confidence=0.8,
            )

    analyzer = CaseHistoryAnalyzer(
        metadata=metadata,
        artifacts=artifacts,
        reviewer=_ForgedReviewer(),
    )
    assert (
        await analyzer.analyze(
            {
                "kind": "forecast_case_history",
                "access_scope_digest": "a" * 64,
                "purpose": "forecast-error-analysis",
                "detector_id": "capacity-linear",
                "metric": "capacity_percent",
            }
        )
        is None
    )
