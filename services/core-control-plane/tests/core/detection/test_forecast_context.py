from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from fdai.core.detection.forecast_context import ContextualForecastObservationProvider
from fdai.core.detection.forecast_episode import ForecastEpisode
from fdai.core.detection.forecast_outcome import ForecastObservation
from fdai.shared.contracts.models import TelemetryCompleteness
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.forecast_context import (
    ForecastContextEvidence,
    ForecastContextRequest,
    ForecastContextUnavailableError,
)

from .test_forecast_episode import T0, _episode


class _Metrics:
    async def observe(self, episode: ForecastEpisode) -> ForecastObservation:
        del episode
        return ForecastObservation(
            observed_value=70.0,
            actual_breach_at=None,
            telemetry_completeness=TelemetryCompleteness.COMPLETE,
            evidence_refs=("metric-window:example",),
        )


class _Context:
    def __init__(self, evidence: ForecastContextEvidence) -> None:
        self.evidence = evidence

    async def read(self, request: ForecastContextRequest) -> ForecastContextEvidence:
        assert request.as_of == _episode().closure_due_at
        return self.evidence


class _Admission:
    async def admit(self, **values: str) -> DecisionEvidenceAdmission:
        return DecisionEvidenceAdmission(
            receipt_digest="sha256:" + "a" * 64,
            verification_bundle_digest="sha256:" + "b" * 64,
            verified_at=_episode().closure_due_at,
            valid_until=_evidence().valid_until,
            **values,
        )


def _evidence() -> ForecastContextEvidence:
    episode = _episode()
    return ForecastContextEvidence(
        access_scope_digest=episode.access_scope_digest,
        target_digest=episode.target_digest,
        horizon_started_at=episode.horizon_started_at,
        horizon_ended_at=episode.horizon_ended_at,
        recorded_at=episode.closure_due_at,
        valid_until=episode.closure_due_at + timedelta(minutes=5),
        complete=True,
        source_revision="c" * 64,
        evidence_refs=("context-history:example",),
    )


async def test_missing_context_binding_preserves_metrics_but_excludes_scoring() -> None:
    observation = await ContextualForecastObservationProvider(
        observations=_Metrics(), context=None
    ).observe(_episode())
    assert observation.telemetry_completeness is TelemetryCompleteness.COMPLETE
    assert observation.observed_value == 70.0
    assert observation.scoring_exclusions == ("intervention_history_unavailable",)


async def test_exact_complete_context_proves_no_intervention_for_scoring() -> None:
    observation = await ContextualForecastObservationProvider(
        admission_provider=_Admission(),
        observations=_Metrics(),
        context=_Context(_evidence()),
        clock=lambda: _episode().closure_due_at,
    ).observe(_episode())
    assert observation.scoring_exclusions == ()
    assert "context-history:example" in observation.evidence_refs
    assert any(reference.startswith("forecast-context:") for reference in observation.evidence_refs)


@pytest.mark.parametrize(
    "changes",
    [
        {"access_scope_digest": "d" * 64},
        {"target_digest": "e" * 64},
        {"horizon_started_at": T0 - timedelta(seconds=1)},
        {"recorded_at": _episode().closure_due_at + timedelta(seconds=1)},
        {"recorded_at": _episode().horizon_ended_at, "valid_until": _episode().closure_due_at},
    ],
)
async def test_mismatched_or_expired_context_is_not_applied(changes: dict[str, object]) -> None:
    evidence = replace(_evidence(), **changes)
    observation = await ContextualForecastObservationProvider(
        observations=_Metrics(), context=_Context(evidence), clock=lambda: _episode().closure_due_at
    ).observe(_episode())
    assert observation.scoring_exclusions == ("context_mismatch",)
    assert "context-history:example" not in observation.evidence_refs


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"complete": False}, "intervention_history_unavailable"),
        ({"resource_deleted": True}, "resource_deleted"),
        ({"excluded_window": True}, "excluded_window"),
    ],
)
async def test_context_exclusions_remain_separate_from_metrics(
    changes: dict[str, object], reason: str
) -> None:
    observation = await ContextualForecastObservationProvider(
        admission_provider=_Admission(),
        observations=_Metrics(),
        context=_Context(replace(_evidence(), **changes)),
        clock=lambda: _episode().closure_due_at,
    ).observe(_episode())
    assert observation.scoring_exclusions == (reason,)
    assert observation.telemetry_completeness is TelemetryCompleteness.COMPLETE


async def test_known_intervention_is_retained_without_claiming_prevention() -> None:
    observation = await ContextualForecastObservationProvider(
        admission_provider=_Admission(),
        observations=_Metrics(),
        context=_Context(replace(_evidence(), intervention_refs=("action-receipt:example",))),
        clock=lambda: _episode().closure_due_at,
    ).observe(_episode())
    assert observation.intervention_refs == ("action-receipt:example",)
    assert observation.scoring_exclusions == ()


@pytest.mark.parametrize("error", [ForecastContextUnavailableError, OSError, RuntimeError])
async def test_provider_unavailability_excludes_scoring(error, caplog) -> None:
    class _Unavailable:
        async def read(self, request: ForecastContextRequest) -> ForecastContextEvidence:
            del request
            raise error("synthetic history unavailable")

    observation = await ContextualForecastObservationProvider(
        observations=_Metrics(), context=_Unavailable(), clock=lambda: _episode().closure_due_at
    ).observe(_episode())
    assert observation.scoring_exclusions == ("intervention_history_unavailable",)
    assert observation.observed_value == 70.0
    assert observation.telemetry_completeness is TelemetryCompleteness.COMPLETE
    assert "synthetic history unavailable" not in caplog.text


