"""Tests for :mod:`fdai.core.audit.what_if_replay`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from fdai.core.audit.what_if_replay import (
    EventReconstructionError,
    ReconstructedEvent,
    reconstruct_event,
    replay_with_what_if,
)


@dataclass(frozen=True, slots=True)
class _StubAuditItem:
    seq: int
    correlation_id: str | None
    entry: Mapping[str, Any]
    action_kind: str = "event.received"
    mode: str = "shadow"
    entry_hash: str = "h"
    recorded_at: str = "2026-07-08T10:00:00+00:00"


@dataclass(slots=True)
class _StubEvaluator:
    verdicts: list[Mapping[str, Any]] = field(default_factory=list)
    seen_calls: list[tuple[str, Mapping[str, Any]]] = field(default_factory=list)

    def evaluate(
        self, resource_type: str, resource_props: Mapping[str, Any]
    ) -> Sequence[Mapping[str, Any]]:
        self.seen_calls.append((resource_type, dict(resource_props)))
        return list(self.verdicts)


def _ingest_item(correlation_id: str) -> _StubAuditItem:
    return _StubAuditItem(
        seq=1,
        correlation_id=correlation_id,
        entry={
            "pipeline_stage": "event_ingest",
            "payload": {
                "resource": {
                    "resource_id": "vm-1",
                    "type": "compute.vm",
                    "props": {"tier": "S1"},
                }
            },
        },
        action_kind="event.received",
    )


def test_reconstruct_event_pulls_from_earliest_entry() -> None:
    items = [
        _StubAuditItem(seq=2, correlation_id="c-1", entry={"decision": "allow"}),
        _ingest_item("c-1"),
    ]
    event = reconstruct_event("c-1", items)
    assert event.correlation_id == "c-1"
    assert event.resource_id == "vm-1"
    assert event.resource_type == "compute.vm"
    assert event.props == {"tier": "S1"}


def test_reconstruct_event_raises_on_empty_items() -> None:
    with pytest.raises(EventReconstructionError):
        reconstruct_event("c-1", [])


def test_reconstruct_event_raises_on_missing_resource_block() -> None:
    items = [_StubAuditItem(seq=1, correlation_id="c-1", entry={"payload": {}})]
    with pytest.raises(EventReconstructionError):
        reconstruct_event("c-1", items)


def test_reconstruct_event_raises_on_missing_resource_type() -> None:
    items = [
        _StubAuditItem(
            seq=1,
            correlation_id="c-1",
            entry={
                "payload": {
                    "resource": {
                        "resource_id": "vm-1",
                        "props": {},
                    }
                }
            },
        )
    ]
    with pytest.raises(EventReconstructionError):
        reconstruct_event("c-1", items)


def test_replay_with_what_if_returns_verdicts_and_original_kinds() -> None:
    items = [
        _ingest_item("c-1"),
        _StubAuditItem(
            seq=2,
            correlation_id="c-1",
            entry={"decision": "denied"},
            action_kind="remediate.tag-add",
        ),
    ]
    evaluator = _StubEvaluator(
        verdicts=[{"rule_id": "fork-x.new-rule", "denied": True, "reason": "missing_owner_tag"}]
    )
    report = replay_with_what_if("c-1", items, evaluator)
    assert isinstance(report.event, ReconstructedEvent)
    assert report.matched_rules == (
        {"rule_id": "fork-x.new-rule", "denied": True, "reason": "missing_owner_tag"},
    )
    assert report.original_action_kinds == ("event.received", "remediate.tag-add")
    # Evaluator MUST see the reconstructed event, not the raw audit item.
    assert evaluator.seen_calls == [("compute.vm", {"tier": "S1"})]


def test_replay_report_is_json_round_trippable() -> None:
    import json

    evaluator = _StubEvaluator()
    items = [_ingest_item("c-1")]
    report = replay_with_what_if("c-1", items, evaluator)
    payload = json.loads(json.dumps(report.as_json()))
    assert payload["event"]["resource_id"] == "vm-1"
    assert payload["matched_rules"] == []


def test_replay_never_mutates_source_items() -> None:
    """Regression: the replay is a pure projection."""
    items = [_ingest_item("c-1")]
    snapshot_before = [dict(item.entry) for item in items]
    replay_with_what_if("c-1", items, _StubEvaluator())
    snapshot_after = [dict(item.entry) for item in items]
    assert snapshot_before == snapshot_after
