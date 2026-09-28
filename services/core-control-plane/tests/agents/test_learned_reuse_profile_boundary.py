"""T1 learned-pattern reuse under the #1553 product-profile selection (#1541).

The default observation-first profile records a reusable T1 match as advisory evidence and stops
before any Action is built. Only the ``governed-execution`` product add-on, read once through
``RuntimeProductSelection``, reopens the existing T1 routing. No environment name, fork marker, or
executor or package flag selects it.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fdai.agents._framework.advisory_verdicts import (
    GOVERNED_EXECUTION_UNSELECTED_REASON as VERDICT_REASON,
)
from fdai.composition import default_container
from fdai.core.control_loop import ControlLoop, ControlLoopOutcome
from fdai.core.control_loop._learned_reuse import (
    GOVERNED_EXECUTION_UNSELECTED_REASON as LOOP_REASON,
)
from fdai.core.event_ingest import EventIngest
from fdai.core.executor import (
    DirectApiShadowExecutor,
    InProcessThorExecutionPort,
    MutationDependencyReadiness,
    ShadowExecutor,
    ToolCallShadowExecutor,
)
from fdai.core.tiers.t1_lightweight import LearnedAction, T1Tier
from fdai.core.tiers.t1_lightweight.testing import InMemoryPatternLibrary
from fdai.core.tiers.t1_lightweight.tier import SimilarityMatch, T1Decision, T1Outcome
from fdai.core.trust_router import RoutingDecision, RoutingTier
from fdai.runtime.bootstrap_plan import build_bootstrap_plan
from fdai.runtime.control_loop import _build_control_loop
from fdai.runtime.product_profile import RuntimeProductSelection
from fdai.shared.config import AppConfig
from fdai.shared.config.models import LlmMode
from fdai.shared.config.provider import EnvVarConfigProvider
from fdai.shared.contracts.models import Mode, Tier
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.product_profile import ProductAddOn, ProductProfile

from tests.agents.test_learning_advisory_boundary import _ConstantEmbedding
from tests.config.test_env_provider import VALID_ENV
from tests.core.test_control_loop_t1_wire import (
    _configure_t1_routing,
    _current_verification,
    _event_dict,
    _make_loop,
    _validator,
)
from tests.product_selection import governed_execution_selection

_ADVISORY = "governed_execution_unselected"
_LEARNED = LearnedAction(
    signature="learned-tag-owner",
    rule_id="r1",
    action_type="remediate.tag-add",
    params={},
    incident_id="incident-learned",
    success_rate=0.99,
    reuse_count=50,
)


def _verified_reuse(event_id: str) -> T1Decision:
    return T1Decision(
        outcome=T1Outcome.REUSED,
        event_id=event_id,
        threshold=0.8,
        best_match=SimilarityMatch(action=_LEARNED, score=0.95),
        current_reuse_verification=_current_verification(),
    )


def _loop(
    tmp_path: Path,
    *,
    selected: bool,
    t1: T1Decision | None,
) -> tuple[ControlLoop, AsyncMock]:
    engine = SimpleNamespace(evaluate=AsyncMock(return_value=t1))
    loop = _make_loop(
        t1_engine=engine,  # type: ignore[arg-type]
        audit=InMemoryStateStore(),
        tmp_path=tmp_path,
        governed_execution_selected=governed_execution_selection(selected),
    )
    _configure_t1_routing(loop)
    loop._risk_table = SimpleNamespace()  # type: ignore[assignment]  # noqa: SLF001
    loop._risk_gate = SimpleNamespace()  # type: ignore[assignment]  # noqa: SLF001
    risk = SimpleNamespace(
        is_auto=False,
        requires_hil=True,
        is_denied=False,
        decision="hil",
        gate=SimpleNamespace(effective_mode=Mode.SHADOW),
    )
    evaluate = AsyncMock(return_value=risk)
    loop._evaluate_and_audit = evaluate  # type: ignore[method-assign]  # noqa: SLF001
    return loop, evaluate


async def _fallback(loop: ControlLoop, key: str) -> object:
    event = EventIngest(validator=_validator()).ingest(_event_dict(key))
    assert event is not None
    return await loop._evaluate_fallback_tiers(  # noqa: SLF001 - real fallback routing
        event=event,
        decision=RoutingDecision(tier=RoutingTier.T1, resource_type="compute.vm.novel"),
        citing=(),
        cs_decision=None,
        event_id=str(event.event_id),
        correlation_id=str(event.event_id),
    )


async def test_default_verified_t1_reuse_builds_no_action(tmp_path: Path) -> None:
    loop, evaluate = _loop(tmp_path, selected=False, t1=_verified_reuse("evt-default"))
    loop._route_t1_reuse = AsyncMock()  # type: ignore[method-assign]  # noqa: SLF001
    loop._simulate_and_audit_dynamic = AsyncMock()  # type: ignore[method-assign]  # noqa: SLF001

    result = await _fallback(loop, "evt-default")

    assert result.outcome is ControlLoopOutcome.T1_REUSE_LOGGED  # type: ignore[attr-defined]
    assert result.decision == "abstain"  # type: ignore[attr-defined]
    assert result.reason == _ADVISORY  # type: ignore[attr-defined]
    assert result.citing_rule_ids == ("r1",)  # type: ignore[attr-defined]
    assert result.execution_results == ()  # type: ignore[attr-defined]
    loop._route_t1_reuse.assert_not_awaited()  # noqa: SLF001
    loop._simulate_and_audit_dynamic.assert_not_awaited()  # noqa: SLF001
    evaluate.assert_not_awaited()
    audit = loop._audit_store  # noqa: SLF001
    assert isinstance(audit, InMemoryStateStore)
    entries = [record["entry"] for record in audit.audit_entries]
    kinds = [entry["action_kind"] for entry in entries]
    assert kinds == ["control_loop.t1_evaluate", "control_loop.t1_reuse_advisory"]
    assert entries[-1]["reason"] == _ADVISORY
    assert entries[-1]["mode"] == "shadow"
    assert "action_type" not in entries[-1]


async def test_selected_verified_t1_reuse_still_meets_the_unified_risk_gate(
    tmp_path: Path,
) -> None:
    loop, evaluate = _loop(tmp_path, selected=True, t1=_verified_reuse("evt-selected"))

    result = await _fallback(loop, "evt-selected")

    # Positive control: the same decision proposes the learned action through the gate.
    assert result.outcome is ControlLoopOutcome.HIL  # type: ignore[attr-defined]
    assert result.reason == "t1_reuse_risk_gated"  # type: ignore[attr-defined]
    evaluate.assert_awaited_once()
    assert evaluate.await_args.kwargs["tier"] is Tier.T1
    assert evaluate.await_args.kwargs["action"].action_type == "remediate.tag-add"


@pytest.mark.parametrize("selected", [False, True])
async def test_real_t1_match_of_a_learned_pattern_is_advisory_by_default(
    tmp_path: Path,
    selected: bool,
) -> None:
    library = InMemoryPatternLibrary()
    library.add(vector=(1.0, 0.0), action=_LEARNED)
    tier = T1Tier(embedding_model=_ConstantEmbedding(), pattern_library=library)
    loop = _make_loop(
        t1_engine=tier,
        audit=InMemoryStateStore(),
        tmp_path=tmp_path,
        governed_execution_selected=governed_execution_selection(selected),
    )

    result = await loop.process(_event_dict(f"evt-real-{selected}"))

    assert result.outcome is ControlLoopOutcome.T1_REUSE_LOGGED
    assert result.t1_decision is not None
    assert result.t1_decision.outcome is T1Outcome.REUSED
    # Without current contextual verification the selected path also stops before an Action.
    assert result.reason == ("t1_reuse_requires_reverification" if selected else _ADVISORY)
    assert result.execution_results == ()


def test_judge_and_control_loop_record_one_advisory_reason() -> None:
    assert VERDICT_REASON == LOOP_REASON == _ADVISORY


def _config_from_env(**extra: str) -> AppConfig:
    return EnvVarConfigProvider(env={**VALID_ENV, **extra}).get()


def test_no_environment_name_fork_marker_or_package_flag_selects_the_add_on() -> None:
    # check-fork-runtime-independence.py keeps fork markers out of every runtime path, so a
    # fork marker cannot reach this selection and is not set here.
    incidental = {
        "RUNTIME_ENV": "prod",
        "FDAI_EXECUTION_VENUE": "deployed",
        "FDAI_PANTHEON_ENFORCE": "1",
        "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER": "1",
        "FDAI_WORKFLOW_EXECUTOR_IDENTITY": "executor",
        "FDAI_EXECUTION_BACKEND_REGISTRY_PATH": "/unused/registry.json",
    }
    config = _config_from_env(**incidental)

    assert RuntimeProductSelection.from_profile(config.product_profile).governed_execution is False
    plan = build_bootstrap_plan(
        llm_mode=LlmMode.LOCAL_FAKE,
        environment=incidental,
        product_profile=config.product_profile,
    )
    assert plan.isolated_executor_authority_cutover is False
    # Positive control: only the explicit product add-on list changes the selection.
    selected = _config_from_env(
        **incidental,
        FDAI_PRODUCT_ADDONS_JSON='["enterprise-identity-governance","governed-execution"]',
    )
    assert RuntimeProductSelection.from_profile(selected.product_profile).governed_execution


@pytest.mark.parametrize(
    ("add_ons", "expected"),
    [
        ((), False),
        ((ProductAddOn.NOTIFICATIONS,), False),
        ((ProductAddOn.ENTERPRISE_IDENTITY_GOVERNANCE,), False),
        ((ProductAddOn.ENTERPRISE_IDENTITY_GOVERNANCE, ProductAddOn.GOVERNED_EXECUTION), True),
    ],
)
def test_runtime_control_loop_builder_derives_the_product_selection(
    app_config: AppConfig,
    add_ons: tuple[ProductAddOn, ...],
    expected: bool,
) -> None:
    config = app_config.model_copy(update={"product_profile": ProductProfile(add_ons=add_ons)})
    readiness = MutationDependencyReadiness(
        saga_audit_durable=True,
        vidar_recovery_contracts=frozenset({"state_forward_only"}),
    )
    port = (
        {
            "thor_execution_port": InProcessThorExecutionPort(
                pr_native=MagicMock(spec=ShadowExecutor),
                direct_api=MagicMock(spec=DirectApiShadowExecutor),
                tool_call=MagicMock(spec=ToolCallShadowExecutor),
            )
        }
        if expected
        else {}
    )

    loop = _build_control_loop(
        default_container(config),
        http_client=None,
        mutation_dependency_readiness=readiness,
        **port,
    )

    assert loop.governed_execution_selected is expected
