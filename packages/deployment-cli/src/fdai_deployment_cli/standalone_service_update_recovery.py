"""Admit one Core source update from a bounded partial AKS application baseline."""

from __future__ import annotations

from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.standalone_host_state import private_json

_CORE = 'kubernetes_deployment_v1.workload["core-control-plane"]'
_ALLOWED_CHANGES = {
    _CORE: ("delete", "create"),
    'kubernetes_horizontal_pod_autoscaler_v2.workload["core-control-plane"]': ("create",),
    'kubernetes_horizontal_pod_autoscaler_v2.workload["document-ingestion-api"]': ("create",),
    'kubernetes_horizontal_pod_autoscaler_v2.workload["document-processing-worker"]': ("create",),
    'kubernetes_horizontal_pod_autoscaler_v2.workload["operator-service"]': ("create",),
    "azurerm_network_security_rule.browser_gateway[0]": ("create",),
}


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
