from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fdai_runtime_diagnostics.decisions import (
    decision_snapshot,
    observe_decision,
    reset_decision_traces,
)
from pydantic import ValidationError

from fdai_runtime_diagnostics import (
    DevelopmentDiagnosticsConfig,
    DevelopmentProfilePacket,
    RuntimeProbe,
)

ROOT = Path(__file__).resolve().parents[3]
RECEIPT = "sha256:" + ("d" * 64)
SESSION = "s1"


@pytest.fixture(autouse=True)
def _enabled(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("FDAI_DEVELOPMENT_DIAGNOSTICS", "1")
    reset_decision_traces()
    yield
    reset_decision_traces()


def _config(tmp_path: Path) -> DevelopmentDiagnosticsConfig:
    config = DevelopmentDiagnosticsConfig.from_environment(
        "core-control-plane",
        RECEIPT,
        {
            "FDAI_DEVELOPMENT_DIAGNOSTICS": "1",
            "FDAI_EXECUTION_VENUE": "local",
            "FDAI_DEVELOPMENT_DIAGNOSTICS_SOURCE_REVISION": "a" * 40,
            "FDAI_DEVELOPMENT_DIAGNOSTICS_INPUT_DIGEST": "b" * 64,
            "FDAI_DEVELOPMENT_DIAGNOSTICS_WORKTREE_DIGEST": hashlib.sha256(
                tmp_path.name.encode("utf-8")
            ).hexdigest(),
            "FDAI_DEVELOPMENT_DIAGNOSTICS_SOURCE_ROOT": str(ROOT),
            "FDAI_DEVELOPMENT_DIAGNOSTICS_SOCKET_DIR": str(ROOT / ".fdai" / "r"),
        },
    )
    assert config is not None
    return config


def _steps() -> list[dict[str, object]]:
    return [
        {
            "stage": "preflight",
            "attributes": {
                "family": "resource_collection",
                "targets": ("resource_type_filter",),
                "model": "model-1",
            },
        },
        {
            "stage": "judgment",
            "attributes": {
                "intent": "query.contextual_resources",
                "attempt": 1,
                "ambiguous": False,
            },
        },
    ]


def test_a_typed_trace_is_retained_in_order_with_step_bound_cues() -> None:
    cue = {"code": "judgment_retry", "step": 1}
    assert observe_decision(session=SESSION, turn_sequence=3, steps=_steps(), cues=(cue,))
    assert observe_decision(session=SESSION, turn_sequence=4, steps=_steps())
    snapshot = decision_snapshot()
    assert (snapshot.evicted, snapshot.rejected, snapshot.recent_rejections) == (0, 0, 0)
    assert [trace.turn_sequence for trace in snapshot.traces] == [3, 4]
    assert [trace.sequence for trace in snapshot.traces] == [1, 2]
    assert snapshot.traces[0].cues[0].step == 1


def test_a_cue_must_point_at_an_existing_step() -> None:
    cue = {"code": "judgment_retry", "step": 2}
    assert not observe_decision(session=SESSION, turn_sequence=3, steps=_steps(), cues=(cue,))
    assert decision_snapshot().rejected == 1


@pytest.mark.parametrize(
    "value",
    [
        "rg-fdai-dev-krc 목록",
        "list the VMs",
        '"quoted"',
        "x" * 97,
    ],
)
def test_text_never_passes_the_token_grammar(value: str) -> None:
    steps = [{"stage": "judgment", "attributes": {"intent": value}}]
    assert not observe_decision(session=SESSION, turn_sequence=1, steps=steps)
    snapshot = decision_snapshot()
    assert snapshot.traces == ()
    assert snapshot.rejected == 1


def test_an_oversized_or_malformed_trace_is_dropped_without_raising() -> None:
    wide = {f"key_{index}": tuple(f"t{item}" for item in range(32)) for index in range(32)}
    oversized = [{"stage": f"stage{index}", "attributes": wide} for index in range(8)]
    assert not observe_decision(session=SESSION, turn_sequence=1, steps=oversized)
    assert not observe_decision(session="0123456789ab", turn_sequence=1, steps=_steps())
    assert not observe_decision(session=SESSION, turn_sequence=1, steps=[{"stage": 5}])
    snapshot = decision_snapshot()
    assert (snapshot.traces, snapshot.rejected, snapshot.recent_rejections) == ((), 3, 3)
    assert decision_snapshot() == snapshot


def test_a_rejection_leaves_the_recent_window_after_fifty_accepted_attempts() -> None:
    assert not observe_decision(session=SESSION, turn_sequence=1, steps=[{"stage": 5}])
    for index in range(49):
        observe_decision(session=SESSION, turn_sequence=index, steps=_steps())
    assert decision_snapshot().recent_rejections == 1
    observe_decision(session=SESSION, turn_sequence=50, steps=_steps())
    snapshot = decision_snapshot()
    assert (snapshot.rejected, snapshot.recent_rejections) == (1, 0)


def test_recording_is_disabled_outside_the_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FDAI_DEVELOPMENT_DIAGNOSTICS")
    assert not observe_decision(session=SESSION, turn_sequence=1, steps=_steps())
    monkeypatch.setenv("FDAI_DEVELOPMENT_DIAGNOSTICS", "1")
    assert decision_snapshot().traces == ()


def test_the_buffer_keeps_the_newest_fifty_traces_and_counts_evictions() -> None:
    for index in range(55):
        observe_decision(session=SESSION, turn_sequence=index, steps=_steps())
    snapshot = decision_snapshot()
    assert len(snapshot.traces) == 50
    assert snapshot.traces[0].turn_sequence == 5
    assert snapshot.traces[-1].sequence == 55
    assert snapshot.evicted == 5


async def test_snapshot_packet_carries_traces_and_new_rejection_limitation(tmp_path: Path) -> None:
    observe_decision(session=SESSION, turn_sequence=2, steps=_steps())
    observe_decision(
        session=SESSION, turn_sequence=3, steps=[{"stage": "x", "attributes": {"a": "b c"}}]
    )
    probe = RuntimeProbe(_config(tmp_path))
    packet = await probe.capture()
    assert packet.schema_version == "1.1.0"
    assert [trace.turn_sequence for trace in packet.decisions] == [2]
    assert packet.decisions_rejected == 1
    assert packet.limitations == ("decision_traces_rejected",)
    assert packet.complete is False
    assert len(json.dumps(packet.model_dump(mode="json"), ensure_ascii=True)) < 1024 * 1024
    tampered = packet.model_dump(mode="json")
    tampered["decisions"][0]["cues"] = [{"code": "forged", "step": 0}]
    with pytest.raises(ValidationError, match="digest"):
        DevelopmentProfilePacket.model_validate(tampered)
    later = await probe.capture()
    assert later.limitations == ("decision_traces_rejected",)
    assert later.decisions_rejected == 1


async def test_a_packet_without_traces_keeps_the_schema_one_wire_shape(tmp_path: Path) -> None:
    packet = await RuntimeProbe(_config(tmp_path)).capture()
    serialized = packet.model_dump(mode="json")
    assert packet.schema_version == "1.0.0"
    assert not {"decisions", "decisions_evicted", "decisions_rejected"} & set(serialized)
    assert DevelopmentProfilePacket.model_validate(serialized).packet_digest == packet.packet_digest
    observe_decision(session=SESSION, turn_sequence=1, steps=_steps())
    traces = tuple(trace.model_dump(mode="json") for trace in decision_snapshot().traces)
    legacy = {key: value for key, value in serialized.items() if key != "packet_digest"}
    with pytest.raises(ValidationError, match="1.0.0"):
        DevelopmentProfilePacket.build(**{**legacy, "decisions": traces})
