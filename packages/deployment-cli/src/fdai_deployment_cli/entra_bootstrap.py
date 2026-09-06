"""Bounded Entra registration/group bootstrap for a future protected executor.

The consumer MUST perform protected authorization before invoking apply, hold an
exclusive tenant/deployment lock, and supply the approved Console origin and
explicit initial owner USER. Plans and consent selection grant no authority.
The consumer persists returned IDs privately, never as public evidence. Partial
failure requires protected reconciliation; this adapter never retries or deletes.
GET verification proves only directory fields, not authenticated browser access
or complete installer readiness. No tokens, private IDs, or provider bodies log.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Literal
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

from fdai_deployment_cli.entra_graph import (
    EntraBootstrapError,
    Graph,
    GraphToken,
    GraphTransport,
    HttpsGraphTransport,
    Json,
    matches,
    objects,
    strings,
    uuid,
)

# Human App Roles and flags are pinned by user-rbac-and-identity and its runbook.
ROLES = ("Reader", "Contributor", "Approver", "Owner", "BreakGlass")
_SLOTS = ("readers", "contributors", "approvers", "owners", "break_glass")


@dataclass(frozen=True, slots=True, repr=False)
class EntraDesired:
    """Private target intent; consent is an operation selection, not authorization."""

    tenant_id: str
    deployment_binding: str
    initial_owner_user_id: str
    console_origin: str
    name_prefix: str
    consent: Literal["none", "initial-owner"] = "none"

    def __post_init__(self) -> None:
        for value in (self.tenant_id, self.initial_owner_user_id):
            if uuid(value) != value:
                raise EntraBootstrapError("noncanonical-uuid")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", self.deployment_binding):
            raise EntraBootstrapError("invalid-binding")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", self.name_prefix):
            raise EntraBootstrapError("invalid-prefix")
        try:
            origin = urlsplit(self.console_origin)
            valid = (
                self.console_origin.isascii()
                and origin.scheme == "https"
                and origin.hostname
                and origin.username is None
                and origin.password is None
                and origin.path == ""
                and not origin.query
                and not origin.fragment
                and origin.port in (None, 443)
                and not any(char in self.console_origin for char in "\\?#")
                and all(32 < ord(char) < 127 for char in self.console_origin)
                and re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", origin.hostname)
            )
        except ValueError:
            valid = False
        if not valid:
            raise EntraBootstrapError("invalid-console-origin")
        if self.consent not in {"none", "initial-owner"}:
            raise EntraBootstrapError("invalid-consent-selection")


@dataclass(frozen=True, slots=True, repr=False)
class EntraPlan:
    """Immutable, deterministic desired state; contains no observed success claim."""

    desired: EntraDesired
    marker: str
    role_ids: tuple[str, ...]
    scope_id: str
    digest: str


def plan_entra_bootstrap(desired: EntraDesired) -> EntraPlan:
    """Compile private desired state without network calls or implicit caller selection."""
    desired.__post_init__()
    binding = hashlib.sha256(
        f"{desired.tenant_id}/{desired.deployment_binding}".encode()
    ).hexdigest()
    marker = f"fdai-bootstrap:v1:{binding}"
    digest = hashlib.sha256(json.dumps(asdict(desired), sort_keys=True).encode()).hexdigest()
    return EntraPlan(
        desired,
        marker,
        tuple(str(uuid5(NAMESPACE_URL, f"{marker}/{role}")) for role in ROLES),
        str(uuid5(NAMESPACE_URL, f"{marker}/access")),
        digest,
    )


@dataclass(frozen=True, slots=True, repr=False)
class EntraReferences:
    """Private configuration references; group slots match the documented RBAC schema."""

    tenant_id: str
    api_object_id: str
    api_client_id: str
    spa_object_id: str
    spa_client_id: str
    api_service_principal_id: str
    spa_service_principal_id: str
    groups: tuple[tuple[str, str], ...]

    @property
    def api_scope(self) -> str:
        """Return the sole requested custom delegated scope, not Graph permissions."""
        return f"api://{self.api_client_id}/access"


@dataclass(frozen=True, slots=True)
class EntraBootstrapResult:
    """Directory-only postconditions, private references, and an opaque evidence digest."""

    references: EntraReferences = field(repr=False)
    verified_stages: tuple[str, ...]
    evidence_digest: str


def _roles(plan: EntraPlan) -> list[Json]:
    return [
        {
            "id": role_id,
            "value": role,
            "displayName": role,
            "description": f"FDAI {role} human role",
            "allowedMemberTypes": ["User"],
            "isEnabled": True,
        }
        for role, role_id in zip(ROLES, plan.role_ids, strict=True)
    ]


def _scope(plan: EntraPlan) -> Json:
    return {
        "id": plan.scope_id,
        "value": "access",
        "type": "User",
        "isEnabled": True,
        "adminConsentDisplayName": "Access the fdai Operator API",
        "adminConsentDescription": "Allow the console to call the fdai Operator API on behalf of the signed-in operator",
        "userConsentDisplayName": "Access the fdai Operator API",
        "userConsentDescription": "Allow the console to call the fdai Operator API on your behalf",
    }


def _merge_definitions(existing: object, desired: list[Json]) -> list[Json]:
    """Add missing definitions, refusing any collision in ID, value, or role flags."""
    merged = [
        {key: value for key, value in row.items() if key != "origin"} for row in objects(existing)
    ]
    for item in desired:
        collisions = [
            row
            for row in merged
            if row.get("id") == item["id"] or row.get("value") == item["value"]
        ]
        if collisions:
            if len(collisions) != 1 or not matches(collisions[0], item):
                raise EntraBootstrapError("role-or-scope-conflict")
            if "allowedMemberTypes" in item and collisions[0]["allowedMemberTypes"] != ["User"]:
                raise EntraBootstrapError("role-or-scope-conflict")
        else:
            merged.append(item)
    return merged


def _app_payload(plan: EntraPlan, label: str, existing: Json | None, api_id: str = "") -> Json:
    old = existing or {}
    if existing and old.get("signInAudience") != "AzureADMyOrg":
        raise EntraBootstrapError("application-contract-conflict")
    if existing:
        required = (
            ("appRoles", "api", "identifierUris")
            if label == "api"
            else (
                "spa",
                "requiredResourceAccess",
            )
        )
        nested = old.get("api" if label == "api" else "spa")
        nested_required = (
            ("oauth2PermissionScopes", "requestedAccessTokenVersion")
            if label == "api"
            else ("redirectUris",)
        )
        if (
            any(key not in old for key in required)
            or not isinstance(nested, dict)
            or any(key not in nested for key in nested_required)
        ):
            raise EntraBootstrapError("incomplete-application")
    payload: Json = {
        "displayName": f"{plan.desired.name_prefix}-{label}",
        "signInAudience": "AzureADMyOrg",
        "tags": list(dict.fromkeys([*strings(old.get("tags", [])), f"{plan.marker}:{label}"])),
    }
    if label == "api":
        api = old.get("api", {})
        if not isinstance(api, dict) or api.get("requestedAccessTokenVersion") not in (None, 2):
            raise EntraBootstrapError("application-contract-conflict")
        payload["appRoles"] = _merge_definitions(old.get("appRoles", []), _roles(plan))
        payload["api"] = {
            **api,
            "requestedAccessTokenVersion": 2,
            "oauth2PermissionScopes": _merge_definitions(
                api.get("oauth2PermissionScopes", []),
                [_scope(plan)],
            ),
        }
        if api_id:
            uris = strings(old.get("identifierUris", []))
            if uris and f"api://{api_id}" not in uris:
                raise EntraBootstrapError("application-uri-conflict")
            payload["identifierUris"] = list(dict.fromkeys([*uris, f"api://{api_id}"]))
    else:
        spa = old.get("spa", {})
        if not isinstance(spa, dict):
            raise EntraBootstrapError("application-contract-conflict")
        payload["spa"] = {
            "redirectUris": list(
                dict.fromkeys(
                    [
                        *strings(spa.get("redirectUris", [])),
                        plan.desired.console_origin,
                    ]
                )
            )
        }
        permissions = [dict(row) for row in objects(old.get("requiredResourceAccess", []))]
        matching = [row for row in permissions if row.get("resourceAppId") == api_id]
        if len(matching) > 1:
            raise EntraBootstrapError("scope-permission-conflict")
        if not matching:
            permissions.append({"resourceAppId": api_id, "resourceAccess": []})
            matching = [permissions[-1]]
        access = objects(matching[0].get("resourceAccess"))
        wanted = {"id": plan.scope_id, "type": "Scope"}
        if any(row.get("id") == plan.scope_id and row != wanted for row in access):
            raise EntraBootstrapError("scope-permission-conflict")
        matching[0]["resourceAccess"] = access if wanted in access else [*access, wanted]
        payload["requiredResourceAccess"] = permissions
    return payload


def _run(plan: EntraPlan, graph: Graph, *, mutate: bool) -> EntraBootstrapResult:
    desired = plan.desired
    owner = graph.call("GET", f"users/{desired.initial_owner_user_id}?$select=id,accountEnabled")
    if owner.get("id") != desired.initial_owner_user_id or owner.get("accountEnabled") is not True:
        raise EntraBootstrapError("initial-owner-unavailable")
    labels = ("api", "console-spa", *_SLOTS)
    records: dict[str, Json | None] = {}
    for label in labels:
        records[label] = graph.owned(
            "applications" if label in labels[:2] else "groups",
            f"{plan.marker}:{label}",
            f"{desired.name_prefix}-{label}",
            f"fdai-{plan.marker.split(':')[-1][:32]}-{label}",
        )
    api_old = records["api"]
    api_id = uuid(api_old["appId"]) if api_old else ""
    _app_payload(plan, "api", api_old, api_id)
    if api_id:
        _app_payload(plan, "console-spa", records["console-spa"], api_id)
    group_payloads: dict[str, Json] = {}
    for slot in _SLOTS:
        payload = {
            "displayName": f"{desired.name_prefix}-{slot}",
            "description": f"{plan.marker}:{slot}",
            "mailNickname": f"fdai-{plan.marker.split(':')[-1][:32]}-{slot}",
            "mailEnabled": False,
            "securityEnabled": True,
            "groupTypes": [],
        }
        record = records[slot]
        if record and (
            not matches(record, payload)
            or record.get("groupTypes") != []
            or record.get("onPremisesSyncEnabled") is True
            or "onPremisesSyncEnabled" not in record
            or record.get("isAssignableToRole") is not False
        ):
            raise EntraBootstrapError("group-contract-conflict")
        group_payloads[slot] = payload

    def ensure(kind: str, existing: Json | None, payload: Json) -> Json:
        if not mutate and (existing is None or not matches(existing, payload)):
            raise EntraBootstrapError("readback-mismatch")
        return graph.ensure(kind, existing, payload)

    api = ensure("applications", api_old, _app_payload(plan, "api", api_old, api_id))
    api_id = uuid(api.get("appId"))
    api = ensure("applications", api, _app_payload(plan, "api", api, api_id))
    spa = ensure(
        "applications",
        records["console-spa"],
        _app_payload(plan, "console-spa", records["console-spa"], api_id),
    )
    principals: list[Json] = []
    for label, app in (("api", api), ("console-spa", spa)):
        app_id = uuid(app.get("appId"))
        rows = graph.list("servicePrincipals", {"$filter": f"appId eq '{app_id}'"})
        if len(rows) > 1:
            raise EntraBootstrapError("ambiguous-ownership")
        old = graph.call("GET", f"servicePrincipals/{uuid(rows[0].get('id'))}") if rows else None
        marker = f"{plan.marker}:{label}"
        if old and (
            [tag for tag in strings(old.get("tags")) if tag.startswith("fdai-bootstrap:")]
            != [marker]
            or old.get("appOwnerOrganizationId") != desired.tenant_id
            or old.get("servicePrincipalType") != "Application"
            or old.get("appId") != app_id
            or old.get("accountEnabled") is not True
        ):
            raise EntraBootstrapError("foreign-ownership")
        principal = ensure(
            "servicePrincipals",
            old,
            {
                "appId": app_id,
                "tags": list(
                    dict.fromkeys(
                        [
                            *strings((old or {}).get("tags", [])),
                            marker,
                        ]
                    )
                ),
                "accountEnabled": True,
            },
        )
        if (
            principal.get("appOwnerOrganizationId") != desired.tenant_id
            or principal.get("servicePrincipalType") != "Application"
        ):
            raise EntraBootstrapError("readback-mismatch")
        principals.append(principal)
    api_sp, spa_sp = (uuid(row.get("id")) for row in principals)
    if not matches(
        principals[0],
        {
            "appRoles": _roles(plan),
            "oauth2PermissionScopes": [_scope(plan)],
        },
    ):
        raise EntraBootstrapError("role-readback-mismatch")
    _merge_definitions(principals[0]["appRoles"], _roles(plan))
    groups = {slot: ensure("groups", records[slot], group_payloads[slot]) for slot in _SLOTS}
    if any(
        row.get("isAssignableToRole") is not False
        or row.get("groupTypes") != []
        or row.get("onPremisesSyncEnabled") is True
        or "onPremisesSyncEnabled" not in row
        for row in groups.values()
    ):
        raise EntraBootstrapError("group-readback-mismatch")
    assignment_path = f"servicePrincipals/{api_sp}/appRoleAssignedTo"
    assignments = graph.list(assignment_path)
    if any(
        not all(
            isinstance(row.get(key), str)
            for key in ("principalId", "resourceId", "appRoleId", "principalType")
        )
        or row["resourceId"] != api_sp
        for row in assignments
    ):
        raise EntraBootstrapError("incomplete-assignment")
    for slot, role_id in zip(_SLOTS, plan.role_ids, strict=True):
        group_id = uuid(groups[slot].get("id"))
        wanted = {"principalId": group_id, "resourceId": api_sp, "appRoleId": role_id}
        own = [row for row in assignments if row.get("principalId") == group_id]
        if len(own) > 1 or any(not matches(row, wanted) for row in own):
            raise EntraBootstrapError("assignment-conflict")
        if not own and mutate:
            graph.call("POST", assignment_path, wanted)
    verified = graph.list(assignment_path)
    if any(
        not any(
            matches(
                row,
                {
                    "principalId": groups[slot]["id"],
                    "resourceId": api_sp,
                    "appRoleId": role_id,
                    "principalType": "Group",
                },
            )
            for row in verified
        )
        for slot, role_id in zip(_SLOTS, plan.role_ids, strict=True)
    ):
        raise EntraBootstrapError("assignment-readback-mismatch")
    member_path = f"groups/{uuid(groups['owners'].get('id'))}/members"
    members = graph.list(member_path, {"$select": "id"})
    for member in members:
        uuid(member.get("id"))
    if not any(row.get("id") == desired.initial_owner_user_id for row in members) and mutate:
        graph.call(
            "POST",
            member_path + "/$ref",
            {
                "@odata.id": f"https://graph.microsoft.com/v1.0/users/{desired.initial_owner_user_id}",
            },
        )
    if not any(
        row.get("id") == desired.initial_owner_user_id
        for row in graph.list(member_path, {"$select": "id"})
    ):
        raise EntraBootstrapError("owner-readback-mismatch")
    stages: tuple[str, ...] = (
        "applications",
        "service-principals",
        "role-groups",
        "assignments",
        "initial-owner",
    )
    if desired.consent == "initial-owner":
        consent = {
            "clientId": spa_sp,
            "resourceId": api_sp,
            "consentType": "Principal",
            "principalId": desired.initial_owner_user_id,
            "scope": "access",
        }
        grants = graph.list("oauth2PermissionGrants", {"$filter": f"clientId eq '{spa_sp}'"})
        own = [
            row
            for row in grants
            if row.get("resourceId") == api_sp
            and row.get("principalId") == desired.initial_owner_user_id
        ]
        if len(own) > 1 or any(not matches(row, consent) for row in own):
            raise EntraBootstrapError("consent-conflict")
        if not own and mutate:
            graph.call("POST", "oauth2PermissionGrants", consent)
        grants = graph.list("oauth2PermissionGrants", {"$filter": f"clientId eq '{spa_sp}'"})
        if not any(matches(row, consent) for row in grants):
            raise EntraBootstrapError("consent-readback-mismatch")
        stages += ("initial-owner-custom-scope-consent",)
    refs = EntraReferences(
        desired.tenant_id,
        uuid(api["id"]),
        api_id,
        uuid(spa["id"]),
        uuid(spa["appId"]),
        api_sp,
        spa_sp,
        tuple((slot, uuid(groups[slot]["id"])) for slot in _SLOTS),
    )
    evidence = {
        "plan": plan.digest,
        "references": asdict(refs),
        "stages": stages,
        "api": _app_payload(plan, "api", api, api_id),
        "spa": _app_payload(plan, "console-spa", spa, api_id),
    }
    return EntraBootstrapResult(
        refs,
        stages,
        hashlib.sha256(
            json.dumps(evidence, sort_keys=True).encode(),
        ).hexdigest(),
    )


def apply_entra_bootstrap(
    plan: EntraPlan,
    *,
    token_provider: Callable[[str], GraphToken],
    transport: GraphTransport | None = None,
) -> EntraBootstrapResult:
    """Reconcile only owned objects after caller-provided protected authorization."""
    if plan != plan_entra_bootstrap(plan.desired):
        raise EntraBootstrapError("invalid-plan")
    return _run(
        plan,
        Graph(plan.desired.tenant_id, token_provider, transport or HttpsGraphTransport()),
        mutate=True,
    )


def readback_entra_bootstrap(
    plan: EntraPlan,
    references: EntraReferences,
    *,
    token_provider: Callable[[str], GraphToken],
    transport: GraphTransport | None = None,
) -> EntraBootstrapResult:
    """Use only fresh GETs and require the same privately retained object identities."""
    if plan != plan_entra_bootstrap(plan.desired):
        raise EntraBootstrapError("invalid-plan")
    result = _run(
        plan,
        Graph(plan.desired.tenant_id, token_provider, transport or HttpsGraphTransport()),
        mutate=False,
    )
    if result.references != references:
        raise EntraBootstrapError("reference-mismatch")
    return result
