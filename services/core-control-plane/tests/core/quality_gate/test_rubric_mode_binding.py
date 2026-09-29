"""Receipt-driven rubric modes: the configured ceiling plus a bound per-ActionType resolver."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from fdai.core.quality_gate import QualityGate, QualityGateConfig, QualityOutcome
from fdai.core.quality_gate._audit import quality_decision_audit_fields
from fdai.core.quality_gate.promotion import RubricModeDecision
from fdai.core.quality_gate.testing import (
    InMemoryGroundingSource,
    MatchTypeCrossCheckModel,
    StaticVerifier,
)
from fdai.runtime.t2_quality_gate import build_rubric_mode_resolver
from fdai.shared.contracts.models import Mode

from .test_rubric_gate import _CRITERIA, _candidate, _failing_rubric, _rule


@dataclass
class _Resolver:
    decision: RubricModeDecision | None = None
    error: Exception | None = None
    calls: list[str] = field(default_factory=list)

    def resolve(self, action_type_name: str) -> RubricModeDecision:
        self.calls.append(action_type_name)
        if self.error is not None:
            raise self.error
        assert self.decision is not None
        return self.decision


def _gate(*, rubric_shadow: bool, resolver: Any = None) -> QualityGate:
    return QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(model_id="m1"),
            MatchTypeCrossCheckModel(model_id="m2"),
        ),
        grounding=InMemoryGroundingSource({"r.known": _rule("r.known")}),
        config=QualityGateConfig(
            confidence_threshold=0.7,
            require_grounding=True,
            require_cross_check_quorum=2,
            rubric_shadow=rubric_shadow,
            rubric_required_criteria=_CRITERIA,
        ),
        rubric_evaluator=_failing_rubric(),
        rubric_mode_resolver=resolver,
    )


@pytest.mark.asyncio
async def test_shadow_ceiling_is_never_lifted_by_a_ready_receipt() -> None:
    resolver = _Resolver(RubricModeDecision(Mode.ENFORCE, "rubric_receipt_ready", "a" * 64))
    decision = await _gate(rubric_shadow=True, resolver=resolver).evaluate(_candidate())

    assert decision.outcome is QualityOutcome.ELIGIBLE
    assert decision.rubric_shadow is True
    assert decision.rubric_mode_reason is None
    assert resolver.calls == []


@pytest.mark.asyncio
async def test_ready_verified_receipt_enforces_below_the_ceiling() -> None:
    resolver = _Resolver(RubricModeDecision(Mode.ENFORCE, "rubric_receipt_ready", "a" * 64))
    candidate = _candidate()
    decision = await _gate(rubric_shadow=False, resolver=resolver).evaluate(candidate)

    assert resolver.calls == [candidate.action_type]
    assert decision.rubric_shadow is False
    assert decision.rubric_mode_reason == "rubric_receipt_ready"
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert any(reason.startswith("rubric_failed") for reason in decision.reasons)


@pytest.mark.parametrize(
    "reason",
    [
        "rubric_receipt_missing",
        "rubric_receipt_expired",
        "rubric_receipt_rejected",
        "rubric_receipt_authority_mismatch",
        "action_type_not_enforce",
    ],
)
@pytest.mark.asyncio
async def test_unready_receipt_keeps_the_leg_in_shadow(reason: str) -> None:
    resolver = _Resolver(RubricModeDecision(Mode.SHADOW, reason))
    decision = await _gate(rubric_shadow=False, resolver=resolver).evaluate(_candidate())

    assert decision.rubric_shadow is True
    assert decision.rubric_mode_reason == reason
    assert decision.outcome is QualityOutcome.ELIGIBLE
    assert decision.aggregate_confidence == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_resolver_error_fails_closed_to_shadow() -> None:
    resolver = _Resolver(error=RuntimeError("receipt source unavailable"))
    decision = await _gate(rubric_shadow=False, resolver=resolver).evaluate(_candidate())

    assert decision.rubric_shadow is True
    assert decision.rubric_mode_reason == "rubric_mode_resolver_error:RuntimeError"
    assert decision.outcome is QualityOutcome.ELIGIBLE


@pytest.mark.asyncio
async def test_without_a_resolver_the_configured_mode_applies_unchanged() -> None:
    decision = await _gate(rubric_shadow=False).evaluate(_candidate())

    assert decision.rubric_shadow is False
    assert decision.rubric_mode_reason is None
    assert decision.outcome is QualityOutcome.ABSTAIN


@pytest.mark.asyncio
async def test_resolver_reason_reaches_the_audit_projection() -> None:
    resolver = _Resolver(RubricModeDecision(Mode.SHADOW, "rubric_receipt_missing"))
    decision = await _gate(rubric_shadow=False, resolver=resolver).evaluate(_candidate())

    fields = quality_decision_audit_fields(decision)
    assert fields["rubric_mode_reason"] == "rubric_receipt_missing"
    unresolved = await _gate(rubric_shadow=True).evaluate(_candidate())
    assert "rubric_mode_reason" not in quality_decision_audit_fields(unresolved)


class _ModeSource:
    def mode_of(self, action_type: str) -> Mode:
        return Mode.SHADOW

    def record(self, action_type: str) -> None:
        return None


def test_runtime_binds_a_resolver_only_with_the_receipt_evidence_pair() -> None:
    unbound = SimpleNamespace(
        rubric_promotion_receipt_source=None,
        rubric_promotion_receipt_verifier=None,
    )
    assert build_rubric_mode_resolver(unbound, _ModeSource()) is None  # type: ignore[arg-type]

    bound = SimpleNamespace(
        rubric_promotion_receipt_source=SimpleNamespace(current=lambda name: None),
        rubric_promotion_receipt_verifier=SimpleNamespace(verify=lambda receipt: False),
    )
    resolver = build_rubric_mode_resolver(bound, _ModeSource())  # type: ignore[arg-type]
    assert resolver is not None
    assert resolver.resolve("remediate.tag-add") == RubricModeDecision(
        Mode.SHADOW, "action_type_not_enforce"
    )
