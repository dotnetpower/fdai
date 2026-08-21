"""Project verified semantic judgments into deterministic Bragi routing."""

from __future__ import annotations

from collections.abc import Collection

from fdai_service_contracts.semantic_judgment import (
    SemanticJudgmentProposal,
)

from fdai.agents._framework.bragi_models import RoutingDecision
from fdai.agents._framework.pantheon import PANTHEON_NAMES, PANTHEON_SPECS

_PANTHEON_PRECEDENCE = {"governance": 0, "pipeline": 1, "domain": 2}


def route_semantic_judgment(
    judgment: SemanticJudgmentProposal,
    *,
    max_contributors: int,
) -> RoutingDecision:
    """Route exact canonical intents and targets from one verified judgment."""

    explicit = tuple(
        target.canonical_value or target.value
        for target in judgment.targets
        if target.kind == "agent" and (target.canonical_value or target.value) in PANTHEON_NAMES
    )
    if explicit:
        primary, *explicit_contributors = explicit
        return RoutingDecision(
            primary_agent=primary,
            scores={name: 10.0 for name in explicit},
            tie_break="explicit_agent",
            contributors=tuple(explicit_contributors[:max_contributors]),
            method="explicit",
        )
    intents = frozenset(
        (judgment.primary_intent, *judgment.secondary_intents, *judgment.requested_facets)
    )
    object_types = frozenset(
        target.canonical_value or target.value
        for target in judgment.targets
        if target.kind == "object_type"
    )
    scores: dict[str, float] = {}
    for spec in PANTHEON_SPECS:
        domain_score = 3.0 * len(intents.intersection(spec.question_domains))
        ownership_score = 0.75 * len(object_types.intersection(spec.owns))
        score = domain_score + min(ownership_score, 1.5)
        if score > 0:
            scores[spec.name] = score
    if not scores:
        return RoutingDecision(
            primary_agent=None,
            scores={},
            tie_break=None,
            method="semantic_abstain",
        )
    winner, tie_break = _pick_winner(scores)
    return RoutingDecision(
        primary_agent=winner,
        scores=scores,
        tie_break=tie_break,
        contributors=tuple(
            name
            for name, _score in sorted(
                scores.items(), key=lambda item: (-item[1], _layer_of(item[0]), item[0])
            )
            if name != winner
        )[:max_contributors],
        method="semantic_judgment",
    )


def action_from_semantic_judgment(
    judgment: SemanticJudgmentProposal,
    action_type_names: Collection[str] = (),
) -> tuple[str | None, str | None]:
    """Return exact action and resource targets from a draft-only judgment."""

    if judgment.action_posture != "draft_only":
        return None, None
    allowed = frozenset(action_type_names)
    actions = tuple(
        target.canonical_value or target.value
        for target in judgment.targets
        if target.kind == "action_type" and (target.canonical_value or target.value) in allowed
    )
    resources = tuple(
        target.canonical_value or target.value
        for target in judgment.targets
        if target.kind == "resource"
    )
    if len(actions) != 1 or len(resources) > 1:
        return None, None
    return actions[0], resources[0] if resources else None


def _pick_winner(scores: dict[str, float]) -> tuple[str, str | None]:
    if not scores:
        raise ValueError("empty scores")
    ordered = sorted(scores.items(), key=lambda item: (-item[1], _layer_of(item[0]), item[0]))
    top_name, top_score = ordered[0]
    if len(ordered) == 1 or ordered[1][1] != top_score:
        return top_name, "score"
    return top_name, "layer_precedence"


def _layer_of(agent_name: str) -> int:
    for spec in PANTHEON_SPECS:
        if spec.name == agent_name:
            return _PANTHEON_PRECEDENCE[spec.layer.value]
    return 99


__all__ = ["action_from_semantic_judgment", "route_semantic_judgment"]
