"""Read every role assignment in one tenant so managed identities can be judged completely.

A managed identity can hold roles at the tenant root, any management group, any subscription, or
any resource group or resource below. One subscription's listing can't show grants elsewhere, so a
managed identity's ``role_assignments`` is projected only from a tenant-wide read that proves its
own completeness:

- the root management group (named by the tenant id) and its complete descendant listing are
  readable, which happens only when the collector can read the whole hierarchy;
- every management group's ``atScope()`` listing and every subscription's full listing (at and
  below the subscription) are read without error; and
- every referenced role definition resolves to a name and its actions; and
- every group principal's transitive service principal members are read from Microsoft Graph, so a
  grant an identity holds through group membership is attributed to it.

Any failed, malformed, truncated, or over-budget read raises, and the caller leaves every managed
identity's assignments unobserved. Scopes are normalized for Rules: an assignment at a management
group or the root applies to every subscription below it, so it is reported as ``subscription``
scope; resource group and resource assignments keep their narrower scope.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from fdai.delivery.azure.arm_subscription_role_assignments import (
    ROLE_ASSIGNMENT_API_VERSION,
    ReadJson,
    RoleAssignmentReadError,
    _pages,
)

MANAGEMENT_GROUP_API_VERSION = "2020-05-01"
MAX_SUBSCRIPTIONS = 200
MAX_MANAGEMENT_GROUPS = 200

_MANAGEMENT_GROUP_TYPE = "microsoft.management/managementgroups"
_SUBSCRIPTION_TYPE = "microsoft.management/managementgroups/subscriptions"
_SUBSCRIPTION_SCOPE = re.compile(r"^/subscriptions/[^/]+$", re.IGNORECASE)
_RESOURCE_GROUP_SCOPE = re.compile(r"^/subscriptions/[^/]+/resourcegroups/[^/]+$", re.IGNORECASE)
_RESOURCE_SCOPE = re.compile(r"^/subscriptions/[^/]+/resourcegroups/[^/]+/providers/.+", re.I)
_MANAGEMENT_GROUP_SCOPE = re.compile(
    r"^/providers/microsoft\.management/managementgroups/[^/]+$", re.IGNORECASE
)


async def tenant_role_assignments_by_principal(
    *,
    tenant_id: str,
    arm_endpoint: str,
    read_arm: ReadJson,
    graph_endpoint: str | None = None,
    read_graph: ReadJson | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return every principal's projected assignments in the tenant, or raise when incomplete."""

    if not tenant_id.strip():
        raise RoleAssignmentReadError("tenant id is required")
    root = f"/providers/Microsoft.Management/managementGroups/{quote(tenant_id, safe='')}"
    descendants = await _pages(
        read_arm,
        f"{arm_endpoint}{root}/descendants?api-version={MANAGEMENT_GROUP_API_VERSION}",
        prefix=arm_endpoint,
    )
    management_groups = [root]
    subscriptions: list[str] = []
    for row in descendants:
        kind = str(row.get("type", "")).casefold()
        name = row.get("name")
        if not isinstance(name, str) or not name:
            raise RoleAssignmentReadError("management group descendant is malformed")
        if kind == _MANAGEMENT_GROUP_TYPE:
            management_groups.append(
                f"/providers/Microsoft.Management/managementGroups/{quote(name, safe='')}"
            )
        elif kind == _SUBSCRIPTION_TYPE:
            subscriptions.append(f"/subscriptions/{quote(name, safe='')}")
        else:
            raise RoleAssignmentReadError("management group descendant has an unknown type")
    if len(subscriptions) > MAX_SUBSCRIPTIONS or len(management_groups) > MAX_MANAGEMENT_GROUPS:
        raise RoleAssignmentReadError("tenant hierarchy exceeds the role assignment read bound")

    rows: dict[str, Mapping[str, Any]] = {}
    listings = [
        *(
            f"{scope}/providers/Microsoft.Authorization/roleAssignments"
            f"?api-version={ROLE_ASSIGNMENT_API_VERSION}&$filter=atScope()"
            for scope in management_groups
        ),
        *(
            f"{scope}/providers/Microsoft.Authorization/roleAssignments"
            f"?api-version={ROLE_ASSIGNMENT_API_VERSION}"
            for scope in subscriptions
        ),
    ]
    for listing in listings:
        for row in await _pages(read_arm, f"{arm_endpoint}{listing}", prefix=arm_endpoint):
            assignment_id = row.get("id")
            if not isinstance(assignment_id, str) or not assignment_id:
                raise RoleAssignmentReadError("role assignment is malformed")
            rows.setdefault(assignment_id.casefold(), row)

    definitions: dict[str, tuple[str, list[str], list[str]]] = {}
    members: dict[str, list[str]] = {}
    by_principal: dict[str, list[dict[str, Any]]] = {}
    for row in rows.values():
        properties = row.get("properties")
        if not isinstance(properties, Mapping) or not all(
            isinstance(properties.get(key), str) and properties[key]
            for key in ("principalId", "principalType", "roleDefinitionId", "scope")
        ):
            raise RoleAssignmentReadError("role assignment is malformed")
        definition_id = str(properties["roleDefinitionId"])
        key = definition_id.casefold()
        if key not in definitions:
            definitions[key] = await _definition(read_arm, arm_endpoint, definition_id)
        role_name, actions, data_actions = definitions[key]
        principal = str(properties["principalId"]).casefold()
        holders = [principal]
        if str(properties["principalType"]).casefold() == "group":
            if principal not in members:
                members[principal] = await _service_principal_members(
                    read_graph, graph_endpoint, principal
                )
            holders.extend(members[principal])
        for holder in dict.fromkeys(holders):
            by_principal.setdefault(holder, []).append(
                {
                    "role_name": role_name,
                    "scope": _scope_level(str(properties["scope"])),
                    "actions": actions,
                    "data_actions": data_actions,
                }
            )
    for assignments in by_principal.values():
        assignments.sort(key=lambda item: (item["scope"], item["role_name"]))
    return by_principal


