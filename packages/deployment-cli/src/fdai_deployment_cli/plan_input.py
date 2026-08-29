"""Private, non-secret Terraform plan input snapshot."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_bytes, load_json_object
from fdai_deployment_cli.target import compute_target_binding

PLAN_ONLY_PASSWORD = "FDAI-PLAN-ONLY-NOT-A-SECRET"
_REQUIRED = frozenset(
    {
        "region",
        "tenant_id",
        "subscription_id",
        "target_binding",
        "postgres_admin_login",
        "postgres_admin_password",
        "core_image",
    }
)
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


@dataclass(frozen=True, slots=True)
class PlanInputContext:
    """Validated provider context removed from Terraform variable content."""

    subscription_id: str


def snapshot_plan_input(
    source: Path,
    destination: Path,
    *,
    expected_target_binding: str,
    expected_region: str,
) -> PlanInputContext:
    """Validate and copy a mode-0600 JSON plan input without real secret values."""

    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) != 0o600:
            raise PermissionError("Terraform plan input MUST be a mode-0600 regular file")
        payload = stream.read(1_048_577)
    values = load_json_object(payload, label="Terraform plan input")
    if set(values) != _REQUIRED:
        raise ValueError("Terraform plan input fields do not match the secret-free schema")
    if any(_KEY.fullmatch(key) is None for key in values):
        raise ValueError("Terraform plan input contains an invalid key")
    if values["postgres_admin_password"] != PLAN_ONLY_PASSWORD:
        raise ValueError("Terraform plan input MUST use the plan-only password placeholder")
    tenant_id = values["tenant_id"]
    subscription_id = values["subscription_id"]
    if not isinstance(tenant_id, str) or not isinstance(subscription_id, str):
        raise ValueError("Terraform plan input Azure target values MUST be strings")
    derived_binding = compute_target_binding(
        tenant_id=tenant_id,
        subscription_id=subscription_id,
    )
    if values["target_binding"] != derived_binding or derived_binding != expected_target_binding:
        raise ValueError("Terraform plan input target binding does not match the profile")
    if values["region"] != expected_region:
        raise ValueError("Terraform plan input region does not match the profile")
    terraform_values = {
        key: value
        for key, value in values.items()
        if key not in {"target_binding", "subscription_id"}
    }
    output = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(output, "wb") as stream:
        stream.write(canonical_bytes(terraform_values) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    return PlanInputContext(subscription_id=subscription_id)
