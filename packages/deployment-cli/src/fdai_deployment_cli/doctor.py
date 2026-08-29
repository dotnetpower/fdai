"""Read-only local deployment prerequisite inspection."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

from fdai_deployment_cli.target import compute_target_binding


@dataclass(frozen=True, slots=True)
class ToolCheck:
    """One non-secret tool availability result."""

    name: str
    available: bool
    version: str | None


def inspect_tools(names: tuple[str, ...] = ("az", "terraform", "gh")) -> tuple[ToolCheck, ...]:
    """Inspect required executables without installing or authenticating."""

    results: list[ToolCheck] = []
    for name in names:
        executable = shutil.which(name)
        if executable is None:
            results.append(ToolCheck(name=name, available=False, version=None))
            continue
        completed = subprocess.run(
            [executable, "version" if name == "terraform" else "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = (completed.stdout or completed.stderr).splitlines()
        version = output[0][:256] if completed.returncode == 0 and output else None
        results.append(ToolCheck(name=name, available=completed.returncode == 0, version=version))
    return tuple(results)


def doctor_json(
    checks: tuple[ToolCheck, ...],
    *,
    azure_authenticated: bool,
) -> str:
    """Return stable doctor output."""

    return json.dumps(
        {
            "schema_version": "fdai.doctor.v1",
            "ready": all(check.available for check in checks) and azure_authenticated,
            "azure_authenticated": azure_authenticated,
            "reason_codes": ([] if azure_authenticated else ["azure_authentication_missing"]),
            "mutation_performed": False,
            "tools": [
                {
                    "name": check.name,
                    "available": check.available,
                    "version": check.version,
                }
                for check in checks
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def azure_cli_authenticated() -> bool:
    """Return whether Azure CLI has one active account without exposing its identifiers."""

    executable = shutil.which("az")
    if executable is None:
        return False
    try:
        completed = subprocess.run(
            [
                executable,
                "account",
                "show",
                "--output",
                "none",
                "--only-show-errors",
            ],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def azure_active_target_binding() -> str | None:
    """Return a digest of the active tenant and subscription, never their raw values."""

    executable = shutil.which("az")
    if executable is None:
        return None
    try:
        completed = subprocess.run(
            [
                executable,
                "account",
                "show",
                "--query",
                "{subscription:id,tenant:tenantId}",
                "--output",
                "json",
                "--only-show-errors",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if completed.returncode != 0:
            return None
        value = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    subscription = value.get("subscription")
    tenant = value.get("tenant")
    if not isinstance(subscription, str) or not isinstance(tenant, str):
        return None
    try:
        return compute_target_binding(tenant_id=tenant, subscription_id=subscription)
    except ValueError:
        return None
