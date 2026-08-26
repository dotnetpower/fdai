"""Content-free privacy admission for model-produced external queries."""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlsplit
from uuid import UUID

from fdai.rule_catalog.pipeline.distill.sensitivity import scan_text

_EDGE_CHARACTERS = "\"'`.,;:!?()[]{}<>"


class DeterministicExternalQueryPrivacyVerifier:
    """Reject secrets, PII, private addresses, UUIDs, and ARM resource IDs."""

    def is_safe(self, query: str) -> bool:
        if scan_text(query):
            return False
        return not any(_structured_identifier(token) for token in query.split())


def _structured_identifier(raw: str) -> bool:
    token = raw.strip(_EDGE_CHARACTERS)
    if not token:
        return False
    if _arm_resource_id(token):
        return True
    parsed = urlsplit(token)
    if parsed.scheme and parsed.hostname and _is_private_address(parsed.hostname):
        return True
    try:
        identifier = UUID(token)
    except ValueError:
        pass
    else:
        if identifier.int != 0:
            return True
    return _is_private_address(token.strip("/"))


def _is_private_address(value: str) -> bool:
    try:
        address = ip_address(value)
    except ValueError:
        return False
    return address.is_private or address.is_link_local or address.is_reserved


def _arm_resource_id(value: str) -> bool:
    parts = value.strip("/").split("/")
    if len(parts) < 8:
        return False
    lowered = tuple(part.casefold() for part in parts)
    if lowered[0] != "subscriptions" or lowered[2] != "resourcegroups":
        return False
    if lowered[4] != "providers":
        return False
    try:
        UUID(parts[1])
    except ValueError:
        return False
    return all(parts[index] for index in (3, 5, 6, 7))


__all__ = ["DeterministicExternalQueryPrivacyVerifier"]
