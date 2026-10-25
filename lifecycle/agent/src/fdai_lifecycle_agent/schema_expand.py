"""Render one bounded schema-expand Job before application workloads switch."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.lifecycle_release import (
    MIGRATION_CLASSIFICATION_SCHEMA,
    SchemaExpandMigration,
)

from fdai_lifecycle_agent.workload import (
    COMPONENT_LABEL,
    ENTITY_LABEL,
    FIELD_MANAGER,
    MANAGED_BY_LABEL,
    Manifest,
    WorkloadError,
)

SCHEMA_EXPAND_ANNOTATION = "fdai.io/schema-expand"
SCHEMA_TARGET_ANNOTATION = "fdai.io/schema-target"
CLASSIFICATION_DIGEST_ANNOTATION = "fdai.io/migration-classification-digest"
RELEASE_DIGEST_ANNOTATION = "fdai.io/release-digest"
_PLAN_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


def render_schema_expand_job(
    desired: tuple[Manifest, ...],
    migration: SchemaExpandMigration,
    *,
    namespace: str,
    plan_digest: str,
    release_digest: str,
    schema_target: int,
) -> Manifest:
    """Render a fixed Core-image migration Job from reviewed runtime references."""

    if (
        _PLAN_DIGEST.fullmatch(plan_digest) is None
        or not release_digest.startswith("sha256:")
        or schema_target < 1
    ):
        raise WorkloadError("schema_expand_job_invalid")
    core = next(
        (
            item
            for item in desired
            if item["kind"] == "Deployment" and item["metadata"]["name"] == "core-control-plane"
        ),
        None,
    )
    if core is None:
        raise WorkloadError("schema_expand_core_unavailable")
    pod = core["spec"]["template"]["spec"]
    containers = pod.get("containers", [])
    if not isinstance(containers, list) or len(containers) != 1:
        raise WorkloadError("schema_expand_core_invalid")
    core_container = containers[0]
    environment = deepcopy(core_container.get("env", []))
    database_entries = [
        item
        for item in environment
        if isinstance(item, Mapping) and item.get("name") == "FDAI_DATABASE_URL"
    ]
    if (
        len(database_entries) != 1
        or set(database_entries[0]) != {"name", "valueFrom"}
        or not isinstance(database_entries[0]["valueFrom"], Mapping)
    ):
        raise WorkloadError("schema_expand_database_reference_missing")
    if any(
        not isinstance(item, Mapping)
        or item.get("name")
        in {
            "FDAI_MIGRATION_CLASSIFICATION",
            "FDAI_MIGRATION_RELEASE_DIGEST",
            "FDAI_MIGRATION_SCHEMA_TARGET",
        }
        for item in environment
    ):
        raise WorkloadError("schema_expand_environment_conflict")
    classification = {
        "schema": MIGRATION_CLASSIFICATION_SCHEMA,
        "revisions": dict(migration.classification),
    }
    environment.extend(
        [
            {
                "name": "FDAI_MIGRATION_CLASSIFICATION",
                "value": _canonical_json(classification),
            },
            {"name": "FDAI_MIGRATION_RELEASE_DIGEST", "value": release_digest},
            {"name": "FDAI_MIGRATION_SCHEMA_TARGET", "value": str(schema_target)},
        ]
    )
    labels = {
        MANAGED_BY_LABEL: FIELD_MANAGER,
        ENTITY_LABEL: core["metadata"]["labels"][ENTITY_LABEL],
        COMPONENT_LABEL: "schema-expand",
    }
    annotations = {
        SCHEMA_EXPAND_ANNOTATION: "true",
        SCHEMA_TARGET_ANNOTATION: str(schema_target),
        CLASSIFICATION_DIGEST_ANNOTATION: f"sha256:{canonical_digest(classification)}",
        RELEASE_DIGEST_ANNOTATION: release_digest,
    }
    container: dict[str, Any] = {
        "name": "schema-expand",
        "image": core_container["image"],
        "command": ["python", "-m", "fdai.delivery.lifecycle_schema_expand"],
        "env": environment,
        "resources": deepcopy(core_container["resources"]),
        "securityContext": deepcopy(core_container["securityContext"]),
    }
    for key in ("envFrom", "volumeMounts"):
        if key in core_container:
            container[key] = deepcopy(core_container[key])
    job_pod: dict[str, Any] = {
        "serviceAccountName": "fdai-schema-migration",
        "automountServiceAccountToken": True,
        "restartPolicy": "Never",
        "securityContext": deepcopy(pod["securityContext"]),
        "containers": [container],
    }
    if "volumes" in pod:
        job_pod["volumes"] = deepcopy(pod["volumes"])
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": f"fdai-schema-expand-{plan_digest[:40]}",
            "namespace": namespace,
            "labels": labels,
            "annotations": annotations,
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": migration.active_deadline_seconds,
            "template": {
                "metadata": {"labels": labels, "annotations": annotations},
                "spec": job_pod,
            },
        },
    }


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
