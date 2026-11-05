from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.detection.series import MetricSample
from fdai.core.rca.hypothesis import (
    CAUSAL_CLOSURE_EVIDENCE_PURPOSE,
    CausalActionMode,
    CausalClosure,
    causal_action_mode,
    causal_closure_evidence_digest,
    causal_closure_scope_digest,
)
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
from fdai.shared.contracts.models import CausalEvidenceGrade, Event
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

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
        ({"intervention_target_ref": "resource:wrong"}, CausalClosure.INCONCLUSIVE),
        ({"predicted_effect_ref": "finding:wrong"}, CausalClosure.INCONCLUSIVE),
        ({"prohibited_effects_absent": False}, CausalClosure.UNSAFE),
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


async def test_intervention_at_evidence_cutoff_is_inconclusive() -> None:
    projector = _Projector()
    coordinator = _coordinator(_Provider(_evidence()), projector)
    analyzed = await coordinator.analyze(event=_event(), incident_id="incident-1")
    assert analyzed.hypothesis is not None

    closed = await coordinator.close(
        CausalClosureObservation(
            hypothesis=analyzed.hypothesis,
            finding_id="finding:latency",
            outcome_ref="outcome:cutoff",
            observed_at=datetime(2026, 8, 2, 1, tzinfo=UTC),
            expected_direction_matched=True,
            telemetry_complete=True,
            within_window=True,
            affected_scope_safe=True,
            intervention_approved=True,
            independent_observer=True,
            intervention_receipt_digest="a" * 64,
            intervention_executed_at=analyzed.hypothesis.evidence_cutoff,
            intervention_target_ref=analyzed.hypothesis.cause_ref,
            predicted_effect_ref=analyzed.hypothesis.effect_ref,
            prohibited_effects_absent=True,
        )
    )

    assert closed.closure is CausalClosure.INCONCLUSIVE


async def test_unverified_intervention_receipt_is_inconclusive() -> None:
    class _RejectingVerifier:
        async def verify(self, observation: CausalClosureObservation) -> bool:
            return False

    projector = _Projector()
    coordinator = CausalRuntimeCoordinator(
        evidence_provider=_Provider(_evidence()),
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
        intervention_receipt_verifier=_RejectingVerifier(),
    )
    analyzed = await coordinator.analyze(event=_event(), incident_id="incident-1")
    assert analyzed.hypothesis is not None
    closed = await coordinator.close(
        CausalClosureObservation(
            hypothesis=analyzed.hypothesis,
            finding_id="finding:latency",
            outcome_ref="outcome:unverified",
            observed_at=datetime(2026, 8, 2, 1, tzinfo=UTC),
            expected_direction_matched=True,
            telemetry_complete=True,
            within_window=True,
            affected_scope_safe=True,
            intervention_approved=True,
            independent_observer=True,
            intervention_receipt_digest="a" * 64,
            intervention_executed_at=datetime(2026, 8, 2, 0, 30, tzinfo=UTC),
            intervention_target_ref=analyzed.hypothesis.cause_ref,
            predicted_effect_ref=analyzed.hypothesis.effect_ref,
            prohibited_effects_absent=True,
        )
    )

    assert closed.closure is CausalClosure.INCONCLUSIVE


async def test_runtime_results_expose_shadow_mode_for_analysis_and_unsafe_closure() -> None:
    projector = _Projector()
    coordinator = _coordinator(_Provider(_evidence()), projector)

    missing = await _coordinator(_Provider(None), _Projector()).analyze(
        event=_event(),
        incident_id="incident-1",
    )
    analyzed = await coordinator.analyze(event=_event(), incident_id="incident-1")
    assert analyzed.hypothesis is not None
    unsafe = await coordinator.close(
        CausalClosureObservation(
            hypothesis=analyzed.hypothesis,
            finding_id="finding:latency",
            outcome_ref="outcome:unsafe",
            observed_at=datetime(2026, 8, 2, 1, tzinfo=UTC),
            expected_direction_matched=True,
            telemetry_complete=True,
            within_window=True,
            affected_scope_safe=False,
            intervention_approved=True,
            independent_observer=True,
        )
    )

    assert missing.action_mode is CausalActionMode.SHADOW
    assert analyzed.action_mode is CausalActionMode.SHADOW
    assert analyzed.decision_evidence is None
    assert unsafe.closure is CausalClosure.UNSAFE
    assert (
        causal_action_mode(
            unsafe,
            decision_evidence=None,
            evaluated_at=datetime(2026, 8, 2, 1, tzinfo=UTC),
        )
        is CausalActionMode.SHADOW
    )


