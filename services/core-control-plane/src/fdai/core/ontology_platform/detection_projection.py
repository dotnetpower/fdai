"""Project deterministic detection and learning outputs into ontology objects."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, Protocol

from fdai.core.detection.forecast_episode import (
    ForecastEpisode,
    ForecastEpisodeState,
    ForecastEvaluationKind,
)
from fdai.core.operational_learning.patterns import (
    OperatingPatternCandidate,
    OperatingPatternCompiler,
    PatternCase,
)
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyObjectRecord,
    canonical_json_mapping,
    normalize_object_record,
)

_FORECAST_OBJECT_TYPE: Final = "Forecast"
_PATTERN_OBJECT_TYPE: Final = "Pattern"


@dataclass(frozen=True, slots=True)
class ProducerAttestation:
    """Authenticated producer claim bound to one canonical projected object."""

    agent: Literal["Heimdall", "Norns"]
    credential_ref: str
    content_digest: str

    def __post_init__(self) -> None:
        if not self.credential_ref.strip():
            raise ValueError("producer credential_ref MUST be non-empty")
        if (
            len(self.content_digest) != 71
            or not self.content_digest.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in self.content_digest[7:])
        ):
            raise ValueError("producer content_digest MUST be a SHA-256 digest")


class ProducerAuthenticator(Protocol):
    """Verify a producer credential over one exact canonical object digest."""

    def verify(self, *, agent: str, credential_ref: str, content_digest: str) -> bool: ...


class DetectionOntologyProjector:
    """Write detector-owned ontology objects idempotently through the instance store."""

    def __init__(
        self,
        store: OntologyInstanceStore,
        *,
        authenticator: ProducerAuthenticator,
    ) -> None:
        self._store = store
        self._authenticator = authenticator

    async def project_forecast(
        self,
        episode: ForecastEpisode,
        *,
        confidence: float,
        issued_at: datetime,
        attestation: ProducerAttestation,
    ) -> OntologyObjectRecord:
        """Persist one positive Forecast record without changing its authority."""

        record = forecast_object_record(episode, confidence=confidence, issued_at=issued_at)
        self._verify_producer(record, attestation, expected_agent="Heimdall")
        return await self._persist(record)

    async def project_pattern(
        self,
        candidate: OperatingPatternCandidate,
        *,
        compiled_at: datetime,
        cases: Sequence[PatternCase],
        attestation: ProducerAttestation,
    ) -> OntologyObjectRecord:
        """Persist one inert Pattern record without changing its authority."""

        verified = OperatingPatternCompiler().compile(cases)
        if verified != candidate:
            raise ValueError("Pattern candidate does not match its balanced sealed cohort")
        record = pattern_object_record(candidate, compiled_at=compiled_at)
        self._verify_producer(record, attestation, expected_agent="Norns")
        return await self._persist(record)

    def _verify_producer(
        self,
        record: OntologyObjectRecord,
        attestation: ProducerAttestation,
        *,
        expected_agent: Literal["Heimdall", "Norns"],
    ) -> None:
        if attestation.agent != expected_agent:
            raise ValueError(f"{record.object_type} producer MUST be {expected_agent}")
        digest = _record_digest(record)
        if attestation.content_digest != digest or not self._authenticator.verify(
            agent=expected_agent,
            credential_ref=attestation.credential_ref,
            content_digest=digest,
        ):
            raise ValueError(f"{record.object_type} producer attestation is not verified")

    async def _persist(self, record: OntologyObjectRecord) -> OntologyObjectRecord:
        record = normalize_object_record(record)
        canonical_properties = dict(record.properties)
        created = await self._store.create_object_if_absent(record)
        if created is not None:
            return created
        existing = await self._store.get_object(record.id)
        if existing is None:
            raise RuntimeError("atomic detection ontology create lost its existing identity")
        existing = normalize_object_record(existing)
        if existing.object_type != record.object_type or dict(existing.properties) != (
            canonical_properties
        ):
            raise ValueError("detection ontology object identity conflicts with stored content")
        return existing


def forecast_object_record(
    episode: ForecastEpisode,
    *,
    confidence: float,
    issued_at: datetime,
) -> OntologyObjectRecord:
    """Build one immutable Forecast object from a positive forecast episode.

    Only a detector episode that actually predicts a breach can create this
    object. The returned record is semantic evidence and carries no action
    authority.
    """

    if episode.evaluation_kind is not ForecastEvaluationKind.PREDICTED_BREACH:
        raise ValueError("only predicted-breach episodes produce Forecast objects")
    if episode.state is not ForecastEpisodeState.OPEN:
        raise ValueError("only open Forecast episodes are active")
    if issued_at.tzinfo is None or issued_at.utcoffset() is None:
        raise ValueError("Forecast issued_at MUST be timezone-aware")
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError("Forecast confidence MUST be finite and in [0, 1]")
    if (
        episode.predicted_value is None
        or episode.interval_lower is None
        or episode.interval_upper is None
    ):
        raise ValueError("predicted-breach episode MUST carry interval evidence")
    if not episode.feature_cutoff <= issued_at < episode.closure_due_at:
        raise ValueError("Forecast issued_at MUST be inside the open episode closure window")
    horizon_seconds = (episode.horizon_ended_at - episode.horizon_started_at).total_seconds()
    if horizon_seconds < 1 or not horizon_seconds.is_integer():
        raise ValueError("Forecast horizon MUST be a positive whole number of seconds")
    record_id = str(episode.episode_id)
    return OntologyObjectRecord(
        id=record_id,
        object_type=_FORECAST_OBJECT_TYPE,
        properties={
            "id": record_id,
            "detector_id": episode.detector_id,
            "detector_version": episode.detector_version,
            "target_ref": episode.target_ref,
            "breach_predicate": (f"{episode.metric}:{episode.direction}:{episode.threshold:g}"),
            "feature_cutoff": episode.feature_cutoff,
            "horizon_seconds": int(horizon_seconds),
            "projected_value": episode.predicted_value,
            "interval_lower": episode.interval_lower,
            "interval_upper": episode.interval_upper,
            "confidence": confidence,
            "issued_at": issued_at,
        },
    )


def pattern_object_record(
    candidate: OperatingPatternCandidate,
    *,
    compiled_at: datetime,
) -> OntologyObjectRecord:
    """Build one inert Pattern object from a balanced sealed-case candidate."""

    if compiled_at.tzinfo is None or compiled_at.utcoffset() is None:
        raise ValueError("Pattern compiled_at MUST be timezone-aware")
    evidence_digest = _digest(
        {
            "pattern_id": candidate.pattern_id,
            "digest_evidence": list(candidate.digest_evidence),
        }
    )
    record_id = candidate.pattern_id
    return OntologyObjectRecord(
        id=record_id,
        object_type=_PATTERN_OBJECT_TYPE,
        properties={
            "id": record_id,
            "failure_fingerprint": candidate.failure_fingerprint,
            "resource_type": candidate.resource_type,
            "action_type": candidate.action_type,
            "sample_size": candidate.sample_size,
            "reusable_count": candidate.reusable_count,
            "negative_count": candidate.negative_count,
            "evidence_digest": evidence_digest,
            "compiled_at": compiled_at,
        },
    )


def _digest(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _record_digest(record: OntologyObjectRecord) -> str:
    _, encoded = canonical_json_mapping(record.properties, path=f"{record.object_type}.properties")
    material = f"{record.object_type}\x00{record.id}\x00{encoded}".encode()
    return "sha256:" + hashlib.sha256(material).hexdigest()


__all__ = [
    "DetectionOntologyProjector",
    "ProducerAttestation",
    "ProducerAuthenticator",
    "forecast_object_record",
    "pattern_object_record",
]
