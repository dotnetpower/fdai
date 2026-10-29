"""Bounded read of who owns an existing observer installation, never a change to it."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, Literal

import httpx
from fdai_service_contracts.cluster_connector import connector_time
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.observer_deployment import ObserverDeploymentFact

from fdai.delivery.kubernetes_connector_installation import ObserverInstallationInput
from fdai.delivery.kubernetes_connector_read_preflight import (
    KubernetesObserverReadPreflight,
    _unique,
)

_OWNER_LABEL = "app.kubernetes.io/managed-by"
_INSTALLER = "fdai-observer-install"


class KubernetesObserverOwnershipPreflight(KubernetesObserverReadPreflight):
    """Allow only when no foreign owner holds the observer namespace or workload name."""

    async def collect_ownership(self, inputs: ObserverInstallationInput) -> ObserverDeploymentFact:
        observed = connector_time(self._now())
        if inputs.target_ref != self._target:
            raise ValueError("Ownership preflight target differs from its binding")
        checks: list[dict[str, object]] = []
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
                headers.update({"Accept": "application/json", "Accept-Encoding": "identity"})
                await self._identity(client, headers)
                namespace = await self._optional(
                    client, f"/api/v1/namespaces/{inputs.namespace}", headers
                )
                job = (
                    None
                    if namespace is None
                    else await self._optional(
                        client,
                        f"/apis/batch/v1/namespaces/{inputs.namespace}/cronjobs/{inputs.name}",
                        headers,
                    )
                )
                await self._identity(client, headers)
                checks.append({"namespace": _owner(namespace), "cronjob": _owner(job)})
                foreign = (namespace is not None and _owner(namespace) != _INSTALLER) or (
                    job is not None and _owner(job) != _INSTALLER
                )
                state = "denied" if foreign else "allowed"
        except (httpx.HTTPError, TimeoutError, ValueError):
            checks.append({"state": "unknown", "reason": "ownership_observation_incomplete"})
        if not observed <= connector_time(self._now()) < observed + timedelta(minutes=5):
            raise ValueError("Ownership preflight observation window expired")
        return ObserverDeploymentFact(
            target_ref=self._target,
            name="ownership_known",
            state=state,
            source="kubernetes_api",
            evidence_digest=canonical_digest(
                {
                    "target_ref": self._target,
                    "namespace_uid": self._uid,
                    "namespace": inputs.namespace,
                    "name": inputs.name,
                    "checks": checks,
                }
            ),
            observed_at=observed,
            expires_at=observed + timedelta(minutes=5),
        )

    async def _optional(
        self, client: httpx.AsyncClient, path: str, headers: dict[str, str]
    ) -> dict[str, Any] | None:
        import json

        async with client.stream("GET", self._origin + path, headers=headers) as response:
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                raise ValueError("Kubernetes ownership request is unavailable")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 65536:
                    raise ValueError("Kubernetes ownership response exceeds its limit")
        value = json.loads(content, object_pairs_hook=_unique)
        if not isinstance(value, dict):
            raise ValueError("Kubernetes ownership response is invalid")
        return value


def _owner(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    labels = (value.get("metadata") or {}).get("labels") or {}
    return str(labels.get(_OWNER_LABEL, "unowned"))
