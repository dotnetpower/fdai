"""Validate recovered Foundation evidence and no-effect adoption receipts."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from fdai_deployment_cli.contracts import ProvisionProfile, canonical_digest

_COMMIT = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_ADOPTION_KEYS = {
    "schema_version",
    "state",
    "foundation_source_commit",
    "application_source_commit",
    "foundation_run_binding",
    "adopted_run_binding",
    "target_binding",
    "kit_manifest_digest",
    "runtime_release_digest",
    "profile_digest",
    "foundation_handoff_digest",
    "foundation_recovery_receipt_digest",
    "foundation_enrollment_receipt_digest",
    "foundation_state_receipt_digest",
    "foundation_state_authority_digest",
    "known_hosts_digest",
    "managed_resource_count",
    "remote_backend_authority_verified",
    "zero_change_verified",
    "local_state_deleted",
    "no_effect_adoption",
    "mutation_performed",
    "deployment_ready",
    "subscription_ready",
    "receipt_digest",
}


def validate_foundation_adoption_receipt(
    receipt: dict[str, Any],
    *,
    handoff: dict[str, Any],
    target_binding: str,
    application_source_commit: str,
    kit_manifest_digest: str,
    runtime_release_digest: str,
) -> str:
    """Validate a no-effect adoption against exact Foundation and artifact inputs."""

    digest = receipt.get("receipt_digest")
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    managed_resource_count = receipt.get("managed_resource_count")
    foundation_run_binding = handoff.get("run_digest")
    foundation_source_commit = handoff.get("source_commit")
    if (
        set(receipt) != _ADOPTION_KEYS
        or not isinstance(digest, str)
        or canonical_digest(unsigned) != digest
        or receipt.get("schema_version") != "fdai.foundation-adoption.v1"
        or receipt.get("state") != "adopted"
        or not isinstance(foundation_source_commit, str)
        or _COMMIT.fullmatch(foundation_source_commit) is None
        or _COMMIT.fullmatch(application_source_commit) is None
        or receipt.get("foundation_source_commit") != foundation_source_commit
        or receipt.get("application_source_commit") != application_source_commit
        or receipt.get("foundation_run_binding") != foundation_run_binding
        or receipt.get("target_binding") != target_binding
        or receipt.get("kit_manifest_digest") != kit_manifest_digest
        or receipt.get("runtime_release_digest") != runtime_release_digest
        or receipt.get("foundation_handoff_digest") != canonical_digest(handoff)
        or type(managed_resource_count) is not int
        or managed_resource_count <= 0
        or any(
            not isinstance(receipt.get(field), str)
            or _DIGEST.fullmatch(str(receipt[field])) is None
            for field in (
                "foundation_run_binding",
                "adopted_run_binding",
                "target_binding",
                "kit_manifest_digest",
                "runtime_release_digest",
                "profile_digest",
                "foundation_handoff_digest",
                "foundation_recovery_receipt_digest",
                "foundation_enrollment_receipt_digest",
                "foundation_state_receipt_digest",
                "foundation_state_authority_digest",
                "known_hosts_digest",
            )
        )
        or any(
            receipt.get(field) is not True
            for field in (
                "remote_backend_authority_verified",
                "zero_change_verified",
                "local_state_deleted",
                "no_effect_adoption",
            )
        )
        or any(
            receipt.get(field) is not False
            for field in (
                "mutation_performed",
                "deployment_ready",
                "subscription_ready",
            )
        )
    ):
        raise ValueError("Foundation adoption receipt differs from its exact context")
    expected_run_binding = canonical_digest(
        {
            "foundation_run_binding": foundation_run_binding,
            "application_source_commit": application_source_commit,
            "kit_manifest_digest": kit_manifest_digest,
            "runtime_release_digest": runtime_release_digest,
        }
    )
    if receipt.get("adopted_run_binding") != expected_run_binding:
        raise ValueError("Foundation adoption run binding differs")
    return digest


def verify_foundation_chain(
    *,
    profile: ProvisionProfile,
    handoff: dict[str, Any],
    recovery: dict[str, Any],
    enrollment: dict[str, Any],
    state_receipt: dict[str, Any],
    authority: dict[str, Any],
    known_hosts: bytes,
    target_binding: str,
    tenant_id: str,
    subscription_id: str,
    region: str,
    monthly_cost_ceiling: int,
) -> tuple[str, str]:
    """Verify recovered Foundation lineage, target, cleanup, and backend authority."""

    if (
        profile.environment != "dev"
        or profile.region != region
        or profile.target_binding != target_binding
        or profile.connectivity not in {"online", "offline"}
        or profile.host != "managed-vm"
        or profile.transport != "manual"
        or profile.access_method != "bastion"
        or not profile.shadow_only
        or profile.approval_quorum != 1
        or profile.monthly_cost_ceiling != monthly_cost_ceiling
    ):
        raise ValueError("adopted Foundation profile differs from the selected deployment")
    foundation_source_commit = handoff.get("source_commit")
    foundation_run_binding = handoff.get("run_digest")
    runner = handoff.get("runner")
    access = handoff.get("access")
    if (
        not isinstance(foundation_source_commit, str)
        or _COMMIT.fullmatch(foundation_source_commit) is None
        or not isinstance(foundation_run_binding, str)
        or _DIGEST.fullmatch(foundation_run_binding) is None
        or handoff.get("tenant_id") != tenant_id
        or handoff.get("subscription_id") != subscription_id
        or handoff.get("region") != region
        or not isinstance(runner, dict)
        or runner.get("execution_transport") != "manual"
        or not isinstance(access, dict)
        or access.get("method") != "bastion"
    ):
        raise ValueError("recovered Foundation handoff context is invalid")
    expected_records = (
        (enrollment, "fdai.genesis-runner-enrollment-receipt.v1", "attested"),
        (
            state_receipt,
            "fdai.genesis-foundation-state-handoff-receipt.v1",
            "verified",
        ),
        (authority, "fdai.genesis-foundation-state-authority.v1", "verified"),
    )
    if any(
        record.get("schema_version") != schema or record.get("state") != state
        for record, schema, state in expected_records
    ):
        raise ValueError("Foundation adoption evidence is not terminal")
    # A Foundation reaches this point either by ordinary apply or by a governed recovery.
    # Both produce a terminal receipt over the same chain, so accept each exact pair and
    # nothing else; an in-progress or unknown receipt still stops adoption.
    if (recovery.get("schema_version"), recovery.get("state")) not in {
        ("fdai.foundation-recovery-receipt.v1", "verified"),
        ("fdai.genesis-foundation-apply-receipt.v1", "applied"),
    }:
        raise ValueError("Foundation adoption evidence is not terminal")
    if any(
        record.get("source_commit") != foundation_source_commit
        for record in (recovery, enrollment, state_receipt, authority)
    ):
        raise ValueError("Foundation adoption source lineage differs")
    if canonical_digest(handoff) != recovery.get("handoff_digest"):
        raise ValueError("Foundation recovery does not bind the private handoff")
    if (
        enrollment.get("foundation_receipt_digest") != recovery.get("receipt_digest")
        or state_receipt.get("foundation_receipt_digest") != recovery.get("receipt_digest")
        or state_receipt.get("enrollment_receipt_digest") != enrollment.get("receipt_digest")
    ):
        raise ValueError("Foundation adoption receipt chain differs")
    if any(
        record.get("target_binding") != target_binding
        for record in (enrollment, state_receipt, authority)
    ):
        raise ValueError("Foundation adoption target binding differs")
    if (
        state_receipt.get("authority_digest") != authority.get("authority_digest")
        or state_receipt.get("state_digest") != authority.get("state_digest")
        or state_receipt.get("managed_resource_count") != authority.get("managed_resource_count")
    ):
        raise ValueError("Foundation state authority differs from its handoff receipt")
    managed_resource_count = state_receipt.get("managed_resource_count")
    if type(managed_resource_count) is not int or managed_resource_count <= 0:
        raise ValueError("Foundation adoption managed resource count is invalid")
    required_true = (
        (recovery, "control_plane_readback_verified"),
        (recovery, "zero_change_verified"),
        (enrollment, "effect_verified"),
        (enrollment, "identity_attested"),
        (enrollment, "manual_host_readback_verified"),
        (enrollment, "services_attested"),
        (state_receipt, "effect_verified"),
        (state_receipt, "runner_attested"),
        (state_receipt, "remote_backend_authority_verified"),
        (state_receipt, "zero_change_verified"),
        (state_receipt, "local_state_deletion_authorized"),
        (state_receipt, "local_state_deleted"),
        (state_receipt, "remote_transient_deleted"),
        (authority, "remote_backend_authority_verified"),
        (authority, "zero_change_verified"),
        (authority, "local_state_deletion_authorized"),
    )
    if any(record.get(field) is not True for record, field in required_true):
        raise ValueError("Foundation adoption evidence is incomplete")
    if hashlib.sha256(known_hosts).hexdigest() != enrollment.get("host_key_digest"):
        raise ValueError("Foundation enrollment host key evidence differs")
    return foundation_source_commit, foundation_run_binding
