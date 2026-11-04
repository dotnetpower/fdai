from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.workflow import (
    OntologyFunctionGateEvaluator,
    OntologyGateReading,
)

_NOW = datetime(2026, 11, 4, tzinfo=UTC)
_DIGEST = "sha256:" + "a" * 64
_REF = "ontology-function:blast-radius.within-limit"


class _Reader:
    def __init__(self, reading: OntologyGateReading | None) -> None:
        self.reading = reading
        self.calls: list[tuple[str, str, datetime]] = []

    async def read(
        self, *, function_ref: str, target_ref: str, at: datetime
    ) -> OntologyGateReading | None:
        self.calls.append((function_ref, target_ref, at))
        return self.reading


class _Fallback:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[str] = []

    async def evaluate(self, **kwargs: object) -> object:
        self.calls.append(str(kwargs["rule_id"]))
        return self.result


def _reading(**overrides: object) -> OntologyGateReading:
    values: dict[str, object] = {
        "function_ref": "blast-radius.within-limit",
        "satisfied": True,
        "complete": True,
        "observed_at": _NOW - timedelta(seconds=30),
        "receipt_digest": _DIGEST,
    }
    values.update(overrides)
    return OntologyGateReading(**values)  # type: ignore[arg-type]


async def _evaluate(evaluator: OntologyFunctionGateEvaluator, rule_id: str = _REF) -> bool:
    return await evaluator.evaluate_context(
        rule_id=rule_id,
        step_id="gate",
        process_id="process-1",
        target_resource_id="resource-1",
        at=_NOW,
    )


def _evaluator(
    reading: OntologyGateReading | None, **kwargs: object
) -> OntologyFunctionGateEvaluator:
    return OntologyFunctionGateEvaluator(
        reader=_Reader(reading),
        max_reading_age=timedelta(minutes=5),
        **kwargs,  # type: ignore[arg-type]
    )


async def test_complete_fresh_receipted_reading_opens_gate_for_exact_target() -> None:
    reader = _Reader(_reading())
    evaluator = OntologyFunctionGateEvaluator(reader=reader, max_reading_age=timedelta(minutes=5))

    assert await _evaluate(evaluator) is True
    assert reader.calls == [("blast-radius.within-limit", "resource-1", _NOW)]


@pytest.mark.parametrize(
    "reading",
    [
        None,
        _reading(satisfied=False),
        _reading(complete=False),
        _reading(receipt_digest="digest"),
        _reading(function_ref="another.function"),
        _reading(observed_at=_NOW - timedelta(minutes=6)),
        _reading(observed_at=_NOW + timedelta(seconds=1)),
        _reading(observed_at=datetime(2026, 11, 3)),
    ],
)
async def test_any_unproven_reading_keeps_gate_shut(reading: OntologyGateReading | None) -> None:
    assert await _evaluate(_evaluator(reading)) is False


async def test_empty_function_name_is_shut_without_reading() -> None:
    reader = _Reader(_reading())
    evaluator = OntologyFunctionGateEvaluator(reader=reader, max_reading_age=timedelta(minutes=5))

    assert await _evaluate(evaluator, "ontology-function:") is False
    assert reader.calls == []


async def test_other_gates_delegate_and_require_exactly_true() -> None:
    reader = _Reader(_reading())
    fallback = _Fallback(True)
    evaluator = OntologyFunctionGateEvaluator(
        reader=reader, max_reading_age=timedelta(minutes=5), fallback=fallback
    )

    assert await _evaluate(evaluator, "change-window.active") is True
    assert fallback.calls == ["change-window.active"]
    assert reader.calls == []

    malformed = _evaluator(None, fallback=_Fallback("denied"))
    assert await _evaluate(malformed, "change-window.active") is False
    assert await _evaluate(_evaluator(None), "change-window.active") is False


def test_non_positive_reading_age_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_reading_age"):
        OntologyFunctionGateEvaluator(reader=_Reader(None), max_reading_age=timedelta(0))
