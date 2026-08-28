from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from fdai.core.operational_learning.cost_governance import (
    CostLearningCohortCompiler,
    build_cost_case_projection,
)
from fdai.shared.providers.cost_governance_decision import (
    CostDecisionOutcome,
    CostDecisionRecord,
    CostEffectKind,
    CostEffectSettlement,
    CostEpisodeSettlement,
    CostSettlementStatus,
)

NOW = datetime(2026, 8, 28, 8, tzinfo=UTC)
DIGEST_A = f"sha256:{'a' * 64}"
DIGEST_B = f"sha256:{'b' * 64}"
DIGEST_C = f"sha256:{'c' * 64}"


def _decision(
    episode_id: str,
    outcome: CostDecisionOutcome,
    *,
    terminal: bool,
) -> CostDecisionRecord:
    return CostDecisionRecord(
        episode_id=episode_id,
        outcome=outcome,
        reason="fixture-outcome",
        decision_frame_digest=DIGEST_A,
        terminal=terminal,
        observation_mode=False,
        selected_option_id="option-safe",
        hold_deadline=None,
        evidence_refs=(DIGEST_B,),
    )


def _verified_settlement(
    episode_id: str,
    *,
    realized: str = "20",
) -> CostEpisodeSettlement:
    return CostEpisodeSettlement(
        episode_id=episode_id,
        decision_frame_digest=DIGEST_A,
        effects=(
            CostEffectSettlement(
                effect_id="effect-cost",
                kind=CostEffectKind.COST,
                status=CostSettlementStatus.VERIFIED,
                reason="expected-effect-observed",
                terminal=True,
                observed_value=Decimal("80"),
                observation_digest=DIGEST_B,
                completeness_digest=DIGEST_C,
                settled_at=NOW,
            ),
        ),
        terminal=True,
        realized_savings=Decimal(realized),
        rollback_request=None,
        recovery_observed=False,
        settled_at=NOW,
    )


def _case(
    episode_id: str,
    outcome: CostDecisionOutcome,
    *,
    terminal: bool,
    settlement: CostEpisodeSettlement | None,
):
    return build_cost_case_projection(
        revision=1,
        decision=_decision(episode_id, outcome, terminal=terminal),
        settlement=settlement,
        recovery_attempts=(),
        evidence_refs=(DIGEST_A, DIGEST_B),
        terminal_audit_digest=DIGEST_C,
    )


def test_replay_projection_is_immutable_and_deterministic() -> None:
    decision = _decision("episode-positive", CostDecisionOutcome.EXECUTE, terminal=False)
    settlement = _verified_settlement("episode-positive")

    first = build_cost_case_projection(
        revision=1,
        decision=decision,
        settlement=settlement,
        recovery_attempts=(),
        evidence_refs=(DIGEST_A, DIGEST_B),
        terminal_audit_digest=DIGEST_C,
    )
    reordered = build_cost_case_projection(
        revision=1,
        decision=decision,
        settlement=settlement,
        recovery_attempts=(),
        evidence_refs=(DIGEST_B, DIGEST_A),
        terminal_audit_digest=DIGEST_C,
    )

    assert first.lineage_complete is True
    assert reordered.projection_digest == first.projection_digest
    assert first.projection_digest.startswith("sha256:")


def test_learning_rejects_incomplete_and_single_outcome_cohorts() -> None:
    compiler = CostLearningCohortCompiler()
    positive = _case(
        "episode-positive",
        CostDecisionOutcome.EXECUTE,
        terminal=False,
        settlement=_verified_settlement("episode-positive"),
    )
    incomplete = _case(
        "episode-incomplete",
        CostDecisionOutcome.EXECUTE,
        terminal=False,
        settlement=None,
    )
    another_positive = _case(
        "episode-positive-2",
        CostDecisionOutcome.EXECUTE,
        terminal=False,
        settlement=_verified_settlement("episode-positive-2"),
    )

    assert compiler.compile((positive, incomplete)) is None
    assert compiler.compile((positive, another_positive)) is None
    assert compiler.compile((positive, positive)) is None


def test_replay_lineage_requires_saga_terminal_audit() -> None:
    projection = build_cost_case_projection(
        revision=1,
        decision=_decision(
            "episode-unaudited",
            CostDecisionOutcome.EXECUTE,
            terminal=False,
        ),
        settlement=_verified_settlement("episode-unaudited"),
        recovery_attempts=(),
        evidence_refs=(DIGEST_A, DIGEST_B),
        terminal_audit_digest=None,
    )

    assert projection.lineage_complete is False


def test_learning_rejects_censored_and_unscorable_cases() -> None:
    positive = _case(
        "episode-positive",
        CostDecisionOutcome.EXECUTE,
        terminal=False,
        settlement=_verified_settlement("episode-positive"),
    )
    for status in (CostSettlementStatus.CENSORED, CostSettlementStatus.UNSCORABLE):
        unverified = replace(
            _verified_settlement(f"episode-{status.value}"),
            effects=(
                replace(
                    _verified_settlement(f"episode-{status.value}").effects[0],
                    status=status,
                    reason=f"{status.value}-fixture",
                    observed_value=None,
                    observation_digest=None,
                ),
            ),
            realized_savings=Decimal("0"),
        )
        candidate = _case(
            f"episode-{status.value}",
            CostDecisionOutcome.EXECUTE,
            terminal=False,
            settlement=unverified,
        )

        assert candidate.lineage_complete is False
        assert CostLearningCohortCompiler().compile((positive, candidate)) is None


def test_balanced_complete_cohort_is_inert_and_reorder_stable() -> None:
    positive = _case(
        "episode-positive",
        CostDecisionOutcome.EXECUTE,
        terminal=False,
        settlement=_verified_settlement("episode-positive"),
    )
    negative = _case(
        "episode-no-op",
        CostDecisionOutcome.NO_OP,
        terminal=True,
        settlement=None,
    )
    compiler = CostLearningCohortCompiler()

    first = compiler.compile((positive, negative))
    reordered = compiler.compile((negative, positive))

    assert first is not None
    assert reordered is not None
    assert first.cohort_id == reordered.cohort_id
    assert first.positive_count == first.negative_count == 1
    assert first.inert is True
    assert not hasattr(first, "promote")
    assert not hasattr(first, "mutate_catalog")


def test_no_op_requires_terminal_audit_before_replay_or_learning() -> None:
    pending = _case(
        "episode-no-op",
        CostDecisionOutcome.NO_OP,
        terminal=False,
        settlement=None,
    )
    terminal = replace(
        pending,
        decision=replace(pending.decision, terminal=True),
        lineage_complete=True,
    )

    assert pending.lineage_complete is False
    assert CostLearningCohortCompiler().compile((pending, terminal)) is None