class _StubAdmissionProvider:
    """Return one admission bound to whatever the boundary asked about."""

    def __init__(self, *, purpose_id: str | None = None) -> None:
        self._purpose_id = purpose_id
        self.requests: list[dict[str, str]] = []

    async def admit(
        self,
        *,
        evidence_digest: str,
        scope_digest: str,
        purpose_id: str,
        source_revision: str,
    ) -> DecisionEvidenceAdmission:
        self.requests.append(
            {
                "evidence_digest": evidence_digest,
                "scope_digest": scope_digest,
                "purpose_id": purpose_id,
                "source_revision": source_revision,
            }
        )
        digest = f"sha256:{'d' * 64}"
        return DecisionEvidenceAdmission(
            receipt_digest=digest,
            verification_bundle_digest=digest,
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=self._purpose_id or purpose_id,
            source_revision=source_revision,
            verified_at=_START,
            valid_until=_START + timedelta(days=7),
        )


async def test_the_runtime_binds_the_exact_causal_admission_request() -> None:
    admissions = _StubAdmissionProvider()
    coordinator = CausalRuntimeCoordinator(
        evidence_provider=_Provider(replace(_evidence(), refuting_evidence_ids=())),
        analyzer=TemporalCausalityAnalyzer(
            TemporalCausalityConfig(
                lag_seconds=(0, 3600, 7200),
                min_samples=12,
                min_abs_correlation=0.7,
                direction_margin=0.2,
                candidate_count=3,
            )
        ),
        projector=_Projector(),
        method_version="temporal-causal-v1",
        intervention_receipt_verifier=_InterventionVerifier(),
        decision_evidence_provider=admissions,
    )

    analyzed = await coordinator.analyze(event=_event(), incident_id="incident-1")
    assert analyzed.hypothesis is not None

    assert admissions.requests == [
        {
            "evidence_digest": causal_closure_evidence_digest(analyzed.hypothesis),
            "scope_digest": causal_closure_scope_digest(analyzed.hypothesis),
            "purpose_id": CAUSAL_CLOSURE_EVIDENCE_PURPOSE,
            "source_revision": "graph-r1",
        }
    ]
    assert analyzed.decision_evidence is not None
    assert analyzed.decision_evidence.execution_authority is False
    assert analyzed.decision_evidence.promotion_authority is False
    # A matched admission never raises the mode: this temporal grade stays below
    # quasi-experimental, so the revision remains evidence-only.
    assert analyzed.hypothesis.evidence_grade is CausalEvidenceGrade.PREDICTIVE_PRECEDENCE
    assert analyzed.action_mode is CausalActionMode.SHADOW


def test_temporal_evidence_and_closure_observation_boundary_validations() -> None:
    base = _evidence()
    with_confounder = replace(base, confounder=_series("conf", (1.0, 2.0)))
    assert with_confounder.confounder is not None

    deep: dict[str, object] = {"leaf": 1}
    for _ in range(12):
        deep = {"nested": deep}
    cyclic_dict: dict[str, object] = {}
    cyclic_dict["self"] = cyclic_dict
    cyclic_list: list[object] = []
    cyclic_list.append(cyclic_list)

    for changes, match in (
        ({"topological_reachability": 1.5}, "topological_reachability MUST be in"),
        ({"ambiguity": 0}, "ambiguity MUST be >= 1"),
        ({"refutation_complete": "yes"}, "refutation_complete MUST be boolean"),
        ({"feature_cutoff": datetime(2026, 8, 1)}, "cutoff MUST be timezone-aware"),
        ({"cause_ref": ""}, "identity MUST be non-empty"),
        ({"evidence_refs": ("",)}, "evidence_refs refs MUST be bounded"),
        (
            {
                "endpoint_objects": tuple(
                    OntologyObjectRecord(id=f"id:{i}", object_type="Service", properties={})
                    for i in range(129)
                )
            },
            "endpoint objects MUST be bounded",
        ),
        (
            {"endpoint_objects": (OntologyObjectRecord("id:1", "Service", deep),)},
            "too deeply nested",
        ),
        (
            {
                "endpoint_objects": (
                    OntologyObjectRecord("id:1", "Service", {"blob": "x" * 600_000}),
                )
            },
            "exceed their byte limit",
        ),
        (
            {"endpoint_objects": (OntologyObjectRecord("id:1", "Service", cyclic_dict),)},
            "contain a cycle",
        ),
        (
            {
                "endpoint_objects": (
                    OntologyObjectRecord("id:1", "Service", {"items": cyclic_list}),
                )
            },
            "contain a cycle",
        ),
    ):
        with pytest.raises(ValueError, match=match):
            replace(base, **changes)  # type: ignore[arg-type]


