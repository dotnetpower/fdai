"""Receipt-gated finalization for one completed AKS service update."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Callable

from fdai_deployment_cli.contracts import canonical_digest


def add_finalization_parser(
    subcommands: Any,
    *,
    services: frozenset[str],
) -> None:
    """Register the managed-host finalization checkpoint."""

    parser = subcommands.add_parser("finalize-service-update")
    parser.add_argument("--service", choices=sorted(services), required=True)
    parser.add_argument("--operation", required=True)
    parser.add_argument("--receipt-digest", required=True)
    parser.set_defaults(handler=finalize_service_update)


def _finalize_service_update(
    args: argparse.Namespace,
    work_dir: Path,
    *,
    private_json: Callable[[Path, str], dict[str, Any]],
    replace_private_json: Callable[[Path, dict[str, object]], None],
    service_update_record: Callable[..., dict[str, Any] | None],
    service_update_review: Callable[[dict[str, Any]], dict[str, str]],
) -> dict[str, object]:
    """Clear one active marker only after complete apply receipt revalidation."""

    operation = str(args.operation)
    service = str(args.service)
    if re.fullmatch(rf"service-update-{re.escape(service)}-[0-9a-f]{{12}}", operation) is None:
        raise ValueError("AKS service update finalization operation is invalid")
    final_path = work_dir / f"{operation}-finalization-receipt.json"
    if final_path.exists():
        retained = private_json(final_path, "AKS service update finalization")
        if retained.get("apply_receipt_digest") != args.receipt_digest:
            raise ValueError("AKS service update finalization receipt differs")
        return retained
    context_path = work_dir / "context.json"
    context = private_json(context_path, "standalone host context")
    active = context.get("active_service_update")
    if (
        not isinstance(active, dict)
        or active.get("operation") != operation
        or active.get("service") != service
    ):
        raise ValueError("active AKS service update differs from finalization")
    record = service_update_record(context, work_dir, stage="application", service=service)
    if record is None:
        raise ValueError("AKS service update record is unavailable")
    apply_receipt = private_json(
        work_dir / f"{operation}-receipt.json",
        "AKS service update apply receipt",
    )
    digest = apply_receipt.get("receipt_digest")
    material = {key: value for key, value in apply_receipt.items() if key != "receipt_digest"}
    if (
        digest != args.receipt_digest
        or digest != canonical_digest(material)
        or apply_receipt.get("state") != "applied"
        or apply_receipt.get("operation") != operation
        or apply_receipt.get("service_update") != service_update_review(record)
        or apply_receipt.get("control_plane_readback_verified") is not True
        or apply_receipt.get("peer_state_unchanged_verified") is not True
        or apply_receipt.get("terraform_zero_change_verified") is not True
    ):
        raise ValueError("AKS service update apply receipt is incomplete")
    context.pop("active_service_update")
    replace_private_json(context_path, context)
    result: dict[str, object] = {
        "schema_version": "fdai.aks-service-update-finalization.v1",
        "state": "finalized",
        "operation": operation,
        "service": service,
        "update_digest": record["update_digest"],
        "apply_receipt_digest": digest,
        "mutation_performed": False,
        "subscription_ready": False,
    }
    result["receipt_digest"] = canonical_digest(result)
    replace_private_json(final_path, result)
    return result


def finalize_service_update(
    args: argparse.Namespace,
    work_dir: Path,
) -> dict[str, object]:
    """Resolve host-owned readers lazily to avoid a module cycle."""

    from fdai_deployment_cli import standalone_host

    return _finalize_service_update(
        args,
        work_dir,
        private_json=standalone_host._private_json,
        replace_private_json=standalone_host._replace_private_json,
        service_update_record=standalone_host._service_update_record,
        service_update_review=standalone_host._service_update_review,
    )


__all__ = ["add_finalization_parser", "finalize_service_update"]
