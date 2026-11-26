"""Transform bounded PostgreSQL inventory rows into read-only graph projections."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final

import psycopg

from fdai.core.operational_context import project_operating_scope
from fdai.core.views.architecture_graph import project_architecture_graph
from fdai.delivery.inventory_schedule import (
    VM_SHUTDOWN_SCHEDULE_TYPE,
    project_vm_shutdown_schedule,
)
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.operating_model import OperatingModelSnapshot

_MAX_OPERATING_SCOPE_LINKS: Final[int] = 200_000


def _resource_payload(row: Mapping[str, Any], *, include_props: bool = False) -> dict[str, Any]:
    props = row["props"]
    if isinstance(props, str):
        props = json.loads(props)
    props = dict(props) if isinstance(props, Mapping) else {}
    payload = {
        "id": row["resource_id"],
        "type": row["resource_type"],
        "name": str(props.get("name") or row["resource_id"]),
        "status": str(props.get("status") or "unknown"),
        **({"parent_id": props["parent_id"]} if props.get("parent_id") else {}),
    }
    if include_props:
        payload["props"] = props
    if row["resource_type"] == VM_SHUTDOWN_SCHEDULE_TYPE:
        try:
            schedule = project_vm_shutdown_schedule(props)
        except ValueError:
            schedule = None
            payload["projection_warnings"] = ["invalid_shutdown_schedule"]
        if schedule is not None:
            payload.update(
                {
                    "scheduled_shutdown_status": schedule["scheduledShutdownStatus"],
                    "scheduled_shutdown_time": schedule["scheduledShutdownTime"],
                    "scheduled_shutdown_time_zone": schedule["scheduledShutdownTimeZone"],
                    "scheduled_shutdown_time_zone_iana": schedule["scheduledShutdownTimeZoneIana"],
                    "scheduled_shutdown_target_name": schedule["scheduledShutdownTargetName"],
                    "scheduled_shutdown_target_resource_group": schedule[
                        "scheduledShutdownTargetResourceGroup"
                    ],
                    "scheduled_shutdown_target_subscription_digest": schedule[
                        "scheduledShutdownTargetSubscriptionDigest"
                    ],
                }
            )
    return payload


async def _load_operating_scope(
    connection: psycopg.AsyncConnection[Any],
    resource_ids: tuple[str, ...],
) -> tuple[tuple[OntologyObjectRecord, ...], tuple[OntologyLinkRecord, ...], bool]:
    """Load only service paths that terminate at the bounded response resources."""
    if not resource_ids:
        return (), (), True
    workload_cursor = await connection.execute(
        "SELECT link_type, from_id, to_id FROM ontology_link "
        "WHERE link_type='workload_runs_on' AND to_id=ANY(%s::text[]) "
        "ORDER BY from_id, to_id LIMIT %s",
        (list(resource_ids), _MAX_OPERATING_SCOPE_LINKS + 1),
    )
    workload_rows = await workload_cursor.fetchall()
    if len(workload_rows) > _MAX_OPERATING_SCOPE_LINKS:
        return (), (), False
    workload_ids = tuple(sorted({str(row["from_id"]) for row in workload_rows}))
    service_rows: Sequence[Mapping[str, Any]] = ()
    if workload_ids:
        remaining = _MAX_OPERATING_SCOPE_LINKS - len(workload_rows)
        service_cursor = await connection.execute(
            "SELECT link_type, from_id, to_id FROM ontology_link "
            "WHERE link_type='implemented_by' AND to_id=ANY(%s::text[]) "
            "ORDER BY from_id, to_id LIMIT %s",
            (list(workload_ids), remaining + 1),
        )
        service_rows = await service_cursor.fetchall()
        if len(service_rows) > remaining:
            return (), (), False
    endpoint_ids = tuple(sorted(set(workload_ids) | {str(row["from_id"]) for row in service_rows}))
    objects: tuple[OntologyObjectRecord, ...] = ()
    if endpoint_ids:
        object_cursor = await connection.execute(
            "SELECT id, object_type, revision FROM ontology_resource "
            "WHERE id=ANY(%s::text[]) "
            "AND object_type=ANY(%s::text[]) ORDER BY id",
            (list(endpoint_ids), ["BusinessService", "Workload"]),
        )
        objects = tuple(
            OntologyObjectRecord(
                id=str(row["id"]),
                object_type=str(row["object_type"]),
                properties={},
                revision=int(row["revision"]),
            )
            for row in await object_cursor.fetchall()
        )
    unique_links = {
        (str(row["link_type"]), str(row["from_id"]), str(row["to_id"]))
        for row in (*workload_rows, *service_rows)
    }
    return (
        objects,
        tuple(OntologyLinkRecord(*values) for values in sorted(unique_links)),
        True,
    )


def _annotate_operating_scope(
    resources: Sequence[Mapping[str, Any]],
    *,
    source_revision: str,
    objects: Sequence[OntologyObjectRecord] = (),
    links: Sequence[OntologyLinkRecord] = (),
    input_complete: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, object]]:
    """Attach reviewed service coverage to every bounded inventory Resource."""
    resource_objects = tuple(
        OntologyObjectRecord(
            id=str(resource["id"]),
            object_type="Resource",
            properties={},
        )
        for resource in resources
    )
    resource_ids = {item.id for item in resource_objects}
    coverage = project_operating_scope(
        OperatingModelSnapshot(
            source_revision=source_revision,
            objects=(
                *resource_objects,
                *(item for item in objects if item.id not in resource_ids),
            ),
            links=tuple(links),
        )
    )
    by_resource = {item.resource_id: item for item in coverage.resources}
    annotated = [
        {
            **dict(resource),
            "service_ref": by_resource[str(resource["id"])].service_ref,
        }
        for resource in resources
    ]
    unmapped_count = len(coverage.unmapped_resource_ids)
    return annotated, {
        "source_revision": coverage.source_revision,
        "input_complete": input_complete,
        "complete": input_complete and unmapped_count == 0,
        "resource_count": len(coverage.resources),
        "mapped_resource_count": len(coverage.resources) - unmapped_count,
        "unmapped_resource_count": unmapped_count,
    }


def _source_priority(metadata: object) -> int:
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    if not isinstance(metadata, Mapping):
        return 2**31 - 1
    value = metadata.get("source_priority")
    return value if isinstance(value, int) and not isinstance(value, bool) else 2**31 - 1


def _unavailable_graph() -> dict[str, Any]:
    projection = project_architecture_graph(resources=(), links=(), requested_view=None)
    return {
        "snapshot_at": datetime.now(tz=UTC).isoformat(),
        "freshness": "unknown",
        "source": "unavailable",
        "observation_kind": "observed",
        "age_seconds": None,
        "coverage": {"scopes": [], "resource_types": []},
        "coverage_gaps": ["no active inventory snapshot"],
        "degraded": True,
        "realtime": {"pending_changes": 0, "latest_at": None},
        "active_view": projection["active_view"],
        "resources": projection["resources"],
        "links": projection["links"],
        "views": projection["views"],
        "truncated": False,
        "cursor": None,
    }
