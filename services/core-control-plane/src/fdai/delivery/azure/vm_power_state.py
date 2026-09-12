"""Read one configured Azure VM power state through a dedicated observer identity."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from fdai.shared.providers.workload_identity import WorkloadIdentity

_MANAGEMENT_AUDIENCE: Final = "https://management.azure.com/.default"
_API_VERSION: Final = "2024-07-01"
_VM_RESOURCE = re.compile(
    r"^/subscriptions/(?P<subscription>[^/]+)/resourceGroups/"
    r"(?P<resource_group>[^/]+)/providers/Microsoft\.Compute/"
    r"virtualMachines/(?P<vm_name>[^/]+)$",
    re.IGNORECASE,
)
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.()-]{0,127}$")
_POWER_STATE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_KNOWN_STATES = frozenset(
    {
        "deallocated",
        "deallocating",
        "running",
        "starting",
        "stopped",
        "stopping",
    }
)


class AzureVmPowerStateSourceError(RuntimeError):
    """Raised when the authoritative VM power-state read cannot be trusted."""


@dataclass(frozen=True, slots=True)
class AzureVmPowerStateConfig:
    """Pin one observer to one VM in one resource group."""

    resource_ref: str
    resource_group: str
    vm_name: str
    endpoint: str = "https://management.azure.com"
    audience: str = _MANAGEMENT_AUDIENCE
    api_version: str = _API_VERSION
    timeout_seconds: float = 8.0
    max_response_bytes: int = 65_536
    freshness_seconds: int = 60

    def __post_init__(self) -> None:
        match = _VM_RESOURCE.fullmatch(self.resource_ref)
        if (
            match is None
            or _NAME.fullmatch(self.resource_group) is None
            or _NAME.fullmatch(self.vm_name) is None
            or match.group("resource_group").casefold() != self.resource_group.casefold()
            or match.group("vm_name").casefold() != self.vm_name.casefold()
        ):
            raise ValueError(
                "VM power-state scope MUST identify one matching Azure VM and resource group"
            )
        try:
            subscription_id = str(UUID(match.group("subscription")))
        except (AttributeError, ValueError) as exc:
            raise ValueError("VM power-state subscription MUST be a canonical UUID") from exc
        if subscription_id != match.group("subscription").casefold():
            raise ValueError("VM power-state subscription MUST be a canonical UUID")
        parsed = urlsplit(self.endpoint)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "management.azure.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("VM power-state endpoint MUST be the Azure management origin")
        if self.audience != _MANAGEMENT_AUDIENCE:
            raise ValueError("VM power-state audience MUST be Azure Resource Manager")
        if self.api_version != _API_VERSION:
            raise ValueError(f"VM power-state api_version MUST be {_API_VERSION}")
        if not 0.1 <= self.timeout_seconds <= 30:
            raise ValueError("VM power-state timeout_seconds MUST be in [0.1, 30]")
        if not 1_024 <= self.max_response_bytes <= 1_000_000:
            raise ValueError("VM power-state max_response_bytes MUST be in [1024, 1000000]")
        if not 1 <= self.freshness_seconds <= 300:
            raise ValueError("VM power-state freshness_seconds MUST be in [1, 300]")


@dataclass(frozen=True, slots=True)
class AzureVmPowerStateReading:
    """Bounded provider observation for one pinned semantic target revision."""

    resource_ref: str
    target_revision: int
    state: str | None
    observed_at: datetime
    recorded_at: datetime
    fresh_until: datetime
    complete: bool
    conflicts: tuple[str, ...]
    censoring_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if _VM_RESOURCE.fullmatch(self.resource_ref) is None:
            raise ValueError("VM power-state reading resource_ref is invalid")
        if isinstance(self.target_revision, bool) or self.target_revision < 1:
            raise ValueError("VM power-state target_revision MUST be positive")
        for name, value in (
            ("observed_at", self.observed_at),
            ("recorded_at", self.recorded_at),
            ("fresh_until", self.fresh_until),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"VM power-state {name} MUST be timezone-aware")
        if not self.observed_at <= self.recorded_at <= self.fresh_until:
            raise ValueError(
                "VM power-state times MUST satisfy observed <= recorded <= fresh_until"
            )
        if self.state is not None and _POWER_STATE.fullmatch(self.state) is None:
            raise ValueError("VM power-state value MUST be canonical")
        if self.complete != (self.state is not None or bool(self.conflicts)):
            raise ValueError(
                "VM power-state completeness MUST match observed state or conflict evidence"
            )
        for name, values in (
            ("conflicts", self.conflicts),
            ("censoring_refs", self.censoring_refs),
            ("evidence_refs", self.evidence_refs),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(f"VM power-state {name} MUST be sorted and unique")
        if not self.evidence_refs or any(
            re.fullmatch(r"^sha256:[0-9a-f]{64}$", value) is None for value in self.evidence_refs
        ):
            raise ValueError("VM power-state evidence_refs MUST contain SHA-256 digests")


class AzureVmPowerStateSource(Protocol):
    """Read one exact VM through an identity independent from its executor."""

    async def observe(
        self,
        *,
        resource_ref: str,
        target_revision: int,
    ) -> AzureVmPowerStateReading: ...


class AzureArmVmPowerStateSource:
    """Read Azure instance view without calling the mutation gateway."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureVmPowerStateConfig,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._identity = identity
        self._http = http_client
        self._config = config
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def observe(
        self,
        *,
        resource_ref: str,
        target_revision: int,
    ) -> AzureVmPowerStateReading:
        """Return one bounded provider reading or raise a fail-closed error."""

        if resource_ref.casefold() != self._config.resource_ref.casefold():
            raise AzureVmPowerStateSourceError(
                "VM power-state request is outside the configured target"
            )
        requested_at = _aware_utc(self._clock(), name="request clock")
        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                token = await self._identity.get_token(self._config.audience)
                if (
                    not token.token
                    or token.audience != self._config.audience
                    or token.expires_at.tzinfo is None
                    or token.expires_at <= requested_at
                ):
                    raise AzureVmPowerStateSourceError(
                        "VM power-state observer identity is unavailable"
                    )
                body, response = await self._read_response(token.token)
        except AzureVmPowerStateSourceError:
            raise
        except (TimeoutError, httpx.HTTPError, RuntimeError) as exc:
            raise AzureVmPowerStateSourceError("Azure VM power-state observation failed") from exc
        observed_at = _aware_utc(self._clock(), name="observation clock")
        payload = _json_object(body)
        _validate_response_identity(payload, self._config.resource_ref)
        states, conflicts = _power_states(payload)
        state = states[0] if len(states) == 1 and states[0] in _KNOWN_STATES else None
        if len(states) == 1 and state is None:
            conflicts = (f"unsupported_power_state:{states[0]}",)
        elif len(states) > 1:
            conflicts = tuple(
                sorted(
                    {
                        *conflicts,
                        *(f"conflicting_power_state:{value}" for value in states),
                    }
                )
            )
        evidence_ref = _digest(
            {
                "resource_ref": self._config.resource_ref.casefold(),
                "etag": payload.get("etag"),
                "power_states": states,
                "observed_at": observed_at.isoformat(),
                "status_code": response.status_code,
            }
        )
        return AzureVmPowerStateReading(
            resource_ref=self._config.resource_ref.casefold(),
            target_revision=target_revision,
            state=state,
            observed_at=observed_at,
            recorded_at=observed_at,
            fresh_until=observed_at + timedelta(seconds=self._config.freshness_seconds),
            complete=state is not None or bool(conflicts),
            conflicts=conflicts,
            censoring_refs=(),
            evidence_refs=(evidence_ref,),
        )

    async def _read_response(self, token: str) -> tuple[bytes, httpx.Response]:
        url = f"{self._config.endpoint.rstrip('/')}{self._config.resource_ref}"
        async with self._http.stream(
            "GET",
            url,
            params={
                "api-version": self._config.api_version,
                "$expand": "instanceView",
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=self._config.timeout_seconds,
            follow_redirects=False,
        ) as response:
            if response.history or response.status_code != 200:
                raise AzureVmPowerStateSourceError(
                    "Azure VM power-state source returned a non-success status"
                )
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > self._config.max_response_bytes:
                    raise AzureVmPowerStateSourceError(
                        "Azure VM power-state response exceeded its size limit"
                    )
        return bytes(content), response


def _validate_response_identity(payload: Mapping[str, object], resource_ref: str) -> None:
    response_id = payload.get("id")
    response_type = payload.get("type")
    if (
        not isinstance(response_id, str)
        or response_id.casefold() != resource_ref.casefold()
        or not isinstance(response_type, str)
        or response_type.casefold() != "microsoft.compute/virtualmachines"
    ):
        raise AzureVmPowerStateSourceError("Azure VM power-state response target changed")


def _power_states(
    payload: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    properties = payload.get("properties")
    if not isinstance(properties, Mapping):
        return (), ()
    instance_view = properties.get("instanceView")
    if not isinstance(instance_view, Mapping):
        return (), ()
    statuses = instance_view.get("statuses")
    if not isinstance(statuses, list):
        return (), ()
    states: set[str] = set()
    malformed: set[str] = set()
    for item in statuses:
        if not isinstance(item, Mapping):
            continue
        code = item.get("code")
        if not isinstance(code, str) or not code.casefold().startswith("powerstate/"):
            continue
        state = code.split("/", 1)[1].casefold()
        if _POWER_STATE.fullmatch(state) is None:
            malformed.add("malformed_power_state")
            continue
        states.add(state)
    return tuple(sorted(states)), tuple(sorted(malformed))


def _json_object(body: bytes) -> Mapping[str, object]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AzureVmPowerStateSourceError(
            "Azure VM power-state response was invalid JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise AzureVmPowerStateSourceError("Azure VM power-state response MUST be an object")
    return payload


def _aware_utc(value: datetime, *, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"VM power-state {name} MUST be timezone-aware")
    return value.astimezone(UTC)


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "AzureArmVmPowerStateSource",
    "AzureVmPowerStateConfig",
    "AzureVmPowerStateReading",
    "AzureVmPowerStateSource",
    "AzureVmPowerStateSourceError",
]
