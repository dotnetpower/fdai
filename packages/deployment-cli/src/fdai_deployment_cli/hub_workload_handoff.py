"""Exact Terraform state-release and rollback-import contract for Hub workload handoff."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.private_output import write_private_bytes

TRANSITION_SCHEMA = "fdai.hub-workload-state-transition.v1"
RECEIPT_SCHEMA = "fdai.hub-workload-state-transition-receipt.v1"
ADOPTION_RELEASE_SCHEMA = "fdai.runtime-adoption-release.v1"
_ADDRESS = re.compile(
    r"kubernetes_(?:deployment_v1|service_v1|cron_job_v1|horizontal_pod_autoscaler_v2)"
    r"\.[a-z][a-z0-9_]*(?:\[[\"'][a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?[\"']\])?\Z",
    re.ASCII,
)
_IMPORT_ID = re.compile(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?/[A-Za-z0-9._/-]{1,253}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)


@dataclass(frozen=True, slots=True)
class WorkloadStateObject:
    address: str
    import_id: str
    render_digest: str

    def __post_init__(self) -> None:
        if (
            _ADDRESS.fullmatch(self.address) is None
            or _IMPORT_ID.fullmatch(self.import_id) is None
            or _DIGEST.fullmatch(self.render_digest) is None
        ):
            raise ValueError("Hub workload state object is invalid")


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

    expected = {item.address for item in objects}
    if not expected or len(expected) != len(objects):
        raise ValueError("Hub handoff plan objects must be unique")
    adoption_release_digest = _adoption_release_digest(adoption_release)
    release_changes = _changes(release_plan)
    if set(release_changes) != expected or any(
        actions != ("forget",) for actions in release_changes.values()
    ):
        raise ValueError("Hub handoff release plan is not exact forget-only")
    rollback_changes = _changes(rollback_plan)
    if any(actions != ("no-op",) for actions in rollback_changes.values()):
        raise ValueError("Hub handoff rollback plan is not zero-change")
    unexpected = set(rollback_changes) - expected
    if unexpected:
        raise ValueError("Hub handoff rollback plan contains unknown objects")
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


def _changes(plan: Mapping[str, object]) -> dict[str, tuple[str, ...]]:
    changes = plan.get("resource_changes", [])
    if not isinstance(changes, list):
        raise ValueError("Terraform plan resource changes are invalid")
    parsed: dict[str, tuple[str, ...]] = {}
    for item in changes:
        if (
            not isinstance(item, Mapping)
            or not isinstance(item.get("address"), str)
            or not isinstance(change := item.get("change"), Mapping)
            or not isinstance(actions := change.get("actions"), list)
            or not all(isinstance(action, str) for action in actions)
        ):
            raise ValueError("Terraform plan resource change is invalid")
        address = str(item["address"])
        if address in parsed:
            raise ValueError("Terraform plan resource addresses must be unique")
        parsed[address] = tuple(str(action) for action in actions)
    return parsed
