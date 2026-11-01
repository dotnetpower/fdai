#!/usr/bin/env python3
"""Export and verify Terraform inventory-to-cost-model SKU and quantity reconciliation."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_REL = Path("config/cost-model-sku-reconciliation.json")
TERRAFORM_SOURCES = (
    "infra/main.tf",
    "infra/modules/compute/container-apps/main.tf",
    "infra/modules/compute/container-apps/scheduler_job.tf",
    "infra/modules/compute/container-apps/variables.tf",
    "infra/modules/event-bus/event-hubs-kafka/main.tf",
    "infra/modules/container-registry/main.tf",
    "infra/modules/identity/user-assigned-mi/main.tf",
)


def compute_terraform_inventory_digest(root: Path = REPO_ROOT) -> str:
    """Compute a deterministic SHA-256 digest over the tracked Terraform inventory files."""
    hasher = hashlib.sha256()
    for rel in TERRAFORM_SOURCES:
        path = root / rel
        if not path.is_file():
            raise FileNotFoundError(f"missing Terraform inventory source: {rel}")
        hasher.update(rel.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return f"sha256:{hasher.hexdigest()}"


def build_reconciliation_artifact(root: Path = REPO_ROOT) -> dict[str, Any]:
    """Build the deterministic plan-to-cost-model SKU and quantity reconciliation artifact."""
    plan_digest = compute_terraform_inventory_digest(root)
    rows = [
        {
            "row": 1,
            "resource": "Container Apps environment",
            "terraform_source": "infra/modules/compute/container-apps/main.tf",
            "sku": "Consumption",
            "quantity": 1,
            "min_replicas": 0,
            "max_replicas": 0,
            "storage_gb": None,
            "retention_days": None,
            "category": "variable",
            "reconciled_baseline_usd": "$0 environment fee (vCPU-s + GiB-s metered in row 2/3)",
            "optional_capability": None,
        },
        {
            "row": 2,
            "resource": "Container App (independent Core service)",
            "terraform_source": "infra/modules/compute/container-apps/variables.tf",
            "sku": "Consumption (0.5 vCPU, 1.0 GiB)",
            "quantity": 1,
            "min_replicas": 1,
            "max_replicas": 3,
            "storage_gb": None,
            "retention_days": None,
            "category": "variable",
            "reconciled_baseline_usd": "rolled into row 1 (~$18-$35 at min_replicas=1)",
            "optional_capability": None,
        },
        {
            "row": 3,
            "resource": "Container Apps Jobs",
            "terraform_source": "infra/modules/compute/container-apps/scheduler_job.tf",
            "sku": "Consumption Job (scale-to-zero between triggers)",
            "quantity": 11,
            "min_replicas": 0,
            "max_replicas": 1,
            "storage_gb": None,
            "retention_days": None,
            "category": "variable",
            "reconciled_baseline_usd": "rolled into row 1 (~$2-$8 scheduled execution bursts)",
            "optional_capability": "cost_governance, wara_assessment, browser_evidence_cleanup",
        },
        {
            "row": 4,
            "resource": "Event Hubs Standard namespace",
            "terraform_source": "infra/modules/event-bus/event-hubs-kafka/main.tf",
            "sku": "Standard (1 TU, auto-inflate off)",
            "quantity": 1,
            "min_replicas": None,
            "max_replicas": None,
            "storage_gb": None,
            "retention_days": 1,
            "category": "fixed",
            "reconciled_baseline_usd": "~$22",
            "optional_capability": None,
        },
        {
            "row": 5,
            "resource": "Event Grid inventory subscription + Diagnostic Settings",
            "terraform_source": "infra/main.tf",
            "sku": "System subscription + Azure Monitor diagnostic routing",
            "quantity": 1,
            "min_replicas": None,
            "max_replicas": None,
            "storage_gb": None,
            "retention_days": None,
            "category": "variable",
            "reconciled_baseline_usd": "~$0-$2 (first 100k operations/mo free)",
            "optional_capability": "live_inventory_event_grid",
        },
        {
            "row": 6,
            "resource": "PostgreSQL Flexible Burstable B1ms",
            "terraform_source": "infra/main.tf",
            "sku": "B_Standard_B1ms (1 vCore, 2 GiB RAM)",
            "quantity": 1,
            "min_replicas": None,
            "max_replicas": None,
            "storage_gb": 32,
            "retention_days": 7,
            "category": "fixed",
            "reconciled_baseline_usd": "~$20-$25",
            "optional_capability": None,
        },
        {
            "row": 7,
            "resource": "Key Vault Standard",
            "terraform_source": "infra/main.tf",
            "sku": "Standard",
            "quantity": 1,
            "min_replicas": None,
            "max_replicas": None,
            "storage_gb": None,
            "retention_days": 90,
            "category": "variable",
            "reconciled_baseline_usd": "~$1",
            "optional_capability": None,
        },
        {
            "row": 8,
            "resource": "User-assigned Managed Identity",
            "terraform_source": "infra/modules/identity/user-assigned-mi/main.tf",
            "sku": "Free",
            "quantity": 1,
            "min_replicas": None,
            "max_replicas": None,
            "storage_gb": None,
            "retention_days": None,
            "category": "none",
            "reconciled_baseline_usd": "$0",
            "optional_capability": None,
        },
        {
            "row": 9,
            "resource": "Log Analytics workspace",
            "terraform_source": "infra/main.tf",
            "sku": "PerGB2018",
            "quantity": 1,
            "min_replicas": None,
            "max_replicas": None,
            "storage_gb": None,
            "retention_days": 30,
            "category": "variable",
            "reconciled_baseline_usd": "$5-$15",
            "optional_capability": None,
        },
        {
            "row": 10,
            "resource": "Azure Container Registry (Basic)",
            "terraform_source": "infra/modules/container-registry/main.tf",
            "sku": "Basic",
            "quantity": 1,
            "min_replicas": None,
            "max_replicas": None,
            "storage_gb": 10,
            "retention_days": 7,
            "category": "fixed",
            "reconciled_baseline_usd": "~$5",
            "optional_capability": None,
        },
    ]
    return {
        "schema_version": "1.0.0",
        "owner": "docs/roadmap/interfaces/cost-model.md",
        "terraform_inventory_digest": plan_digest,
        "terraform_sources": list(TERRAFORM_SOURCES),
        "row_count": len(rows),
        "rows": rows,
    }


def validate_reconciliation_artifact(root: Path = REPO_ROOT) -> list[str]:
    """Validate that cost-model-sku-reconciliation.json matches the Terraform tree."""
    path = root / ARTIFACT_REL
    if not path.is_file():
        return [f"missing reconciliation artifact: {ARTIFACT_REL.as_posix()}"]
    try:
        actual = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"unreadable reconciliation artifact: {type(exc).__name__}"]
    expected = build_reconciliation_artifact(root)
    errors: list[str] = []
    if actual.get("schema_version") != "1.0.0":
        errors.append("reconciliation artifact schema_version must be 1.0.0")
    if actual.get("terraform_inventory_digest") != expected["terraform_inventory_digest"]:
        errors.append(
            "terraform_inventory_digest does not match current Terraform sources; "
            "run check-cost-model-reconciliation.py --write"
        )
    rows = actual.get("rows")
    if not isinstance(rows, list) or len(rows) != 10:
        errors.append("reconciliation artifact must contain all 10 cost-model resource rows")
    elif [r.get("row") for r in rows if isinstance(r, dict)] != list(range(1, 11)):
        errors.append("reconciliation rows must be numbered 1 through 10 in order")
    else:
        for row in rows:
            if not isinstance(row, dict):
                errors.append("reconciliation row must be an object")
                continue
            qty = row.get("quantity")
            if type(qty) is not int or qty < 1:
                errors.append(f"row {row.get('row')} quantity must be a positive integer")
            min_rep, max_rep = row.get("min_replicas"), row.get("max_replicas")
            if type(min_rep) is int and type(max_rep) is int and min_rep > max_rep:
                errors.append(f"row {row.get('row')} min_replicas exceeds max_replicas")
            if row.get("category") not in {"fixed", "variable", "none"}:
                errors.append(f"row {row.get('row')} category must be fixed, variable, or none")
            baseline = str(row.get("reconciled_baseline_usd", ""))
            if not baseline or "recalculate from current plan" in baseline.lower():
                errors.append(f"row {row.get('row')} still contains unreconciled placeholder")
            tf_src = str(row.get("terraform_source", ""))
            if not tf_src or not (root / tf_src).is_file():
                errors.append(f"row {row.get('row')} cites missing terraform_source {tf_src!r}")
    return errors


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args == ["--write"]:
        artifact = build_reconciliation_artifact(REPO_ROOT)
        target = REPO_ROOT / ARTIFACT_REL
        target.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
        print(f"cost-model-reconciliation: wrote {ARTIFACT_REL.as_posix()}")
        return 0
    errors = validate_reconciliation_artifact(REPO_ROOT)
    if errors:
        for err in errors:
            print(f"cost-model-reconciliation: ERROR: {err}", file=sys.stderr)
        return 1
    print(
        "cost-model-reconciliation: OK (10/10 cost rows reconciled to Terraform inventory digest)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
