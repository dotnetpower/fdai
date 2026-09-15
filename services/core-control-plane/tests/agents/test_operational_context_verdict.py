from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.agents.forseti import Forseti
from fdai.core.operational_context import OperationalContextMaterializer
from fdai.core.operational_context.test_context import TestContextClaim as ContextClaim
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

REPO_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 7, 31, tzinfo=UTC)


async def test_operator_context_command_uses_var_mimir_and_saga_topics() -> None:
    from fdai.agents._framework.bus import InMemoryBus
    from fdai.agents._framework.registry import load_pantheon
    from fdai.agents.huginn import Huginn
    from fdai.agents.mimir import Mimir
    from fdai.agents.saga import Saga
    from fdai.agents.var import Var
    from fdai.core.operational_context.test_context_commands import TestContextCommandHandler
    from fdai.core.operational_context.test_context_lifecycle import GovernedTestContextStore
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    from tests.core.operational_context.test_test_context import NOW as INSTANT
    from tests.core.operational_context.test_test_context import _claim, _TransitionAdmission

    contexts = GovernedTestContextStore(
        store=InMemoryStateStore(), admission=_TransitionAdmission(), clock=lambda: INSTANT
    )
    handler = TestContextCommandHandler(
        contexts=contexts, admission=_TransitionAdmission(), clock=lambda: INSTANT
    )
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    huginn, mimir, var, saga = Huginn(), Mimir(), Var(), Saga()
    mimir.bind_test_context_commands(handler)
    var.bind_test_context_commands(handler)
    for agent in (huginn, mimir, var, saga):
        agent.bind_bus(bus)
        for topic in agent.spec.subscribes:
            bus.subscribe(topic, agent.spec.name, agent.on_typed_message)
    claim = _claim()
    request = {
        "operation": "propose",
        "context_id": claim.context_id,
        "access_scope_digest": claim.access_scope_digest,
        "target_ref": claim.target_ref,
        "signal_code": claim.signal_code,
        "expected_revision": 0,
        "policy_revision": claim.policy_revision,
        "source_ref": claim.source_ref,
        "semantic_receipt": "sha256:" + "a" * 64,
        "expected_min": 60,
        "expected_max": 90,
        "effective_from": INSTANT.isoformat(),
        "effective_to": (INSTANT + timedelta(hours=1)).isoformat(),
    }

    async def send(request, actor, role, key):
        await huginn.ingest(
            {
                "id": key,
                "event_id": key,
                "idempotency_key": key,
                "correlation_id": key,
                "source": "operator-context-command",
                "event_type": "test_context.command.v1",
                "attributes": {
                    "request": request,
                    "actor_id": actor,
                    "actor_roles": [role],
                    "idempotency_key": key,
                    "requested_at": INSTANT.isoformat(),
                },
            }
        )

    await send(request, "operator-one", "Contributor", "propose-example")
    review = {
        key: value
        for key, value in request.items()
        if key not in {"expected_min", "expected_max", "effective_from", "effective_to"}
    }
    review.update(operation="review", expected_revision=1)
    await send(review, "reviewer-two", "Approver", "review-example")
    assert len(bus.messages_on("object.approval")) == 1
    assert [message.payload["state"] for message in bus.messages_on("object.policy")] == [
        "proposed",
        "reviewed",
    ]
    assert saga.audit_chain.entries_for_correlation("review-example")
    current = await contexts.read(
        target_ref=claim.target_ref, access_scope_digest=claim.access_scope_digest, at=INSTANT
    )
    assert current is not None and current.state == "reviewed"
    from fdai_service_contracts.test_context import TestContextApplication, TestContextCommand

    application = TestContextApplication.model_validate(
        bus.messages_on("object.policy")[-1].payload["application"]
    )
    command = TestContextCommand.model_validate(
        bus.messages_on("object.approval")[-1].payload["command"]
    )
    assert application.matches(command)
    assert application.context_digest == current.digest
    audited = [
        entry.payload
        for entry in bus.messages_on("object.audit-entry")
        if entry.payload.get("kind") == "test_context_application"
    ]
    assert audited[-1]["application"] == application.model_dump(mode="json")
    assert audited[-1]["producer_principal"] == "Saga"
    from unittest.mock import AsyncMock

    from fdai.runtime.test_context_projection import TestContextApplicationPublisher
    from fdai_service_contracts.semantic_turn import LOGICAL_TOPIC_FIELD
    from fdai_service_contracts.test_context import TEST_CONTEXT_RESULT_TOPIC

    provider = AsyncMock()
    relay = TestContextApplicationPublisher(provider, physical_topic="fdai.pantheon.objects")
    await relay.handle("object.audit-entry", audited[-1])
    provider.publish.assert_awaited_once_with(
        "fdai.pantheon.objects",
        application.command_digest,
        {**application.model_dump(mode="json"), LOGICAL_TOPIC_FIELD: TEST_CONTEXT_RESULT_TOPIC},
    )
    with pytest.raises(ValueError, match="Saga-owned"):
        await relay.handle("object.audit-entry", {**audited[-1], "producer_principal": "Mimir"})
    assert provider.publish.await_count == 1
    revoke = {**review, "operation": "revoke", "expected_revision": 2}
    await send(revoke, "reviewer-two", "Approver", "revoke-example")
    replay = await handler.transition(command.model_dump(mode="json"), reviewed_by_var=True)
    assert replay["application"] == application.model_dump(mode="json")
    await handler.review(command.model_dump(mode="json"))
    latest = await contexts.read(
        target_ref=claim.target_ref, access_scope_digest=claim.access_scope_digest, at=INSTANT
    )
    assert latest is not None and latest.state == "revoked" and latest.revision == 3
    for field_name, value in {
        "actor_id": "other",
        "target_ref": "other",
        "policy_revision": "other",
        "context_id": "other",
        "access_scope_digest": "f" * 64,
        "request_key": "other",
        "command_digest": "sha256:" + "f" * 64,
        "revision": 5,
        "state": "revoked",
    }.items():
        assert not application.model_copy(update={field_name: value}).matches(command)


