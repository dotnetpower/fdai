"""Governed chaos adapter: success, denial, scope, ceiling, detection, and delegation."""

from __future__ import annotations

from typing import Any

import pytest
from fdai.core.chaos.factory import ScenarioFactory
from fdai.core.chaos.run_state import ChaosRunState
from fdai.core.chaos.scenario_catalog import CatalogEntry
from fdai.core.executor.lock import ResourceLockManager
from fdai.delivery.chaos import governed_bindings
from fdai.delivery.chaos.governed import GovernedChaosExecutionAdapter
from fdai.delivery.chaos.governed_bindings import (
    GOVERNED_CHAOS_ENTRY_POINT_GROUP,
    GOVERNED_CHAOS_ENTRY_POINT_NAME,
    ChaosApprovalEvidence,
    GovernedChaosBindings,
)
from fdai.delivery.chaos.tool import ChaosExperimentToolExecutor, GovernedChaosExecution
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.tool import (
    ToolCallOutcome,
    ToolPreconditionError,
    ToolPromotionError,
)

from tests.delivery.chaos.governed_doubles import (
    ENFORCED,
    ENTRY,
    NOW,
    RUN_ID,
    SCENARIO_ID,
    DistributedLock,
    EvidenceCollector,
    Injector,
    Planner,
    Registry,
    UnscopedInjector,
    ledger,
    recovery_plan,
    run_plan,
)
from tests.delivery.chaos.governed_fixtures import (
    audit_kinds,
    chaos_action_type,
    enforce_request,
    governed_fixture,
    run_state,
)


async def test_governed_adapter_runs_approved_enforce_through_runner() -> None:
    fixture = governed_fixture()

    receipt = await fixture.adapter.execute(enforce_request())

    assert receipt.outcome is ToolCallOutcome.SUCCEEDED
    assert receipt.receipt_ref == RUN_ID
    assert receipt.detail == "recovered:validated"
    assert fixture.injector.injected == ["pod-a"]
    assert fixture.injector.stopped == ["pod-a"]
    assert fixture.dispatcher.calls == ["restore"]
    assert await run_state(fixture) is ChaosRunState.RECOVERED
    kinds = audit_kinds(fixture)
    assert kinds.count("chaos.experiment.result") == 1
    assert kinds.count("chaos.run.transition") == 10


_CLOSURE_APPROVAL = ChaosApprovalEvidence(
    approval_ref="approval-1",
    approval_principal="Var",
    approver_ids=("approver-a",),
    initiator_id="initiator-a",
    intent="closure",
    run_id=RUN_ID,
)
_OTHER_RUN_APPROVAL = ChaosApprovalEvidence(
    approval_ref="approval-1",
    approval_principal="Var",
    approver_ids=("approver-a",),
    initiator_id="initiator-a",
    run_id="another-run",
)
_SELF_APPROVAL = ChaosApprovalEvidence(
    approval_ref="approval-1",
    approval_principal="Var",
    approver_ids=("initiator-a",),
    initiator_id="initiator-a",
)


@pytest.mark.parametrize(
    ("fixture_overrides", "request_overrides", "reason"),
    [
        pytest.param(
            {"planner": Planner(run_plan(graph_complete=False))},
            {},
            "graph_incomplete",
            id="readiness-evidence",
        ),
        pytest.param({"approval": None}, {}, "var_approval_required", id="missing-approval"),
        pytest.param(
            {"approval": _CLOSURE_APPROVAL},
            {},
            "var_approval_required",
            id="closure-intent-cannot-authorize-injection",
        ),
        pytest.param(
            {"approval": _OTHER_RUN_APPROVAL},
            {},
            "var_approval_required",
            id="approval-bound-to-another-run",
        ),
        pytest.param({"approval": None}, {}, "approval_quorum_not_met", id="missing-quorum"),
        pytest.param(
            {"approval": _SELF_APPROVAL}, {}, "self_approval_forbidden", id="self-approval"
        ),
        pytest.param(
            {}, {"approval_ref": "approval-forged"}, "var_approval_required", id="claim-mismatch"
        ),
        pytest.param(
            {"planner": Planner(run_plan(production_or_stateful=True))},
            {},
            "approval_quorum_not_met",
            id="stateful-quorum",
        ),
        pytest.param({"eligible": False}, {}, "scenario_not_promoted", id="scenario-shadow"),
        pytest.param(
            {"enforced": ENFORCED - {"tool.run-chaos-experiment"}},
            {},
            "action_type_not_promoted",
            id="chaos-action-type-shadow",
        ),
        pytest.param(
            {"enforced": ENFORCED - {"ops.undo-restore"}},
            {},
            "action_type_not_promoted",
            id="compensation-action-type-shadow",
        ),
        pytest.param({}, {"time_box": False}, "stop_conditions_unavailable", id="no-time-box"),
        pytest.param(
            {"planner": Planner(run_plan(recovery_plan=recovery_plan(expires_at=NOW)))},
            {},
            "recovery_not_ready",
            id="expired-recovery-plan",
        ),
        pytest.param({}, {"tier": "t1"}, "autonomy_ceiling_not_enforce", id="t1-shadow-only"),
        pytest.param({}, {"tier": "t2"}, "autonomy_ceiling_not_enforce", id="t2-shadow-only"),
        pytest.param({}, {"tier": None}, "autonomy_ceiling_not_enforce", id="tier-missing"),
        pytest.param({}, {"tier": "t9"}, "autonomy_ceiling_not_enforce", id="tier-unknown"),
        pytest.param(
            {"injector": Injector(scope=("/subscriptions/0/vm-x",))},
            {},
            "mutation_targets_unapproved",
            id="mutates-unapproved-resource",
        ),
        pytest.param(
            {"injector": UnscopedInjector()},
            {},
            "mutation_targets_unapproved",
            id="mutation-scope-undeclared",
        ),
    ],
)
async def test_governed_adapter_denies_ineligible_run_before_injection(
    fixture_overrides: dict[str, Any],
    request_overrides: dict[str, Any],
    reason: str,
) -> None:
    fixture = governed_fixture(**fixture_overrides)

    receipt = await fixture.adapter.execute(enforce_request(**request_overrides))

    assert receipt.outcome is ToolCallOutcome.PRECONDITION_FAILED
    assert receipt.detail is not None and reason in receipt.detail.split(":", 1)[1].split(",")
    assert fixture.injector.injected == []
    assert fixture.dispatcher.calls == []
    assert await run_state(fixture) is ChaosRunState.DENIED


