"""Server-anchored inventory impact query tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.inventory_impact_queries import (
    INVENTORY_IMPACT_FUNCTION_NAME,
    InventoryImpactContext,
    InventoryImpactEdge,
    InventoryImpactPage,
    inventory_impact_function,
    inventory_impact_function_type,
)
from fdai.shared.contracts.models import CeilingRole, OntologyLinkType, OntologyObjectType
from fdai.shared.ontology.release import build_ontology_release


class _Anchor:
    calls = 0

    async def resolve(self, context: FunctionInvocationContext) -> str | None:
        self.calls += 1
        assert context.caller_role is CeilingRole.READER
        return "opaque:root"


class _Reader:
    def __init__(self, release_digest: str) -> None:
        self.release_digest = release_digest

    async def read_context(self):
        return InventoryImpactContext(
            snapshot_ref="snapshot:active",
            observed_at=datetime(2026, 8, 19, tzinfo=UTC),
            ontology_release_digest=self.release_digest,
        )

    async def resource_exists(self, *, snapshot_ref: str, resource_ref: str) -> bool:
        return snapshot_ref == "snapshot:active" and resource_ref == "opaque:root"

    async def read_outgoing(
        self,
        *,
        snapshot_ref: str,
        source_refs: tuple[str, ...],
        link_types: tuple[str, ...],
        limit: int,
    ) -> InventoryImpactPage:
        if source_refs == ("opaque:root",):
            return InventoryImpactPage(
                edges=(InventoryImpactEdge("opaque:root", "opaque:child", "contains"),),
                resource_refs=frozenset({"opaque:root", "opaque:child"}),
                truncated=False,
            )
        return InventoryImpactPage(edges=(), resource_refs=frozenset(source_refs), truncated=False)


def _runtime():
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={},
    )
    link = OntologyLinkType(
        schema_version="1.0.0",
        name="contains",
        version="1.0.0",
        from_type="Resource",
        to_type="Resource",
        cardinality="one_to_many",
    )
    function_type = inventory_impact_function_type()
    release = build_ontology_release(
        object_types=(resource,),
        link_types=(link,),
        function_types=(function_type,),
    )
    anchor = _Anchor()
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        function_type,
        inventory_impact_function(
            release,
            declared_link_types=frozenset({"contains"}),
            reader=_Reader(release.digest),
            anchor_resolver=anchor,
        ),
    )
    return registry, anchor


def _context() -> FunctionInvocationContext:
    return FunctionInvocationContext(
        caller_agent="Bragi",
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
    )


async def test_inventory_impact_uses_server_anchor_and_preserves_unverified_edges() -> None:
    registry, anchor = _runtime()

    result = await registry.invoke(
        INVENTORY_IMPACT_FUNCTION_NAME,
        {"depth": 1, "link_types": ["contains"]},
        context=_context(),
    )

    assert anchor.calls == 1
    assert result["target_ref"] == "opaque:root"
    assert result["affected_count"] == 1
    assert result["edges"][0]["verification_status"] == "unverified"
    assert result["impact_interpretation"] == "reachability_only"
    assert result["complete"] is True
    assert result["execution_authority"] is False
    assert result["mutation_authority"] is False


async def test_model_cannot_supply_or_replace_inventory_target() -> None:
    registry, anchor = _runtime()

    with pytest.raises(ValueError, match="input_schema"):
        await registry.invoke(
            INVENTORY_IMPACT_FUNCTION_NAME,
            {
                "target_ref": "model-selected",
                "depth": 1,
                "link_types": ["contains"],
            },
            context=_context(),
        )

    assert anchor.calls == 0
