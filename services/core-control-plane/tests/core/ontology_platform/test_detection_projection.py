from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID, uuid4

import pytest
from fdai.core.case_history import OperationalEvidenceSourceKind, OperationalOutcomeClass
from fdai.core.detection.forecast_episode import (
    ForecastEpisode,
    ForecastEpisodeState,
    ForecastEvaluationKind,
)
from fdai.core.ontology_platform.detection_projection import (
    DetectionOntologyProjector,
    ProducerAttestation,
    _record_digest,
    forecast_object_record,
    pattern_object_record,
)
from fdai.core.operational_learning.patterns import (
    OperatingPatternCandidate,
    OperatingPatternCompiler,
    PatternCase,
)
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyObjectRecord,
)

NOW = datetime(2026, 8, 27, tzinfo=UTC)
SCOPE_DIGEST = "a" * 64
FINGERPRINT = "b" * 64


class _Store:
    def __init__(self) -> None:
        self.records: dict[str, OntologyObjectRecord] = {}
        self.writes = 0

    async def create_object_if_absent(
        self,
        record: OntologyObjectRecord,
    ) -> OntologyObjectRecord | None:
        if record.id in self.records:
            return None
        self.writes += 1
        self.records[record.id] = record
        return record

    async def get_object(self, object_id: str) -> OntologyObjectRecord | None:
        return self.records.get(object_id)

    async def upsert_object(
        self,
        record: OntologyObjectRecord,
        *,
        expected_revision: int | None = None,
    ) -> OntologyObjectRecord:
        del expected_revision
        self.writes += 1
        self.records[record.id] = record
        return record


class _Authenticator:
    def verify(self, *, agent: str, credential_ref: str, content_digest: str) -> bool:
        return credential_ref == f"credential:{agent}" and bool(content_digest)


def _episode(
    kind: ForecastEvaluationKind = ForecastEvaluationKind.PREDICTED_BREACH,
) -> ForecastEpisode:
    return ForecastEpisode(
        episode_id=uuid4(),
        correlation_id="forecast:example",
        detector_id="detector.example",
        detector_version="v1",
        scorer_version="scorer.v1",
        access_scope_digest=SCOPE_DIGEST,
        target_ref="resource-example",
        metric="cpu",
        feature_cutoff=NOW,
        horizon_started_at=NOW,
        horizon_ended_at=NOW + timedelta(seconds=600),
        telemetry_grace_seconds=60,
        direction="rising",
        threshold=90.0,
        evaluation_kind=kind,
        predicted_value=95.0 if kind is ForecastEvaluationKind.PREDICTED_BREACH else None,
        interval_lower=92.0 if kind is ForecastEvaluationKind.PREDICTED_BREACH else None,
        interval_upper=98.0 if kind is ForecastEvaluationKind.PREDICTED_BREACH else None,
        evidence_refs=("metric-window:example",),
        abstain_reason=None,
    )


def _candidate() -> OperatingPatternCandidate:
    candidate = OperatingPatternCompiler().compile(_cases())
    assert candidate is not None
    return candidate


def _attestation(
    record: OntologyObjectRecord,
    *,
    agent: Literal["Heimdall", "Norns"],
) -> ProducerAttestation:
    return ProducerAttestation(
        agent=agent,
        credential_ref=f"credential:{agent}",
        content_digest=_record_digest(record),
    )


def _cases() -> tuple[PatternCase, PatternCase]:
    return (
        PatternCase(
            case_id="case-one",
            revision=1,
            manifest_digest="c" * 64,
            failure_fingerprint=FINGERPRINT,
            resource_type="compute.vm",
            action_type="restart",
            outcome_class=OperationalOutcomeClass.SUCCESS,
            reusable=True,
            negative=False,
            digest_evidence=(FINGERPRINT,),
            fdai_revision="a" * 40,
            scenario_set_version="v2026.08",
            event_time_cutoff=NOW,
            source_kind=OperationalEvidenceSourceKind.LIVE,
            source_identity_digest="1" * 64,
            source_synthetic=False,
            evidence_complete=True,
            conflict_digests=(),
        ),
        PatternCase(
            case_id="case-two",
            revision=1,
            manifest_digest="d" * 64,
            failure_fingerprint=FINGERPRINT,
            resource_type="compute.vm",
            action_type="restart",
            outcome_class=OperationalOutcomeClass.ROLLBACK,
            reusable=False,
            negative=True,
            digest_evidence=(FINGERPRINT,),
            fdai_revision="a" * 40,
            scenario_set_version="v2026.08",
            event_time_cutoff=NOW,
            source_kind=OperationalEvidenceSourceKind.LIVE,
            source_identity_digest="2" * 64,
            source_synthetic=False,
            evidence_complete=True,
            conflict_digests=(),
        ),
    )


def test_forecast_and_pattern_records_match_catalog_shapes() -> None:
    forecast = forecast_object_record(_episode(), confidence=0.9, issued_at=NOW)
    pattern = pattern_object_record(_candidate(), compiled_at=NOW)

    assert isinstance(forecast, OntologyObjectRecord)
    assert forecast.properties["horizon_seconds"] == 600
    assert forecast.properties["breach_predicate"] == "cpu:rising:90"
    assert pattern.properties["evidence_digest"].startswith("sha256:")
    assert pattern.properties["sample_size"] == 2


