"""Configuration, identity, and value contracts for the development gateway."""

from __future__ import annotations

import ipaddress
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlparse

import httpx

if TYPE_CHECKING:
    from delivery.dev_operations_gateway.idempotency import AzureBlobIdempotencyConfig
elif __package__:
    from .idempotency import AzureBlobIdempotencyConfig
else:
    from idempotency import AzureBlobIdempotencyConfig

_ARM_AUDIENCE = "https://management.azure.com"

_NETWORK_API_VERSION = "2025-05-01"

_COMPUTE_API_VERSION = "2025-04-01"

_TAGS_API_VERSION = "2021-04-01"

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.()-]{0,127}$")

_TAG_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

_TAG_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@ -]{0,255}$")

_LOGICAL_RESOURCE_REF = re.compile(
    r"^scope-[a-f0-9]{16,64}/resource-group/"
    r"(?P<resource_group>[A-Za-z0-9][A-Za-z0-9_.()-]{0,127})"
    r"(?P<provider_path>/providers(?:/[A-Za-z0-9][A-Za-z0-9_.()-]{0,127}){3,15})?$",
    re.IGNORECASE,
)

_MUTATION_OPERATIONS = frozenset(
    {
        "azure.network.nsg.rule.upsert",
        "azure.network.nsg.rule.delete",
        "azure.compute.vm.start",
        "azure.compute.vm.deallocate",
        "azure.compute.vmss.scale",
        "azure.resource.tags.merge",
    }
)

_EXECUTOR_VERTICAL_ORDER = ("change", "resilience", "finops")

_OPERATION_VERTICALS = {
    "azure.network.nsg.rule.upsert": "change",
    "azure.network.nsg.rule.delete": "change",
    "azure.compute.vm.start": "resilience",
    "azure.compute.vm.deallocate": "finops",
    "azure.compute.vmss.scale": "finops",
    "azure.resource.tags.merge": "change",
}


