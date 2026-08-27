"""Project deterministic detection and learning outputs into ontology objects."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Final

from fdai.core.detection.forecast_episode import (
    ForecastEpisode,
    ForecastEvaluationKind,
)
from fdai.core.operational_learning.patterns import OperatingPatternCandidate
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

_FORECAST_OBJECT_TYPE: Final = "Forecast"
_PATTERN_OBJECT_TYPE: Final = "Pattern"


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


__all__ = ["forecast_object_record", "pattern_object_record"]
