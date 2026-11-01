"""Stewardship GitOps Terraform input defaults."""

from __future__ import annotations

import copy
from typing import Any


def stewardship_gitops_binding(binding: dict[str, Any] | None, *, service: str) -> dict[str, Any]:
    """Return defaulted stewardship GitOps tfvars for services that support them."""
    if not isinstance(service, str) or not service.strip():
        raise ValueError("stewardship_gitops_binding service MUST be a non-empty string")
    if binding is not None and not isinstance(binding, dict):
        raise ValueError("stewardship_gitops_binding binding MUST be a dict when provided")
    if not binding:
        return {}
    materialized = copy.deepcopy(binding)
    if isinstance(materialized.get("auth_mode"), str):
        materialized["auth_mode"] = materialized["auth_mode"].strip()
    if materialized.get("auth_mode") == "console":
        if service == "document-ingestion-api":
            return {}
        return {
            "enabled": bool(materialized.get("enabled", True)),
            "auth_mode": "console",
            "owner": "",
            "repo": "",
            "token_secret_id": "",
            "app_client_id": "",
            "app_installation_id": "",
            "app_private_key_secret_id": "",
            "webhook_secret_id": "",
        }
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
