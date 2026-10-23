"""Guarded source-installation teardown from retained ownership evidence."""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile

_DIGEST = re.compile(r"[0-9a-f]{64}")
_GROUP = re.compile(r"rg-[a-z0-9-]{3,80}")


class ResourceGroupClient(Protocol):
    def delete_group(self, *, subscription_id: str, name: str) -> None: ...

    def group_absent(self, *, subscription_id: str, name: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class SourceTeardownPlan:
    target_binding: str
    source_commit: str
    run_binding: str
    installation_anchor: str
    subscription_id: str
    resource_groups: tuple[str, ...]

    @property
    def confirmation(self) -> str:
        return f"delete {self.installation_anchor[:12]}"


def plan_source_teardown(
    *,
    work_dir: Path,
    runtime_profile: RuntimeDeploymentProfile,
    region: str,
    monthly_cost_ceiling: int,
    recovery_directory: Path | None = None,
) -> SourceTeardownPlan:
    """Prove exactly one retained source installation before naming resources to remove."""

    # The intent is written unsigned; the signed preparation receipt binds its digest.
    intent = _plain_json(work_dir / "source-intent.json", "source intent")
    source = _object(intent.get("source"), "source intent source")
    if (
        intent.get("schema_version") != "fdai.source-deployment-intent.v1"
        or intent.get("runtime_profile") != runtime_profile.to_mapping()
        or intent.get("region") != region
        or intent.get("monthly_cost_ceiling") != monthly_cost_ceiling
        or source.get("provenance") != "operator-selected-source"
        or source.get("release_signature_verified") is not False
    ):
        raise ValueError("source teardown intent differs from the selected installation")
    source_commit = _text(source, "source_commit", pattern=r"[0-9a-f]{40}")
    preparation = _verified(work_dir / "source-preparation.json", "source preparation", None)
    if (
        preparation.get("source_commit") != source_commit
        or preparation.get("intent_digest") != canonical_digest(intent)
        or preparation.get("provenance") != "operator-selected-source"
        or preparation.get("release_signature_verified") is not False
    ):
        raise ValueError("source teardown preparation proof differs")
    foundation = work_dir / "foundation"
    marker = _verified(foundation / "source-genesis.json", "source genesis", None)
    target_binding = _text(marker, "target_binding", pattern=r"[0-9a-f]{64}")
    run_binding = _text(marker, "run_binding", pattern=r"[0-9a-f]{64}")
    if marker.get("source_commit") != source_commit:
        raise ValueError("source teardown Genesis proof differs")
    status = _plain_json(foundation / "status.json", "source status")
    report = _object(status.get("foundation_report"), "Foundation report")
    plan_ref = _text(
        _object(report.get("foundation_plan"), "Foundation plan"),
        "plan_ref",
        pattern=r"foundation-plan-attempt-[1-9][0-9]*",
    )
    if recovery_directory is not None:
        handoff, located = _recovered_foundation_ownership(
            recovery_directory=recovery_directory.absolute(),
            source_commit=source_commit,
            target_binding=target_binding,
            run_binding=run_binding,
        )
        partial_claimed = False
    else:
        state_handoff = report.get("state_handoff")
        if isinstance(state_handoff, dict):
            handoff_digest = _text(
                state_handoff,
                "receipt_digest",
                pattern=r"[0-9a-f]{64}",
            )
            handoff = _verified(
                foundation / plan_ref / "foundation-state-handoff-receipt.json",
                "Foundation handoff",
                handoff_digest,
            )
            apply = _verified(
                foundation / plan_ref / "foundation-apply-receipt.json",
                "Foundation apply",
                _text(handoff, "foundation_receipt_digest", pattern=r"[0-9a-f]{64}"),
            )
            if (
                apply.get("schema_version") != "fdai.genesis-foundation-apply-receipt.v1"
                or apply.get("state") != "applied"
                or apply.get("source_commit") != source_commit
                or apply.get("target_binding") != target_binding
            ):
                raise ValueError("source teardown Foundation apply proof differs")
            located = _plain_json(
                foundation / plan_ref / "foundation-private-handoff.json", "handoff"
            )
            if (
                canonical_digest(located) != apply.get("handoff_digest")
                or located.get("source_commit") != source_commit
                or located.get("run_digest") != run_binding
            ):
                raise ValueError("source teardown Foundation location proof differs")
            partial_claimed = False
        else:
            located = _claimed_partial_foundation_ownership(
                foundation=foundation,
                plan_ref=plan_ref,
                source_commit=source_commit,
                target_binding=target_binding,
                run_binding=run_binding,
            )
            handoff = {}
            partial_claimed = True
    if not partial_claimed and (
        handoff.get("schema_version") != "fdai.genesis-foundation-state-handoff-receipt.v1"
        or handoff.get("source_commit") != source_commit
        or handoff.get("target_binding") != target_binding
        or any(
            handoff.get(key) is not True
            for key in (
                "effect_verified",
                "runner_attested",
                "remote_backend_authority_verified",
                "zero_change_verified",
                "remote_transient_deleted",
            )
        )
    ):
        raise ValueError("source teardown Foundation ownership proof is incomplete")
    app = _object(located.get("app_resource_group"), "application resource group")
    ops = _object(located.get("ops"), "operations resource group")
    groups = tuple(
        dict.fromkeys(
            (
                _text(app, "name", pattern=_GROUP.pattern),
                _text(ops, "resource_group_name", pattern=_GROUP.pattern),
            )
        )
    )
    anchor = canonical_digest(
        {
            "schema_version": "fdai.source-teardown-anchor.v1",
            "target_binding": target_binding,
            "run_binding": run_binding,
            "source_commit": source_commit,
            "resource_groups": groups,
        }
    )
    return SourceTeardownPlan(
        target_binding=target_binding,
        source_commit=source_commit,
        run_binding=run_binding,
        installation_anchor=anchor,
        subscription_id=_text(located, "subscription_id"),
        resource_groups=groups,
    )


def _claimed_partial_foundation_ownership(
    *,
    foundation: Path,
    plan_ref: str,
    source_commit: str,
    target_binding: str,
    run_binding: str,
) -> dict[str, object]:
    """Verify a claimed partial Foundation without inventing effect completion."""
    plan_directory = foundation / plan_ref
    plan = _verified_full(
        plan_directory / "foundation-plan.json",
        "Foundation saved plan",
        digest_field="review_digest",
    )
    claim = _plain_json(plan_directory / "foundation-apply-claim.json", "Foundation apply claim")
    variables = _plain_json(foundation / "foundation-variables.json", "Foundation variables")
    context = _object(plan.get("context"), "Foundation saved plan context")
    expected_idempotency = canonical_digest(
        {
            "target_binding": target_binding,
            "plan_digest": plan.get("plan_digest"),
        }
    )
    if (
        (plan_directory / "foundation-apply-receipt.json").exists()
        or plan.get("schema_version") != "fdai.foundation-saved-source-plan.v1"
        or plan.get("state") != "review"
        or context.get("source_commit") != source_commit
        or context.get("target_binding") != target_binding
        or context.get("run_digest") != run_binding
        or context.get("variables_digest") != canonical_digest(variables)
        or claim.get("schema_version") != "fdai.genesis-foundation-apply-claim.v1"
        or claim.get("state") != "applying"
        or claim.get("review_digest") != plan.get("review_digest")
        or claim.get("plan_digest") != plan.get("plan_digest")
        or claim.get("target_binding") != target_binding
        or claim.get("idempotency_key") != expected_idempotency
        or claim.get("mutation_performed") is not False
    ):
        raise ValueError("source teardown claimed Foundation proof differs")
    workload = _text(variables, "workload", pattern=r"[a-z][a-z0-9]{1,15}")
    region_short = _text(variables, "region_short", pattern=r"[a-z][a-z0-9]{1,7}")
    located = _plain_json(plan_directory / "foundation-private-handoff.json", "handoff")
    app = _object(located.get("app_resource_group"), "application resource group")
    ops = _object(located.get("ops"), "operations resource group")
    if (
        located.get("source_commit") != source_commit
        or located.get("run_digest") != run_binding
        or located.get("subscription_id") != variables.get("subscription_id")
        or _text(app, "name", pattern=_GROUP.pattern) != f"rg-{workload}-dev-{region_short}"
        or _text(ops, "resource_group_name", pattern=_GROUP.pattern)
        != f"rg-{workload}-ops-{region_short}"
    ):
        raise ValueError("source teardown claimed Foundation location differs")
    return located


def _recovered_foundation_ownership(
    *,
    recovery_directory: Path,
    source_commit: str,
    target_binding: str,
    run_binding: str,
) -> tuple[dict[str, object], dict[str, object]]:
    """Verify recovered Foundation ownership without fabricating an ordinary apply receipt."""

    if (
        not recovery_directory.is_dir()
        or recovery_directory.is_symlink()
        or re.fullmatch(r"foundation-recovery-attempt-[1-9][0-9]*", recovery_directory.name) is None
    ):
        raise ValueError("source teardown recovery directory is invalid")
    review = _verified_full(
        recovery_directory / "recovery-review.json",
        "Foundation recovery review",
        digest_field="review_digest",
    )
    apply = _verified_full(
        recovery_directory / "recovery-apply-receipt.json",
        "Foundation recovery apply",
    )
    handoff = _verified_full(
        recovery_directory / "foundation-state-handoff-receipt.json",
        "recovered Foundation handoff",
    )
    located = _plain_json(
        recovery_directory / "recovery-private-handoff.json",
        "recovered private handoff",
    )
    if (
        review.get("schema_version") != "fdai.foundation-recovery-review.v1"
        or review.get("source_commit") != source_commit
        or review.get("target_binding") != target_binding
        or apply.get("schema_version") != "fdai.foundation-recovery-receipt.v1"
        or apply.get("state") != "verified"
        or apply.get("source_commit") != source_commit
        or apply.get("control_plane_readback_verified") is not True
        or apply.get("zero_change_verified") is not True
        or handoff.get("schema_version") != "fdai.genesis-foundation-state-handoff-receipt.v1"
        or handoff.get("state") != "verified"
        or handoff.get("source_commit") != source_commit
        or handoff.get("target_binding") != target_binding
        or handoff.get("foundation_receipt_digest") != apply.get("receipt_digest")
        or any(
            handoff.get(key) is not True
            for key in (
                "effect_verified",
                "runner_attested",
                "remote_backend_authority_verified",
                "zero_change_verified",
                "remote_transient_deleted",
                "local_state_deleted",
            )
        )
        or canonical_digest(located) != apply.get("handoff_digest")
        or located.get("source_commit") != source_commit
        or located.get("run_digest") != run_binding
    ):
        raise ValueError("source teardown recovered Foundation ownership proof differs")
    return handoff, located


def apply_source_teardown(
    *,
    work_dir: Path,
    runtime_profile: RuntimeDeploymentProfile,
    region: str,
    monthly_cost_ceiling: int,
    confirmation: str | None,
    client: ResourceGroupClient,
    readback_timeout_seconds: float = 1800,
    readback_interval_seconds: float = 30,
    sleep: Callable[[float], None] = time.sleep,
    recovery_directory: Path | None = None,
) -> dict[str, object]:
    """Delete only proven-owned groups, then read back their absence."""

    plan = plan_source_teardown(
        work_dir=work_dir,
        runtime_profile=runtime_profile,
        region=region,
        monthly_cost_ceiling=monthly_cost_ceiling,
        recovery_directory=recovery_directory,
    )
    review = _review(plan)
    if confirmation != plan.confirmation:
        return {
            **review,
            "state": "review",
            "reason_code": "source_teardown_confirmation_required",
            "required_confirmation": plan.confirmation,
            "mutation_performed": False,
            "deployment_ready": False,
        }
    for group in plan.resource_groups:
        # A rerun after a partial failure must not fail on a group that is already gone.
        if not client.group_absent(subscription_id=plan.subscription_id, name=group):
            client.delete_group(subscription_id=plan.subscription_id, name=group)
    # Deletion is accepted asynchronously, so absence is read back until a bounded deadline.
    deadline = time.monotonic() + readback_timeout_seconds
    while True:
        absent = {
            group: client.group_absent(subscription_id=plan.subscription_id, name=group)
            for group in plan.resource_groups
        }
        if all(absent.values()) or time.monotonic() >= deadline:
            break
        sleep(min(readback_interval_seconds, max(0.0, deadline - time.monotonic())))
    if not all(absent.values()):
        return {
            **review,
            "state": "partial-failure",
            "reason_code": "source_teardown_readback_failed",
            "absent": absent,
            "mutation_performed": True,
            "deployment_ready": False,
        }
    receipt = {
        **review,
        "state": "torn-down",
        "absent": absent,
        "mutation_performed": True,
        "deployment_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    write_private_output(
        work_dir / "source-teardown-receipt.json",
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
    )
    return receipt


class AzureResourceGroupClient:
    """Remove and read back resource groups through the current Azure CLI identity."""

    def delete_group(self, *, subscription_id: str, name: str) -> None:
        _run(
            (
                "az",
                "group",
                "delete",
                "--subscription",
                subscription_id,
                "--name",
                name,
                "--yes",
                "--no-wait",
                "--only-show-errors",
            ),
            reason="source teardown resource deletion failed",
        )

    def group_absent(self, *, subscription_id: str, name: str) -> bool:
        output = _run(
            (
                "az",
                "group",
                "exists",
                "--subscription",
                subscription_id,
                "--name",
                name,
                "--output",
                "tsv",
                "--only-show-errors",
            ),
            reason="source teardown resource readback failed",
        ).strip()
        if output not in {"true", "false"}:
            raise ValueError("source teardown resource readback is invalid")
        return output == "false"


def _review(plan: SourceTeardownPlan) -> dict[str, object]:
    return {
        "schema_version": "fdai.source-teardown-review.v1",
        "target_binding": plan.target_binding,
        "source_commit": plan.source_commit,
        "run_binding": plan.run_binding,
        "installation_anchor": plan.installation_anchor,
        "resource_groups": list(plan.resource_groups),
        "owned_resources_verified": True,
        "foreign_resources_refused": True,
        "subscription_ready": False,
    }


def _verified(path: Path, label: str, expected_digest: str | None) -> dict[str, object]:
    value = _verified_full(path, label)
    digest = value["receipt_digest"]
    if expected_digest is not None and digest != expected_digest:
        raise ValueError(f"{label} digest differs")
    return {key: item for key, item in value.items() if key != "receipt_digest"}


def _verified_full(
    path: Path, label: str, *, digest_field: str = "receipt_digest"
) -> dict[str, object]:
    value = _plain_json(path, label)
    digest = value.get(digest_field)
    unsigned = {key: item for key, item in value.items() if key != digest_field}
    if not isinstance(digest, str) or canonical_digest(unsigned) != digest:
        raise ValueError(f"{label} digest is invalid")
    return value


def _plain_json(path: Path, label: str) -> dict[str, object]:
    value = load_json_object(read_private_bytes(path, max_bytes=1024 * 1024), label=label)
    if not isinstance(value, dict):
        raise TypeError(f"{label} is invalid")
    return {str(key): item for key, item in value.items()}


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} is invalid")
    return {str(key): item for key, item in value.items()}


def _text(value: dict[str, object], key: str, *, pattern: str | None = None) -> str:
    item = value.get(key)
    if not isinstance(item, str) or (pattern is not None and re.fullmatch(pattern, item) is None):
        raise ValueError(f"{key} is invalid")
    return item


def _run(command: tuple[str, ...], *, reason: str) -> str:
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=900)
    if completed.returncode != 0:
        raise ValueError(reason)
    return completed.stdout
