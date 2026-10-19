"""Offline context transport is complete and source-bound, never promotion evidence."""

import asyncio
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from fdai.core.ontology_platform import QueryManifest, build_query_manifest
from fdai.core.ontology_platform.interfaces import compile_interfaces
from fdai.core.ontology_platform.object_sets import ObjectSetService
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.core.prompts.types import PromptReplayManifest
from fdai.delivery.azure.llm.semantic_planning import AzureOpenAISemanticPlanningModel
from fdai.delivery.catalog_search.generation import SemanticGenerationBuild
from fdai.delivery.catalog_search.ontology_candidate_context import (
    CandidateContextError,
    CandidateContextLimits,
    prepare_candidate_proposal_context,
    restore_candidate_proposal_context,
)
from fdai.delivery.catalog_search.ontology_candidate_proposal import (
    OntologyCandidateModelBinding,
    OntologyCandidateProposal,
    candidate_proposal_payload,
)
from fdai.delivery.catalog_search.ontology_candidate_selection import (
    OntologyCandidateClause,
    OntologyCandidateSelection,
    resolve_candidate_selection,
)
from fdai.delivery.catalog_search.ontology_snapshot_store import (
    OntologyGenerationSnapshotStore,
    OntologyStagedProjection,
)
from fdai.delivery.catalog_search.ontology_snapshot_validation import (
    OntologySnapshotValidation,
    validate_snapshot_against_current_graph,
)
from fdai.shared.contracts.models import CeilingRole, OntologyObjectType, PropertyDecl, PropertyType
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.ontology_query import canonical_json, content_digest
from pydantic import ValidationError
from tests.delivery.azure.llm.test_ontology_candidate_proposal import _candidate_config
from tests.delivery.azure.llm.test_semantic_planning import _Identity

_NOW = datetime(2026, 10, 19, tzinfo=UTC)
_REVISION = "a" * 40
_DIGEST = "sha256:" + "a" * 64
_OTHER_DIGEST = "sha256:" + "b" * 64
_QUERY = "모든 리소스를 빠짐없이 보여 주세요."
_MODEL = OntologyCandidateModelBinding(
    target_digest=_DIGEST,
    deployment_digest=_DIGEST,
    request_parameters_digest=_DIGEST,
    prompt_manifest=PromptReplayManifest(
        system_text_sha256="a" * 64, layer_manifest=(), token_estimate=1
    ),
)


@dataclass(frozen=True)
class _Source:
    manifest: QueryManifest
    build: SemanticGenerationBuild
    staged: OntologyStagedProjection
    validation: OntologySnapshotValidation
    gateway: SecuredObjectSetQueryGateway
    store: InMemoryOntologyInstanceStore

    def inputs(self) -> dict:
        return {
            "query": _QUERY,
            "manifest": self.manifest,
            "build": self.build,
            "staged": self.staged,
            "source_validation": self.validation,
            "source_revision": _REVISION,
            "model_binding": _MODEL,
            "data_handling_policy_digest": _DIGEST,
        }


async def _source(
    *, count: int = 600, label: str = '자료 "검토" \\ 경로', function_types: tuple = ()
) -> _Source:
    declaration = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "name": PropertyDecl(type=PropertyType.STRING),
            "metadata": PropertyDecl(type=PropertyType.OBJECT),
        },
    )
    release = build_ontology_release(object_types=(declaration,), function_types=function_types)
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=_DIGEST,
        object_types=(declaration,),
        functions=function_types,
    )
    store = InMemoryOntologyInstanceStore(
        object_types=(declaration,), link_types=(), source_generation="context-source"
    )
    for ordinal in range(count):
        identifier = f"example-resource-{ordinal:05}"
        await store.upsert_object(
            OntologyObjectRecord(
                id=identifier,
                object_type="Resource",
                properties={
                    "id": identifier,
                    "name": label,
                    "metadata": {"목적": label, "tier": ordinal},
                },
            )
        )
    gateway = SecuredObjectSetQueryGateway(
        service=ObjectSetService(
            store=store,
            interfaces=compile_interfaces(
                interfaces=(), implementations=(), object_types=(declaration,)
            ),
            object_type_names=frozenset(("Resource",)),
        ),
        object_types={"Resource": declaration},
        ontology_release=release,
        evaluation_cutoff=lambda: _NOW,
        max_as_of_skew=timedelta(seconds=5),
    )
    snapshots = OntologyGenerationSnapshotStore(InMemoryStateStore())
    staged = await snapshots.stage_manifest_from_gateway(
        gateway=gateway,
        manifest=manifest,
        as_of=_NOW,
        expected_source_generation="context-source",
        embedding_space_id="test-space",
        embedding_model_version="synthetic-embedding-v1",
        embedding_dimension=4,
    )
    build = await snapshots.read(
        staged.snapshot_digest,
        manifest=manifest,
        source_generation=staged.source_generation,
        source_projection_digest=staged.source_projection_digest,
    )
    assert build is not None
    validation = await validate_snapshot_against_current_graph(
        snapshots=snapshots,
        staged=staged,
        gateway=gateway,
        manifest=manifest,
        as_of=_NOW,
        embedding_space_id="test-space",
        embedding_model_version="synthetic-embedding-v1",
        embedding_dimension=4,
        validator_id="synthetic-offline-context-test",
    )
    return _Source(manifest, build, staged, validation, gateway, store)


