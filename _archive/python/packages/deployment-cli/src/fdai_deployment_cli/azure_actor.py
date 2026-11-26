"""Bind exact-plan approval to the current authenticated Azure human."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable

from fdai_deployment_cli.target import (
    azure_target_selection_arguments,
    compute_target_binding,
    require_selected_azure_target,
)


def actor_digest(
    target_binding: str,
    *,
    timeout_seconds: int = 60,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    result = runner(
        (
            "az",
            "account",
            "show",
            *azure_target_selection_arguments(),
            "--query",
            "{subscription_id:id,tenant_id:tenantId,user_name:user.name,user_type:user.type}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("authenticated Azure approval actor is unavailable") from exc
    if not isinstance(value, dict) or result.returncode != 0 or value.get("user_type") != "user":
        raise ValueError("authenticated Azure approval actor is unavailable")
    subscription = value.get("subscription_id")
    tenant = value.get("tenant_id")
    login = value.get("user_name")
    if (
        not isinstance(subscription, str)
        or not isinstance(tenant, str)
        or not isinstance(login, str)
        or not login.strip()
        or compute_target_binding(tenant_id=tenant, subscription_id=subscription) != target_binding
    ):
        raise ValueError("active Azure target does not match the approved plan")
    require_selected_azure_target(subscription_id=subscription, tenant_id=tenant)
    return hashlib.sha256(f"{target_binding}:{login.casefold()}".encode()).hexdigest()


__all__ = ["actor_digest"]
