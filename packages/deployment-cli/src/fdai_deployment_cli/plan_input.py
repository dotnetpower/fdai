"""Private, non-secret Terraform plan input snapshot."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_bytes, load_json_object

PLAN_ONLY_PASSWORD = "FDAI-PLAN-ONLY-NOT-A-SECRET"
_REQUIRED = frozenset(
    {"region", "tenant_id", "postgres_admin_login", "postgres_admin_password", "core_image"}
)
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


def snapshot_plan_input(source: Path, destination: Path) -> None:
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
    output = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(output, "wb") as stream:
        stream.write(canonical_bytes(values) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
