"""Microsoft Graph implementation of the human identity search contract."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final
from urllib.parse import urlparse

import httpx

from fdai.shared.providers.human_identity import (
    HumanIdentity,
    HumanIdentityDirectory,
    IdentityRosterEntry,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_GRAPH_SCOPE: Final[str] = "https://graph.microsoft.com/.default"
_DEFAULT_BASE_URL: Final[str] = "https://graph.microsoft.com/v1.0"
_RETRYABLE_STATUS: Final[frozenset[int]] = frozenset({429, 502, 503, 504})


@dataclass(slots=True)
class _RosterCache:
    entries: tuple[IdentityRosterEntry, ...] | None = None
    expires_at: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(frozen=True, slots=True)
class EntraHumanIdentityDirectory(HumanIdentityDirectory):
    """Search active tenant users through Microsoft Graph using managed identity."""

    client: httpx.AsyncClient
    identity: WorkloadIdentity
    application_id: str | None = None
    base_url: str = _DEFAULT_BASE_URL
    max_attempts: int = 3
    roster_cache_seconds: float = 60.0
    _roster_cache: _RosterCache = field(default_factory=_RosterCache, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.max_attempts < 1 or self.max_attempts > 5:
            raise ValueError("max_attempts MUST be between 1 and 5")
        if self.roster_cache_seconds < 0 or self.roster_cache_seconds > 300:
            raise ValueError("roster_cache_seconds MUST be between 0 and 300")

    async def search(self, query: str, *, limit: int = 20) -> tuple[HumanIdentity, ...]:
        normalized = query.strip()
        if len(normalized) < 2:
            raise ValueError("identity search query MUST contain at least 2 characters")
        if len(normalized) > 128:
            raise ValueError("identity search query MUST contain at most 128 characters")
        if limit < 1 or limit > 50:
            raise ValueError("identity search limit MUST be between 1 and 50")

        token = await self.identity.get_token(_GRAPH_SCOPE)
        escaped = normalized.replace("'", "''")
        response = await self._get_with_retry(
            f"{self.base_url.rstrip('/')}/users",
            params={
                "$select": "id,displayName,userPrincipalName,mail,userType,accountEnabled",
                "$filter": (
                    f"startswith(displayName,'{escaped}') or "
                    f"startswith(userPrincipalName,'{escaped}') or "
                    f"startswith(mail,'{escaped}')"
                ),
                "$top": str(limit),
                "$count": "true",
            },
            headers={
                "Authorization": f"Bearer {token.token}",
                "ConsistencyLevel": "eventual",
            },
        )
        payload = response.json()
        raw_items = payload.get("value")
        if not isinstance(raw_items, list):
            raise RuntimeError("Microsoft Graph users response has no value array")
        identities: list[HumanIdentity] = []
        for item in raw_items:
            parsed = _parse_user(item)
            if parsed is not None:
                identities.append(parsed)
        return tuple(identities[:limit])

    async def get_by_subject_id(self, subject_id: str) -> HumanIdentity | None:
        normalized = subject_id.strip()
        if not normalized:
            raise ValueError("identity subject_id MUST be non-empty")
        token = await self.identity.get_token(_GRAPH_SCOPE)
        try:
            response = await self._get_with_retry(
                f"{self.base_url.rstrip('/')}/users/{normalized}",
                params={
                    "$select": "id,displayName,userPrincipalName,mail,userType,accountEnabled",
                },
                headers={"Authorization": f"Bearer {token.token}"},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return _parse_user(response.json())

    async def list_role_roster(
        self,
        role_group_ids: Mapping[str, str],
        *,
        limit: int = 200,
    ) -> tuple[IdentityRosterEntry, ...]:
        if limit < 1 or limit > 500:
            raise ValueError("identity roster limit MUST be between 1 and 500")
        token = await self.identity.get_token(_GRAPH_SCOPE)
        headers = {"Authorization": f"Bearer {token.token}"}
        if self.application_id:
            return await self._cached_application_role_roster(headers=headers, limit=limit)
        groups: list[IdentityRosterEntry] = []
        people: dict[str, IdentityRosterEntry] = {}
        for role, group_id in role_group_ids.items():
            response = await self._get_with_retry(
                f"{self.base_url.rstrip('/')}/groups/{group_id}",
                params={"$select": "id,displayName"},
                headers=headers,
            )
            group = response.json()
            group_subject = _required_graph_string(group, "id", "group")
            group_name = _required_graph_string(group, "displayName", "group")
            groups.append(
                IdentityRosterEntry(
                    provider="entra",
                    subject_id=group_subject,
                    display_name=group_name,
                    principal_type="group",
                    roles=(role,),
                )
            )
            await self._collect_group_people(
                group_id=group_id,
                role=role,
                headers=headers,
                people=people,
                limit=limit,
            )
        ordered_people = sorted(people.values(), key=lambda item: item.display_name.casefold())
        return tuple((*groups, *ordered_people)[:limit])

    async def _cached_application_role_roster(
        self,
        *,
        headers: dict[str, str],
        limit: int,
    ) -> tuple[IdentityRosterEntry, ...]:
        now = time.monotonic()
        cached = self._roster_cache.entries
        if cached is not None and now < self._roster_cache.expires_at:
            return cached[:limit]
        async with self._roster_cache.lock:
            now = time.monotonic()
            cached = self._roster_cache.entries
            if cached is not None and now < self._roster_cache.expires_at:
                return cached[:limit]
            entries = await self._list_application_role_roster(headers=headers, limit=500)
            self._roster_cache.entries = entries
            self._roster_cache.expires_at = now + self.roster_cache_seconds
            return entries[:limit]

    async def _list_application_role_roster(
        self,
        *,
        headers: dict[str, str],
        limit: int,
    ) -> tuple[IdentityRosterEntry, ...]:
        response = await self._get_with_retry(
            f"{self.base_url.rstrip('/')}/servicePrincipals",
            params={
                "$filter": f"appId eq '{self.application_id}'",
                "$select": "id,appRoles",
                "$top": "2",
            },
            headers=headers,
        )
        values = response.json().get("value")
        if not isinstance(values, list) or len(values) != 1:
            raise RuntimeError("Microsoft Graph FDAI service principal lookup was not unique")
        service_principal = values[0]
        service_principal_id = _required_graph_string(
            service_principal,
            "id",
            "service principal",
        )
        app_roles = service_principal.get("appRoles")
        if not isinstance(app_roles, list):
            raise RuntimeError("Microsoft Graph service principal response has no appRoles array")
        role_by_id = {
            role_id: role_value
            for item in app_roles
            if isinstance(item, dict)
            and isinstance((role_id := item.get("id")), str)
            and isinstance((role_value := item.get("value")), str)
            and role_value
        }

        groups: dict[str, IdentityRosterEntry] = {}
        people: dict[str, IdentityRosterEntry] = {}
        url: str | None = (
            f"{self.base_url.rstrip('/')}/servicePrincipals/"
            f"{service_principal_id}/appRoleAssignedTo"
        )
        params: dict[str, str] | None = {
            "$select": "appRoleId,principalId,principalType",
            "$top": "100",
        }
        pages = 0
        while url is not None and pages < 10:
            assignment_response = await self._get_with_retry(
                url,
                params=params or {},
                headers=headers,
            )
            payload = assignment_response.json()
            assignments = payload.get("value")
            if not isinstance(assignments, list):
                raise RuntimeError(
                    "Microsoft Graph app-role assignments response has no value array"
                )
            for assignment in assignments:
                if not isinstance(assignment, dict):
                    continue
                role_id = assignment.get("appRoleId")
                principal_id = assignment.get("principalId")
                principal_type = assignment.get("principalType")
                if not isinstance(role_id, str):
                    continue
                role = role_by_id.get(role_id)
                if role is None or not isinstance(principal_id, str) or not principal_id:
                    continue
                if principal_type == "Group":
                    await self._collect_assigned_group(
                        group_id=principal_id,
                        role=role,
                        headers=headers,
                        groups=groups,
                        people=people,
                        limit=limit,
                    )
                elif principal_type == "User":
                    await self._collect_assigned_user(
                        subject_id=principal_id,
                        role=role,
                        headers=headers,
                        people=people,
                    )
            url = self._validated_next_link(payload.get("@odata.nextLink"))
            params = None
            pages += 1
        if url is not None:
            raise RuntimeError("Microsoft Graph app-role assignment pagination exceeded 10 pages")

        ordered_groups = sorted(groups.values(), key=lambda item: item.display_name.casefold())
        ordered_people = sorted(people.values(), key=lambda item: item.display_name.casefold())
        return tuple((*ordered_groups, *ordered_people)[:limit])

    async def _collect_assigned_group(
        self,
        *,
        group_id: str,
        role: str,
        headers: dict[str, str],
        groups: dict[str, IdentityRosterEntry],
        people: dict[str, IdentityRosterEntry],
        limit: int,
    ) -> None:
        response = await self._get_with_retry(
            f"{self.base_url.rstrip('/')}/groups/{group_id}",
            params={"$select": "id,displayName"},
            headers=headers,
        )
        group = response.json()
        group_subject = _required_graph_string(group, "id", "group")
        group_name = _required_graph_string(group, "displayName", "group")
        existing = groups.get(group_subject)
        roles = tuple(dict.fromkeys((*(existing.roles if existing else ()), role)))
        groups[group_subject] = IdentityRosterEntry(
            provider="entra",
            subject_id=group_subject,
            display_name=group_name,
            principal_type="group",
            roles=roles,
        )
        await self._collect_group_people(
            group_id=group_id,
            role=role,
            headers=headers,
            people=people,
            limit=limit,
        )

    async def _collect_assigned_user(
        self,
        *,
        subject_id: str,
        role: str,
        headers: dict[str, str],
        people: dict[str, IdentityRosterEntry],
    ) -> None:
        response = await self._get_with_retry(
            f"{self.base_url.rstrip('/')}/users/{subject_id}",
            params={
                "$select": "id,displayName,userPrincipalName,mail,userType,accountEnabled",
            },
            headers=headers,
        )
        identity = _parse_user(response.json())
        if identity is None:
            return
        existing = people.get(identity.subject_id)
        roles = tuple(dict.fromkeys((*(existing.roles if existing else ()), role)))
        people[identity.subject_id] = IdentityRosterEntry(
            provider=identity.provider,
            subject_id=identity.subject_id,
            display_name=identity.display_name,
            principal_type="person",
            roles=roles,
            username=identity.username,
            active=identity.active,
        )

    async def _collect_group_people(
        self,
        *,
        group_id: str,
        role: str,
        headers: dict[str, str],
        people: dict[str, IdentityRosterEntry],
        limit: int,
    ) -> None:
        url: str | None = (
            f"{self.base_url.rstrip('/')}/groups/{group_id}/transitiveMembers/microsoft.graph.user"
        )
        params: dict[str, str] | None = {
            "$select": "id,displayName,userPrincipalName,mail,accountEnabled",
            "$top": "100",
        }
        pages = 0
        while url is not None and pages < 10 and len(people) < limit:
            response = await self._get_with_retry(
                url,
                params=params or {},
                headers=headers,
            )
            payload = response.json()
            values = payload.get("value")
            if not isinstance(values, list):
                raise RuntimeError("Microsoft Graph group members response has no value array")
            for value in values:
                identity = _parse_user(value)
                if identity is None:
                    continue
                existing = people.get(identity.subject_id)
                roles = tuple(dict.fromkeys((*(existing.roles if existing else ()), role)))
                people[identity.subject_id] = IdentityRosterEntry(
                    provider=identity.provider,
                    subject_id=identity.subject_id,
                    display_name=identity.display_name,
                    principal_type="person",
                    roles=roles,
                    username=identity.username,
                    active=identity.active,
                )
            next_link = payload.get("@odata.nextLink")
            url = self._validated_next_link(next_link)
            params = None
            pages += 1
        if url is not None:
            raise RuntimeError("Microsoft Graph roster pagination exceeded 10 pages")

    def _validated_next_link(self, value: object) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise RuntimeError("Microsoft Graph nextLink MUST be a string")
        base = urlparse(self.base_url)
        candidate = urlparse(value)
        base_path = base.path.rstrip("/")
        if (
            candidate.scheme != base.scheme
            or candidate.netloc != base.netloc
            or not candidate.path.startswith(f"{base_path}/")
        ):
            raise RuntimeError("Microsoft Graph nextLink is outside the configured API root")
        return value

    async def _get_with_retry(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> httpx.Response:
        for attempt in range(1, self.max_attempts + 1):
            response = await self.client.get(url, params=params, headers=headers, timeout=10.0)
            if response.status_code not in _RETRYABLE_STATUS or attempt == self.max_attempts:
                response.raise_for_status()
                return response
            retry_after = response.headers.get("Retry-After")
            delay = (
                float(retry_after)
                if retry_after and retry_after.isdigit()
                else 0.25 * 2 ** (attempt - 1)
            )
            await asyncio.sleep(min(delay, 2.0))
        raise RuntimeError("Microsoft Graph retry loop exhausted")


def _parse_user(value: Any) -> HumanIdentity | None:
    if not isinstance(value, dict):
        return None
    subject_id = value.get("id")
    display_name = value.get("displayName")
    username = value.get("userPrincipalName") or value.get("mail")
    if not isinstance(subject_id, str) or not subject_id.strip():
        return None
    if not isinstance(display_name, str) or not display_name.strip():
        return None
    if not isinstance(username, str) or not username.strip():
        return None
    user_type = value.get("userType")
    return HumanIdentity(
        provider="entra",
        subject_id=subject_id,
        username=username,
        display_name=display_name,
        user_type=user_type.casefold() if isinstance(user_type, str) and user_type else "member",
        active=value.get("accountEnabled") is not False,
    )


def _required_graph_string(value: Any, key: str, resource: str) -> str:
    item = value.get(key) if isinstance(value, dict) else None
    if not isinstance(item, str) or not item.strip():
        raise RuntimeError(f"Microsoft Graph {resource} response has no {key}")
    return item


__all__ = ["EntraHumanIdentityDirectory"]
