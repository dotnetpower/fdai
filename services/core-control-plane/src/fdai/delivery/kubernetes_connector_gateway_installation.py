"""Render the connector gateway as an ordinary, restricted workload.

The gateway needs no Kubernetes API permission, so the recipe has no RBAC objects. Material is the
same digest-pinned bundle the observer uses (`config.json`, `registrations.json`, `ca.pem`, and the
server certificate and key as `client.pem` and `client.key`). The state-store DSN is a Secret
reference, never a value. Exposure follows the topology decision and never opens a public address.
"""

from __future__ import annotations

import ipaddress
import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from fdai_service_contracts.cluster_connector import ConnectorContract, Digest
from fdai_service_contracts.compatibility import canonical_digest
from pydantic import Field, field_validator, model_validator

from fdai.delivery.kubernetes_connector_gateway_exposure import ExposureDecision
from fdai.delivery.kubernetes_connector_installation import GatewayPeer
from fdai.delivery.kubernetes_connector_material import MATERIAL_FILES, material_digest
from fdai.delivery.kubernetes_connector_runtime import (
    ConnectorRuntimeConfig,
    _unique_fields,
    private_file,
)

KubernetesName = Annotated[
    str, Field(min_length=1, max_length=63, pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
]
_LISTEN_PORT = 8443


class GatewayInstallationInput(ConnectorContract):
    """Exact private inputs for one gateway installation."""

    namespace: KubernetesName
    name: Annotated[
        str, Field(max_length=50, pattern=r"^fdai-gateway-[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
    ]
    image: Annotated[
        str, Field(max_length=512, pattern=r"^[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}$")
    ]
    material_secret: KubernetesName
    material_digest: Digest
    database_secret: KubernetesName
    database_secret_key: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,253}$")] = "dsn"  # noqa: S105
    database_cidrs: Annotated[tuple[str, ...], Field(max_length=8)] = ()
    database_peer: GatewayPeer | None = None
    database_port: Annotated[int, Field(strict=True, ge=1, le=65535)] = 5432
    ingress_cidrs: Annotated[tuple[str, ...], Field(max_length=8)] = ()
    ingress_peers: Annotated[tuple[GatewayPeer, ...], Field(max_length=8)] = ()
    dns_cidrs: Annotated[tuple[str, ...], Field(min_length=1, max_length=8)]
    replicas: Annotated[int, Field(strict=True, ge=1, le=3)] = 2
    exposure: Literal["internal_load_balancer", "private_link_service"]
    private_link_subnet: KubernetesName | None = None
    private_link_subscriptions: Annotated[tuple[str, ...], Field(max_length=8)] = ()

    @field_validator("database_cidrs", "dns_cidrs")
    @classmethod
    def _networks(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _bounded(values, widest=24)

    @field_validator("ingress_cidrs")
    @classmethod
    def _ingress(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        # An observer network is a whole peered VNet, so ingress may be wider than a service CIDR.
        return _bounded(values, widest=16)

    @field_validator("namespace")
    @classmethod
    def _namespace(cls, value: str) -> str:
        if value == "default" or value.startswith("kube-"):
            raise ValueError("gateway requires a dedicated non-system namespace")
        return value

    @model_validator(mode="after")
    def _exposure(self) -> Self:
        if not self.ingress_cidrs and not self.ingress_peers:
            raise ValueError("the gateway needs bounded ingress networks or in-cluster peers")
        if not self.database_cidrs and self.database_peer is None:
            raise ValueError("the state store needs bounded networks or an in-cluster peer")
        if self.exposure == "private_link_service" and not (
            self.private_link_subnet and self.private_link_subscriptions
        ):
            raise ValueError(
                "a Private Link service needs its NAT subnet and the subscriptions it may approve"
            )
        return self


# The Service port equals the Pod port because a policy engine evaluates egress after service
# translation and the observer pins one gateway port for both its origin and its egress rule.


def _bounded(values: tuple[str, ...], *, widest: int) -> tuple[str, ...]:
    result = []
    for value in values:
        network = ipaddress.ip_network(value, strict=True)
        if (
            network.prefixlen < (widest if network.version == 4 else 64)
            or network.is_multicast
            or network.is_loopback
            or network.is_unspecified
        ):
            raise ValueError("gateway networks must be bounded unicast networks")
        result.append(str(network))
    if len(set(result)) != len(result):
        raise ValueError("gateway networks must be unique")
    return tuple(sorted(result))


def validate_gateway_material(
    inputs: GatewayInstallationInput, *, directory: Path
) -> ConnectorRuntimeConfig:
    """Bind the preview to the exact mounted bytes and the paths the recipe will provide."""
    contents = {name: private_file(directory / name) for name in MATERIAL_FILES}
    if material_digest(contents) != inputs.material_digest:
        raise ValueError("gateway material digest differs from the preview")
    config = ConnectorRuntimeConfig.model_validate(
        json.loads(contents["config.json"], object_pairs_hook=_unique_fields)
    )
    expected = {
        "registration_path": Path("/private/material/registrations.json"),
        "tls_ca_path": Path("/private/material/ca.pem"),
        "tls_certificate_path": Path("/private/material/client.pem"),
        "tls_key_path": Path("/private/material/client.key"),
    }
    if config.role != "gateway" or any(getattr(config, k) != v for k, v in expected.items()):
        raise ValueError("gateway configuration does not match the fixed recipe paths")
    if config.listen_host != "0.0.0.0" or config.listen_port != _LISTEN_PORT:  # noqa: S104
        raise ValueError("gateway must listen on every Pod address at the recipe port")
    return config


def render_gateway_installation(
    inputs: GatewayInstallationInput,
    decision: ExposureDecision,
    *,
    now: datetime,
    material_directory: Path,
) -> dict[str, Any]:
    """Return reviewable documents; rendering never touches a cluster and grants no authority."""
    del now
    if decision.exposure != inputs.exposure:
        raise ValueError("gateway exposure differs from the topology decision")
    validate_gateway_material(inputs, directory=material_directory)
    labels = {
        "app.kubernetes.io/name": "fdai-connector-gateway",
        "app.kubernetes.io/instance": inputs.name,
    }
    annotations = {"fdai.dev/execution-authority": "false"}

    def resource(
        api: str, kind: str, body: dict[str, Any], extra: dict[str, str] | None = None
    ) -> dict[str, Any]:
        return {
            "apiVersion": api,
            "kind": kind,
            "metadata": {
                "name": inputs.name,
                "namespace": inputs.namespace,
                "labels": labels.copy(),
                "annotations": {**annotations, **(extra or {})},
            },
            **body,
        }

    security = {
        "privileged": False,
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
            "limits": {"cpu": "1", "memory": "512Mi"},
        },
    }
    pod = {
        "hostNetwork": False,
        "hostPID": False,
        "hostIPC": False,
        "serviceAccountName": inputs.name,
        "automountServiceAccountToken": False,
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
                "name": "gateway",
                "command": ["python", "-m", "fdai.delivery.kubernetes_connector_cli"],
                "args": ["serve", "--config", "/private/material/config.json"],
                "env": [
                    {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"},
                    # Without the deployed venue the gateway accepts only a loopback database.
                    {"name": "FDAI_EXECUTION_VENUE", "value": "deployed"},
                    {
                        "name": "FDAI_STATE_STORE_DSN",
                        "valueFrom": {
                            "secretKeyRef": {
                                "name": inputs.database_secret,
                                "key": inputs.database_secret_key,
                            }
                        },
                    },
                ],
                "ports": [{"name": "mtls", "containerPort": _LISTEN_PORT, "protocol": "TCP"}],
                "readinessProbe": {"tcpSocket": {"port": "mtls"}, "periodSeconds": 10},
                "livenessProbe": {
                    "tcpSocket": {"port": "mtls"},
                    "periodSeconds": 20,
                    "failureThreshold": 3,
                },
                "volumeMounts": [
                    {"name": "private-material", "mountPath": "/private", "readOnly": True}
                ],
            }
        ],
        "volumes": [
            {
                "name": "material-input",
                "secret": {"secretName": inputs.material_secret, "defaultMode": 0o440},
            },
            {"name": "private-material", "emptyDir": {"medium": "Memory", "sizeLimit": "4Mi"}},
        ],
    }
    service_annotations = {
        "service.beta.kubernetes.io/azure-load-balancer-internal": "true",
        "service.beta.kubernetes.io/azure-load-balancer-health-probe-protocol": "tcp",
    }
    if inputs.exposure == "private_link_service":
        service_annotations |= {
            "service.beta.kubernetes.io/azure-pls-create": "true",
            "service.beta.kubernetes.io/azure-pls-name": inputs.name,
            "service.beta.kubernetes.io/azure-pls-ip-configuration-subnet": str(
                inputs.private_link_subnet
            ),
            "service.beta.kubernetes.io/azure-pls-visibility": "*",
            "service.beta.kubernetes.io/azure-pls-auto-approval": " ".join(
                inputs.private_link_subscriptions
            ),
        }

    def blocks(values: tuple[str, ...]) -> list[dict[str, Any]]:
        return [{"ipBlock": {"cidr": value}} for value in values]

    # A policy engine does not match Pod addresses with an address block, so an observer in the
    # same cluster is named by its namespace and labels, while remote networks use address blocks.
    ingress_from = blocks(inputs.ingress_cidrs) + [
        {
            "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": peer.namespace}},
            "podSelector": {"matchLabels": dict(sorted(peer.labels.items()))},
        }
        for peer in inputs.ingress_peers
    ]
    database_to = blocks(inputs.database_cidrs)
    if inputs.database_peer is not None:
        database_to.append(
            {
                "namespaceSelector": {
                    "matchLabels": {"kubernetes.io/metadata.name": inputs.database_peer.namespace}
                },
                "podSelector": {"matchLabels": dict(sorted(inputs.database_peer.labels.items()))},
            }
        )
    documents = [
        resource("v1", "ServiceAccount", {"automountServiceAccountToken": False}),
        resource(
            "apps/v1",
            "Deployment",
            {
                "spec": {
                    "replicas": inputs.replicas,
                    "revisionHistoryLimit": 3,
                    "selector": {"matchLabels": labels.copy()},
                    "template": {"metadata": {"labels": labels.copy()}, "spec": pod},
                }
            },
        ),
        resource(
            "v1",
            "Service",
            {
                "spec": {
                    "type": "LoadBalancer",
                    "externalTrafficPolicy": "Local",
                    "selector": labels.copy(),
                    "ports": [
                        {
                            "name": "mtls",
                            "port": _LISTEN_PORT,
                            "targetPort": "mtls",
                            "protocol": "TCP",
                        }
                    ],
                }
            },
            service_annotations,
        ),
        resource(
            "networking.k8s.io/v1",
            "NetworkPolicy",
            {
                "spec": {
                    "podSelector": {"matchLabels": labels.copy()},
                    "policyTypes": ["Ingress", "Egress"],
                    "ingress": [
                        {
                            "from": ingress_from,
                            "ports": [{"protocol": "TCP", "port": _LISTEN_PORT}],
                        }
                    ],
                    "egress": [
                        {
                            "to": database_to,
                            "ports": [{"protocol": "TCP", "port": inputs.database_port}],
                        },
                        {
                            "to": blocks(inputs.dns_cidrs)
                            + [
                                {
                                    "namespaceSelector": {
                                        "matchLabels": {
                                            "kubernetes.io/metadata.name": "kube-system"
                                        }
                                    },
                                    "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
                                }
                            ],
                            "ports": [
                                {"protocol": "UDP", "port": 53},
                                {"protocol": "TCP", "port": 53},
                            ],
                        },
                    ],
                }
            },
        ),
    ]
    return {
        "schema_version": "1.0.0",
        "exposure": decision.exposure,
        "exposure_reason": decision.reason,
        "requires_peering": decision.requires_peering,
        "topology_digest": decision.evidence_digest,
        "inputs_digest": canonical_digest(inputs.model_dump(mode="json")),
        "material_digest": inputs.material_digest,
        "manifest_digest": canonical_digest(documents),
        "documents": documents,
        "execution_authority": False,
        "approval_required": True,
    }
