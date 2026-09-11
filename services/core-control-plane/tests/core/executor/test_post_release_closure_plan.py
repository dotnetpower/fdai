"""Binding contract for one atomic post-release closure plan.

A closure plan is the exact predecessor/successor pair a single database
transaction will apply. If any leg can be swapped - a different action's
evidence, a rewritten release receipt, a foreign reservation, or a fence from
another generation - then the "atomic" write is no longer atomic over the
thing it claims to close. Every substitution below MUST be refused.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from fdai.core.executor.post_release_closure import (
    PostReleaseClosureOutcome,
    ReconciliationEvidenceKind,
    ReconciliationOutcome,
)
from fdai.core.executor.post_release_closure_plan import (
    PostReleaseClosurePlan,
    build_initial_post_release_closure,
    build_reconciled_post_release_closure,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import AuthoritativeSinkState

from tests.core.executor.test_post_release_closure import (
    _initial_plan,
    _reconciliation_evidence,
    _release_receipt,
)
from tests.core.executor.test_safeguard_dispatch_checkpoint import _NOW

_OTHER = {
    "action_name": "other",
    "idempotency_key": "other-idem",
    "target_resource_ref": "resource/other",
}


def _resolved_plan() -> PostReleaseClosurePlan:
    return _initial_plan(sink_state=AuthoritativeSinkState.COMMITTED)


def _quarantined_plan() -> PostReleaseClosurePlan:
    return _initial_plan(sink_state=AuthoritativeSinkState.ACCEPTED)


def _other_plan() -> PostReleaseClosurePlan:
    return _initial_plan(sink_state=AuthoritativeSinkState.COMMITTED, **_OTHER)


def _reconciled_plan() -> PostReleaseClosurePlan:
    initial = _quarantined_plan()
    return build_reconciled_post_release_closure(
        prior_closure=initial.record,
        pre_release_record=initial.pre_release_record,
        reservation_record=initial.reservation_record,
        quarantined_fence=initial.fence_record,
        release_receipt=initial.release_receipt,
        evidence=_reconciliation_evidence(
            initial,
            kind=ReconciliationEvidenceKind.AUTHORITATIVE_SINK_STATUS,
            outcome=ReconciliationOutcome.SINK_IRREVOCABLY_NOT_ACCEPTED,
        ),
        reconciled_at=_NOW + timedelta(seconds=6),
    )


class TestPlanShape:
    def test_a_plan_requires_exact_pre_release_evidence(self) -> None:
        plan = _resolved_plan()
        start = plan.pre_release_record.dispatch_start_checkpoint
        assert start is not None

        with pytest.raises(ValueError, match="requires exact pre-release evidence"):
            replace(plan, pre_release_record="pre-release")  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("field", "name"),
        [
            ("prior_reservation_record", "reservation predecessor"),
            ("reservation_record", "reservation successor"),
            ("prior_fence_record", "fence predecessor"),
            ("fence_record", "fence successor"),
            ("release_receipt", "release receipt"),
            ("record", "closure record"),
        ],
    )
    def test_every_plan_leg_must_be_an_exact_record(self, field: str, name: str) -> None:
        with pytest.raises(ValueError, match=f"post-release plan {name} is invalid"):
            replace(_resolved_plan(), **{field: name})


class TestInitialPlanBuilder:
    def test_an_inexact_reservation_record_is_refused(self) -> None:
        plan = _resolved_plan()

        with pytest.raises(ValueError, match="requires exact reservation record"):
            build_initial_post_release_closure(
                pre_release_record=plan.pre_release_record,
                reservation_record="reservation",  # type: ignore[arg-type]
                release_pending_fence=plan.prior_fence_record,
                release_receipt=plan.release_receipt,
                closed_at=plan.record.closed_at,
            )

    def test_an_already_terminal_reservation_cannot_be_closed_again(self) -> None:
        plan = _resolved_plan()

        with pytest.raises(ValueError, match="requires unresolved reservation"):
            build_initial_post_release_closure(
                pre_release_record=plan.pre_release_record,
                reservation_record=plan.reservation_record,
                release_pending_fence=plan.prior_fence_record,
                release_receipt=plan.release_receipt,
                closed_at=plan.record.closed_at,
            )

    def test_a_release_receipt_from_another_acquisition_is_refused(self) -> None:
        plan = _resolved_plan()
        foreign = _other_plan()

        with pytest.raises(ValueError, match="release receipt changed acquisition"):
            build_initial_post_release_closure(
                pre_release_record=plan.pre_release_record,
                reservation_record=plan.prior_reservation_record,
                release_pending_fence=plan.prior_fence_record,
                release_receipt=foreign.release_receipt,
                closed_at=plan.record.closed_at,
            )

    def test_a_repeated_quarantine_keeps_the_unknown_reservation_unchanged(self) -> None:
        first = _initial_plan(sink_state=AuthoritativeSinkState.UNKNOWN)
        assert first.record.outcome is PostReleaseClosureOutcome.QUARANTINED

        # Re-closing an already unknown reservation must not invent a new
        # reservation transition; the durable record stays exactly as it was.
        repeated = build_initial_post_release_closure(
            pre_release_record=first.pre_release_record,
            reservation_record=first.reservation_record,
            release_pending_fence=first.prior_fence_record,
            release_receipt=first.release_receipt,
            closed_at=first.record.closed_at,
        )

        assert repeated.reservation_record == repeated.prior_reservation_record
        assert repeated.reservation_record == first.reservation_record
        assert repeated.record.outcome is PostReleaseClosureOutcome.QUARANTINED


class TestReconciliationBuilder:
    def _kwargs(self, plan: PostReleaseClosurePlan, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "prior_closure": plan.record,
            "pre_release_record": plan.pre_release_record,
            "reservation_record": plan.reservation_record,
            "quarantined_fence": plan.fence_record,
            "release_receipt": plan.release_receipt,
            "evidence": _reconciliation_evidence(
                plan,
                kind=ReconciliationEvidenceKind.AUTHORITATIVE_SINK_STATUS,
                outcome=ReconciliationOutcome.SINK_IRREVOCABLY_NOT_ACCEPTED,
            ),
            "reconciled_at": _NOW + timedelta(seconds=6),
        }
        base.update(overrides)
        return base

    def test_a_resolved_closure_cannot_be_reconciled(self) -> None:
        resolved = _resolved_plan()
        quarantined = _quarantined_plan()

        with pytest.raises(ValueError, match="requires quarantined closure"):
            build_reconciled_post_release_closure(
                **self._kwargs(quarantined, prior_closure=resolved.record)
            )

    def test_inexact_reconciliation_evidence_is_refused(self) -> None:
        plan = _quarantined_plan()

        with pytest.raises(ValueError, match="requires exact durable evidence"):
            build_reconciled_post_release_closure(**self._kwargs(plan, evidence="verified"))

    def test_reconciliation_cannot_change_the_closure_identity(self) -> None:
        plan = _quarantined_plan()
        foreign = _other_plan()

        with pytest.raises(ValueError, match="changed closure identity"):
            build_reconciled_post_release_closure(
                **self._kwargs(plan, pre_release_record=foreign.pre_release_record)
            )

    def test_reconciliation_cannot_rewrite_the_release_evidence(self) -> None:
        plan = _quarantined_plan()

        with pytest.raises(ValueError, match="rewrote release evidence"):
            build_reconciled_post_release_closure(
                **self._kwargs(
                    plan,
                    release_receipt=_release_receipt(
                        plan.pre_release_record,
                        attestation="sha256:" + "7" * 64,
                    ),
                )
            )

    def test_evidence_recorded_before_the_quarantine_is_refused(self) -> None:
        plan = _quarantined_plan()
        evidence = _reconciliation_evidence(
            plan,
            kind=ReconciliationEvidenceKind.AUTHORITATIVE_SINK_STATUS,
            outcome=ReconciliationOutcome.SINK_IRREVOCABLY_NOT_ACCEPTED,
            now=_NOW - timedelta(hours=1),
        )

        with pytest.raises(ValueError, match="evidence predates quarantine"):
            build_reconciled_post_release_closure(**self._kwargs(plan, evidence=evidence))

    def test_a_reconciliation_cannot_predate_its_own_evidence(self) -> None:
        plan = _quarantined_plan()

        with pytest.raises(ValueError, match="reconciliation predates durable evidence"):
            build_reconciled_post_release_closure(
                **self._kwargs(plan, reconciled_at=_NOW + timedelta(seconds=1))
            )

    def test_a_changed_predecessor_is_refused(self) -> None:
        plan = _quarantined_plan()

        with pytest.raises(ValueError, match="reconciliation predecessor changed"):
            build_reconciled_post_release_closure(
                **self._kwargs(plan, reservation_record=plan.prior_reservation_record)
            )


class TestPlanBindings:
    def test_a_plan_cannot_swap_in_another_actions_evidence(self) -> None:
        plan = _resolved_plan()
        foreign = _other_plan()

        with pytest.raises(ValueError, match="changed pre-release identity"):
            replace(plan, pre_release_record=foreign.pre_release_record)

    def test_a_plan_cannot_swap_in_another_actions_reservation(self) -> None:
        plan = _resolved_plan()
        foreign = _other_plan()

        with pytest.raises(ValueError, match="changed reservation acquisition"):
            replace(plan, prior_reservation_record=foreign.prior_reservation_record)

    def test_a_plan_cannot_swap_in_another_generations_fence(self) -> None:
        plan = _resolved_plan()
        foreign = _other_plan()

        with pytest.raises(ValueError, match="changed target fence generation"):
            replace(plan, prior_fence_record=foreign.prior_fence_record)

    def test_an_initial_plan_requires_a_release_pending_predecessor(self) -> None:
        plan = _resolved_plan()

        with pytest.raises(ValueError, match="requires release-pending fence"):
            replace(plan, prior_fence_record=plan.fence_record)

    def test_a_reconciliation_plan_requires_a_quarantined_predecessor(self) -> None:
        plan = _reconciled_plan()

        with pytest.raises(ValueError, match="reconciliation requires quarantined fence"):
            replace(plan, prior_fence_record=plan.fence_record)

    def test_a_plan_record_must_bind_the_exact_release_receipt(self) -> None:
        plan = _resolved_plan()

        with pytest.raises(ValueError, match="record digests mismatched exact records"):
            replace(
                plan,
                release_receipt=_release_receipt(
                    plan.pre_release_record,
                    attestation="sha256:" + "8" * 64,
                ),
            )
