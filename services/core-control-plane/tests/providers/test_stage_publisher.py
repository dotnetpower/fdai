"""Tests for :mod:`fdai.shared.providers.stage_publisher` and the two
transport adapters in :mod:`fdai.shared.streaming.stage_publisher`.

The Protocol + Null + Recording types are pure data - assert
construction validity and the "record what you saw" helpers. The two
adapters (:class:`SseSinkStagePublisher`, :class:`EventBusStagePublisher`)
are asserted against the in-memory fakes for :class:`SseSink` and
:class:`EventBus`.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fdai.shared.providers.event_bus import EventEnvelope
from fdai.shared.providers.stage_publisher import (
    NullStagePublisher,
    ObservationSource,
    StageEvent,
    StageName,
    StagePhase,
    _iso,
)
from fdai.shared.providers.testing import (
    InMemoryEventBus,
    InMemorySseSink,
    RecordingStagePublisher,
)
from fdai.shared.streaming.stage_publisher import (
    EventBusStagePublisher,
    SseSinkStagePublisher,
)


class TestStageEvent:
    def test_minimal_event_serializes_join_keys(self) -> None:
        ev = StageEvent(
            event_id="evt-1",
            correlation_id="corr-1",
            stage=StageName.ROUTE,
            phase=StagePhase.DONE,
        )
        d = ev.to_dict()
        assert d["event_id"] == "evt-1"
        assert d["correlation_id"] == "corr-1"
        assert d["stage"] == "route"
        assert d["phase"] == "done"
        assert d["ts"].endswith("Z")
        # No detail / error fields when unused.
        assert "detail" not in d
        assert "error" not in d

    def test_detail_preserved_in_to_dict(self) -> None:
        ev = StageEvent(
            event_id="evt-1",
            correlation_id="corr-1",
            stage=StageName.GATE,
            phase=StagePhase.DONE,
            detail={"gate_decision": "auto", "tier": "t0"},
        )
        d = ev.to_dict()
        assert d["detail"] == {"gate_decision": "auto", "tier": "t0"}
        assert d["source"] == "unknown"

    def test_failed_phase_requires_error(self) -> None:
        with pytest.raises(ValueError, match="error MUST be set"):
            StageEvent(
                event_id="evt-1",
                correlation_id="corr-1",
                stage=StageName.EXECUTE,
                phase=StagePhase.FAILED,
                # missing error
            )

    def test_explicit_observation_source_is_serialized(self) -> None:
        event = StageEvent(
            event_id="evt-1",
            correlation_id="corr-1",
            stage=StageName.AUDIT,
            phase=StagePhase.DONE,
            source=ObservationSource.REPLAY,
        )
        assert event.to_dict()["source"] == "replay"

    def test_non_failed_phase_rejects_error(self) -> None:
        with pytest.raises(ValueError, match="error MUST be set"):
            StageEvent(
                event_id="evt-1",
                correlation_id="corr-1",
                stage=StageName.EXECUTE,
                phase=StagePhase.DONE,
                error="not allowed here",
            )

    def test_ts_must_be_timezone_aware(self) -> None:
        with pytest.raises(ValueError, match="tzinfo"):
            StageEvent(
                event_id="evt-1",
                correlation_id="corr-1",
                stage=StageName.ROUTE,
                phase=StagePhase.DONE,
                ts=datetime(2026, 7, 8, 12, 0, 0),  # naive
            )


class TestNullStagePublisher:
    async def test_emit_is_a_noop(self) -> None:
        pub = NullStagePublisher()
        # Must accept any event without raising and without doing anything
        # observable.
        await pub.emit(
            StageEvent(
                event_id="evt-1",
                correlation_id="corr-1",
                stage=StageName.INGEST,
                phase=StagePhase.BEGIN,
            )
        )


class TestRecordingStagePublisher:
    async def test_records_in_call_order(self) -> None:
        pub = RecordingStagePublisher()
        for stage in (StageName.INGEST, StageName.ROUTE, StageName.GATE):
            await pub.emit(
                StageEvent(
                    event_id="evt-1",
                    correlation_id="corr-1",
                    stage=stage,
                    phase=StagePhase.DONE,
                )
            )
        stages = [e.stage for e in pub.events]
        assert stages == [StageName.INGEST, StageName.ROUTE, StageName.GATE]

    async def test_by_stage_and_by_phase(self) -> None:
        pub = RecordingStagePublisher()
        for phase in (StagePhase.BEGIN, StagePhase.DONE):
            await pub.emit(
                StageEvent(
                    event_id="evt-1",
                    correlation_id="corr-1",
                    stage=StageName.ROUTE,
                    phase=phase,
                )
            )
        assert len(pub.by_stage(StageName.ROUTE)) == 2
        assert len(pub.by_stage(StageName.GATE)) == 0
        assert len(pub.by_phase(StagePhase.BEGIN)) == 1
        assert len(pub.by_phase(StagePhase.DONE)) == 1

    async def test_last_and_clear(self) -> None:
        pub = RecordingStagePublisher()
        assert pub.last() is None
        await pub.emit(
            StageEvent(
                event_id="evt-1",
                correlation_id="corr-1",
                stage=StageName.INGEST,
                phase=StagePhase.DONE,
            )
        )
        assert pub.last() is not None and pub.last().stage is StageName.INGEST
        pub.clear()
        assert pub.last() is None


class TestSseSinkStagePublisher:
    async def test_emit_publishes_json_on_channel(self) -> None:
        sink = InMemorySseSink()
        pub = SseSinkStagePublisher(sink, channel="ch-stages")
        it = sink.subscribe("ch-stages")
        # Kick the generator on a task so the subscriber queue is registered
        # BEFORE we publish; InMemorySseSink registers lazily on first
        # ``__anext__``.
        next_task = asyncio.create_task(it.__anext__())
        # Yield to the loop until the subscriber is registered.
        for _ in range(50):
            if sink.subscriber_count("ch-stages") == 1:
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("subscriber failed to register in time")

        ev = StageEvent(
            event_id="evt-1",
            correlation_id="corr-1",
            stage=StageName.EXECUTE,
            phase=StagePhase.DONE,
            detail={"tier": "t0", "gate_decision": "auto"},
        )
        await pub.emit(ev)
        try:
            frame = await asyncio.wait_for(next_task, timeout=1.0)
        finally:
            aclose = getattr(it, "aclose", None)
            if aclose is not None:
                await aclose()
        assert frame.id == "evt-1"
        assert frame.event == "stage"
        parsed = json.loads(frame.data)
        assert parsed["stage"] == "execute"
        assert parsed["phase"] == "done"
        assert parsed["detail"] == {"tier": "t0", "gate_decision": "auto"}

    async def test_empty_channel_rejected(self) -> None:
        sink = InMemorySseSink()
        with pytest.raises(ValueError, match="channel"):
            SseSinkStagePublisher(sink, channel="")

    async def test_sink_error_does_not_abort(self) -> None:
        # A publisher whose sink raises MUST swallow so the pipeline
        # keeps running - live view is best-effort.
        class RaisingSink:
            async def publish(self, channel, event):  # type: ignore[no-untyped-def]
                raise RuntimeError("boom")

            def subscribe(self, channel):  # type: ignore[no-untyped-def]
                raise AssertionError("not called")

        pub = SseSinkStagePublisher(RaisingSink(), channel="ch-x")
        # Should NOT raise.
        await pub.emit(
            StageEvent(
                event_id="evt-1",
                correlation_id="corr-1",
                stage=StageName.ROUTE,
                phase=StagePhase.DONE,
            )
        )


class TestEventBusStagePublisher:
    async def test_emit_publishes_to_topic(self) -> None:
        bus = InMemoryEventBus()
        pub = EventBusStagePublisher(bus, topic="aw.pipeline.stages")
        ev = StageEvent(
            event_id="evt-1",
            correlation_id="corr-1",
            stage=StageName.ROUTE,
            phase=StagePhase.DONE,
            detail={"tier": "t0"},
        )
        await pub.emit(ev)
        # Consumer group id is arbitrary for the in-memory fake.
        received: list[EventEnvelope] = []
        agen = bus.subscribe("aw.pipeline.stages", "test-consumer")
        try:
            envelope = await asyncio.wait_for(agen.__anext__(), timeout=1.0)
            received.append(envelope)
        finally:
            aclose = getattr(agen, "aclose", None)
            if aclose is not None:
                await aclose()
        assert received[0].topic == "aw.pipeline.stages"
        assert received[0].key == "evt-1"  # default key selector = event_id
        assert received[0].payload["stage"] == "route"

    async def test_custom_key_selector(self) -> None:
        bus = InMemoryEventBus()
        pub = EventBusStagePublisher(
            bus,
            topic="ch",
            key_selector=lambda e: e.correlation_id,
        )
        await pub.emit(
            StageEvent(
                event_id="evt-1",
                correlation_id="corr-99",
                stage=StageName.GATE,
                phase=StagePhase.DONE,
            )
        )
        agen = bus.subscribe("ch", "test")
        try:
            envelope = await asyncio.wait_for(agen.__anext__(), timeout=1.0)
        finally:
            aclose = getattr(agen, "aclose", None)
            if aclose is not None:
                await aclose()
        assert envelope.key == "corr-99"

    async def test_empty_topic_rejected(self) -> None:
        bus = InMemoryEventBus()
        with pytest.raises(ValueError, match="topic"):
            EventBusStagePublisher(bus, topic="")

    async def test_bus_error_does_not_abort(self) -> None:
        class RaisingBus:
            async def publish(self, **kwargs):  # type: ignore[no-untyped-def]
                raise RuntimeError("broker down")

            def subscribe(self, topic, group_id):  # type: ignore[no-untyped-def]
                raise AssertionError("not called")

            async def dead_letter(self, **kwargs):  # type: ignore[no-untyped-def]
                raise AssertionError("not called")

        pub = EventBusStagePublisher(RaisingBus(), topic="t")
        # Must not raise.
        await pub.emit(
            StageEvent(
                event_id="evt-1",
                correlation_id="corr-1",
                stage=StageName.GATE,
                phase=StagePhase.DONE,
            )
        )


def test_iso_converts_non_utc_aware_to_true_utc() -> None:
    # StageEvent only validates that ts is aware (any offset). 14:00 at
    # +09:00 is 05:00Z; _iso MUST report the true UTC instant, not stamp a
    # literal Z onto the local wall-clock components.
    kst = timezone(timedelta(hours=9))
    ts = datetime(2026, 7, 9, 14, 0, 0, tzinfo=kst)
    assert _iso(ts) == "2026-07-09T05:00:00.000Z"


def test_iso_utc_is_unchanged() -> None:
    ts = datetime(2026, 7, 9, 5, 0, 0, tzinfo=UTC)
    assert _iso(ts) == "2026-07-09T05:00:00.000Z"
