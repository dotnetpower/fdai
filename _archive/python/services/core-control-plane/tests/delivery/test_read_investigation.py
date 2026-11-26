from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fdai.delivery.read_investigation import InventoryReadInvestigationProvider
from fdai.shared.providers.read_investigation import (
    EvidenceFreshness,
    EvidenceStatus,
    ReadToolId,
    ReadToolLimits,
    ResourceResolutionStatus,
    ResourceSelector,
)

NOW = datetime(2026, 8, 12, 1, tzinfo=UTC)


class _GraphReader:
    def __init__(self, *, resources: list[dict[str, Any]], truncated: bool = False) -> None:
        self.resources = resources
        self.truncated = truncated

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
        selected = self.resources
        if root is not None:
            selected = [item for item in selected if item["id"] == root]
        return {
            "snapshot_id": "snapshot-1",
            "snapshot_at": NOW.isoformat(),
            "freshness": "fresh",
            "resources": selected,
            "truncated": self.truncated,
        }


async def _context(resource_ref: str) -> dict[str, Any] | None:
    if resource_ref != "resource:vm-01":
        return None
    return {
        "resource_id": resource_ref,
        "resource_type": "compute.vm",
        "props": {"status": "running"},
    }


def _provider(*, resources: list[dict[str, Any]], truncated: bool = False):
    return InventoryReadInvestigationProvider(
        graph_reader=_GraphReader(resources=resources, truncated=truncated),
        context_reader=_context,
        clock=lambda: NOW,
        monotonic=lambda: 1.0,
    )


def _resource(name: str, resource_ref: str = "resource:vm-01") -> dict[str, Any]:
    return {
        "id": resource_ref,
        "name": name,
        "type": "compute.vm",
        "props": {"resourceGroup": "example-group"},
    }


async def test_exact_inventory_resource_state_is_authoritative_read_evidence() -> None:
    provider = _provider(resources=[_resource("vm-01")])
    limits = ReadToolLimits(timeout_seconds=5, max_results=8, max_output_bytes=4096)

    resolution = await provider.resolve_resource(
        ResourceSelector(name="vm-01", scope_ref="scope:operator"),
        limits=limits,
    )
    assert resolution.resolution.status is ResourceResolutionStatus.MATCHED
    resource = resolution.resolution.resource
    assert resource is not None

    attempt = await provider.get_resource_state(resource, limits=limits)
    assert attempt.tool_id is ReadToolId.GET_RESOURCE_STATE
    assert attempt.evidence.status is EvidenceStatus.MATCHED
    assert attempt.evidence.freshness is EvidenceFreshness.LIVE
    assert attempt.evidence.records[0].state == "running"
    assert attempt.evidence.evidence_refs == ("inventory-snapshot:snapshot-1",)


async def test_truncated_inventory_never_claims_resource_absence() -> None:
    provider = _provider(resources=[], truncated=True)

    attempt = await provider.resolve_resource(
        ResourceSelector(name="vm-01", scope_ref="scope:operator"),
        limits=ReadToolLimits(timeout_seconds=5, max_results=8, max_output_bytes=4096),
    )

    assert attempt.resolution.status is ResourceResolutionStatus.UNAVAILABLE


async def test_duplicate_exact_names_are_ambiguous() -> None:
    provider = _provider(
        resources=[
            _resource("vm-01"),
            _resource("vm-01", "resource:vm-01-copy"),
        ]
    )

    attempt = await provider.resolve_resource(
        ResourceSelector(name="vm-01", scope_ref="scope:operator"),
        limits=ReadToolLimits(timeout_seconds=5, max_results=8, max_output_bytes=4096),
    )

    assert attempt.resolution.status is ResourceResolutionStatus.AMBIGUOUS
    assert len(attempt.resolution.candidates) == 2
