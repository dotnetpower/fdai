"""Build one bounded no-authority projection for an operational ontology Resource instance."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime

from fdai_operator_service.context_selection import ContextSelectionRegistry
from fdai_operator_service.families.operations.contracts import (
    UNSELECTABLE_INSTANCE_DIRECTORY_TYPES,
    InventoryAksDiagnosticReceipt,
    InventoryImpactContext,
    InventoryInstanceActivity,
    InventoryInstanceReader,
    InventoryInstanceResource,
    InventoryProviderScopeCoverage,
    InventoryRelationshipCoverage,
    InventoryRelationshipEvidence,
    ProjectionNotFoundError,
    ProjectionQuery,
    ProjectionUnavailableError,
)
from fdai_operator_service.families.operations.recorded_state import (
    RecordedStateObservation,
    recorded_resource_states,
)
from fdai_service_contracts import (
    OperatorRole,
    canonical_ordinary_role,
    context_selection_digest,
)
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.recorded_resource_state import (
    is_recorded_state_value_valid,
    operational_state_paths,
)

MAX_INSTANCE_LINK_TYPES = 16
MAX_INSTANCE_RESOURCES = 200
MAX_INSTANCE_ACTIVITIES = 100
MAX_INSTANCE_SEARCH_CHARS = 256
MAX_MODEL_DEPLOYMENT_TPM = 2_147_483_647
MAX_KUBERNETES_DIAGNOSTIC_SEQUENCE = 384
MODEL_DEPLOYMENT_RESOURCE_TYPE = "llm-model-deployment"
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
_KUBERNETES_DIAGNOSTIC_KEYS = frozenset(
    {
        "access_modes",
        "address_type",
        "affinity_kinds",
        "allow_volume_expansion",
        "available_replicas",
        "capacity_storage",
        "claim_name",
        "claim_namespace",
        "claim_uid",
        "container_count",
        "container_resources",
        "container_terminations",
        "container_waiting_reasons",
        "current_healthy",
        "current_replicas",
        "diagnostic_conditions",
        "disruptions_allowed",
        "desired_healthy",
        "desired_replicas",
        "egress_rule_count",
        "endpoint_count",
        "ephemeral_container_count",
        "ephemeral_container_ready_count",
        "ephemeral_container_restart_count",
        "ephemeral_container_termination_reasons",
        "ephemeral_container_waiting_reasons",
        "expected_pods",
        "init_container_count",
        "init_container_ready_count",
        "init_container_restart_count",
        "init_container_termination_reasons",
        "init_container_waiting_reasons",
        "ingress_rule_count",
        "limit_summaries",
        "max_replicas",
        "max_unavailable",
        "min_available",
        "min_replicas",
        "node_selector",
        "observed_generation",
        "phase",
        "policy_types",
        "port_count",
        "priority_class_name",
        "probe_kinds",
        "progressing_reason",
        "progressing_status",
        "provisioner",
        "pvc_claim_names",
        "qos_class",
        "quota_hard",
        "quota_used",
        "ready",
        "ready_container_count",
        "ready_replicas",
        "ready_status",
        "ready_unknown",
        "reason",
        "reclaim_policy",
        "restart_count",
        "restart_policy",
        "requested_storage",
        "scale_target_api_version",
        "scale_target_kind",
        "scale_target_name",
        "scheduler_name",
        "selector",
        "selector_matches_all",
        "serving",
        "serving_unknown",
        "service_account_name",
        "status_counts",
        "storage_class_name",
        "target_uids",
        "terminating",
        "terminating_unknown",
        "tolerations",
        "unavailable_replicas",
        "updated_replicas",
        "volume_binding_mode",
        "volume_mode",
        "volume_name",
    }
)


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
    evaluated_at = datetime.now(UTC)
    return {
        "schema_version": "1.0.0",
        "ontology_release_digest": release_digest,
        "source_generation": context.snapshot_id,
        "source_cutoff": context.observed_at.isoformat(),
        "search": search,
        "resources": [
            _resource_projection(
                resource,
                root_id=None,
                now=evaluated_at,
                state_observation=_state_observation(resource, context),
            )
            for resource in page.resources
        ],
        "complete": not page.truncated,
        "truncation_reason": "resource_limit" if page.truncated else None,
        **_context_identity(
            query=query,
            release_digest=release_digest,
            source_generation=context.snapshot_id,
            resource_ids=_selectable_resource_ids(page.resources),
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
    root_resource = by_id[root_id]
    diagnostic_receipt = (
        await reader.read_latest_aks_diagnostic_receipt(resource_id=root_id)
        if root_resource.resource_type.startswith("kubernetes.")
        else None
    )
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
        "schema_version": "1.4.0",
        "ontology_release_digest": release_digest,
        "source_generation": context.snapshot_id,
        "source_cutoff": context.observed_at.isoformat(),
        "root_id": root_id,
        "depth": depth,
        "link_types": list(link_types),
        "resources": [
            _resource_projection(
                resource,
                root_id=root_id,
                now=evaluated_at,
                state_observation=_state_observation(resource, context),
                aks_diagnostic_receipt=(
                    _current_aks_diagnostic_receipt(
                        diagnostic_receipt,
                        resource=root_resource,
                        context=context,
                        ontology_release=release_digest,
                    )
                    if resource.resource_id == root_id
                    and root_resource.resource_type.startswith("kubernetes.")
                    else None
                ),
                include_aks_diagnostic_receipt=(
                    resource.resource_id == root_id
                    and root_resource.resource_type.startswith("kubernetes.")
                ),
            )
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
            *_projection_sources(
                context,
                source="runtime_call_graph",
                unavailable_reason="endpoint_identity_projection_unavailable",
            ),
            *_projection_sources(
                context,
                source="kubernetes_runtime_inventory",
                unavailable_reason="kubernetes_source_unconfigured",
            ),
            *_projection_sources(
                context,
                source="postgres_role_evidence",
                unavailable_reason="projection_not_bound",
            ),
            *_projection_sources(
                context,
                source="azure_resource_health",
                unavailable_reason="projection_not_bound",
            ),
            *_projection_sources(
                context,
                source="azure_activity_log",
                unavailable_reason="projection_not_bound",
            ),
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
        "relationship_coverage": _relationship_coverage_projection(context.relationship_coverage),
        "provider_scope_coverage": _provider_scope_coverage_projection(
            context.provider_scope_coverage
        ),
        "complete": not truncation_reasons and not context.relationship_drop_reasons,
        "truncation_reasons": truncation_reasons,
        **_context_identity(
            query=query,
            release_digest=release_digest,
            source_generation=context.snapshot_id,
            resource_ids=_selectable_resource_ids(neighborhood.resources),
            complete=not truncation_reasons and not context.relationship_drop_reasons,
            selection_registry=selection_registry,
        ),
        "execution_authority": False,
        "mutation_authority": False,
    }


def _projection_sources(
    context: InventoryImpactContext,
    *,
    source: str,
    unavailable_reason: str,
) -> list[dict[str, str | None]]:
    states = [item for item in context.projection_source_states if item.source == source]
    if not states:
        return [
            {
                "source": source,
                "status": "unavailable",
                "observed_at": None,
                "reason": unavailable_reason,
            }
        ]
    projected: list[dict[str, str | None]] = []
    for state in states:
        item = {
            "source": state.source,
            "status": state.status,
            "observed_at": (
                state.observed_at.isoformat() if state.observed_at is not None else None
            ),
            "reason": state.reason,
        }
        if state.scope_digest is not None:
            item["scope_digest"] = state.scope_digest
        projected.append(item)
    return projected


def _relationship_coverage_projection(
    coverage: InventoryRelationshipCoverage | None,
) -> dict[str, object] | None:
    """Render the exact candidate-relationship count, or ``None`` for an older generation."""

    if coverage is None:
        return None
    return {
        "total_candidates": coverage.total_candidates,
        "materialized": coverage.materialized,
        "reviewed_unavailable": coverage.reviewed_unavailable,
        "unclassified": coverage.unclassified,
        "complete": coverage.complete,
    }


def _provider_scope_coverage_projection(
    coverage: InventoryProviderScopeCoverage | None,
) -> dict[str, object] | None:
    """Render provider type coverage without provider object identities or properties."""

    if coverage is None:
        return None
    return {
        "capture_method": coverage.capture_method,
        "provider_object_count": coverage.provider_object_count,
        "mapped_provider_object_count": coverage.mapped_provider_object_count,
        "unmapped_provider_object_count": coverage.unmapped_provider_object_count,
        "materialized_unmapped_provider_object_count": (
            coverage.materialized_unmapped_provider_object_count
        ),
        "provider_identity_complete": coverage.provider_identity_complete,
        "provider_type_count": coverage.provider_type_count,
        "unmapped_provider_type_count": len(coverage.unmapped_provider_types),
        "unmapped_provider_types": [
            {"provider_type": item.provider_type, "count": item.count}
            for item in coverage.unmapped_provider_types
        ],
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
    if not complete or not resource_ids:
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
        "context_capability": {"selection_token": selection_token},
    }


def _selectable_resource_ids(
    resources: tuple[InventoryInstanceResource, ...],
) -> tuple[str, ...]:
    return tuple(
        resource.resource_id
        for resource in resources
        if resource.resource_type not in UNSELECTABLE_INSTANCE_DIRECTORY_TYPES
    )


def _resource_projection(
    resource: InventoryInstanceResource,
    *,
    root_id: str | None,
    now: datetime | None = None,
    state_observation: RecordedStateObservation | None = None,
    aks_diagnostic_receipt: dict[str, object] | None = None,
    include_aks_diagnostic_receipt: bool = False,
) -> dict[str, object]:
    properties = resource.properties
    if (
        not resource.resource_id
        or len(resource.resource_id) > 1024
        or (not resource.resource_type or len(resource.resource_type) > 256)
    ):
        raise ProjectionUnavailableError("inventory Resource identity exceeds its bounds")
    projection: dict[str, object] = {
        "id": resource.resource_id,
        "object_type": "Resource",
        "resource_type": resource.resource_type,
        "name": _optional_text(properties.get("name")),
        "location": _optional_text(properties.get("location")),
        "resource_group": _optional_text(properties.get("resourceGroup"))
        or _optional_text(properties.get("resource_group")),
        "subscription_id": _optional_text(properties.get("subscriptionId"))
        or _optional_text(properties.get("subscription_id")),
        "status": _optional_text(_resource_status(properties, resource.resource_type)),
        "states": recorded_resource_states(
            properties,
            resource_type=resource.resource_type,
            observation=state_observation,
            now=now,
        ),
        "last_seen": (
            resource.last_seen.isoformat()
            if resource.last_seen and resource.last_seen.utcoffset() is not None
            else None
        ),
        "selected": root_id is not None and resource.resource_id == root_id,
    }
    capacity = _resource_capacity(resource.resource_type, properties)
    if capacity is not None:
        projection["capacity"] = capacity
    model_deployment = _model_deployment_projection(resource.resource_type, properties)
    if model_deployment is not None:
        projection["model_deployment"] = model_deployment
    kubernetes_identity = _kubernetes_identity_projection(resource.resource_type, properties)
    if kubernetes_identity is not None:
        projection["kubernetes_identity"] = kubernetes_identity
        projection["kubernetes_diagnostics"] = _kubernetes_diagnostic_projection(properties)
        if include_aks_diagnostic_receipt:
            projection["aks_diagnostic_receipt"] = aks_diagnostic_receipt
    return projection


def _current_aks_diagnostic_receipt(
    receipt: InventoryAksDiagnosticReceipt | None,
    *,
    resource: InventoryInstanceResource,
    context: InventoryImpactContext,
    ontology_release: str,
) -> dict[str, object] | None:
    if receipt is None:
        return None
    uid = resource.properties.get("uid")
    resource_version = resource.properties.get("resource_version")
    inventory_revision = "sha256:" + hashlib.sha256(context.snapshot_id.encode()).hexdigest()
    if (
        receipt.target_resource_id != resource.resource_id
        or receipt.target_uid != uid
        or receipt.target_resource_version != resource_version
        or receipt.ontology_release != ontology_release
        or receipt.cutoff != context.observed_at
        or receipt.source_cutoffs.get("inventory_snapshot") != context.observed_at
        or receipt.source_revisions.get("inventory_snapshot") != inventory_revision
        or set(receipt.source_cutoffs)
        - {
            "inventory_snapshot",
            "kubernetes_runtime_inventory",
        }
    ):
        return None
    kubernetes_cutoff = receipt.source_cutoffs.get("kubernetes_runtime_inventory")
    kubernetes_revision = receipt.source_revisions.get("kubernetes_runtime_inventory")
    if kubernetes_cutoff is None or kubernetes_revision is None:
        if "kubernetes_runtime_inventory_unavailable" not in receipt.evidence_gaps:
            return None
    elif not any(
        state.source == "kubernetes_runtime_inventory"
        and state.status == "available"
        and state.observed_at == kubernetes_cutoff
        and state.scope_digest == kubernetes_revision
        for state in context.projection_source_states
    ):
        return None
    return {
        "schema_version": "1.0.0",
        "owner_agent": "Forseti",
        "principal_class": receipt.principal_class,
        "purpose": "operations-review",
        "producer_version": receipt.producer_version,
        "method_version": receipt.method_version,
        "target_resource_id": receipt.target_resource_id,
        "target_uid": receipt.target_uid,
        "target_resource_version": receipt.target_resource_version,
        "ontology_release": receipt.ontology_release,
        "cutoff": receipt.cutoff.isoformat(),
        "source_cutoffs": {
            key: value.isoformat() for key, value in sorted(receipt.source_cutoffs.items())
        },
        "source_revisions": dict(sorted(receipt.source_revisions.items())),
        "status": receipt.status,
        "signals": list(receipt.signals),
        "complete": receipt.complete,
        "evidence_gaps": list(receipt.evidence_gaps),
        "conflicts": list(receipt.conflicts),
        "evidence_refs": list(receipt.evidence_refs),
        "synthetic": False,
        "cause_claim_supported": False,
        "execution_authority": False,
        "audit_correlation_id": receipt.audit_correlation_id,
    }


def _kubernetes_identity_projection(
    resource_type: str,
    properties: Mapping[str, object],
) -> dict[str, object] | None:
    if not resource_type.startswith("kubernetes."):
        return None
    fields = {
        key: properties.get(key)
        for key in ("api_version", "kind", "name", "resource_version", "uid")
    }
    if all(fields[key] is None for key in ("api_version", "kind", "resource_version")):
        return None
    if all(value is None for value in fields.values()):
        return None
    if any(not isinstance(value, str) or not value.strip() for value in fields.values()):
        raise ProjectionUnavailableError("Kubernetes Resource identity is incomplete")
    namespace = properties.get("namespace")
    if namespace is not None and (not isinstance(namespace, str) or not namespace.strip()):
        raise ProjectionUnavailableError("Kubernetes Resource namespace is malformed")
    return {
        **fields,
        "namespace": namespace,
    }


def _kubernetes_diagnostic_projection(
    properties: Mapping[str, object],
) -> dict[str, object]:
    return {
        key: _bounded_diagnostic_value(properties[key], depth=0)
        for key in sorted(_KUBERNETES_DIAGNOSTIC_KEYS & properties.keys())
    }


def _bounded_diagnostic_value(value: object, *, depth: int) -> object:
    if depth > 4:
        raise ProjectionUnavailableError("Kubernetes diagnostic fact nesting exceeds its bound")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if abs(value) > 2_147_483_647:
            raise ProjectionUnavailableError("Kubernetes diagnostic integer exceeds its bound")
        return value
    if isinstance(value, str):
        if len(value) > 512:
            raise ProjectionUnavailableError("Kubernetes diagnostic text exceeds its bound")
        return value
    if isinstance(value, Mapping):
        if len(value) > 128 or any(not isinstance(key, str) or not key for key in value):
            raise ProjectionUnavailableError("Kubernetes diagnostic object exceeds its bound")
        return {
            str(key): _bounded_diagnostic_value(item, depth=depth + 1)
            for key, item in sorted(value.items())
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) > MAX_KUBERNETES_DIAGNOSTIC_SEQUENCE:
            raise ProjectionUnavailableError("Kubernetes diagnostic array exceeds its bound")
        return [_bounded_diagnostic_value(item, depth=depth + 1) for item in value]
    raise ProjectionUnavailableError("Kubernetes diagnostic fact has an unsupported value")


def _state_observation(
    resource: InventoryInstanceResource,
    context: InventoryImpactContext,
) -> RecordedStateObservation | None:
    if resource.last_seen is None or resource.last_seen.utcoffset() is None:
        return None
    return RecordedStateObservation(
        generation=context.snapshot_id,
        observed_at=resource.last_seen,
        recorded_at=context.observed_at,
    )


def _resource_capacity(resource_type: str, properties: Mapping[str, object]) -> int | None:
    """Return one observed scalable-resource capacity from allowlisted provider fields."""

    candidate: object | None = None
    if resource_type == "kubernetes-node-pool":
        nested = properties.get("properties")
        if isinstance(nested, Mapping):
            candidate = nested.get("count")
    elif resource_type == "compute.vm-scale-set":
        sku = properties.get("sku")
        if isinstance(sku, Mapping):
            candidate = sku.get("capacity")
    if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate < 0:
        return None
    return candidate


def _model_deployment_projection(
    resource_type: str,
    properties: Mapping[str, object],
) -> dict[str, object] | None:
    """Return only reviewed model-deployment identity and capacity facts."""

    if resource_type != MODEL_DEPLOYMENT_RESOURCE_TYPE:
        return None
    capacity_tpm = properties.get("capacity_tpm")
    return {
        "model_name": _optional_text(properties.get("model_name")),
        "model_version": _optional_text(properties.get("model_version")),
        "sku_name": _optional_text(properties.get("sku_name")),
        "capacity_tpm": (
            capacity_tpm
            if isinstance(capacity_tpm, int)
            and not isinstance(capacity_tpm, bool)
            and 0 <= capacity_tpm <= MAX_MODEL_DEPLOYMENT_TPM
            else None
        ),
    }


def _resource_status(properties: Mapping[str, object], resource_type: str) -> str | None:
    for prefix in ("", "properties.", "properties.properties."):
        for path in operational_state_paths(resource_type):
            current: object = properties
            for part in (prefix + path).split("."):
                if not isinstance(current, Mapping):
                    current = None
                    break
                current = current.get(part)
            if is_recorded_state_value_valid(
                current,
                allow_unknown=path == "ready_status",
            ) and isinstance(current, str):
                value = current.strip()
                return _READY_STATUS_TEXT.get(value, value) if path == "ready_status" else value
    return None


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() and len(value) <= 256 else None


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
