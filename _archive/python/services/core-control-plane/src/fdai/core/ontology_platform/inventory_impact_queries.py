"""Server-anchored read-only impact traversal over one active inventory snapshot."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)

from .functions import ContextualOntologyFunction, FunctionInvocationContext

INVENTORY_IMPACT_FUNCTION_NAME = "query.inventory_impact"
INVENTORY_IMPACT_PURPOSE = "operations-review"
MAX_IMPACT_DEPTH = 5
MAX_IMPACT_EDGES = 1_000
MAX_IMPACT_LINK_TYPES = 16


@dataclass(frozen=True, slots=True)
class InventoryImpactContext:
    """Exact active inventory generation and observation cutoff."""

    snapshot_ref: str
    observed_at: datetime
    ontology_release_digest: str


@dataclass(frozen=True, slots=True)
class InventoryImpactEdge:
    """One stored-direction inventory relationship."""

    source_ref: str
    target_ref: str
    link_type: str


@dataclass(frozen=True, slots=True)
class InventoryImpactPage:
    """One bounded edge page plus endpoint-closure evidence."""

    edges: tuple[InventoryImpactEdge, ...]
    resource_refs: frozenset[str]
    truncated: bool


class InventoryImpactReader(Protocol):
    """Read one exact active inventory graph without mutation authority."""

    async def read_context(self) -> InventoryImpactContext | None: ...

    async def resource_exists(self, *, snapshot_ref: str, resource_ref: str) -> bool: ...

    async def read_outgoing(
        self,
        *,
        snapshot_ref: str,
        source_refs: tuple[str, ...],
        link_types: tuple[str, ...],
        limit: int,
    ) -> InventoryImpactPage: ...


class InventoryImpactAnchorResolver(Protocol):
    """Resolve an opaque authenticated resource anchor outside model arguments."""

    async def resolve(self, context: FunctionInvocationContext) -> str | None: ...


def inventory_impact_function_type() -> OntologyFunctionType:
    """Return the declaration for server-anchored bounded impact traversal."""

    return OntologyFunctionType(
        name=INVENTORY_IMPACT_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["depth", "link_types"],
            "properties": {
                "depth": {"type": "integer", "minimum": 1, "maximum": MAX_IMPACT_DEPTH},
                "link_types": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": MAX_IMPACT_LINK_TYPES,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1, "maxLength": 128},
                },
            },
        },
        output_schema=_output_schema(),
        read_sets=[],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=[INVENTORY_IMPACT_PURPOSE],
        timeout_seconds=5,
        cpu_millis=250,
        memory_bytes=67_108_864,
        max_output_bytes=4_194_304,
        network_allowed=False,
        credentials_allowed=False,
    )


def inventory_impact_function(
    ontology_release: OntologyRelease,
    *,
    declared_link_types: frozenset[str],
    reader: InventoryImpactReader,
    anchor_resolver: InventoryImpactAnchorResolver,
) -> ContextualOntologyFunction:
    """Bind stored-direction traversal to a server-owned authenticated anchor."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        INVENTORY_IMPACT_FUNCTION_NAME,
    )
    for link_type in declared_link_types:
        ontology_release.type_ref(OntologyDeclarationKind.LINK, link_type)

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != (INVENTORY_IMPACT_PURPOSE,):
            raise PermissionError("inventory impact purpose does not match invocation context")
        target_ref = await anchor_resolver.resolve(invocation_context)
        if target_ref is None:
            raise LookupError("authenticated inventory impact anchor is unavailable")
        depth_limit = int(arguments["depth"])
        link_types = tuple(str(item) for item in arguments["link_types"])
        unknown = sorted(set(link_types) - declared_link_types)
        if unknown:
            raise ValueError(f"inventory impact LinkType is absent from release: {unknown[0]}")
        context = await reader.read_context()
        if context is None:
            raise RuntimeError("active inventory snapshot is unavailable")
        if context.ontology_release_digest != ontology_release.digest:
            raise ValueError("inventory impact snapshot release does not match active release")
        if context.observed_at.tzinfo is None:
            raise ValueError("inventory impact cutoff MUST be timezone-aware")
        if not await reader.resource_exists(
            snapshot_ref=context.snapshot_ref,
            resource_ref=target_ref,
        ):
            raise LookupError("authenticated inventory impact target is absent")
        return await _traverse(
            reader=reader,
            context=context,
            target_ref=target_ref,
            depth_limit=depth_limit,
            link_types=link_types,
        )

    return evaluate