@pytest.mark.parametrize("malformed_request", [None, [], "review", 1])
async def test_malformed_context_request_fails_schema_validation(malformed_request) -> None:
    from fdai.agents.mimir import Mimir
    from fdai.agents.var import Var
    from pydantic import ValidationError

    for agent in (Mimir(), Var()):
        with pytest.raises(ValidationError):
            await agent.on_typed_message(
                "object.event",
                {
                    "producer_principal": "Huginn",
                    "event_type": "test_context.command.v1",
                    "attributes": {"request": malformed_request},
                },
            )


async def test_context_governance_never_enters_signal_or_execution_approval_handlers() -> None:
    from unittest.mock import AsyncMock

    from fdai.agents.heimdall import Heimdall
    from fdai.agents.thor import Thor

    observer, executor = Heimdall(), Thor()
    observer._maybe_emit_anomaly = AsyncMock()
    executor._handle_approval = AsyncMock()
    await observer.on_typed_message(
        "object.event",
        {
            "event_type": "test_context.command.v1",
            "correlation_id": "existing-action",
        },
    )
    await executor.on_typed_message(
        "object.approval",
        {
            "kind": "test_context_review",
            "state": "approved",
            "correlation_id": "existing-action",
            "producer_principal": "Var",
        },
    )
    observer._maybe_emit_anomaly.assert_not_awaited()
    executor._handle_approval.assert_not_awaited()


@pytest.mark.parametrize(
    "change", ["unchanged", "revoked", "missing", "expired", "unbound", "source-error"]
)
@pytest.mark.parametrize("shadow", [False, True])
async def test_thor_rechecks_context_after_queueing_before_executor(change, shadow):
    from dataclasses import replace
    from unittest.mock import AsyncMock

    from fdai.agents.thor import ActionRun, ActionRunState, Thor
    from fdai.core.operational_context.test_context_dispatch import (
        TestContextDispatchBinding,
        TestContextDispatchGuard,
    )
    from fdai.shared.contracts.models import Autonomy

    from tests.core.operational_context.test_test_context import NOW as INSTANT
    from tests.core.operational_context.test_test_context import _claim, _TransitionAdmission

    claim = _claim()
    source = AsyncMock()
    source.read.return_value = (
        replace(claim, state="revoked", revision=claim.revision + 1)
        if change == "revoked"
        else None
        if change == "missing"
        else claim
    )
    if change == "source-error":
        source.read.side_effect = OSError("synthetic source error")
    now = claim.effective_to if change == "expired" else INSTANT
    binding = TestContextDispatchBinding(
        target_ref=claim.target_ref,
        access_scope_digest=claim.access_scope_digest,
        signal_code=claim.signal_code,
        context_digest=claim.digest,
    )
    invoked = AsyncMock(return_value=True)
    thor = Thor(executor=invoked, clock=lambda: now)
    if change != "unbound":
        thor.bind_test_context_dispatch_guard(
            TestContextDispatchGuard(
                source=source, admission=_TransitionAdmission(), clock=lambda: now
            )
        )
    original = ActionRun(
        correlation_id="queued-context-action",
        action_type="ops.restart-service",
        resource_id=claim.target_ref,
        state=ActionRunState.VERDICTED,
        verdict="auto",
        resolved_autonomy_ceiling=Autonomy.ENFORCE_AUTO,
        shadow_mode=shadow,
        test_context_guard=binding,
    )
    restored = ActionRun.from_dict(original.to_dict())
    assert restored.test_context_guard == binding
    await thor._execute(restored)
    if change == "unchanged":
        if shadow:
            invoked.assert_not_awaited()
            assert restored.outcome == "shadow_success"
        else:
            invoked.assert_awaited_once()
    else:
        invoked.assert_not_awaited()
        assert restored.state is ActionRunState.DENY_DROPPED
        assert restored.outcome == "test_context_changed_before_dispatch"


