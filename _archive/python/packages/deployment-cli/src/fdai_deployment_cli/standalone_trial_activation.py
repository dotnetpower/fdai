"""Open the installation's Trial window during deployment, at its anchored creation time.

The window is anchored to the Terraform-recorded first-apply time of the installation,
never to the time of this run, so a rerun, an upgrade, or a recreated record cannot
renew it. The Core writer keeps a retained record unchanged and refuses one bound to
another installation; this step only supplies the bindings and records the outcome.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fdai_deployment_cli import standalone_planned_outputs
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.standalone_host_state import private_json, replace_private_json
from fdai_deployment_cli.standalone_host_values import vault_name

_SCHEMA = "fdai.standalone-trial-activation-receipt.v1"
_WRITER_SCHEMA = "fdai.trial-activation.v1"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_RUNTIME_NAME = re.compile(r"[a-z][a-z0-9-]{1,62}")


def deployment_binding_digest(context: dict[str, Any], runtime_name: str) -> str:
    """Bind one deployment to its tenant, subscription, and runtime without naming them."""

    if _RUNTIME_NAME.fullmatch(runtime_name) is None:
        raise ValueError("Terraform runtime name is invalid")
    material = f"{context['tenant_id']}\0{context['subscription_id']}\0{runtime_name}"
    return hashlib.sha256(material.encode()).hexdigest()


def activate_trial(
    context: dict[str, Any],
    work_dir: Path,
    *,
    login: Callable[[dict[str, object], Path], None],
) -> dict[str, object]:
    """Run the Core writer once and persist a sanitized, digest-bound receipt."""

    receipt_path = work_dir / "trial-activation-receipt.json"
    if receipt_path.exists():
        return require_trial_activation_receipt(
            private_json(receipt_path, "standalone Trial activation receipt")
        )
    if not all(
        (work_dir / name).is_file()
        for name in ("migration-receipt.json", "application-receipt.json")
    ):
        raise ValueError("Trial activation requires the migrated and applied application")
    deployment_binding = str(context.get("deployment_binding", ""))
    if _DIGEST.fullmatch(deployment_binding) is None:
        raise ValueError("Trial activation requires the prepared deployment binding")
    login(context, work_dir)
    infra = Path(str(context["infra"]))
    installation_binding = _output(infra, "installation_binding")
    if _DIGEST.fullmatch(installation_binding) is None:
        raise ValueError("Terraform installation binding is invalid")
    activated_at = _output(infra, "installation_created_at")
    bundle = infra.parent
    result = subprocess.run(
        (
            str(work_dir / "runtime-venv/bin/python"),
            "-m",
            "fdai.runtime.licensing_trial_activation",
            "--installation-binding",
            installation_binding,
            "--deployment-binding",
            deployment_binding,
            "--activated-at",
            activated_at,
        ),
        cwd=bundle,
        env={
            **os.environ,
            "FDAI_STATE_STORE_DSN": _state_store_dsn(infra, work_dir),
            "PYTHONPATH": os.pathsep.join(
                (
                    str(bundle / "services/core-control-plane/src"),
                    str(bundle / "packages/service-contracts/src"),
                )
            ),
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise ValueError("Trial activation failed")
    window = _writer_result(result.stdout)
    receipt: dict[str, object] = {
        "schema_version": _SCHEMA,
        "state": "activated",
        "activated_at": window["activated_at"],
        "expires_at": window["expires_at"],
        "window_ended": window["window_ended"],
        "clock_blocked": window["clock_blocked"],
        "effect_verified": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    replace_private_json(receipt_path, receipt)
    return receipt


def require_trial_activation_receipt(value: dict[str, Any]) -> dict[str, Any]:
    """Accept only a digest-bound receipt for a committed, read-back Trial window."""

    material = {key: item for key, item in value.items() if key != "receipt_digest"}
    if (
        value.get("receipt_digest") != canonical_digest(material)
        or value.get("schema_version") != _SCHEMA
        or value.get("state") != "activated"
        or not isinstance(value.get("activated_at"), str)
        or not isinstance(value.get("expires_at"), str)
        or type(value.get("window_ended")) is not bool
        or type(value.get("clock_blocked")) is not bool
        or value.get("effect_verified") is not True
        or value.get("mutation_performed") is not True
        or value.get("subscription_ready") is not False
    ):
        raise ValueError("standalone Trial activation receipt is invalid")
    return value


def _writer_result(stdout: str) -> dict[str, Any]:
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise ValueError("Trial activation result is invalid") from error
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != _WRITER_SCHEMA
        or value.get("outcome") != "retained"
        or not isinstance(value.get("activated_at"), str)
        or not isinstance(value.get("expires_at"), str)
        or type(value.get("window_ended")) is not bool
        or type(value.get("clock_blocked")) is not bool
    ):
        raise ValueError("Trial activation result is invalid")
    return value


def _state_store_dsn(infra: Path, work_dir: Path) -> str:
    result = subprocess.run(
        (
            "az",
            "keyvault",
            "secret",
            "show",
            "--vault-name",
            vault_name(_output(infra, "key_vault_uri")),
            "--name",
            "fdai-state-store-dsn",
            "--query",
            "value",
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        cwd=work_dir,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    dsn = result.stdout.strip() if result.returncode == 0 else ""
    if not dsn or any(character in dsn for character in "\r\n"):
        raise ValueError("Trial activation database reference is unavailable")
    return dsn


def _output(infra: Path, name: str) -> str:
    value = standalone_planned_outputs.read_output(
        infra, name, raw=True, reason="Terraform output readback failed"
    )
    return str(value)


__all__ = [
    "activate_trial",
    "deployment_binding_digest",
    "require_trial_activation_receipt",
]
