"""Accounting, verification, and fallback tests for the dialogue-state contract."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest
from fdai_service_contracts.dialogue_state import (
    DialogueAnchor,
    DialogueAnchorKind,
    DialogueRole,
    DialogueState,
    DialogueStateProposal,
    DialogueTurn,
    build_dialogue_state,
    compact_dialogue,
    compacted_range_digest,
)
from pydantic import ValidationError


def _turns(count: int) -> list[DialogueTurn]:
    return [
        DialogueTurn(
            turn_id=f"t{index}",
            role=DialogueRole.USER if index % 2 == 0 else DialogueRole.ASSISTANT,
            content=f"고혈압 turn {index} 🚀 scope=prod-{index}",
        )
        for index in range(count)
    ]


def _anchor(turns: Sequence[DialogueTurn], index: int, text: str) -> DialogueAnchor:
    content = turns[index].content
    start = content.index(text)
    return DialogueAnchor(
        kind=DialogueAnchorKind.SCOPE,
        value=text,
        turn_id=turns[index].turn_id,
        start=start,
        end=start + len(text),
    )


@pytest.mark.parametrize("count", range(0, 9))
@pytest.mark.parametrize("keep_recent", [0, 1, 3, 8, 20])
def test_every_turn_is_accounted_exactly_once(count: int, keep_recent: int) -> None:
    turns = _turns(count)

    state = compact_dialogue(turns, keep_recent=keep_recent)

    ids = [turn.turn_id for turn in turns]
    assert [*state.compacted_turn_ids, *state.kept_turn_ids] == ids
    assert state.source_turn_count == count
    assert len(state.kept_turn_ids) == min(count, keep_recent)
    assert state.tier == "T0"
    assert state.anchors == ()
    assert state.execution_authority is False
    assert (state.compacted_digest is None) is (not state.compacted_turn_ids)


def test_digest_is_stable_and_binds_ids_roles_and_content() -> None:
    turns = _turns(4)
    digest = compacted_range_digest(turns)

    assert digest == compacted_range_digest(_turns(4))
    changed = [*turns[:3], turns[3].model_copy(update={"content": "changed"})]
    assert compacted_range_digest(changed) != digest
    renamed = [turns[0].model_copy(update={"turn_id": "other"}), *turns[1:]]
    assert compacted_range_digest(renamed) != digest
    flipped = [turns[0].model_copy(update={"role": DialogueRole.ASSISTANT}), *turns[1:]]
    assert compacted_range_digest(flipped) != digest


def test_verified_proposal_promotes_to_t1() -> None:
    turns = _turns(6)
    proposal = DialogueStateProposal(anchors=(_anchor(turns, 0, "prod-0"),))

    state = compact_dialogue(turns, keep_recent=2, proposal=proposal)

    assert state.tier == "T1"
    assert state.anchors == proposal.anchors
    assert state.fallback_reason is None


@pytest.mark.parametrize("field", ["value", "turn", "span_end", "recent_turn"])
def test_unverified_anchor_rejects_the_whole_proposal(field: str) -> None:
    turns = _turns(6)
    good = _anchor(turns, 0, "prod-0")
    bad = {
        "value": good.model_copy(update={"value": "prod-9"}),
        "turn": good.model_copy(update={"turn_id": "missing"}),
        "span_end": good.model_copy(update={"end": 10_000}),
        "recent_turn": _anchor(turns, 5, "prod-5"),
    }[field]

    state = compact_dialogue(
        turns, keep_recent=2, proposal=DialogueStateProposal(anchors=(good, bad))
    )

    assert state.tier == "T0"
    assert state.anchors == ()
    assert state.fallback_reason == "t1_rejected_unverified_anchor"


class _Proposer:
    def __init__(self, result: DialogueStateProposal | None | Exception) -> None:
        self.result = result
        self.seen: list[str] = []

    async def propose(self, turns: Sequence[DialogueTurn]) -> DialogueStateProposal | None:
        self.seen = [turn.turn_id for turn in turns]
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_build_reports_a_typed_fallback_for_every_t1_outcome() -> None:
    turns = _turns(6)
    anchored = DialogueStateProposal(anchors=(_anchor(turns, 1, "prod-1"),))

    async def run() -> list[DialogueState]:
        return [
            await build_dialogue_state(turns, keep_recent=2),
            await build_dialogue_state(turns, keep_recent=2, proposer=_Proposer(None)),
            await build_dialogue_state(turns, keep_recent=2, proposer=_Proposer(RuntimeError())),
            await build_dialogue_state(turns, keep_recent=2, proposer=_Proposer(anchored)),
        ]

    unconfigured, abstained, failed, accepted = asyncio.run(run())

    assert unconfigured.fallback_reason == "t1_unconfigured"
    assert abstained.fallback_reason == "t1_abstained"
    assert failed.fallback_reason == "t1_failed"
    assert accepted.tier == "T1"
    assert {unconfigured.tier, abstained.tier, failed.tier} == {"T0"}


def test_proposer_sees_only_the_compacted_range_and_is_skipped_when_nothing_compacts() -> None:
    turns = _turns(6)
    proposer = _Proposer(None)

    asyncio.run(build_dialogue_state(turns, keep_recent=2, proposer=proposer))
    assert proposer.seen == ["t0", "t1", "t2", "t3"]

    skipped = _Proposer(RuntimeError())
    state = asyncio.run(build_dialogue_state(turns, keep_recent=6, proposer=skipped))
    assert skipped.seen == []
    assert state.fallback_reason is None
    assert state.compacted_turn_ids == ()


def test_contract_rejects_inexact_accounting_and_authority() -> None:
    state = compact_dialogue(_turns(4), keep_recent=1)
    payload = state.model_dump()

    for update in (
        {"source_turn_count": 99},
        {"kept_turn_ids": ("t0",)},
        {"compacted_digest": None},
        {"execution_authority": True},
        {"tier": "T1", "fallback_reason": "t1_failed"},
    ):
        with pytest.raises(ValidationError):
            DialogueState.model_validate({**payload, **update})
    with pytest.raises(ValidationError):
        DialogueAnchor(kind=DialogueAnchorKind.TIME, value="x", turn_id="t0", start=3, end=3)
    with pytest.raises(ValueError, match="non-negative"):
        compact_dialogue(_turns(2), keep_recent=-1)