@pytest.mark.parametrize(
    "failure",
    [
        "no-admission",
        "propose-review",
        "missing",
        "self",
        "source",
        "wrong-owner",
        "stale",
        "scope",
    ],
)
async def test_context_command_rejections_never_mutate_policy(failure):
    from dataclasses import replace
    from unittest.mock import AsyncMock

    from fdai.core.operational_context.test_context_commands import TestContextCommandHandler
    from fdai.core.operational_context.test_context_lifecycle import GovernedTestContextStore
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    from tests.core.operational_context.test_test_context import NOW as INSTANT
    from tests.core.operational_context.test_test_context import _claim, _TransitionAdmission

    store = InMemoryStateStore()
    contexts = GovernedTestContextStore(
        store=store, admission=_TransitionAdmission(), clock=lambda: INSTANT
    )
    claim = replace(_claim(), state="proposed", reviewed_by="")
    await contexts.record_transition(claim, expected_revision=0, now=INSTANT)
    unavailable = AsyncMock()
    unavailable.admit.return_value = None
    handler = TestContextCommandHandler(
        contexts=contexts,
        admission=unavailable if failure == "no-admission" else _TransitionAdmission(),
        clock=lambda: INSTANT,
    )
    request = {
        "operation": "review",
        "context_id": claim.context_id,
        "access_scope_digest": claim.access_scope_digest,
        "target_ref": claim.target_ref,
        "signal_code": claim.signal_code,
        "expected_revision": 1,
        "policy_revision": claim.policy_revision,
        "source_ref": claim.source_ref,
        "semantic_receipt": "sha256:" + "a" * 64,
    }
    command = {
        "request": request,
        "actor_id": "reviewer-two",
        "actor_roles": ["Approver"],
        "idempotency_key": "review-example",
        "requested_at": INSTANT.isoformat(),
    }
    if failure == "propose-review":
        request.update(
            operation="propose",
            expected_revision=0,
            expected_min=60,
            expected_max=90,
            effective_from=INSTANT.isoformat(),
            effective_to=(INSTANT + timedelta(hours=1)).isoformat(),
        )
    elif failure == "missing":
        request["context_id"] = "missing-context"
    elif failure == "self":
        command["actor_id"] = claim.requested_by
    elif failure == "source":
        request["source_ref"] = "turn:changed"
    elif failure == "stale":
        request["expected_revision"] = 5
    elif failure == "scope":
        request["access_scope_digest"] = "f" * 64
    with pytest.raises((ValueError, PermissionError)):
        if failure in {"source", "wrong-owner"}:
            await handler.transition(command, reviewed_by_var=failure != "wrong-owner")
        else:
            await handler.review(command)
    assert (
        await contexts.read_revision(
            context_id=claim.context_id,
            target_ref=claim.target_ref,
            access_scope_digest=claim.access_scope_digest,
        )
        == claim
    )
    assert await store.verify_chain()


