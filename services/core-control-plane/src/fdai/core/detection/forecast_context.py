"""Join exact-target context without changing observed telemetry or granting authority."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from fdai.core.detection.forecast_closure import ForecastObservationProvider
from fdai.core.detection.forecast_episode import ForecastEpisode
from fdai.core.detection.forecast_outcome import ForecastObservation
from fdai.shared.contracts.models import ForecastScoringExclusion, TelemetryCompleteness
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceAdmissionProvider,
    assess_decision_evidence_admission,
)
from fdai.shared.providers.forecast_context import (
    ForecastContextEvidence,
    ForecastContextProvider,
    ForecastContextRequest,
)

_LOGGER = logging.getLogger(__name__)


class ContextualForecastObservationProvider:
    """Fail closed on unknown history while retaining independently measured telemetry."""

    def __init__(
        self,
        *,
        observations: ForecastObservationProvider,
        context: ForecastContextProvider | None,
        admission_provider: DecisionEvidenceAdmissionProvider | None = None,
        clock: Callable[[], datetime] | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 60
        ):
            raise ValueError("forecast context timeout MUST be finite and in (0, 60]")
        self._observations = observations
        self._context = context
        self._admission_provider = admission_provider
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._timeout_seconds = timeout_seconds

    async def observe(self, episode: ForecastEpisode) -> ForecastObservation:
        """Bound the entire join and preserve measured telemetry when context work times out."""
        observation = ForecastObservation(
            observed_value=None,
            actual_breach_at=None,
            telemetry_completeness=TelemetryCompleteness.UNAVAILABLE,
            evidence_refs=(),
        )
        try:
            async with asyncio.timeout(self._timeout_seconds):
                observation = await self._observations.observe(episode)
                return await self._join_context(episode, observation)
        except TimeoutError:
            return _exclude(observation, "intervention_history_unavailable")

    async def _join_context(
        self, episode: ForecastEpisode, observation: ForecastObservation
    ) -> ForecastObservation:
        if self._context is None:
            return _exclude(observation, "intervention_history_unavailable")
        now = self._clock()
        if now.utcoffset() is None or now < episode.closure_due_at:
            return _exclude(observation, "context_mismatch")
        request = ForecastContextRequest(
            access_scope_digest=episode.access_scope_digest,
            target_digest=episode.target_digest,
            horizon_started_at=episode.horizon_started_at,
            horizon_ended_at=episode.horizon_ended_at,
            as_of=now,
        )
        try:
            async with asyncio.timeout(self._timeout_seconds):
                evidence = await self._context.read(request)
        except Exception as exc:
            _LOGGER.warning(
                "forecast_history_unavailable", extra={"error_type": type(exc).__name__}
            )
            return _exclude(observation, "intervention_history_unavailable")
        completed_at = self._clock()
        if completed_at.utcoffset() is None or completed_at < now:
            return _exclude(observation, "context_mismatch")
        if not isinstance(evidence, ForecastContextEvidence) or (
            evidence.access_scope_digest != request.access_scope_digest
            or evidence.target_digest != request.target_digest
            or evidence.horizon_started_at != request.horizon_started_at
            or evidence.horizon_ended_at != request.horizon_ended_at
            or not evidence.recorded_at <= request.as_of <= completed_at < evidence.valid_until
        ):
            return _exclude(observation, "context_mismatch")
        admission = None
        if self._admission_provider is not None:
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    admission = await self._admission_provider.admit(
                        evidence_digest="sha256:" + _context_ref(evidence).split(":", 1)[1],
                        scope_digest="sha256:" + evidence.access_scope_digest,
                        purpose_id="forecast-context",
                        source_revision=evidence.source_revision,
                    )
            except Exception as exc:
                _LOGGER.warning(
                    "forecast_admission_unavailable", extra={"error_type": type(exc).__name__}
                )
                admission = None
        verified_at = self._clock()
        if (
            verified_at.utcoffset() is None
            or not completed_at <= verified_at < evidence.valid_until
        ):
            return _exclude(observation, "context_mismatch")
        if not isinstance(admission, DecisionEvidenceAdmission):
            return _exclude(observation, "intervention_history_unavailable")
        if (
            assess_decision_evidence_admission(
                admission,
                expected_evidence_digest="sha256:" + _context_ref(evidence).split(":", 1)[1],
                expected_scope_digest="sha256:" + evidence.access_scope_digest,
                expected_purpose_id="forecast-context",
                expected_source_revision=evidence.source_revision,
                evaluated_at=verified_at,
            )
            or not evidence.recorded_at
            <= admission.verified_at
            <= verified_at
            < admission.valid_until
        ):
            return _exclude(observation, "intervention_history_unavailable")
        references = tuple(
            sorted(
                set(
                    (
                        *observation.evidence_refs,
                        *evidence.evidence_refs,
                        _context_ref(evidence),
                        admission.receipt_digest,
                        admission.verification_bundle_digest,
                    )
                )
            )
        )
        interventions = tuple(
            sorted(set((*observation.intervention_refs, *evidence.intervention_refs)))
        )
        if len(references) > 64 or len(interventions) > 64:
            return _exclude(observation, "context_mismatch")
        result = replace(observation, evidence_refs=references, intervention_refs=interventions)
        if not evidence.complete:
            result = _exclude(result, "intervention_history_unavailable")
        if evidence.resource_deleted:
            result = _exclude(result, "resource_deleted")
        if evidence.excluded_window:
            result = _exclude(result, "excluded_window")
        if interventions and result.actual_breach_at is not None:
            result = _exclude(result, "intervention_affected")
        return result


def _exclude(
    observation: ForecastObservation, reason: ForecastScoringExclusion | str
) -> ForecastObservation:
    return replace(
        observation,
        scoring_exclusions=tuple(sorted({*observation.scoring_exclusions, reason})),
    )


def _context_ref(evidence: ForecastContextEvidence) -> str:
    return f"forecast-context:{evidence.digest}"