@pytest.mark.parametrize(
    "planner",
    [
        pytest.param(Planner(None), id="plan-missing"),
        pytest.param(Planner(run_plan(), raises=True), id="planner-error"),
    ],
)
async def test_governed_adapter_denies_when_run_plan_is_unavailable(planner: Planner) -> None:
    fixture = governed_fixture(planner=planner)

    receipt = await fixture.adapter.execute(enforce_request())

    assert receipt.outcome is ToolCallOutcome.PRECONDITION_FAILED
    assert receipt.detail == "denied:run_plan_unavailable"
    assert fixture.injector.injected == []
    assert fixture.verifier.calls == 0
    assert await run_state(fixture) is ChaosRunState.DENIED


@pytest.mark.parametrize(
    ("request_overrides", "error"),
    [
        ({"mode": Mode.SHADOW}, ToolPromotionError),
        ({"action_type_name": "tool.run-investigation"}, ToolPreconditionError),
        ({"targets": ("pod-a", "pod-b")}, ToolPreconditionError),
    ],
)
async def test_governed_adapter_refuses_malformed_requests_before_state(
    request_overrides: dict[str, Any],
    error: type[Exception],
) -> None:
    fixture = governed_fixture()

    with pytest.raises(error):
        await fixture.adapter.execute(enforce_request(**request_overrides))

    assert fixture.planner.calls == 0
    assert await run_state(fixture) is None
    assert fixture.injector.injected == []


def test_governed_bindings_and_adapter_fail_closed_without_collaborators() -> None:
    fixture = governed_fixture()
    with pytest.raises(ValueError, match="planner"):
        GovernedChaosBindings(
            state_store=fixture.state_store,
            action_registry=Registry(ENFORCED),
            scenario_ledger=ledger(),
            approval_verifier=fixture.verifier,
            planner=None,  # type: ignore[arg-type]
            recovery_dispatcher=fixture.dispatcher,
            evidence_collector=EvidenceCollector(),
            target_lock=DistributedLock(),
        )
    with pytest.raises(ValueError, match="distributed target lock"):
        GovernedChaosBindings(
            state_store=fixture.state_store,
            action_registry=Registry(ENFORCED),
            scenario_ledger=ledger(),
            approval_verifier=fixture.verifier,
            planner=fixture.planner,
            recovery_dispatcher=fixture.dispatcher,
            evidence_collector=EvidenceCollector(),
            target_lock=ResourceLockManager(),
        )
    with pytest.raises(TypeError, match="GovernedChaosBindings"):
        GovernedChaosExecutionAdapter(
            entries=(ENTRY,),
            promoted_ids=frozenset({SCENARIO_ID}),
            factory=ScenarioFactory(),
            context={},
            bindings=None,  # type: ignore[arg-type]
            action_type=chaos_action_type(),
        )
    with pytest.raises(ValueError, match="ActionType"):
        GovernedChaosExecutionAdapter(
            entries=(ENTRY,),
            promoted_ids=frozenset({SCENARIO_ID}),
            factory=ScenarioFactory(),
            context={},
            bindings=fixture.adapter._bindings,  # noqa: SLF001 - reuse composed fakes
            action_type=chaos_action_type().model_copy(update={"name": "tool.other"}),
        )


