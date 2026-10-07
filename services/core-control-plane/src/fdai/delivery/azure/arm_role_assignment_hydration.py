"""Project Azure RBAC role assignments onto user-assigned managed identities.

Managed-identity Rules evaluate ``role_assignments``: the scope kind, role name, and permitted
actions of every assignment that applies to the identity. One subscription's assignments are read
once, at, above, and below the subscription, and each referenced role definition is resolved once.
Any failed or malformed read leaves every identity in that subscription unobserved, because a
partial assignment list would make a privileged identity look clean.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any
from urllib.parse import quote

ROLE_ASSIGNMENT_API_VERSION = "2022-04-01"
MAX_ROLE_ASSIGNMENT_PAGES = 64

ReadJson = Callable[[str], Awaitable[Mapping[str, Any] | None]]


class RoleAssignmentsUnavailableError(Exception):
    """One subscription's assignments could not be read completely."""


def scope_kind(scope: str, subscription_id: str) -> str:
    """Classify an assignment scope relative to the subscription it was listed under.

    A scope at or above the subscription, including a management group, covers the whole
    subscription and is reported as ``subscription``.
    """

    normalized = scope.rstrip("/").casefold()
    subscription = f"/subscriptions/{subscription_id}".casefold()
    if normalized in {"", subscription} or not normalized.startswith(subscription + "/"):
        return "subscription"
    remainder = normalized.removeprefix(subscription + "/").split("/")
    if len(remainder) == 2 and remainder[0] == "resourcegroups":
        return "resource_group"
    return "resource"


async def subscription_role_assignments(
    *,
    endpoint: str,
    subscription_id: str,
    read_json: ReadJson,
) -> dict[str, list[dict[str, Any]]]:
    """Return projected assignments keyed by lowercase principal id for one subscription.

    Raises:
        RoleAssignmentsUnavailableError: when any page or role definition is missing or malformed.
    """

    url: str | None = (
        f"{endpoint}/subscriptions/{quote(subscription_id, safe='')}"
        f"/providers/Microsoft.Authorization/roleAssignments"
        f"?api-version={ROLE_ASSIGNMENT_API_VERSION}"
    )
    assignments: list[Mapping[str, Any]] = []
    for _page in range(MAX_ROLE_ASSIGNMENT_PAGES):
        if url is None:
            break
        payload = await read_json(url)
        rows = payload.get("value") if payload is not None else None
        if not isinstance(rows, Sequence) or isinstance(rows, str):
            raise RoleAssignmentsUnavailableError("role assignment page is malformed")
        assignments.extend(_assignment_properties(row) for row in rows)
        next_link = payload.get("nextLink") if payload is not None else None
        if next_link is not None and (
            not isinstance(next_link, str) or not next_link.startswith(endpoint + "/")
        ):
            raise RoleAssignmentsUnavailableError("role assignment continuation is malformed")
        url = next_link
    else:
        if url is not None:
            raise RoleAssignmentsUnavailableError("role assignment page cap exceeded")

    definitions: dict[str, Mapping[str, Any]] = {}
    projected: dict[str, list[dict[str, Any]]] = {}
    for assignment in assignments:
        definition_id = str(assignment["roleDefinitionId"])
        definition = definitions.get(definition_id.casefold())
        if definition is None:
            definition = await _role_definition(endpoint, definition_id, read_json)
            definitions[definition_id.casefold()] = definition
        projected.setdefault(str(assignment["principalId"]).casefold(), []).append(
            {
                "scope": scope_kind(str(assignment["scope"]), subscription_id),
                "role_name": definition["role_name"],
                "actions": definition["actions"],
                "data_actions": definition["data_actions"],
                "principal_type": assignment.get("principalType"),
            }
        )
    for items in projected.values():
        items.sort(key=lambda item: (item["scope"], str(item["role_name"])))
    return projected


def _assignment_properties(row: object) -> Mapping[str, Any]:
    properties = row.get("properties") if isinstance(row, Mapping) else None
    if not isinstance(properties, Mapping) or not all(
        isinstance(properties.get(key), str) and properties[key]
        for key in ("principalId", "roleDefinitionId", "scope")
    ):
        raise RoleAssignmentsUnavailableError("role assignment is malformed")
    return properties


async def _role_definition(
    endpoint: str,
    definition_id: str,
    read_json: ReadJson,
) -> Mapping[str, Any]:
    payload = await read_json(
        f"{endpoint}{quote(definition_id, safe='/')}?api-version={ROLE_ASSIGNMENT_API_VERSION}"
    )
    properties = payload.get("properties") if payload is not None else None
    if not isinstance(properties, Mapping) or not isinstance(properties.get("roleName"), str):
        raise RoleAssignmentsUnavailableError("role definition is malformed")
    permissions = properties.get("permissions")
    if not isinstance(permissions, Sequence) or isinstance(permissions, str):
        raise RoleAssignmentsUnavailableError("role definition permissions are malformed")
    actions: set[str] = set()
    data_actions: set[str] = set()
    for permission in permissions:
        if not isinstance(permission, Mapping):
            raise RoleAssignmentsUnavailableError("role definition permission is malformed")
        actions.update(_strings(permission.get("actions")))
        data_actions.update(_strings(permission.get("dataActions")))
    return {
        "role_name": properties["roleName"],
        "actions": sorted(actions),
        "data_actions": sorted(data_actions),
    }


def _strings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise RoleAssignmentsUnavailableError("role definition action list is malformed")
    if not all(isinstance(item, str) for item in value):
        raise RoleAssignmentsUnavailableError("role definition action is malformed")
    return tuple(value)


__all__ = [
    "ROLE_ASSIGNMENT_API_VERSION",
    "RoleAssignmentsUnavailableError",
    "scope_kind",
    "subscription_role_assignments",
]
