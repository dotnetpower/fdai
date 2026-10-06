"""Stewardship GitOps Terraform input defaults."""

from __future__ import annotations

import copy
from typing import Any


def stewardship_gitops_binding(binding: dict[str, Any] | None, *, service: str) -> dict[str, Any]:
    """Return defaulted stewardship GitOps tfvars for services that support them."""

    if not binding:
        return {}
    materialized = copy.deepcopy(binding)
    if "auth_mode" in materialized:
        return materialized
    if service == "document-ingestion-api":
        return {}
    materialized.update(
        {
            "auth_mode": "static_token",
            "app_client_id": "",
            "app_installation_id": "",
            "app_private_key_secret_id": "",
            "webhook_secret_id": "",
        }
    )
    return materialized
