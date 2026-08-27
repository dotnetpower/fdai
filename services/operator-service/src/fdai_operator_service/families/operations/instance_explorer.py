"""Build one bounded no-authority projection for an operational ontology Resource instance."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from fdai_operator_service.context_selection import ContextSelectionRegistry
from fdai_operator_service.families.operations.contracts import (
    InventoryImpactContext,
    InventoryInstanceActivity,
    InventoryInstanceReader,
    InventoryInstanceResource,
    InventoryRelationshipEvidence,
    ProjectionNotFoundError,
    ProjectionQuery,
    ProjectionUnavailableError,
)
from fdai_service_contracts import (
    OperatorRole,
    canonical_ordinary_role,
    context_selection_digest,
)
from fdai_service_contracts.ontology_query import content_digest

MAX_INSTANCE_LINK_TYPES = 16
MAX_INSTANCE_RESOURCES = 200
MAX_INSTANCE_ACTIVITIES = 100
MAX_INSTANCE_SEARCH_CHARS = 256
_DEFAULT_LINK_TYPES = (
    "contains",
    "attached_to",
    "depends_on",
    "routes_to",
    "runtime_calls",
    "peered_with",
    "kubernetes_backed_by",
    "kubernetes_exposes_endpoint_slice",
    "kubernetes_exposes_endpoints",
    "kubernetes_owned_by",
    "kubernetes_scheduled_on",
    "kubernetes_selects",
)
_ACTIVITY_FACTS = (
    "action_type",
    "decision",
    "mode",
    "outcome",
    "reason",
    "risk_verdict",
    "state",
    "tier",
    "verdict",
)
_READY_STATUS_TEXT = {"True": "Ready", "False": "NotReady", "Unknown": "Ready unknown"}


async def project_inventory_instances(
    *,
    query: ProjectionQuery,
    reader: InventoryInstanceReader,
    ontology_projection: Mapping[str, object],
    selection_registry: ContextSelectionRegistry | None = None,
) -> dict[str, object]:
    """List Resources from the same active generation used by instance detail."""

    release_digest, _declared_links = _ontology_identity(ontology_projection)
    context = await reader.read_inventory_impact_context()
    if context is None:
        raise ProjectionUnavailableError("active inventory snapshot is unavailable")
    search = _optional_parameter(query.params, "search", maximum=MAX_INSTANCE_SEARCH_CHARS)
    page = await reader.read_inventory_instances(
        snapshot_id=context.snapshot_id,
        search=search,
        limit=min(query.limit, MAX_INSTANCE_RESOURCES),
    )
    return {
        "schema_version": "1.0.0",
        "ontology_release_digest": release_digest,
        "source_generation": context.snapshot_id,
        "source_cutoff": context.observed_at.isoformat(),
        "search": search,
        "resources": [_resource_projection(resource, root_id=None) for resource in page.resources],
        "complete": not page.truncated,
        "truncation_reason": "resource_limit" if page.truncated else None,
        **_context_identity(
            query=query,
            release_digest=release_digest,
            source_generation=context.snapshot_id,
            resource_ids=tuple(resource.resource_id for resource in page.resources),
            complete=not page.truncated,
            selection_registry=selection_registry,
        ),
        "execution_authority": False,
        "mutation_authority": False,
    }


async def project_inventory_instance(
    *,
    query: ProjectionQuery,
    reader: InventoryInstanceReader,
    ontology_projection: Mapping[str, object],
    now: Callable[[], datetime] | None = None,
    selection_registry: ContextSelectionRegistry | None = None,
) -> dict[str, object]:
    """Project one Resource, its bounded connected graph, and exact durable FDAI activity."""

    release_digest, declared_links = _ontology_identity(ontology_projection)
    root_id = _single_parameter(query.params, "root", maximum=1_024)
    link_types = _link_types(query.params, declared_links=declared_links)
    resource_limit = min(query.limit, MAX_INSTANCE_RESOURCES)
    depth = _integer_parameter(query.params, "depth", default=6, minimum=1, maximum=8)
    activity_limit = _integer_parameter(
        query.params,
        "activity_limit",
        default=20,
        minimum=1,
        maximum=MAX_INSTANCE_ACTIVITIES,
    )
    context = await reader.read_inventory_impact_context()
    if context is None:
        raise ProjectionUnavailableError("active inventory snapshot is unavailable")
    evaluated_at = (now or (lambda: datetime.now(UTC)))()
    if evaluated_at.tzinfo is None:
        raise ValueError("inventory instance evaluation time MUST be timezone-aware")
    neighborhood = await reader.read_inventory_instance_neighborhood(
        snapshot_id=context.snapshot_id,
        root_id=root_id,
        link_types=link_types,
        depth=depth,
        limit=resource_limit,
    )
    by_id = {resource.resource_id: resource for resource in neighborhood.resources}
    if root_id not in by_id:
        raise ProjectionNotFoundError(root_id)
    activity = await reader.read_inventory_instance_activity(
        resource_id=root_id,
        limit=activity_limit,
    )
    neighborhood_reasons = neighborhood.truncation_reasons or (
        ("resource_limit",) if neighborhood.truncated else ()
    )
    truncation_reasons = [
        *neighborhood_reasons,
        *(("activity_limit",) if activity.truncated else ()),
    ]
    return {
        "schema_version": "1.3.0",
        "ontology_release_digest": release_digest,
        "source_generation": context.snapshot_id,
        "source_cutoff": context.observed_at.isoformat(),
        "root_id": root_id,
        "depth": depth,
        "link_types": list(link_types),
        "resources": [
            _resource_projection(resource, root_id=root_id)
            for resource in sorted(
                neighborhood.resources,
                key=lambda item: (item.resource_id != root_id, item.resource_id),
            )
        ],
        "links": [
            {
                "source": edge.source,
                "target": edge.target,
                "link_type": edge.link_type,
                "evidence": _relationship_evidence_projection(
                    edge.evidence,
                    cutoff=context.observed_at,
                    evaluated_at=evaluated_at,
                ),
            }
            for edge in sorted(
                neighborhood.edges,
                key=lambda item: (item.source, item.link_type, item.target),
            )
        ],
        "timeline": {
            "items": [
                {
                    "sequence": item.sequence,
                    "action_kind": item.action_kind,
                    "actor": item.actor,
                    "recorded_at": item.recorded_at.isoformat(),
                    "correlation_id": item.correlation_id,
                    "facts": {
                        key: value
                        for key in _ACTIVITY_FACTS
                        if (value := item.facts.get(key)) is not None
                    },
                    "evidence_ref": f"audit:{item.sequence}",
                }
                for item in activity.activities
            ],
            "complete": not activity.truncated,
            "truncation_reason": "activity_limit" if activity.truncated else None,
        },
        "sources": [
            {
                "source": "inventory_snapshot",
                "status": "available",
                "observed_at": context.observed_at.isoformat(),
                "reason": None,
            },
            {
                "source": "inventory_relationships",
                "status": ("unavailable" if context.relationship_drop_reasons else "available"),
                "observed_at": context.observed_at.isoformat(),
                "reason": (
                    "relationship_coverage_incomplete"
                    if context.relationship_drop_reasons
                    else None
                ),
            },
            {
                "source": "fdai_audit",
                "status": "available",
                "observed_at": _latest_activity_time(activity.activities),
                "reason": None,
            },
            _projection_source(
                context,
                source="runtime_call_graph",
                unavailable_reason="endpoint_identity_projection_unavailable",
            ),
            _projection_source(
                context,
                source="kubernetes_runtime_inventory",
                unavailable_reason="kubernetes_source_unconfigured",
            ),
            _projection_source(
                context,
                source="postgres_role_evidence",
                unavailable_reason="projection_not_bound",
            ),
            {
                "source": "azure_resource_health",
                "status": "unavailable",
                "observed_at": None,
                "reason": "projection_not_bound",
            },
            {
                "source": "azure_activity_log",
                "status": "unavailable",
                "observed_at": None,
                "reason": "projection_not_bound",
            },
        ],
        "relationship_drop_reasons": list(context.relationship_drop_reasons),
        "relationship_drop_classifications": [
            {
                "reason": item.reason,
                "mapping_id": item.mapping_id,
                "source_property_path": item.source_property_path,
                "source_provider_type": item.source_provider_type,
                "target_provider_type": item.target_provider_type,
                "unavailable_reason": item.unavailable_reason,
                "count": item.count,
            }
            for item in context.relationship_drop_classifications
        ],
        "complete": not truncation_reasons and not context.relationship_drop_reasons,
        "truncation_reasons": truncation_reasons,
        **_context_identity(
            query=query,
            release_digest=release_digest,
            source_generation=context.snapshot_id,
            resource_ids=tuple(resource.resource_id for resource in neighborhood.resources),
            complete=not truncation_reasons and not context.relationship_drop_reasons,
            selection_registry=selection_registry,
        ),
        "execution_authority": False,
        "mutation_authority": False,
    }


def _projection_source(
    context: InventoryImpactContext,
    *,
    source: str,
    unavailable_reason: str,
) -> dict[str, str | None]:
    state = next(
        (item for item in context.projection_source_states if item.source == source),
        None,
    )
    if state is None:
        return {
            "source": source,
            "status": "unavailable",
            "observed_at": None,
            "reason": unavailable_reason,
        }
    return {
        "source": state.source,
        "status": state.status,
        "observed_at": state.observed_at.isoformat() if state.observed_at is not None else None,
        "reason": state.reason,
    }


def _ontology_identity(
    ontology_projection: Mapping[str, object],
) -> tuple[str, frozenset[str]]:
    release_digest = ontology_projection.get("ontology_release_digest")
    if not isinstance(release_digest, str) or not release_digest.startswith("sha256:"):
        raise ProjectionUnavailableError("ontology release identity is unavailable")
    raw_links = ontology_projection.get("link_types")
    if not isinstance(raw_links, list):
        raise ProjectionUnavailableError("ontology LinkType declarations are unavailable")
    declared = frozenset(item for item in raw_links if isinstance(item, str) and item)
    if not declared:
        raise ProjectionUnavailableError("ontology LinkType declarations are unavailable")
    return release_digest, declared


def _single_parameter(
    params: Mapping[str, tuple[str, ...]],
    name: str,
    *,
    maximum: int,
) -> str:
    values = params.get(name, ())
    if len(values) != 1 or not values[0].strip():
        raise ValueError(f"{name} MUST be supplied exactly once")
    value = values[0].strip()
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds its length bound")
    return value


def _optional_parameter(
    params: Mapping[str, tuple[str, ...]],
    name: str,
    *,
    maximum: int,
) -> str | None:
    values = params.get(name, ())
    if not values:
        return None
    if len(values) != 1:
        raise ValueError(f"{name} MUST be supplied at most once")
    value = values[0].strip()
    if not value:
        return None
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds its length bound")
    return value


def _integer_parameter(
    params: Mapping[str, tuple[str, ...]],
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    values = params.get(name, (str(default),))
    if len(values) != 1:
        raise ValueError(f"{name} MUST be supplied at most once")
    try:
        value = int(values[0])
    except ValueError as exc:
        raise ValueError(f"{name} MUST be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} MUST be in [{minimum}, {maximum}]")
    return value


def _link_types(
    params: Mapping[str, tuple[str, ...]],
    *,
    declared_links: frozenset[str],
) -> tuple[str, ...]:
    requested: list[str] = []
    for value in params.get("link", ()):
        requested.extend(value.split(","))
    normalized = tuple(dict.fromkeys(item.strip() for item in requested if item.strip()))
    if not normalized:
        normalized = tuple(item for item in _DEFAULT_LINK_TYPES if item in declared_links)
    if not normalized:
        raise ProjectionUnavailableError("inventory LinkType declarations are unavailable")
    if len(normalized) > MAX_INSTANCE_LINK_TYPES:
        raise ValueError("link types exceed the instance exploration bound")
    unknown = set(normalized) - declared_links
    if unknown:
        raise ValueError("instance exploration requested an undeclared LinkType")
    return normalized


def _context_identity(
    *,
    query: ProjectionQuery,
    release_digest: str,
    source_generation: str,
    resource_ids: tuple[str, ...],
    complete: bool,
    selection_registry: ContextSelectionRegistry | None,
) -> dict[str, object]:
    """Issue a digest-bound selection only for a complete principal-scoped read."""
    if not complete:
        return {}
    ordinary_roles = tuple(
        role
        for role in (query.roles or frozenset({OperatorRole.READER}))
        if role is not OperatorRole.BREAK_GLASS
    )
    if not ordinary_roles:
        return {}
    principal_role = max(
        ordinary_roles,
        key=lambda role: tuple(OperatorRole).index(role),
    )
    principal_scope_digest = content_digest(
        {
            "principal_id": query.principal_id,
            "role": canonical_ordinary_role(principal_role),
            "purpose": query.purpose,
        }
    )
    selection_digest = context_selection_digest(
        kind="screen",
        principal_id=query.principal_id,
        principal_scope_digest=principal_scope_digest,
        ontology_release_digest=release_digest,
        source_generation=source_generation,
        complete=complete,
        screen_id="ontology-instances",
        resource_group_id=None,
        resource_ids=resource_ids,
    )
    registry = selection_registry or ContextSelectionRegistry()
    selection_token = registry.issue(
        {
            "kind": "screen",
            "screen_id": "ontology-instances",
            "resource_ids": list(resource_ids),
            "principal_id": query.principal_id,
            "role": canonical_ordinary_role(principal_role),
            "purpose": query.purpose,
            "principal_scope_digest": principal_scope_digest,
            "ontology_release_digest": release_digest,
            "source_generation": source_generation,
            "selection_digest": selection_digest,
            "complete": True,
        }
    )
    return {
        "principal_id": query.principal_id,
        "principal_scope_digest": principal_scope_digest,
        "selection_digest": selection_digest,
        "selection_token": selection_token,
    }


def _resource_projection(
    resource: InventoryInstanceResource,
    *,
    root_id: str | None,
) -> dict[str, object]:
    properties = resource.properties
    return {
        "id": resource.resource_id,
        "object_type": "Resource",
        "resource_type": resource.resource_type,
        "name": _optional_text(properties.get("name")),
        "location": _optional_text(properties.get("location")),
        "resource_group": _optional_text(properties.get("resourceGroup"))
        or _optional_text(properties.get("resource_group")),
        "status": _resource_status(properties),
        "last_seen": resource.last_seen.isoformat() if resource.last_seen else None,
        "selected": root_id is not None and resource.resource_id == root_id,
    }


def _resource_status(properties: Mapping[str, object]) -> str | None:
    for key in ("status", "state", "phase", "provisioningState"):
        value = _optional_text(properties.get(key))
        if value is not None:
            return value
    ready_status = _optional_text(properties.get("ready_status"))
    if ready_status is not None:
        return _READY_STATUS_TEXT.get(ready_status)
    nested = properties.get("properties")
    if isinstance(nested, Mapping):
        return _optional_text(nested.get("provisioningState"))
    return None


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _latest_activity_time(
    activities: tuple[InventoryInstanceActivity, ...],
) -> str | None:
    times = [item.recorded_at for item in activities if isinstance(item.recorded_at, datetime)]
    return max(times).isoformat() if times else None


def _relationship_evidence_projection(
    evidence: InventoryRelationshipEvidence | None,
    *,
    cutoff: datetime,
    evaluated_at: datetime,
) -> dict[str, object]:
    if evidence is None:
        return {
            "status": "unavailable",
            "evidence_kind": None,
            "verification_status": "unavailable",
            "source": None,
            "source_property_path": None,
            "mapping_id": None,
            "evidence_method": None,
            "cutoff": None,
            "freshness_ceiling_seconds": None,
            "complete": False,
            "reason": "provider_relationship_evidence_unavailable",
        }
    evidence_cutoff = evidence.evidence_cutoff or cutoff
    age_seconds = (evaluated_at - evidence_cutoff).total_seconds()
    if age_seconds < 0:
        status = "stale"
        reason = "relationship_evidence_future_cutoff"
    elif age_seconds > evidence.freshness_ceiling_seconds:
        status = "stale"
        reason = "relationship_evidence_stale"
    else:
        status = "available"
        reason = None
    return {
        "status": status,
        "evidence_kind": evidence.evidence_kind,
        "verification_status": (
            "independently_verified"
            if evidence.evidence_kind == "observation"
            else "configuration_observed"
        ),
        "source": evidence.source_identity,
        "source_property_path": evidence.source_property_path,
        "mapping_id": evidence.mapping_id,
        "evidence_method": evidence.evidence_method,
        "cutoff": evidence_cutoff.isoformat(),
        "freshness_ceiling_seconds": evidence.freshness_ceiling_seconds,
        "complete": status == "available",
        "reason": reason,
    }


__all__ = ["project_inventory_instance", "project_inventory_instances"]
