"""Read-only derivation of an enrollment request from the Agent's own namespace.

Entities and reported state are observed, never declared: a workload belongs to an Entity when it
carries the `fdai.io/entity` label. Release id, schema revision and artifact digests come from
explicit workload metadata, and health from rollout status. Anything ambiguous, unbounded or
unobserved is refused instead of guessed, because the Hub treats this snapshot as the
installation's claim and plans from it only after a human approves.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.runtime_release import is_release_id

from fdai_lifecycle_agent.installation_declaration import InstallationDeclaration
from fdai_lifecycle_agent.workload import (
    ENTITY_LABEL,
    Manifest,
    WorkloadError,
    deployment_image_digests,
    is_dns_label,
)

VERSION_LABEL = "app.kubernetes.io/version"
SCHEMA_REVISION_ANNOTATION = "fdai.io/schema-revision"
ENTITY_KIND = "workload"
MAX_ENTITIES = 64
MAX_RELEASE_ID_LENGTH = 128
MAX_SCHEMA_REVISION = 2**31 - 1
_ENTITY_ID = re.compile(r"[a-z][a-z0-9-]{0,62}\Z", re.ASCII)
_REVISION = re.compile(r"(?:0|[1-9][0-9]{0,9})\Z", re.ASCII)

type Workloads = tuple[Sequence[Manifest], Sequence[Manifest]]


class EntityWorkloadSource(Protocol):
    """Installation-bound, read-only seam: Entity-labelled `(deployments, cronjobs)`."""

    def list_entity_workloads(self) -> Workloads: ...


def derive_enrollment_facts(
    source: EntityWorkloadSource, *, namespace: str, now: datetime
) -> tuple[list[dict[str, str]], dict[str, object]]:
    """Return the declared Entities and the reported state for one namespace.

    Raises ``WorkloadError`` with a stable reason code when the observation cannot be trusted.
    """

    if not is_dns_label(namespace):
        raise WorkloadError("enrollment_source_outside_scope")
    deployments, cronjobs = source.list_entity_workloads()
    grouped: dict[str, list[Manifest]] = {}
    for kind, items in (("Deployment", deployments), ("CronJob", cronjobs)):
        for item in items:
            grouped.setdefault(_entity_id(item, namespace), []).append({**item, "kind": kind})
    if not grouped:
        raise WorkloadError("enrollment_no_entities_observed")
    if len(grouped) > MAX_ENTITIES:
        raise WorkloadError("enrollment_too_many_entities")
    states: dict[str, dict[str, object]] = {}
    revisions: set[int] = set()
    for entity_id, workloads in sorted(grouped.items()):
        release_id = _release_id(workloads)
        if release_id is None:
            states[entity_id] = {"release_id": None, "artifact_digests": [], "health": "unknown"}
            continue
        revisions.add(_schema_revision(workloads))
        digests = sorted({d for workload in workloads for d in deployment_image_digests(workload)})
        states[entity_id] = {
            "release_id": release_id,
            "artifact_digests": digests,
            "health": _health(workloads),
        }
    if len(revisions) > 1:
        raise WorkloadError("enrollment_schema_revision_ambiguous")
    schema_revision = next(iter(revisions), 0)
    reported: dict[str, object] = {
        "digest": canonical_digest({"schema_revision": schema_revision, "entities": states}),
        "schema_revision": schema_revision,
        "entities": states,
        "observed_at": now.isoformat(),
    }
    entities = [{"entity_id": entity_id, "kind": ENTITY_KIND} for entity_id in sorted(states)]
    return entities, reported


def enrollment_template(
    declaration: InstallationDeclaration,
    entities: Sequence[Mapping[str, str]],
    reported: Mapping[str, object],
) -> dict[str, object]:
    """The unsigned payload: customer-declared fields plus cluster-derived facts."""

    return {**declaration.enrollment_template(), "entities": list(entities), "reported": reported}


def _entity_id(workload: Manifest, namespace: str) -> str:
    metadata = workload.get("metadata")
    labels = metadata.get("labels") if isinstance(metadata, Mapping) else None
    entity_id = labels.get(ENTITY_LABEL) if isinstance(labels, Mapping) else None
    if (
        not isinstance(metadata, Mapping)
        or metadata.get("namespace") not in (None, namespace)
        or not isinstance(entity_id, str)
        or _ENTITY_ID.fullmatch(entity_id) is None
    ):
        raise WorkloadError("enrollment_entity_invalid")
    return entity_id


def _release_id(workloads: Sequence[Manifest]) -> str | None:
    values = {
        (workload["metadata"].get("labels") or {}).get(VERSION_LABEL) for workload in workloads
    }
    if values == {None}:
        return None
    (value,) = values if len(values) == 1 else (None,)
    if not isinstance(value, str) or len(value) > MAX_RELEASE_ID_LENGTH or not is_release_id(value):
        raise WorkloadError("enrollment_release_ambiguous")
    return value


def _schema_revision(workloads: Sequence[Manifest]) -> int:
    values = {
        (workload["metadata"].get("annotations") or {}).get(SCHEMA_REVISION_ANNOTATION)
        for workload in workloads
    }
    (value,) = values if len(values) == 1 else (None,)
    if (
        not isinstance(value, str)
        or _REVISION.fullmatch(value) is None
        or int(value) > MAX_SCHEMA_REVISION
    ):
        raise WorkloadError("enrollment_schema_revision_unobserved")
    return int(value)


def _health(workloads: Sequence[Manifest]) -> str:
    deployments = [workload for workload in workloads if workload["kind"] == "Deployment"]
    states = {_deployment_health(deployment) for deployment in deployments}
    for state in ("unhealthy", "degraded"):
        if state in states:
            return state
    return "healthy" if states == {"healthy"} else "unknown"


def _deployment_health(deployment: Manifest) -> str:
    spec = deployment.get("spec") or {}
    status = deployment.get("status") or {}
    desired = spec["replicas"] if "replicas" in spec else status.get("replicas", 0)
    counts = [
        status.get(name, 0)
        for name in ("replicas", "updatedReplicas", "availableReplicas", "readyReplicas")
    ]
    generation = (deployment.get("metadata") or {}).get("generation", 0)
    if (
        not isinstance(desired, int)
        or not all(isinstance(count, int) for count in counts)
        or desired < 1
        or status.get("availableReplicas", 0) < 1
    ):
        return "unhealthy"
    if status.get("observedGeneration", -1) >= generation and all(
        count == desired for count in counts
    ):
        return "healthy"
    return "degraded"
