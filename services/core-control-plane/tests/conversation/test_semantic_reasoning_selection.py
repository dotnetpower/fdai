"""Two blind concept choosers: bounded two-call waves over complete catalog shards."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from fdai.core.conversation import semantic_reasoning_selection
from fdai.core.conversation.semantic_reasoning_concepts import ConceptCandidate, ConceptShard
from fdai.core.conversation.semantic_reasoning_form import MentionDomain
from fdai.core.conversation.semantic_reasoning_selection import select_chooser_concepts

from tests.conversation.test_semantic_reasoning_concepts import _admission

_UTTERANCE = "How many VMs depend on sql-app, and what depends on sql-app?"


def _catalog() -> tuple[ConceptCandidate, ...]:
    return tuple(
        ConceptCandidate(f"value:example.{index}", (f"example.{index}",), ("Type",))
        for index in range(10)
    )


def _route_shards_through_runoff(
    monkeypatch: pytest.MonkeyPatch, catalog: tuple[ConceptCandidate, ...]
) -> None:
    """Present the planned shards as finalist runoffs instead of initial requests."""

    plan = semantic_reasoning_selection.plan_concept_selection(
        _admission(),
        catalogs={MentionDomain.RESOURCE_TYPE: catalog},
        max_model_calls=16,
        max_shard_bytes=400,
    )
    monkeypatch.setattr(
        semantic_reasoning_selection,
        "plan_concept_selection",
        lambda *args, **kwargs: replace(plan, requests=()),
    )
    monkeypatch.setattr(
        semantic_reasoning_selection, "runoff_requests", lambda *args: plan.requests
    )


@pytest.mark.parametrize("runoff", (False, True))
async def test_independent_shard_wave_overlaps_at_most_two_without_dropping_candidates(
    monkeypatch: pytest.MonkeyPatch, runoff: bool
) -> None:
    barrier = asyncio.Event()
    active = 0
    peak = 0
    seen: list[str] = []

    async def choose(*, shard: ConceptShard, mentions: Any, **kwargs: Any) -> Any:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 2:
            barrier.set()
        await barrier.wait()
        seen.extend(candidate.id for candidate in shard.candidates)
        active -= 1
        return {
            "shard_digest": shard.digest,
            "choices": [{"mention": item["mention"], "candidate_ids": []} for item in mentions],
        }

    catalog = _catalog()
    if runoff:
        _route_shards_through_runoff(monkeypatch, catalog)
    await asyncio.wait_for(
        select_chooser_concepts(
            SimpleNamespace(choose_concepts=choose),
            admission=_admission(),
            catalogs={MentionDomain.RESOURCE_TYPE: catalog},
            utterance=_UTTERANCE,
            max_calls=16,
            max_shard_bytes=400,
            second=False,
        ),
        timeout=2,
    )
    assert peak == 2
    assert sorted(seen) == sorted(candidate.id for candidate in catalog)


@pytest.mark.parametrize("runoff", (False, True))
async def test_failed_shard_wave_cancels_and_drains_its_other_call(
    monkeypatch: pytest.MonkeyPatch, runoff: bool
) -> None:
    started = asyncio.Event()
    drained = False

    async def choose(*, shard: ConceptShard, **kwargs: Any) -> Any:
        nonlocal drained
        if shard.index == 0:
            await started.wait()
            raise RuntimeError("synthetic provider stop")
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            drained = True

    catalog = _catalog()
    if runoff:
        _route_shards_through_runoff(monkeypatch, catalog)
    with pytest.raises(RuntimeError, match="synthetic provider stop"):
        await asyncio.wait_for(
            select_chooser_concepts(
                SimpleNamespace(choose_concepts=choose),
                admission=_admission(),
                catalogs={MentionDomain.RESOURCE_TYPE: catalog},
                utterance=_UTTERANCE,
                max_calls=16,
                max_shard_bytes=400,
                second=False,
            ),
            timeout=2,
        )
    assert drained
