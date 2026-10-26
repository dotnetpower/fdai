"""Admit one Core source update from a bounded partial AKS application baseline."""

from __future__ import annotations

from pathlib import Path

from fdai_deployment_cli.aks_service_update import (
    service_update_review,
    validated_secret_environment,
    validate_plan_scope,
)
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.standalone_host_state import private_json

_CORE = 'kubernetes_deployment_v1.workload["core-control-plane"]'
_ALLOWED_CHANGES = {
    _CORE: ("delete", "create"),
    'kubernetes_horizontal_pod_autoscaler_v2.workload["core-control-plane"]': ("create",),
    'kubernetes_horizontal_pod_autoscaler_v2.workload["document-ingestion-api"]': ("create",),
    'kubernetes_horizontal_pod_autoscaler_v2.workload["document-processing-worker"]': ("create",),
    'kubernetes_horizontal_pod_autoscaler_v2.workload["operator-service"]': ("create",),
    "module.browser_gateway.azurerm_network_security_rule.browser_gateway[0]": ("create",),
}


def readback_context(
    work_dir: Path,
    context: dict[str, object],
) -> dict[str, object]:
    """Refresh readback-only secret contracts from the exact planned workload variables."""
    values = private_json(work_dir / "workloads.auto.tfvars.json", "AKS workload variables")
    workloads = values.get("workloads")
    expected = context.get("expected_workloads")
    if not isinstance(workloads, dict) or not isinstance(expected, dict):
        raise ValueError("AKS service update workload inventory is invalid")
    if set(workloads) != set(expected):
        raise ValueError("AKS service update workload inventory differs")
    refreshed: dict[str, dict[str, object]] = {}
    for name, contract_value in expected.items():
        workload = workloads.get(name)
        if not isinstance(contract_value, dict) or not isinstance(workload, dict):
            raise ValueError("AKS service update workload contract is invalid")
        contract = dict(contract_value)
        contract["secret_environment"] = validated_secret_environment(
            workload.get("secret_environment", {})
        )
        refreshed[str(name)] = contract
    return {**context, "expected_workloads": refreshed}


def partial_core_update_admissible(
    work_dir: Path,
    context: dict[str, object],
    *,
    service: str | None,
) -> bool:
    """Return whether exact retained recovery evidence permits only a Core image update."""

    if service != "core-control-plane":
        return False
    paths = {
        "original_claim": work_dir / "application-claim.json",
        "residual_review": work_dir / "application-residual-review.json",
        "residual_claim": work_dir / "application-residual-claim.json",
        "successor_review": work_dir / "application-residual-successor-review.json",
        "successor_claim": work_dir / "application-residual-successor-claim.json",
        "rebind_receipt": work_dir / "application-input-rebind-receipt.json",
    }
    if any(not path.is_file() or path.is_symlink() for path in paths.values()):
        return False
    records = {name: private_json(path, name) for name, path in paths.items()}
    original = records["original_claim"]
    residual_review = records["residual_review"]
    residual = records["residual_claim"]
    successor_review = records["successor_review"]
    successor = records["successor_claim"]
    rebind = records["rebind_receipt"]
    binding = successor_review.get("residual_successor")
    summary = successor_review.get("summary")
    changes = summary.get("resource_changes") if isinstance(summary, dict) else None
    observed = (
        {
            str(item.get("address")): tuple(item.get("actions", ()))
            for item in changes
            if isinstance(item, dict) and item.get("actions") != ["no-op"]
        }
        if isinstance(changes, list)
        else {}
    )
    receipt_digest = rebind.pop("receipt_digest", None)
    return (
        original.get("schema_version") == "fdai.standalone-application-claim.v1"
        and original.get("stage") == "application"
        and residual_review.get("schema_version") == "fdai.standalone-application-plan.v1"
        and residual_review.get("stage") == "application"
        and residual.get("schema_version") == "fdai.standalone-residual-claim.v1"
        and residual.get("stage") == "application"
        and successor_review.get("schema_version") == "fdai.standalone-application-plan.v1"
        and successor_review.get("stage") == "application"
        and successor_review.get("source_commit") == context.get("source_commit")
        and isinstance(binding, dict)
        and binding.get("original_claim_digest") == canonical_digest(original)
        and binding.get("residual_plan_digest") == residual_review.get("plan_digest")
        and binding.get("residual_claim_digest") == canonical_digest(residual)
        and successor.get("schema_version") == "fdai.standalone-residual-successor-claim.v1"
        and successor.get("stage") == "application"
        and successor.get("plan_digest") == successor_review.get("plan_digest")
        and successor.get("original_claim_digest") == canonical_digest(original)
        and successor.get("residual_claim_digest") == canonical_digest(residual)
        and canonical_digest(rebind) == receipt_digest
        and rebind.get("schema_version") == "fdai.application-input-rebind-receipt.v1"
        and rebind.get("field") == "browser_gateway.backend_nsg_id"
        and rebind.get("mutation_performed") is True
        and bool(observed)
        and observed.get(_CORE) == ("delete", "create")
        and set(observed).issubset(_ALLOWED_CHANGES)
        and all(observed[address] == _ALLOWED_CHANGES[address] for address in observed)
    )


