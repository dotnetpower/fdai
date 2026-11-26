"""No-network composition checks using canonical catalogs and the normal Workflow builder.

In-memory stores and generated subjects are explicit unit fixtures, not approval,
promotion or production evidence. These tests require no Azure, model or database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from fdai.core.detection.alert_noise.execution import ALERT_ACTIONS
from fdai.core.detection.alert_noise.workflow import ALERT_WORKFLOWS, AlertWorkflowCoordinator
from fdai.core.risk_gate import ActionPromotionRegistry
from fdai.core.workflow import StateStoreAutomationHoldLedger, StateStoreWorkflowOutcomeLedger
from fdai.delivery.alert_noise_pr import StateStoreAlertPlanReader
from fdai.delivery.alert_noise_workflow import (
    MappedAlertRequesterReader,
    StateStoreAlertActionBinder,
)
from fdai.delivery.persistence.state_store_action_promotion import StateStoreActionPromotionRegistry
from fdai.delivery.persistence.state_store_decision_evidence import (
    StateStoreDecisionEvidenceAdmissionProvider,
)
from fdai.delivery.persistence.workflow_approval import StateStoreWorkflowApprovalProvider
from fdai.rule_catalog.schema.action_type import load_action_type_from_mapping
from fdai.rule_catalog.schema.workflow import load_workflow_from_mapping
from fdai.runtime.alert_noise_control import build_alert_workflow_bindings, registered_alert_actions
from fdai.runtime.control_loop_support import build_workflow_coordinator
from fdai.runtime.workflow_action_dispatch import EventBusWorkflowActionDispatcher
from fdai.shared.contracts.models import (
    OntologyActionType,
    OntologyDeclarationKind,
    OntologyRelease,
    Workflow,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.runtime.test_alert_noise_config import _SUBJECT, _environment, _requester

_ROOT = Path(__file__).resolve().parents[4]
_NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


@pytest.fixture
def alert_catalog() -> tuple[dict[str, OntologyActionType], tuple[Workflow, ...], OntologyRelease]:
    """Read only the seven owning catalog declarations, not the whole application."""
    schema = PackageResourceSchemaRegistry()
    actions = {
        name: load_action_type_from_mapping(
            yaml.safe_load((_ROOT / "rule-catalog" / "action-types" / f"{name}.yaml").read_text()),
            schema_registry=schema,
        )
        for name in sorted(ALERT_ACTIONS)
    }
    workflows = tuple(
        load_workflow_from_mapping(
            yaml.safe_load((_ROOT / "rule-catalog" / "workflows" / f"{name}.yaml").read_text()),
            schema_registry=schema,
            action_type_names=set(actions),
        )
        for name, _step in ALERT_WORKFLOWS.values()
    )
    return actions, workflows, build_ontology_release(action_types=tuple(actions.values()))


@pytest.fixture
def workflow_parts(
    alert_catalog: tuple[dict[str, OntologyActionType], tuple[Workflow, ...], OntologyRelease],
    monkeypatch: pytest.MonkeyPatch,
) -> SimpleNamespace:
    environment = _environment(writers=False, scope_count=2)
    monkeypatch.setenv("FDAI_WORKFLOW_SHADOW", "1")
    monkeypatch.setenv("FDAI_SOURCE_REVISION", environment["FDAI_SOURCE_REVISION"])
    actions, workflows, release = alert_catalog
    store, processes, bus = InMemoryStateStore(), InMemoryProcessRuntimeStore(), InMemoryEventBus()

    def clock() -> datetime:
        return _NOW

    admissions = StateStoreDecisionEvidenceAdmissionProvider(store=store, clock=clock)
    registry = StateStoreActionPromotionRegistry(store=store)
    outcomes = StateStoreWorkflowOutcomeLedger(store, decision_evidence_provider=admissions)
    holds = StateStoreAutomationHoldLedger(store)
    dispatcher = EventBusWorkflowActionDispatcher(event_bus=bus, topic="test:alert-workflow")
    trigger = build_workflow_coordinator(
        catalog_root=_ROOT / "rule-catalog",
        workflows=workflows,
        action_types_by_name=actions,
        audit_store=store,
        process_store=processes,
        outcome_verifier=outcomes,
        decision_evidence_provider=admissions,
        action_dispatcher=dispatcher,
        automation_holds=holds,
    )
    assert trigger is not None
    options = {
        "workflow_coordinator": trigger,
        "workflows": workflows,
        "action_types_by_name": actions,
        "ontology_release": release,
        "process_store": processes,
        "audit_store": store,
        "promotion_registry": registry,
        "decision_evidence_provider": admissions,
        "environment": environment,
        "clock": clock,
    }
    return SimpleNamespace(
        options=options,
        trigger=trigger,
        store=store,
        processes=processes,
        admissions=admissions,
        registry=registry,
        outcomes=outcomes,
        holds=holds,
        dispatcher=dispatcher,
        workflows=workflows,
        actions=actions,
        release=release,
        clock=clock,
    )


def _unbound_options() -> dict[str, Any]:
    """Absence must not require an optional orchestrator, publisher or verifier."""
    return {
        "workflow_coordinator": None,
        "workflows": (),
        "action_types_by_name": {},
        "ontology_release": build_ontology_release(),
        "process_store": InMemoryProcessRuntimeStore(),
        "audit_store": InMemoryStateStore(),
        "promotion_registry": ActionPromotionRegistry(),
        "decision_evidence_provider": None,
        "clock": lambda: _NOW,
    }


def test_unconfigured_alert_workflows_and_binder_remain_none() -> None:
    result = build_alert_workflow_bindings(**_unbound_options(), environment={})
    assert result.workflows is result.binder is None


def test_missing_source_does_not_require_optional_runtime_or_invent_provenance() -> None:
    result = build_alert_workflow_bindings(
        **_unbound_options(), environment=_environment(source=False)
    )
    assert result.workflows is result.binder is None


def test_explicit_partial_startup_is_not_silently_disabled() -> None:
    with pytest.raises(ValueError, match="requires both"):
        build_alert_workflow_bindings(
            **_unbound_options(),
            environment={"FDAI_ALERT_NOISE_WRITER_BINDINGS_JSON": "[]"},
        )


def test_complete_opt_in_requires_the_existing_normal_coordinator() -> None:
    with pytest.raises(RuntimeError, match="canonical Workflow coordinator"):
        build_alert_workflow_bindings(**_unbound_options(), environment=_environment(writers=False))


def test_public_runtime_is_read_only_and_preserves_every_normal_dependency(
    workflow_parts: SimpleNamespace,
) -> None:
    h = workflow_parts
    runtime = h.trigger.runtime
    assert runtime is h.trigger._orchestrator
    assert runtime._process_store is h.processes
    assert runtime._outcome_verifier is h.outcomes
    assert runtime._action_dispatcher is h.dispatcher
    assert runtime._automation_holds is h.holds
    assert runtime._approval_decision_evidence_provider is h.admissions
    assert isinstance(runtime._approval_provider, StateStoreWorkflowApprovalProvider)
    assert runtime._recovery_coordinator is not None
    with pytest.raises(AttributeError):
        h.trigger.runtime = runtime


async def test_workflow_and_binder_reuse_normal_runtime_store_registry_and_de(
    workflow_parts: SimpleNamespace,
) -> None:
    h = workflow_parts
    result = build_alert_workflow_bindings(**h.options)
    assert isinstance(result.workflows, AlertWorkflowCoordinator)
    assert isinstance(result.binder, StateStoreAlertActionBinder)
    workflow, binder = result.workflows, result.binder
    assert workflow._orchestrator is h.trigger.runtime
    assert workflow._processes is h.processes and workflow._store is h.store
    assert workflow._registry is h.registry and workflow._clock is h.clock
    assert workflow._promotions._store is h.store
    assert workflow._promotions._admissions is h.admissions
    assert (
        workflow._promotions._source_revision == workflow._source_revision == "commit:" + "a" * 40
    )
    assert isinstance(workflow._plans, StateStoreAlertPlanReader)
    assert workflow._plans._store is h.store
    assert isinstance(workflow._requesters, MappedAlertRequesterReader)
    for scope in ("scope:example-0", "scope:example-1"):
        assert (
            await workflow._requesters.resolve(requester_ref=_requester(_SUBJECT, scope))
            == _SUBJECT
        )
    assert await workflow._requesters.resolve(requester_ref="principal:" + "f" * 64) is None
    assert binder._workflows is workflow and binder._store is h.store and binder._clock is h.clock
    assert binder._registered == registered_alert_actions(h.release)
    assert h.store.audit_entries == ()


def test_missing_independent_de_is_preserved_without_requiring_a_writer(
    workflow_parts: SimpleNamespace,
) -> None:
    result = build_alert_workflow_bindings(
        **{**workflow_parts.options, "decision_evidence_provider": None}
    )
    assert result.workflows is not None and result.binder is not None
    assert result.workflows._promotions._admissions is None


def test_registered_actions_use_the_exact_ontology_release(workflow_parts: SimpleNamespace) -> None:
    h = workflow_parts
    refs = registered_alert_actions(h.release)
    assert set(refs) == ALERT_ACTIONS
    for name, ref in refs.items():
        assert ref == h.release.type_ref(OntologyDeclarationKind.ACTION, name)
        assert ref.catalog_digest == h.release.digest
    assert registered_alert_actions(build_ontology_release()) == {}


def test_partial_catalog_does_not_fabricate_action_or_workflow_references(
    workflow_parts: SimpleNamespace,
) -> None:
    h = workflow_parts
    for changed in (
        {"ontology_release": build_ontology_release()},
        {"workflows": h.workflows[:1]},
        {"action_types_by_name": {}},
    ):
        with pytest.raises(ValueError, match="exact complete alert catalog"):
            build_alert_workflow_bindings(**{**h.options, **changed})


def test_binding_a_second_facade_does_not_replace_normal_approvals_or_recovery(
    workflow_parts: SimpleNamespace,
) -> None:
    h = workflow_parts
    runtime = h.trigger.runtime
    approvals, recovery = runtime._approval_provider, runtime._recovery_coordinator
    first = build_alert_workflow_bindings(**h.options)
    second = build_alert_workflow_bindings(**h.options)
    assert first.workflows is not None and second.workflows is not None
    assert first.workflows._orchestrator is second.workflows._orchestrator is runtime
    assert runtime._approval_provider is approvals and runtime._recovery_coordinator is recovery
    assert h.store.audit_entries == ()
