from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.recovery import (
    PreauthorizedRecoveryController,
    ProbeVerdict,
    RecoveryAction,
    RecoveryProbeKind,
    RecoveryProbeResult,
    RecoveryStrategy,
    RecoveryVerificationOutcome,
    compile_recovery_plan,
    evaluate_recovery_readiness,
    preauthorization_covers,
    reverse_topological_compensation,
    verify_recovery_postconditions,
)

_NOW = datetime(2026, 7, 31, tzinfo=UTC)


def _action(
    action_id: str,
    *,
    depends_on: tuple[str, ...] = (),
    action_type: str | None = None,
) -> RecoveryAction:
    return RecoveryAction(
        action_id=action_id,
        action_type_ref=action_type or f"ops.{action_id}",
        action_type_version="1.0.0",
        target_ref="resource-a",
        depends_on=depends_on,
        compensation_action_type_ref=f"ops.undo-{action_id}",
        stop_conditions=("time_box",),
        rollback_ref=f"rollback:{action_id}",
    )


def _plan(**overrides: object):  # type: ignore[no-untyped-def]
    values: dict[str, object] = {
        "strategy": RecoveryStrategy.COMPENSATE,
        "workflow_ref": "recover-service",
        "workflow_version": "1.0.0",
        "catalog_digest": "catalog-1",
        "actions": (_action("a"), _action("b", depends_on=("a",))),
        "impact_envelope_id": "impact-1",
        "recovery_objective_ref": "rto-1",
        "verification_probes": tuple(item.value for item in RecoveryProbeKind),
        "direct_target_ids": ("resource-a",),
        "graph_revision": "graph-1",
        "dry_run_receipt": "dry-run-1",
        "last_rehearsed_at": _NOW - timedelta(hours=1),
        "expires_at": _NOW + timedelta(hours=1),
    }
    values.update(overrides)
    return compile_recovery_plan(**values)  # type: ignore[arg-type]


def test_compensation_is_reverse_topological_and_deterministic() -> None:
    actions = (
        _action("a"),
        _action("b", depends_on=("a",)),
        _action("c", depends_on=("a",)),
        _action("d", depends_on=("b", "c")),
    )
    assert reverse_topological_compensation(actions) == ("d", "c", "b", "a")


def test_compensation_rejects_cycle_dangling_and_missing_inverse() -> None:
    with pytest.raises(ValueError, match="acyclic"):
        reverse_topological_compensation(
            (_action("a", depends_on=("b",)), _action("b", depends_on=("a",)))
        )
    with pytest.raises(ValueError, match="dangling"):
        reverse_topological_compensation((_action("a", depends_on=("missing",)),))
    with pytest.raises(ValueError, match="compensation evidence"):
        reverse_topological_compensation(
            (
                RecoveryAction(
                    action_id="a",
                    action_type_ref="ops.a",
                    action_type_version="1.0.0",
                    target_ref="resource-a",
                    stop_conditions=("time_box",),
                ),
            )
        )


def test_plan_is_ready_and_projects_ontology() -> None:
    plan = _plan()
    assert plan.status.value == "ready"
    assert plan.compensation_order == ("b", "a")
    assert plan.to_ontology_object().object_type == "RecoveryPlan"


def test_readiness_collects_every_fail_closed_reason() -> None:
    plan = _plan(expires_at=_NOW - timedelta(minutes=1))
    readiness = evaluate_recovery_readiness(
        plan,
        now=_NOW,
        current_graph_revision="graph-new",
        promoted_action_types=frozenset(),
        telemetry_sources=frozenset(),
        required_telemetry_sources=frozenset({"metrics"}),
        max_rehearsal_age=timedelta(minutes=1),
    )
    assert not readiness.ready
    assert set(readiness.reasons) == {
        "graph_revision_changed",
        "plan_expired",
        "recovery_action_not_promoted",
        "rehearsal_stale",
        "telemetry_incomplete",
    }


def test_preauthorization_refuses_scope_version_and_destructive_widening() -> None:
    plan = _plan()
    assert preauthorization_covers(
        plan,
        target_ids=("resource-a",),
        action_versions=(("ops.a", "1.0.0"),),
        now=_NOW,
    )
    assert not preauthorization_covers(
        plan,
        target_ids=("resource-b",),
        action_versions=(("ops.a", "1.0.0"),),
        now=_NOW,
    )
    assert not preauthorization_covers(
        plan,
        target_ids=("resource-a",),
        action_versions=(("ops.a", "2.0.0"),),
        now=_NOW,
    )
    assert not preauthorization_covers(
        plan,
        target_ids=("resource-a",),
        action_versions=(("ops.a", "1.0.0"),),
        now=_NOW,
        destructive=True,
    )


def _probes(verdict: ProbeVerdict = ProbeVerdict.PASSED) -> tuple[RecoveryProbeResult, ...]:
    return tuple(
        RecoveryProbeResult(
            kind=kind,
            verdict=verdict,
            observed_at=_NOW,
            evidence_ref=f"evidence:{kind.value}",
        )
        for kind in RecoveryProbeKind
    )


def test_verification_requires_all_six_independent_postconditions() -> None:
    recovered = verify_recovery_postconditions(_probes(), telemetry_complete=True)
    assert recovered.outcome is RecoveryVerificationOutcome.RECOVERED

    unscorable = verify_recovery_postconditions(_probes()[:-1], telemetry_complete=True)
    assert unscorable.outcome is RecoveryVerificationOutcome.UNSCORABLE

    failed = list(_probes())
    failed[0] = RecoveryProbeResult(
        kind=failed[0].kind,
        verdict=ProbeVerdict.FAILED,
        observed_at=_NOW,
        evidence_ref="evidence:failed",
    )
    partial = verify_recovery_postconditions(tuple(failed), telemetry_complete=True)
    assert partial.outcome is RecoveryVerificationOutcome.PARTIALLY_RECOVERED


class _Dispatcher:
    def __init__(self, *, fail_action: str | None = None) -> None:
        self.fail_action = fail_action
        self.calls: list[str] = []

    async def dispatch(self, action: RecoveryAction, *, idempotency_key: str) -> str | None:
        self.calls.append(action.action_id)
        if action.action_id == self.fail_action:
            return None
        return f"receipt:{idempotency_key}"


async def test_preauthorized_controller_dispatches_compensation_order() -> None:
    dispatcher = _Dispatcher()
    result = await PreauthorizedRecoveryController(dispatcher=dispatcher).execute(
        _plan(),
        target_ids=("resource-a",),
        now=_NOW,
    )
    assert result.succeeded
    assert dispatcher.calls == ["b", "a"]


async def test_preauthorized_controller_stops_on_missing_receipt() -> None:
    dispatcher = _Dispatcher(fail_action="b")
    result = await PreauthorizedRecoveryController(dispatcher=dispatcher).execute(
        _plan(),
        target_ids=("resource-a",),
        now=_NOW,
    )
    assert not result.succeeded
    assert result.failed_action_id == "b"
    assert dispatcher.calls == ["b"]
