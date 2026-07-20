"""Frozen hallucination-regression gate for Command Deck screen claims."""

from __future__ import annotations

import json
from pathlib import Path

from fdai.delivery.read_api.routes.chat_claim_eval import (
    ClaimEvalCase,
    evaluate_claim_cases,
)

_FIXTURE = Path(__file__).with_name("fixtures") / "chat_claim_eval.json"


def _load_cases() -> list[ClaimEvalCase]:
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return [
        ClaimEvalCase(
            case_id=item["case_id"],
            answer=item["answer"],
            view_context=item["view_context"],
            expected_supported=item["expected_supported"],
        )
        for item in raw
    ]


def test_frozen_claim_corpus_has_zero_unsupported_escapes_and_rejections() -> None:
    metrics = evaluate_claim_cases(_load_cases())

    assert metrics.total == 15
    assert metrics.clean_total == 8
    assert metrics.unsafe_total == 7
    assert metrics.unsupported_claim_escape_rate == 0.0
    assert metrics.clean_rejection_rate == 0.0
    assert metrics.passed is True


def test_metric_reducer_counts_escape_and_false_rejection() -> None:
    cases = [
        ClaimEvalCase(
            case_id="escape",
            answer="Operations require attention.",
            view_context={"facts": []},
            expected_supported=False,
        ),
        ClaimEvalCase(
            case_id="rejection",
            answer="There are 2 events.",
            view_context={"facts": [{"key": "event_count", "value": 1}]},
            expected_supported=True,
        ),
    ]

    metrics = evaluate_claim_cases(cases)

    assert metrics.unsupported_claim_escapes == 1
    assert metrics.clean_rejections == 1
    assert metrics.passed is False
