"""Wait for the managed host's selected private application data planes."""

from __future__ import annotations

import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

_RESOURCE_NAME = re.compile(r"[a-z0-9-]{3,63}")


def wait_for_private_data_planes(
    *,
    context: dict[str, object],
    work_dir: Path,
    timeout_seconds: float = 600,
    interval_seconds: float = 15,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    """Require Key Vault and Data Lake access before a residual can consume authority."""

    vault = _name(context, "key_vault_name")
    storage = _name(context, "document_storage_account_name")
    if (
        context.get("key_vault_private_access") is not True
        or context.get("document_storage_private_access") is not True
        or timeout_seconds <= 0
        or interval_seconds <= 0
    ):
        raise ValueError("private application data-plane probe context is invalid")
    commands = (
        (
            "az",
            "keyvault",
            "secret",
            "list",
            "--vault-name",
            vault,
            "--query",
            "length(@)",
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        (
            "az",
            "storage",
            "fs",
            "list",
            "--account-name",
            storage,
            "--auth-mode",
            "login",
            "--query",
            "length(@)",
            "--output",
            "tsv",
            "--only-show-errors",
        ),
    )
    deadline = clock() + timeout_seconds
    attempts = 0
    while True:
        attempts += 1
        results = [
            run(
                command,
                cwd=work_dir,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            for command in commands
        ]
        if all(result.returncode == 0 and result.stdout.strip().isdigit() for result in results):
            return {
                "schema_version": "fdai.private-data-plane-probe.v1",
                "state": "ready",
                "key_vault_verified": True,
                "document_storage_verified": True,
                "attempts": attempts,
                "mutation_performed": False,
                "subscription_ready": False,
            }
        remaining = deadline - clock()
        if remaining <= 0:
            raise ValueError("private application data planes did not become ready")
        sleep(min(interval_seconds, remaining))


def _name(context: dict[str, object], field: str) -> str:
    value = context.get(field)
    if not isinstance(value, str) or _RESOURCE_NAME.fullmatch(value) is None:
        raise ValueError("private application data-plane resource name is invalid")
    return value