@pytest.fixture
async def source() -> _Source:
    return await _source()


async def test_large_context_round_trip_preserves_every_document_and_catalog(
    source: _Source,
) -> None:
    inputs = source.inputs()
    with pytest.raises(ValueError, match="bound|exceeds"):
        candidate_proposal_payload(
            query=_QUERY, manifest=source.manifest, build=source.build, staged=source.staged
        )
    context = prepare_candidate_proposal_context(**inputs)
    assert context.payload_bytes > 65536
    assert len(context.pages) > 1
    assert context.document_count == 601
    for page in context.pages:
        assert len(canonical_json(page.model_dump()).encode()) <= context.limits.max_page_bytes
    payload = restore_candidate_proposal_context(context, **inputs)
    assert payload["query"] == _QUERY
    assert payload["documents"] == [
        {"document_id": document.rule_id, "content": json.loads(document.text)}
        for document in source.build.documents
    ]
    assert payload["allowed_predicate_properties"] == [
        {"object_type": "Resource", "properties": ["id", "metadata", "name"]}
    ]
    assert payload["allowed_nested_predicate_keys"] == [
        {"object_type": "Resource", "property": "metadata", "keys": ["tier", "목적"]}
    ]
    assert "input_digest" not in payload
    assert prepare_candidate_proposal_context(**inputs) == context


async def test_small_context_preserves_legacy_proposer_payload() -> None:
    source = await _source(count=1)
    old = candidate_proposal_payload(
        query=_QUERY, manifest=source.manifest, build=source.build, staged=source.staged
    )
    old.pop("input_digest")
    context = prepare_candidate_proposal_context(**source.inputs())
    restored = restore_candidate_proposal_context(context, **source.inputs())
    assert json.loads(json.dumps(old)) == restored


async def test_fragments_split_a_large_unicode_document_only_as_transport() -> None:
    source = await _source(count=1, label='인용 "문자" \\ 경로 ' * 500)
    context = prepare_candidate_proposal_context(
        **source.inputs(), limits=CandidateContextLimits(max_page_bytes=4096)
    )
    assert len(context.pages) > len(source.build.documents)
    restored = restore_candidate_proposal_context(
        context, **source.inputs(), limits=CandidateContextLimits(max_page_bytes=4096)
    )
    assert restored["documents"] == [
        {"document_id": document.rule_id, "content": json.loads(document.text)}
        for document in source.build.documents
    ]


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "reverse",
        "fragment",
        "digest",
        "ordinal",
        "bytes",
        "count",
        "root",
        "malformed",
        "rehashed",
        "authority",
    ],
)
async def test_fragment_corruption_never_releases_partial_context(
    source: _Source, change: str
) -> None:
    context = prepare_candidate_proposal_context(**source.inputs())
    pages = context.pages
    if change == "missing":
        context = context.model_copy(update={"pages": pages[:-1]})
    elif change == "duplicate":
        context = context.model_copy(update={"pages": (pages[0], *pages)})
    elif change == "reverse":
        context = context.model_copy(update={"pages": tuple(reversed(pages))})
    elif change == "malformed":
        context = context.model_copy(update={"pages": ()})
    elif change == "authority":
        context = context.model_copy(update={"authority": "enforce", "execution_authority": True})
    elif change == "rehashed":
        fragment = pages[0].fragment.replace("example-resource-00000", "example-resource-xxxxx")
        assert fragment != pages[0].fragment
        page = pages[0].model_copy(
            update={
                "fragment": fragment,
                "page_digest": content_digest({"ordinal": 0, "fragment": fragment}),
            }
        )
        context = context.model_copy(update={"pages": (page, *pages[1:])})
        context = context.model_copy(
            update={
                "context_digest": content_digest(
                    {
                        "binding": context.binding.model_dump(mode="json"),
                        "limits": context.limits.model_dump(mode="json"),
                        "document_count": context.document_count,
                        "payload_bytes": context.payload_bytes,
                        "payload_digest": context.payload_digest,
                        "page_digests": tuple(page.page_digest for page in context.pages),
                        "authority": "transport_only",
                        "execution_authority": False,
                    }
                )
            }
        )
    elif change in ("fragment", "digest", "ordinal"):
        values = {
            "fragment": {"fragment": pages[0].fragment + "x"},
            "digest": {"page_digest": _OTHER_DIGEST},
            "ordinal": {"ordinal": 1},
        }
        context = context.model_copy(
            update={"pages": (pages[0].model_copy(update=values[change]), *pages[1:])}
        )
    else:
        values = {
            "bytes": {"payload_bytes": context.payload_bytes - 1},
            "count": {"document_count": context.document_count - 1},
            "root": {"context_digest": _OTHER_DIGEST},
        }
        context = context.model_copy(update=values[change])
    with pytest.raises(CandidateContextError, match="context_corrupt") as error:
        restore_candidate_proposal_context(context, **source.inputs())
    assert _QUERY not in str(error.value)


