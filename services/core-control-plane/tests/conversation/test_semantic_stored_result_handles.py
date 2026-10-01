"""Stored result handles bind prior-result ordinal references after reauthorization."""

from __future__ import annotations

from datetime import timedelta

from fdai.core.conversation.result_handle_store import (
    InMemoryResultHandleStore,
    ResultHandleBinding,
    ResultHandleKey,
    StaticResultHandleKeyProvider,
    rendered_order_digest,
)
from fdai.core.conversation.semantic_reasoning_compiler import GoalStatus, compile_question_form
from fdai.core.conversation.semantic_reasoning_handles import reference_anchors
from fdai.core.conversation.semantic_stored_result_handles import bind_stored_references
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.acl import ProjectionRequest
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.reasoning_handles import PageDescriptor, ResultHandle, TypedRowKey

from tests.conversation.semantic_reasoning_support import (
    DEFAULT_LOOKBACK_SECONDS,
    NOW,
    PURPOSE,
    admitted,
    concepts,
    fixture_anchors,
    fixture_gateway,
    plan_verifier,
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
