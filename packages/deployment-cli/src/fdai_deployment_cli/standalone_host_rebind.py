"""Retained managed-host input rebind operations."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from fdai_deployment_cli import standalone_planned_outputs, standalone_terraform_environment
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.private_output import write_private_output
from fdai_deployment_cli.standalone_host_state import private_json, replace_private_json
from fdai_deployment_cli.standalone_license_installation import aks_license_environment
from fdai_deployment_cli.standalone_stage_targets import (
    focused_private_access,
    reconcile_retained_private_access,
)

ManagedIdentityLogin = Callable[[dict[str, object], Path], None]
_DEFAULT_SUBPROCESS_RUN = subprocess.run


def reconcile_retained_aks_license_binding(
    retained_values: dict[str, object],
    current_values: dict[str, object],
) -> bool:
    """Admit only the first verified license binding into a retained Core workload."""
    retained_workloads = retained_values.get("workloads")
    current_workloads = current_values.get("workloads")
    if not isinstance(retained_workloads, dict) or not isinstance(current_workloads, dict):
        raise TypeError("retained AKS workload inventory is invalid")
    retained_core = retained_workloads.get("core-control-plane")
    current_core = current_workloads.get("core-control-plane")
    if not isinstance(retained_core, dict) or not isinstance(current_core, dict):
        raise TypeError("retained Core workload is invalid")
    environment_keys = {"FDAI_LICENSE_IMAGE_DIGEST", "FDAI_LICENSE_TOKEN_REVISION"}
    secret_keys = {"FDAI_LICENSE_TOKEN"}
    changed = False
    for field, allowed in (
        ("environment", environment_keys),
        ("secret_environment", secret_keys),
    ):
        retained = retained_core.get(field)
        current = current_core.get(field)
        if not isinstance(retained, dict) or not isinstance(current, dict):
            raise TypeError("retained Core license binding is invalid")
        previous = {key: retained.get(key) for key in allowed if key in retained}
        selected = {key: current.get(key) for key in allowed if key in current}
        if previous and previous != selected:
            raise ValueError("retained Core license binding differs")
        if not previous and selected:
            retained.update(selected)
            changed = True
    if changed:
        image_digest = retained_core["environment"].get("FDAI_LICENSE_IMAGE_DIGEST")
        revision = retained_core["environment"].get("FDAI_LICENSE_TOKEN_REVISION")
        token_secret = retained_core["secret_environment"].get("FDAI_LICENSE_TOKEN")
        if (
            not isinstance(image_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", image_digest) is None
            or not isinstance(revision, str)
            or re.fullmatch(r"[0-9a-f]{64}", revision) is None
            or token_secret != "fdai-capability-license"
        ):
            raise ValueError("new Core license binding is invalid")
    return changed


def bind_installed_license(
    _args: argparse.Namespace,
    work_dir: Path,
) -> dict[str, object]:
    """Bind an already verified entitlement to the retained Core workload contract."""
    application_values = private_json(
        work_dir / "application.auto.tfvars.json",
        "application variables",
    )
    environment, secrets = aks_license_environment(application_values)
    if not environment or secrets != {"FDAI_LICENSE_TOKEN": "fdai-capability-license"}:
        raise ValueError("verified installed license binding is unavailable")
    workloads_path = work_dir / "workloads.auto.tfvars.json"
    context_path = work_dir / "context.json"
    retained_values = private_json(workloads_path, "AKS workload variables")
    current_values = copy.deepcopy(retained_values)
    current_workloads = current_values.get("workloads")
    if not isinstance(current_workloads, dict):
        raise TypeError("AKS workload inventory is invalid")
    current_core = current_workloads.get("core-control-plane")
    if not isinstance(current_core, dict):
        raise TypeError("Core workload is invalid")
    current_environment = current_core.get("environment")
    current_secrets = current_core.get("secret_environment")
    if not isinstance(current_environment, dict) or not isinstance(current_secrets, dict):
        raise TypeError("Core workload environment is invalid")
    current_environment.update(environment)
    current_secrets.update(secrets)
    changed = reconcile_retained_aks_license_binding(retained_values, current_values)

    context = private_json(context_path, "standalone host context")
    expected = context.get("expected_workloads")
    if not isinstance(expected, dict):
        raise TypeError("expected AKS workload inventory is invalid")
    expected_core = expected.get("core-control-plane")
    if not isinstance(expected_core, dict):
        raise TypeError("expected Core workload is invalid")
    expected_secrets = expected_core.get("secret_environment")
    if not isinstance(expected_secrets, dict):
        raise TypeError("expected Core secret environment is invalid")
    retained_secret = expected_secrets.get("FDAI_LICENSE_TOKEN")
    if retained_secret not in {None, secrets["FDAI_LICENSE_TOKEN"]}:
        raise ValueError("expected Core license binding differs")
    expected_secrets.update(secrets)

    if changed:
        replace_private_json(workloads_path, retained_values)
    replace_private_json(context_path, context)
    receipt: dict[str, object] = {
        "schema_version": "fdai.aks-license-workload-binding.v1",
        "state": "bound",
        "workloads_digest": canonical_digest(retained_values),
        "expected_workloads_digest": canonical_digest(expected),
        "mutation_performed": changed,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    replace_private_json(work_dir / "license-workload-binding-receipt.json", receipt)
    return receipt


def refresh_private_access(
    _args: argparse.Namespace,
    work_dir: Path,
    *,
    login: ManagedIdentityLogin,
) -> dict[str, object]:
    """Refresh only policy-forced private-access selectors after a claimed substrate failure."""
    context_path = work_dir / "context.json"
    variables_path = work_dir / "application.auto.tfvars.json"
    context = private_json(context_path, "standalone host context")
    variables = private_json(variables_path, "standalone host Terraform variables")
    login(context, work_dir)
    key_vault_private_access = (
        standalone_terraform_environment.requires_aks_key_vault_private_access(
            subscription_id=str(context["subscription_id"]),
            resource_group_name=str(context["resource_group_name"]),
            vault_name=str(context["key_vault_name"]),
            work_dir=work_dir,
        )
    )
    document_storage_private_access = (
        standalone_terraform_environment.requires_aks_document_storage_private_access(
            subscription_id=str(context["subscription_id"]),
            resource_group_name=str(context["resource_group_name"]),
            account_name=str(context["document_storage_account_name"]),
            work_dir=work_dir,
        )
    )
    changed = reconcile_retained_private_access(
        context,
        variables,
        key_vault_private_access,
        document_storage_private_access,
    )
    if changed:
        replace_private_json(context_path, context)
        replace_private_json(variables_path, variables)
    return {
        "schema_version": "fdai.standalone-private-access-refresh.v1",
        "state": "refreshed",
        "focused_private_access": focused_private_access(context),
        "mutation_performed": False,
        "subscription_ready": False,
    }


def prepare_managed_identity_login(
    context: dict[str, object],
    work_dir: Path,
    *,
    login: Callable[[str, str, str, str, Path], None],
) -> None:
    standalone_terraform_environment.configure_terraform(context)
    standalone_planned_outputs.bind(
        Path(str(context["infra"])),
        variables=work_dir / "application.auto.tfvars.json",
        data_dir=Path(str(context.get("terraform_data", work_dir / "terraform-data"))),
    )
    sub = str(context["subscription_id"])
    ten = str(context["tenant_id"])
    cid = str(context["client_id"])
    pid = str(context["principal_id"])
    config = work_dir / "azure"
    cache_stamp = config / ".mi-verified.json"
    expected_stamp = {
        "subscription": sub.casefold(),
        "tenant": ten.casefold(),
        "client_id": cid.casefold(),
        "principal_id": pid.casefold(),
    }
    if subprocess.run is _DEFAULT_SUBPROCESS_RUN and (config / "azureProfile.json").is_file():
        try:
            if cache_stamp.is_file() and not cache_stamp.is_symlink():
                cached = json.loads(cache_stamp.read_text(encoding="utf-8"))
                if (
                    isinstance(cached, dict)
                    and cached.get("binding") == expected_stamp
                    and isinstance(cached.get("verified_at"), int | float)
                    and 0 <= time.time() - float(cached["verified_at"]) < 900
                ):
                    os.environ["AZURE_CONFIG_DIR"] = str(config)
                    return
        except (OSError, ValueError):
            pass
    login(sub, ten, cid, pid, work_dir)
    if subprocess.run is _DEFAULT_SUBPROCESS_RUN and config.is_dir():
        try:
            write_private_output(
                cache_stamp,
                json.dumps({"binding": expected_stamp, "verified_at": time.time()}) + "\n",
            )
        except OSError:
            pass


def pending_application_operation(
    context: dict[str, object],
    work_dir: Path,
    *,
    input_rebind_pending: bool,
) -> str | None:
    if (
        input_rebind_pending
        and not (work_dir / "application-input-rebind-update-receipt.json").is_file()
    ):
        return "application-input-rebind-update"
    if (work_dir / "license-application-update-receipt.json").is_file():
        return None
    path = work_dir / "license-workload-binding-receipt.json"
    if not path.is_file() or path.is_symlink():
        return None
    receipt = private_json(path, "license workload binding receipt")
    digest = receipt.pop("receipt_digest", None)
    expected = context.get("expected_workloads")
    workloads = private_json(work_dir / "workloads.auto.tfvars.json", "AKS workload variables")
    if (
        canonical_digest(receipt) != digest
        or receipt.get("schema_version") != "fdai.aks-license-workload-binding.v1"
        or receipt.get("state") != "bound"
        or receipt.get("workloads_digest") != canonical_digest(workloads)
        or not isinstance(expected, dict)
        or receipt.get("expected_workloads_digest") != canonical_digest(expected)
    ):
        raise ValueError("license workload binding receipt is invalid")
    return "license-application-update"