@pytest.mark.parametrize(
    ("detects", "experiment_outcome", "passed"),
    [
        pytest.param(True, "validated", True, id="validated"),
        pytest.param(False, "not_detected", False, id="detection-gap"),
    ],
)
async def test_governed_outcome_separates_recovery_from_detection(
    detects: bool,
    experiment_outcome: str,
    passed: bool,
) -> None:
    fixture = governed_fixture(detects=detects)

    first = await fixture.adapter.run(enforce_request())
    replay = await fixture.adapter.run(enforce_request())

    assert first.receipt.outcome is ToolCallOutcome.SUCCEEDED
    assert first.receipt.detail == f"recovered:{experiment_outcome}"
    for outcome in (first, replay):
        assert outcome.recovered is True
        assert outcome.detected is detects
        assert outcome.experiment_outcome == experiment_outcome
        assert outcome.passed is passed
    assert replay.receipt.outcome is ToolCallOutcome.ALREADY_APPLIED
    assert fixture.injector.injected == ["pod-a"]


async def test_chaos_tool_enforce_delegates_to_governed_adapter() -> None:
    fixture = governed_fixture()
    execution: GovernedChaosExecution = fixture.adapter
    tool = ChaosExperimentToolExecutor(
        entries=(ENTRY,),
        promoted_ids=frozenset({SCENARIO_ID}),
        factory=ScenarioFactory(),
        governed_execution=execution,
    )

    receipt = await tool.execute(enforce_request())

    assert receipt.outcome is ToolCallOutcome.SUCCEEDED
    assert fixture.injector.injected == ["pod-a"]


class _EntryPoint:
    def __init__(self, name: str, factory: object) -> None:
        self.name = name
        self._factory = factory

    def load(self) -> object:
        return self._factory


@pytest.mark.parametrize(
    ("installed", "outcome"),
    [
        pytest.param((), None, id="unbound"),
        pytest.param(("valid",), "bindings", id="single-provider"),
        pytest.param(("valid", "valid"), RuntimeError, id="ambiguous-providers"),
        pytest.param(("invalid",), RuntimeError, id="invalid-bindings"),
        pytest.param(("not-callable",), RuntimeError, id="not-callable"),
    ],
)
def test_governed_bindings_loader_requires_exactly_one_valid_provider(
    installed: tuple[str, ...],
    outcome: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bindings = governed_fixture().adapter._bindings  # noqa: SLF001 - reuse composed fakes
    factories: dict[str, object] = {
        "valid": lambda *, environment: bindings,
        "invalid": lambda *, environment: object(),
        "not-callable": "not-callable",
    }
    points = tuple(
        _EntryPoint(GOVERNED_CHAOS_ENTRY_POINT_NAME, factories[kind]) for kind in installed
    )
    points += (_EntryPoint("other-provider", factories["invalid"]),)
    seen: list[str] = []

    def _entry_points(*, group: str) -> tuple[_EntryPoint, ...]:
        seen.append(group)
        return points

    monkeypatch.setattr(governed_bindings, "entry_points", _entry_points)

    if outcome is RuntimeError:
        with pytest.raises(RuntimeError):
            governed_bindings.load_governed_chaos_bindings({})
    else:
        loaded = governed_bindings.load_governed_chaos_bindings({})
        assert (loaded is bindings) if outcome == "bindings" else loaded is None
    assert seen == [GOVERNED_CHAOS_ENTRY_POINT_GROUP]


_TWO_TARGET_ENTRY = CatalogEntry(
    id="chaos.test.pod-pair",
    source_path=ENTRY.source_path,
    spec={**ENTRY.spec, "id": "chaos.test.pod-pair", "blast_radius_cap": 2},
)


@pytest.mark.parametrize(
    ("scope", "outcome", "injected"),
    [
        pytest.param(("pod-a",), ToolCallOutcome.PRECONDITION_FAILED, [], id="surplus-target"),
        pytest.param(None, ToolCallOutcome.SUCCEEDED, ["pod-a", "pod-b"], id="one-per-target"),
    ],
)
async def test_governed_adapter_injects_once_per_declared_target(
    scope: tuple[str, ...] | None,
    outcome: ToolCallOutcome,
    injected: list[str],
) -> None:
    fixture = governed_fixture(injector=Injector(scope=scope), entry=_TWO_TARGET_ENTRY)

    receipt = await fixture.adapter.execute(
        enforce_request(scenario_id=_TWO_TARGET_ENTRY.id, targets=("pod-a", "pod-b"))
    )

    assert receipt.outcome is outcome
    if outcome is ToolCallOutcome.PRECONDITION_FAILED:
        assert receipt.detail is not None and "mutation_targets_unapproved" in receipt.detail
    assert fixture.injector.injected == injected
