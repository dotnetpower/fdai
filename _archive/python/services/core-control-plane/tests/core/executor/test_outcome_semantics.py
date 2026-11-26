"""Cross-path execution outcome classification tests."""

from __future__ import annotations

import pytest
from fdai.core.executor.direct_api import DirectApiExecutionOutcome
from fdai.core.executor.executor import ExecutorOutcome
from fdai.core.executor.tool_call import ToolCallExecutionOutcome
from fdai.shared.contracts.execution_outcomes import (
    ExecutionLifecycleDisposition,
    execution_lifecycle_disposition,
    execution_outcome_is_no_effect,
    execution_outcome_is_pending,
    execution_outcome_may_have_effect,
)


@pytest.mark.parametrize(
    ("outcome", "disposition", "effect_possible"),
    [
        ("dispatched", ExecutionLifecycleDisposition.ACCEPTED, True),
        ("already_applied", ExecutionLifecycleDisposition.ACCEPTED, True),
        ("succeeded", ExecutionLifecycleDisposition.ACCEPTED, True),
        ("awaiting_effect_evidence", ExecutionLifecycleDisposition.PENDING, True),
        ("receipt_timeout", ExecutionLifecycleDisposition.PENDING, True),
        ("execution_unknown", ExecutionLifecycleDisposition.PENDING, True),
        ("publish_outcome_unknown", ExecutionLifecycleDisposition.PENDING, True),
        ("dispatch_not_attempted", ExecutionLifecycleDisposition.NO_EFFECT, False),
        ("rejected_invariant", ExecutionLifecycleDisposition.NO_EFFECT, False),
        ("abstained_render_error", ExecutionLifecycleDisposition.NO_EFFECT, False),
        ("failed", ExecutionLifecycleDisposition.FAILED, True),
        ("unrecognized", ExecutionLifecycleDisposition.FAILED, False),
    ],
)
def test_execution_outcome_classification(
    outcome: str,
    disposition: ExecutionLifecycleDisposition,
    effect_possible: bool,
) -> None:
    assert execution_lifecycle_disposition(outcome) is disposition
    assert execution_outcome_is_pending(outcome) is (
        disposition is ExecutionLifecycleDisposition.PENDING
    )
    assert execution_outcome_is_no_effect(outcome) is (
        disposition is ExecutionLifecycleDisposition.NO_EFFECT
    )
    assert execution_outcome_may_have_effect(outcome) is effect_possible


def test_every_executor_outcome_has_an_explicit_shared_classification() -> None:
    expected = {
        "published": ExecutionLifecycleDisposition.ACCEPTED,
        "already_existed": ExecutionLifecycleDisposition.ACCEPTED,
        "dispatched": ExecutionLifecycleDisposition.ACCEPTED,
        "already_applied": ExecutionLifecycleDisposition.ACCEPTED,
        "publish_outcome_unknown": ExecutionLifecycleDisposition.PENDING,
        "awaiting_effect_evidence": ExecutionLifecycleDisposition.PENDING,
        "receipt_timeout": ExecutionLifecycleDisposition.PENDING,
        "execution_unknown": ExecutionLifecycleDisposition.PENDING,
        "dispatch_not_attempted": ExecutionLifecycleDisposition.NO_EFFECT,
        "abstained_blast_radius": ExecutionLifecycleDisposition.NO_EFFECT,
        "abstained_precondition": ExecutionLifecycleDisposition.NO_EFFECT,
        "abstained_render_error": ExecutionLifecycleDisposition.NO_EFFECT,
        "authentication_failed": ExecutionLifecycleDisposition.NO_EFFECT,
        "permission_denied": ExecutionLifecycleDisposition.NO_EFFECT,
        "policy_denied": ExecutionLifecycleDisposition.NO_EFFECT,
        "network_denied": ExecutionLifecycleDisposition.NO_EFFECT,
        "rejected_mode": ExecutionLifecycleDisposition.NO_EFFECT,
        "rejected_invariant": ExecutionLifecycleDisposition.NO_EFFECT,
        "rejected_capability_unavailable": ExecutionLifecycleDisposition.NO_EFFECT,
        "rejected_idempotency_conflict": ExecutionLifecycleDisposition.NO_EFFECT,
        "expired": ExecutionLifecycleDisposition.NO_EFFECT,
        "stopped": ExecutionLifecycleDisposition.FAILED,
        "failed": ExecutionLifecycleDisposition.FAILED,
    }

    outcomes = {
        *ExecutorOutcome,
        *DirectApiExecutionOutcome,
        *ToolCallExecutionOutcome,
    }
    assert {outcome.value for outcome in outcomes} == set(expected)
    for outcome in outcomes:
        assert execution_lifecycle_disposition(outcome) is expected[outcome.value]
