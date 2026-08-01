from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fdai.core.detection.series import MetricSample
from fdai.core.rca.hypothesis import CausalClosure
from fdai.core.rca.runtime import (
    CausalClosureObservation,
    CausalRuntimeCoordinator,
    CausalRuntimeOutcome,
    TemporalCausalEvidence,
)
from fdai.core.rca.temporal_causality import (
    TemporalCausalityAnalyzer,
    TemporalCausalityConfig,
    TemporalSeries,
)
from fdai.shared.contracts.models import Event

_START = datetime(2026, 8, 1, tzinfo=UTC)
_VALUES = (3, 8, 1, 7, 2, 9, 4, 6, 0, 5, 11, 3, 10, 2, 8, 1, 12, 4, 9, 0, 7, 5, 13, 2)


def _series(metric: str, values: tuple[float, ...]) -> TemporalSeries:
    return TemporalSeries(
        metric=metric,
        samples=tuple(
            MetricSample(timestamp=_START + timedelta(hours=index), value=value)
            for index, value in enumerate(values)
        ),
    )


def _evidence() -> TemporalCausalEvidence:
    cause = _series("request_rate", tuple(float(value) for value in _VALUES))
    effect = _series("latency", (0.0, *(float(value * 2) for value in _VALUES[:-1])))
    return TemporalCausalEvidence(
        cause=cause,
        effect=effect,
        feature_cutoff=effect.samples[-1].timestamp,
        evidence_refs=("metric-window:request-latency",),
        cause_ref="metric:request-rate",
        effect_ref="finding:latency",
        mechanism="load-saturation",
        graph_revision="graph-r1",
        finding_id="finding:latency",
        topological_reachability=0.9,
        mechanism_fit=0.9,
        intervention_consistency=0.8,
        evidence_completeness=0.9,
        supporting_evidence_ids=("evidence:support",),
        refutation_complete=True,
        refuting_evidence_ids=("evidence:refutation-query",),
    )


def _event() -> Event:
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "idempotency_key": "event-1",
            "source": "example",
            "event_type": "anomaly",
            "detected_at": "2026-08-02T00:00:00Z",
            "ingested_at": "2026-08-02T00:00:01Z",
            "mode": "shadow",
            "payload": {},
        }
    )


class _Provider:
    def __init__(self, evidence: TemporalCausalEvidence | None) -> None:
        self._evidence = evidence

    async def collect(self, *, event: Event, incident_id: str) -> TemporalCausalEvidence | None:
        return self._evidence


class _Projector:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    async def project(self, hypothesis: Any, **kwargs: Any) -> None:
        self.calls.append((hypothesis, kwargs))


class _InterventionVerifier:
    async def verify(self, observation: CausalClosureObservation) -> bool:
        return True


def _coordinator(provider: _Provider, projector: _Projector) -> CausalRuntimeCoordinator:
    return CausalRuntimeCoordinator(
        evidence_provider=provider,
        analyzer=TemporalCausalityAnalyzer(
            TemporalCausalityConfig(
                lag_seconds=(0, 3600, 7200),
                min_samples=12,
                min_abs_correlation=0.7,
                direction_margin=0.2,
                candidate_count=3,
            )
        ),
        projector=projector,
        method_version="temporal-causal-v1",
        intervention_receipt_verifier=_InterventionVerifier(),
    )


async def test_temporal_runtime_projects_immutable_hypothesis() -> None:
    projector = _Projector()
    coordinator = _coordinator(_Provider(_evidence()), projector)

    result = await coordinator.analyze(event=_event(), incident_id="incident-1")

    assert result.outcome is CausalRuntimeOutcome.ANALYZED
    assert result.claim is not None
    assert result.claim.lag_seconds == 3600
    assert result.hypothesis is not None
    assert result.hypothesis.incident_id == "incident-1"
    assert result.hypothesis.supporting_refs == ("evidence:support",)
    assert projector.calls[0][1]["finding_id"] == "finding:latency"


async def test_temporal_runtime_reports_missing_evidence_without_projection() -> None:
    projector = _Projector()
    coordinator = _coordinator(_Provider(None), projector)

    result = await coordinator.analyze(event=_event(), incident_id="incident-1")

    assert result.outcome is CausalRuntimeOutcome.NO_EVIDENCE
    assert projector.calls == []


def test_temporal_runtime_evidence_rejects_unbounded_projection_refs() -> None:
    with pytest.raises(ValueError, match="change_ids MUST be bounded"):
        replace(
            _evidence(),
            change_ids=tuple(f"change:{index}" for index in range(33)),
        )


def test_temporal_runtime_evidence_rejects_unbounded_series_samples() -> None:
    samples = tuple(
        MetricSample(timestamp=_START + timedelta(seconds=index), value=float(index))
        for index in range(2_050)
    )
    with pytest.raises(ValueError, match="series samples MUST be bounded"):
        replace(
            _evidence(),
            cause=TemporalSeries(metric="cause", samples=samples),
            effect=TemporalSeries(metric="effect", samples=samples),
        )


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, CausalClosure.CONFIRMED),
        ({"expected_direction_matched": False}, CausalClosure.REFUTED),
        ({"telemetry_complete": False}, CausalClosure.INCONCLUSIVE),
        ({"within_window": False}, CausalClosure.INCONCLUSIVE),
        ({"independent_observer": False}, CausalClosure.INCONCLUSIVE),
        ({"intervention_approved": False}, CausalClosure.INCONCLUSIVE),
        ({"affected_scope_safe": False}, CausalClosure.UNSAFE),
    ],
)
async def test_independent_outcome_classifies_and_projects_closure(
    changes: dict[str, object],
    expected: CausalClosure,
) -> None:
    projector = _Projector()
    coordinator = _coordinator(_Provider(_evidence()), projector)
    analyzed = await coordinator.analyze(event=_event(), incident_id="incident-1")
    assert analyzed.hypothesis is not None
    values: dict[str, object] = {
        "hypothesis": analyzed.hypothesis,
        "finding_id": "finding:latency",
        "outcome_ref": "outcome:1",
        "observed_at": datetime(2026, 8, 2, 1, tzinfo=UTC),
        "expected_direction_matched": True,
        "telemetry_complete": True,
        "within_window": True,
        "affected_scope_safe": True,
        "intervention_approved": True,
        "independent_observer": True,
        "intervention_receipt_digest": "a" * 64,
        "intervention_executed_at": datetime(2026, 8, 2, 0, 30, tzinfo=UTC),
        "intervention_target_ref": analyzed.hypothesis.cause_ref,
        "predicted_effect_ref": analyzed.hypothesis.effect_ref,
        "prohibited_effects_absent": True,
    }
    values.update(changes)

    closed = await coordinator.close(CausalClosureObservation(**values))  # type: ignore[arg-type]

    assert closed.closure is expected
    assert projector.calls[-1][1]["outcome_ids"] == ("outcome:1",)
    assert projector.calls[-1][1]["previous_hypothesis_id"] == (analyzed.hypothesis.hypothesis_id)
