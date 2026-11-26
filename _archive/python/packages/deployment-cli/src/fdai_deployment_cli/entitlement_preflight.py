"""Workstation checks that run before the first Azure call of a deployment."""

from __future__ import annotations

import shutil
import subprocess
import sys

from fdai_deployment_cli.license_issue import discover_license_signing_key

_TRIAL = "trial"
_KEY_HOLDER = "key-holder"
_DESCRIPTIONS = {
    _TRIAL: "30-day Trial (no secrets/integrity-signing-key.pem)",
    _KEY_HOLDER: "key holder (secrets/integrity-signing-key.pem)",
}


def select_entitlement_mode() -> str:
    """Return the entitlement mode, stopping on a present but unusable key.

    The decision reads only the working checkout's fixed integrity key, so it
    needs no Azure access and runs before any.
    """

    try:
        key = discover_license_signing_key()
    except (OSError, ValueError) as exc:
        raise ValueError(
            "secrets/integrity-signing-key.pem is present but unusable "
            f"({exc}); fix its custody or remove it to deploy the 30-day Trial"
        ) from None
    return _TRIAL if key is None else _KEY_HOLDER


def describe_entitlement_mode(mode: str) -> str:
    """Return the operator-facing description of one entitlement mode."""

    return _DESCRIPTIONS[mode]


def ensure_azure_session(*, timeout_seconds: int = 900) -> None:
    """Start the interactive Azure CLI login when no session exists."""

    azure_cli = shutil.which("az")
    if azure_cli is None:
        raise ValueError("the Azure CLI (az) is required")
    probe = subprocess.run(  # noqa: S603 - resolved Azure CLI with fixed arguments
        (azure_cli, "account", "show", "--only-show-errors", "--output", "none"),
        capture_output=True,
        check=False,
        timeout=60,
    )
    if probe.returncode == 0:
        return
    if not sys.stdin.isatty():
        raise ValueError("no Azure CLI session; run az login first")
    print("fdaictl: no Azure CLI session; starting az login", file=sys.stderr)
    login = subprocess.run(  # noqa: S603 - resolved Azure CLI with fixed arguments
        (azure_cli, "login", "--only-show-errors", "--output", "none"),
        check=False,
        timeout=timeout_seconds,
    )
    if login.returncode != 0:
        raise ValueError("az login did not complete; no deployment was performed")


__all__ = ["describe_entitlement_mode", "ensure_azure_session", "select_entitlement_mode"]
