"""Post-application inventory and catalog-review checkpoints."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.deployment_progress import begin_stage, progress_detail
from fdai_deployment_cli.standalone_aks_inventory import require_initial_inventory_receipt
from fdai_deployment_cli.standalone_trial_activation import require_trial_activation_receipt


@dataclass(frozen=True, slots=True)
class PostApplicationReceipts:
    inventory: dict[str, Any]
    catalog_review: dict[str, Any]
    trial_activation: dict[str, Any] | None = None


def run_post_application_checkpoints(
    tunnel: Any,
    *,
    remote_root: str,
    app_work: str,
    runtime_platform: str,
    remote_json: Callable[..., dict[str, Any]],
) -> PostApplicationReceipts:
    """Open the AKS Trial window, then run inventory and the selected-or-skipped review."""

    trial_activation = None
    if runtime_platform == "aks":
        progress_detail("Opening the Trial window at the installation's anchored creation time")
        trial_activation = require_trial_activation_receipt(
            remote_json(tunnel, remote_root, app_work, ("activate-trial",), timeout=900)
        )
    begin_stage("initial-inventory")
    progress_detail("Collecting and independently reading back the initial inventory")
    inventory = remote_json(
        tunnel,
        remote_root,
        app_work,
        ("initial-inventory",),
        timeout=4200,
    )
    require_initial_inventory_receipt(inventory, runtime_platform=runtime_platform)
    begin_stage("catalog-review")
    progress_detail("Publishing or explicitly skipping the frozen catalog review")
    catalog_review = remote_json(
        tunnel,
        remote_root,
        app_work,
        ("catalog-review",),
        timeout=600,
    )
    require_catalog_review_receipt(catalog_review)
    return PostApplicationReceipts(
        inventory=inventory,
        catalog_review=catalog_review,
        trial_activation=trial_activation,
    )


def require_catalog_review_receipt(value: dict[str, Any]) -> None:
    """Accept only an explicit skip or independently observed draft publication."""

    supplied_digest = value.get("receipt_digest")
    material = {key: item for key, item in value.items() if key != "receipt_digest"}
    if supplied_digest != canonical_digest(material):
        raise ValueError("standalone catalog review receipt digest is invalid")
    if value.get("state") == "skipped":
        if (
            value.get("selected") is not False
            or value.get("reason") != "not_selected"
            or value.get("mutation_performed") is not False
        ):
            raise ValueError("standalone catalog review skip receipt is invalid")
        return
    required_labels = value.get("required_labels")
    observed_labels = value.get("observed_labels")
    if (
        value.get("state") != "draft-review-published"
        or value.get("selected") is not True
        or not isinstance(required_labels, list)
        or any(not isinstance(label, str) for label in required_labels)
        or len(required_labels) != len(set(required_labels))
        or required_labels != sorted(required_labels)
        or observed_labels != required_labels
        or not {"draft", "shadow", "governance", "catalog-review"}.issubset(required_labels)
        or sum(label.startswith("rule:") for label in required_labels) != 1
        or sum(label.startswith("action:") for label in required_labels) != 1
        or value.get("independent_pr_observation_verified") is not True
        or value.get("independent_observation_scope") != "gitops-pr"
        or value.get("durable_intent_verified") is not True
        or value.get("durable_terminal_verified") is not True
        or value.get("code_path_merge_authority") is not False
        or value.get("managed_resource_mutation_status") != "unknown"
        or value.get("managed_resource_mutation_performed") is not None
        or re.fullmatch(
            r"(?:[0-9a-f]{40}|[0-9a-f]{64})",
            str(value.get("publication_head_sha", "")),
        )
        is None
        or re.fullmatch(r"[0-9a-f]{64}", str(value.get("review_document_digest", ""))) is None
    ):
        raise ValueError("standalone selected catalog review is incomplete")


__all__ = [
    "PostApplicationReceipts",
    "require_catalog_review_receipt",
    "run_post_application_checkpoints",
]
