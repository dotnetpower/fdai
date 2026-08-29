"""Canonical secret-free Azure target binding."""

from __future__ import annotations

import hashlib
import re

_GUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def compute_target_binding(*, tenant_id: str, subscription_id: str) -> str:
    """Bind one concrete tenant and subscription without retaining either value."""

    if _GUID.fullmatch(tenant_id) is None or _GUID.fullmatch(subscription_id) is None:
        raise ValueError("Azure tenant and subscription MUST be GUIDs")
    material = f"{tenant_id.lower()}:{subscription_id.lower()}".encode()
    return hashlib.sha256(material).hexdigest()
