"""Same-schema Operator slice; Foundation supplies dependencies and reference objects.

This profile never bootstraps or upgrades a database. Its Core-image Job checks the
installed legacy and service heads before the Operator image can switch.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from fdai_lifecycle_agent.workload import (
    COMPONENT_LABEL,
    ENTITY_LABEL,
    FIELD_MANAGER,
    MANAGED_BY_LABEL,
    Manifest,
    WorkloadError,
    is_dns_label,
    render,
)

PROFILE = "operator-service-v1"
PROFILE_ANNOTATION = "fdai.io/workload-profile"


def validate_profile(
    values: Mapping[str, object],
    components: Mapping[str, frozenset[str]],
    *,
    current_schema: int,
    target_schema: int | None,
    schema_minimum: int | None,
    schema_maximum: int | None,
) -> None:
    """Reject incomplete topology and any schema transition, including rollback."""

    if values.get("workload_profile") != PROFILE:
        raise WorkloadError("workload_profile_unsupported")
    if list(components.values()) != [frozenset({"operator-service"})]:
        raise WorkloadError("workload_profile_entities_invalid")
    if not (
        target_schema == current_schema
        and schema_minimum is not None
        and schema_maximum is not None
        and schema_minimum <= current_schema <= schema_maximum
    ):
        raise WorkloadError("schema_transition_unsupported")
    config_map = values.get("operator_config_map_name")
    if not isinstance(config_map, str) or not is_dns_label(config_map):
        raise WorkloadError("workload_reference_invalid")
    for prefix in ("operator", "schema"):
        _database_name(values, prefix)
    replicas = values.get("replicas", 1)
    if type(replicas) is not int or not 1 <= replicas <= 3:
        raise WorkloadError("workload_replicas_invalid")


def render_operator(
    namespace: str,
    images: Mapping[tuple[str, str], str],
    *,
    core_image: str,
    values: Mapping[str, object],
    plan_digest: str,
) -> tuple[Manifest, ...]:
    """Render only a read-only schema Job, Operator Deployment, and internal Service.

    Configuration carries names, not values. Existing service accounts and the external
    Operator Service stay Foundation-owned. No role, identity, namespace, or Secret is rendered.
    The caller validates the profile and schema before invoking this renderer.
    """

    if (
        not is_dns_label(namespace)
        or len(images) != 1
        or any(component != "operator-service" for _, component in images)
    ):
        raise WorkloadError("workload_profile_entities_invalid")
    deployment, service = render(namespace, images)
    # Validate the migration image through the same immutable-reference boundary.
    render(namespace, {("schema-check", "core-control-plane"): core_image})
    if re.fullmatch(r"[0-9a-f]{64}", plan_digest, re.ASCII) is None:
        raise WorkloadError("workload_render_failed")
    entity = deployment["metadata"]["labels"][ENTITY_LABEL]
    labels = {
        **deployment["metadata"]["labels"],
        "app.kubernetes.io/name": "operator-service",
    }
    selector = {"app.kubernetes.io/name": "operator-service"}
    deployment["metadata"]["annotations"] = {PROFILE_ANNOTATION: PROFILE}
    deployment["spec"].update(
        replicas=values.get("replicas", 1),
        selector={"matchLabels": selector},
        strategy={"type": "RollingUpdate", "rollingUpdate": {"maxSurge": 1, "maxUnavailable": 0}},
    )
    pod = deployment["spec"]["template"]
    pod["metadata"]["labels"] = labels
    pod["spec"].update(
        serviceAccountName="operator-service",
        securityContext={
            "runAsNonRoot": True,
            "runAsUser": 65532,
            "runAsGroup": 65532,
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        volumes=[{"name": "tmp", "emptyDir": {"sizeLimit": "128Mi"}}],
    )
    container = pod["spec"]["containers"][0]
    container.update(
        name="operator-service",
        command=["fdai-operator-service"],
        ports=[{"name": "http", "containerPort": 8000}],
        envFrom=[{"configMapRef": {"name": values["operator_config_map_name"], "optional": False}}],
        env=[
            {"name": "FDAI_OPERATOR_SERVICE_HOST", "value": "0.0.0.0"},  # noqa: S104
            {"name": "FDAI_OPERATOR_SERVICE_PORT", "value": "8000"},
            {"name": "FDAI_DATABASE_ROLE", "value": "fdai_operator"},
            {
                "name": "FDAI_DATABASE_URL",
                "valueFrom": _secret(values, "operator"),
            },
        ],
        readinessProbe=_probe(5, 10),
        livenessProbe=_probe(10, 30),
        resources={
            "requests": {"cpu": "250m", "memory": "512Mi"},
            "limits": {"cpu": "1", "memory": "1Gi"},
        },
        securityContext={
            **container["securityContext"],
            "readOnlyRootFilesystem": True,
            "runAsNonRoot": True,
        },
        volumeMounts=[{"name": "tmp", "mountPath": "/tmp"}],  # noqa: S108 - pod-local emptyDir
    )
    service = {**service, "metadata": {**service["metadata"], "name": "operator-service-internal"}}
    service["spec"]["selector"] = selector
    service["spec"]["type"] = "ClusterIP"
    job_labels = {
        MANAGED_BY_LABEL: FIELD_MANAGER,
        ENTITY_LABEL: entity,
        COMPONENT_LABEL: "operator-schema-check",
    }
    job: Manifest = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": f"operator-schema-{plan_digest[:40]}",
            "namespace": namespace,
            "labels": job_labels,
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 120,
            "template": {
                "metadata": {"labels": job_labels},
                "spec": {
                    "serviceAccountName": "fdai-schema-check",
                    "automountServiceAccountToken": False,
                    "restartPolicy": "Never",
                    "securityContext": pod["spec"]["securityContext"],
                    "containers": [
                        {
                            "name": "schema-check",
                            "image": core_image,
                            "command": ["python", "-c", _schema_script()],
                            "env": [
                                {
                                    "name": "FDAI_DATABASE_URL",
                                    "valueFrom": _secret(values, "schema"),
                                }
                            ],
                            "securityContext": container["securityContext"],
                            "resources": container["resources"],
                        }
                    ],
                },
            },
        },
    }
    return job, deployment, service


def _secret(values: Mapping[str, object], prefix: str) -> dict[str, object]:
    return {
        "secretKeyRef": {
            "name": _database_name(values, prefix),
            "key": "FDAI_DATABASE_URL",
            "optional": False,
        }
    }


def _database_name(values: Mapping[str, object], prefix: str) -> str:
    reference = values.get(f"{prefix}_database")
    if (
        isinstance(reference, Mapping)
        and set(reference) == {"secret_name"}
        and isinstance(name := reference["secret_name"], str)
        and is_dns_label(name)
    ):
        return name
    raise WorkloadError("workload_reference_invalid")


def _probe(delay: int, period: int) -> dict[str, object]:
    return {
        "httpGet": {"path": "/healthz", "port": "http"},
        "initialDelaySeconds": delay,
        "periodSeconds": period,
        "timeoutSeconds": 3,
        "failureThreshold": 3,
    }


def _schema_script() -> str:
    return Path(__file__).with_name("schema_check.py").read_text(encoding="utf-8")
