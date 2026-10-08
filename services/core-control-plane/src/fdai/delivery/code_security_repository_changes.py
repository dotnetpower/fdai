"""Owner-requested registration changes for code-security repositories.

The Console submits a registration change as a typed Operator proposal
(``code_security.repository_change``): register an alias for a GitHub ``owner/repository``, or
enable or disable an existing registration. The scan-request worker applies each change before it
scans, so a change made from the Console has the same validation, compare-and-set, and
Heimdall-attributed audit as the ``repo-register`` CLI. Only the Owner role may change
registrations, and the worker rechecks that role from the stored proposal.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from fdai.delivery.persistence.state_store_code_security_repository import (
    CodeSecurityRepositoryError,
    CodeSecurityRepositoryNotFoundError,
    register_repository,
    set_repository_enabled,
    validate_ref,
)
from fdai.rule_catalog.code_security import Exposure
from fdai.shared.providers.state_store import StateStore

REPOSITORY_CHANGE_OPERATION = "code_security.repository_change"
CHANGE_ROLES = frozenset({"Owner"})
ACTIONS = ("register", "enable", "disable")
_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_LOCATION = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
_PRINCIPAL = re.compile(r"^[A-Za-z0-9@._:/+-]{1,128}$")
_REQUEST_ID = re.compile(r"^operator-[0-9a-f]{32}$")

REJECT_MALFORMED = "request_malformed"
REJECT_ROLE = "requester_role_insufficient"
REJECT_UNREGISTERED = "repository_not_registered"
REJECT_REPOSITORY_CONFLICT = "repository_conflict"


@dataclass(frozen=True, slots=True)
class RepositoryChange:
    request_id: str
    action: str
    repository_alias: str
    principal_id: str
    principal_roles: tuple[str, ...]
    location: str | None = None
    default_ref: str = "main"
    exposure: str = Exposure.UNKNOWN.value


def parse_repository_change(record: Mapping[str, object]) -> RepositoryChange | None:
    """Return the typed change from an Operator proposal record, or ``None`` if malformed."""
    if record.get("operation") != REPOSITORY_CHANGE_OPERATION:
        return None
    request_id, principal = record.get("proposal_id"), record.get("principal_id")
    envelope = record.get("payload")
    if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
        return None
    if not isinstance(principal, str) or _PRINCIPAL.fullmatch(principal) is None:
        return None
    if not isinstance(envelope, Mapping):
        return None
    body, roles = envelope.get("payload"), envelope.get("principal_roles", ())
    if not isinstance(body, Mapping) or not isinstance(roles, list | tuple):
        return None
    action, alias = body.get("action"), body.get("repository_alias")
    if action not in ACTIONS or not isinstance(alias, str) or _ALIAS.fullmatch(alias) is None:
        return None
    if action != "register":
        if set(body) != {"action", "repository_alias"}:
            return None
        return RepositoryChange(
            request_id, str(action), alias, principal, tuple(str(role) for role in roles)
        )
    if set(body) - {"action", "repository_alias", "location", "default_ref", "exposure"}:
        return None
    location = body.get("location")
    default_ref = body.get("default_ref", "main")
    exposure = body.get("exposure", Exposure.UNKNOWN.value)
    if not isinstance(location, str) or _LOCATION.fullmatch(location) is None:
        return None
    if not isinstance(default_ref, str) or exposure not in {item.value for item in Exposure}:
        return None
    try:
        validate_ref(default_ref)
    except CodeSecurityRepositoryError:
        return None
    return RepositoryChange(
        request_id,
        "register",
        alias,
        principal,
        tuple(str(role) for role in roles),
        location=location,
        default_ref=default_ref,
        exposure=str(exposure),
    )


async def apply_repository_change(
    store: StateStore, change: RepositoryChange
) -> tuple[dict[str, object] | None, str | None]:
    """Apply one change; return ``(result, None)`` or ``(None, rejection_reason)``."""
    if not CHANGE_ROLES & set(change.principal_roles):
        return None, REJECT_ROLE
    try:
        if change.action == "register":
            repository, created = await register_repository(
                store,
                alias=change.repository_alias,
                location=str(change.location),
                default_ref=change.default_ref,
                exposure=Exposure(change.exposure),
                registered_by=change.principal_id,
            )
            return {
                "action": "register",
                "repository_alias": repository.repository_alias,
                "enabled": repository.enabled,
                "created": created,
            }, None
        repository = await set_repository_enabled(
            store,
            change.repository_alias,
            enabled=change.action == "enable",
            actor=change.principal_id,
        )
    except CodeSecurityRepositoryNotFoundError:
        return None, REJECT_UNREGISTERED
    except CodeSecurityRepositoryError:
        return None, REJECT_REPOSITORY_CONFLICT
    return {
        "action": change.action,
        "repository_alias": repository.repository_alias,
        "enabled": repository.enabled,
        "created": False,
    }, None


__all__ = [
    "ACTIONS",
    "CHANGE_ROLES",
    "REJECT_REPOSITORY_CONFLICT",
    "REPOSITORY_CHANGE_OPERATION",
    "RepositoryChange",
    "apply_repository_change",
    "parse_repository_change",
]
