"""Reduce persisted Pantheon diagnostics into a read-only Console projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai_operator_service.families.conversation.contracts import (
    ConversationUnavailableError,
    JsonObject,
)

_VERDICTS = frozenset({"pass", "review", "fail", "hard_zero_fail"})


def pantheon_projection(assessments: Sequence[Mapping[str, object]]) -> JsonObject:
    """Aggregate only assessments that carry a complete 30-point diagnostic."""

    diagnostics = tuple(
        _diagnostic(value)
        for assessment in assessments
        if (value := assessment.get("pantheon_diagnostic")) is not None
    )
    if not diagnostics:
        return {
            "available": False,
            "turns": 0,
            "pass": 0,
            "review": 0,
            "fail": 0,
            "hard_zero_fail": 0,
            "average_score": None,
            "routing_accuracy": None,
            "missed_t2_rate": None,
            "unnecessary_t2_rate": None,
            "agents": [],
        }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in diagnostics:
        grouped.setdefault(item["agent"], []).append(item)
    agents = [
        {
            "agent": agent,
            "turns": len(rows),
            "average_score": round(sum(row["score"] for row in rows) / len(rows), 4),
            "minimum_score": min(row["score"] for row in rows),
            "pass": sum(row["verdict"] == "pass" for row in rows),
            "review": sum(row["verdict"] == "review" for row in rows),
            "fail": sum(row["verdict"] == "fail" for row in rows),
            "hard_zero_fail": sum(row["verdict"] == "hard_zero_fail" for row in rows),
        }
        for agent, rows in sorted(grouped.items())
    ]
    routing = [_item_passed(item, 1) and _item_passed(item, 2) for item in diagnostics]
    required_t2 = [
        _item_passed(item, 27) for item in diagnostics if item["t2_expectation"] == "required"
    ]
    forbidden_t2 = [
        _item_passed(item, 26) for item in diagnostics if item["t2_expectation"] == "forbidden"
    ]
    return {
        "available": True,
        "turns": len(diagnostics),
        "pass": _verdict_count(diagnostics, "pass"),
        "review": _verdict_count(diagnostics, "review"),
        "fail": _verdict_count(diagnostics, "fail"),
        "hard_zero_fail": _verdict_count(diagnostics, "hard_zero_fail"),
        "average_score": round(
            sum(item["score"] for item in diagnostics) / len(diagnostics),
            4,
        ),
        "routing_accuracy": _rate(routing),
        "missed_t2_rate": _failure_rate(required_t2),
        "unnecessary_t2_rate": _failure_rate(forbidden_t2),
        "agents": agents,
    }


def _diagnostic(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ConversationUnavailableError("Pantheon diagnostic is malformed")
    required = {
        "agent",
        "score",
        "verdict",
        "results",
        "hard_zero_violations",
        "trace_receipt_digest",
        "t2_expectation",
    }
    if required - value.keys():
        raise ConversationUnavailableError("Pantheon diagnostic is missing fields")
    score = value["score"]
    verdict = value["verdict"]
    results = value["results"]
    t2_expectation = value["t2_expectation"]
    if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 30:
        raise ConversationUnavailableError("Pantheon diagnostic score is malformed")
    if verdict not in _VERDICTS or not isinstance(results, list) or len(results) != 30:
        raise ConversationUnavailableError("Pantheon diagnostic verdict or results are malformed")
    if t2_expectation not in {"required", "forbidden", "optional"}:
        raise ConversationUnavailableError("Pantheon diagnostic T2 expectation is malformed")
    normalized_results: list[dict[str, object]] = []
    for index, result in enumerate(results, start=1):
        if not isinstance(result, Mapping):
            raise ConversationUnavailableError("Pantheon diagnostic result is malformed")
        if result.get("item_id") != index or type(result.get("passed")) is not bool:
            raise ConversationUnavailableError("Pantheon diagnostic item order is malformed")
        normalized_results.append(
            {
                "item_id": index,
                "passed": result["passed"],
                "reason": str(result.get("reason", "")),
            }
        )
    if score != sum(bool(item["passed"]) for item in normalized_results):
        raise ConversationUnavailableError("Pantheon diagnostic score does not match results")
    return {
        "agent": str(value["agent"]),
        "score": score,
        "verdict": verdict,
        "results": normalized_results,
        "t2_expectation": t2_expectation,
    }


def _item_passed(value: Mapping[str, object], item_id: int) -> bool:
    result = _result_at(value, item_id)
    return result["passed"] is True


def _result_at(value: Mapping[str, object], item_id: int) -> Mapping[str, object]:
    results = value["results"]
    if not isinstance(results, list):
        raise ConversationUnavailableError("Pantheon diagnostic results are malformed")
    result = results[item_id - 1]
    if not isinstance(result, Mapping):
        raise ConversationUnavailableError("Pantheon diagnostic result is malformed")
    return result


def _verdict_count(values: tuple[dict[str, Any], ...], verdict: str) -> int:
    return sum(value["verdict"] == verdict for value in values)


def _rate(values: list[bool]) -> float | None:
    return None if not values else sum(values) / len(values)


def _failure_rate(values: list[bool]) -> float | None:
    value = _rate(values)
    return None if value is None else 1.0 - value


__all__ = ["pantheon_projection"]
