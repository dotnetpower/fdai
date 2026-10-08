"""Authoritative exact Resource state reads from Azure Resource Manager.

Azure Resource Graph is eventually consistent and can return a pre-change value after a change, so
a typed answer that must cover an unreconciled change reads the resource provider directly. Only the
reviewed per-type capabilities below are read; every other type is unsupported, and an ambiguous or
missing state, a missing provider time, or a denied read returns no reading.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Final

import httpx

from fdai.shared.providers.exact_resource_state import (
    ExactResourceStateReading,
    ExactResourceStateUnavailableError,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_MANAGEMENT_ORIGIN: Final = "https://management.azure.com"
_MANAGEMENT_AUDIENCE: Final = "https://management.azure.com/.default"
_ARM_ID: Final = re.compile(
    r"/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/[^/]{1,90}/providers/"
    r"[A-Za-z0-9.]{1,64}/[A-Za-z0-9]{1,64}/[^/?#]{1,80}"
)


@dataclass(frozen=True, slots=True)
class ArmStateCapability:
    """One reviewed ARM read and the exact field that holds the lifecycle state."""

    provider_type: str
    path_suffix: str
    api_version: str
    extract: Callable[[Mapping[str, Any]], str | None]


def _power_state(payload: Mapping[str, Any]) -> str | None:
    statuses = payload.get("statuses")
    if not isinstance(statuses, list):
        return None
    codes = [
        item.get("code")
        for item in statuses
        if isinstance(item, Mapping)
        and isinstance(item.get("code"), str)
        and item["code"].startswith("PowerState/")
    ]
    # Exactly one power status is the state; none or several are ambiguous.
    return codes[0] if len(codes) == 1 else None


def _properties_state(payload: Mapping[str, Any]) -> str | None:
    properties = payload.get("properties")
    if not isinstance(properties, Mapping):
        return None
    state = properties.get("state")
    return state if isinstance(state, str) and state.strip() else None


#: Reviewed capabilities keyed by FDAI Resource type. The extracted values use the same vocabulary
#: the inventory projection records, such as ``PowerState/running`` and ``Stopped``.
ARM_STATE_CAPABILITIES: Final[Mapping[str, ArmStateCapability]] = {
    "compute.vm": ArmStateCapability(
        provider_type="microsoft.compute/virtualmachines",
        path_suffix="/instanceView",
        api_version="2024-07-01",
        extract=_power_state,
    ),
    "postgresql-server": ArmStateCapability(
        provider_type="microsoft.dbforpostgresql/flexibleservers",
        path_suffix="",
        api_version="2024-08-01",
        extract=_properties_state,
    ),
    "mysql-server": ArmStateCapability(
        provider_type="microsoft.dbformysql/flexibleservers",
        path_suffix="",
        api_version="2023-12-30",
        extract=_properties_state,
    ),
}


class AzureArmExactStateReader:
    """Read one supported Resource's state from ARM with the injected workload identity."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        management_origin: str = _MANAGEMENT_ORIGIN,
        audience: str = _MANAGEMENT_AUDIENCE,
        capabilities: Mapping[str, ArmStateCapability] = ARM_STATE_CAPABILITIES,
    ) -> None:
        if not management_origin.startswith("https://"):
            raise ValueError("ARM management origin MUST use HTTPS")
        self._identity = identity
        self._http = http_client
        self._origin = management_origin.rstrip("/")
        self._audience = audience
        self._capabilities = capabilities

    def supports(self, resource_type: str) -> bool:
        return resource_type in self._capabilities

    async def read_state(
        self,
        *,
        resource_ref: str,
        resource_type: str,
        provider_ref: str,
        timeout_seconds: float,
    ) -> ExactResourceStateReading | None:
        capability = self._capabilities.get(resource_type)
        if capability is None or _ARM_ID.fullmatch(provider_ref) is None:
            return None
        if f"/providers/{capability.provider_type}/" not in provider_ref.lower():
            return None
        endpoint = f"{self._origin}{provider_ref}{capability.path_suffix}"
        try:
            token = await self._identity.get_token(self._audience)
            response = await self._http.get(
                endpoint,
                params={"api-version": capability.api_version},
                headers={"Authorization": f"Bearer {token.token}"},
                timeout=timeout_seconds,
            )
        except (httpx.HTTPError, TimeoutError, RuntimeError) as exc:
            # Identity adapters report token failures as RuntimeError; no reading is proven.
            raise ExactResourceStateUnavailableError("ARM state read is unavailable") from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise ExactResourceStateUnavailableError(
                f"ARM state read returned {response.status_code}"
            )
        if response.status_code != 200:
            # A denied or missing read proves nothing about the Resource, so it yields no reading.
            return None
        provider_time = _provider_time(response.headers.get("date"))
        try:
            payload = response.json()
        except ValueError:
            return None
        state = capability.extract(payload) if isinstance(payload, Mapping) else None
        if provider_time is None or state is None:
            return None
        return ExactResourceStateReading(
            resource_ref=resource_ref,
            resource_type=resource_type,
            state=state,
            provider_time=provider_time,
            evidence_ref=_evidence_ref(
                provider_ref=provider_ref,
                api_version=capability.api_version,
                state=state,
                provider_time=provider_time,
            ),
        )


def _provider_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _evidence_ref(
    *,
    provider_ref: str,
    api_version: str,
    state: str,
    provider_time: datetime,
) -> str:
    body = json.dumps(
        {
            "provider_ref": provider_ref.lower(),
            "api_version": api_version,
            "state": state,
            "provider_time": provider_time.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "arm-state:sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


__all__ = ["ARM_STATE_CAPABILITIES", "ArmStateCapability", "AzureArmExactStateReader"]