@pytest.mark.parametrize(
    "change", ["revision", "target", "deployment", "parameters", "prompt", "policy", "query"]
)
async def test_replay_rejects_changed_model_source_and_policy_pins(
    source: _Source, change: str
) -> None:
    inputs = source.inputs()
    context = prepare_candidate_proposal_context(**inputs)
    if change == "revision":
        inputs["source_revision"] = "b" * 40
    elif change in ("target", "deployment", "parameters"):
        field = {
            "target": "target_digest",
            "deployment": "deployment_digest",
            "parameters": "request_parameters_digest",
        }[change]
        inputs["model_binding"] = replace(_MODEL, **{field: _OTHER_DIGEST})
    elif change == "prompt":
        inputs["model_binding"] = replace(
            _MODEL, prompt_manifest=replace(_MODEL.prompt_manifest, system_text_sha256="b" * 64)
        )
    elif change == "policy":
        inputs["data_handling_policy_digest"] = _OTHER_DIGEST
    else:
        inputs["query"] = _QUERY + " 다른 요청"
    with pytest.raises(CandidateContextError, match="binding_changed"):
        restore_candidate_proposal_context(context, **inputs)


@pytest.mark.parametrize(
    "field",
    [
        "snapshot_digest",
        "generation_digest",
        "source_generation",
        "principal_scope_digest",
        "manifest_digest",
        "source_projection_digest",
    ],
)
async def test_source_validation_must_bind_the_complete_current_projection(
    source: _Source, field: str
) -> None:
    inputs = source.inputs()
    inputs["source_validation"] = replace(source.validation, **{field: _OTHER_DIGEST})
    with pytest.raises(CandidateContextError, match="invalid_source"):
        prepare_candidate_proposal_context(**inputs)


async def test_later_current_projection_digest_is_bound_without_requiring_same_cutoff(
    source: _Source,
) -> None:
    inputs = source.inputs()
    validation = replace(source.validation, checked_projection_digest=_OTHER_DIGEST)
    inputs["source_validation"] = validation
    context = prepare_candidate_proposal_context(**inputs)
    assert context.binding.source_validation_digest == validation.receipt_digest


async def test_actual_payload_bound_counts_escaping_and_returns_no_prefix() -> None:
    source = await _source(count=1, label="가" * 1000)
    raw_size = sum(len(document.text.encode()) for document in source.build.documents)
    with pytest.raises(CandidateContextError, match="context_budget_exceeded"):
        prepare_candidate_proposal_context(
            **source.inputs(), limits=CandidateContextLimits(max_context_bytes=raw_size + 500)
        )


async def test_source_bound_stops_before_context_construction(source: _Source) -> None:
    with pytest.raises(CandidateContextError, match="context_budget_exceeded"):
        prepare_candidate_proposal_context(
            **source.inputs(), limits=CandidateContextLimits(max_context_bytes=1)
        )


async def test_page_count_ceiling_is_explicit_instead_of_dropping_a_tail() -> None:
    source = await _source(count=800)
    with pytest.raises(CandidateContextError, match="page_budget_exceeded"):
        prepare_candidate_proposal_context(
            **source.inputs(), limits=CandidateContextLimits(max_page_bytes=1024)
        )


