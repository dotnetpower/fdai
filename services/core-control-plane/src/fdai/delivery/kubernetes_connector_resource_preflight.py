"""Bounded GET-only observation of exact observer resource prerequisites."""

from __future__ import annotations

import asyncio
import re
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from fdai_service_contracts.cluster_connector import connector_time
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.observer_deployment import (
    ObserverDeploymentFact,
    ObserverDeploymentProposal,
)

from fdai.delivery.kubernetes_connector_installation import (
    ObserverInstallationInput,
    render_observer_installation,
)
from fdai.delivery.kubernetes_connector_read_preflight import KubernetesObserverReadPreflight
from fdai.delivery.kubernetes_connector_resource_checks import (
    mapping,
    snapshot_has_capacity,
    storage_is_bound,
    text,
)
from fdai.delivery.kubernetes_quantity import storage_bytes
from fdai.delivery.kubernetes_resource_accounting import pod_resource_requests

ResourceFactName = Literal["capacity", "persistent_storage"]
_NAME = re.compile(r"[a-z0-9](?:[-a-z0-9.]{0,251}[a-z0-9])?")


class KubernetesObserverResourcePreflight(KubernetesObserverReadPreflight):
    """Reuse verified TLS and exact cluster identity; never create a scheduling or volume effect."""

    async def collect_resources(
        self,
        inputs: ObserverInstallationInput,
        proposal: ObserverDeploymentProposal,
        *,
        material_directory: Path,
        name: ResourceFactName,
        claim_uid: str | None = None,
    ) -> ObserverDeploymentFact:
        observed = connector_time(self._now())
        if inputs.target_ref != self._target:
            raise ValueError("Resource preflight target differs from its binding")
        preview = render_observer_installation(
            inputs, proposal, now=observed, material_directory=material_directory
        )
        documents = {item["kind"]: item for item in preview["documents"]}
        template = documents["CronJob"]["spec"]["jobTemplate"]["spec"]["template"]
        expires = min(observed + timedelta(minutes=5), proposal.expires_at)
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
                if name == "capacity":
                    budget = [8]
                    nodes = await self._list(client, headers, "nodes", "Node", budget)
                    pods = await self._list(client, headers, "pods", "Pod", budget)
                    fits = snapshot_has_capacity(nodes, pods, pod_resource_requests(template))
                    checks.append(
                        {
                            "snapshot_digest": canonical_digest(
                                [_evidence(item) for item in [*nodes, *pods]]
                            )
                        }
                    )
                else:
                    fits = await self._storage(
                        client, headers, documents["PersistentVolumeClaim"], claim_uid, checks
                    )
                await self._identity(client, headers)
                state = "allowed" if fits else "denied"
        except (httpx.HTTPError, TimeoutError, ValueError, RecursionError):
            checks.append({"state": "unknown", "reason": "resource_observation_incomplete"})
        if not observed <= connector_time(self._now()) < expires:
            raise ValueError("Resource preflight observation window expired")
        return ObserverDeploymentFact(
            target_ref=self._target,
            name=name,
            state=state,
            source="kubernetes_api",
            evidence_digest=canonical_digest(
                {
                    "target_ref": self._target,
                    "namespace_uid": self._uid,
                    "name": name,
                    "inputs_digest": preview["inputs_digest"],
                    "manifest_digest": preview["manifest_digest"],
                    "claim_uid": claim_uid,
                    "checks": checks,
                }
            ),
            observed_at=observed,
            expires_at=expires,
        )

    async def _list(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        resource: str,
        kind: str,
        budget: list[int],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        version: str | None = None
        cursor = ""
        cursors: set[str] = set()
        uids: set[str] = set()
        identities: set[tuple[str, str]] = set()
        while budget[0] > 0:
            budget[0] -= 1
            query = urlencode({"limit": 256, **({"continue": cursor} if cursor else {})})
            page = await self._request(
                client, "GET", f"/api/v1/{resource}?{query}", headers, max_bytes=1048576
            )
            metadata = mapping(page.get("metadata"))
            current_version = text(metadata.get("resourceVersion"))
            if (
                page.get("apiVersion") != "v1"
                or page.get("kind") != kind + "List"
                or version not in (None, current_version)
            ):
                raise ValueError("Resource preflight list identity or version changed")
            version = current_version
            batch = page.get("items")
            if not isinstance(batch, list) or len(batch) > 256:
                raise ValueError("Resource preflight list is malformed")
            for item in batch:
                if not isinstance(item, dict):
                    raise ValueError("Resource preflight list item is invalid")
                identity = _identity(item, kind)
                uid = text(mapping(item.get("metadata")).get("uid"))
                if uid in uids or identity in identities:
                    raise ValueError("Resource preflight list contains duplicate objects")
                uids.add(uid)
                identities.add(identity)
                items.append(item)
            cursor = metadata.get("continue", "")
            remaining = metadata.get("remainingItemCount", 0)
            if (
                not isinstance(cursor, str)
                or len(cursor) > 4096
                or type(remaining) is not int
                or remaining < 0
            ):
                raise ValueError("Resource preflight pagination is invalid")
            if not cursor:
                if remaining:
                    raise ValueError("Resource preflight list is incomplete")
                return items
            if not batch or cursor in cursors:
                raise ValueError("Resource preflight pagination made no progress")
            cursors.add(cursor)
        raise ValueError("Resource preflight exceeded its page budget")

    async def _storage(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        template: dict[str, Any],
        claim_uid: str | None,
        checks: list[dict[str, object]],
    ) -> bool:
        text(claim_uid)
        namespace, name = template["metadata"]["namespace"], template["metadata"]["name"]
        path = f"/api/v1/namespaces/{namespace}/persistentvolumeclaims/{name}"
        claim = await self._request(client, "GET", path, headers)
        if (
            _identity(claim, "PersistentVolumeClaim") != (namespace, name)
            or mapping(claim.get("metadata")).get("uid") != claim_uid
        ):
            raise ValueError("Resource preflight claim target changed")
        volume_name = text(mapping(claim.get("spec")).get("volumeName"))
        if _NAME.fullmatch(volume_name) is None:
            raise ValueError("Resource preflight volume name is invalid")
        volume_path = f"/api/v1/persistentvolumes/{volume_name}"
        volume = await self._request(client, "GET", volume_path, headers)
        if _identity(volume, "PersistentVolume") != ("", volume_name):
            raise ValueError("Resource preflight volume target changed")
        fits = storage_is_bound(
            claim,
            volume,
            namespace=namespace,
            name=name,
            claim_uid=text(claim_uid),
            storage_class=template["spec"]["storageClassName"],
            required_bytes=storage_bytes(template["spec"]["resources"]["requests"]["storage"]),
        )
        for original, read_path in ((claim, path), (volume, volume_path)):
            current = await self._request(client, "GET", read_path, headers)
            if _evidence(current) != _evidence(original):
                raise ValueError("Resource preflight volume evidence changed during collection")
        checks.append({"binding_digest": canonical_digest([_evidence(claim), _evidence(volume)])})
        return fits


def _identity(value: dict[str, Any], kind: str) -> tuple[str, str]:
    metadata = mapping(value.get("metadata"))
    if value.get("apiVersion") != "v1" or value.get("kind") != kind:
        raise ValueError("Resource preflight object type is invalid")
    text(metadata.get("uid"))
    text(metadata.get("resourceVersion"))
    namespace = text(metadata.get("namespace")) if kind in ("Pod", "PersistentVolumeClaim") else ""
    return namespace, text(metadata.get("name"))


def _evidence(value: dict[str, Any]) -> dict[str, Any]:
    """Hash only identity and resource-accounting fields, never environment, CSI secrets or logs."""
    metadata = mapping(value.get("metadata"))
    spec, status = mapping(value.get("spec")), mapping(value.get("status"))
    view: dict[str, Any] = {
        "apiVersion": value.get("apiVersion"),
        "kind": value.get("kind"),
        "metadata": {
            key: metadata[key]
            for key in ("uid", "resourceVersion", "name", "namespace", "deletionTimestamp")
            if key in metadata
        },
        "spec": {
            key: spec[key]
            for key in (
                "unschedulable",
                "taints",
                "nodeName",
                "resources",
                "overhead",
                "volumeName",
                "storageClassName",
                "volumeMode",
                "accessModes",
                "claimRef",
                "capacity",
            )
            if key in spec
        },
        "status": {
            key: status[key]
            for key in (
                "phase",
                "allocatable",
                "capacity",
                "resize",
                "resources",
                "allocatedResources",
                "allocatedResourceStatuses",
            )
            if key in status
        },
    }
    if value.get("kind") == "Node":
        labels = mapping(metadata.get("labels", {}))
        view["metadata"]["labels"] = {
            key: labels.get(key) for key in ("kubernetes.io/os", "kubernetes.io/arch")
        }
    for parent, source, fields in (
        ("spec", spec, ("containers", "initContainers")),
        ("status", status, ("containerStatuses", "initContainerStatuses")),
    ):
        for field in fields:
            if field in source:
                view[parent][field] = [
                    {
                        key: item[key]
                        for key in (
                            "resources",
                            "restartPolicy",
                            "restartPolicyRules",
                            "resizePolicy",
                            "allocatedResources",
                            "allocatedResourcesStatus",
                        )
                        if key in item
                    }
                    for item in _rows(source[field])
                ]
    if "conditions" in status:
        view["status"]["conditions"] = [
            {key: item.get(key) for key in ("type", "status")}
            for item in _rows(status["conditions"])
        ]
    return view


def _rows(value: object) -> list[Any]:
    if not isinstance(value, list) or len(value) > 512:
        raise ValueError("Resource preflight summary requires a bounded array")
    return [mapping(item) for item in value]
