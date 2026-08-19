"""Deterministic bounded campaign selection from one question universe."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.core.conversation.question_perspectives import QuestionCapabilityFamily
from fdai.core.conversation.question_universe import (
    GeneratedQuestionCase,
    GeneratedQuestionUniverse,
)

_MAX_CAMPAIGN_CASES = 100
_TERMINAL_STATES = frozenset({"passed", "failed", "held", "inconclusive"})
_UNRESOLVED_STATES = frozenset({"failed", "held", "inconclusive"})


@dataclass(frozen=True, slots=True)
class QuestionCaseHistory:
    """Latest terminal campaign state used only for deterministic prioritization."""

    case_id: str
    terminal_state: str
    last_verified_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("question case history id MUST be non-empty")
        if self.terminal_state not in _TERMINAL_STATES:
            raise ValueError("question case history terminal state is unsupported")
        if self.last_verified_at is not None and self.last_verified_at.tzinfo is None:
            raise ValueError("question case history time MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class QuestionSelectionDelta:
    """Exact release and runtime deltas that move affected cases forward."""

    declaration_ids: frozenset[str] = frozenset()
    capability_families: frozenset[QuestionCapabilityFamily] = frozenset()
    inventory_declaration_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class QuestionCaseSelectionReceipt:
    """Replay-stable bounded selection identity for one campaign."""

    question_universe_digest: str
    seed: int
    budget: int
    available_case_count: int
    selected_case_ids: tuple[str, ...]
    perspective_locale_cells: tuple[str, ...]
    receipt_digest: str


def select_question_cases(
    *,
    universe: GeneratedQuestionUniverse,
    budget: int,
    seed: int,
    history: Sequence[QuestionCaseHistory] = (),
    delta: QuestionSelectionDelta | None = None,
) -> tuple[tuple[GeneratedQuestionCase, ...], QuestionCaseSelectionReceipt]:
    """Select delta and unresolved cases first without exceeding 100 cases."""

    if not 1 <= budget <= _MAX_CAMPAIGN_CASES:
        raise ValueError(f"question campaign budget MUST be in [1, {_MAX_CAMPAIGN_CASES}]")
    effective_delta = delta or QuestionSelectionDelta()
    history_by_id = {item.case_id: item for item in history}
    if len(history_by_id) != len(history):
        raise ValueError("question case history ids MUST be unique")
    known_ids = {item.case_id for item in universe.cases}
    if not set(history_by_id) <= known_ids:
        raise ValueError("question case history MUST belong to the exact universe")
    ordered = tuple(
        sorted(
            universe.cases,
            key=lambda item: _priority(
                item,
                history=history_by_id.get(item.case_id),
                delta=effective_delta,
                seed=seed,
            ),
        )
    )
    selected = ordered[: min(budget, len(ordered))]
    cells = tuple(sorted({f"{item.perspective.value}:{item.locale}" for item in selected}))
    body = {
        "question_universe_digest": universe.receipt.receipt_digest,
        "seed": seed,
        "budget": budget,
        "available_case_count": len(universe.cases),
        "selected_case_ids": tuple(item.case_id for item in selected),
        "perspective_locale_cells": cells,
    }
    receipt = QuestionCaseSelectionReceipt(
        question_universe_digest=universe.receipt.receipt_digest,
        seed=seed,
        budget=budget,
        available_case_count=len(universe.cases),
        selected_case_ids=tuple(item.case_id for item in selected),
        perspective_locale_cells=cells,
        receipt_digest=_digest(body),
    )
    return selected, receipt


def _priority(
    case: GeneratedQuestionCase,
    *,
    history: QuestionCaseHistory | None,
    delta: QuestionSelectionDelta,
    seed: int,
) -> tuple[int, float, str]:
    if case.declaration_id in delta.declaration_ids:
        tier = 0
    elif case.required_capability in delta.capability_families:
        tier = 1
    elif case.declaration_id in delta.inventory_declaration_ids:
        tier = 2
    elif history is not None and history.terminal_state in _UNRESOLVED_STATES:
        tier = 3
    elif history is None or history.last_verified_at is None:
        tier = 4
    else:
        tier = 5
    verified_time = (
        history.last_verified_at.astimezone(UTC).timestamp()
        if history is not None and history.last_verified_at is not None
        else float("-inf")
    )
    tie_breaker = hashlib.sha256(f"{seed}:{case.case_id}".encode()).hexdigest()
    return tier, verified_time, tie_breaker


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "QuestionCaseHistory",
    "QuestionCaseSelectionReceipt",
    "QuestionSelectionDelta",
    "select_question_cases",
]