@pytest.mark.parametrize(
    "limits", [{"max_context_bytes": 8388609}, {"max_page_bytes": 65537}, {"max_page_bytes": True}]
)
def test_limits_cannot_be_raised_past_the_reviewed_ceiling(limits: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CandidateContextLimits.model_validate(limits)


async def test_package_limits_are_not_taken_as_trusted_verifier_inputs(source: _Source) -> None:
    context = prepare_candidate_proposal_context(
        **source.inputs(), limits=CandidateContextLimits(max_context_bytes=4000000)
    )
    with pytest.raises(CandidateContextError, match="binding_changed"):
        restore_candidate_proposal_context(context, **source.inputs())


async def test_invalid_pins_and_queries_have_content_free_failure_reasons(source: _Source) -> None:
    for values in (
        {"source_revision": "not-a-commit"},
        {"data_handling_policy_digest": "unreviewed"},
        {"query": " "},
        {"query": "가" * 6000},
    ):
        inputs = {**source.inputs(), **values}
        with pytest.raises(CandidateContextError, match="invalid_source") as error:
            prepare_candidate_proposal_context(**inputs)
        assert str(error.value) == "candidate context preparation failed: invalid_source"


async def test_package_can_round_trip_through_a_bounded_record(source: _Source) -> None:
    context = prepare_candidate_proposal_context(**source.inputs())
    assert type(context).model_validate(context.model_dump()) == context
    with pytest.raises(ValidationError):
        context.document_count = 1


async def test_corrupt_context_stops_before_the_existing_secured_membership_read(
    source: _Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = prepare_candidate_proposal_context(**source.inputs())
    context = context.model_copy(update={"pages": context.pages[:-1]})
    materialize = AsyncMock()
    monkeypatch.setattr(source.gateway, "materialize", materialize)
    with pytest.raises(CandidateContextError, match="context_corrupt"):
        payload = restore_candidate_proposal_context(context, **source.inputs())
        selection = OntologyCandidateSelection.bind(
            query=str(payload["query"]),
            manifest=source.manifest,
            staged=source.staged,
            clauses=(OntologyCandidateClause(object_type="Resource"),),
        )
        await resolve_candidate_selection(
            selection=selection,
            query=_QUERY,
            staged=source.staged,
            manifest=source.manifest,
            documents=source.build.documents,
            gateway=source.gateway,
            as_of=_NOW,
            deadline=asyncio.get_running_loop().time() + 5,
            resource_type_query_terms={},
        )
    materialize.assert_not_awaited()


async def test_context_to_secured_membership_is_complete_but_not_answer_activation(
    source: _Source,
) -> None:
    context = prepare_candidate_proposal_context(**source.inputs())
    payload = restore_candidate_proposal_context(context, **source.inputs())
    # A synthetic model proposes meaning. The real existing gateway still verifies membership.
    proposal = OntologyCandidateProposal(
        status="select",
        reason="conditions_proposed",
        clauses=(OntologyCandidateClause(object_type="Resource"),),
        clause_quotes=(_QUERY,),
    )
    proposal.validate_source_quotes(payload["query"])
    selection = OntologyCandidateSelection.bind(
        query=_QUERY, manifest=source.manifest, staged=source.staged, clauses=proposal.clauses
    )
    selected = await resolve_candidate_selection(
        selection=selection,
        query=_QUERY,
        staged=source.staged,
        manifest=source.manifest,
        documents=source.build.documents,
        gateway=source.gateway,
        as_of=_NOW,
        deadline=asyncio.get_running_loop().time() + 5,
        resource_type_query_terms={},
    )
    assert len(selected.documents) == 600
    assert selected.documents[-1].rule_id == "object:Resource:example-resource-00599"
    assert selected.query_receipt_digests
    assert context.authority == "transport_only"
    assert context.execution_authority is False
    assert not hasattr(context, "promotion_receipt")
    assert not hasattr(context, "selection")


async def test_transport_does_not_replace_current_membership_source_validation(
    source: _Source,
) -> None:
    context = prepare_candidate_proposal_context(**source.inputs())
    restore_candidate_proposal_context(context, **source.inputs())
    await source.store.upsert_object(
        OntologyObjectRecord(
            id="example-resource-00599",
            object_type="Resource",
            properties={"id": "example-resource-00599", "name": "Changed after preparation"},
        )
    )
    selection = OntologyCandidateSelection.bind(
        query=_QUERY,
        manifest=source.manifest,
        staged=source.staged,
        clauses=(OntologyCandidateClause(object_type="Resource"),),
    )
    with pytest.raises(ValueError, match="source content changed"):
        await resolve_candidate_selection(
            selection=selection,
            query=_QUERY,
            staged=source.staged,
            manifest=source.manifest,
            documents=source.build.documents,
            gateway=source.gateway,
            as_of=_NOW,
            deadline=asyncio.get_running_loop().time() + 5,
            resource_type_query_terms={},
        )


async def test_reassembly_rejects_document_mutation_even_with_the_same_metadata(
    source: _Source,
) -> None:
    context = prepare_candidate_proposal_context(**source.inputs())
    first = source.build.documents[0]
    changed = replace(
        source.build, documents=(replace(first, text=first.text + " "), *source.build.documents[1:])
    )
    inputs = source.inputs()
    inputs["build"] = changed
    with pytest.raises(CandidateContextError, match="invalid_source"):
        restore_candidate_proposal_context(context, **inputs)


@pytest.mark.parametrize(
    "outcome", ["selected", "clarify", "budget", "changed_binding", "corrupt", "unavailable"]
)
async def test_actual_diagnostic_adapter_consumes_the_complete_prepared_context(
    outcome: str,
) -> None:
    source = await _source(count=300)
    config = _candidate_config()
    assert config.plan_prompt_manifest is not None
    config = replace(
        config,
        timeout_seconds=5.0,
        plan_prompt_manifest=replace(
            config.plan_prompt_manifest,
            request_token_budget=(
                (config.plan_prompt_manifest.system_token_budget or 8192) + 1
                if outcome == "budget"
                else 200000
            ),
        ),
    )
    requests: list[httpx.Request] = []

    async def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if outcome == "unavailable":
            return httpx.Response(503, json={"error": {"code": "ServiceUnavailable"}})
        proposal = (
            {"status": "clarify", "reason": "unresolved_reference", "clauses": []}
            if outcome == "clarify"
            else {
                "status": "select",
                "reason": "conditions_proposed",
                "clauses": [
                    {
                        "object_type": "Resource",
                        "predicates": [],
                        "object_ids": None,
                        "quote": _QUERY,
                    }
                ],
            }
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(proposal)}}]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        model = AzureOpenAISemanticPlanningModel(
            identity=_Identity(),
            http_client=http,
            config=config,
            owner_loop=asyncio.get_running_loop(),
        )
        inputs = {
            **source.inputs(),
            "model_binding": model.candidate_proposal_binding_for_manifest(
                source.manifest, source.build
            ),
        }
        context = prepare_candidate_proposal_context(**inputs)
        assert context.payload_bytes > 65536
        if outcome == "changed_binding":
            model = AzureOpenAISemanticPlanningModel(
                identity=_Identity(),
                http_client=http,
                config=replace(config, max_tokens=1024),
                owner_loop=asyncio.get_running_loop(),
            )
        elif outcome == "corrupt":
            context = context.model_copy(update={"pages": context.pages[:-1]})
        inputs.pop("model_binding")
        if outcome in ("budget", "changed_binding", "corrupt", "unavailable"):
            reason = {
                "budget": "request_budget_exceeded",
                "changed_binding": "binding_changed",
                "corrupt": "context_corrupt",
                "unavailable": "model unavailable",
            }[outcome]
            with pytest.raises(ValueError, match=reason):
                await model.propose_prepared_candidate_selection(context=context, **inputs)
            assert len(requests) == (1 if outcome == "unavailable" else 0)
            return
        proposed = await model.propose_prepared_candidate_selection(context=context, **inputs)
    assert len(requests) == 1
    transmitted = json.loads(requests[0].content)["messages"][1]["content"]
    payload = json.loads(transmitted)["untrusted_input"]
    assert payload["documents"] == [
        {"document_id": document.rule_id, "content": json.loads(document.text)}
        for document in source.build.documents
    ]
    assert proposed.input_digest == payload["input_digest"] == context.context_digest
    if outcome == "clarify":
        assert proposed.proposal.status == "clarify"
        assert proposed.selection is None
        return
    assert proposed.selection is not None
    selected = await resolve_candidate_selection(
        selection=proposed.selection,
        query=_QUERY,
        staged=source.staged,
        manifest=source.manifest,
        documents=source.build.documents,
        gateway=source.gateway,
        as_of=_NOW,
        deadline=asyncio.get_running_loop().time() + 5,
        resource_type_query_terms={},
    )
    assert len(selected.documents) == 300
    assert selected.documents[-1].rule_id == "object:Resource:example-resource-00299"
    assert selected.query_receipt_digests


async def test_large_identity_enum_remains_an_explicit_unqualified_scale_block(
    source: _Source,
) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(AsyncMock())) as http:
        model = AzureOpenAISemanticPlanningModel(
            identity=_Identity(),
            http_client=http,
            config=_candidate_config(),
            owner_loop=asyncio.get_running_loop(),
        )
        with pytest.raises(ValueError, match="structured-output enum bound"):
            model.candidate_proposal_binding_for_manifest(source.manifest, source.build)
