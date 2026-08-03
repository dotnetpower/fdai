from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.workflow import (
    CHANGE_WINDOW_GATE_REF,
    ChangeWindowWorkflowGuardEvaluator,
)

_NOW = datetime(2026, 8, 4, tzinfo=UTC)


class _ChangeWindows:
    def __init__(self, *, active: bool) -> None:
        self.active = active
        self.calls: list[tuple[str, datetime]] = []

    async def is_active(self, *, target_ref: str, at: datetime) -> bool:
        self.calls.append((target_ref, at))
        return self.active


class _Fallback:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def evaluate(self, **kwargs: object) -> bool:
        self.calls.append(str(kwargs["rule_id"]))
        return True


async def test_change_window_gate_uses_exact_target_and_time() -> None:
    evidence = _ChangeWindows(active=True)
    evaluator = ChangeWindowWorkflowGuardEvaluator(change_windows=evidence)

    result = await evaluator.evaluate_context(
        rule_id=CHANGE_WINDOW_GATE_REF,
        step_id="window",
        process_id="process-1",
        target_resource_id="resource-1",
        at=_NOW,
    )

    assert result is True
    assert evidence.calls == [("resource-1", _NOW)]


async def test_unrelated_gate_delegates_without_querying_change_windows() -> None:
    evidence = _ChangeWindows(active=False)
    fallback = _Fallback()
    evaluator = ChangeWindowWorkflowGuardEvaluator(
        change_windows=evidence,
        fallback=fallback,
    )

    result = await evaluator.evaluate_context(
        rule_id="architecture-review.production-ready",
        step_id="production",
        process_id="process-1",
        target_resource_id="resource-1",
        at=_NOW,
    )

    assert result is True
    assert fallback.calls == ["architecture-review.production-ready"]
    assert evidence.calls == []