def validate_service_update_plan(
    summary: dict[str, object],
    work_dir: Path,
    context: dict[str, object],
    update: dict[str, object],
) -> None:
    """Apply the ordinary or recovery-specific selected Deployment scope."""

    service = update.get("service")
    if not isinstance(service, str):
        raise ValueError("AKS service update plan service is invalid")
    validate_plan_scope(
        summary,
        service=service,
        allow_replacement=partial_core_update_admissible(
            work_dir,
            context,
            service=service,
        ),
    )


def failed_core_update_repair_digest(
    work_dir: Path,
    context: dict[str, object],
    *,
    service: str,
) -> str | None:
    """Return one exact failed Core update digest eligible for a single repair."""

    active = context.get("active_service_update")
    operation = active.get("operation") if isinstance(active, dict) else None
    if (
        not isinstance(active, dict)
        or active.get("service") != service
        or not isinstance(operation, str)
    ):
        return None
    record_path = work_dir / f"{operation}.json"
    review_path = work_dir / f"{operation}-review.json"
    claim_path = work_dir / f"{operation}-claim.json"
    receipt_path = work_dir / f"{operation}-receipt.json"
    if (
        any(
            not path.is_file() or path.is_symlink()
            for path in (record_path, review_path, claim_path)
        )
        or receipt_path.exists()
        or receipt_path.is_symlink()
    ):
        return None
    record = private_json(record_path, "failed Core service update")
    review = private_json(review_path, "failed Core service update review")
    claim = private_json(claim_path, "failed Core service update claim")
    digest = record.get("update_digest")
    document = {key: value for key, value in record.items() if key != "update_digest"}
    counts = review.get("summary", {}).get("action_counts")
    baseline = record.get("baseline")
    previous = baseline.get("core-control-plane") if isinstance(baseline, dict) else None
    ordinary_update = (
        isinstance(counts, dict)
        and counts.get("update") == 1
        and counts.get("replace") == 0
        and counts.get("delete") == 0
    )
    partial_replacement = (
        partial_core_update_admissible(work_dir, context, service=service)
        and isinstance(counts, dict)
        and counts.get("replace") == 1
        and counts.get("update") == 0
        and counts.get("delete") == 0
    )
    return (
        str(digest)
        if isinstance(digest, str)
        and active.get("update_digest") == digest
        and digest == canonical_digest(document)
        and record.get("schema_version") == "fdai.aks-service-update.v1"
        and record.get("service") == "core-control-plane"
        and isinstance(previous, dict)
        and previous.get("image") == record.get("previous_image")
        and isinstance(previous.get("source_commit"), str)
        and review.get("service_update") == service_update_review(record)
        and record.get("superseded_update_digest") is None
        and review.get("schema_version") == "fdai.standalone-application-plan.v1"
        and review.get("plan_digest") == claim.get("plan_digest")
        and claim.get("schema_version") == "fdai.standalone-application-claim.v1"
        and claim.get("stage") == "application"
        and (ordinary_update or partial_replacement)
        else None
    )


def superseded_update_digest(
    work_dir: Path,
    context: dict[str, object],
    *,
    service: str,
) -> str | None:
    """Return the one failed update to supersede, or reject an incomplete operation."""

    active = context.get("active_service_update")
    if not isinstance(active, dict):
        return None
    operation = active.get("operation")
    if isinstance(operation, str) and (work_dir / f"{operation}-receipt.json").is_file():
        return None
    digest = failed_core_update_repair_digest(work_dir, context, service=service)
    if digest is None:
        raise ValueError("AKS service update already has an incomplete active operation")
    return digest


def validate_repair_binding(record: dict[str, object]) -> None:
    """Require any optional superseded update binding to be one canonical digest."""

    value = record.get("superseded_update_digest")
    if value is not None and (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError("active AKS service update repair binding is invalid")


def source_image_import_paths(
    work_dir: Path,
    service: str,
    source_commit: str,
    image_digest: str,
) -> tuple[Path, Path]:
    """Preserve one legacy import while giving each later image an exact identity."""

    prefix = f"source-image-import-{service}"
    legacy_claim = work_dir / f"{prefix}-claim.json"
    legacy_receipt = work_dir / f"{prefix}-receipt.json"
    if not legacy_claim.exists() and not legacy_claim.is_symlink():
        return legacy_claim, legacy_receipt
    retained = private_json(legacy_claim, "source service image import claim")
    if (
        retained.get("source_commit") == source_commit
        and retained.get("image_digest") == image_digest
    ):
        return legacy_claim, legacy_receipt
    if not legacy_receipt.is_file() or legacy_receipt.is_symlink():
        return legacy_claim, legacy_receipt
    identity = canonical_digest(
        {
            "service": service,
            "source_commit": source_commit,
            "image_digest": image_digest,
        }
    )[:12]
    return (
        work_dir / f"{prefix}-{identity}-claim.json",
        work_dir / f"{prefix}-{identity}-receipt.json",
    )
