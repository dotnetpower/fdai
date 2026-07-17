"""Deterministic verification and cross-check helpers for QualityGate."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdai.core.quality_gate.gate import (
        CrossCheckModel,
        GroundingSource,
        ModelVote,
        QualityCandidate,
    )


@dataclass(frozen=True, slots=True)
class GroundingResult:
    grounded_rule_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    known_rule_ids: set[str]


@dataclass(frozen=True, slots=True)
class CrossCheckResult:
    votes: tuple[ModelVote, ...]
    agree_count: int
    first_proposer_output: tuple[str, Any] | None


def verify_grounding(
    candidate: QualityCandidate,
    grounding: GroundingSource,
    *,
    require_grounding: bool,
) -> GroundingResult:
    known = grounding.known_rule_ids()
    grounded: list[str] = []
    reasons: list[str] = []
    supports_fn = getattr(grounding, "supports", None)
    for rule_id in candidate.cited_rule_ids:
        if rule_id not in known:
            reasons.append(f"unknown_cited_rule:{rule_id}")
            continue
        if supports_fn is not None:
            try:
                supported = supports_fn(candidate, rule_id)
            except Exception:  # noqa: BLE001 - grounding failure fails closed
                supported = False
            if not supported:
                reasons.append(f"ungrounded_citation:{rule_id}")
                continue
        grounded.append(rule_id)
    if require_grounding and not grounded:
        reasons.append("no_grounded_citation")
    return GroundingResult(tuple(grounded), tuple(reasons), known)


async def cross_check_candidate(
    candidate: QualityCandidate,
    models: tuple[CrossCheckModel, ...],
) -> CrossCheckResult:
    from fdai.core.quality_gate.gate import ModelVote

    proposals = await asyncio.gather(*(model.propose(candidate) for model in models))
    agree = 0
    votes: list[ModelVote] = []
    first_proposer_output: tuple[str, Any] | None = None
    for index, (model, (proposed_type, proposed_params)) in enumerate(
        zip(models, proposals, strict=True)
    ):
        if index == 0:
            first_proposer_output = (proposed_type, proposed_params)
        agreed = proposed_type == candidate.action_type
        if agreed:
            agree += 1
        votes.append(
            ModelVote(
                model_id=str(getattr(model, "model_id", f"model-{index}")),
                proposed_action_type=proposed_type,
                agreed=agreed,
            )
        )
    return CrossCheckResult(tuple(votes), agree, first_proposer_output)
