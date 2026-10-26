"""Exact Terraform import, state-release, and rollback contract for Hub workload handoff."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.hub_workload_handoff_inputs import (
    INVENTORY_SCHEMA,
    WorkloadStateObject,
    build_handoff_inventory,
    read_handoff_inventory,
    write_handoff_operator_inputs,
)
from fdai_deployment_cli.private_output import write_private_bytes

TRANSITION_SCHEMA = "fdai.hub-workload-state-transition.v1"
RECEIPT_SCHEMA = "fdai.hub-workload-state-transition-receipt.v1"
ADOPTION_RELEASE_SCHEMA = "fdai.runtime-adoption-release.v1"
PLAN_RECEIPT_SCHEMA = "fdai.hub-workload-plan-verification.v1"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)

__all__ = [
    "WorkloadStateObject",
    "build_handoff_inventory",
    "read_handoff_inventory",
    "verify_handoff_plan",
    "verify_handoff_plans",
    "write_handoff_operator_inputs",
    "write_handoff_terraform_files",
]


def verify_handoff_plan(
    plan: Mapping[str, object],
    objects: Sequence[WorkloadStateObject],
    *,
    phase: str,
    inventory_digest: str,
) -> dict[str, object]:
    """Verify an exact import, forget-only release, or post-import zero-change plan."""

    if (
        phase not in {"import", "release", "zero-change"}
        or _DIGEST.fullmatch(inventory_digest) is None
    ):
        raise ValueError("Hub handoff plan verification inputs are invalid")
    expected = {item.address: item for item in objects}
    if not expected or len(expected) != len(objects):
        raise ValueError("Hub handoff plan objects must be unique")
    _plan_header(plan, applyable=phase != "zero-change")
    changes = _plan_changes(plan)
    if set(changes) != set(expected):
        raise ValueError(f"Hub handoff {phase} plan inventory differs")
    for address, change in changes.items():
        actions = change.get("actions")
        importing = change.get("importing")
        if phase == "import":
            before = change.get("before")
            if (
                actions != ["no-op"]
                or not isinstance(importing, Mapping)
                or importing.get("id") != expected[address].import_id
                or (before is not None and before != change.get("after"))
            ):
                raise ValueError("Hub handoff import plan is not exact import-only")
        elif phase == "release":
            if (
                actions != ["forget"]
                or importing is not None
                or change.get("before") is None
                or change.get("after") is not None
            ):
                raise ValueError("Hub handoff release plan is not exact forget-only")
        elif (
            actions != ["no-op"]
            or importing is not None
            or "before" not in change
            or change.get("before") != change.get("after")
        ):
            raise ValueError("Hub handoff plan is not zero-change")
    body: dict[str, object] = {
        "schema_version": PLAN_RECEIPT_SCHEMA,
        "phase": phase,
        "inventory_digest": inventory_digest,
        "plan_digest": "sha256:" + canonical_digest(plan),
        "object_count": len(expected),
        "live_mutation_authorized": False,
        "state_effect": {
            "import": "import-only",
            "release": "forgotten-without-destroy",
            "zero-change": "zero-change",
        }[phase],
    }
    return body | {"receipt_digest": "sha256:" + canonical_digest(body)}


def write_handoff_terraform_files(
    destination: Path,
    objects: Sequence[WorkloadStateObject],
) -> tuple[Path, Path]:
    """Write exact removed/import blocks into a fresh private execution directory."""

    if destination.exists() or destination.is_symlink():
        raise ValueError("Hub handoff Terraform destination already exists")
    by_address = {item.address: item for item in objects}
    if not by_address or len(by_address) != len(objects):
        raise ValueError("Hub handoff Terraform objects must be unique")
    destination.mkdir(mode=0o700, parents=True)
    release_path = destination / "hub-release.tf.json"
    rollback_path = destination / "hub-rollback.tf.json"
    write_private_bytes(
        release_path,
        canonical_bytes(
            {
                "removed": [
                    {
                        "from": f"${{{address}}}",
                        "lifecycle": {"destroy": False},
                    }
                    for address in sorted(by_address)
                ]
            }
        )
        + b"\n",
    )
    write_private_bytes(
        rollback_path,
        canonical_bytes(
            {
                "import": [
                    {
                        "to": f"${{{address}}}",
                        "id": by_address[address].import_id,
                    }
                    for address in sorted(by_address)
                ]
            }
        )
        + b"\n",
    )
    return release_path, rollback_path


def verify_handoff_plans(
    release_plan: Mapping[str, object],
    rollback_plan: Mapping[str, object],
    objects: Sequence[WorkloadStateObject],
    *,
    adoption_release: Mapping[str, object],
) -> dict[str, object]:
    """Require exact forget-only release and zero-change rollback plans."""

    adoption_release_digest = _adoption_release_digest(adoption_release)
    inventory_body = {
        "schema_version": INVENTORY_SCHEMA,
        "objects": [
            {
                "address": item.address,
                "import_id": item.import_id,
                "render_digest": item.render_digest,
            }
            for item in sorted(objects, key=lambda value: value.address)
        ],
    }
    inventory_digest = "sha256:" + canonical_digest(inventory_body)
    release_verification = verify_handoff_plan(
        release_plan,
        objects,
        phase="release",
        inventory_digest=inventory_digest,
    )
    rollback_verification = verify_handoff_plan(
        rollback_plan,
        objects,
        phase="zero-change",
        inventory_digest=inventory_digest,
    )
    body: dict[str, object] = {
        "schema_version": RECEIPT_SCHEMA,
        "objects": [
            {
                "address": item.address,
                "import_id": item.import_id,
                "render_digest": item.render_digest,
            }
            for item in sorted(objects, key=lambda value: value.address)
        ],
        "release_plan_digest": "sha256:" + canonical_digest(release_plan),
        "rollback_plan_digest": "sha256:" + canonical_digest(rollback_plan),
        "release_verification_digest": release_verification["receipt_digest"],
        "rollback_verification_digest": rollback_verification["receipt_digest"],
        "adoption_release_receipt_digest": adoption_release_digest,
        "release_state": "forgotten-without-destroy",
        "rollback_state": "zero-change",
    }
    return body | {"receipt_digest": "sha256:" + canonical_digest(body)}


def _adoption_release_digest(receipt: Mapping[str, object]) -> str:
    digest = receipt.get("receipt_digest")
    body = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    if (
        body.get("schema_version") != ADOPTION_RELEASE_SCHEMA
        or body.get("reconciliation_released") is not True
        or not isinstance(body.get("installation_id"), str)
        or not isinstance(body.get("release_id"), str)
        or _DIGEST.fullmatch(str(body.get("adoption_receipt_digest"))) is None
        or not isinstance(digest, str)
        or digest != "sha256:" + canonical_digest(body)
    ):
        raise ValueError("Agent reconciliation release receipt is invalid")
    return digest


def _plan_header(plan: Mapping[str, object], *, applyable: bool) -> None:
    if (
        plan.get("format_version") not in {"1.1", "1.2"}
        or plan.get("complete") is not True
        or plan.get("errored") is not False
        or plan.get("applyable") is not applyable
        or plan.get("resource_drift", []) != []
        or plan.get("deferred_changes", []) != []
    ):
        raise ValueError("Hub handoff plan metadata is invalid")
    output_changes = plan.get("output_changes", {})
    if not isinstance(output_changes, Mapping):
        raise ValueError(  # noqa: TRY004 - normalize untrusted plan JSON
            "Hub handoff plan outputs are invalid"
        )
    if phase_changes := [
        value
        for value in output_changes.values()
        if not isinstance(value, Mapping) or value.get("actions") != ["no-op"]
    ]:
        raise ValueError(f"Hub handoff plan contains {len(phase_changes)} output changes")
    checks = plan.get("checks", [])
    if not isinstance(checks, list) or any(
        not isinstance(check, Mapping) or check.get("status") != "pass" for check in checks
    ):
        raise ValueError("Hub handoff plan checks must pass")


def _plan_changes(plan: Mapping[str, object]) -> dict[str, dict[str, Any]]:
    changes = plan.get("resource_changes")
    if not isinstance(changes, list):
        raise ValueError(  # noqa: TRY004 - normalize untrusted plan JSON
            "Terraform plan resource changes are invalid"
        )
    result: dict[str, dict[str, Any]] = {}
    for item in changes:
        if (
            not isinstance(item, Mapping)
            or not isinstance(address := item.get("address"), str)
            or item.get("previous_address") is not None
            or not isinstance(change := item.get("change"), Mapping)
            or address in result
        ):
            raise ValueError("Terraform plan resource change is invalid")
        result[address] = dict(change)
    return result
