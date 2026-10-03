"""Two blind concept choosers over complete catalog shards for the question-form shadow.

Each chooser sees every planned shard and resolves its own finalist runoff without seeing
the other's choice, and a binding stands only where both choose the same values. Shards
and runoffs run in waves of at most two provider calls inside the chooser's call budget.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Protocol

from .semantic_reasoning_concepts import (
    ConceptSelectionReceipt,
    ConceptShard,
    accept_concept_selection,
    agree_concepts,
    apply_runoff,
    plan_concept_selection,
    runoff_requests,
    shard_answer_valid,
)


class ConceptChooser(Protocol):
    async def choose_concepts(
        self,
        *,
        utterance: str,
        mentions: tuple[dict[str, Any], ...],
        shard: ConceptShard,
        second: bool = False,
    ) -> Mapping[str, Any] | None: ...


async def select_concepts(
    model: ConceptChooser,
    *,
    admission: Any,
    catalogs: Any,
    utterance: str,
    max_calls: int,
    max_shard_bytes: int,
) -> ConceptSelectionReceipt:
    """Ground every concept with two blind choosers of different model families.

    Each chooser sees every planned shard and resolves its own runoff; a binding stands
    only where both choose the same values, so no single reader grounds a concept.
    """

    primary, second = await asyncio.gather(
        select_chooser_concepts(
            model,
            admission=admission,
            catalogs=catalogs,
            utterance=utterance,
            max_calls=max_calls // 2,
            max_shard_bytes=max_shard_bytes,
            second=False,
        ),
        select_chooser_concepts(
            model,
            admission=admission,
            catalogs=catalogs,
            utterance=utterance,
            max_calls=max_calls // 2,
            max_shard_bytes=max_shard_bytes,
            second=True,
        ),
    )
    return agree_concepts(primary, second)


async def select_chooser_concepts(
    model: ConceptChooser,
    *,
    admission: Any,
    catalogs: Any,
    utterance: str,
    max_calls: int,
    max_shard_bytes: int,
    second: bool,
) -> ConceptSelectionReceipt:
    """Present every planned shard to one chooser, then accept verified choices.

    A failed or cancelled wave cancels and drains its other call before the error
    propagates, so no provider call outlives the stage.
    """

    plan = plan_concept_selection(
        admission,
        catalogs=catalogs,
        max_model_calls=max_calls,
        max_shard_bytes=max_shard_bytes,
    )

    async def choose(request: Any) -> Mapping[str, Any] | None:
        return await model.choose_concepts(
            utterance=utterance, mentions=request.mentions, shard=request.shard, second=second
        )

    async def choose_wave(requests: tuple[Any, ...]) -> list[Mapping[str, Any] | None]:
        tasks = [asyncio.create_task(choose(request)) for request in requests]
        try:
            return list(await asyncio.gather(*tasks))
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    answers: list[Mapping[str, Any] | None] = []
    retries = 0
    for offset in range(0, len(plan.requests), 2):
        wave = plan.requests[offset : offset + 2]
        results = await choose_wave(wave)
        for request, answer in zip(wave, results, strict=True):
            if not shard_answer_valid(answer, request) and (
                len(plan.requests) + retries < max_calls
            ):
                retries += 1
                answer = await choose(request)
            answers.append(answer)
    receipt = accept_concept_selection(plan, answers)
    receipt = replace(receipt, model_calls=receipt.model_calls + retries)
    runoff = runoff_requests(plan, receipt)
    if not runoff or receipt.model_calls + len(runoff) > max_calls:
        return receipt
    runoff_answers: list[Mapping[str, Any] | None] = []
    for offset in range(0, len(runoff), 2):
        runoff_answers.extend(await choose_wave(runoff[offset : offset + 2]))
    return apply_runoff(receipt, runoff, runoff_answers)


__all__ = ["ConceptChooser", "select_chooser_concepts", "select_concepts"]