async def _service_principal_members(
    read_graph: ReadJson | None,
    graph_endpoint: str | None,
    group_id: str,
) -> list[str]:
    """Return a group's transitive service principal member ids, or raise when unreadable."""

    if read_graph is None or graph_endpoint is None:
        raise RoleAssignmentReadError("group role assignments need Microsoft Graph membership")
    rows = await _pages(
        read_graph,
        f"{graph_endpoint}/v1.0/groups/{quote(group_id, safe='')}/transitiveMembers/"
        "microsoft.graph.servicePrincipal?$select=id&$top=999",
        prefix=graph_endpoint,
    )
    identifiers: list[str] = []
    for row in rows:
        identifier = row.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise RoleAssignmentReadError("group member is malformed")
        identifiers.append(identifier.casefold())
    return identifiers


def _scope_level(scope: str) -> str:
    if scope == "/" or _MANAGEMENT_GROUP_SCOPE.match(scope) or _SUBSCRIPTION_SCOPE.match(scope):
        return "subscription"
    if _RESOURCE_GROUP_SCOPE.match(scope):
        return "resource_group"
    if _RESOURCE_SCOPE.match(scope):
        return "resource"
    raise RoleAssignmentReadError("role assignment scope is not recognized")


async def _definition(
    read: ReadJson,
    arm_endpoint: str,
    definition_id: str,
) -> tuple[str, list[str], list[str]]:
    payload = await read(
        f"{arm_endpoint}{quote(definition_id, safe='/')}?api-version={ROLE_ASSIGNMENT_API_VERSION}"
    )
    properties = payload.get("properties")
    name = properties.get("roleName") if isinstance(properties, Mapping) else None
    permissions = properties.get("permissions") if isinstance(properties, Mapping) else None
    if not isinstance(name, str) or not name or not isinstance(permissions, list):
        raise RoleAssignmentReadError("role definition is malformed")
    actions: set[str] = set()
    data_actions: set[str] = set()
    for permission in permissions:
        if not isinstance(permission, Mapping):
            raise RoleAssignmentReadError("role definition permission is malformed")
        for field, target in (("actions", actions), ("dataActions", data_actions)):
            values = permission.get(field, [])
            if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
                raise RoleAssignmentReadError("role definition permission is malformed")
            target.update(values)
    return name, sorted(actions), sorted(data_actions)


__all__ = [
    "MANAGEMENT_GROUP_API_VERSION",
    "MAX_MANAGEMENT_GROUPS",
    "MAX_SUBSCRIPTIONS",
    "tenant_role_assignments_by_principal",
]
