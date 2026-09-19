"""Render one observer-only installation preview; no Kubernetes or Azure effects occur here."""

from __future__ import annotations

import argparse
import ipaddress
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from fdai_service_contracts.cluster_connector import (
    ConnectorContract,
    ConnectorRegistration,
    Digest,
    connector_time,
)
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.observer_deployment import ObserverDeploymentProposal, TargetRef
from pydantic import Field, field_validator

from fdai.delivery.kubernetes_connector_material import MATERIAL_FILES, material_digest
from fdai.delivery.kubernetes_connector_read_preflight import snapshot_read_attributes
from fdai.delivery.kubernetes_connector_runtime import (
    ConnectorRuntimeConfig,
    _unique_fields,
    connector_tls,
    private_file,
)

KubernetesName = Annotated[
    str, Field(min_length=1, max_length=63, pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
]


class ObserverInstallationInput(ConnectorContract):
    """Exact preview inputs. A referenced digest is not a release signature or plan approval."""

    target_ref: TargetRef
    namespace: KubernetesName
    name: Annotated[
        str, Field(max_length=50, pattern=r"^fdai-observer-[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
    ]
    image: Annotated[
        str, Field(max_length=512, pattern=r"^[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}$")
    ]
    material_secret: KubernetesName
    material_digest: Digest
    storage_class: KubernetesName
    gateway_port: Annotated[int, Field(strict=True, ge=1, le=65535)]
    api_port: Annotated[int, Field(strict=True, ge=1, le=65535)]
    gateway_cidrs: Annotated[tuple[str, ...], Field(min_length=1, max_length=8)]
    api_cidrs: Annotated[tuple[str, ...], Field(min_length=1, max_length=8)]
    dns_cidrs: Annotated[tuple[str, ...], Field(min_length=1, max_length=8)]

    @field_validator("namespace")
    @classmethod
    def _namespace(cls, value: str) -> str:
        if value == "default" or value.startswith("kube-") or value == "fdai-runtime":
            raise ValueError("observer preview requires a dedicated non-system namespace")
        return value

    @field_validator("gateway_cidrs", "api_cidrs", "dns_cidrs")
    @classmethod
    def _networks(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        result = []
        for value in values:
            network = ipaddress.ip_network(value, strict=True)
            if (
                network.prefixlen < (24 if network.version == 4 else 64)
                or network.is_multicast
                or network.is_loopback
                or network.is_unspecified
            ):
                raise ValueError("observer egress requires bounded unicast networks")
            result.append(str(network))
        if len(set(result)) != len(result):
            raise ValueError("observer egress networks must be unique")
        return tuple(sorted(result))


def validate_installation_material(
    inputs: ObserverInstallationInput, *, directory: Path, now: datetime
) -> None:
    """Check mounted bytes against the fixed recipe without outputting credential content.

    The deployment owner must still prove the Kubernetes target and gateway trust registration.
    Local validation binds the preview to its material, not to an installation authorization.
    """
    contents = {name: private_file(directory / name) for name in MATERIAL_FILES}
    if material_digest(contents) != inputs.material_digest:
        raise ValueError("observer installation material digest differs from the preview")
    config = ConnectorRuntimeConfig.model_validate(
        json.loads(contents["config.json"], object_pairs_hook=_unique_fields)
    )
    paths = {
        "registration_path": Path("/private/material/registrations.json"),
        "tls_ca_path": Path("/private/material/ca.pem"),
        "tls_certificate_path": Path("/private/material/client.pem"),
        "tls_key_path": Path("/private/material/client.key"),
        "spool_directory": Path("/spool/snapshots"),
        "api_ca_path": Path("/api-identity/ca.crt"),
        "api_token_path": Path("/api-identity/token"),
    }
    if config.role != "observer" or not config.allow_cluster_resources:
        raise ValueError("observer installation requires the complete cluster-read profile")
    if any(getattr(config, name) != value for name, value in paths.items()):
        raise ValueError("observer installation file paths do not match the workload recipe")
    gateway = urlsplit(config.gateway_origin or "")
    api = urlsplit(config.api_server or "")
    if (gateway.port or 443) != inputs.gateway_port or (api.port or 443) != inputs.api_port:
        raise ValueError("observer installation ports do not match the network policy")
    if api.hostname != "kubernetes.default.svc":
        raise ValueError("observer installation requires its in-cluster Kubernetes endpoint")
    entries = json.loads(contents["registrations.json"], object_pairs_hook=_unique_fields)
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError("observer installation requires exactly one enrollment")
    registration = ConnectorRegistration.model_validate(entries[0])
    if (
        registration.scope.cluster_ref != inputs.target_ref
        or inputs.namespace not in registration.namespaces
    ):
        raise ValueError("observer installation enrollment does not match its target and namespace")
    registration.admit(
        principal_ref=config.observer_principal_ref or "",
        scope=registration.scope,
        capability="inventory.snapshot",
        now=now,
    )
    connector_tls(
        config.model_copy(
            update={
                "tls_ca_path": directory / "ca.pem",
                "tls_certificate_path": directory / "client.pem",
                "tls_key_path": directory / "client.key",
            }
        )
    )
    if (
        material_digest({name: private_file(directory / name) for name in MATERIAL_FILES})
        != inputs.material_digest
    ):
        raise ValueError("observer installation material changed during validation")


def render_observer_installation(
    inputs: ObserverInstallationInput,
    proposal: ObserverDeploymentProposal,
    *,
    now: datetime,
    material_directory: Path,
) -> dict[str, Any]:
    """Return deterministic review material, not an executable approval or readiness receipt."""
    inputs = ObserverInstallationInput.model_validate_json(inputs.model_dump_json())
    proposal = ObserverDeploymentProposal.model_validate_json(proposal.model_dump_json())
    if (
        proposal.target_ref != inputs.target_ref
        or proposal.status != "ready_for_review"
        or proposal.recommended is None
        or not proposal.evaluated_at <= connector_time(now) < proposal.expires_at
    ):
        raise ValueError(
            "observer installation preview requires a current exact-target recommendation"
        )
    validate_installation_material(inputs, directory=material_directory, now=now)
    labels = {
        "app.kubernetes.io/name": "fdai-cluster-observer",
        "app.kubernetes.io/instance": inputs.name,
    }
    annotation = {
        "fdai.dev/proposal-digest": proposal.proposal_digest,
        "fdai.dev/execution-authority": "false",
    }

    def resource(
        api: str, kind: str, body: dict[str, Any], *, namespaced: bool = True
    ) -> dict[str, Any]:
        return {
            "apiVersion": api,
            "kind": kind,
            "metadata": {
                "name": inputs.name,
                **({"namespace": inputs.namespace} if namespaced else {}),
                "labels": labels.copy(),
                "annotations": annotation.copy(),
            },
            **body,
        }

    groups: dict[str, list[str]] = {}
    for attributes in snapshot_read_attributes():
        groups.setdefault(attributes["group"], []).append(attributes["resource"])
    rules = [
        {"apiGroups": [group], "resources": sorted(resources), "verbs": ["list"]}
        for group, resources in sorted(groups.items())
    ]
    rules.append(
        {
            "apiGroups": [""],
            "resources": ["namespaces"],
            "resourceNames": ["kube-system"],
            "verbs": ["get"],
        }
    )
    security = {
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
        "runAsNonRoot": True,
        "runAsUser": 10001,
        "runAsGroup": 10001,
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    common = {
        "image": inputs.image,
        "imagePullPolicy": "IfNotPresent",
        "securityContext": security,
        "resources": {
            "requests": {"cpu": "100m", "memory": "128Mi"},
            "limits": {"cpu": "500m", "memory": "512Mi"},
        },
    }
    pod = {
        "serviceAccountName": inputs.name,
        "automountServiceAccountToken": False,
        "restartPolicy": "Never",
        "terminationGracePeriodSeconds": 15,
        "securityContext": {
            "runAsNonRoot": True,
            "runAsUser": 10001,
            "runAsGroup": 10001,
            "fsGroup": 10001,
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "initContainers": [
            {
                **common,
                "name": "private-material",
                "command": ["python", "-m", "fdai.delivery.kubernetes_connector_material"],
                "args": [
                    "--source",
                    "/input",
                    "--destination",
                    "/private/material",
                    "--expected-digest",
                    inputs.material_digest,
                ],
                "volumeMounts": [
                    {"name": "material-input", "mountPath": "/input", "readOnly": True},
                    {"name": "private-material", "mountPath": "/private"},
                ],
            }
        ],
        "containers": [
            {
                **common,
                "name": "observer",
                "command": ["python", "-m", "fdai.delivery.kubernetes_connector_cli"],
                "args": ["observe-once", "--config", "/private/material/config.json"],
                "env": [{"name": "PYTHONDONTWRITEBYTECODE", "value": "1"}],
                "volumeMounts": [
                    {"name": "private-material", "mountPath": "/private", "readOnly": True},
                    {"name": "api-identity", "mountPath": "/api-identity", "readOnly": True},
                    {"name": "spool", "mountPath": "/spool"},
                ],
            }
        ],
        "volumes": [
            {
                "name": "material-input",
                "secret": {
                    "secretName": inputs.material_secret,
                    "defaultMode": 0o440,
                    "items": [{"key": name, "path": name} for name in MATERIAL_FILES],
                },
            },
            {"name": "private-material", "emptyDir": {"medium": "Memory", "sizeLimit": "4Mi"}},
            {
                "name": "api-identity",
                "projected": {
                    "defaultMode": 0o440,
                    "sources": [
                        {"serviceAccountToken": {"path": "token", "expirationSeconds": 600}},
                        {
                            "configMap": {
                                "name": "kube-root-ca.crt",
                                "items": [{"key": "ca.crt", "path": "ca.crt"}],
                            }
                        },
                    ],
                },
            },
            {"name": "spool", "persistentVolumeClaim": {"claimName": inputs.name}},
        ],
    }
    egress = [
        {"to": [{"ipBlock": {"cidr": cidr}} for cidr in networks], "ports": ports}
        for networks, ports in (
            (inputs.gateway_cidrs, [{"protocol": "TCP", "port": inputs.gateway_port}]),
            (inputs.api_cidrs, [{"protocol": "TCP", "port": inputs.api_port}]),
            (inputs.dns_cidrs, [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]),
        )
    ]
    documents = [
        resource("v1", "ServiceAccount", {"automountServiceAccountToken": False}),
        resource("rbac.authorization.k8s.io/v1", "ClusterRole", {"rules": rules}, namespaced=False),
        resource(
            "rbac.authorization.k8s.io/v1",
            "ClusterRoleBinding",
            {
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "ClusterRole",
                    "name": inputs.name,
                },
                "subjects": [
                    {"kind": "ServiceAccount", "name": inputs.name, "namespace": inputs.namespace}
                ],
            },
            namespaced=False,
        ),
        resource(
            "v1",
            "PersistentVolumeClaim",
            {
                "spec": {
                    "accessModes": ["ReadWriteOnce"],
                    "storageClassName": inputs.storage_class,
                    "resources": {"requests": {"storage": "1Gi"}},
                }
            },
        ),
        resource(
            "batch/v1",
            "CronJob",
            {
                "spec": {
                    "suspend": True,
                    "schedule": "* * * * *",
                    "concurrencyPolicy": "Forbid",
                    "startingDeadlineSeconds": 30,
                    "successfulJobsHistoryLimit": 1,
                    "failedJobsHistoryLimit": 1,
                    "jobTemplate": {
                        "spec": {
                            "backoffLimit": 0,
                            "activeDeadlineSeconds": 180,
                            "ttlSecondsAfterFinished": 3600,
                            "template": {"metadata": {"labels": labels.copy()}, "spec": pod},
                        }
                    },
                }
            },
        ),
        resource(
            "networking.k8s.io/v1",
            "NetworkPolicy",
            {
                "spec": {
                    "podSelector": {"matchLabels": labels.copy()},
                    "policyTypes": ["Ingress", "Egress"],
                    "ingress": [],
                    "egress": egress,
                }
            },
        ),
    ]
    return {
        "schema_version": "1.0.0",
        "target_ref": inputs.target_ref,
        "proposal_digest": proposal.proposal_digest,
        "method": proposal.recommended.method,
        "inputs_digest": canonical_digest(inputs.model_dump(mode="json")),
        "material_digest": inputs.material_digest,
        "manifest_digest": canonical_digest(documents),
        "documents": documents,
        "execution_authority": False,
        "approval_required": True,
        "installation_ready": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--material-directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        inputs = ObserverInstallationInput.model_validate_json(private_file(args.inputs))
        proposal = ObserverDeploymentProposal.model_validate_json(private_file(args.proposal))
        print(
            json.dumps(
                render_observer_installation(
                    inputs,
                    proposal,
                    now=datetime.now(UTC),
                    material_directory=args.material_directory,
                )
            )
        )
        return 0
    except (OSError, ValueError):
        print(json.dumps({"status": "unavailable", "reason": "observer_preview_rejected"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