async def test_closure_observation_and_coordinator_guard_branches() -> None:
    projector = _Projector()
    coordinator = _coordinator(_Provider(_evidence()), projector)
    analyzed = await coordinator.analyze(event=_event(), incident_id="incident-1")
    assert analyzed.hypothesis is not None
    hyp = analyzed.hypothesis

    deep: dict[str, object] = {"leaf": 1}
    for _ in range(12):
        deep = {"nested": deep}

    valid_obs = CausalClosureObservation(
        hypothesis=hyp,
        finding_id="finding:latency",
        outcome_ref="outcome:ok",
        observed_at=_event().ingested_at,
        expected_direction_matched=None,
        telemetry_complete=True,
        within_window=True,
        affected_scope_safe=True,
        intervention_approved=True,
        independent_observer=True,
        intervention_receipt_digest="a" * 64,
        intervention_executed_at=datetime(2026, 8, 1, 22, tzinfo=UTC),
        intervention_target_ref=hyp.cause_ref,
        predicted_effect_ref=hyp.effect_ref,
        prohibited_effects_absent=True,
        intervention_action_ref="action:1",
        intervention_resource_ref="resource:1",
    )
    for changes, match in (
        ({"finding_id": ""}, "finding and outcome refs MUST be non-empty"),
        ({"observed_at": datetime(2026, 8, 2)}, "observed_at MUST be timezone-aware"),
        ({"telemetry_complete": "yes"}, "checks MUST be boolean"),
        ({"expected_direction_matched": "yes"}, "direction result MUST be boolean"),
        (
            {
                "intervention_executed_at": None,
                "intervention_action_ref": None,
                "intervention_resource_ref": None,
            },
            "supplied together",
        ),
        ({"intervention_receipt_digest": "bad"}, "MUST be SHA-256"),
        ({"intervention_executed_at": datetime(2026, 8, 2)}, "execution time is invalid"),
        ({"intervention_target_ref": ""}, "intervention refs MUST be non-empty"),
        ({"intervention_action_ref": " "}, "action ref requires a bounded receipt"),
        ({"intervention_resource_ref": " "}, "resource ref requires an exact bounded"),
        (
            {
                "endpoint_objects": tuple(
                    OntologyObjectRecord(id=f"id:{i}", object_type="Service", properties={})
                    for i in range(129)
                )
            },
            "endpoint count exceeds",
        ),
        (
            {"endpoint_objects": (OntologyObjectRecord("id:1", "Service", deep),)},
            "exceed their depth bound",
        ),
        (
            {
                "endpoint_objects": (
                    OntologyObjectRecord("id:1", "Service", {"blob": "x" * 600_000}),
                )
            },
            "exceed their byte bound",
        ),
    ):
        with pytest.raises(ValueError, match=match):
            replace(valid_obs, **changes)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="method_version MUST be non-empty"):
        CausalRuntimeCoordinator(
            evidence_provider=None, analyzer=None, projector=projector, method_version=""
        )
    with pytest.raises(ValueError, match="MUST be bound together"):
        CausalRuntimeCoordinator(
            evidence_provider=_Provider(None),
            analyzer=None,
            projector=projector,
            method_version="v1",
        )

    class _ClosureSource:
        def __init__(self, items: object) -> None:
            self.items = items

        async def collect(self, *, event: Event, incident_id: str) -> Any:
            return self.items

    for bad_items, match in (
        ([valid_obs], "at most 32 immutable observations"),
        ((valid_obs, valid_obs), "changed incident, cutoff or outcome identity"),
    ):
        bad_coord = CausalRuntimeCoordinator(
            evidence_provider=None,
            analyzer=None,
            projector=projector,
            method_version="v1",
            closure_source=_ClosureSource(bad_items),
        )
        with pytest.raises(ValueError, match=match):
            await bad_coord.analyze(event=_event(), incident_id="incident-1")

    close_only = CausalRuntimeCoordinator(
        evidence_provider=None,
        analyzer=None,
        projector=projector,
        method_version="v1",
        closure_source=_ClosureSource((valid_obs,)),
    )
    closed_res = await close_only.analyze(event=_event(), incident_id="incident-1")
    assert closed_res.outcome is CausalRuntimeOutcome.CLOSED
    assert len(closed_res.closed_hypotheses) == 1

    late_cutoff = replace(_evidence(), feature_cutoff=datetime(2026, 8, 3, tzinfo=UTC))
    with pytest.raises(ValueError, match="MUST NOT follow event ingestion"):
        await _coordinator(_Provider(late_cutoff), projector).analyze(
            event=_event(), incident_id="incident-1"
        )

    short = _series("short", (1.0, 2.0))
    no_claim_ev = replace(
        _evidence(), cause=short, effect=short, feature_cutoff=short.samples[-1].timestamp
    )
    no_claim_res = await _coordinator(_Provider(no_claim_ev), projector).analyze(
        event=_event(), incident_id="incident-1"
    )
    assert no_claim_res.outcome is CausalRuntimeOutcome.NO_CLAIM

    broken = _coordinator(_Provider(_evidence()), projector)
    broken._analyzer = None
    with pytest.raises(RuntimeError, match="no bound analyzer"):
        await broken.analyze(event=_event(), incident_id="incident-1")
