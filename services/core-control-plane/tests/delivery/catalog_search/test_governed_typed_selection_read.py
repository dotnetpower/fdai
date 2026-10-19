"""Production-validated fixed-role governance and actual pre-Function read integration."""

import asyncio
import json
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fdai.agents import (
    ActionSemanticsCatalog,
    InMemoryBus,
    default_payload_validator,
    load_pantheon,
)
from fdai.agents.forseti import Forseti
from fdai.agents.saga import Saga
from fdai.agents.thor import Thor
from fdai.agents.var import Var
from fdai.agents.vidar import Vidar
from fdai.composition.semantic_query_typed_selection_read import prepared_function_handler
from fdai.core.conversation.model_observation import ConversationModelObservation
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.typed_selection_contracts import (
    READ_DEMOTION_EVENT,
    READ_FUNCTION,
    READ_PROMOTION_ACTION,
    ReadCapabilityBinding,
    ReadDemotionCommand,
    ReadQualification,
)
from fdai.core.ontology_platform.typed_selection_function import typed_selection_function_type
from fdai.delivery.catalog_search.ontology_candidate_proposal import (
    OntologyCandidateProposal,
    OntologyCandidateProposalResult,
)
from fdai.delivery.catalog_search.ontology_candidate_selection import (
    OntologyCandidateClause,
    OntologyCandidateSelection,
)
from fdai.delivery.catalog_search.ontology_governed_selection_read import (
    GovernedTypedSelectionRead,
    ReadSelectionSource,
)
from fdai.delivery.persistence.state_store_typed_selection_read import StateStoreTypedSelectionRead
from fdai.delivery.typed_selection_read_governance import (
    READ_QUALIFIED_EVENT,
    TypedSelectionReadDemoter,
    TypedSelectionReadPromotionExecutor,
    governed_read_dispatcher,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.runtime.typed_selection_read_lifecycle import (
    FinalizedTypedReadApproval,
    TypedReadLifecycle,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.direct_api import (
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiRequest,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.ontology_query import OntologyQueryNode, QueryNodeKind, content_digest
from tests.delivery.catalog_search.test_ontology_candidate_context import (
    _DIGEST,
    _MODEL,
    _NOW,
    _QUERY,
    _REVISION,
    _source,
)

_OWNERS = (
    "00000000-0000-0000-0000-000000000001",
    "00000000-0000-0000-0000-000000000002",
)


class _Admission:
    allowed = True

    async def admit(self, **values):
        if not self.allowed:
            return None
        return DecisionEvidenceAdmission(
            receipt_digest=_DIGEST,
            verification_bundle_digest=_DIGEST,
            verified_at=_NOW - timedelta(minutes=1),
            valid_until=_NOW + timedelta(hours=1),
            **values,
        )


class _Proposer:
    calls = 0
    mode = "select"

    def candidate_proposal_binding_for_manifest(self, manifest, build=None):
        return _MODEL

    async def propose_prepared_candidate_selection(self, **values):
        self.calls += 1
        if self.mode == "stall":
            await asyncio.Event().wait()
        clause = OntologyCandidateClause(
            object_type="Resource",
            object_ids=("example-resource-00000",)
            if self.mode == "disagree" and self.calls == 2
            else None,
        )
        proposal = OntologyCandidateProposal(
            status="select",
            reason="conditions_proposed",
            clauses=(clause,),
            clause_quotes=(values["query"],),
        )
        return OntologyCandidateProposalResult(
            proposal=proposal,
            selection=OntologyCandidateSelection.bind(
                query=values["query"],
                manifest=values["manifest"],
                staged=values["staged"],
                clauses=proposal.clauses,
            ),
            input_digest=values["context"].context_digest,
            observation=ConversationModelObservation(model="synthetic", usage=None, trace_call={}),
        )


async def _fixture():
    declaration = typed_selection_function_type(object_type_names=("Resource",))
    source = await _source(count=3, function_types=(declaration,))
    clock = SimpleNamespace(now=_NOW, fail_effect=False)
    store = InMemoryStateStore(linearization_clock=lambda: clock.now)
    admission = _Admission()
    registry = StateStoreTypedSelectionRead(
        store,
        admission=admission,
        approvals=FinalizedTypedReadApproval(store),
        clock=lambda: clock.now,
    )
    binding = ReadCapabilityBinding(
        source_revision=_REVISION,
        manifest_digest=source.manifest.manifest_digest,
        principal_scope_digest=_DIGEST,
        model_binding_digest=content_digest(asdict(_MODEL)),
        data_policy_digest=_DIGEST,
        context_protocol="typed-selection-context-transport.v1",
    )
    qualification = ReadQualification(
        binding=binding,
        outcome="qualified",
        qualification_evidence_digest=_DIGEST,
        answer_latency_evidence_digest=_DIGEST,
        issued_at=_NOW - timedelta(minutes=1),
        expires_at=_NOW + timedelta(hours=1),
    )
    await registry.save_qualification(qualification)
    current = [
        ReadSelectionSource(
            binding, source.manifest, source.build, source.staged, source.validation, source.gateway
        )
    ]

    async def resolve(context):
        return current[0]

    proposer = _Proposer()
    reader = GovernedTypedSelectionRead(registry=registry, source=resolve, proposer=proposer)
    lifecycle = TypedReadLifecycle(
        registry,
        can_approve=lambda person, action: person in _OWNERS and action == READ_PROMOTION_ACTION,
    )
    catalog = load_action_type_catalog(
        Path(__file__).parents[5] / "rule-catalog/action-types",
        schema_registry=PackageResourceSchemaRegistry(),
    )
    semantics = ActionSemanticsCatalog.from_action_types(catalog)
    bus = InMemoryBus(
        registry=load_pantheon(),
        payload_validator=default_payload_validator,
        isolate_handlers=False,
    )
    saga = Saga(durable_state_store=store, clock=lambda: clock.now)
    saga.bind_bus(bus)
    forseti = Forseti(
        bus=bus,
        rbac={"Heimdall": frozenset({READ_PROMOTION_ACTION})},
        action_semantics=semantics,
        anomaly_action_sources={READ_QUALIFIED_EVENT: lifecycle},
        state_store=store,
        test_context_clock=lambda: clock.now,
    )

    executed_runs = []

    async def execute(context):
        executed_runs.append(context["run"])
        applied = await lifecycle.execute(context)
        return applied and not clock.fail_effect

    thor = Thor(
        bus=bus,
        executor=execute,
        action_semantics_catalog=semantics,
        approval_state_store=store,
        preflight_simulator=lifecycle,
        clock=lambda: clock.now,
        approver_authorizer=lambda value, action: (
            value in _OWNERS and action == READ_PROMOTION_ACTION
        ),
        owner_authorizer=lambda value, action: value in _OWNERS and action == READ_PROMOTION_ACTION,
    )
    var = Var(
        bus=bus,
        state_store=store,
        clock=lambda: clock.now,
        action_semantics=semantics,
        approver_authorizer=lambda value, action: (
            value in _OWNERS and action == READ_PROMOTION_ACTION
        ),
    )
    vidar = Vidar(
        bus=bus,
        state_store=store,
        clock=lambda: clock.now,
        action_executors={(READ_PROMOTION_ACTION, "scripted"): lifecycle.rollback},
    )
    vidar.bind_typed_read_demoter(TypedSelectionReadDemoter(registry))
    for agent in (saga, forseti, thor, var, vidar):
        for topic in agent.spec.subscribes:
            bus.subscribe(topic, agent.spec.name, agent.on_typed_message)
    context = FunctionInvocationContext(
        caller_agent="Bragi",
        principal_ref="example-owner",
        caller_role="reader",
        principal_scope_digest=_DIGEST,
        purposes=("operations-review",),
    )
    release = build_ontology_release(
        object_types=tuple(source.gateway._object_types.values()), function_types=(declaration,)
    )
    functions = OntologyFunctionRegistry(release=release)
    functions.register_contextual(
        declaration,
        __import__(
            "fdai.core.ontology_platform.instance_candidate_queries",
            fromlist=["instance_candidates_function"],
        ).instance_candidates_function(reader.consume, ontology_release_digest=release.digest),
    )
    return SimpleNamespace(**locals())


async def _promote(f):
    await f.bus.publish(
        "Heimdall",
        "object.anomaly",
        {
            "correlation_id": "read-promotion",
            "idempotency_key": "read-qualified-observation",
            "event_type": READ_QUALIFIED_EVENT,
            "resource_id": "typed-selection-read:" + _DIGEST,
        },
    )
    assert await f.registry.pointer(_DIGEST) is None
    for owner in _OWNERS:
        await f.var.decide("read-promotion", approver=owner, decision="approve")
    pointer = await f.registry.pointer(_DIGEST)
    assert pointer is not None and pointer.enabled, (
        f.thor.behavior_snapshot(),
        f.forseti.behavior_snapshot(),
        f.var.behavior_snapshot(),
    )
    return pointer


async def test_production_validated_fixed_roles_reach_actual_deterministic_answer():
    f = await _fixture()
    pointer = await _promote(f)
    assert (await f.registry.active(f.binding)).revision == pointer.revision
    context = await f.reader.prepare({"query": _QUERY, "limit": 20}, f.context)
    assert f.proposer.calls == 2
    result, receipt = await f.functions.invoke_with_receipt(
        READ_FUNCTION,
        {"query": _QUERY, "limit": 20},
        context=context,
    )
    assert result["candidate_count"] == 3
    assert len(result["candidates"]) == 3
    assert result["execution_authority"] is False
    assert receipt.function_ref.name == READ_FUNCTION
    assert f.proposer.calls == 2
    assert f.saga.audit_chain.entries_for_correlation("read-promotion")


async def test_actual_production_function_node_prepares_outside_the_registry():
    f = await _fixture()
    await _promote(f)
    handler = prepared_function_handler(f.functions, f.context, f.reader)
    node = OntologyQueryNode(
        node_id="typed-read",
        kind=QueryNodeKind.FUNCTION,
        output_kind="query.candidates",
        arguments_json=json.dumps(
            {"function_name": READ_FUNCTION, "arguments": {"query": _QUERY, "limit": 20}},
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    result = await handler(node, {})
    assert result.value["candidate_count"] == 3
    assert f.proposer.calls == 2
    assert f.declaration.network_allowed is False
    assert f.declaration.timeout_seconds == 5
    assert f.reader.contract.total_timeout_seconds == 24


async def test_forged_owner_or_approval_never_reaches_registry_promotion():
    f = await _fixture()
    with pytest.raises(ValueError, match="not the owner"):
        await f.bus.publish(
            "Bragi",
            "object.approval",
            {
                "state": "approved",
                "correlation_id": "forged",
                "idempotency_key": "forged",
            },
        )
    with pytest.raises(PermissionError, match="only Thor"):
        await f.registry.promote(
            qualification_digest=f.qualification.digest,
            expected_revision=0,
            approval_key="forged",
            approval_fingerprint="forged",
            request_digest=_DIGEST,
            actor="Var",
        )
    assert await f.registry.pointer(_DIGEST) is None


async def test_revoked_independent_qualification_denies_before_any_model_call():
    f = await _fixture()
    await _promote(f)
    f.admission.allowed = False
    with pytest.raises(PermissionError):
        await f.reader.prepare({"query": _QUERY, "limit": 20}, f.context)
    assert f.proposer.calls == 0


async def test_failed_effect_observation_triggers_actual_vidar_scripted_rollback():
    f = await _fixture()
    f.clock.fail_effect = True
    await f.bus.publish(
        "Heimdall",
        "object.anomaly",
        {
            "correlation_id": "read-promotion",
            "idempotency_key": "read-qualified-observation",
            "event_type": READ_QUALIFIED_EVENT,
            "resource_id": "typed-selection-read:" + _DIGEST,
        },
    )
    for owner in _OWNERS:
        await f.var.decide("read-promotion", approver=owner, decision="approve")
    pointer = await f.registry.pointer(_DIGEST)
    assert pointer is not None and not pointer.enabled
    assert f.bus.messages_on("object.rollback")
    assert f.saga.audit_chain.entries_for_correlation("read-promotion")


@pytest.mark.parametrize("reason", ["revoked", "regression"])
async def test_vidar_typed_demotion_fences_pending_selection_and_old_promotion(reason):
    f = await _fixture()
    pointer = await _promote(f)
    context = await f.reader.prepare({"query": _QUERY, "limit": 20}, f.context)
    command = ReadDemotionCommand(
        principal_scope_digest=_DIGEST,
        expected_revision=pointer.revision,
        qualification_digest=f.qualification.digest,
        action_run_identity=_DIGEST,
        source_revision=_REVISION,
        reason=reason,
        issued_at=_NOW,
        expires_at=_NOW + timedelta(seconds=60),
    )
    await f.bus.publish(
        "Huginn",
        "object.event",
        {
            "event_type": READ_DEMOTION_EVENT,
            "correlation_id": "read-demotion",
            "idempotency_key": "read-demotion-" + reason,
            "resource_id": "typed-selection-read:" + _DIGEST,
            "attributes": command.model_dump(mode="json"),
        },
    )
    assert not (await f.registry.pointer(_DIGEST)).enabled
    assert f.bus.messages_on("object.rollback")
    with pytest.raises(PermissionError):
        await f.reader.consume(_QUERY, 20, context)
    with pytest.raises(PermissionError):
        await f.registry.promote(
            qualification_digest=f.qualification.digest,
            expected_revision=0,
            approval_key="old",
            approval_fingerprint="old",
            request_digest=_DIGEST,
            actor="Thor",
        )


@pytest.mark.parametrize("kind", ["model", "source", "scope", "replay", "expired", "cancelled"])
async def test_exact_evidence_drift_and_replay_fail_closed(kind):
    f = await _fixture()
    await _promote(f)
    context = await f.reader.prepare({"query": _QUERY, "limit": 20}, f.context)
    if kind in {"model", "source", "scope"}:
        name = {
            "model": "model_binding_digest",
            "source": "source_revision",
            "scope": "principal_scope_digest",
        }[kind]
        changed = f.binding.model_copy(
            update={name: "b" * 40 if kind == "source" else "sha256:" + "b" * 64}
        )
        f.current[0] = replace(f.current[0], binding=changed)
    elif kind == "replay":
        await f.reader.consume(_QUERY, 20, context)
    elif kind == "expired":
        f.clock.now += timedelta(seconds=31)
    else:
        await f.registry.cancel_request(context.authentication_request_ref)
    with pytest.raises(PermissionError):
        await f.reader.consume(_QUERY, 20, context)


@pytest.mark.parametrize("kind", ["unqualified", "disagreement", "cancel"])
async def test_no_consumable_evidence_on_unavailable_disagreement_or_cancel(kind):
    f = await _fixture()
    if kind == "unqualified":
        with pytest.raises(PermissionError):
            await f.reader.prepare({"query": _QUERY, "limit": 20}, f.context)
        assert f.proposer.calls == 0
        return
    await _promote(f)
    f.proposer.mode = "disagree" if kind == "disagreement" else "stall"
    task = asyncio.create_task(f.reader.prepare({"query": _QUERY, "limit": 20}, f.context))
    if kind == "cancel":
        for _ in range(100):
            await asyncio.sleep(0)
            if f.proposer.calls == 2:
                break
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(PermissionError, match="disagree"):
            await task


async def _direct_request(f):
    candidate = await f.lifecycle.resolve(
        event_type=READ_QUALIFIED_EVENT, resource_ref="typed-selection-read:" + _DIGEST
    )
    assert candidate is not None
    return DirectApiRequest(
        action_id=uuid4(),
        idempotency_key="typed-read-direct-test",
        action_type_name=READ_PROMOTION_ACTION,
        rule_ids=(),
        resource_ref=candidate.resource_ref,
        arguments=json.loads(candidate.arguments_json),
    )


async def test_direct_shadow_is_nonmutating_and_unapproved_enforce_is_rejected():
    f = await _fixture()
    request = await _direct_request(f)
    executor = TypedSelectionReadPromotionExecutor(f.registry)
    receipt = await executor.execute(request)
    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert receipt.receipt_ref.startswith("shadow:")
    assert await f.registry.pointer(_DIGEST) is None
    enforced = replace(request, mode=Mode.ENFORCE, labels=("enforce",))
    with pytest.raises(DirectApiPreconditionError):
        await governed_read_dispatcher(f.registry).execute(enforced)
    assert await f.registry.pointer(_DIGEST) is None
    with pytest.raises(DirectApiPreconditionError, match="requires enforce"):
        await executor.execute(replace(request, mode=Mode.ENFORCE))
    assert await f.registry.pointer(_DIGEST) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("evidence_digest", None),
        ("expected_revision", True),
        ("expected_revision", -1),
        ("action_type_id", "example.unregistered"),
        ("fdai_revision", "b" * 40),
        ("scenario_set_version", "unregistered"),
        ("target_mode", "shadow"),
        ("target_resource_ref", "example:other"),
    ],
)
async def test_direct_promotion_rejects_argument_or_exact_binding_drift(field, value):
    f = await _fixture()
    request = await _direct_request(f)
    executor = TypedSelectionReadPromotionExecutor(f.registry)
    with pytest.raises(DirectApiPreconditionError):
        await executor.execute(replace(request, arguments={**request.arguments, field: value}))
    assert await f.registry.pointer(_DIGEST) is None


async def test_specialized_executor_and_lifecycle_do_not_claim_other_actions():
    f = await _fixture()
    request = await _direct_request(f)
    with pytest.raises(DirectApiPreconditionError, match="unregistered"):
        await TypedSelectionReadPromotionExecutor(f.registry).execute(
            replace(request, action_type_name="example.unregistered")
        )
    assert await f.lifecycle.execute({}) is False
    assert await f.lifecycle.rollback({"action_type": "example.unregistered"}) is None
    assert (
        await f.lifecycle.rollback(
            {"action_type": READ_PROMOTION_ACTION, "resource_id": "typed-selection-read:" + _DIGEST}
        )
        is None
    )
    with pytest.raises(PermissionError, match="action type mismatch"):
        await f.lifecycle.prepare({"action_type": "example.unregistered"})
    with pytest.raises(PermissionError, match="arguments are unavailable"):
        await f.lifecycle.prepare({"action_type": READ_PROMOTION_ACTION, "params": None})


async def test_qualification_source_never_turns_missing_or_denied_evidence_into_a_candidate():
    f = await _fixture()
    target = "typed-selection-read:" + _DIGEST
    assert await f.lifecycle.resolve(event_type="example.other", resource_ref=target) is None
    assert await f.lifecycle.resolve(event_type=READ_QUALIFIED_EVENT, resource_ref="other") is None
    assert (
        await f.lifecycle.resolve(
            event_type=READ_QUALIFIED_EVENT, resource_ref="typed-selection-read:sha256:" + "b" * 64
        )
        is None
    )
    f.admission.allowed = False
    assert await f.lifecycle.resolve(event_type=READ_QUALIFIED_EVENT, resource_ref=target) is None
    assert await f.registry.pointer(_DIGEST) is None


@pytest.mark.parametrize("failure", ["owner", "expired", "target", "admission"])
async def test_vidar_demotion_requires_owned_current_independently_admitted_evidence(failure):
    f = await _fixture()
    pointer = await _promote(f)
    command = ReadDemotionCommand(
        principal_scope_digest=_DIGEST,
        expected_revision=pointer.revision + (1 if failure == "target" else 0),
        qualification_digest=f.qualification.digest,
        action_run_identity=_DIGEST,
        source_revision=_REVISION,
        reason="regression",
        issued_at=_NOW - timedelta(minutes=2) if failure == "expired" else _NOW,
        expires_at=_NOW - timedelta(minutes=1)
        if failure == "expired"
        else _NOW + timedelta(seconds=60),
    )
    if failure == "admission":
        f.admission.allowed = False
    with pytest.raises(PermissionError):
        await TypedSelectionReadDemoter(f.registry)(
            {
                "event_type": READ_DEMOTION_EVENT,
                "producer_principal": "Bragi" if failure == "owner" else "Huginn",
                "attributes": command.model_dump(mode="json"),
            }
        )
    assert await f.registry.pointer(_DIGEST) == pointer


async def test_current_registry_never_borrows_missing_or_unfinalized_human_approval():
    f = await _fixture()
    pointer = await _promote(f)
    f.registry.approvals = None
    with pytest.raises(PermissionError, match="binding is not admitted"):
        await f.registry.active(f.binding)
    f.registry.approvals = FinalizedTypedReadApproval(InMemoryStateStore())
    with pytest.raises(PermissionError, match="not finalized"):
        await f.registry.active(f.binding)
    with pytest.raises(PermissionError, match="revision changed"):
        await f.registry.promote(
            qualification_digest=f.qualification.digest,
            expected_revision=0,
            approval_key=pointer.approval_key,
            approval_fingerprint=pointer.approval_fingerprint,
            request_digest=pointer.promotion_request_digest,
            actor="Thor",
        )
    with pytest.raises(PermissionError, match="requires Vidar"):
        await f.registry.demote(
            scope_digest=_DIGEST,
            expected_revision=pointer.revision,
            reason="regression",
            actor="Thor",
        )
    with pytest.raises(PermissionError, match="revision changed"):
        await f.registry.demote(
            scope_digest=_DIGEST, expected_revision=0, reason="regression", actor="Vidar"
        )
    assert await f.registry.pointer(_DIGEST) == pointer


async def test_lifecycle_rechecks_the_retained_original_and_current_authorizer():
    f = await _fixture()
    pointer = await _promote(f)
    run = f.executed_runs[0]
    assert await f.lifecycle.execute({"run": run})
    assert await f.registry.pointer(_DIGEST) == pointer
    changed = replace(run, resource_id="typed-selection-read:other")
    with pytest.raises(PermissionError, match="retained action or target changed"):
        await f.lifecycle.execute({"run": changed})
    assert (await f.lifecycle.simulate(changed)).outcome == "failed"
    f.lifecycle.can_approve = None
    with pytest.raises(PermissionError, match="human authorization is unavailable"):
        await f.lifecycle.execute({"run": run})
    assert await f.registry.pointer(_DIGEST) == pointer


async def test_lifecycle_original_action_identity_cannot_be_rebound_on_replay():
    f = await _fixture()
    request = await _direct_request(f)
    verdict = {
        "action_type": READ_PROMOTION_ACTION,
        "params": dict(request.arguments),
        "idempotency_key": "retained-original-test",
        "correlation_id": "retained-original-correlation",
        "resource_id": request.resource_ref,
    }
    first = await f.lifecycle.prepare(verdict)
    assert await f.lifecycle.prepare(verdict) == first
    with pytest.raises(PermissionError, match="retained action identity changed"):
        await f.lifecycle.prepare({**verdict, "resource_id": "typed-selection-read:other"})
    assert await f.registry.pointer(_DIGEST) is None


async def test_final_approval_replay_requires_both_exact_key_and_fingerprint():
    f = await _fixture()
    pointer = await _promote(f)
    approvals = FinalizedTypedReadApproval(f.store)
    assert await approvals.load_replay("pantheon/var/missing", _DIGEST) is None
    assert await approvals.load_replay(pointer.approval_key, "sha256:" + "b" * 64) is None
    assert await approvals.load_replay(pointer.approval_key, pointer.approval_fingerprint)


@pytest.mark.parametrize(
    "arguments",
    [
        {"query": "", "limit": 20},
        {"query": _QUERY, "limit": True},
        {"query": _QUERY, "limit": 21},
        {"query": _QUERY, "limit": 20, "extra": "injected"},
    ],
)
async def test_invalid_model_stage_arguments_are_rejected_without_billed_work(arguments):
    f = await _fixture()
    await _promote(f)
    with pytest.raises(PermissionError, match="arguments are invalid"):
        await f.reader.prepare(arguments, f.context)
    assert f.proposer.calls == 0


async def test_missing_model_stage_and_wrong_read_identity_are_explicitly_unavailable():
    f = await _fixture()
    await _promote(f)
    f.reader.proposer = None
    with pytest.raises(PermissionError, match="proposer is unavailable"):
        await f.reader.prepare({"query": _QUERY, "limit": 20}, f.context)
    f.reader.proposer = f.proposer
    with pytest.raises(PermissionError, match="authenticated read source"):
        await f.reader.prepare(
            {"query": _QUERY, "limit": 20}, f.context.model_copy(update={"caller_agent": "Thor"})
        )
    f.current[0] = replace(
        f.current[0],
        binding=f.binding.model_copy(update={"principal_scope_digest": "sha256:" + "b" * 64}),
    )
    with pytest.raises(PermissionError, match="source scope changed"):
        await f.reader.prepare({"query": _QUERY, "limit": 20}, f.context)
    assert f.proposer.calls == 0
