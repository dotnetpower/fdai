from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.workflow import (
    CHANGE_WINDOW_GATE_REF,
    ChangeWindowWorkflowGuardEvaluator,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission

from tests.decision_evidence import StubDecisionEvidenceAdmissionProvider

_NOW = datetime(2026, 8, 4, tzinfo=UTC)


class _Admissions(StubDecisionEvidenceAdmissionProvider):
    """Emit one otherwise-matching admission with explicit field overrides."""

    def __init__(self, **overrides: object) -> None:
        super().__init__(lambda: _NOW)
        self._overrides = overrides

    async def admit(self, **request: str) -> DecisionEvidenceAdmission:
        admission = await super().admit(**request)  # type: ignore[arg-type]
        return replace(admission, **self._overrides)  # type: ignore[arg-type]


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


class _MalformedFallback:
    async def evaluate(self, **kwargs: object) -> object:
        del kwargs
        return "denied"


async def test_change_window_gate_uses_exact_target_and_time() -> None:
    evidence = _ChangeWindows(active=True)
    evaluator = ChangeWindowWorkflowGuardEvaluator(
        change_windows=evidence,
        decision_evidence_provider=_Admissions(),
    )

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
        decision_evidence_provider=_Admissions(),
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


async def test_truthy_non_boolean_fallback_cannot_open_a_gate() -> None:
    evaluator = ChangeWindowWorkflowGuardEvaluator(
        change_windows=_ChangeWindows(active=False),
        fallback=_MalformedFallback(),  # type: ignore[arg-type]
        decision_evidence_provider=_Admissions(),
    )

    result = await evaluator.evaluate_context(
        rule_id="architecture-review.production-ready",
        step_id="production",
        process_id="process-1",
        target_resource_id="resource-1",
        at=_NOW,
    )

    assert result is False


async def test_an_unbound_admission_provider_keeps_a_satisfied_gate_closed() -> None:
    evidence = _ChangeWindows(active=True)
    evaluator = ChangeWindowWorkflowGuardEvaluator(change_windows=evidence)

    result = await evaluator.evaluate_context(
        rule_id=CHANGE_WINDOW_GATE_REF,
        step_id="window",
        process_id="process-1",
        target_resource_id="resource-1",
        at=_NOW,
    )

    assert result is False
    assert evidence.calls == [("resource-1", _NOW)]


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"purpose_id": "workflow-outcome"}, id="wrong-purpose"),
        pytest.param({"scope_digest": f"sha256:{'3' * 64}"}, id="wrong-scope"),
        pytest.param({"evidence_digest": f"sha256:{'4' * 64}"}, id="mismatched-evidence"),
        pytest.param({"source_revision": "change-window.forged"}, id="wrong-source-revision"),
        pytest.param(
            {
                "verified_at": datetime(2026, 8, 1, tzinfo=UTC),
                "valid_until": datetime(2026, 8, 2, tzinfo=UTC),
            },
            id="expired",
        ),
    ],
)
async def test_a_mismatched_admission_keeps_a_satisfied_gate_closed(
    overrides: dict[str, object],
) -> None:
    evidence = _ChangeWindows(active=True)
    evaluator = ChangeWindowWorkflowGuardEvaluator(
        change_windows=evidence,
        decision_evidence_provider=_Admissions(**overrides),
    )

    result = await evaluator.evaluate_context(
        rule_id=CHANGE_WINDOW_GATE_REF,
        step_id="window",
        process_id="process-1",
        target_resource_id="resource-1",
        at=_NOW,
    )

    assert result is False