async def test_reviewed_expected_test_signal_cannot_trigger_automatic_remediation() -> None:
    now = NOW
    claim = ContextClaim(
        context_id="test-example",
        revision=1,
        access_scope_digest="a" * 64,
        target_ref="resource-example",
        signal_code="cpu_percent",
        expected_min=60,
        expected_max=90,
        effective_from=now - timedelta(minutes=5),
        effective_to=now + timedelta(hours=1),
        recorded_at=now - timedelta(minutes=4),
        source_ref="operator-turn:example",
        requested_by="operator-one",
        reviewed_by="reviewer-two",
        policy_revision="policy:example:1",
        state="reviewed",
    )

    class _Source:
        async def read(self, **_kwargs):
            return claim

    class _Admission:
        async def admit(self, **values):
            return DecisionEvidenceAdmission(
                receipt_digest="sha256:" + "b" * 64,
                verification_bundle_digest="sha256:" + "c" * 64,
                verified_at=now,
                valid_until=claim.effective_to,
                **values,
            )

    forseti = Forseti(
        test_context_source=_Source(),
        test_context_admission=_Admission(),
        test_context_clock=lambda: now,
    )
    event = {
        "event_type": "restart_needed",
        "correlation_id": "test-context-example",
        "resource_id": "resource-example",
        "access_scope_digest": "a" * 64,
        "detected_at": now.isoformat(),
        "metric": "cpu_percent",
        "observed_value": 80.0,
        "service_impact": "none",
        "protected_signal": False,
    }
    verdict = await forseti.judge(event)
    assert verdict is not None
    assert verdict["risk_verdict"] == "deny"
    assert verdict["reason"] == "expected_test_signal_no_remediation"
    assert verdict["test_context"]["observed_fact"] == "observed"
    assert verdict["test_context"]["learning_eligibility"] == "test_cohort"
    assert verdict["resolved_autonomy_ceiling"] == "shadow_only"
    unexpected = await forseti.judge({**event, "observed_value": 99.0})
    assert unexpected is not None
    assert unexpected["test_context"]["response_disposition"] == "investigate"
    protected = await forseti.judge({**event, "protected_signal": True})
    assert protected is not None
    assert protected["test_context"]["response_disposition"] == "investigate"
    denied = await forseti.judge({**event, "action_type": "remediate.delete-storage"})
    assert denied is not None
    assert denied["risk_verdict"] == "deny"
    assert denied["reason"] == "risk_deny"
    unverified = await Forseti(test_context_source=_Source(), test_context_clock=lambda: now).judge(
        event
    )
    assert unverified is not None
    assert unverified["risk_verdict"] == "hil"
    assert unverified["resolved_autonomy_ceiling"] == "shadow_only"

    class _ClaimOnlyAdmission(_Admission):
        async def admit(self, **values):
            if values["purpose_id"] == "operational-test-observation":
                return None
            return await super().admit(**values)

    claim_only = await Forseti(
        test_context_source=_Source(),
        test_context_admission=_ClaimOnlyAdmission(),
        test_context_clock=lambda: now,
    ).judge(event)
    assert claim_only is not None
    assert claim_only["risk_verdict"] == "hil"
    assert claim_only["test_context"]["reason"] == "observation_admission_required"


async def test_context_factory_binding_preserves_events_without_context_scope() -> None:
    from fdai.agents._framework.factory import configured_forseti

    class _Source:
        async def read(self, **_values):
            raise AssertionError("unscoped ordinary events must not query test context")

    source = _Source()
    forseti = configured_forseti(
        rbac=None,
        action_semantics=None,
        operational_context=None,
        operational_planner=None,
        kinetic_proposal_source=None,
        change_assessor=None,
        test_context_source=source,
    )
    assert forseti is not None and forseti._test_context_source is source
    verdict = await forseti.judge(
        {
            "event_type": "restart_needed",
            "resource_id": "resource-example",
            "correlation_id": "ordinary-example",
        }
    )
    assert verdict is not None and verdict["risk_verdict"] == "auto"
    assert "test_context" not in verdict


async def test_failed_saga_audit_never_publishes_context_application():
    from unittest.mock import AsyncMock

    from fdai.agents.saga import Saga

    saga = Saga()
    saga._append_audit = AsyncMock(side_effect=OSError("synthetic audit failure"))
    saga.bus = AsyncMock()
    with pytest.raises(OSError):
        await saga.on_typed_message(
            "object.policy",
            {
                "kind": "test_context_revision",
                "producer_principal": "Mimir",
                "correlation_id": "example",
            },
        )
    saga.bus.publish.assert_not_awaited()


def _store() -> InMemoryOntologyInstanceStore:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    return InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )


async def _add_resource(store: InMemoryOntologyInstanceStore) -> None:
    await store.upsert_object(
        OntologyObjectRecord(
            id="resource-example",
            object_type="Resource",
            properties={"id": "resource-example", "type": "app-service"},
        )
    )


