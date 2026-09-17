"""Discover subscription AKS observation bindings without retaining credentials."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse

import httpx
import yaml

from fdai.delivery.kubernetes_cluster_binding import KubernetesClusterBinding
from fdai.shared.providers.workload_identity import WorkloadIdentity

_AKS_API_VERSION = "2026-05-01"
_MAX_KUBECONFIG_BYTES = 256 * 1024
_SUBSCRIPTION_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_STATIC_CREDENTIAL_KEYS = frozenset(
    {
        "client-certificate",
        "client-certificate-data",
        "client-key",
        "client-key-data",
        "password",
        "token",
        "tokenFile",
        "username",
    }
)


class AksSubscriptionDiscoveryError(RuntimeError):
    """Raised when subscription discovery cannot prove a bounded result."""


@dataclass(frozen=True, slots=True)
class AksUnavailableScope:
    """Record one discovered cluster that cannot supply a safe read binding."""

    scope_digest: str
    reason: str


@dataclass(frozen=True, slots=True)
class AksSubscriptionDiscoveryResult:
    """Return usable in-memory bindings and explicit unavailable cluster scopes."""

    bindings: tuple[KubernetesClusterBinding, ...]
    unavailable_scopes: tuple[AksUnavailableScope, ...]


@dataclass(frozen=True, slots=True)
class AksSubscriptionDiscoveryConfig:
    """Bound Azure management reads used to discover AKS clusters."""

    management_endpoint: str
    management_audience: str
    api_version: str = _AKS_API_VERSION
    max_pages: int = 16
    max_clusters: int = 128
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.management_endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("AKS discovery management endpoint MUST be an HTTPS origin")
        if not self.management_audience.strip() or not self.api_version.strip():
            raise ValueError("AKS discovery audience and API version MUST be non-empty")
        if self.max_pages < 1 or self.max_clusters < 1 or self.timeout_seconds <= 0:
            raise ValueError("AKS discovery limits MUST be positive")


class AzureAksSubscriptionBindingDiscovery:
    """Build ephemeral workload-identity bindings for every AKS in one subscription."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AksSubscriptionDiscoveryConfig,
    ) -> None:
        self._identity = identity
        self._http = http_client
        self._config = config
        self._management_host = urlparse(config.management_endpoint).netloc.casefold()

    async def discover(self, subscription_id: str) -> AksSubscriptionDiscoveryResult:
        """Discover current clusters and discard credential responses after minimization."""

        if _SUBSCRIPTION_PATTERN.fullmatch(subscription_id) is None:
            raise ValueError("AKS discovery requires one canonical subscription id")
        credential = await self._identity.get_token(self._config.management_audience)
        if credential.audience != self._config.management_audience or not credential.token.strip():
            raise AksSubscriptionDiscoveryError("AKS discovery management token is invalid")
        headers = {
            "Authorization": f"Bearer {credential.token.strip()}",
            "Accept": "application/json",
        }
        clusters = await self._list_clusters(subscription_id, headers=headers)
        bindings: list[KubernetesClusterBinding] = []
        unavailable: list[AksUnavailableScope] = []
        for cluster in sorted(clusters, key=lambda item: str(item["id"]).casefold()):
            cluster_ref = str(cluster["id"])
            scope_digest = _scope_digest(cluster_ref)
            if not _supports_azure_rbac(cluster):
                unavailable.append(
                    AksUnavailableScope(
                        scope_digest=scope_digest,
                        reason="kubernetes_azure_rbac_unavailable",
                    )
                )
                continue
            try:
                bindings.append(
                    await self._binding_from_exec_profile(
                        cluster_ref,
                        headers=headers,
                    )
                )
            except AksSubscriptionDiscoveryError:
                unavailable.append(
                    AksUnavailableScope(
                        scope_digest=scope_digest,
                        reason="kubernetes_discovered_binding_unavailable",
                    )
                )
        return AksSubscriptionDiscoveryResult(
            bindings=tuple(bindings),
            unavailable_scopes=tuple(unavailable),
        )

    async def _list_clusters(
        self,
        subscription_id: str,
        *,
        headers: Mapping[str, str],
    ) -> tuple[Mapping[str, Any], ...]:
        current = (
            f"{self._config.management_endpoint.rstrip('/')}/subscriptions/"
            f"{quote(subscription_id, safe='')}/providers/"
            "Microsoft.ContainerService/managedClusters"
            f"?api-version={quote(self._config.api_version, safe='')}"
        )
        clusters: list[Mapping[str, Any]] = []
        for _page in range(self._config.max_pages):
            self._validate_management_url(current)
            response = await self._request("GET", current, headers=headers)
            payload = _json_mapping(response)
            values = payload.get("value")
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                raise AksSubscriptionDiscoveryError("AKS discovery response has no value array")
            for value in values:
                if not isinstance(value, Mapping):
                    raise AksSubscriptionDiscoveryError("AKS discovery returned a malformed row")
                cluster_ref = value.get("id")
                if not isinstance(cluster_ref, str) or not _is_cluster_ref(
                    cluster_ref, subscription_id
                ):
                    raise AksSubscriptionDiscoveryError(
                        "AKS discovery returned an out-of-scope cluster"
                    )
                clusters.append(value)
                if len(clusters) > self._config.max_clusters:
                    raise AksSubscriptionDiscoveryError("AKS discovery cluster cap exceeded")
            next_link = payload.get("nextLink")
            if next_link is None:
                return tuple(clusters)
            if not isinstance(next_link, str) or not next_link:
                raise AksSubscriptionDiscoveryError("AKS discovery next link is malformed")
            current = next_link
        raise AksSubscriptionDiscoveryError("AKS discovery pagination cap exceeded")

    async def _binding_from_exec_profile(
        self,
        cluster_ref: str,
        *,
        headers: Mapping[str, str],
    ) -> KubernetesClusterBinding:
        url = (
            f"{self._config.management_endpoint.rstrip('/')}"
            f"{quote(cluster_ref, safe='/')}/listClusterUserCredential"
            f"?api-version={quote(self._config.api_version, safe='')}&format=exec"
        )
        response = await self._request("POST", url, headers=headers)
        payload = _json_mapping(response)
        kubeconfigs = payload.get("kubeconfigs")
        if (
            not isinstance(kubeconfigs, Sequence)
            or isinstance(kubeconfigs, (str, bytes))
            or len(kubeconfigs) != 1
            or not isinstance(kubeconfigs[0], Mapping)
        ):
            raise AksSubscriptionDiscoveryError("AKS credential response is malformed")
        encoded = kubeconfigs[0].get("value")
        if not isinstance(encoded, str) or len(encoded) > _MAX_KUBECONFIG_BYTES * 2:
            raise AksSubscriptionDiscoveryError("AKS kubeconfig value is malformed")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise AksSubscriptionDiscoveryError("AKS kubeconfig is not valid base64") from exc
        if len(decoded) > _MAX_KUBECONFIG_BYTES:
            raise AksSubscriptionDiscoveryError("AKS kubeconfig exceeds the byte limit")
        try:
            kubeconfig = yaml.safe_load(decoded)
        except yaml.YAMLError as exc:
            raise AksSubscriptionDiscoveryError("AKS kubeconfig is not valid YAML") from exc
        return _minimize_exec_kubeconfig(kubeconfig, cluster_ref=cluster_ref)

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> httpx.Response:
        self._validate_management_url(url)
        try:
            response = await self._http.request(
                method,
                url,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise AksSubscriptionDiscoveryError("AKS management request failed") from exc
        if response.status_code >= 400:
            raise AksSubscriptionDiscoveryError(
                f"AKS management request returned HTTP {response.status_code}"
            )
        return response

    def _validate_management_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc.casefold() != self._management_host:
            raise AksSubscriptionDiscoveryError("AKS management URL changed origin")


def _minimize_exec_kubeconfig(
    value: object,
    *,
    cluster_ref: str,
) -> KubernetesClusterBinding:
    if not isinstance(value, Mapping):
        raise AksSubscriptionDiscoveryError("AKS kubeconfig root is malformed")
    current_context = value.get("current-context")
    if not isinstance(current_context, str) or not current_context:
        raise AksSubscriptionDiscoveryError("AKS kubeconfig current context is missing")
    context = _named_entry(value.get("contexts"), current_context, "context")
    cluster_name = context.get("cluster")
    user_name = context.get("user")
    if not isinstance(cluster_name, str) or not isinstance(user_name, str):
        raise AksSubscriptionDiscoveryError("AKS kubeconfig context is incomplete")
    cluster = _named_entry(value.get("clusters"), cluster_name, "cluster")
    user = _named_entry(value.get("users"), user_name, "user")
    if _STATIC_CREDENTIAL_KEYS & set(user):
        raise AksSubscriptionDiscoveryError("AKS kubeconfig contains static credentials")
    exec_profile = user.get("exec")
    if not isinstance(exec_profile, Mapping) or exec_profile.get("env"):
        raise AksSubscriptionDiscoveryError("AKS kubeconfig exec profile is unavailable")
    if set(exec_profile) - {
        "apiVersion",
        "args",
        "command",
        "installHint",
        "interactiveMode",
        "provideClusterInfo",
    }:
        raise AksSubscriptionDiscoveryError("AKS kubeconfig exec profile has unsupported fields")
    command = exec_profile.get("command")
    if not isinstance(command, str) or command.rsplit("/", maxsplit=1)[-1] != "kubelogin":
        raise AksSubscriptionDiscoveryError("AKS kubeconfig requires an unsupported exec plugin")
    audience = _server_id(exec_profile.get("args"))
    api_server = cluster.get("server")
    encoded_ca = cluster.get("certificate-authority-data")
    if (
        not isinstance(api_server, str)
        or not isinstance(encoded_ca, str)
        or cluster.get("certificate-authority") is not None
        or cluster.get("insecure-skip-tls-verify") is True
    ):
        raise AksSubscriptionDiscoveryError("AKS kubeconfig cluster profile is incomplete")
    try:
        ca_pem = base64.b64decode(encoded_ca, validate=True).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise AksSubscriptionDiscoveryError("AKS kubeconfig CA is invalid") from exc
    if "-----BEGIN CERTIFICATE-----" not in ca_pem or len(ca_pem) > 65_536:
        raise AksSubscriptionDiscoveryError("AKS kubeconfig CA is not a bounded certificate")
    return KubernetesClusterBinding(
        api_server=api_server,
        cluster_ref=cluster_ref,
        auth_mode="workload-identity",
        ca_pem=ca_pem,
        audience=audience,
    )


def _named_entry(value: object, name: str, body_key: str) -> Mapping[str, Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise AksSubscriptionDiscoveryError("AKS kubeconfig named list is malformed")
    matches = [
        item.get(body_key)
        for item in value
        if isinstance(item, Mapping) and item.get("name") == name
    ]
    if len(matches) != 1 or not isinstance(matches[0], Mapping):
        raise AksSubscriptionDiscoveryError("AKS kubeconfig named entry is ambiguous")
    return matches[0]


def _server_id(value: object) -> str:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise AksSubscriptionDiscoveryError("AKS kubeconfig exec arguments are malformed")
    args = tuple(value)
    if not all(isinstance(item, str) and item.isascii() and len(item) <= 512 for item in args):
        raise AksSubscriptionDiscoveryError("AKS kubeconfig exec arguments are invalid")
    candidates: list[str] = []
    for index, argument in enumerate(args):
        if argument == "--server-id" and index + 1 < len(args):
            candidates.append(args[index + 1])
        elif argument.startswith("--server-id="):
            candidates.append(argument.partition("=")[2])
    if len(candidates) != 1 or not candidates[0]:
        raise AksSubscriptionDiscoveryError("AKS kubeconfig server audience is unavailable")
    return candidates[0]


def _supports_azure_rbac(cluster: Mapping[str, Any]) -> bool:
    properties = cluster.get("properties")
    if not isinstance(properties, Mapping):
        return False
    aad_profile = properties.get("aadProfile")
    return bool(
        properties.get("provisioningState") == "Succeeded"
        and properties.get("enableRBAC") is True
        and isinstance(aad_profile, Mapping)
        and aad_profile.get("managed") is True
        and aad_profile.get("enableAzureRBAC") is True
    )


def _json_mapping(response: httpx.Response) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise AksSubscriptionDiscoveryError("AKS management response is not JSON") from exc
    if not isinstance(payload, Mapping):
        raise AksSubscriptionDiscoveryError("AKS management response is malformed")
    return payload


def _is_cluster_ref(cluster_ref: str, subscription_id: str) -> bool:
    return bool(
        re.fullmatch(
            rf"/subscriptions/{re.escape(subscription_id)}/resourceGroups/[^/]+/providers/"
            r"Microsoft\.ContainerService/managedClusters/[^/]+",
            cluster_ref,
            flags=re.IGNORECASE,
        )
    )


def _scope_digest(cluster_ref: str) -> str:
    digest = hashlib.sha256(cluster_ref.strip().casefold().encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def subscription_scope_digest(subscription_id: str) -> str:
    """Return a customer-safe source identity for one subscription discovery failure."""

    if _SUBSCRIPTION_PATTERN.fullmatch(subscription_id) is None:
        raise ValueError("AKS discovery requires one canonical subscription id")
    return _scope_digest(f"/subscriptions/{subscription_id}")


__all__ = [
    "AksSubscriptionDiscoveryConfig",
    "AksSubscriptionDiscoveryError",
    "AksSubscriptionDiscoveryResult",
    "AksUnavailableScope",
    "AzureAksSubscriptionBindingDiscovery",
    "subscription_scope_digest",
]