async def test_projector_persists_each_record_once_and_replays_idempotently() -> None:
    store = _Store()
    projector = DetectionOntologyProjector(
        cast(OntologyInstanceStore, store),
        authenticator=_Authenticator(),
    )
    episode = _episode()
    record = forecast_object_record(episode, confidence=0.9, issued_at=NOW)
    attestation = _attestation(record, agent="Heimdall")

    first = await projector.project_forecast(
        episode,
        confidence=0.9,
        issued_at=NOW,
        attestation=attestation,
    )
    second = await projector.project_forecast(
        _episode_from(first),
        confidence=0.9,
        issued_at=NOW,
        attestation=attestation,
    )

    assert first == second
    assert store.writes == 1
    assert isinstance(store.records[first.id].properties["feature_cutoff"], str)


async def test_projector_concurrent_delivery_uses_atomic_create() -> None:
    store = _Store()
    projector = DetectionOntologyProjector(
        cast(OntologyInstanceStore, store),
        authenticator=_Authenticator(),
    )
    episode = _episode()
    attestation = _attestation(
        forecast_object_record(episode, confidence=0.9, issued_at=NOW),
        agent="Heimdall",
    )

    results = await asyncio.gather(
        *(
            projector.project_forecast(
                episode,
                confidence=0.9,
                issued_at=NOW,
                attestation=attestation,
            )
            for _ in range(8)
        )
    )

    assert len({item.id for item in results}) == 1
    assert store.writes == 1


async def test_projector_requires_authenticated_owner_and_revalidates_pattern_cohort() -> None:
    store = _Store()
    projector = DetectionOntologyProjector(
        cast(OntologyInstanceStore, store),
        authenticator=_Authenticator(),
    )
    candidate = _candidate()
    pattern = pattern_object_record(candidate, compiled_at=NOW)

    stored = await projector.project_pattern(
        candidate,
        compiled_at=NOW,
        cases=_cases(),
        attestation=_attestation(pattern, agent="Norns"),
    )

    assert stored.object_type == "Pattern"
    with pytest.raises(ValueError, match="producer MUST be Norns"):
        await projector.project_pattern(
            candidate,
            compiled_at=NOW,
            cases=_cases(),
            attestation=_attestation(pattern, agent="Heimdall"),
        )
    with pytest.raises(ValueError, match="balanced sealed cohort"):
        await projector.project_pattern(
            candidate,
            compiled_at=NOW,
            cases=(_cases()[0],),
            attestation=_attestation(pattern, agent="Norns"),
        )


async def test_forecast_requires_open_episode_and_verified_heimdall_attestation() -> None:
    store = _Store()
    projector = DetectionOntologyProjector(
        cast(OntologyInstanceStore, store),
        authenticator=_Authenticator(),
    )
    closed = replace(_episode(), state=ForecastEpisodeState.CLOSED)
    record = forecast_object_record(_episode(), confidence=0.9, issued_at=NOW)
    with pytest.raises(ValueError, match="open Forecast"):
        await projector.project_forecast(
            closed,
            confidence=0.9,
            issued_at=NOW,
            attestation=_attestation(record, agent="Heimdall"),
        )
    open_episode = _episode()
    with pytest.raises(ValueError, match="attestation"):
        await projector.project_forecast(
            open_episode,
            confidence=0.9,
            issued_at=NOW,
            attestation=ProducerAttestation(
                agent="Heimdall",
                credential_ref="credential:Heimdall",
                content_digest="sha256:" + "e" * 64,
            ),
        )


def _episode_from(record: OntologyObjectRecord) -> ForecastEpisode:
    return ForecastEpisode(
        episode_id=UUID(record.id),
        correlation_id="forecast:example",
        detector_id="detector.example",
        detector_version="v1",
        scorer_version="scorer.v1",
        access_scope_digest=SCOPE_DIGEST,
        target_ref="resource-example",
        metric="cpu",
        feature_cutoff=NOW,
        horizon_started_at=NOW,
        horizon_ended_at=NOW + timedelta(seconds=600),
        telemetry_grace_seconds=60,
        direction="rising",
        threshold=90.0,
        evaluation_kind=ForecastEvaluationKind.PREDICTED_BREACH,
        predicted_value=95.0,
        interval_lower=92.0,
        interval_upper=98.0,
        evidence_refs=("metric-window:example",),
    )


@pytest.mark.parametrize(
    ("factory", "message"),
    (
        (
            lambda: forecast_object_record(
                _episode(ForecastEvaluationKind.PREDICTED_NO_BREACH),
                confidence=0.9,
                issued_at=NOW,
            ),
            "only predicted",
        ),
        (
            lambda: forecast_object_record(_episode(), confidence=1.1, issued_at=NOW),
            "confidence",
        ),
    ),
)
def test_forecast_producer_rejects_unsupported_inputs(
    factory: Callable[[], object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()
