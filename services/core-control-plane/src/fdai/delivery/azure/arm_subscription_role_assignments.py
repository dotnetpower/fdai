"""Read the complete role assignments that apply at one subscription's scope.

Subscription role-assignment Rules evaluate every assignment at or above the subscription: the
role name, whether the principal is a guest, and whether access is standing. Assignments come
from the `atScope()` listing, role names from their definitions, guest status from Microsoft
Graph (including guests reached through a group), and standing status from Privileged Identity
Management. A tenant without the PIM license can't hold just-in-time assignments, so every active
assignment there is standing. Any other failed or incomplete read leaves the whole list
unobserved, because a partial list would make a privileged guest or standing assignment invisible.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any
from urllib.parse import quote

ROLE_ASSIGNMENT_API_VERSION = "2022-04-01"
PIM_API_VERSION = "2020-10-01"
MAX_PAGES = 64
PIM_LICENSE_REQUIRED = "AadPremiumLicenseRequired"

ReadJson = Callable[[str], Awaitable[Mapping[str, Any]]]


class RoleAssignmentReadError(Exception):
    """One read in the subscription's role assignment set failed or was malformed."""

    def __init__(self, message: str, *, error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


async def subscription_role_assignments(
    *,
    subscription_id: str,
    arm_endpoint: str,
    graph_endpoint: str,
    read_arm: ReadJson,
    read_graph: ReadJson,
) -> list[dict[str, Any]]:
    """Return the projected assignments for one subscription, or raise when incomplete."""

    scope = f"/subscriptions/{quote(subscription_id, safe='')}"
    assignments = await _pages(
        read_arm,
        f"{arm_endpoint}{scope}/providers/Microsoft.Authorization/roleAssignments"
        f"?api-version={ROLE_ASSIGNMENT_API_VERSION}&$filter=atScope()",
        prefix=arm_endpoint,
    )
    standing_by_id = await _standing(read_arm, arm_endpoint=arm_endpoint, scope=scope)
    definitions: dict[str, str] = {}
    principal_types: dict[str, list[str]] = {}
    projected: list[dict[str, Any]] = []
    for row in assignments:
        properties = row.get("properties") if isinstance(row, Mapping) else None
        if not isinstance(properties, Mapping) or not all(
            isinstance(properties.get(key), str) and properties[key]
            for key in ("principalId", "principalType", "roleDefinitionId", "scope")
        ):
            raise RoleAssignmentReadError("role assignment is malformed")
        definition_id = str(properties["roleDefinitionId"])
        if definition_id.casefold() not in definitions:
            definitions[definition_id.casefold()] = await _role_name(
                read_arm, arm_endpoint, definition_id
            )
        principal = str(properties["principalId"])
        kind = str(properties["principalType"])
        key = f"{kind}:{principal}".casefold()
        if key not in principal_types:
            principal_types[key] = await _principal_types(
                read_graph, graph_endpoint=graph_endpoint, kind=kind, principal=principal
            )
        assignment_id = str(row.get("id", "")).casefold()
        standing = True if standing_by_id is None else standing_by_id.get(assignment_id, True)
        for principal_type in principal_types[key]:
            projected.append(
                {
                    "role_name": definitions[definition_id.casefold()],
                    "principal_type": principal_type,
                    "standing": standing,
                    "scope": "subscription",
                }
            )
    projected.sort(
        key=lambda item: (item["role_name"], item["principal_type"], not item["standing"])
    )
    return projected


async def _pages(read: ReadJson, url: str, *, prefix: str) -> list[Mapping[str, Any]]:
    collected: list[Mapping[str, Any]] = []
    current: str | None = url
    for _page in range(MAX_PAGES):
        if current is None:
            return collected
        payload = await read(current)
        rows = payload.get("value")
        if not isinstance(rows, Sequence) or isinstance(rows, str):
            raise RoleAssignmentReadError("listing page is malformed")
        if any(not isinstance(row, Mapping) for row in rows):
            raise RoleAssignmentReadError("listing row is malformed")
        collected.extend(rows)
        next_link = payload.get("nextLink") or payload.get("@odata.nextLink")
        if next_link is not None and (
            not isinstance(next_link, str) or not next_link.startswith(prefix + "/")
        ):
            raise RoleAssignmentReadError("listing continuation is malformed")
        current = next_link
    raise RoleAssignmentReadError("listing page cap exceeded")


async def _standing(
    read: ReadJson,
    *,
    arm_endpoint: str,
    scope: str,
) -> dict[str, bool] | None:
    """Map each active assignment id to whether it is standing, or ``None`` without PIM."""

    try:
        instances = await _pages(
            read,
            f"{arm_endpoint}{scope}/providers/Microsoft.Authorization/"
            f"roleAssignmentScheduleInstances?api-version={PIM_API_VERSION}&$filter=atScope()",
            prefix=arm_endpoint,
        )
    except RoleAssignmentReadError as exc:
        if exc.error_code == PIM_LICENSE_REQUIRED:
            # Without the license no assignment can be just-in-time, so all are standing.
            return None
        raise
    standing: dict[str, bool] = {}
    for instance in instances:
        properties = instance.get("properties")
        if not isinstance(properties, Mapping):
            raise RoleAssignmentReadError("PIM schedule instance is malformed")
        origin = properties.get("originRoleAssignmentId")
        kind = properties.get("assignmentType")
        if not isinstance(origin, str) or kind not in {"Activated", "Assigned"}:
            raise RoleAssignmentReadError("PIM schedule instance is malformed")
        standing[origin.casefold()] = kind != "Activated"
    return standing


async def _role_name(read: ReadJson, arm_endpoint: str, definition_id: str) -> str:
    payload = await read(
        f"{arm_endpoint}{quote(definition_id, safe='/')}?api-version={ROLE_ASSIGNMENT_API_VERSION}"
    )
    properties = payload.get("properties")
    name = properties.get("roleName") if isinstance(properties, Mapping) else None
    if not isinstance(name, str) or not name:
        raise RoleAssignmentReadError("role definition is malformed")
    return name


async def _principal_types(
    read: ReadJson,
    *,
    graph_endpoint: str,
    kind: str,
    principal: str,
) -> list[str]:
    """Return the principal types an assignment grants access to, including group guests."""

    encoded = quote(principal, safe="")
    if kind == "User":
        payload = await read(f"{graph_endpoint}/v1.0/users/{encoded}?$select=userType")
        user_type = payload.get("userType")
        if user_type not in {"Member", "Guest"}:
            raise RoleAssignmentReadError("user type is unavailable")
        return ["Guest" if user_type == "Guest" else "User"]
    if kind == "Group":
        members = await _pages(
            read,
            f"{graph_endpoint}/v1.0/groups/{encoded}/transitiveMembers/microsoft.graph.user"
            "?$select=userType&$top=999",
            prefix=graph_endpoint,
        )
        if any(member.get("userType") not in {"Member", "Guest"} for member in members):
            raise RoleAssignmentReadError("group member type is unavailable")
        guests = any(member.get("userType") == "Guest" for member in members)
        return ["Group", "Guest"] if guests else ["Group"]
    return [kind]


__all__ = [
    "PIM_LICENSE_REQUIRED",
    "RoleAssignmentReadError",
    "subscription_role_assignments",
]
