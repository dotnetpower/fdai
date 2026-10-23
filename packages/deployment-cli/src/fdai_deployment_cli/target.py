"""Canonical secret-free Azure target binding."""

from __future__ import annotations

import hashlib
import os
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


def azure_target_selection_arguments() -> tuple[str, ...]:
    """Pin Azure CLI reads when the caller selected one explicit subscription."""

    subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "").strip()
    if not subscription_id:
        return ()
    if _GUID.fullmatch(subscription_id) is None:
        raise ValueError("AZURE_SUBSCRIPTION_ID MUST be a GUID")
    return ("--subscription", subscription_id)


def require_selected_azure_target(*, subscription_id: str, tenant_id: str) -> None:
    """Reject an Azure CLI result that differs from explicit non-secret target inputs."""

    selected_subscription = os.environ.get("AZURE_SUBSCRIPTION_ID", "").strip()
    selected_tenant = os.environ.get("AZURE_TENANT_ID", "").strip()
    if selected_subscription and selected_subscription.casefold() != subscription_id.casefold():
        raise ValueError("active Azure subscription differs from AZURE_SUBSCRIPTION_ID")
    if selected_tenant:
        if _GUID.fullmatch(selected_tenant) is None:
            raise ValueError("AZURE_TENANT_ID MUST be a GUID")
        if selected_tenant.casefold() != tenant_id.casefold():
            raise ValueError("active Azure tenant differs from AZURE_TENANT_ID")