async def test_context_timeout_excludes_scoring() -> None:
    class _Blocked:
        async def read(self, request: ForecastContextRequest) -> ForecastContextEvidence:
            del request
            await asyncio.Event().wait()
            return _evidence()

    observation = await ContextualForecastObservationProvider(
        observations=_Metrics(),
        context=_Blocked(),
        clock=lambda: _episode().closure_due_at,
        timeout_seconds=0.01,
    ).observe(_episode())
    assert observation.scoring_exclusions == ("intervention_history_unavailable",)
    assert observation.observed_value == 70.0
    assert observation.telemetry_completeness is TelemetryCompleteness.COMPLETE


async def test_total_join_deadline_also_bounds_metric_provider() -> None:
    closed = asyncio.Event()

    class _BlockedMetrics:
        async def observe(self, episode: ForecastEpisode) -> ForecastObservation:
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()
            return await _Metrics().observe(episode)

    observation = await ContextualForecastObservationProvider(
        observations=_BlockedMetrics(),
        context=None,
        timeout_seconds=0.01,
    ).observe(_episode())
    assert closed.is_set()
    assert observation.observed_value is None
    assert observation.telemetry_completeness is TelemetryCompleteness.UNAVAILABLE
    assert observation.scoring_exclusions == ("intervention_history_unavailable",)


async def test_context_expiring_during_read_is_rejected() -> None:
    moments = iter((_episode().closure_due_at, _evidence().valid_until))
    observation = await ContextualForecastObservationProvider(
        observations=_Metrics(), context=_Context(_evidence()), clock=lambda: next(moments)
    ).observe(_episode())
    assert observation.scoring_exclusions == ("context_mismatch",)


async def test_external_context_cancellation_propagates() -> None:
    entered = asyncio.Event()

    class _Cancelled:
        async def read(self, request: ForecastContextRequest) -> ForecastContextEvidence:
            del request
            entered.set()
            await asyncio.Event().wait()
            return _evidence()

    task = asyncio.create_task(
        ContextualForecastObservationProvider(
            observations=_Metrics(), context=_Cancelled(), clock=lambda: _episode().closure_due_at
        ).observe(_episode())
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_self_declared_complete_history_without_admission_cannot_score() -> None:
    observation = await ContextualForecastObservationProvider(
        observations=_Metrics(),
        context=_Context(_evidence()),
        clock=lambda: _episode().closure_due_at,
    ).observe(_episode())
    assert observation.scoring_exclusions == ("intervention_history_unavailable",)
    assert "context-history:example" not in observation.evidence_refs


async def test_wrong_scope_admission_does_not_admit_history() -> None:
    class _WrongScope(_Admission):
        async def admit(self, **values: str) -> DecisionEvidenceAdmission:
            return replace(await super().admit(**values), scope_digest="sha256:" + "f" * 64)

    observation = await ContextualForecastObservationProvider(
        observations=_Metrics(),
        context=_Context(_evidence()),
        admission_provider=_WrongScope(),
        clock=lambda: _episode().closure_due_at,
    ).observe(_episode())
    assert observation.scoring_exclusions == ("intervention_history_unavailable",)


@pytest.mark.parametrize("timeout", [0, True, 61, float("nan")])
def test_context_deadline_rejects_invalid_configuration(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout"):
        ContextualForecastObservationProvider(
            observations=_Metrics(), context=None, timeout_seconds=timeout
        )


@pytest.mark.parametrize("now", [T0, T0.replace(tzinfo=None)])
async def test_context_clock_cannot_precede_episode_closure(now) -> None:
    observation = await ContextualForecastObservationProvider(
        observations=_Metrics(),
        context=_Context(_evidence()),
        clock=lambda: now,
    ).observe(_episode())
    assert observation.scoring_exclusions == ("context_mismatch",)


async def test_combined_reference_limit_holds_without_truncating_evidence() -> None:
    evidence = replace(
        _evidence(), evidence_refs=tuple(f"context-history:{index}" for index in range(64))
    )
    observation = await ContextualForecastObservationProvider(
        observations=_Metrics(),
        context=_Context(evidence),
        admission_provider=_Admission(),
        clock=lambda: _episode().closure_due_at,
    ).observe(_episode())
    assert observation.scoring_exclusions == ("context_mismatch",)
    assert observation.evidence_refs == ("metric-window:example",)


@pytest.mark.parametrize("error", [ValueError, OSError, RuntimeError, asyncio.CancelledError])
async def test_admission_provider_error_cannot_admit_history(error, caplog) -> None:
    class _Invalid:
        async def admit(self, **_values):
            raise error("synthetic invalid admission")

    provider = ContextualForecastObservationProvider(
        observations=_Metrics(),
        context=_Context(_evidence()),
        admission_provider=_Invalid(),
        clock=lambda: _episode().closure_due_at,
    )
    if error is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError):
            await provider.observe(_episode())
        return
    observation = await provider.observe(_episode())
    assert observation.scoring_exclusions == ("intervention_history_unavailable",)
    assert observation.observed_value == 70.0
    assert observation.telemetry_completeness is TelemetryCompleteness.COMPLETE
    assert "synthetic invalid admission" not in caplog.text
