"""Strict parser for the App Service Easy Auth principal header."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from delivery.dev_operations_gateway.gateway import GatewayPrincipal
elif __package__:
    from .gateway import GatewayPrincipal
else:
    from gateway import GatewayPrincipal

_MAX_ENCODED_BYTES = 32_768
_MAX_CLAIMS = 256
_MAX_CLAIM_VALUE = 512
_OBJECT_ID_TYPES = {
    "oid",
    "http://schemas.microsoft.com/identity/claims/objectidentifier",
}
_GROUP_TYPES = {
    "groups",
    "http://schemas.microsoft.com/ws/2008/06/identity/claims/groups",
}
_ROLE_TYPES = {
    "roles",
    "http://schemas.microsoft.com/ws/2008/06/identity/claims/role",
}


class PrincipalHeaderError(ValueError):
    """The platform-authenticated principal header was malformed."""


def parse_easy_auth_principal(encoded: str) -> GatewayPrincipal:
    if not encoded or len(encoded) > _MAX_ENCODED_BYTES:
        raise PrincipalHeaderError("Easy Auth principal is missing or too large")
    try:
        decoded = base64.b64decode(encoded, validate=True)
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrincipalHeaderError("Easy Auth principal is invalid") from exc
    claims = payload.get("claims") if isinstance(payload, Mapping) else None
    if not isinstance(claims, list) or len(claims) > _MAX_CLAIMS:
        raise PrincipalHeaderError("Easy Auth claims are missing or too large")

    object_id: str | None = None
    groups: set[str] = set()
    roles: set[str] = set()
    recognized_types = _OBJECT_ID_TYPES | _GROUP_TYPES | _ROLE_TYPES
    for claim in claims:
        if not isinstance(claim, Mapping):
            continue
        claim_type = claim.get("typ")
        if not isinstance(claim_type, str) or claim_type not in recognized_types:
            continue
        value = claim.get("val")
        if not isinstance(value, str) or not _bounded_claim(value):
            raise PrincipalHeaderError("Easy Auth security claim value is invalid")
        if claim_type in _OBJECT_ID_TYPES:
            if object_id is not None and object_id != value:
                raise PrincipalHeaderError("Easy Auth object id claims conflict")
            object_id = value
        elif claim_type in _GROUP_TYPES:
            groups.add(value)
        else:
            roles.add(value)
    if object_id is None:
        raise PrincipalHeaderError("Easy Auth object id is missing")
    return GatewayPrincipal(
        object_id=object_id,
        groups=frozenset(groups),
        roles=frozenset(roles),
    )


def _bounded_claim(value: str) -> bool:
    return (
        0 < len(value) <= _MAX_CLAIM_VALUE
        and "\x00" not in value
        and "\r" not in value
        and "\n" not in value
    )


__all__ = ["PrincipalHeaderError", "parse_easy_auth_principal"]
