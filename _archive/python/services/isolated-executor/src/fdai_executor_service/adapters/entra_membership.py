"""Bounded exact Graph membership I/O, owned only by the isolated Executor.

No retry, role inference, arbitrary URL, directory search or assignment write is
implemented here. A caller-supplied current guard is rechecked after every read
and immediately before the one mutation. Acknowledgement is not effect proof.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from fdai_service_contracts.executor import (
    DirectApiAuthenticationError,
    DirectApiError,
    DirectApiPermissionDeniedError,
    DirectApiPreconditionError,
    WorkloadIdentity,
)
from fdai_service_contracts.human_access import HumanAccessPlan

_BASE = "https://graph.microsoft.com/v1.0"
_SCOPE = "https://graph.microsoft.com/.default"
CurrentGuard = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class MembershipPreflight:
    """Transient exact target read; authentication never enters records or repr output."""

    target_digest: str
    membership: bool
    token_expires_at: datetime
    headers: Mapping[str, str] = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class EntraMembershipClient:
    """One Graph request per step with exact allowlist and source/clock rechecks."""

    http_client: httpx.AsyncClient
    identity: WorkloadIdentity
    allowed_group_ids: frozenset[str]
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def __post_init__(self) -> None:
        if (
            type(self.allowed_group_ids) is not frozenset
            or not self.allowed_group_ids
            or any(
                not isinstance(ref, str) or ref != ref.casefold() for ref in self.allowed_group_ids
            )
        ):
            raise ValueError(
                "isolated membership groups MUST be exact normalized immutable references"
            )

    async def inspect(self, plan: HumanAccessPlan, *, guard: CurrentGuard) -> MembershipPreflight:
        """Read current exact user/group/classification/membership before mutation intent."""
        if plan.group_id not in self.allowed_group_ids:
            raise DirectApiPermissionDeniedError("human access target group is not allowlisted")
        await guard()
        async with asyncio.timeout(5):
            token = await self.identity.get_token(_SCOPE)
        if (
            token.audience != _SCOPE
            or token.expires_at.tzinfo is None
            or token.expires_at <= self.clock()
        ):
            raise DirectApiAuthenticationError(
                "human access workload token is not current or audience-bound"
            )
        headers = {"Authorization": f"Bearer {token.token}"}
        await guard()
        user = await self._read(f"/users/{plan.subject_id}?$select=id,accountEnabled", headers)
        await guard()
        if (
            user is None
            or user.get("id") != plan.subject_id
            or (plan.desired_membership and user.get("accountEnabled") is not True)
        ):
            raise DirectApiPreconditionError("human access target user is absent or ineligible")
        group = await self._read(
            f"/groups/{plan.group_id}?$select=id,securityEnabled,groupTypes,isAssignableToRole",
            headers,
        )
        await guard()
        types = group.get("groupTypes") if group is not None else None
        if (
            group is None
            or group.get("id") != plan.group_id
            or group.get("securityEnabled") is not True
            or group.get("isAssignableToRole") is not False
            or not isinstance(types, list)
        ):
            raise DirectApiPreconditionError(
                "human access group classification is unavailable or unsafe"
            )
        if not all(isinstance(item, str) for item in types) or "DynamicMembership" in types:
            raise DirectApiPermissionDeniedError("dynamic or ambiguous groups are not supported")
        membership = await self._read(
            f"/groups/{plan.group_id}/members/{plan.subject_id}?$select=id",
            headers,
            absent_allowed=True,
        )
        await guard()
        if membership is not None and membership.get("id") != plan.subject_id:
            raise DirectApiPreconditionError(
                "membership response differs from the exact requested person"
            )
        return MembershipPreflight(
            plan.target_digest, membership is not None, token.expires_at, headers
        )

    async def dispatch(
        self, plan: HumanAccessPlan, preflight: MembershipPreflight, *, guard: CurrentGuard
    ) -> None:
        """Perform at most one effect; any timeout or cancellation leaves its result unknown."""
        if (
            preflight.target_digest != plan.target_digest
            or plan.group_id not in self.allowed_group_ids
        ):
            raise DirectApiPreconditionError("human access preflight target changed")
        if preflight.membership is plan.desired_membership:
            raise DirectApiPreconditionError("an already satisfied membership MUST NOT be mutated")
        await guard()
        if preflight.token_expires_at <= self.clock():
            raise DirectApiAuthenticationError(
                "human access workload token expired before mutation"
            )
        path = f"/groups/{plan.group_id}/members/"
        method = "POST" if plan.desired_membership else "DELETE"
        path += "$ref" if plan.desired_membership else f"{plan.subject_id}/$ref"
        body = (
            {"@odata.id": f"{_BASE}/directoryObjects/{plan.subject_id}"}
            if plan.desired_membership
            else None
        )
        async with asyncio.timeout(10):
            response = await self.http_client.request(
                method,
                _BASE + path,
                headers=dict(preflight.headers),
                json=body,
                follow_redirects=False,
            )
        self._status(response)
        if response.status_code != 204:
            raise DirectApiError(
                "acknowledgement_unknown",
                "human access mutation did not return an exact acknowledgement",
            )

    async def _read(
        self, path: str, headers: Mapping[str, str], *, absent_allowed: bool = False
    ) -> dict[str, object] | None:
        async with asyncio.timeout(5):
            response = await self.http_client.get(
                _BASE + path, headers=dict(headers), follow_redirects=False
            )
        if absent_allowed and response.status_code == 404:
            return None
        self._status(response)
        if response.status_code != 200 or len(response.content) > 65536:
            raise DirectApiPreconditionError(
                "human access source response is unexpected or oversized"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise DirectApiPreconditionError(
                "human access source response is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise DirectApiPreconditionError("human access source response is not an exact record")
        return payload

    @staticmethod
    def _status(response: httpx.Response) -> None:
        if response.status_code == 401:
            raise DirectApiAuthenticationError("human access provider authentication failed")
        if response.status_code == 403:
            raise DirectApiPermissionDeniedError("human access provider permission denied")
        if response.status_code >= 300:
            raise DirectApiError(
                "request_refused",
                "human access provider refused the bounded request; no retry was made",
            )


__all__ = ["EntraMembershipClient", "MembershipPreflight"]
