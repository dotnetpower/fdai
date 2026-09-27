"""AKS initial-inventory execution and independent closure for standalone deployment."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.standalone_aks_job_execution import execute_aks_cronjob_once
from fdai_deployment_cli.standalone_host_state import replace_private_json
from fdai_deployment_cli.standalone_host_values import vault_name

_GUID = re.compile(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
_CLOSURE_CLOCK_SKEW = timedelta(seconds=60)
_INITIAL_INVENTORY_SOURCES = ("arg", "arm")


def initial_inventory_binding(subscription_id: str) -> dict[str, object]:
    """Return the protected full-subscription source and filter contract."""

    if _GUID.fullmatch(subscription_id) is None:
        raise ValueError("initial inventory subscription binding is invalid")
    scope = f"/subscriptions/{subscription_id.casefold()}"
    material: dict[str, object] = {
        "schema_version": "fdai.initial-inventory-binding.v1",
        "scope_digest": "sha256:" + hashlib.sha256(scope.encode()).hexdigest(),
        "sources": list(_INITIAL_INVENTORY_SOURCES),
        "resource_types": [],
    }
    return {**material, "binding_digest": canonical_digest(material)}


def run_initial_aks_inventory(
    context: dict[str, Any],
    work_dir: Path,
    *,
    receipt_path: Path,
) -> dict[str, object]:
    """Run the exact CronJob template and independently verify its active generation."""

    source_revision = str(context.get("source_commit", ""))
    target_binding = str(context.get("target_binding", ""))
    binding = _validated_initial_inventory_binding(context)
    sources = binding["sources"]
    if not isinstance(sources, list):
        raise ValueError("initial inventory source binding is invalid")
    progress_url = str(context.get("inventory_progress_container_url", ""))
    if not progress_url.startswith("https://"):
        raise ValueError("initial inventory progress endpoint is invalid")
    image_refs = _mapping(context.get("image_refs"), "runtime image references")
    core_image = str(image_refs.get("core-control-plane", ""))
    run_id = f"genesis.{source_revision}"
    attempt_id = (
        "attempt."
        + hashlib.sha256(
            f"{source_revision}:{target_binding}:initial-inventory".encode()
        ).hexdigest()[:32]
    )
    execution = execute_aks_cronjob_once(
        context,
        work_dir,
        template_name="inventory",
        purpose="inventory",
        expected_container_name="inventory",
        expected_image=core_image,
        expected_command=("python", "-m", "fdai.delivery.inventory_sync_cli"),
        expected_service_account="inventory-job",
        args=("--initial",),
        environment={
            "FDAI_INVENTORY_RESOURCE_TYPES": "",
            "FDAI_INVENTORY_SCOPES": str(context["subscription_id"]),
            "FDAI_INVENTORY_SOURCES": ",".join(str(source) for source in sources),
            "FDAI_INVENTORY_PROGRESS_ATTEMPT_ID": attempt_id,
            "FDAI_INVENTORY_PROGRESS_CONTAINER_URL": progress_url,
            "FDAI_INVENTORY_PROGRESS_RUN_ID": run_id,
        },
        require_suspended=False,
        timeout_seconds=960,
    )
    infra = Path(str(context["infra"]))
    bundle = infra.parent
    key_vault_name = vault_name(_terraform_output(infra, "key_vault_uri"))
    dsn = _capture(
        (
            "az",
            "keyvault",
            "secret",
            "show",
            "--vault-name",
            key_vault_name,
            "--name",
            "fdai-state-store-dsn",
            "--query",
            "value",
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        cwd=work_dir,
        timeout=120,
        reason="initial inventory database reference is unavailable",
    ).strip()
    if not dsn or any(character in dsn for character in "\r\n"):
        raise ValueError("initial inventory database reference is invalid")
    runtime_python = work_dir / "runtime-venv/bin/python"
    closure_environment = {
        **os.environ,
        "AZURE_CLIENT_ID": str(context["client_id"]),
        "FDAI_MI_CLIENT_ID": str(context["client_id"]),
        "FDAI_EXECUTION_VENUE": "deployed",
        "FDAI_INVENTORY_DSN": dsn,
        "FDAI_INVENTORY_EXPECTED_SCOPE_DIGEST": str(binding["scope_digest"]),
        "FDAI_INVENTORY_RESOURCE_TYPES": "",
        "FDAI_INVENTORY_SCOPES": str(context["subscription_id"]),
        "FDAI_INVENTORY_SOURCES": ",".join(str(source) for source in sources),
        "FDAI_INVENTORY_PROGRESS_CONTAINER_URL": progress_url,
        "FDAI_INVENTORY_PROGRESS_RUN_ID": run_id,
        "FDAI_INVENTORY_PROGRESS_ATTEMPT_ID": attempt_id,
        "PYTHONPATH": os.pathsep.join(
            (
                str(bundle / "services/core-control-plane/src"),
                str(bundle / "packages/service-contracts/src"),
            )
        ),
    }
    closure_started_at = datetime.now(tz=UTC)
    closure = _verified_closure(
        _capture_env(
            (str(runtime_python), "-m", "fdai.delivery.inventory_closure_cli"),
            cwd=bundle,
            env=closure_environment,
            timeout=300,
            reason="initial inventory independent closure failed",
        ),
        expected_attempt_id=attempt_id,
        expected_run_id=run_id,
        expected_scope_digest=str(binding["scope_digest"]),
        observed_after=closure_started_at,
    )
    closure_environment["FDAI_INVENTORY_DSN"] = ""
    receipt: dict[str, object] = {
        "schema_version": "fdai.standalone-aks-initial-inventory-receipt.v1",
        "state": "inventory-verified",
        "source_revision": source_revision,
        "run_id": run_id,
        "attempt_id": attempt_id,
        "execution_ref_digest": hashlib.sha256(execution.name.encode()).hexdigest(),
        "execution_template_digest": execution.execution_digest,
        "execution_observer": "kubernetes-job",
        "inventory_binding_digest": binding["binding_digest"],
        "scope_digest": closure["scope_digest"],
        "sources": list(sources),
        "full_subscription": closure["subscription_root"],
        "resource_type_filter": closure["resource_type_filter"],
        "progress_persisted": True,
        "complete_generation_readback_verified": True,
        "active_generation_readback_verified": True,
        "generation_digest": closure["generation_digest"],
        "fresh_generation": closure["fresh_generation"],
        "freshness_observed_at": closure["observed_at"],
        "resource_count": closure["resource_count"],
        "link_count": closure["link_count"],
        "unmapped_object_count": closure["unmapped_object_count"],
        "coverage_gap_count": closure["coverage_gap_count"],
        "closure_receipt_digest": closure["receipt_digest"],
        "closure_receipt_verified": True,
        "effect_verified": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    replace_private_json(receipt_path, receipt)
    return receipt


def require_initial_inventory_receipt(
    value: dict[str, Any],
    *,
    runtime_platform: str,
) -> None:
    """Require AKS complete-generation evidence without changing Container Apps."""

    if (
        value.get("state") != "inventory-verified"
        or value.get("active_generation_readback_verified") is not True
        or value.get("progress_persisted") is not True
    ):
        raise ValueError("standalone initial inventory is incomplete")
    if runtime_platform != "aks":
        return
    receipt = {str(key): item for key, item in value.items()}
    supplied_digest = receipt.pop("receipt_digest", None)
    if (
        supplied_digest != canonical_digest(receipt)
        or receipt.get("complete_generation_readback_verified") is not True
        or receipt.get("fresh_generation") is not True
        or receipt.get("closure_receipt_verified") is not True
        or receipt.get("sources") != list(_INITIAL_INVENTORY_SOURCES)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", str(receipt.get("scope_digest", ""))) is None
        or re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            str(receipt.get("closure_receipt_digest", "")),
        )
        is None
        or re.fullmatch(
            r"[0-9a-f]{64}",
            str(receipt.get("inventory_binding_digest", "")),
        )
        is None
        or not _coverage_counts_are_valid(receipt)
        or _parse_observed_at(receipt.get("freshness_observed_at")) is None
    ):
        raise ValueError("standalone initial inventory is incomplete")


def _verified_closure(
    raw: str,
    *,
    expected_attempt_id: str,
    expected_run_id: str,
    expected_scope_digest: str,
    observed_after: datetime,
) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("initial inventory closure receipt is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("initial inventory closure receipt is invalid")
    required_true = (
        "subscription_root",
        "final_fence",
        "provider_coverage_complete",
        "active_generation_matches",
        "child_sources_complete",
        "fresh_generation",
        "observer_distinct",
    )
    observed_at = _parse_observed_at(value.get("observed_at"))
    supplied_digest = value.get("receipt_digest")
    receipt_material = {str(key): item for key, item in value.items() if key != "receipt_digest"}
    if (
        value.get("schema_version") != "1.0.0"
        or value.get("run_id") != expected_run_id
        or value.get("attempt_id") != expected_attempt_id
        or value.get("scope_digest") != expected_scope_digest
        or any(value.get(name) is not True for name in required_true)
        or value.get("resource_type_filter") is not False
        or value.get("truncated") is not False
        or value.get("overlay_open") is not False
        or value.get("execution_authority") is not False
        or not _coverage_counts_are_valid(value)
        or observed_at is None
        or observed_at < observed_after - _CLOSURE_CLOCK_SKEW
        or observed_at > datetime.now(tz=UTC) + _CLOSURE_CLOCK_SKEW
        or re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("generation_digest", ""))) is None
        or supplied_digest != _closure_receipt_digest(receipt_material)
    ):
        raise ValueError("initial inventory closure receipt is incomplete")
    return {str(key): item for key, item in value.items()}


def _validated_initial_inventory_binding(context: dict[str, Any]) -> dict[str, object]:
    subscription_id = str(context.get("subscription_id", ""))
    expected = initial_inventory_binding(subscription_id)
    supplied = context.get("initial_inventory_binding")
    if supplied != expected:
        raise ValueError("initial inventory protected binding differs")
    return expected


def _coverage_counts_are_valid(value: dict[str, Any]) -> bool:
    return all(
        isinstance(value.get(name), int)
        and not isinstance(value.get(name), bool)
        and int(value[name]) >= 0
        for name in (
            "resource_count",
            "link_count",
            "unmapped_object_count",
            "coverage_gap_count",
        )
    )


def _parse_observed_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _closure_receipt_digest(value: dict[str, object]) -> str:
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _terraform_output(infra: Path, name: str) -> str:
    return _capture(
        ("terraform", "output", "-raw", name),
        cwd=infra,
        timeout=120,
        reason="Terraform output readback failed",
    ).strip()


def _capture(command: tuple[str, ...], *, cwd: Path, timeout: int, reason: str) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise ValueError(reason)
    return result.stdout


def _capture_env(
    command: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    reason: str,
) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise ValueError(reason)
    return result.stdout


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} is invalid")
    return {str(key): item for key, item in value.items()}


__all__ = [
    "initial_inventory_binding",
    "require_initial_inventory_receipt",
    "run_initial_aks_inventory",
]
