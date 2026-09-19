"""Bounded Kubernetes authorization observation for the exact snapshot reader identity."""

from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import httpx
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.observer_deployment import (
    ObserverDeploymentFact,
    ObserverDeploymentProposal,
)

from fdai.delivery.kubernetes_api_inventory import _RESOURCE_PATHS, KubernetesApiAuth
from fdai.delivery.kubernetes_connector_transport import ConnectorTransportConfig

if TYPE_CHECKING:
    from fdai.delivery.kubernetes_connector_installation import ObserverInstallationInput


def snapshot_read_attributes() -> tuple[dict[str, str], ...]:
    """Use the collector's actual resource inventory; absence of a resource is not authorization."""
    return tuple(
        {
            "group": api_version.split("/", 1)[0] if "/" in api_version else "",
            "resource": path.rsplit("/", 1)[1],
            "verb": "list",
        }
        for path, _, _, api_version, _ in _RESOURCE_PATHS
    )


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values: dict[str, object] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("Kubernetes preflight returned duplicate fields")
        values[key] = value
    return values


class KubernetesObserverReadPreflight:
    """Observe fixed authorization or admission checks without installing resources.

    The deployment binding supplies a previously verified kube-system namespace UID. An exact
    UID read precedes and follows all non-persistent SelfSubjectAccessReview requests. TLS,
    response size, total deadline and the fixed request list are not caller-selectable bypasses.
    The separate installation method requires a deployment-preflight identity and uses only
    dry-run creates of the rendered recipe and its Pod, never the observer's read credential.
    """

    def __init__(
        self,
        *,
        origin: str,
        target_ref: str,
        namespace_uid: str,
        auth: KubernetesApiAuth,
        tls: ssl.SSLContext,
        now: Callable[[], datetime],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        ConnectorTransportConfig(origin, "kubernetes-preflight")
        if tls.verify_mode != ssl.CERT_REQUIRED or not tls.check_hostname:
            raise ValueError("Kubernetes preflight requires verified TLS")
        if not namespace_uid or len(namespace_uid) > 128 or not namespace_uid.isascii():
            raise ValueError("Kubernetes preflight requires an exact namespace UID")
        self._origin, self._target, self._uid = origin.rstrip("/"), target_ref, namespace_uid
        self._auth, self._tls, self._now, self._transport = auth, tls, now, transport

    async def collect(self) -> ObserverDeploymentFact:
        from fdai_service_contracts.cluster_connector import connector_time

        observed = connector_time(self._now())
        results: list[dict[str, object]] = []
        state: Literal["allowed", "denied", "unknown"] = "unknown"
        try:
            async with (
                asyncio.timeout(30),
                httpx.AsyncClient(
                    verify=self._tls,
                    transport=self._transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=3,
                ) as client,
            ):
                headers = dict(await self._auth.headers())
                headers["Accept-Encoding"] = "identity"
                await self._identity(client, headers)
                for attributes in snapshot_read_attributes():
                    value = await self._request(
                        client,
                        "POST",
                        "/apis/authorization.k8s.io/v1/selfsubjectaccessreviews",
                        headers,
                        {
                            "apiVersion": "authorization.k8s.io/v1",
                            "kind": "SelfSubjectAccessReview",
                            "spec": {"resourceAttributes": attributes},
                        },
                    )
                    if (
                        value.get("apiVersion") != "authorization.k8s.io/v1"
                        or value.get("kind") != "SelfSubjectAccessReview"
                        or value.get("spec") != {"resourceAttributes": attributes}
                    ):
                        raise ValueError("Kubernetes preflight response binding is invalid")
                    status = value.get("status")
                    if (
                        not isinstance(status, dict)
                        or status.get("evaluationError")
                        or type(status.get("allowed")) is not bool
                        or type(status.get("denied", False)) is not bool
                    ):
                        raise ValueError("Kubernetes preflight authorization is unknown")
                    if status["allowed"] and status.get("denied", False):
                        raise ValueError("Kubernetes preflight authorization conflicts")
                    result = "allowed" if status["allowed"] else "denied"
                    results.append({"attributes": attributes, "state": result})
                await self._identity(client, headers)
                state = (
                    "denied" if any(item["state"] == "denied" for item in results) else "allowed"
                )
        except (httpx.HTTPError, TimeoutError, ValueError):
            results.append({"state": "unknown", "reason": "authorization_observation_incomplete"})
        if not observed <= connector_time(self._now()) < observed + timedelta(minutes=5):
            raise ValueError("Kubernetes preflight observation window expired")
        return ObserverDeploymentFact(
            target_ref=self._target,
            name="kubernetes_read",
            state=state,
            source="kubernetes_api",
            evidence_digest=canonical_digest(
                {"target_ref": self._target, "namespace_uid": self._uid, "checks": results}
            ),
            observed_at=observed,
            expires_at=observed + timedelta(minutes=5),
        )

    async def collect_installation(
        self,
        inputs: ObserverInstallationInput,
        proposal: ObserverDeploymentProposal,
        *,
        material_directory: Path,
    ) -> ObserverDeploymentFact:
        """Probe exact recipe and Pod admission; scheduling, storage and effects remain unknown."""
        from fdai_service_contracts.cluster_connector import connector_time

        from fdai.delivery.kubernetes_connector_installation import render_observer_installation

        observed = connector_time(self._now())
        if inputs.target_ref != self._target:
            raise ValueError("observer admission target differs from its authenticated binding")
        preview = render_observer_installation(
            inputs, proposal, now=observed, material_directory=material_directory
        )
        documents = preview["documents"]
        template = next(item for item in documents if item["kind"] == "CronJob")["spec"][
            "jobTemplate"
        ]["spec"]["template"]
        pod = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                **template["metadata"],
                "name": inputs.name,
                "namespace": inputs.namespace,
            },
            "spec": template["spec"],
        }
        paths = {
            "ServiceAccount": f"/api/v1/namespaces/{inputs.namespace}/serviceaccounts",
            "ClusterRole": "/apis/rbac.authorization.k8s.io/v1/clusterroles",
            "ClusterRoleBinding": "/apis/rbac.authorization.k8s.io/v1/clusterrolebindings",
            "PersistentVolumeClaim": (
                f"/api/v1/namespaces/{inputs.namespace}/persistentvolumeclaims"
            ),
            "CronJob": f"/apis/batch/v1/namespaces/{inputs.namespace}/cronjobs",
            "NetworkPolicy": (
                f"/apis/networking.k8s.io/v1/namespaces/{inputs.namespace}/networkpolicies"
            ),
            "Pod": f"/api/v1/namespaces/{inputs.namespace}/pods",
        }
        expires = min(observed + timedelta(minutes=5), proposal.expires_at)
        results: list[dict[str, object]] = []
        state: Literal["allowed", "unknown"] = "unknown"
        try:
            async with (
                asyncio.timeout(30),
                httpx.AsyncClient(
                    verify=self._tls,
                    transport=self._transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=3,
                ) as client,
            ):
                headers = dict(await self._auth.headers())
                headers.update({"Accept": "application/json", "Accept-Encoding": "identity"})
                await self._identity(client, headers)
                for document in [*documents, pod]:
                    if not observed <= connector_time(self._now()) < expires:
                        raise ValueError("observer admission evidence expired")
                    path = (
                        paths[document["kind"]]
                        + "?dryRun=All&fieldValidation=Strict&fieldManager=fdai-observer-preflight"
                    )
                    response = await self._request(client, "POST", path, headers, document)
                    if not _preserves_fields(document, response):
                        raise ValueError("observer admission changed the inspected recipe")
                    results.append(
                        {"kind": document["kind"], "response_digest": canonical_digest(response)}
                    )
                await self._identity(client, headers)
                state = "allowed"
        except (httpx.HTTPError, TimeoutError, ValueError):
            results.append({"state": "unknown", "reason": "admission_observation_incomplete"})
        if not observed <= connector_time(self._now()) < expires:
            raise ValueError("observer admission observation window expired")
        return ObserverDeploymentFact(
            target_ref=self._target,
            name="admission",
            state=state,
            source="kubernetes_api",
            evidence_digest=canonical_digest(
                {
                    "target_ref": self._target,
                    "namespace_uid": self._uid,
                    "inputs_digest": preview["inputs_digest"],
                    "manifest_digest": preview["manifest_digest"],
                    "checks": results,
                }
            ),
            observed_at=observed,
            expires_at=expires,
        )

    async def _identity(self, client: httpx.AsyncClient, headers: dict[str, str]) -> None:
        value = await self._request(client, "GET", "/api/v1/namespaces/kube-system", headers)
        metadata = value.get("metadata")
        if (
            value.get("apiVersion") != "v1"
            or value.get("kind") != "Namespace"
            or not isinstance(metadata, dict)
            or metadata.get("name") != "kube-system"
            or metadata.get("uid") != self._uid
        ):
            raise ValueError("Kubernetes preflight cluster identity mismatch")

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        headers: dict[str, str],
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        async with client.stream(
            method, self._origin + path, headers=headers, json=payload
        ) as response:
            if (
                response.status_code not in {200, 201}
                or response.headers.get("content-encoding", "identity") != "identity"
            ):
                raise ValueError("Kubernetes preflight request is unavailable")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 16384:
                    raise ValueError("Kubernetes preflight response exceeds its limit")
        value = json.loads(content, object_pairs_hook=_unique)
        if not isinstance(value, dict):
            raise ValueError("Kubernetes preflight response is invalid")
        return value


def _preserves_fields(expected: object, actual: object) -> bool:
    """Allow server defaults but never changes to specified fields or added list entries."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            (key not in actual and value is False) or _preserves_fields(value, actual.get(key))
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(expected) == len(actual)
            and all(
                _preserves_fields(before, after)
                for before, after in zip(expected, actual, strict=True)
            )
        )
    return type(expected) is type(actual) and expected == actual
