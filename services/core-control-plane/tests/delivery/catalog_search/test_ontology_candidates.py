"""Current-graph authorization for inactive ontology index candidates."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from fdai.agents import (
    ContextIndexMessage,
    PantheonRuntime,
    StateStoreAuditChainAdapter,
    recover_context_index_publications,
    request_context_index,
)
from fdai.agents.saga import Saga
from fdai.composition.semantic_query_instance_candidates import declare_instance_candidate_query
from fdai.core.conversation.semantic_manifest import semantic_principal_scope_digest
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import build_query_manifest
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.instance_candidate_queries import instance_candidates_function
from fdai.core.ontology_platform.interfaces import compile_interfaces
from fdai.core.ontology_platform.object_sets import ObjectSetService
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.delivery.catalog_search.ontology_candidate_authorization import (
    reauthorize_ontology_candidates,
)
from fdai.delivery.catalog_search.ontology_candidate_reader import OntologyInstanceCandidateReader
from fdai.delivery.catalog_search.ontology_index_lifecycle import IndexScope, IndexTransition
from fdai.delivery.catalog_search.ontology_index_workers import (
    IndexPreparationRequest,
    OntologyContextIndexWorkers,
)
from fdai.delivery.catalog_search.ontology_snapshot_store import OntologyGenerationSnapshotStore
from fdai.delivery.catalog_search.ontology_snapshot_validation import (
    validate_snapshot_against_current_graph,
)
from fdai.delivery.catalog_search.ontology_vector_store import OntologyVectorSnapshotStore
from fdai.delivery.catalog_search.ranking import CatalogRankingPolicy
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog
from fdai.rule_catalog.schema.property_semantic import empty_property_semantic_registry
from fdai.runtime.ontology_index_runtime import build_ontology_index_runtime
from fdai.shared.contracts.models import CeilingRole, OntologyObjectType, PropertyDecl, PropertyType
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 9, 21, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64


@pytest.mark.parametrize(
    "drift",
    [
        "none",
        "value",
        "deleted",
        "source",
        "forged",
        "duplicate",
        "scope_isolation",
        "runtime_enrollment",
    ],
)
async def test_candidate_facts_must_match_the_current_authorized_graph(
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declaration = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "label": PropertyDecl(type=PropertyType.STRING),
            "private_note": PropertyDecl(type=PropertyType.STRING, access_scope=CeilingRole.OWNER),
        },
    )
    release = build_ontology_release(object_types=(declaration,))
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(declaration,),
    )
    store = InMemoryOntologyInstanceStore(
        object_types=(declaration,),
        link_types=(),
        source_generation="source-1",
    )
    record = OntologyObjectRecord(
        id="example-resource",
        object_type="Resource",
        properties={"id": "example-resource", "label": "observed", "private_note": "restricted"},
    )
    await store.upsert_object(record)
    gateway = SecuredObjectSetQueryGateway(
        service=ObjectSetService(
            store=store,
            interfaces=compile_interfaces(
                interfaces=(), implementations=(), object_types=(declaration,)
            ),
            object_type_names=frozenset({"Resource"}),
        ),
        object_types={"Resource": declaration},
        ontology_release=release,
        evaluation_cutoff=lambda: NOW,
    )
    state = InMemoryStateStore()
    snapshots = OntologyGenerationSnapshotStore(state)
    staged = await snapshots.stage_manifest_from_gateway(
        gateway=gateway,
        manifest=manifest,
        as_of=NOW,
        expected_source_generation="source-1",
        embedding_space_id="test-space",
        embedding_model_version="test-model",
        embedding_dimension=1,
    )
    build = await snapshots.read(
        staged.snapshot_digest,
        manifest=manifest,
        source_generation=staged.source_generation,
        source_projection_digest=staged.source_projection_digest,
    )
    assert build is not None
    candidates = tuple(item for item in build.documents if item.document_kind == "ontology_object")
    assert all("restricted" not in item.text for item in candidates)

    class Embedder:
        unavailable = False
        calls = 0
        embedding_space_id = "test-space"
        embedding_model_version = "test-model"
        dim = 1

        async def embed(self, text: str) -> tuple[float, ...]:
            self.calls += 1
            if self.unavailable:
                raise RuntimeError("private provider message")
            return (1.0,)

    embedder = Embedder()
    vectors = OntologyVectorSnapshotStore(
        state,
        embedder=embedder,
        embedding_space_id="test-space",
        embedding_model_version="test-model",
        embedding_dimension=1,
    )
    vector_digest = await vectors.stage(
        snapshots=snapshots,
        snapshot_digest=staged.snapshot_digest,
        manifest=manifest,
        source_generation=staged.source_generation,
        source_projection_digest=staged.source_projection_digest,
    )
    validation = await validate_snapshot_against_current_graph(
        snapshots=snapshots,
        staged=staged,
        gateway=gateway,
        manifest=manifest,
        as_of=NOW,
        embedding_space_id="test-space",
        embedding_model_version="test-model",
        embedding_dimension=1,
        validator_id="Heimdall",
    )
    reader = OntologyInstanceCandidateReader(
        snapshots=snapshots,
        vectors=vectors,
        ranking_policy=CatalogRankingPolicy(),
    )
    await reader.prepare(
        staged=staged,
        vector_digest=vector_digest,
        manifest=manifest,
        validation=validation,
    )
    read_state = AsyncMock(wraps=state.read_state)
    monkeypatch.setattr(state, "read_state", read_state)
    if drift == "runtime_enrollment":
        principal = Principal(
            id="example-reader", role=Role.READER, groups=frozenset({"example-readers"})
        )
        context = FunctionInvocationContext(
            caller_agent="Bragi",
            principal_ref=principal.id,
            principal_groups=tuple(principal.groups),
            principal_scope_digest=semantic_principal_scope_digest(
                principal=principal, purpose="operations-review"
            ),
            purposes=("operations-review",),
        )

        runtime_catalog = declare_instance_candidate_query(
            OntologyCatalog(
                object_types=(declaration,),
                link_types=(),
                interface_types=(),
                interface_implementations=(),
                action_types=(),
                property_semantics=empty_property_semantic_registry(),
            )
        )
        runtime_release = build_ontology_release(
            object_types=runtime_catalog.object_types,
            function_types=operational_function_types(runtime_catalog.function_types),
        )
        options = dict(
            store=state,
            ontology_store=store,
            catalog=runtime_catalog,
            release=runtime_release,
            embedder=embedder,
            clock=lambda: NOW,
        )
        monkeypatch.setattr(embedder, "embedding_model_version", "")
        assert build_ontology_index_runtime(**options) is None
        monkeypatch.setattr(embedder, "embedding_model_version", "test-model")
        coordinator = build_ontology_index_runtime(**options)
        assert coordinator is not None and coordinator.workers is not None
        scoped_reader = coordinator.workers._reader
        indexed_runtime = PantheonRuntime.build(
            provider=InMemoryEventBus(),
            raw_event_topic="raw-events",
            saga=Saga(audit_chain=StateStoreAuditChainAdapter(state)),
            context_index_workers=coordinator.workers.bindings,
        )
        with pytest.raises(PermissionError, match="principal scope mismatch"):
            await coordinator.query(
                record.id, 10, context.model_copy(update={"principal_scope_digest": DIGEST})
            )
        assert not coordinator._enrollments
        calls = embedder.calls
        with pytest.raises(ValueError, match="no current active"):
            await coordinator.query(record.id, 10, context)
        assert embedder.calls == calls
        original_publish = request_context_index
        ingress_attempts = 0

        async def lose_first_ingress(
            runtime: PantheonRuntime, message: ContextIndexMessage
        ) -> None:
            nonlocal ingress_attempts
            ingress_attempts += 1
            if ingress_attempts > 1:
                await original_publish(runtime, message)

        monkeypatch.setattr(
            "fdai.runtime.ontology_index_runtime.request_context_index", lose_first_ingress
        )
        await coordinator.reconcile(indexed_runtime)
        await coordinator.reconcile(indexed_runtime)
        assert ingress_attempts == 2
        monkeypatch.setattr(
            "fdai.runtime.ontology_index_runtime.request_context_index", original_publish
        )
        assert (
            len([key for key in state._state if key.startswith("ontology-index-request:v1:")]) == 1
        )
        request_key = next(
            key for key in state._state if key.startswith("ontology-index-request:v1:")
        )
        retained_request = state._state[request_key]
        substituted = ContextIndexMessage.create(
            phase="prepare",
            correlation_id=retained_request["correlation_id"],
            body={**retained_request["body"], "source_generation": "substituted-source"},
        )
        await state.write_state(request_key, substituted.model_dump(mode="json"))
        coordinator._attempted.clear()
        with pytest.raises(ValueError, match="request scope mismatch"):
            await coordinator.reconcile(indexed_runtime)
        await state.write_state(request_key, retained_request)
        for _ in range(8):
            await indexed_runtime.run()
        value = await coordinator.query(record.id, 10, context)
        assert value["candidates"][0]["properties"]["label"] == "observed"
        calls = embedder.calls
        with pytest.raises(ValueError, match="ranking is not qualified"):
            await coordinator.query("observed resources", 10, context)
        assert embedder.calls == calls
        scoped_reader.invalidate()
        await coordinator.reconcile(indexed_runtime)
        assert embedder.calls == calls
        assert (await coordinator.query(record.id, 10, context))["candidates"] == value[
            "candidates"
        ]
        await store.upsert_object(
            replace(record, properties={**record.properties, "label": "replacement"})
        )
        active_scope = next(iter(coordinator._enrollments.values())).scope
        current_pointer = await coordinator.workers.lifecycle.read(active_scope)
        assert current_pointer.terminal is not None
        terminal_key = (
            "ontology-context-evidence:v1:terminal-seal:" + current_pointer.terminal.command.digest
        )
        terminal_value = state._state.pop(terminal_key)
        before_requests = {
            key for key in state._state if key.startswith("ontology-index-request:v1:")
        }
        try:
            await coordinator.reconcile(indexed_runtime)
            assert {
                key for key in state._state if key.startswith("ontology-index-request:v1:")
            } == before_requests
        finally:
            await state.write_state(terminal_key, terminal_value)
        ready_key = next(
            key
            for key, value in state._state.items()
            if ":Muninn:result:" in key
            and value["result"]["phase"] == "ready"
            and value["result"]["body"]["revision"] == current_pointer.revision
        )
        ready_value = state._state.pop(ready_key)
        try:
            await coordinator.reconcile(indexed_runtime)
            assert {
                key for key in state._state if key.startswith("ontology-index-request:v1:")
            } == before_requests
        finally:
            await state.write_state(ready_key, ready_value)
        await coordinator.reconcile(indexed_runtime)
        for _ in range(8):
            await indexed_runtime.run()
        with pytest.raises(ValueError, match="no current active"):
            await coordinator.query(record.id, 10, context)
        await coordinator.reconcile(indexed_runtime)
        for _ in range(8):
            await indexed_runtime.run()
        assert (await coordinator.query(record.id, 10, context))["candidates"][0]["properties"][
            "label"
        ] == "replacement"
        for generation_number in range(9):
            expected_label = f"replacement-{generation_number}"
            await store.upsert_object(
                replace(record, properties={**record.properties, "label": expected_label})
            )
            for _ in range(3):
                await coordinator.reconcile(indexed_runtime)
                for _ in range(8):
                    await indexed_runtime.run()
            refreshed = await coordinator.query(record.id, 10, context)
            assert refreshed["candidates"][0]["properties"]["label"] == expected_label
        assert any(key.endswith(":retired") for key in state._state)
        assert await state.verify_chain()
        monkeypatch.setattr(coordinator, "_clock", lambda: NOW + timedelta(minutes=5))
        await coordinator.reconcile(indexed_runtime)
        assert not coordinator._enrollments
        assert not coordinator._attempted
        assert not scoped_reader._prepared
        return
    if drift == "scope_isolation":
        second_manifest = build_query_manifest(
            release=release,
            principal_role=CeilingRole.READER,
            purposes=("operations-review",),
            principal_scope_digest="sha256:" + "b" * 64,
            object_types=(declaration,),
        )
        second_staged = await snapshots.stage_manifest_from_gateway(
            gateway=gateway,
            manifest=second_manifest,
            as_of=NOW,
            expected_source_generation="source-1",
            embedding_space_id="test-space",
            embedding_model_version="test-model",
            embedding_dimension=1,
        )
        second_vectors = await vectors.stage(
            snapshots=snapshots,
            snapshot_digest=second_staged.snapshot_digest,
            manifest=second_manifest,
            source_generation=second_staged.source_generation,
            source_projection_digest=second_staged.source_projection_digest,
        )
        second_validation = await validate_snapshot_against_current_graph(
            snapshots=snapshots,
            staged=second_staged,
            gateway=gateway,
            manifest=second_manifest,
            as_of=NOW,
            embedding_space_id="test-space",
            embedding_model_version="test-model",
            embedding_dimension=1,
            validator_id="Heimdall",
        )
        first_args = dict(
            staged=staged, vector_digest=vector_digest, manifest=manifest, validation=validation
        )
        second_args = dict(
            staged=second_staged,
            vector_digest=second_vectors,
            manifest=second_manifest,
            validation=second_validation,
        )
        await reader.prepare(**second_args)
        for expected_manifest, expected_staged in (
            (manifest, staged),
            (second_manifest, second_staged),
        ):
            found = await reader.search(
                record.id,
                staged=expected_staged,
                manifest=expected_manifest,
                gateway=gateway,
                as_of=NOW,
            )
            assert found.authorized is not None
            assert (
                found.authorized.principal_scope_digest
                == expected_manifest.coverage_receipt.principal_scope_digest
            )
        reader.invalidate(
            principal_scope_digest=second_manifest.coverage_receipt.principal_scope_digest
        )
        assert (
            await reader.search(
                record.id, staged=staged, manifest=manifest, gateway=gateway, as_of=NOW
            )
        ).authorized is not None
        with pytest.raises(ValueError, match="not prepared"):
            await reader.search(
                record.id,
                staged=second_staged,
                manifest=second_manifest,
                gateway=gateway,
                as_of=NOW,
            )

        load = reader._load
        entered, proceed = asyncio.Event(), asyncio.Event()

        async def paused_load(*args: object) -> object:
            if args[0] == staged:
                entered.set()
                await proceed.wait()
            return await load(*args)

        monkeypatch.setattr(reader, "_load", paused_load)
        async with asyncio.timeout(2):
            async with asyncio.TaskGroup() as group:
                group.create_task(reader.prepare(**first_args))
                await entered.wait()
                await reader.prepare(**second_args)
                proceed.set()
        entered.clear()
        proceed.clear()
        async with asyncio.timeout(2):
            pending = asyncio.create_task(reader.prepare(**first_args))
            try:
                await entered.wait()
            finally:
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
        await reader.prepare(**second_args)
        monkeypatch.setattr(reader, "_load", load)
        assert (
            await reader.search(
                record.id, staged=staged, manifest=manifest, gateway=gateway, as_of=NOW
            )
        ).authorized is not None
        for capacity, scopes, documents in (("scope", 1, 20_000), ("document", 2, 1)):
            bounded = OntologyInstanceCandidateReader(
                snapshots=snapshots,
                vectors=vectors,
                ranking_policy=CatalogRankingPolicy(),
                max_prepared_scopes=scopes,
                max_prepared_documents=documents,
            )
            await bounded.prepare(**first_args)
            with pytest.raises(ValueError, match=f"{capacity} capacity exceeded"):
                await bounded.prepare(**second_args)
            assert (
                await bounded.search(
                    record.id, staged=staged, manifest=manifest, gateway=gateway, as_of=NOW
                )
            ).authorized is not None
        return
    if drift == "value":
        await store.upsert_object(
            replace(record, properties={**record.properties, "label": "changed"})
        )
    elif drift == "deleted":
        await store.delete_object(record.id)
    elif drift == "source":
        staged = replace(staged, source_generation="source-2")
    elif drift == "forged":
        candidates = (
            replace(candidates[0], text=candidates[0].text.replace("observed", "invented")),
        )
    elif drift == "duplicate":
        candidates = (*candidates, *candidates)
    operation = reauthorize_ontology_candidates(
        candidates=candidates,
        staged=staged,
        manifest=manifest,
        gateway=gateway,
        as_of=NOW,
    )
    if drift != "none":
        with pytest.raises(ValueError):
            await operation
        if drift in {"value", "deleted", "source"}:
            with pytest.raises(ValueError):
                await reader.search(
                    record.id,
                    staged=staged,
                    manifest=manifest,
                    gateway=gateway,
                    as_of=NOW,
                )
        return
    result = await operation
    assert [item.id for item in result.objects] == [record.id]
    assert result.objects[0].properties == {"id": record.id, "label": "observed"}
    assert len(result.query_receipt_digests) == 1
    assert result.principal_scope_digest == DIGEST
    assert result.result_digest.startswith("sha256:")
    with pytest.raises(TypeError):
        result.objects[0].properties["label"] = "invented"  # type: ignore[index]

    calls = embedder.calls
    embedder.unavailable = True
    exact = await reader.search(
        record.id,
        staged=staged,
        manifest=manifest,
        gateway=gateway,
        as_of=NOW,
    )
    assert exact.authorized == result
    assert exact.execution_authority is False
    assert embedder.calls == calls
    with pytest.raises(ValueError, match="provider unavailable"):
        await reader.search(
            "observed resources",
            staged=staged,
            manifest=manifest,
            gateway=gateway,
            as_of=NOW,
        )
    embedder.unavailable = False
    semantic = await reader.search(
        "observed resources",
        staged=staged,
        manifest=manifest,
        gateway=gateway,
        as_of=NOW,
    )
    assert semantic.authorized == result
    read_state.assert_not_awaited()

    scope = IndexScope(
        principal_scope_digest=DIGEST,
        role=CeilingRole.READER,
        purpose="operations-review",
    )

    async def resolve_source(requested_scope: IndexScope) -> tuple[object, object]:
        assert requested_scope == scope
        return manifest, gateway

    owned_reader = OntologyInstanceCandidateReader(
        snapshots=snapshots,
        vectors=vectors,
        ranking_policy=CatalogRankingPolicy(),
    )
    workers = OntologyContextIndexWorkers(
        store=state,
        snapshots=snapshots,
        vectors=vectors,
        reader=owned_reader,
        resolve_source=resolve_source,
        clock=lambda: NOW,
        embedding_space_id="test-space",
        embedding_model_version="test-model",
        embedding_dimension=1,
    )
    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="raw-events",
        saga=Saga(audit_chain=StateStoreAuditChainAdapter(state)),
        context_index_workers=workers.bindings,
    )
    prepare_request = ContextIndexMessage.create(
        phase="prepare",
        correlation_id="example-index-request",
        body=IndexPreparationRequest(
            scope=scope,
            source_generation="source-1",
            expected_revision=0,
            expected_active_digest=None,
            requested_at=NOW,
        ).model_dump(mode="json"),
    )
    bounded_source = AsyncMock(wraps=resolve_source)
    monkeypatch.setattr(workers, "_resolve_source", bounded_source)
    initial_embedding_calls = embedder.calls
    for offset in (-120, 6):
        invalid_request = ContextIndexMessage.create(
            phase="prepare",
            correlation_id=f"example-deadline-{offset}",
            body={
                **prepare_request.body,
                "requested_at": (NOW + timedelta(seconds=offset)).isoformat(),
            },
        )
        with pytest.raises(ValueError, match="original deadline"):
            await workers.muninn(invalid_request)
    bounded_source.assert_not_awaited()
    assert embedder.calls == initial_embedding_calls
    source_cancelled = asyncio.Event()

    async def hanging_source(_scope: IndexScope) -> object:
        try:
            await asyncio.Future()
        finally:
            source_cancelled.set()

    monkeypatch.setattr(workers, "_resolve_source", hanging_source)
    monkeypatch.setattr(workers, "_clock", lambda: NOW + timedelta(seconds=119.99))
    with pytest.raises(TimeoutError):
        await workers.muninn(prepare_request)
    assert source_cancelled.is_set()
    assert (await workers.lifecycle.read(scope)).revision == 0
    monkeypatch.setattr(workers, "_resolve_source", resolve_source)
    monkeypatch.setattr(workers, "_clock", lambda: NOW)
    await request_context_index(runtime, prepare_request)
    for _ in range(8):
        await runtime.run()
    pointer = await workers.lifecycle.read(scope)
    assert pointer.revision == 1
    assert pointer.active is not None
    assert pointer.active.snapshot_digest == staged.snapshot_digest
    assert pointer.terminal is not None
    query_function = instance_candidates_function(
        workers.query_function,
        ontology_release_digest=manifest.release_digest,
    )
    original_resolver = workers._resolve_source
    source_resolution = AsyncMock(wraps=original_resolver)
    workers._resolve_source = source_resolution
    function_output = await query_function(
        {"query": record.id, "limit": 20},
        FunctionInvocationContext(
            caller_agent="Bragi",
            principal_ref="example-reader",
            principal_scope_digest=DIGEST,
            purposes=("operations-review",),
        ),
    )
    assert isinstance(function_output, dict)
    assert function_output["candidates"][0]["id"] == record.id
    assert function_output["exhaustive"] is False
    assert function_output["execution_authority"] is False
    assert function_output["ontology_release_digest"] == manifest.release_digest
    source_resolution.assert_awaited_once_with(scope)
    workers._resolve_source = original_resolver
    assert (await workers.search_current(record.id, scope=scope, as_of=NOW)).authorized == result
    seal_key = "ontology-context-evidence:v1:terminal-seal:" + pointer.terminal.command.digest
    terminal_seal = state._state.pop(seal_key)
    owned_reader.invalidate(principal_scope_digest=DIGEST)
    with pytest.raises(ValueError, match="terminal audit"):
        await workers.search_current(record.id, scope=scope, as_of=NOW)
    with pytest.raises(ValueError, match="terminal audit"):
        await workers.restore_current(scope)
    await state.write_state(seal_key, terminal_seal)
    calls_before_recovery = embedder.calls
    assert await workers.restore_current(scope)
    assert embedder.calls == calls_before_recovery
    assert await workers.lifecycle.read(scope) == pointer
    validation_key = (
        "ontology-context-evidence:v1:validation:" + pointer.active.validation_receipt_digest
    )
    retained_validation = state._state.pop(validation_key)
    with pytest.raises(ValueError, match="independent validation is unavailable"):
        await workers.restore_current(scope)
    await state.write_state(
        validation_key,
        {
            **retained_validation,
            "prepared": {**retained_validation["prepared"], "vector_digest": DIGEST},
        },
    )
    with pytest.raises(ValueError, match="validation target mismatch"):
        await workers.restore_current(scope)
    await state.write_state(validation_key, retained_validation)
    pointer_read = workers.lifecycle.read
    monkeypatch.setattr(
        workers.lifecycle,
        "read",
        AsyncMock(
            side_effect=[pointer, pointer.model_copy(update={"revision": pointer.revision + 1})]
        ),
    )
    with pytest.raises(ValueError, match="lost its current pointer identity"):
        await workers.restore_current(scope)
    monkeypatch.setattr(workers.lifecycle, "read", pointer_read)
    with pytest.raises(ValueError, match="not prepared"):
        await workers.search_current(record.id, scope=scope, as_of=NOW)
    assert await workers.restore_current(scope)
    assert (
        await owned_reader.search(
            record.id,
            staged=staged,
            manifest=manifest,
            gateway=gateway,
            as_of=NOW,
        )
    ).authorized == result
    calls = embedder.calls
    await request_context_index(runtime, prepare_request)
    for _ in range(8):
        await runtime.run()
    assert await workers.lifecycle.read(scope) == pointer
    assert embedder.calls == calls
    assert await state.verify_chain()
    assert await recover_context_index_publications(runtime.agents, workers.bindings) == 0
    pending_key = next(
        key
        for key in state._state
        if ":Muninn:result:" in key and state._state[key]["result"]["phase"] == "prepared"
    )
    pending = dict(state._state[pending_key])
    pending.update(state="pending", revision=1)
    await state.write_state(pending_key, pending)
    state._state.pop(
        "ontology-context-evidence:v1:publication:" + pending["result"]["idempotency_key"]
    )
    assert await recover_context_index_publications(runtime.agents, workers.bindings) == 1
    for _ in range(8):
        await runtime.run()
    assert await recover_context_index_publications(runtime.agents, workers.bindings) == 0
    assert await workers.lifecycle.read(scope) == pointer
    assert embedder.calls == calls

    result_keys = [key for key in state._state if ":Muninn:result:" in key]
    prepared_result = next(
        state._state[key]["result"]
        for key in result_keys
        if state._state[key]["result"]["phase"] == "prepared"
    )
    missing_message_key = (
        "ontology-context-evidence:v1:message:" + prepared_result["idempotency_key"]
    )
    state._state.pop(missing_message_key)
    replayed = await workers.muninn(prepare_request)
    assert await state.read_state(missing_message_key) == replayed.model_dump(mode="json")

    await store.upsert_object(
        replace(record, properties={**record.properties, "label": "replacement"})
    )
    replacement_request = ContextIndexMessage.create(
        phase="prepare",
        correlation_id="example-source-drift-request",
        body=IndexPreparationRequest(
            scope=scope,
            source_generation="source-1",
            expected_revision=1,
            expected_active_digest=pointer.active.digest,
            requested_at=NOW,
        ).model_dump(mode="json"),
    )
    prepared_message = await workers.muninn(replacement_request)
    monkeypatch.setattr(workers, "_clock", lambda: NOW + timedelta(seconds=120))
    with pytest.raises(ValueError, match="original deadline"):
        await workers.heimdall(prepared_message)
    monkeypatch.setattr(workers, "_clock", lambda: NOW + timedelta(seconds=1))
    monkeypatch.setattr(gateway, "_evaluation_cutoff", lambda: NOW + timedelta(seconds=1))
    validated_message = await workers.heimdall(prepared_message)
    monkeypatch.setattr(workers, "_clock", lambda: NOW + timedelta(seconds=120))
    with pytest.raises(ValueError, match="original deadline"):
        await workers.muninn(validated_message)
    monkeypatch.setattr(workers, "_clock", lambda: NOW)
    monkeypatch.setattr(gateway, "_evaluation_cutoff", lambda: NOW)
    intent_message = await workers.muninn(validated_message)
    assert IndexTransition.model_validate(
        intent_message.body["command"]
    ).expires_at == NOW + timedelta(seconds=120)
    sealed_message = await workers.saga(intent_message)
    await store.upsert_object(replace(record, properties={**record.properties, "label": "changed"}))
    with pytest.raises(ValueError, match="content mismatch"):
        await workers.muninn(sealed_message)
    assert await workers.lifecycle.read(scope) == pointer
    await store.upsert_object(record)

    async def deliver_transition(operation: str, target: object) -> None:
        current = await workers.lifecycle.read(scope)
        command = IndexTransition.model_validate(
            {
                "command_id": f"example-{operation}-{current.revision}",
                "scope": scope,
                "operation": operation,
                "expected_revision": current.revision,
                "expected_active_digest": current.active.digest if current.active else None,
                "target": target,
                "requested_at": NOW,
                "expires_at": NOW + timedelta(seconds=60),
            }
        )
        request = ContextIndexMessage.create(
            phase="transition",
            correlation_id=command.command_id,
            body=command.model_dump(mode="json"),
        )
        await request_context_index(runtime, request)
        for _ in range(8):
            await runtime.run()

    scoped_invalidation = Mock(wraps=owned_reader.invalidate)
    monkeypatch.setattr(owned_reader, "invalidate", scoped_invalidation)
    await deliver_transition("invalidate", None)
    scoped_invalidation.assert_called_once_with(principal_scope_digest=DIGEST)
    assert (await workers.lifecycle.read(scope)).active is None
    with pytest.raises(ValueError, match="no current active"):
        await workers.search_current(record.id, scope=scope, as_of=NOW)
    await deliver_transition("rollback", pointer.active)
    assert (await workers.lifecycle.read(scope)).active == pointer.active
    rolled_back = (await workers.search_current(record.id, scope=scope, as_of=NOW)).authorized
    assert rolled_back is not None
    assert rolled_back.objects[0].properties == result.objects[0].properties
    assert rolled_back.objects[0].revision > result.objects[0].revision

    materialize = gateway.materialize

    async def invalidate_during_query(*args: object, **kwargs: object) -> object:
        output = await materialize(*args, **kwargs)  # type: ignore[arg-type]
        reader.invalidate()
        return output

    monkeypatch.setattr(gateway, "materialize", AsyncMock(side_effect=invalidate_during_query))
    with pytest.raises(ValueError, match="invalidated"):
        await reader.search(
            record.id,
            staged=staged,
            manifest=manifest,
            gateway=gateway,
            as_of=NOW,
        )

    read_vectors = vectors.read

    async def invalidate_during_prepare(*args: object, **kwargs: object) -> object:
        output = await read_vectors(*args, **kwargs)  # type: ignore[arg-type]
        reader.invalidate()
        return output

    monkeypatch.setattr(vectors, "read", AsyncMock(side_effect=invalidate_during_prepare))
    with pytest.raises(ValueError, match="invalidated"):
        await reader.prepare(
            staged=staged,
            vector_digest=vector_digest,
            manifest=manifest,
            validation=validation,
        )
    with pytest.raises(ValueError, match="not prepared"):
        await reader.search(
            record.id,
            staged=staged,
            manifest=manifest,
            gateway=gateway,
            as_of=NOW,
        )
    monkeypatch.setattr(gateway, "materialize", materialize)
    monkeypatch.setattr(vectors, "read", read_vectors)
    await state.write_state("catalog-search:active", {"generation": "retained-rule"})
    await deliver_transition("invalidate", None)
    projection_acquire = Mock(wraps=workers._projection_lock.acquire)
    monkeypatch.setattr(workers._projection_lock, "acquire", projection_acquire)
    await deliver_transition("retire", pointer.active)
    projection_acquire.assert_called_once_with(f"ontology-index-projection:{scope.digest}")
    retired = await workers.lifecycle.read(scope)
    assert retired.active is None
    assert pointer.active not in retired.retained
    assert (
        await snapshots.read(
            staged.snapshot_digest,
            manifest=manifest,
            source_generation=staged.source_generation,
            source_projection_digest=staged.source_projection_digest,
        )
        is None
    )
    with pytest.raises(ValueError, match="retired"):
        await snapshots.stage(
            build=build,
            manifest=manifest,
            source_generation=staged.source_generation,
            source_projection_digest=staged.source_projection_digest,
        )
    assert await state.read_state("catalog-search:active") == {"generation": "retained-rule"}
    assert await state.verify_chain()
