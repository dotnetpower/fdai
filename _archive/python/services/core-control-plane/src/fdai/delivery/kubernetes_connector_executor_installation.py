"""Render and guard the namespace-scoped cluster Executor workload for segmentation.

Observation and execution use separate identities, ServiceAccounts, and RBAC scopes. The cluster
Executor renders only namespace-scoped resources in one target namespace (`ServiceAccount`, `Role`,
`RoleBinding`, `Deployment`, and `NetworkPolicy`), never a `ClusterRole` or `ClusterRoleBinding`,
and never grants Secret or ConfigMap access. While segmentation remains in shadow mode, the
rendered Deployment stays scaled to zero replicas.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import ssl
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Self
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from fdai_service_contracts.cluster_connector import (
    ConnectorContract,
    ConnectorRegistration,
    Digest,
    connector_time,
)
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.observer_deployment import TargetRef
from pydantic import Field, field_validator, model_validator

from fdai.delivery.kubernetes_connector_installation import (
    GatewayPeer,
    KubernetesName,
    recipe_digest,
)
from fdai.delivery.kubernetes_connector_material import MATERIAL_FILES, material_digest
from fdai.delivery.kubernetes_connector_runtime import _unique_fields, private_file

_EXECUTOR_KINDS = frozenset(
    {"ServiceAccount", "Role", "RoleBinding", "Deployment", "NetworkPolicy"}
)
_EXECUTOR_ROLE_RULES = [
    {
        "apiGroups": ["networking.k8s.io"],
        "resources": ["networkpolicies"],
        "verbs": ["create", "delete", "get", "list", "patch"],
    },
    {
        "apiGroups": ["coordination.k8s.io"],
        "resources": ["leases"],
        "verbs": ["create", "get", "update"],
    },
]
_FORBIDDEN_RESOURCES = frozenset(
    {"secrets", "configmaps", "pods/exec", "pods/attach", "pods/portforward", "nodes/proxy", "*"}
)


class ExecutorInstallationInput(ConnectorContract):
    """Exact preview inputs for a namespace-scoped cluster Executor workload."""

    target_ref: TargetRef
    namespace: KubernetesName
    name: Annotated[
        str, Field(max_length=50, pattern=r"^fdai-executor-[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
    ]
    image: Annotated[
        str, Field(max_length=512, pattern=r"^[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}$")
    ]
    material_secret: KubernetesName
    material_digest: Digest
    gateway_port: Annotated[int, Field(strict=True, ge=1, le=65535)]
    api_port: Annotated[int, Field(strict=True, ge=1, le=65535)]
    gateway_cidrs: Annotated[tuple[str, ...], Field(max_length=8)] = ()
    gateway_peer: GatewayPeer | None = None
    api_cidrs: Annotated[tuple[str, ...], Field(min_length=1, max_length=8)]
    dns_cidrs: Annotated[tuple[str, ...], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def _gateway_destination(self) -> Self:
        if not self.gateway_cidrs and self.gateway_peer is None:
            raise ValueError("the executor gateway needs bounded networks or an in-cluster peer")
        return self

    @field_validator("namespace")
    @classmethod
    def _namespace(cls, value: str) -> str:
        if value == "default" or value.startswith("kube-") or value == "fdai-runtime":
            raise ValueError("executor workload requires a dedicated non-system target namespace")
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
                raise ValueError("executor egress requires bounded unicast networks")
            result.append(str(network))
        if len(set(result)) != len(result):
            raise ValueError("executor egress networks must be unique")
        return tuple(sorted(result))


def build_management_egress_rules(
    *,
    gateway_cidrs: tuple[str, ...],
    gateway_peer: GatewayPeer | None,
    gateway_port: int,
    api_cidrs: tuple[str, ...],
    api_port: int,
    dns_cidrs: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Build the explicit DNS, Kubernetes API, and gateway egress allowlist rules."""

    def blocks(networks: tuple[str, ...]) -> list[dict[str, Any]]:
        return [{"ipBlock": {"cidr": cidr}} for cidr in networks]

    gateway_to = blocks(gateway_cidrs)
    if gateway_peer is not None:
        gateway_to.append(
            {
                "namespaceSelector": {
                    "matchLabels": {"kubernetes.io/metadata.name": gateway_peer.namespace}
                },
                "podSelector": {"matchLabels": dict(sorted(gateway_peer.labels.items()))},
            }
        )
    dns_to = blocks(dns_cidrs) + [
        {
            "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
            "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
        }
    ]
    return [
        {"to": gateway_to, "ports": [{"protocol": "TCP", "port": gateway_port}]},
        {"to": blocks(api_cidrs), "ports": [{"protocol": "TCP", "port": api_port}]},
        {"to": dns_to, "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]},
    ]


def validate_executor_material(
    inputs: ExecutorInstallationInput, *, directory: Path, now: datetime
) -> None:
    """Verify mounted executor material, single-namespace enrollment, and TLS key binding."""
    contents = {name: private_file(directory / name) for name in MATERIAL_FILES}
    if material_digest(contents) != inputs.material_digest:
        raise ValueError("executor installation material digest differs from the preview")
    config = json.loads(contents["config.json"], object_pairs_hook=_unique_fields)
    if not isinstance(config, dict) or config.get("role") != "executor":
        raise ValueError("executor material requires role 'executor'")
    gateway = urlsplit(str(config.get("gateway_origin", "")))
    api = urlsplit(str(config.get("api_server", "")))
    if (
        gateway.scheme != "https"
        or api.scheme != "https"
        or api.hostname != "kubernetes.default.svc"
        or (gateway.port or 443) != inputs.gateway_port
        or (api.port or 443) != inputs.api_port
    ):
        raise ValueError("executor endpoints or ports do not match the network policy")
    entries = json.loads(contents["registrations.json"], object_pairs_hook=_unique_fields)
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError("executor installation requires exactly one enrollment")
    registration = ConnectorRegistration.model_validate(entries[0])
    if (
        registration.role != "executor"
        or registration.capabilities != ("governed.execute",)
        or registration.scope.cluster_ref != inputs.target_ref
        or registration.namespaces != (inputs.namespace,)
    ):
        raise ValueError("executor enrollment must bind one target and one namespace")
    principal = str(config.get("executor_principal_ref", ""))
    registration.admit(
        principal_ref=principal,
        scope=registration.scope,
        capability="governed.execute",
        now=connector_time(now),
    )
    certificate = x509.load_pem_x509_certificate(contents["client.pem"])
    fingerprint = "sha256:" + hashlib.sha256(certificate.public_bytes(Encoding.DER)).hexdigest()
    if fingerprint != principal:
        raise ValueError("executor certificate does not match its registered principal")
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(directory / "ca.pem"))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_cert_chain(str(directory / "client.pem"), str(directory / "client.key"))
    if (
        material_digest({name: private_file(directory / name) for name in MATERIAL_FILES})
        != inputs.material_digest
    ):
        raise ValueError("executor installation material changed during validation")