async def _traverse(
    *,
    reader: InventoryImpactReader,
    context: InventoryImpactContext,
    target_ref: str,
    depth_limit: int,
    link_types: tuple[str, ...],
) -> dict[str, object]:
    reached: dict[str, dict[str, object]] = {
        target_ref: {"resource_ref": target_ref, "depth": 0, "via_link_type": None}
    }
    traversed: list[dict[str, object]] = []
    edge_ids: set[tuple[str, str, str]] = set()
    frontier: tuple[str, ...] = (target_ref,)
    edge_limit_reached = False
    depth_limit_reached = False
    for depth in range(1, depth_limit + 1):
        if not frontier:
            break
        remaining = MAX_IMPACT_EDGES - len(traversed)
        if remaining < 1:
            edge_limit_reached = True
            break
        page = await reader.read_outgoing(
            snapshot_ref=context.snapshot_ref,
            source_refs=frontier,
            link_types=link_types,
            limit=remaining,
        )
        ordered = _validated_edges(page, source_refs=frontier, link_types=link_types)
        next_frontier: set[str] = set()
        for edge in ordered:
            identity = (edge.source_ref, edge.link_type, edge.target_ref)
            if identity in edge_ids:
                raise ValueError("inventory impact reader returned a duplicate edge")
            edge_ids.add(identity)
            traversed.append(
                {
                    "source_ref": edge.source_ref,
                    "target_ref": edge.target_ref,
                    "link_type": edge.link_type,
                    "depth": depth,
                    "verification_status": "unverified",
                }
            )
            if edge.target_ref not in reached:
                reached[edge.target_ref] = {
                    "resource_ref": edge.target_ref,
                    "depth": depth,
                    "via_link_type": edge.link_type,
                }
                next_frontier.add(edge.target_ref)
        if page.truncated:
            edge_limit_reached = True
            break
        frontier = tuple(sorted(next_frontier))
    if not edge_limit_reached and frontier:
        probe = await reader.read_outgoing(
            snapshot_ref=context.snapshot_ref,
            source_refs=frontier,
            link_types=link_types,
            limit=1,
        )
        probe_edges = _validated_edges(probe, source_refs=frontier, link_types=link_types)
        depth_limit_reached = probe.truncated or any(
            item.target_ref not in reached for item in probe_edges
        )
    reasons = [
        reason
        for reason, active in (
            ("edge_limit", edge_limit_reached),
            ("depth_limit", depth_limit_reached),
        )
        if active
    ]
    return {
        "schema_version": "1.0.0",
        "ontology_release_digest": context.ontology_release_digest,
        "source_generation": context.snapshot_ref,
        "source_cutoff": context.observed_at.isoformat(),
        "target_ref": target_ref,
        "traversal_depth": depth_limit,
        "traversal_links": list(link_types),
        "reached": sorted(reached.values(), key=lambda item: (item["depth"], item["resource_ref"])),
        "edges": traversed,
        "affected_count": len(reached) - 1,
        "complete": not reasons,
        "truncation_reasons": reasons,
        "impact_interpretation": "reachability_only",
        "execution_authority": False,
        "mutation_authority": False,
    }


def _validated_edges(
    page: InventoryImpactPage,
    *,
    source_refs: tuple[str, ...],
    link_types: tuple[str, ...],
) -> tuple[InventoryImpactEdge, ...]:
    if any(
        edge.source_ref not in source_refs
        or edge.link_type not in link_types
        or edge.source_ref not in page.resource_refs
        or edge.target_ref not in page.resource_refs
        for edge in page.edges
    ):
        raise ValueError("inventory impact page violates its requested scope or endpoint closure")
    source_order = {value: index for index, value in enumerate(source_refs)}
    link_order = {value: index for index, value in enumerate(link_types)}
    return tuple(
        sorted(
            page.edges,
            key=lambda edge: (
                source_order[edge.source_ref],
                link_order[edge.link_type],
                edge.target_ref,
            ),
        )
    )


def _output_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "ontology_release_digest",
            "source_generation",
            "source_cutoff",
            "target_ref",
            "traversal_depth",
            "traversal_links",
            "reached",
            "edges",
            "affected_count",
            "complete",
            "truncation_reasons",
            "impact_interpretation",
            "execution_authority",
            "mutation_authority",
        ],
        "properties": {
            "schema_version": {"const": "1.0.0"},
            "ontology_release_digest": {
                "type": "string",
                "pattern": "^sha256:[a-f0-9]{64}$",
            },
            "source_generation": {"type": "string"},
            "source_cutoff": {"type": "string"},
            "target_ref": {"type": "string"},
            "traversal_depth": {"type": "integer", "minimum": 1, "maximum": MAX_IMPACT_DEPTH},
            "traversal_links": {
                "type": "array",
                "maxItems": MAX_IMPACT_LINK_TYPES,
                "items": {"type": "string"},
            },
            "reached": {"type": "array", "maxItems": MAX_IMPACT_EDGES + 1},
            "edges": {
                "type": "array",
                "maxItems": MAX_IMPACT_EDGES,
                "items": {
                    "type": "object",
                    "required": [
                        "source_ref",
                        "target_ref",
                        "link_type",
                        "depth",
                        "verification_status",
                    ],
                    "properties": {"verification_status": {"const": "unverified"}},
                },
            },
            "affected_count": {"type": "integer", "minimum": 0},
            "complete": {"type": "boolean"},
            "truncation_reasons": {
                "type": "array",
                "uniqueItems": True,
                "items": {"enum": ["edge_limit", "depth_limit"]},
            },
            "impact_interpretation": {"const": "reachability_only"},
            "execution_authority": {"const": False},
            "mutation_authority": {"const": False},
        },
    }


__all__ = [
    "INVENTORY_IMPACT_FUNCTION_NAME",
    "INVENTORY_IMPACT_PURPOSE",
    "InventoryImpactAnchorResolver",
    "InventoryImpactContext",
    "InventoryImpactEdge",
    "InventoryImpactPage",
    "InventoryImpactReader",
    "inventory_impact_function",
    "inventory_impact_function_type",
]
