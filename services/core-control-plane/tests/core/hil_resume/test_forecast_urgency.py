"""Immutable forecast lineage, expiration, and conservative timing fallback."""

from __future__ import annotations

import asyncio
import copy
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fdai.core.detection.forecast_episode import ForecastEpisodeState, ForecastEvaluationKind
from fdai.core.detection.forecast_evaluation import _forecast_payload
from fdai.core.hil_resume.forecast_urgency import (
    ForecastUrgencySource,
    bind_forecast_timing_context,
    verify_forecast_urgency,
)

from tests.core.detection.test_forecast_episode import T0, _episode


def source():
    episode = _episode()
    episode = replace(episode, correlation_id=f"forecast:{episode.episode_id}")
    payload = _forecast_payload(episode)
    payload["approval_timing"] = {
        "schema_version": "1.0.0",
        "confidence_level": "0.95",
        "predicted_breach_at": (T0 + timedelta(seconds=200)).isoformat(),
    }
    return ForecastUrgencySource(episode, payload)


def verify(value, *, at=T0, **kwargs):
    return verify_forecast_urgency(
        value,
        episode_id=value.episode.episode_id,
        target_ref=value.episode.target_ref,
        at=at,
        **kwargs,
    )


def test_exact_forecast_retains_band_confidence_and_elapsed_eta():
    proof = verify(source(), at=T0 + timedelta(seconds=20))
    assert proof.confidence == 0.95
    assert proof.remaining_seconds(T0 + timedelta(seconds=20)) == 180
    assert proof.remaining_seconds(T0 + timedelta(seconds=40)) == 160
    assert proof.remaining_seconds(T0 + timedelta(seconds=200)) is None
    assert len(proof.source_digest) == 64


@pytest.mark.parametrize(
    "field,value",
    [
        ("prediction_id", str(UUID(int=2))),
        ("resource_id", "resource:other"),
        ("detector_version", "other"),
        ("access_scope_digest", "b" * 64),
        ("interval_lower", 95),
        ("evidence_refs", ["different"]),
        ("threshold", True),
        ("mode", "enforce"),
        ("feature_cutoff", "2026-01-01T00:00:00+00:00"),
    ],
)
def test_payload_cannot_substitute_episode_lineage(field, value):
    original = source()
    changed = {**original.payload, field: value}
    assert verify(replace(original, payload=changed)) is None


@pytest.mark.parametrize("delta", [-1, 200, 301, 3601])
def test_future_stale_or_passed_forecast_cannot_compress(delta):
    assert verify(source(), at=T0 + timedelta(seconds=delta)) is None


def test_closed_or_non_breach_source_is_not_urgency():
    original = source()
    assert (
        verify(
            replace(original, episode=replace(original.episode, state=ForecastEpisodeState.CLOSED))
        )
        is None
    )
    episode = replace(
        original.episode,
        evaluation_kind=ForecastEvaluationKind.PREDICTED_NO_BREACH,
        predicted_value=None,
        interval_lower=None,
        interval_upper=None,
    )
    assert verify(replace(original, episode=episode)) is None


@pytest.mark.parametrize("direction,lower,upper", [("rising", 89, 100), ("falling", 80, 91)])
def test_point_breach_never_substitutes_for_a_breached_prediction_band(direction, lower, upper):
    original = source()
    episode = replace(
        original.episode, direction=direction, interval_lower=lower, interval_upper=upper
    )
    payload = {**_forecast_payload(episode), "approval_timing": original.payload["approval_timing"]}
    assert verify(ForecastUrgencySource(episode, payload)) is None


@pytest.mark.parametrize(
    "timing",
    [
        None,
        {},
        {
            "schema_version": "1.0.0",
            "confidence_level": True,
            "predicted_breach_at": T0.isoformat(),
        },
    ],
)
def test_legacy_or_malformed_timing_cannot_invent_confidence(timing):
    original = source()
    assert (
        verify(replace(original, payload={**original.payload, "approval_timing": timing})) is None
    )


async def test_raw_context_is_discarded_and_unavailable_source_is_bounded():
    reader = AsyncMock()
    reader.read.side_effect = OSError("synthetic source unavailable")
    original = source()
    context = await bind_forecast_timing_context(
        reader,
        correlation_id=original.episode.correlation_id,
        target_ref=original.episode.target_ref,
        impact="resource_group",
        context={
            "finding_class": "forecast.breach",
            "forecast_confidence": 1,
            "remaining_lead_time_seconds": 1,
            "verified_forecast_urgency": {},
        },
        at=T0,
    )
    assert context == {
        "finding_class": "forecast.breach",
        "impact": "resource_group",
        "forecast_timing_status": "unavailable",
    }


async def test_exact_reader_result_produces_only_an_inert_timing_value():
    original = source()
    reader = AsyncMock()
    reader.read.return_value = original
    context = await bind_forecast_timing_context(
        reader,
        correlation_id=original.episode.correlation_id,
        target_ref=original.episode.target_ref,
        impact="resource_group",
        context=None,
        at=T0,
    )
    assert context["finding_class"] == "forecast.breach"
    assert context["verified_forecast_urgency"].remaining_seconds(T0) == 200
    reader.read.assert_awaited_once_with(original.episode.episode_id)


def test_source_payload_mutation_changes_proof_instead_of_reusing_a_digest():
    original = source()
    first = verify(original)
    payload = copy.deepcopy(original.payload)
    payload["approval_timing"]["confidence_level"] = "0.90"
    changed = verify(replace(original, payload=payload))
    assert first.source_digest != changed.source_digest


