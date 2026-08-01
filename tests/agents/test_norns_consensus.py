"""Norns internal Urd, Verdandi, and Skuld consensus boundary."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.norns_consensus import NornsConsensus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.norns import Norns, NornsCapacityError
from fdai.core.learning import RuleCandidateHint


@pytest.mark.parametrize(
    ("candidate_update", "holding_perspective"),
    [
        ({"evidence": {}}, "Urd"),
        ({"suggested_change": "lower_confidence_threshold"}, "Skuld"),
    ],
)
def test_norns_consensus_holds_ungrounded_or_autonomy_raising_candidates(
    candidate_update: dict[str, object],
    holding_perspective: str,
) -> None:
    candidate = {
        "proposed_by": "Norns",
        "proposal_kind": "threshold_adjustment",
        "source_signal": "audit_outcome",
        "evidence": {"sample_size": 20, "rollback_rate": 0.4},
        "suggested_change": "raise_confidence_threshold",
    }
    candidate.update(candidate_update)

    decision = NornsConsensus().evaluate(candidate)

    assert decision.unanimous is False
    assert decision.holding_perspectives() == (holding_perspective,)


async def test_norns_publishes_one_unanimous_consensus_result() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    norns = Norns(promotion_threshold=1)
    norns.bind_bus(bus)

    await norns.on_typed_message("object.issue", {"fingerprint": "fp-consensus"})

    messages = bus.messages_on("object.rule-candidate")
    assert len(messages) == 1
    assert messages[0].payload["correlation_id"].startswith("norns:")
    assert messages[0].payload["idempotency_key"].startswith("rule-candidate:")
    assert messages[0].payload["norns_consensus"] == {
        "decision": "propose",
        "unanimous": True,
        "perspective_count": 3,
        "reason_codes": [
            "historical_evidence_grounded",
            "current_contract_valid",
            "future_safety_preserved",
        ],
    }


async def test_norns_holds_candidate_when_one_perspective_disagrees() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    norns = Norns()
    norns.bind_bus(bus)
    hint = RuleCandidateHint(
        proposal_kind="promotion",
        target_ref="rule-1",
        pattern="Repeated corrections suggest direct promotion.",
        evidence_refs=("audit-1",),
        confidence=0.9,
    )

    await norns.submit_rule_hint(
        hint,
        proposed_by="Norns",
        at=datetime(2026, 7, 21, tzinfo=UTC),
    )

    assert bus.messages_on("object.rule-candidate") == []
    assert norns.pending_candidates == []
    assert norns.consensus_holds() == (
        {
            "decision": "hold",
            "source_signal": "post_turn_review",
            "proposal_kind": "promotion",
            "holding_perspectives": ("Verdandi",),
            "reason_codes": (
                "historical_evidence_grounded",
                "current_contract_invalid",
                "future_safety_preserved",
            ),
        },
    )
    assert norns.behavior_snapshot()["rule_candidate_consensus_held"] == 1


async def test_norns_capacity_backpressure_does_not_mutate_new_fingerprint() -> None:
    norns = Norns(promotion_threshold=1, max_pending_candidates=1)

    await norns.on_typed_message("object.issue", {"fingerprint": "fp-one"})
    with pytest.raises(NornsCapacityError, match="capacity exhausted"):
        await norns.on_typed_message("object.issue", {"fingerprint": "fp-two"})

    assert norns.occurrences("fp-one") == 1
    assert norns.occurrences("fp-two") == 0
    assert len(norns.pending_candidates) == 1


async def test_norns_serializes_async_case_analysis() -> None:
    class _Analyzer:
        def __init__(self) -> None:
            self.active = 0
            self.maximum = 0

        async def analyze(self, payload):  # type: ignore[no-untyped-def]
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            await asyncio.sleep(0)
            self.active -= 1
            return None

    analyzer = _Analyzer()
    norns = Norns(forecast_error_threshold=1, case_history_analyzer=analyzer)  # type: ignore[arg-type]

    def payload(identifier: str) -> dict[str, object]:
        return {
            "producer_principal": "Muninn",
            "kind": "forecast_case_history",
            "correlation_id": f"corr-{identifier}",
            "idempotency_key": f"case-index-{identifier}",
            "case_id": f"case-{identifier}",
            "revision": 1,
            "manifest_digest": "a" * 64,
            "outcome_label": "false_positive",
            "detector_id": f"detector-{identifier}",
            "metric": "capacity_percent",
            "case_ref": f"case-history:case-{identifier}:1:{'a' * 64}",
        }

    await asyncio.gather(
        norns.on_typed_message("object.context-index", payload("one")),
        norns.on_typed_message("object.context-index", payload("two")),
    )

    assert analyzer.maximum == 1
