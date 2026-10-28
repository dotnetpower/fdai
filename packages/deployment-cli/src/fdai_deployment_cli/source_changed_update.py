"""Apply the service-only portion of one exact changed-source plan."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes
from fdai_deployment_cli.source_change_plan import plan_git_changes
from fdai_deployment_cli.source_service_update import (
    _require_private_directory,
    deploy_source_service_update,
)

_SUPPORTED_LANES = frozenset({"single-service-update", "multi-service-update"})
_DIGEST = re.compile(r"[0-9a-f]{64}")
_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def deploy_changed_source(
    *,
    source_root: Path,
    base: str,
    application_work_dir: Path,
    work_dir: Path,
    timeout_seconds: int,
) -> dict[str, object]:
    """Deploy affected baseline services serially under their existing exact approvals."""

    started = time.monotonic()
    plan = plan_git_changes(source_root, base)
    lane = str(plan["lane"])
    services = plan.get("services")
    if not isinstance(services, list) or any(not isinstance(item, str) for item in services):
        raise TypeError("source change plan contains an invalid service list")
    if lane == "no-deploy":
        result: dict[str, object] = {
            "schema_version": "fdai.source-changed-update.v1",
            "state": "no-deploy",
            "change_plan_digest": plan["plan_digest"],
            "services": [],
            "service_receipts": [],
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "mutation_performed": False,
            "deployment_ready": False,
        }
        result["receipt_digest"] = canonical_digest(result)
        return result
    if lane not in _SUPPORTED_LANES:
        result = {
            "schema_version": "fdai.source-changed-update.v1",
            "state": "review",
            "lane": lane,
            "reason_code": plan["reason_code"],
            "change_plan_digest": plan["plan_digest"],
            "services": services,
            "next_action": "use_the_reported_deployment_lane",
            "mutation_performed": False,
            "deployment_ready": False,
        }
        result["receipt_digest"] = canonical_digest(result)
        return result

    deadline = DeploymentDeadline(timeout_seconds)
    source = source_root.resolve(strict=True)
    application = application_work_dir.absolute()
    root = work_dir.absolute()
    _require_private_directory(root, create=True)
    intent: dict[str, object] = {
        "schema_version": "fdai.source-changed-update-intent.v1",
        "change_plan_digest": plan["plan_digest"],
        "base_commit": plan["base_commit"],
        "head_commit": plan["head_commit"],
        "services": services,
        "source_binding": canonical_digest({"path": str(source)}),
        "application_work_binding": canonical_digest({"path": str(application)}),
    }
    intent["intent_digest"] = canonical_digest(intent)
    _persist_exact(
        root / "source-changed-update-intent.json",
        intent,
        label="source changed update intent",
    )
    receipts: list[dict[str, Any]] = []
    for index, service in enumerate(services, start=1):
        assert isinstance(service, str)
        receipt = deploy_source_service_update(
            source_root=source,
            application_work_dir=application,
            work_dir=root / service,
            service=service,
            timeout_seconds=deadline.remaining(),
            expected_source_commit=str(plan["head_commit"]),
            expected_current_source_commit=str(plan["base_commit"]),
        )
        summary = _service_receipt_summary(
            receipt,
            expected_service=service,
            expected_source_commit=str(plan["head_commit"]),
        )
        receipts.append(summary)
        progress: dict[str, object] = {
            "schema_version": "fdai.source-changed-update-progress.v1",
            "intent_digest": intent["intent_digest"],
            "completed_service_count": index,
            "service_receipts": list(receipts),
        }
        progress["progress_digest"] = canonical_digest(progress)
        _persist_exact(
            root / f"source-changed-update-progress-{index:02d}.json",
            progress,
            label="source changed update progress",
        )
    effect: dict[str, object] = {
        "schema_version": "fdai.source-changed-update-effect.v1",
        "state": "applied",
        "intent_digest": intent["intent_digest"],
        "change_plan_digest": plan["plan_digest"],
        "head_commit": plan["head_commit"],
        "services": services,
        "service_receipts": receipts,
        "effect_verified": True,
        "mutation_performed": True,
        "deployment_ready": False,
    }
    effect["receipt_digest"] = canonical_digest(effect)
    _persist_exact(
        root / "source-changed-update-effect.json",
        effect,
        label="source changed update effect",
    )
    result = {
        "schema_version": "fdai.source-changed-update.v1",
        "state": "applied",
        "change_plan_digest": plan["plan_digest"],
        "services": services,
        "service_receipts": receipts,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "effect_verified": True,
        "effect_receipt_digest": effect["receipt_digest"],
        "mutation_performed": True,
        "deployment_ready": False,
    }
    result["receipt_digest"] = canonical_digest(result)
    return result


def _service_receipt_summary(
    receipt: dict[str, object],
    *,
    expected_service: str,
    expected_source_commit: str,
) -> dict[str, object]:
    receipt_digest = receipt.get("receipt_digest")
    image_digest = receipt.get("image_digest")
    if (
        receipt.get("schema_version") != "fdai.source-service-update.v1"
        or receipt.get("state") != "applied"
        or receipt.get("service") != expected_service
        or receipt.get("source_commit") != expected_source_commit
        or not isinstance(receipt_digest, str)
        or _DIGEST.fullmatch(receipt_digest) is None
        or not isinstance(image_digest, str)
        or _IMAGE_DIGEST.fullmatch(image_digest) is None
        or any(
            receipt.get(key) is not True
            for key in (
                "effect_verified",
                "peer_state_unchanged_verified",
                "terraform_zero_change_verified",
            )
        )
    ):
        raise ValueError("source changed update received incomplete service effect evidence")
    return {
        "service": expected_service,
        "source_commit": expected_source_commit,
        "receipt_digest": receipt_digest,
        "image_digest": image_digest,
    }


def _persist_exact(path: Path, value: dict[str, object], *, label: str) -> None:
    if path.exists() or path.is_symlink():
        retained = load_json_object(
            read_private_bytes(path, max_bytes=1024 * 1024),
            label=label,
        )
        if retained != value:
            raise ValueError(f"retained {label} differs")
        return
    write_private_bytes(path, canonical_bytes(value))