class GatewayError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class GatewayPrincipal:
    object_id: str
    groups: frozenset[str]
    roles: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class PrivateProbe:
    url: str
    audience: str
    result_contract: str = "http_status"

    def __post_init__(self) -> None:
        parsed = urlparse(self.url)
        hostname = parsed.hostname or ""
        try:
            ipaddress.ip_address(hostname)
            literal_ip = True
        except ValueError:
            literal_ip = False
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or hostname.casefold() == "localhost"
            or literal_ip
            or len(self.url) > 2_048
            or any(character in self.url for character in ("\x00", "\r", "\n"))
        ):
            raise ValueError("private probe URL MUST be an absolute HTTPS URL")
        if (
            not self.audience.strip()
            or len(self.audience) > 256
            or any(character in self.audience for character in ("\x00", "\r", "\n"))
        ):
            raise ValueError("private probe audience MUST be bounded")
        if self.result_contract not in {"http_status", "application_database_dependency"}:
            raise ValueError("private probe result_contract is unsupported")


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    subscription_id: str
    resource_groups: frozenset[str]
    contributor_group_id: str
    executor_principal_ids: tuple[str, str, str]
    reader_identity_client_id: str
    executor_identity_client_id: str
    idempotency_container_url: str
    private_probes: Mapping[str, PrivateProbe]
    mutations_enabled: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> GatewayConfig:
        values = os.environ if env is None else env
        if values.get("FDAI_DEV_GATEWAY_ENABLED", "").strip() != "1":
            raise ValueError("development operations gateway is disabled")
        if values.get("FDAI_ENV", "").strip().casefold() != "dev":
            raise ValueError("development operations gateway requires FDAI_ENV=dev")
        groups = frozenset(
            item.strip()
            for item in values.get("FDAI_DEV_GATEWAY_RESOURCE_GROUPS", "").split(",")
            if item.strip()
        )
        probes_raw = json.loads(values.get("FDAI_DEV_GATEWAY_PRIVATE_PROBES_JSON", "{}"))
        if not isinstance(probes_raw, Mapping):
            raise ValueError("private probes configuration MUST be an object")
        probes: dict[str, PrivateProbe] = {}
        for alias, item in probes_raw.items():
            if not isinstance(alias, str) or _IDENTIFIER.fullmatch(alias) is None:
                raise ValueError("private probe aliases MUST be bounded identifiers")
            if not isinstance(item, Mapping):
                raise ValueError("private probe entries MUST be objects")
            probes[alias] = PrivateProbe(
                url=str(item.get("url", "")),
                audience=str(item.get("audience", "")),
                result_contract=str(item.get("result_contract", "http_status")),
            )
        idempotency_container_url = values.get(
            "FDAI_DEV_GATEWAY_IDEMPOTENCY_CONTAINER_URL", ""
        ).strip()
        AzureBlobIdempotencyConfig(container_url=idempotency_container_url)
        mutations_raw = values.get("FDAI_DEV_GATEWAY_MUTATIONS_ENABLED", "0").strip()
        if mutations_raw not in {"0", "1"}:
            raise ValueError("FDAI_DEV_GATEWAY_MUTATIONS_ENABLED MUST be 0 or 1")
        parsed_executor_principal_ids = tuple(
            item.strip()
            for item in values.get("FDAI_DEV_GATEWAY_EXECUTOR_PRINCIPAL_IDS", "").split(",")
            if item.strip()
        )
        if len(parsed_executor_principal_ids) != len(_EXECUTOR_VERTICAL_ORDER):
            raise ValueError(
                "executor principal ids MUST contain change, resilience, and finops in order"
            )
        if len(set(parsed_executor_principal_ids)) != len(parsed_executor_principal_ids):
            raise ValueError("executor principal ids MUST be distinct")
        if any(len(item) > 256 for item in parsed_executor_principal_ids):
            raise ValueError("executor principal ids MUST be bounded")
        executor_principal_ids = (
            parsed_executor_principal_ids[0],
            parsed_executor_principal_ids[1],
            parsed_executor_principal_ids[2],
        )
        config = cls(
            subscription_id=values.get("FDAI_DEV_GATEWAY_SUBSCRIPTION_ID", "").strip(),
            resource_groups=groups,
            contributor_group_id=values.get("FDAI_DEV_GATEWAY_CONTRIBUTOR_GROUP_ID", "").strip(),
            executor_principal_ids=executor_principal_ids,
            reader_identity_client_id=values.get(
                "FDAI_DEV_GATEWAY_READER_MI_CLIENT_ID", ""
            ).strip(),
            executor_identity_client_id=values.get(
                "FDAI_DEV_GATEWAY_EXECUTOR_MI_CLIENT_ID", ""
            ).strip(),
            idempotency_container_url=idempotency_container_url,
            private_probes=probes,
            mutations_enabled=mutations_raw == "1",
        )
        for name, value in (
            ("subscription id", config.subscription_id),
            ("contributor group id", config.contributor_group_id),
            ("reader identity client id", config.reader_identity_client_id),
            ("executor identity client id", config.executor_identity_client_id),
            ("idempotency container URL", config.idempotency_container_url),
        ):
            if not value or len(value) > 256:
                raise ValueError(f"{name} MUST be configured")
        if not config.resource_groups:
            raise ValueError("at least one development resource group MUST be configured")
        return config


class TokenProvider(Protocol):
    async def get_token(self, audience: str) -> str: ...


class ManagedIdentityTokenProvider:
    def __init__(self, *, client_id: str, http_client: httpx.AsyncClient) -> None:
        self._client_id = client_id
        self._http = http_client

    async def get_token(self, audience: str) -> str:
        endpoint = os.environ.get("IDENTITY_ENDPOINT", "").strip()
        identity_header = os.environ.get("IDENTITY_HEADER", "").strip()
        if not endpoint or not identity_header:
            raise GatewayError(503, "identity_unavailable", "managed identity is unavailable")
        try:
            response = await self._http.get(
                endpoint,
                headers={"X-IDENTITY-HEADER": identity_header},
                params={
                    "api-version": "2019-08-01",
                    "resource": audience,
                    "client_id": self._client_id,
                },
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            raise GatewayError(
                503,
                "identity_unavailable",
                "managed identity token request failed",
            ) from exc
        if response.status_code >= 400:
            raise GatewayError(503, "identity_unavailable", "managed identity token failed")
        try:
            payload = response.json()
        except ValueError as exc:
            raise GatewayError(
                503,
                "identity_unavailable",
                "managed identity token response was invalid",
            ) from exc
        token = payload.get("access_token") if isinstance(payload, Mapping) else None
        if not isinstance(token, str) or not token:
            raise GatewayError(503, "identity_unavailable", "managed identity token was empty")
        return token
