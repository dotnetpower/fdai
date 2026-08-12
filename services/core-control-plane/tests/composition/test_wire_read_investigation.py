"""Production resource-state investigation shadow composition tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fdai.composition.wire_read_investigation import build_resource_state_shadow_hook
from fdai.core.read_investigation.shadow_sink import StateStoreShadowComparisonSink
from fdai.delivery.read_investigation import InventoryReadInvestigationProvider
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog
from fdai.rule_catalog.schema.property_semantic import empty_property_semantic_registry
from fdai.shared.contracts.models import (
    LogicExecutionClass,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore, InMemoryStateStore

NOW = datetime(2026, 8, 12, 1, tzinfo=UTC)
RESOURCE_REF = "resource:vm-01"


class _GraphReader:
    async def __call__(
        self,
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        del scope, depth, link_types, limit
        resources = [
            {
                "id": RESOURCE_REF,
                "name": "vm-01",
                "type": "compute.vm",
                "props": {"status": "running"},
            }
        ]
        if root is not None:
            resources = [item for item in resources if item["id"] == root]
        return {
            "snapshot_id": "snapshot-1",
            "snapshot_at": NOW.isoformat(),
            "freshness": "fresh",
            "resources": resources,
            "truncated": False,
        }


async def _context(resource_ref: str) -> dict[str, Any] | None:
    if resource_ref != RESOURCE_REF:
        return None
    return {
        "resource_id": RESOURCE_REF,
        "resource_type": "compute.vm",
        "props": {"status": "running"},
    }


def _object_type() -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "type": PropertyDecl(type=PropertyType.STRING, required=True),
            "properties": PropertyDecl(type=PropertyType.OBJECT, required=True),
        },
    )


def _function_type() -> OntologyFunctionType:
    return OntologyFunctionType(
        name="inventory.select_resources",
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest="sha256:" + "f" * 64,
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["object_set"],
            "properties": {"object_set": {"type": "object"}},
        },
        output_schema={"type": "object"},
        read_sets=["ontology.object-set"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        purpose_bindings=["operations-review"],
        network_allowed=False,
        credentials_allowed=False,
    )


async def _hook(*, complete_metadata: bool = True):  # type: ignore[no-untyped-def]
    object_type = _object_type()
    function_type = _function_type()
    release = build_ontology_release(
        object_types=(object_type,),
        function_types=(function_type,),
    )
    store = InMemoryOntologyInstanceStore(object_types=(object_type,), link_types=())
    metadata = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="inventory-provider",
        source_revision="snapshot-1",
        effective_at=NOW,
        recorded_at=NOW,
        evidence_cutoff=NOW,
        freshness_ceiling_seconds=300,
        completeness=1.0,
        synthetic=False,
        evidence_refs=("inventory-snapshot:snapshot-1",),
    )
    provider_properties: dict[str, Any] = {"state": "running"}
    if complete_metadata:
        provider_properties[STATE_FACT_METADATA_PROPERTY] = metadata.to_mapping()
    await store.upsert_object(
        OntologyObjectRecord(
            id=RESOURCE_REF,
            object_type="Resource",
            properties={
                "id": RESOURCE_REF,
                "type": "compute.vm",
                "properties": provider_properties,
            },
        )
    )
    state_store = InMemoryStateStore()
    hook = build_resource_state_shadow_hook(
        provider=InventoryReadInvestigationProvider(
            graph_reader=_GraphReader(),
            context_reader=_context,
            clock=lambda: NOW,
            monotonic=lambda: 1.0,
        ),
        shadow_sink=StateStoreShadowComparisonSink(store=state_store),
        ontology_release=release,
        ontology_catalog=OntologyCatalog(
            object_types=(object_type,),
            interface_types=(),
            interface_implementations=(),
            link_types=(),
            action_types=(),
            function_types=(function_type,),
            property_semantics=empty_property_semantic_registry(),
        ),
        ontology_store=store,
        clock=lambda: NOW,
    )
    return hook, state_store


async def test_resource_state_runs_exact_query_profile_and_records_match() -> None:
    hook, state_store = await _hook()

    result = await hook(
        "What is the current state of vm-01?",
        {"session_id": "session-one", "user_id": "reader-one"},
    )

    assert result is not None
    assert result["answer"] == "vm-01 is currently running."
    assert result["facts"]["state"] == "running"
    records = await state_store.read_states("read-investigation-shadow:", limit=10)
    assert result["facts"]["shadow_outcome"] == "match", records[0]["receipt"]["reasons"]
    assert result["facts"]["shadow_persistence"] == "recorded"
    assert len(records) == 1
    assert records[0]["receipt"]["execution_authority"] is False


async def test_semantic_evidence_failure_does_not_replace_authoritative_answer() -> None:
    hook, _ = await _hook(complete_metadata=False)

    result = await hook(
        "vm-01의 현재 상태는?",
        {"session_id": "session-one", "user_id": "reader-one"},
    )

    assert result is not None
    assert result["answer"] == "vm-01의 현재 상태는 running입니다."
    assert result["facts"]["state"] == "running"
    assert result["facts"]["shadow_outcome"] == "error"
    assert result["facts"]["execution_authority"] is False


async def test_non_resource_state_intent_is_not_claimed() -> None:
    hook, _ = await _hook()

    assert (
        await hook(
            "Show the recent Activity Log for vm-01",
            {"session_id": "session-one", "user_id": "reader-one"},
        )
        is None
    )
