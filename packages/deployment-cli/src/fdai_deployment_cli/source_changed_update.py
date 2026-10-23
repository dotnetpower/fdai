"""Apply the service-only portion of one exact changed-source plan."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.source_change_plan import plan_git_changes
from fdai_deployment_cli.source_service_update import deploy_source_service_update

_SUPPORTED_LANES = frozenset({"single-service-update", "multi-service-update"})


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
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    receipts: list[dict[str, Any]] = []
    for service in services:
        assert isinstance(service, str)
        receipt = deploy_source_service_update(
            source_root=source,
            application_work_dir=application,
            work_dir=root / service,
            service=service,
            timeout_seconds=deadline.remaining(),
            expected_source_commit=str(plan["head_commit"]),
        )
        receipts.append(
            {
                "service": service,
                "receipt_digest": receipt["receipt_digest"],
                "image_digest": receipt["image_digest"],
            }
        )
    result = {
        "schema_version": "fdai.source-changed-update.v1",
        "state": "applied",
        "change_plan_digest": plan["plan_digest"],
        "services": services,
        "service_receipts": receipts,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "effect_verified": True,
        "mutation_performed": True,
        "deployment_ready": False,
    }
    result["receipt_digest"] = canonical_digest(result)
    return result
