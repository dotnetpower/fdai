"""Deterministic routing and action translation for Bragi."""

from __future__ import annotations

import re
from collections.abc import Collection

from fdai.agents._framework.bragi_models import RoutingDecision
from fdai.agents._framework.introspection import leading_verb
from fdai.agents._framework.pantheon import PANTHEON_NAMES, PANTHEON_SPECS
from fdai.core.read_investigation import (
    classify_read_investigation_intent,
    resource_name_from_question,
)

INTENT_ACTION: dict[str, str] = {
    "restart": "ops.restart-service",
    "reboot": "ops.restart-service",
    "failover": "ops.failover-primary",
    "delete": "remediate.delete-storage",
    "destroy": "remediate.delete-storage",
    "drop": "remediate.delete-storage",
    "encrypt": "remediate.enable-encryption",
}

_WORD = re.compile(r"[a-z0-9]+")
_PANTHEON_PRECEDENCE = {"governance": 0, "pipeline": 1, "domain": 2}


def route_question(question: str, *, max_contributors: int) -> RoutingDecision:
    explicit = _explicit_agent_names(question)
    if explicit:
        primary, *explicit_contributors = explicit
        return RoutingDecision(
            primary_agent=primary,
            scores={name: 10.0 for name in explicit},
            tie_break="explicit_agent",
            contributors=tuple(explicit_contributors[:max_contributors]),
        )
    read_intent = classify_read_investigation_intent(question)
    if read_intent is not None and resource_name_from_question(question) is not None:
        return RoutingDecision(
            primary_agent="Heimdall",
            scores={"Heimdall": 3.0},
            tie_break=f"read_investigation:{read_intent.value}",
        )
    tokens = _tokenize(question)
    scores: dict[str, float] = {}
    for spec in PANTHEON_SPECS:
        best_score = max(
            (_domain_score(domain, tokens) for domain in spec.question_domains),
            default=0,
        )
        if best_score > 0:
            scores[spec.name] = best_score
    if not scores:
        return RoutingDecision(primary_agent=None, scores={}, tie_break=None)
    winner, tie_break = _pick_winner(scores)
    return RoutingDecision(
        primary_agent=winner,
        scores=scores,
        tie_break=tie_break,
        contributors=tuple(name for name in scores if name != winner),
    )


def translate_action_intent(
    question: str,
    action_type_names: Collection[str] = (),
) -> tuple[str | None, str | None]:
    """Map an operator command to ``(action_type, resource_id)``."""
    action_type = _catalog_action_intent(question, action_type_names)
    if action_type is None:
        action_type = INTENT_ACTION.get(leading_verb(question) or "")
    if action_type is None:
        return None, None
    return action_type, _resource_of(question, action_type=action_type)


def _catalog_action_intent(question: str, action_type_names: Collection[str]) -> str | None:
    normalized = question.lower()
    names = tuple(sorted({name for name in action_type_names if name}))
    exact = [
        name
        for name in names
        if re.search(rf"(?<![a-z0-9.-]){re.escape(name.lower())}(?![a-z0-9.-])", normalized)
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None
    tokens = _tokenize(question)
    matches: list[tuple[int, str]] = []
    for name in names:
        parts = tuple(part for part in name.split(".", 1)[-1].split("-") if part)
        if len(parts) >= 2 and all(part in tokens for part in parts):
            matches.append((len(parts), name))
    if not matches:
        return None
    best_length = max(length for length, _ in matches)
    best = [name for length, name in matches if length == best_length]
    return best[0] if len(best) == 1 else None


def _resource_of(question: str, *, action_type: str | None = None) -> str | None:
    ignored = set(re.split(r"[.-]", action_type.lower())) if action_type else set()
    if action_type:
        ignored.add(action_type.split(".", 1)[-1].lower())
    for token in re.findall(r"[a-z0-9-]+", question.lower()):
        resembles_id = "-" in token or any(character.isdigit() for character in token)
        if token not in ignored and len(token) >= 3 and resembles_id:
            return str(token)
    return None


def _tokenize(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _explicit_agent_names(question: str) -> list[str]:
    canonical = {name.lower(): name for name in PANTHEON_NAMES}
    found: list[str] = []
    for token in _WORD.findall(question.lower()):
        name = canonical.get(token)
        if name is not None and name not in found:
            found.append(name)
    return found


def _domain_score(domain: str, tokens: set[str]) -> float:
    domain_tokens = set(re.split(r"[_\W]+", domain.lower())) - {""}
    if not domain_tokens:
        return 0.0
    exact = len(tokens & domain_tokens)
    if exact == len(domain_tokens):
        return 2.0
    if exact:
        return float(exact)
    partial = 0
    for token in tokens:
        if len(token) < 4:
            continue
        for domain_token in domain_tokens:
            if (
                len(domain_token) >= 4
                and abs(len(token) - len(domain_token)) <= 3
                and (token.startswith(domain_token) or domain_token.startswith(token))
            ):
                partial += 1
                break
    return 0.6 * partial if partial else 0.0


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


__all__ = ["INTENT_ACTION", "route_question", "translate_action_intent"]
