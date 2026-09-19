"""Bounded Kubernetes authorization observation for the exact snapshot reader identity."""

from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal

import httpx
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.observer_deployment import ObserverDeploymentFact

from fdai.delivery.kubernetes_api_inventory import _RESOURCE_PATHS, KubernetesApiAuth
from fdai.delivery.kubernetes_connector_transport import ConnectorTransportConfig


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
    """Observe the caller's list permissions, not installation, admission or egress permission.

    The deployment binding supplies a previously verified kube-system namespace UID. An exact
    UID read precedes and follows all non-persistent SelfSubjectAccessReview requests. TLS,
    response size, total deadline and the fixed request list are not caller-selectable bypasses.
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
