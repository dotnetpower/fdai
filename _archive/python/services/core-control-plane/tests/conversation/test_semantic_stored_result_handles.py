"""Stored result handles bind prior-result ordinal references after reauthorization."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fdai.core.conversation.result_handle_store import (
    InMemoryResultHandleStore,
    ResultHandleBinding,
    ResultHandleKey,
    StaticResultHandleKeyProvider,
    rendered_order_digest,
    result_handle_conversation_id,
)
from fdai.core.conversation.semantic_reasoning_compiler import GoalStatus, compile_question_form
from fdai.core.conversation.semantic_reasoning_form import MentionDomain
from fdai.core.conversation.semantic_reasoning_handles import (
    ReferenceOutcome,
    reference_anchors,
)
from fdai.core.conversation.semantic_stored_result_handles import (
    StoredReferenceContext,
    bind_stored_references,
)
from fdai.core.ontology_platform import ObjectSetService
from fdai.core.ontology_platform.interfaces import compile_interfaces
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore
from fdai_core_service.semantic_property_answer import render_property_value_answer
from fdai_core_service.semantic_result_handle_projection import result_handle_from_technical_details
from fdai_service_contracts import SemanticTurnDisposition, SemanticTurnRequest
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.reasoning_handles import PageDescriptor, ResultHandle, TypedRowKey
from fdai_service_contracts.semantic_turn import SemanticTurnResult

from tests.conversation.semantic_reasoning_support import (
    DEFAULT_LOOKBACK_SECONDS,
    NOW,
    PURPOSE,
    admitted,
    concepts,
    execute,
    fixture_anchors,
    fixture_gateway,
    plan_verifier,
    production_catalog,
    production_manifest,
    span,
)


def _row_key(row_id: str) -> TypedRowKey:
    return TypedRowKey(
        row_type="semantic_query_row",
        row_digest=content_digest({"node_id": "resources", "row_id": row_id}),
    )


def _state_lookup_form() -> tuple[str, dict[str, object]]:
    utterance = "What is the current state of the second one?"
    return utterance, {
        "mentions": [
            {
                "id": "m1",
                "form": "ordinal",
                "domain": "instance",
                "span": span(utterance, "second one"),
                "position": 2,
            },
            {
                "id": "m2",
                "form": "value",
                "domain": "state",
                "span": span(utterance, "current state"),
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "lookup",
                "subject": "m1",
                "subject_scope": "prior_result",
                "measure": {"kind": "state", "mention": "m2"},
                "cue": span(utterance, "What is"),
                "confidence": 0.9,
            }
        ],
    }


async def test_ordinal_follow_up_binds_second_stored_handle_row_as_state_lookup_anchor() -> None:
    manifest = production_manifest()
    gateway = await fixture_gateway()
    store = InMemoryResultHandleStore(
        keys=StaticResultHandleKeyProvider(
            current=ResultHandleKey("result-handle-key-v1", b"1" * 32)
        ),
        handle_ref_factory=lambda: "OpaqueHandleRef0123456789abcdefABCDEF",
    )
    row_keys = (_row_key("vm-1"), _row_key("aks-1"))
    handle = ResultHandle.model_validate(
        {
            "deployment_scope_digest": manifest.release_digest,
            "principal_digest": manifest.manifest_digest,
            "conversation_id": "session-a",
            "purpose": PURPOSE,
            "manifest_digest": manifest.manifest_digest,
            "rendered_order_digest": rendered_order_digest(row_keys),
            "row_keys": row_keys,
            "page": PageDescriptor(page_number=1, page_size=2),
            "truncated": False,
        },
        context={"allowed_snapshot_fields": set()},
    )
    handle_ref = await store.put(
        handle,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    utterance, form = _state_lookup_form()
    admission = admitted(form, utterance)
    references = await bind_stored_references(
        admission,
        references=(handle_ref,),
        store=store,
        binding=ResultHandleBinding(
            deployment_scope_digest=manifest.release_digest,
            principal_digest=manifest.manifest_digest,
            conversation_id="session-a",
            purpose=PURPOSE,
            manifest_digest=manifest.manifest_digest,
            now=NOW + timedelta(minutes=1),
        ),
        gateway=gateway,
        projection_request=ProjectionRequest(
            caller_role=CeilingRole.READER,
            declared_purposes=frozenset({PURPOSE}),
        ),
        purpose=PURPOSE,
        as_of=NOW,
    )
    anchors = reference_anchors(await fixture_anchors(admission), references)
    compilation = compile_question_form(
        admission,
        concepts=concepts(),
        manifest=manifest,
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=utterance,
        anchors=anchors,
        references=references,
    )

    assert references.binding("m1").row_ids == ("aks-1",)  # type: ignore[union-attr]
    assert anchors.binding("m1").object_id == "aks-1"  # type: ignore[union-attr]
    assert compilation.goals[0].status is GoalStatus.COMPILED


async def _stored_references(
    admission: object,
    row_ids: tuple[str, ...],
    gateway: object,
    *,
    row_identities: tuple[str, ...] = (),
    schema_version: str | None = None,
) -> tuple[object, object]:
    manifest = production_manifest()
    store = InMemoryResultHandleStore(
        keys=StaticResultHandleKeyProvider(
            current=ResultHandleKey("result-handle-key-v1", b"1" * 32)
        ),
        handle_ref_factory=lambda: "OpaqueHandleRef0123456789abcdefABCDEF",
    )
    row_keys = tuple(_row_key(item) for item in row_ids)
    handle = ResultHandle.model_validate(
        {
            **({"schema_version": schema_version} if schema_version is not None else {}),
            "deployment_scope_digest": manifest.release_digest,
            "principal_digest": manifest.manifest_digest,
            "conversation_id": "session-a",
            "purpose": PURPOSE,
            "manifest_digest": manifest.manifest_digest,
            "rendered_order_digest": rendered_order_digest(row_keys),
            "row_keys": row_keys,
            **({"row_identities": row_identities} if row_identities else {}),
            "page": PageDescriptor(page_number=1, page_size=len(row_keys)),
            "truncated": False,
        },
        context={"allowed_snapshot_fields": set()},
    )
    handle_ref = await store.put(handle, issued_at=NOW, expires_at=NOW + timedelta(minutes=15))
    references = await bind_stored_references(
        admission,  # type: ignore[arg-type]
        references=(handle_ref,),
        store=store,
        binding=ResultHandleBinding(
            deployment_scope_digest=manifest.release_digest,
            principal_digest=manifest.manifest_digest,
            conversation_id="session-a",
            purpose=PURPOSE,
            manifest_digest=manifest.manifest_digest,
            now=NOW + timedelta(minutes=1),
        ),
        gateway=gateway,  # type: ignore[arg-type]
        projection_request=ProjectionRequest(
            caller_role=CeilingRole.READER,
            declared_purposes=frozenset({PURPOSE}),
        ),
        purpose=PURPOSE,
        as_of=NOW,
    )
    assert references is not None
    return references, reference_anchors(await fixture_anchors(admission), references)  # type: ignore[arg-type]


async def _large_gateway(count: int = 1_001) -> SecuredObjectSetQueryGateway:
    catalog = production_catalog()
    resource = next(item for item in catalog.object_types if item.name == "Resource")
    store = InMemoryOntologyInstanceStore(
        object_types=(resource,),
        link_types=(),
        source_complete=True,
        source_generation="large-generation",
    )
    for index in range(count):
        identity = f"resource-{index:04d}"
        await store.upsert_object(
            OntologyObjectRecord(
                id=identity,
                object_type="Resource",
                properties={"id": identity, "name": identity, "type": "compute.vm"},
            )
        )
    service = ObjectSetService(
        store=store,
        interfaces=compile_interfaces(interfaces=(), implementations=(), object_types=(resource,)),
        object_type_names=frozenset({resource.name}),
    )
    return SecuredObjectSetQueryGateway(
        service=service,
        object_types={resource.name: resource},
        ontology_release=build_ontology_release(object_types=(resource,), link_types=()),
        evaluation_cutoff=lambda: NOW,
        graph_completeness=lambda: _complete_graph(),
        max_as_of_skew=timedelta(seconds=5),
    )


async def _complete_graph() -> bool:
    return True


async def test_ordinal_follow_up_rereads_exact_handle_identities_in_large_inventory() -> None:
    utterance, form = _state_lookup_form()
    admission = admitted(form, utterance)
    identities = tuple(f"resource-{index:04d}" for index in range(250))
    references, anchors = await _stored_references(
        admission,
        identities,
        await _large_gateway(),
        row_identities=identities,
    )

    assert references.binding("m1").row_ids == ("resource-0001",)  # type: ignore[union-attr]
    assert anchors.binding("m1").object_id == "resource-0001"  # type: ignore[union-attr]


async def test_tampered_handle_identity_digest_mismatch_does_not_bind() -> None:
    utterance, form = _state_lookup_form()
    admission = admitted(form, utterance)
    references, anchors = await _stored_references(
        admission,
        ("vm-1", "aks-1"),
        await fixture_gateway(),
        row_identities=("vm-1", "sql-1"),
    )

    assert references.binding("m1").outcome.value == "unavailable"  # type: ignore[union-attr]
    assert anchors.binding("m1") is None


async def test_handle_identity_that_is_no_longer_readable_does_not_bind() -> None:
    utterance, form = _state_lookup_form()
    admission = admitted(form, utterance)
    references, anchors = await _stored_references(
        admission,
        ("vm-1", "missing-readable-resource"),
        await fixture_gateway(),
        row_identities=("vm-1", "missing-readable-resource"),
    )

    assert references.binding("m1").outcome.value == "unavailable"  # type: ignore[union-attr]
    assert anchors.binding("m1") is None


async def test_old_handle_record_without_identities_still_uses_scan_fallback() -> None:
    utterance, form = _state_lookup_form()
    admission = admitted(form, utterance)
    references, anchors = await _stored_references(
        admission,
        ("vm-1", "aks-1"),
        await fixture_gateway(),
        schema_version="1.1",
    )

    assert references.binding("m1").row_ids == ("aks-1",)  # type: ignore[union-attr]
    assert anchors.binding("m1").object_id == "aks-1"  # type: ignore[union-attr]


def test_result_handle_projection_keeps_core_only_row_identities() -> None:
    request = SemanticTurnRequest(
        principal={"subject_id": "operator", "roles": ["Reader"]},
        session_id="session-a",
        turn_id="turn-a",
        turn_sequence=1,
        purpose=PURPOSE,
        locale="en",
        utterance="show resources",
        deadline_at=NOW + timedelta(seconds=30),
    )
    result = SemanticTurnResult(
        disposition=SemanticTurnDisposition.ANSWERED,
        reason_code="semantic_plan_verified",
        semantic_route="verified_query_plan",
        session_id="session-a",
        turn_id="turn-a",
        turn_sequence=1,
        ontology_release_digest=production_manifest().release_digest,
        principal_manifest_digest=production_manifest().manifest_digest,
        plan_digest="sha256:" + "1" * 64,
        execution_receipt_digest="sha256:" + "2" * 64,
        evidence_refs=("evidence:1",),
        checks_completed=1,
        checks_total=1,
        answer="Verified answer.",
    )
    handle = result_handle_from_technical_details(
        request,
        result,
        technical_details={
            "outputs": [
                {
                    "node_id": "resources",
                    "rows": [
                        {"row_id": "vm-1", "values": {"name": "vm-app-01"}},
                        {"row_id": "aks-1", "values": {"name": "aks-prod-01"}},
                    ],
                }
            ]
        },
    )

    assert handle is not None
    assert handle.row_identities == ("vm-1", "aks-1")


@pytest.mark.parametrize(
    "session_id",
    ["screen:ce739f1e:/agent-activity", "Session With Capitals And Spaces", "s" * 256],
)
def test_a_session_id_that_is_not_a_machine_token_still_issues_a_handle(session_id: str) -> None:
    request = SemanticTurnRequest(
        principal={"subject_id": "operator", "roles": ["Reader"]},
        session_id=session_id,
        turn_id="turn-a",
        turn_sequence=1,
        purpose=PURPOSE,
        locale="en",
        utterance="show resources",
        deadline_at=NOW + timedelta(seconds=30),
    )
    result = SemanticTurnResult(
        disposition=SemanticTurnDisposition.ANSWERED,
        reason_code="semantic_plan_verified",
        semantic_route="verified_query_plan",
        session_id=session_id,
        turn_id="turn-a",
        turn_sequence=1,
        ontology_release_digest=production_manifest().release_digest,
        principal_manifest_digest=production_manifest().manifest_digest,
        plan_digest="sha256:" + "1" * 64,
        execution_receipt_digest="sha256:" + "2" * 64,
        evidence_refs=("evidence:1",),
        checks_completed=1,
        checks_total=1,
        answer="Verified answer.",
    )
    handle = result_handle_from_technical_details(
        request,
        result,
        technical_details={
            "outputs": [
                {"node_id": "resources", "rows": [{"row_id": "vm-1", "values": {"name": "vm"}}]}
            ]
        },
    )

    # The key the handle is written under is the key a later request binds to.
    assert handle is not None
    assert handle.conversation_id == result_handle_conversation_id(session_id)
    assert result_handle_conversation_id(session_id) == result_handle_conversation_id(session_id)
    assert result_handle_conversation_id("session-a") == "session-a"
    assert result_handle_conversation_id(session_id + "x") != handle.conversation_id


async def test_an_ordinal_property_follow_up_answers_the_exact_value_of_the_stored_row() -> None:
    zone = "resilience.database.zone_redundant.enabled"
    utterance = "Is zone redundancy enabled on the second one?"
    form = {
        "mentions": [
            {
                "id": "m1",
                "form": "ordinal",
                "domain": "instance",
                "span": span(utterance, "second one"),
                "position": 2,
            },
            {
                "id": "m2",
                "form": "concept",
                "domain": "property",
                "span": span(utterance, "zone redundancy"),
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "lookup",
                "subject": "m1",
                "subject_scope": "prior_result",
                "measure": {"kind": "property", "mention": "m2"},
                "cue": span(utterance, "enabled"),
                "confidence": 0.9,
            }
        ],
    }
    admission = admitted(form, utterance)
    gateway = await fixture_gateway({"sql-1": {"zone_redundant": True}})
    references, anchors = await _stored_references(admission, ("vm-1", "sql-1"), gateway)

    bound = anchors.binding("m1")  # type: ignore[attr-defined]
    assert bound.object_id == "sql-1" and bound.resource_type == "sql-database"
    compilation = compile_question_form(
        admission,
        concepts=concepts(("m2", MentionDomain.PROPERTY, (zone,))),
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=utterance,
        anchors=anchors,  # type: ignore[arg-type]
        references=references,  # type: ignore[arg-type]
    )
    goal = compilation.goals[0]
    assert goal.status is GoalStatus.COMPILED, goal.reasons
    (batch,) = goal.batches
    execution = await execute(batch.plan, gateway)
    table = execution.results["g1-read"].value
    answer = render_property_value_answer(
        [{"rows": [{"values": dict(row.values)} for row in table.rows]}],
        korean=False,
        output_shape=batch.frame.output_shape,
        measure_concepts=batch.frame.measure_concepts,
    )

    assert answer is not None
    assert answer.splitlines()[0] == f"## {zone} of sql-app"
    assert f"- {zone}: true" in answer


async def test_a_failing_handle_store_never_withholds_a_verified_answer() -> None:
    from types import SimpleNamespace

    from fdai_core_service.semantic_turn_processor import SemanticTurnProcessor

    class FailingStore:
        async def put(self, *_args: object, **_kwargs: object) -> object:
            raise OSError("state store unavailable")

    request = SemanticTurnRequest(
        principal={"subject_id": "operator", "roles": ["Reader"]},
        session_id="session-a",
        turn_id="turn-a",
        turn_sequence=1,
        purpose=PURPOSE,
        locale="en",
        utterance="show resources",
        deadline_at=NOW + timedelta(seconds=30),
    )
    result = SemanticTurnResult(
        disposition=SemanticTurnDisposition.ANSWERED,
        reason_code="semantic_plan_verified",
        semantic_route="verified_query_plan",
        session_id="session-a",
        turn_id="turn-a",
        turn_sequence=1,
        ontology_release_digest=production_manifest().release_digest,
        principal_manifest_digest=production_manifest().manifest_digest,
        plan_digest="sha256:" + "1" * 64,
        execution_receipt_digest="sha256:" + "2" * 64,
        evidence_refs=("evidence:1",),
        checks_completed=1,
        checks_total=1,
        answer="Verified answer.",
    )
    processor = SemanticTurnProcessor(
        runtime=None,
        results=SimpleNamespace(),  # type: ignore[arg-type]
        result_handle_store=FailingStore(),  # type: ignore[arg-type]
        result_handles_enabled=True,
    )
    extensions = SimpleNamespace(
        technical_details={
            "outputs": [
                {"node_id": "resources", "rows": [{"row_id": "vm-1", "values": {"name": "vm"}}]}
            ]
        }
    )

    returned = await processor._with_result_handle_ref(request, result, extensions)  # type: ignore[arg-type]

    assert returned is result
    assert returned.result_handle_ref is None


async def test_an_anaphor_binds_every_stored_row_the_operator_saw() -> None:
    utterance = "Only the running ones"
    admission = admitted(
        {
            "mentions": [
                {
                    "id": "m1",
                    "form": "anaphor",
                    "domain": "instance",
                    "span": span(utterance, "ones"),
                },
                {
                    "id": "m2",
                    "form": "value",
                    "domain": "state",
                    "span": span(utterance, "running"),
                },
            ],
            "goals": [
                {
                    "id": "g1",
                    "level": "instance",
                    "operation": "select",
                    "subject": "m1",
                    "subject_scope": "prior_result",
                    "filters": [{"role": "state", "mention": "m2"}],
                    "cue": span(utterance, "Only the"),
                    "confidence": 0.9,
                }
            ],
        },
        utterance,
    )
    references, _ = await _stored_references(admission, ("vm-1", "aks-1"), await fixture_gateway())

    bound = references.binding("m1")  # type: ignore[union-attr]
    assert bound is not None and bound.bound
    assert bound.row_ids == ("vm-1", "aks-1")


async def test_stored_reference_context_and_fallback_candidates_cover_edge_outcomes() -> None:
    from fdai.core.conversation.semantic_reasoning_form import MentionForm
    from fdai.core.conversation.semantic_stored_result_handles import _bind_one

    manifest = production_manifest()
    gateway = await fixture_gateway()
    refs_produced = iter(tuple(f"OpaqueHandleRef0123456789abcdefABCD{i:02d}" for i in range(10)))
    store = InMemoryResultHandleStore(
        keys=StaticResultHandleKeyProvider(
            current=ResultHandleKey("result-handle-key-v1", b"1" * 32)
        ),
        handle_ref_factory=lambda: next(refs_produced),
    )
    assert StoredReferenceContext(session_id="session-a", references=(), store=store).session_id
    with pytest.raises(ValueError, match="session_id MUST be non-empty"):
        StoredReferenceContext(session_id="   ", references=(), store=store)

    utterance, form = _state_lookup_form()
    multi_goal_form = {
        **form,
        "goals": [
            form["goals"][0],  # type: ignore[index]
            {**form["goals"][0], "id": "g2"},  # type: ignore[index]
        ],
    }
    admission = admitted(multi_goal_form, utterance)
    binding = ResultHandleBinding(
        deployment_scope_digest=manifest.release_digest,
        principal_digest=manifest.manifest_digest,
        conversation_id="session-a",
        purpose=PURPOSE,
        manifest_digest=manifest.manifest_digest,
        now=NOW + timedelta(minutes=1),
    )
    projection = ProjectionRequest(
        caller_role=CeilingRole.READER, declared_purposes=frozenset({PURPOSE})
    )

    async def _bind(
        adm: object, refs: tuple[object, ...], *, gw: object = gateway, as_of: object = NOW
    ) -> object:
        return await bind_stored_references(
            adm,  # type: ignore[arg-type]
            references=refs,  # type: ignore[arg-type]
            store=store,
            binding=binding,
            gateway=gw,  # type: ignore[arg-type]
            projection_request=projection,
            purpose=PURPOSE,
            as_of=as_of,  # type: ignore[arg-type]
        )

    assert await _bind(admission, ()) is None

    def _make_handle(row_ids: tuple[str, ...], identities: tuple[str, ...] = ()) -> ResultHandle:
        keys = tuple(_row_key(item) for item in row_ids)
        return ResultHandle.model_validate(
            {
                "deployment_scope_digest": manifest.release_digest,
                "principal_digest": manifest.manifest_digest,
                "conversation_id": "session-a",
                "purpose": PURPOSE,
                "manifest_digest": manifest.manifest_digest,
                "rendered_order_digest": rendered_order_digest(keys),
                "row_keys": keys,
                **({"row_identities": identities} if identities else {}),
                "page": PageDescriptor(page_number=1, page_size=max(1, len(keys))),
                "truncated": False,
            },
            context={"allowed_snapshot_fields": set()},
        )

    exp = NOW + timedelta(days=1)
    ref_empty = await store.put(_make_handle(()), issued_at=NOW, expires_at=exp)
    ref_unreadable = await store.put(
        _make_handle(("deleted-vm",), ("deleted-vm",)), issued_at=NOW, expires_at=exp
    )
    ref_valid = await store.put(
        _make_handle(("vm-1", "aks-1"), ("vm-1", "aks-1")), issued_at=NOW, expires_at=exp
    )
    ref_one_no_id = await store.put(_make_handle(("vm-1",)), issued_at=NOW, expires_at=exp)
    ref_one_id = await store.put(_make_handle(("vm-1",), ("vm-1",)), issued_at=NOW, expires_at=exp)
    ref_unknown = ref_valid.model_copy(
        update={"handle_ref": "UnknownHandleRef0123456789abcdefABCD"}
    )

    non_ref_adm = admitted(
        {
            "mentions": [
                {"id": "m1", "form": "name", "domain": "instance", "span": span(utterance, "one")},
                {"id": "m2", "form": "value", "domain": "state", "span": span(utterance, "state")},
            ],
            "goals": [{**form["goals"][0], "subject_scope": "anchor"}],  # type: ignore[index]
        },
        utterance,
    )
    assert (await _bind(non_ref_adm, (ref_empty,))).bindings == ()  # type: ignore[union-attr]
    assert (await _bind(admission, (ref_empty,))).binding("m1").outcome is ReferenceOutcome.EMPTY  # type: ignore[union-attr]
    assert (await _bind(admission, (ref_unknown,))).binding("m1").outcome is (  # type: ignore[union-attr]
        ReferenceOutcome.UNAVAILABLE
    )
    assert (await _bind(admission, (ref_empty, ref_unknown, ref_unreadable))).binding(
        "m1"
    ).outcome is ReferenceOutcome.EMPTY  # type: ignore[union-attr]
    fallback_res = await _bind(
        admission, (ref_empty, ref_unknown, ref_unreadable, ref_valid), as_of=lambda: NOW
    )
    assert fallback_res.binding("m1").row_ids == ("aks-1",)  # type: ignore[union-attr]

    implicit_utt = "How many are there?"
    implicit_adm = admitted(
        {
            "mentions": [],
            "goals": [
                {
                    "id": "g1",
                    "level": "instance",
                    "operation": "count",
                    "subject_scope": "prior_result",
                    "cue": span(implicit_utt, "How many"),
                    "confidence": 0.9,
                }
            ],
        },
        implicit_utt,
    )
    assert (await _bind(implicit_adm, (ref_one_no_id,))).binding(
        "implicit:g1"
    ).resource_type == "compute.vm"  # type: ignore[union-attr]

    class _TruncatedGateway:
        async def materialize(self, definition: object, *, projection_request: object) -> object:
            real = await gateway.materialize(definition, projection_request=projection_request)  # type: ignore[arg-type]
            return real.model_copy(
                update={"receipt": real.receipt.model_copy(update={"truncated": True})}
            )

    for target_ref, gw_arg, as_of_arg in (
        (ref_one_no_id, gateway, NOW + timedelta(hours=1)),
        (ref_one_no_id, await _large_gateway(1001), NOW),
        (ref_one_id, gateway, NOW + timedelta(hours=1)),
        (ref_one_id, _TruncatedGateway(), NOW),
    ):
        res = await _bind(implicit_adm, (target_ref,), gw=gw_arg, as_of=as_of_arg)
        assert res.binding("implicit:g1").outcome is ReferenceOutcome.UNAVAILABLE  # type: ignore[union-attr]

    one_key = (_row_key("vm-1"),)
    row_map: dict[str, tuple[str, str | None]] = {one_key[0].model_dump_json(): ("vm-1", "vm")}
    for pos, expected_out in (
        (0, ReferenceOutcome.OUT_OF_RANGE),
        (5, ReferenceOutcome.OUT_OF_RANGE),
        (-1, ReferenceOutcome.BOUND),
    ):
        assert (
            _bind_one(
                "m1",
                MentionForm.ORDINAL,
                pos,
                handle_ref="h1",
                row_keys=one_key,
                truncated=False,
                row_map=row_map,
                fallback=ReferenceOutcome.BOUND,
                source_generation=None,
            ).outcome
            is expected_out
        )
