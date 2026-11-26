"""Standalone AKS frozen-scenario catalog-review checkpoint."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.standalone_aks_job_execution import execute_aks_cronjob_once
from fdai_deployment_cli.standalone_host_state import private_json, replace_private_json

_NAMESPACE = "fdai-runtime"
_TRIGGER_SCHEMA = "fdai.operational-catalog-review-trigger-receipt.v3"
_SCHEMA = "fdai.standalone-catalog-review-receipt.v3"


def run_catalog_review(
    context: dict[str, Any],
    work_dir: Path,
    *,
    login: Callable[[dict[str, object], Path], None],
) -> dict[str, object]:
    """Run one deployed draft-only review and persist its sanitized receipt."""

    receipt_path = work_dir / "catalog-review-receipt.json"
    if receipt_path.exists():
        return _validated_receipt(
            private_json(receipt_path, "standalone catalog review receipt"),
            context=context,
        )
    if context.get("catalog_review_selected") is not True:
        receipt: dict[str, object] = {
            "schema_version": _SCHEMA,
            "state": "skipped",
            "selected": False,
            "reason": "not_selected",
            "source_revision": str(context.get("source_commit", "")),
            "catalog_review_profile_digest": str(context.get("catalog_review_profile_digest", "")),
            "mutation_performed": False,
            "subscription_ready": False,
        }
        receipt["receipt_digest"] = canonical_digest(receipt)
        replace_private_json(receipt_path, receipt)
        return receipt
    if _runtime_platform(context) != "aks":
        raise ValueError("catalog review one-shot execution requires AKS")
    if not (work_dir / "application-receipt.json").is_file():
        raise ValueError("catalog review application prerequisite is incomplete")
    values = private_json(work_dir / "workloads.auto.tfvars.json", "AKS workload variables")
    scheduled_jobs = _mapping(values.get("scheduled_jobs"), "AKS scheduled jobs")
    job = scheduled_jobs.get("catalog-review")
    if not isinstance(job, dict) or context.get("catalog_review_available") is not True:
        raise ValueError("catalog review private GitOps binding is unavailable")
    login(context, work_dir)
    execution = execute_aks_cronjob_once(
        context,
        work_dir,
        template_name="catalog-review",
        purpose="catalog-review",
        expected_container_name="catalog-review",
        expected_image=str(job.get("image", "")),
        expected_command=(
            "python",
            "-m",
            "fdai.runtime.operational_catalog_review_trigger",
        ),
        expected_service_account="catalog-review-job",
        args=(),
        environment={},
        require_suspended=True,
        timeout_seconds=360,
    )
    kubeconfig = Path(str(context["kubeconfig"]))
    logs = _capture(
        (
            "kubectl",
            "logs",
            f"job/{execution.name}",
            "--namespace",
            _NAMESPACE,
            "--container",
            "catalog-review",
            "--tail",
            "20",
            "--limit-bytes",
            "65536",
            f"--kubeconfig={kubeconfig}",
        ),
        cwd=work_dir,
        timeout=60,
        reason="catalog review sanitized receipt readback failed",
    )
    trigger_receipt = _receipt_from_logs(
        logs,
        source_revision=str(context.get("source_commit", "")),
    )
    receipt = {key: item for key, item in trigger_receipt.items() if key != "receipt_digest"}
    receipt.update(
        schema_version=_SCHEMA,
        selected=True,
        catalog_review_profile_digest=str(context["catalog_review_profile_digest"]),
        trigger_receipt_digest=trigger_receipt["receipt_digest"],
    )
    receipt["receipt_digest"] = canonical_digest(receipt)
    replace_private_json(receipt_path, receipt)
    return receipt


def _receipt_from_logs(logs: str, *, source_revision: str) -> dict[str, object]:
    for line in reversed(logs.splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("schema_version") == _TRIGGER_SCHEMA:
            return _validated_trigger_receipt(candidate, source_revision=source_revision)
    raise ValueError("catalog review sanitized receipt is unavailable")


def _validated_trigger_receipt(
    value: dict[str, Any],
    *,
    source_revision: str,
) -> dict[str, object]:
    receipt = {str(key): item for key, item in value.items()}
    supplied_digest = receipt.pop("receipt_digest", None)
    required_labels = receipt.get("required_labels")
    observed_labels = receipt.get("observed_labels")
    if (
        receipt.get("schema_version") != _TRIGGER_SCHEMA
        or receipt.get("state") != "draft-review-published"
        or receipt.get("source_revision") != source_revision
        or re.fullmatch(r"[0-9a-f]{40}", source_revision) is None
        or not isinstance(required_labels, list)
        or any(not isinstance(label, str) for label in required_labels)
        or len(required_labels) != len(set(required_labels))
        or required_labels != sorted(required_labels)
        or observed_labels != required_labels
        or not {"draft", "shadow", "governance", "catalog-review"}.issubset(required_labels)
        or sum(isinstance(label, str) and label.startswith("rule:") for label in required_labels)
        != 1
        or sum(isinstance(label, str) and label.startswith("action:") for label in required_labels)
        != 1
        or receipt.get("draft") is not True
        or receipt.get("mode") != "shadow"
        or receipt.get("catalog_activation_performed") is not False
        or receipt.get("code_path_merge_authority") is not False
        or receipt.get("independent_pr_observation_required") is not True
        or receipt.get("independent_pr_observation_verified") is not True
        or receipt.get("independent_observation_scope") != "gitops-pr"
        or receipt.get("durable_intent_verified") is not True
        or receipt.get("durable_terminal_verified") is not True
        or receipt.get("managed_resource_mutation_status") != "unknown"
        or receipt.get("managed_resource_mutation_performed") is not None
        or receipt.get("grants_authority") is not False
        or not isinstance(receipt.get("already_existed"), bool)
        or receipt.get("subscription_ready") is not False
        or any(
            re.fullmatch(r"[0-9a-f]{64}", str(receipt.get(name, ""))) is None
            for name in (
                "candidate_digest",
                "package_digest",
                "review_ref_digest",
                "binding_digest",
                "publication_observation_digest",
                "review_document_digest",
                "durable_audit_digest",
            )
        )
        or re.fullmatch(
            r"(?:[0-9a-f]{40}|[0-9a-f]{64})",
            str(receipt.get("publication_head_sha", "")),
        )
        is None
        or supplied_digest != canonical_digest(receipt)
    ):
        raise ValueError("catalog review sanitized receipt is invalid")
    receipt["receipt_digest"] = supplied_digest
    return receipt


def _validated_receipt(
    value: dict[str, Any],
    *,
    context: dict[str, Any],
) -> dict[str, object]:
    receipt = {str(key): item for key, item in value.items()}
    supplied_digest = receipt.pop("receipt_digest", None)
    if (
        receipt.get("schema_version") != _SCHEMA
        or receipt.get("source_revision") != context.get("source_commit")
        or receipt.get("catalog_review_profile_digest")
        != context.get("catalog_review_profile_digest")
        or supplied_digest != canonical_digest(receipt)
    ):
        raise ValueError("catalog review sanitized receipt is invalid")
    selected = context.get("catalog_review_selected") is True
    if selected:
        if (
            receipt.get("selected") is not True
            or receipt.get("state") != "draft-review-published"
            or receipt.get("independent_pr_observation_verified") is not True
            or receipt.get("independent_observation_scope") != "gitops-pr"
        ):
            raise ValueError("selected catalog review receipt is incomplete")
    elif (
        receipt.get("selected") is not False
        or receipt.get("state") != "skipped"
        or receipt.get("reason") != "not_selected"
    ):
        raise ValueError("unselected catalog review receipt is invalid")
    receipt["receipt_digest"] = supplied_digest
    return receipt


def _runtime_platform(context: dict[str, Any]) -> str:
    value = context.get("runtime_profile")
    if value is None:
        return "container-apps"
    profile = _mapping(value, "runtime deployment profile")
    platform = profile.get("runtime_platform")
    if platform not in {"container-apps", "aks"}:
        raise ValueError("runtime deployment platform is invalid")
    return str(platform)


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


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} is invalid")
    return {str(key): item for key, item in value.items()}


__all__ = ["run_catalog_review"]
