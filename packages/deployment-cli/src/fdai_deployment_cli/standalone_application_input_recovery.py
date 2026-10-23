"""Recover one authoritative AKS application input after an ambiguous apply."""

from __future__ import annotations

import json
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.private_output import write_private_output
from fdai_deployment_cli.standalone_host_state import (
    private_json,
    replace_private_json,
)


def bind_authoritative_backend_nsg(
    *,
    work_dir: Path,
    retained: dict[str, object],
    current: dict[str, object],
) -> bool:
    """Bind the sole empty-to-authoritative NSG transition under retained claims."""

    if retained == current:
        return False
    original_paths = ("application-claim.json", "application-receipt.json")
    residual_paths = (
        "application-claim.json",
        "application-residual-claim.json",
        "application-residual-review.json",
    )
    ordinary_applied = all((work_dir / name).is_file() for name in original_paths)
    residual_claimed = all((work_dir / name).is_file() for name in residual_paths)
    if not ordinary_applied and not residual_claimed:
        raise ValueError("retained workloads.auto.tfvars.json differs")
    old_gateway = retained.get("browser_gateway")
    new_gateway = current.get("browser_gateway")
    if not isinstance(old_gateway, dict) or not isinstance(new_gateway, dict):
        raise TypeError("retained workloads.auto.tfvars.json differs")
    old_nsg = old_gateway.get("backend_nsg_id")
    new_nsg = new_gateway.get("backend_nsg_id")
    expected = {
        **retained,
        "browser_gateway": {**old_gateway, "backend_nsg_id": new_nsg},
    }
    if old_nsg != "" or not isinstance(new_nsg, str) or not new_nsg or expected != current:
        raise ValueError("retained workloads.auto.tfvars.json differs")
    original_claim = private_json(work_dir / "application-claim.json", "application claim")
    claim = {
        "schema_version": "fdai.application-input-rebind-claim.v1",
        "field": "browser_gateway.backend_nsg_id",
        "prior_values_digest": canonical_digest(retained),
        "current_values_digest": canonical_digest(current),
        "original_claim_digest": canonical_digest(original_claim),
        "mutation_performed": False,
    }
    if residual_claimed:
        claim["residual_claim_digest"] = canonical_digest(
            private_json(
                work_dir / "application-residual-claim.json",
                "application residual claim",
            )
        )
    else:
        claim["application_receipt_digest"] = canonical_digest(
            private_json(work_dir / "application-receipt.json", "application receipt")
        )
    claim["claim_digest"] = canonical_digest(claim)
    claim_path = work_dir / "application-input-rebind-claim.json"
    if claim_path.exists():
        if private_json(claim_path, "application input rebind claim") != claim:
            raise ValueError("application input rebind claim differs")
    else:
        write_private_output(
            claim_path,
            json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n",
        )
    replace_private_json(work_dir / "workloads.auto.tfvars.json", current)
    receipt = {
        "schema_version": "fdai.application-input-rebind-receipt.v1",
        "claim_digest": claim["claim_digest"],
        "field": claim["field"],
        "authoritative_value_digest": canonical_digest({"backend_nsg_id": new_nsg}),
        "mutation_performed": True,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    replace_private_json(work_dir / "application-input-rebind-receipt.json", receipt)
    return True


def successor_prerequisite_verified(work_dir: Path, stage: str) -> bool:
    """Return whether the stage has its exact recovery prerequisite receipt."""

    if stage != "application":
        return False
    path = work_dir / "application-input-rebind-receipt.json"
    if not path.is_file() or path.is_symlink():
        return False
    receipt = private_json(path, "application input rebind receipt")
    digest = receipt.pop("receipt_digest", None)
    return (
        canonical_digest(receipt) == digest
        and receipt.get("schema_version") == "fdai.application-input-rebind-receipt.v1"
        and receipt.get("field") == "browser_gateway.backend_nsg_id"
        and receipt.get("mutation_performed") is True
    )