def test_governed_low_confidence_remains_below_the_catalog_compression_floor():
    from tests.core.hil_resume.test_escalation_catalog_binding import _rungs, _timing

    original = source()
    payload = copy.deepcopy(original.payload)
    payload["approval_timing"]["confidence_level"] = "0.80"
    proof = verify(replace(original, payload=payload))
    result = _timing().resolve(
        {
            "finding_class": "forecast.breach",
            "impact": "resource_group",
            "verified_forecast_urgency": proof,
        },
        [rung.subject_ref for rung in _rungs()],
        at=T0,
    )
    assert result["catalog_ttl_seconds"] == [300, 300, 600]
    assert not result["catalog_compressed"]


def test_prediction_point_must_belong_to_its_retained_interval():
    original = source()
    episode = replace(original.episode, predicted_value=120)
    payload = {**_forecast_payload(episode), "approval_timing": original.payload["approval_timing"]}
    assert verify(ForecastUrgencySource(episode, payload)) is None


async def test_cancelled_request_is_not_retried_or_hidden_as_source_unavailable():
    original = source()
    reader = AsyncMock()
    reader.read.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await bind_forecast_timing_context(
            reader,
            correlation_id=original.episode.correlation_id,
            target_ref=original.episode.target_ref,
            impact="resource",
            context=None,
            at=T0,
        )
    reader.read.assert_awaited_once()


async def test_source_read_deadline_holds_without_retry(monkeypatch):
    original = source()
    deadline = asyncio.timeout
    monkeypatch.setattr(asyncio, "timeout", lambda seconds: deadline(0.001))
    calls = 0

    class BlockedReader:
        async def read(self, episode_id):
            nonlocal calls
            calls += 1
            await asyncio.Event().wait()

    context = await bind_forecast_timing_context(
        BlockedReader(),
        correlation_id=original.episode.correlation_id,
        target_ref=original.episode.target_ref,
        impact="resource",
        context=None,
        at=T0,
    )
    assert calls == 1
    assert context["forecast_timing_status"] == "unavailable"


async def test_actual_approval_park_reads_source_and_replay_keeps_original_deadlines(monkeypatch):
    from datetime import datetime
    from importlib import import_module

    from fdai.core.hil_resume import HumanNonResponseSupervisor
    from fdai.shared.contracts.models import BlastRadiusScope

    from tests.core.hil_resume.test_coordinator import _action, _coordinator, _rule
    from tests.core.hil_resume.test_escalation_catalog_binding import _rungs, _timing

    class Clock(datetime):
        value = T0

        @classmethod
        def now(cls, tz=None):
            return cls.value

    monkeypatch.setattr(import_module("fdai.core.hil_resume.coordinator"), "datetime", Clock)
    original = source()
    reader = AsyncMock()
    reader.read.return_value = original
    coordinator, publisher, store, channel = _coordinator()
    coordinator.escalation_supervisor = HumanNonResponseSupervisor(
        state_store=store,
        channel=channel,
        catalog_timing=_timing(),
        forecast_urgency_reader=reader,
        clock=lambda: Clock.value,
    )
    action = _action(target=original.episode.target_ref)
    action = action.model_copy(
        update={
            "blast_radius": action.blast_radius.model_copy(
                update={"scope": BlastRadiusScope.RESOURCE_GROUP}
            ),
        }
    )
    args = dict(
        action=action,
        rule=_rule(),
        submitter_oid="human:requester",
        correlation_id=original.episode.correlation_id,
        approval_id="forecast-approval",
        escalation_rungs=_rungs(),
        escalation_context={"finding_class": "forecast.finding"},
    )
    await coordinator.request_approval(**args)
    parked = await store.read_state("hil_park:forecast-approval")
    assert parked["escalation"]["catalog_ttl_seconds"] == [100, 100, 100]
    assert parked["escalation"]["forecast_timing_status"] == "verified"
    assert parked["action"] == action.model_dump(mode="json")
    deadline = parked["escalation"]["decision_deadline"]
    Clock.value += timedelta(seconds=20)
    await coordinator.request_approval(**args)
    assert (await store.read_state("hil_park:forecast-approval"))["escalation"][
        "decision_deadline"
    ] == deadline
    assert publisher.records == ()


async def test_source_expiring_during_read_keeps_conservative_catalog_windows():
    from fdai.core.hil_resume import HumanNonResponseSupervisor
    from fdai.shared.providers.testing import InMemoryStateStore
    from fdai.shared.providers.testing.hil_channel import InMemoryHilChannel

    from tests.core.hil_resume.test_coordinator import _action
    from tests.core.hil_resume.test_escalation_catalog_binding import _park, _rungs, _timing

    now = T0
    original = source()

    class SlowReader:
        async def read(self, episode_id):
            nonlocal now
            now += timedelta(seconds=201)
            return original

    supervisor = HumanNonResponseSupervisor(
        state_store=InMemoryStateStore(),
        channel=InMemoryHilChannel(),
        catalog_timing=_timing(),
        forecast_urgency_reader=SlowReader(),
        clock=lambda: now,
    )
    parked = {
        **_park(T0),
        "correlation_id": original.episode.correlation_id,
        "action": _action(target=original.episode.target_ref).model_dump(mode="json"),
    }
    parked["action"]["blast_radius"]["scope"] = "resource_group"
    result = await supervisor.attach_with_source(parked, rungs=_rungs(), now=T0)
    assert result["escalation"]["catalog_ttl_seconds"] == [300, 300, 600]
    assert result["escalation"]["forecast_timing_status"] == "unavailable"