def render_executor_installation(
    inputs: ExecutorInstallationInput,
    *,
    now: datetime,
    material_directory: Path,
) -> dict[str, Any]:
    """Render a namespace-scoped, shadow-suspended Executor recipe with no Secret access."""
    inputs = ExecutorInstallationInput.model_validate_json(inputs.model_dump_json())
    validate_executor_material(inputs, directory=material_directory, now=now)
    labels = {
        "app.kubernetes.io/name": "fdai-cluster-executor",
        "app.kubernetes.io/instance": inputs.name,
    }
    annotations = {"fdai.dev/execution-authority": "false", "fdai.dev/mode": "shadow"}

    def resource(api: str, kind: str, body: dict[str, Any]) -> dict[str, Any]:
        return {
            "apiVersion": api,
            "kind": kind,
            "metadata": {
                "name": inputs.name,
                "namespace": inputs.namespace,
                "labels": labels.copy(),
                "annotations": annotations.copy(),
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
            "limits": {"cpu": "500m", "memory": "512Mi"},
        },
    }
    pod = {
        "hostNetwork": False,
        "hostPID": False,
        "hostIPC": False,
        "serviceAccountName": inputs.name,
        "automountServiceAccountToken": False,
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
                "name": "executor",
                "command": ["python", "-m", "fdai.delivery.kubernetes_connector_cli"],
                "args": ["observe-once", "--config", "/private/material/config.json"],
                "env": [{"name": "PYTHONDONTWRITEBYTECODE", "value": "1"}],
                "volumeMounts": [
                    {"name": "private-material", "mountPath": "/private", "readOnly": True},
                    {"name": "api-identity", "mountPath": "/api-identity", "readOnly": True},
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
        ],
    }
    egress = build_management_egress_rules(
        gateway_cidrs=inputs.gateway_cidrs,
        gateway_peer=inputs.gateway_peer,
        gateway_port=inputs.gateway_port,
        api_cidrs=inputs.api_cidrs,
        api_port=inputs.api_port,
        dns_cidrs=inputs.dns_cidrs,
    )
    documents = [
        resource("v1", "ServiceAccount", {"automountServiceAccountToken": False}),
        resource(
            "rbac.authorization.k8s.io/v1",
            "Role",
            {"rules": [dict(rule) for rule in _EXECUTOR_ROLE_RULES]},
        ),
        resource(
            "rbac.authorization.k8s.io/v1",
            "RoleBinding",
            {
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "Role",
                    "name": inputs.name,
                },
                "subjects": [
                    {"kind": "ServiceAccount", "name": inputs.name, "namespace": inputs.namespace}
                ],
            },
        ),
        resource(
            "apps/v1",
            "Deployment",
            {
                "spec": {
                    "replicas": 0,
                    "selector": {"matchLabels": labels.copy()},
                    "template": {"metadata": {"labels": labels.copy()}, "spec": pod},
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
        "namespace": inputs.namespace,
        "mode": "shadow",
        "inputs_digest": canonical_digest(inputs.model_dump(mode="json")),
        "material_digest": inputs.material_digest,
        "manifest_digest": canonical_digest(documents),
        "recipe_digest": recipe_digest(documents),
        "documents": documents,
        "execution_authority": False,
        "approval_required": True,
    }


def verify_executor_documents(
    rendered: Mapping[str, Any], inputs: ExecutorInstallationInput
) -> list[dict[str, Any]]:
    """Reject cluster-wide RBAC, Secret reads, active shadow replicas, or missing egress guards."""
    documents = rendered.get("documents")
    if (
        not isinstance(documents, list)
        or canonical_digest(documents) != rendered.get("manifest_digest")
        or recipe_digest(documents) != rendered.get("recipe_digest")
        or rendered.get("execution_authority") is not False
        or rendered.get("mode") != "shadow"
    ):
        raise ValueError("executor manifest failed integrity or shadow-mode checks")
    kinds = [str(item.get("kind")) for item in documents]
    if sorted(kinds) != sorted(_EXECUTOR_KINDS):
        raise ValueError("executor manifest must contain only the namespace-scoped recipe kinds")
    by_kind = {str(item["kind"]): item for item in documents}
    for item in documents:
        metadata = item.get("metadata", {})
        if (
            metadata.get("name") != inputs.name
            or metadata.get("namespace") != inputs.namespace
            or metadata.get("annotations", {}).get("fdai.dev/execution-authority") != "false"
        ):
            raise ValueError("executor resource identity must stay in the single target namespace")
    rules = by_kind["Role"].get("rules", [])
    for rule in rules:
        resources = set(rule.get("resources", []))
        if resources & _FORBIDDEN_RESOURCES or "*" in set(rule.get("verbs", [])):
            raise ValueError("executor Role must never read or mutate Secrets or wildcards")
    if rules != _EXECUTOR_ROLE_RULES:
        raise ValueError("executor Role rules differ from the namespace-scoped NetworkPolicy role")
    binding = by_kind["RoleBinding"]
    if binding.get("roleRef", {}).get("kind") != "Role":
        raise ValueError("executor RoleBinding must reference a namespace Role, not a ClusterRole")
    deployment = by_kind["Deployment"].get("spec", {})
    if deployment.get("replicas") != 0:
        raise ValueError("shadow-mode executor Deployment must stay at zero replicas")
    expected_egress = build_management_egress_rules(
        gateway_cidrs=inputs.gateway_cidrs,
        gateway_peer=inputs.gateway_peer,
        gateway_port=inputs.gateway_port,
        api_cidrs=inputs.api_cidrs,
        api_port=inputs.api_port,
        dns_cidrs=inputs.dns_cidrs,
    )
    policy_spec = by_kind["NetworkPolicy"].get("spec", {})
    if policy_spec.get("ingress") != [] or policy_spec.get("egress") != expected_egress:
        raise ValueError("executor NetworkPolicy must deny ingress and preserve management egress")
    return documents
