"""Bounded Microsoft Graph reader for Operator IAM directory views."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import urlparse

import httpx

from fdai_operator_service.families.iam.contracts import DirectoryIdentity, DirectoryStatus

_GRAPH_SCOPE: Final = "https://graph.microsoft.com/.default"
_GRAPH_BASE_URL: Final = "https://graph.microsoft.com/v1.0"
_RETRYABLE_STATUS: Final = frozenset({429, 502, 503, 504})

TokenProvider = Callable[[str], Awaitable[str]]


@dataclass(slots=True)
class EntraHumanIdentityDirectory:
    """Read exact users and configured role groups without Graph write permission."""

    client: httpx.AsyncClient | None
    token_provider: TokenProvider
    application_id: str | None = None
    base_url: str = _GRAPH_BASE_URL
    max_attempts: int = 3
    _observed_at: datetime | None = field(default=None, init=False, repr=False)
    _available: bool | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.base_url.rstrip("/") != _GRAPH_BASE_URL:
            raise ValueError(
                "identity directory Graph base_url MUST be the Microsoft v1.0 endpoint"
            )
        if not 1 <= self.max_attempts <= 5:
            raise ValueError("identity directory max_attempts MUST be between 1 and 5")

    async def search(self, query: str, *, limit: int) -> Sequence[DirectoryIdentity]:
        normalized = query.strip()
        if not 2 <= len(normalized) <= 128:
            raise ValueError("identity search query MUST contain between 2 and 128 characters")
        if not 1 <= limit <= 50:
            raise ValueError("identity search limit MUST be between 1 and 50")
        escaped = normalized.replace("'", "''")
        payload = await self._get_json(
            "/users",
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
            consistency=True,
        )
        identities: list[DirectoryIdentity] = []
        for item in _items(payload, "users"):
            if isinstance(item, Mapping):
                identities.append(_user(item))
        return tuple(identities)

    async def list_role_roster(
        self,
        role_group_ids: Mapping[str, str],
        *,
        limit: int,
    ) -> Sequence[DirectoryIdentity]:
        if not 1 <= limit <= 500:
            raise ValueError("identity roster limit MUST be between 1 and 500")
        if self.application_id is not None:
            return await self._list_application_role_roster(limit=limit)
        groups: list[DirectoryIdentity] = []
        people: dict[str, DirectoryIdentity] = {}
        for role, group_id in role_group_ids.items():
            group = await self._get_json(
                f"/groups/{_component(group_id, 'group id')}",
                params={"$select": "id,displayName"},
            )
            groups.append(
                DirectoryIdentity(
                    provider="entra",
                    subject_id=_required(group, "id", "group"),
                    username=_required(group, "displayName", "group"),
                    display_name=_required(group, "displayName", "group"),
                    active=True,
                    user_type="group",
                    principal_type="group",
                    roles=(role,),
                )
            )
            await self._collect_group_people(
                group_id=group_id,
                role=role,
                people=people,
                limit=limit,
            )
        ordered = sorted(people.values(), key=lambda item: (item.display_name or "").casefold())
        return tuple((*groups, *ordered)[:limit])

    async def _list_application_role_roster(
        self,
        *,
        limit: int,
    ) -> Sequence[DirectoryIdentity]:
        service_principals = await self._get_json(
            "/servicePrincipals",
            params={
                "$filter": f"appId eq '{_component(self.application_id or '', 'application id')}'",
                "$select": "id,appRoles",
                "$top": "2",
            },
        )
        values = _items(service_principals, "service principals")
        if len(values) != 1 or not isinstance(values[0], Mapping):
            raise RuntimeError("Microsoft Graph FDAI service principal lookup was not unique")
        service_principal = values[0]
        service_principal_id = _required(service_principal, "id", "service principal")
        raw_roles = service_principal.get("appRoles")
        if not isinstance(raw_roles, list):
            raise RuntimeError("Microsoft Graph service principal response has no appRoles array")
        role_by_id = {
            role_id: role_value
            for item in raw_roles
            if isinstance(item, Mapping)
            and isinstance((role_id := item.get("id")), str)
            and isinstance((role_value := item.get("value")), str)
            and role_value
        }
        groups: dict[str, DirectoryIdentity] = {}
        people: dict[str, DirectoryIdentity] = {}
        path: str | None = f"/servicePrincipals/{service_principal_id}/appRoleAssignedTo"
        params: Mapping[str, str] | None = {
            "$select": "appRoleId,principalId,principalType",
            "$top": "100",
        }
        pages = 0
        while path is not None and pages < 10:
            payload = await self._get_json(path, params=params)
            for item in _items(payload, "app-role assignments"):
                if not isinstance(item, Mapping):
                    continue
                role_id = item.get("appRoleId")
                principal_id = item.get("principalId")
                principal_type = item.get("principalType")
                role = role_by_id.get(role_id) if isinstance(role_id, str) else None
                if role is None or not isinstance(principal_id, str):
                    continue
                if principal_type == "Group":
                    await self._collect_assigned_group(
                        group_id=principal_id,
                        role=role,
                        groups=groups,
                        people=people,
                        limit=limit,
                    )
                elif principal_type == "User":
                    await self._collect_assigned_user(
                        subject_id=principal_id,
                        role=role,
                        people=people,
                    )
            next_link = payload.get("@odata.nextLink")
            path = next_link if isinstance(next_link, str) and next_link else None
            params = None
            pages += 1
        if path is not None:
            raise RuntimeError("Microsoft Graph app-role assignment pagination exceeded 10 pages")
        ordered_groups = sorted(
            groups.values(),
            key=lambda item: (item.display_name or "").casefold(),
        )
        ordered_people = sorted(
            people.values(),
            key=lambda item: (item.display_name or "").casefold(),
        )
        return tuple((*ordered_groups, *ordered_people)[:limit])

    async def _collect_assigned_group(
        self,
        *,
        group_id: str,
        role: str,
        groups: dict[str, DirectoryIdentity],
        people: dict[str, DirectoryIdentity],
        limit: int,
    ) -> None:
        group = await self._get_json(
            f"/groups/{_component(group_id, 'group id')}",
            params={"$select": "id,displayName"},
        )
        group_subject = _required(group, "id", "group")
        group_name = _required(group, "displayName", "group")
        existing = groups.get(group_subject)
        roles = tuple(sorted(set(existing.roles if existing else ()) | {role}))
        groups[group_subject] = DirectoryIdentity(
            provider="entra",
            subject_id=group_subject,
            username=group_name,
            display_name=group_name,
            active=True,
            user_type="group",
            principal_type="group",
            roles=roles,
        )
        await self._collect_group_people(
            group_id=group_id,
            role=role,
            people=people,
            limit=limit,
        )

    async def _collect_assigned_user(
        self,
        *,
        subject_id: str,
        role: str,
        people: dict[str, DirectoryIdentity],
    ) -> None:
        payload = await self._get_json(
            f"/users/{_component(subject_id, 'subject id')}",
            params={"$select": "id,displayName,userPrincipalName,mail,userType,accountEnabled"},
        )
        parsed = _user(payload)
        existing = people.get(parsed.subject_id)
        roles = tuple(sorted(set(existing.roles if existing else ()) | {role}))
        people[parsed.subject_id] = DirectoryIdentity(
            provider=parsed.provider,
            subject_id=parsed.subject_id,
            username=parsed.username,
            display_name=parsed.display_name,
            active=parsed.active,
            user_type=parsed.user_type,
            roles=roles,
        )

    async def get_by_subject_id(self, subject_id: str) -> DirectoryIdentity | None:
        normalized = _component(subject_id, "subject id")
        try:
            payload = await self._get_json(
                f"/users/{normalized}",
                params={"$select": "id,displayName,userPrincipalName,mail,userType,accountEnabled"},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
        else:
            return _user(payload)
        try:
            group = await self._get_json(
                f"/groups/{normalized}",
                params={"$select": "id,displayName"},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        display_name = _required(group, "displayName", "group")
        return DirectoryIdentity(
            provider="entra",
            subject_id=_required(group, "id", "group"),
            username=display_name,
            display_name=display_name,
            active=True,
            user_type="group",
            principal_type="group",
        )

    async def directory_status(self) -> DirectoryStatus:
        availability = (
            "available"
            if self._available is True
            else "unavailable"
            if self._available is False
            else "unknown"
        )
        return DirectoryStatus(
            source="microsoft-graph",
            availability=availability,
            observed_at=self._observed_at,
            detail=(
                "No directory query has completed in this process."
                if self._available is None
                else None
            ),
        )

    async def _collect_group_people(
        self,
        *,
        group_id: str,
        role: str,
        people: dict[str, DirectoryIdentity],
        limit: int,
    ) -> None:
        path: str | None = (
            f"/groups/{_component(group_id, 'group id')}/transitiveMembers/microsoft.graph.user"
        )
        params: Mapping[str, str] | None = {
            "$select": "id,displayName,userPrincipalName,mail,userType,accountEnabled",
            "$top": str(min(limit, 100)),
        }
        while path is not None and len(people) < limit:
            payload = await self._get_json(path, params=params)
            for raw in _items(payload, "group members"):
                if not isinstance(raw, Mapping):
                    continue
                parsed = _user(raw)
                existing = people.get(parsed.subject_id)
                roles = tuple(sorted(set(existing.roles if existing else ()) | {role}))
                people[parsed.subject_id] = DirectoryIdentity(
                    provider=parsed.provider,
                    subject_id=parsed.subject_id,
                    username=parsed.username,
                    display_name=parsed.display_name,
                    active=parsed.active,
                    user_type=parsed.user_type,
                    principal_type="person",
                    roles=roles,
                )
                if len(people) >= limit:
                    break
            next_link = payload.get("@odata.nextLink")
            path = next_link if isinstance(next_link, str) and next_link else None
            params = None

    async def _get_json(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        consistency: bool = False,
    ) -> Mapping[str, Any]:
        token = await self.token_provider(_GRAPH_SCOPE)
        headers = {"Authorization": "Bearer " + token}
        if consistency:
            headers["ConsistencyLevel"] = "eventual"
        if path.startswith("https://"):
            parsed = urlparse(path)
            base = urlparse(self.base_url)
            if (
                parsed.scheme != base.scheme
                or parsed.netloc != base.netloc
                or not parsed.path.startswith(f"{base.path.rstrip('/')}/")
            ):
                self._available = False
                raise RuntimeError("Microsoft Graph pagination URL left the configured API")
            url = path
        else:
            url = f"{self.base_url.rstrip('/')}{path}"
        try:
            response = await self._request(url, headers=headers, params=params)
            payload = response.json()
            if not isinstance(payload, Mapping):
                raise RuntimeError("Microsoft Graph directory response MUST be an object")
        except Exception:
            self._available = False
            raise
        self._available = True
        self._observed_at = datetime.now(UTC)
        return payload

    async def _request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, str] | None,
    ) -> httpx.Response:
        for attempt in range(self.max_attempts):
            if self.client is None:
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
                    response = await client.get(url, headers=headers, params=params)
            else:
                response = await self.client.get(url, headers=headers, params=params)
            if response.status_code not in _RETRYABLE_STATUS or attempt + 1 >= self.max_attempts:
                response.raise_for_status()
                return response
            await asyncio.sleep(min(2**attempt, 4))
        raise RuntimeError("Microsoft Graph directory retry bound was exhausted")


def _user(value: Mapping[str, Any]) -> DirectoryIdentity:
    subject_id = _required(value, "id", "user")
    username = value.get("userPrincipalName") or value.get("mail")
    if not isinstance(username, str) or not username:
        raise RuntimeError("Microsoft Graph user has no displayable username")
    display_name = value.get("displayName")
    user_type = value.get("userType")
    return DirectoryIdentity(
        provider="entra",
        subject_id=subject_id,
        username=username,
        display_name=display_name if isinstance(display_name, str) and display_name else username,
        active=value.get("accountEnabled") is True,
        user_type=(user_type.casefold() if isinstance(user_type, str) and user_type else "unknown"),
    )


def _items(value: Mapping[str, Any], label: str) -> list[object]:
    items = value.get("value")
    if not isinstance(items, list):
        raise RuntimeError(f"Microsoft Graph {label} response has no value array")
    return items


def _required(value: Mapping[str, Any], key: str, label: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise RuntimeError(f"Microsoft Graph {label} response has no {key}")
    return item


def _component(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized or "/" in normalized or "?" in normalized or "#" in normalized:
        raise ValueError(f"identity directory {label} is invalid")
    return normalized


__all__ = ["EntraHumanIdentityDirectory", "TokenProvider"]