async def test_unmapped_operational_context_lowers_auto_verdict_to_hil() -> None:
    store = _store()
    await _add_resource(store)
    forseti = Forseti(
        operational_context=OperationalContextMaterializer(store=store, clock=lambda: NOW)
    )

    verdict = await forseti.judge(
        {
            "event_type": "restart_needed",
            "correlation_id": "correlation-example",
            "resource_id": "resource-example",
            "detected_at": NOW.isoformat(),
            "catalog_versions": {"ontology": "1.0.0"},
        }
    )

    assert verdict is not None
    assert verdict["risk_verdict"] == "hil"
    assert verdict["reason"] == "operational_context_ceiling"
    assert verdict["operational_context"]["conflicts"] == ["service_mapping_missing"]


@pytest.mark.parametrize(
    ("action_type", "risk_verdict", "ceiling"),
    [
        ("ops.restart-service", "auto", "enforce_auto"),
        ("remediate.enable-encryption", "hil", "enforce_hil"),
        ("remediate.delete-storage", "deny", "shadow_only"),
    ],
)
async def test_fresh_operational_context_never_raises_verdict_authority(
    action_type: str, risk_verdict: str, ceiling: str
) -> None:
    store = _store()
    await _add_resource(store)
    for record in (
        OntologyObjectRecord(
            id="workload-example",
            object_type="Workload",
            properties={
                "id": "workload-example",
                "name": "Example Workload",
                "workload_kind": "api",
                "effective_from": NOW.isoformat(),
                "source_ref": "service-manifest:example",
            },
        ),
        OntologyObjectRecord(
            id="service-example",
            object_type="BusinessService",
            properties={
                "id": "service-example",
                "name": "Example Service",
                "criticality": "high",
                "effective_from": NOW.isoformat(),
                "source_ref": "service-catalog:example",
            },
        ),
    ):
        await store.upsert_object(record)
    for link in (
        OntologyLinkRecord(
            link_type="workload_runs_on",
            from_id="workload-example",
            to_id="resource-example",
        ),
        OntologyLinkRecord(
            link_type="implemented_by",
            from_id="service-example",
            to_id="workload-example",
        ),
    ):
        await store.upsert_link(link)
    forseti = Forseti(
        operational_context=OperationalContextMaterializer(store=store, clock=lambda: NOW)
    )

    verdict = await forseti.judge(
        {
            "action_type": action_type,
            "event_type": "restart_needed",
            "correlation_id": "correlation-example",
            "resource_id": "resource-example",
            "detected_at": NOW.isoformat(),
            "catalog_versions": {"ontology": "1.0.0"},
        }
    )

    assert verdict is not None
    assert verdict["risk_verdict"] == risk_verdict
    assert verdict["resolved_autonomy_ceiling"] == ceiling
    assert verdict["operational_context"]["service_ids"] == ["service-example"]


async def test_boolean_source_freshness_age_lowers_verdict_to_hil() -> None:
    store = _store()
    await _add_resource(store)
    for record in (
        OntologyObjectRecord(
            id="workload-example",
            object_type="Workload",
            properties={
                "id": "workload-example",
                "name": "Example Workload",
                "workload_kind": "api",
                "effective_from": NOW.isoformat(),
                "source_ref": "service-manifest:example",
            },
        ),
        OntologyObjectRecord(
            id="service-example",
            object_type="BusinessService",
            properties={
                "id": "service-example",
                "name": "Example Service",
                "criticality": "high",
                "effective_from": NOW.isoformat(),
                "source_ref": "service-catalog:example",
            },
        ),
    ):
        await store.upsert_object(record)
    for link in (
        OntologyLinkRecord(
            link_type="workload_runs_on",
            from_id="workload-example",
            to_id="resource-example",
        ),
        OntologyLinkRecord(
            link_type="implemented_by",
            from_id="service-example",
            to_id="workload-example",
        ),
    ):
        await store.upsert_link(link)
    forseti = Forseti(
        operational_context=OperationalContextMaterializer(store=store, clock=lambda: NOW)
    )

    verdict = await forseti.judge(
        {
            "event_type": "restart_needed",
            "correlation_id": "correlation-example",
            "resource_id": "resource-example",
            "detected_at": NOW.isoformat(),
            "catalog_versions": {"ontology": "1.0.0"},
            "source_freshness": [
                {
                    "source": "inventory",
                    "observed_at": NOW.isoformat(),
                    "max_age_seconds": True,
                }
            ],
        }
    )

    assert verdict is not None
    assert verdict["risk_verdict"] == "hil"
    assert verdict["reason"] == "operational_context_invalid"
    assert "operational_context" not in verdict
