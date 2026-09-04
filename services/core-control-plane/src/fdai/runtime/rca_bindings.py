"""Deployment-owned Azure history and fresh dependency bindings for T1 RCA."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

import httpx

from fdai.composition import Container
from fdai.core.ontology_platform.topology_history import (
    TopologyHistoryReader,
    graph_at,
)
from fdai.core.rca.causal_chain import CorrelatedEvent
from fdai.core.rca.deployment_member_source import DeploymentHistoryMemberSource
from fdai.core.rca.member_source import (
    IncidentMemberSource,
    IncidentRcaContext,
)
from fdai.delivery.azure.deployment_history import (
    AzureActivityDeploymentHistoryProvider,
    AzureDeploymentHistoryConfig,
)
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.persistence.postgres_provider_identity import (
    PostgresAzureResourceIdentityResolver,
    PostgresAzureResourceIdentityResolverConfig,
)
from fdai.delivery.persistence.postgres_topology_history import (
    PostgresTopologyHistoryStore,
    PostgresTopologyHistoryStoreConfig,
)
from fdai.runtime.venue import resolve_execution_venue, uses_developer_identity
from fdai.shared.contracts.models import Incident, IncidentState
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyInstanceStore,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("fdai.startup")
_DEPENDENCY_LINK = "depends_on"
_MAX_GRAPH_RESOURCES = 5_000


@dataclass(frozen=True, slots=True)
class ReviewedDependencyGraph:
    """One complete dependency mapping pinned to an inventory generation."""

    depends_on: Mapping[str, frozenset[str]]
    inventory_generation: str
    dependency_digest: str


@dataclass(frozen=True, slots=True)
class GenerationGuardedIncidentMemberSource:
    """Return incident members only while the reviewed graph generation is current."""

    source: IncidentMemberSource
    graph_store: OntologyInstanceStore
    required_generation: str
    required_dependency_digest: str

    async def members(self, *, incident_id: str) -> Sequence[CorrelatedEvent]:
        try:
            graph = await load_reviewed_dependency_graph(self.graph_store)
        except Exception:  # noqa: BLE001 - IncidentMemberSource MUST never raise
            _LOGGER.warning(
                "rca_dependency_generation_unavailable",
                extra={"incident_id": incident_id},
                exc_info=True,
            )
            return ()
        if (
            graph is None
            or graph.inventory_generation != self.required_generation
            or graph.dependency_digest != self.required_dependency_digest
        ):
            _LOGGER.info(
                "rca_dependency_generation_stale",
                extra={"incident_id": incident_id},
            )
            return ()
        members = tuple(await self.source.members(incident_id=incident_id))
        if any(member.inventory_generation != self.required_generation for member in members):
            _LOGGER.info(
                "rca_member_inventory_generation_mismatch",
                extra={"incident_id": incident_id},
            )
            return ()
        try:
            after = await load_reviewed_dependency_graph(self.graph_store)
        except Exception:  # noqa: BLE001 - IncidentMemberSource MUST never raise
            _LOGGER.warning(
                "rca_dependency_generation_unavailable_after_read",
                extra={"incident_id": incident_id},
                exc_info=True,
            )
            return ()
        if (
            after is None
            or after.inventory_generation != self.required_generation
            or after.dependency_digest != self.required_dependency_digest
        ):
            _LOGGER.info(
                "rca_dependency_generation_changed_during_read",
                extra={"incident_id": incident_id},
            )
            return ()
        return members


@dataclass(frozen=True, slots=True)
class TopologyHistoryIncidentRcaContextSource:
    """Load deployment changes and dependency topology at one incident cutoff."""

    incident_lookup: Callable[[UUID], Incident | None]
    incident_candidates: Callable[[], Mapping[UUID, Incident]]
    member_source: DeploymentHistoryMemberSource
    topology_history: TopologyHistoryReader
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC)

    async def context(
        self,
        *,
        incident_id: str,
        resource_ref: str,
        event_type: str,
        correlation_id: str | None,
        detected_at: datetime,
    ) -> IncidentRcaContext | None:
        try:
            identity = UUID(incident_id)
        except ValueError:
            return None
        incident = self.incident_lookup(identity)
        if incident is not None and not _incident_active_at(
            incident,
            detected_at=detected_at,
        ):
            incident = None
        if incident is None:
            incident = _match_lifecycle_incident(
                self.incident_candidates(),
                resource_ref=resource_ref,
                event_type=event_type,
                correlation_id=correlation_id,
                detected_at=detected_at,
            )
        if incident is None:
            return None
        known_at = self.clock()
        if known_at.tzinfo is None or incident.opened_at > known_at:
            return None
        batches = await self.topology_history.read(
            as_of=detected_at,
            known_at=known_at,
        )
        topology = graph_at(
            batches,
            as_of=detected_at,
            known_at=known_at,
        )
        generations = tuple(dict.fromkeys(topology.provider_generation_refs))
        if not topology.complete or len(generations) != 1:
            return None
        depends_on = _dependency_mapping(topology.graph)
        if not depends_on:
            return None
        members = tuple(
            await self.member_source.members_for_incident(
                incident,
                cutoff=detected_at,
            )
        )
        if not members or any(member.inventory_generation != generations[0] for member in members):
            return None
        return IncidentRcaContext(
            members=members,
            depends_on=depends_on,
            inventory_generation=generations[0],
        )


async def bind_t1_rca_from_environment(
    container: Container,
    *,
    incident_lookup: Callable[[UUID], Incident | None],
    incident_candidates: Callable[[], Mapping[UUID, Incident]],
    http_client: httpx.AsyncClient | None,
    identity: WorkloadIdentity | None,
    environment: Mapping[str, str],
) -> Container:
    """Bind Azure deployment history only with a complete current dependency graph."""

    if (
        container.incident_member_source is not None
        or container.incident_rca_context_source is not None
    ):
        if not container.resource_dependency_graph:
            _LOGGER.info(
                "t1_rca_deployment_history_unavailable",
                extra={"reason": "injected_dependency_graph_absent"},
            )
        return container
    state_dsn = environment.get("FDAI_STATE_STORE_DSN", "").strip()
    if not state_dsn or http_client is None or identity is None:
        _LOGGER.info(
            "t1_rca_deployment_history_unavailable",
            extra={"reason": "deployment_prerequisites_absent"},
        )
        return container

    venue = resolve_execution_venue(environment)
    reader_identity = identity
    if not uses_developer_identity(venue):
        if not environment.get("FDAI_RCA_AZURE_READER_CLIENT_ID", "").strip():
            _LOGGER.info(
                "t1_rca_deployment_history_unavailable",
                extra={"reason": "dedicated_reader_identity_absent"},
            )
            return container
        reader_identity = ManagedIdentityWorkloadIdentity.from_env(
            http_client=http_client,
            env=environment,
            client_id_env="FDAI_RCA_AZURE_READER_CLIENT_ID",
        )

    freshness_seconds = _bounded_integer(
        environment.get("FDAI_INVENTORY_FRESHNESS_SECONDS", ""),
        default=86_400,
        minimum=1,
        maximum=604_800,
        name="FDAI_INVENTORY_FRESHNESS_SECONDS",
    )
    inventory_dsn = environment.get("FDAI_INVENTORY_DSN", "").strip() or state_dsn
    resource_identities = PostgresAzureResourceIdentityResolver(
        config=PostgresAzureResourceIdentityResolverConfig(
            dsn=inventory_dsn.replace(
                "postgresql+psycopg://",
                "postgresql://",
                1,
            ),
            freshness_budget_seconds=freshness_seconds,
        )
    )
    history = AzureActivityDeploymentHistoryProvider(
        identity=reader_identity,
        resource_identities=resource_identities,
        http_client=http_client,
        config=AzureDeploymentHistoryConfig(
            endpoint=environment.get(
                "FDAI_INVENTORY_MANAGEMENT_ENDPOINT",
                "https://management.azure.com",
            ).strip(),
            audience=environment.get(
                "FDAI_INVENTORY_MANAGEMENT_AUDIENCE",
                "https://management.azure.com/.default",
            ).strip(),
        ),
    )

    def lookup(raw_incident_id: str) -> Incident | None:
        try:
            incident_id = UUID(raw_incident_id)
        except ValueError:
            return None
        return incident_lookup(incident_id)

    base_source = DeploymentHistoryMemberSource(
        lookup=lookup,
        deployment_history=history,
        lookback=environment.get("FDAI_RCA_DEPLOYMENT_LOOKBACK", "P1D").strip(),
    )
    source = TopologyHistoryIncidentRcaContextSource(
        incident_lookup=incident_lookup,
        incident_candidates=incident_candidates,
        member_source=base_source,
        topology_history=PostgresTopologyHistoryStore(
            config=PostgresTopologyHistoryStoreConfig(
                dsn=state_dsn.replace(
                    "postgresql+psycopg://",
                    "postgresql://",
                    1,
                )
            )
        ),
    )
    _LOGGER.info("t1_rca_deployment_history_ready")
    return replace(
        container,
        incident_rca_context_source=source,
    )


async def load_reviewed_dependency_graph(
    store: OntologyInstanceStore,
) -> ReviewedDependencyGraph | None:
    """Load one complete verified Resource dependency graph or return unavailable."""

    snapshot = await store.traverse_from_type(
        root_object_type="Resource",
        link_types=(_DEPENDENCY_LINK,),
        direction="outgoing",
        max_depth=1,
        limit=_MAX_GRAPH_RESOURCES,
    )
    if snapshot.truncated or not snapshot.source_complete or snapshot.source_generation is None:
        return None
    depends_on = _dependency_mapping(snapshot)
    return ReviewedDependencyGraph(
        depends_on=depends_on,
        inventory_generation=snapshot.source_generation,
        dependency_digest=_dependency_digest(depends_on),
    )


def _dependency_mapping(
    snapshot: OntologyGraphSnapshot,
) -> Mapping[str, frozenset[str]]:
    resources = {item.id for item in snapshot.objects if item.object_type == "Resource"}
    mapping: dict[str, set[str]] = {}
    for link in snapshot.links:
        if link.link_type != _DEPENDENCY_LINK:
            continue
        if link.from_id not in resources or link.to_id not in resources:
            raise ValueError("dependency graph contains an invalid Resource edge")
        mapping.setdefault(link.from_id, set()).add(link.to_id)
    return {key: frozenset(sorted(values)) for key, values in sorted(mapping.items())}


def _dependency_digest(depends_on: Mapping[str, frozenset[str]]) -> str:
    material = json.dumps(
        {key: sorted(values) for key, values in sorted(depends_on.items())},
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(material.encode()).hexdigest()}"


def _match_lifecycle_incident(
    incidents: Mapping[UUID, Incident],
    *,
    resource_ref: str,
    event_type: str,
    correlation_id: str | None,
    detected_at: datetime,
) -> Incident | None:
    required = {
        f"resource:{resource_ref}",
        f"signal:{event_type}",
    }
    if correlation_id:
        required.add(f"correlation:{correlation_id}")
    matches = tuple(
        incident
        for _, incident in sorted(incidents.items(), key=lambda item: str(item[0]))
        if required.issubset(set(incident.correlation_keys))
        and _incident_active_at(incident, detected_at=detected_at)
    )
    return matches[0] if len(matches) == 1 else None


def _incident_active_at(
    incident: Incident,
    *,
    detected_at: datetime,
) -> bool:
    terminal = (
        incident.closed_at
        if incident.state is IncidentState.CLOSED
        else incident.resolved_at
        if incident.state is IncidentState.RESOLVED
        else None
    )
    return incident.opened_at <= detected_at and (terminal is None or detected_at <= terminal)


def _bounded_integer(
    raw: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
    name: str,
) -> int:
    if not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} MUST be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} MUST be in [{minimum}, {maximum}]")
    return value


__all__ = [
    "GenerationGuardedIncidentMemberSource",
    "ReviewedDependencyGraph",
    "TopologyHistoryIncidentRcaContextSource",
    "bind_t1_rca_from_environment",
    "load_reviewed_dependency_graph",
]
