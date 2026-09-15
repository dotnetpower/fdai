"""Read a recovered Foundation as evidence without rewriting its original receipt or state."""

from __future__ import annotations

import fcntl
import hashlib
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.foundation_plan import verify_foundation_plan
from fdai_deployment_cli.private_output import _open_private_parent, read_private_bytes
from fdai_deployment_cli.profile import load_profile
from fdai_deployment_cli.source_snapshot import verify_source_snapshot
from fdai_deployment_cli.target import compute_target_binding
from genesis_approval import load_genesis_approval
from genesis_approval_prompt import current_actor_digest
from genesis_foundation_apply_contract import load_apply_claim
from genesis_foundation_recovery_apply import _validate_claim
from genesis_foundation_recovery_plan import _json


@contextmanager
def recovery_lock(original_directory: Path) -> Iterator[None]:
    """Serialize handover with the original Foundation execution, never create a new lock."""
    path = original_directory.parent / "source-execution.lock"
    parent = _open_private_parent(path)
    try:
        descriptor = os.open(path.name, os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.geteuid()
            or details.st_nlink != 1
            or stat.S_IMODE(details.st_mode) != 0o600
        ):
            raise ValueError("Foundation recovery handover requires the original private lock")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class RecoveryHandoff:
    """Keep the original recovery receipt separate from the common enrollment reference."""

    receipt: dict[str, object]
    handoff: dict[str, object]
    target_binding: str

    @property
    def foundation_reference(self) -> dict[str, object]:
        """Project correlation fields only; this is not a signed or persisted apply receipt."""
        return {
            "receipt_digest": self.receipt["receipt_digest"],
            "handoff_digest": self.receipt["handoff_digest"],
            "source_commit": self.receipt["source_commit"],
            "target_binding": self.target_binding,
        }


def load_recovery_handoff(
    *,
    original_directory: Path,
    recovery_directory: Path,
    source_snapshot: Path,
    expected_digest: str,
    target_binding: str,
) -> RecoveryHandoff:
    """Validate complete recovery evidence and current original state before host enrollment.

    The caller must hold ``recovery_lock`` across validation and enrollment. Receipt integrity
    is not current execution authority: the enrollment caller separately checks source CI,
    human approval, host identity and effect readback. No artifact or state is written here.
    """
    if not all(
        path.is_absolute() for path in (original_directory, recovery_directory, source_snapshot)
    ):
        raise ValueError("Foundation recovery handover paths must be absolute")
    receipt = _json(recovery_directory / "recovery-apply-receipt.json")
    review = _json(recovery_directory / "recovery-review.json")
    for record in (receipt, review):
        digest_key = "receipt_digest" if record is receipt else "review_digest"
        if canonical_digest(
            {key: value for key, value in record.items() if key != digest_key}
        ) != record.get(digest_key):
            raise ValueError("Foundation recovery handover evidence digest is invalid")
    if (
        receipt.get("receipt_digest") != expected_digest
        or receipt.get("schema_version") != "fdai.foundation-recovery-receipt.v1"
        or receipt.get("state") != "verified"
        or receipt.get("review_digest") != review.get("review_digest")
        or review.get("schema_version") != "fdai.foundation-recovery-review.v1"
        or review.get("state") != "review"
        or review.get("application_group_absent") is not True
        or review.get("original_state_unchanged") is not True
        or review.get("target_binding") != target_binding
        or receipt.get("execution_source_commit") != review.get("recovery_source_commit")
        or receipt.get("source_commit") != review.get("source_commit")
        or any(
            receipt.get(field) is not True
            for field in (
                "control_plane_readback_verified",
                "zero_change_verified",
                "mutation_performed",
            )
        )
        or any(
            receipt.get(field) is not False
            for field in (
                "remote_backend_authority_verified",
                "runner_attested",
                "deployment_ready",
            )
        )
        or any(
            review.get(field) is not False
            for field in ("apply_authorized", "mutation_performed", "deployment_ready")
        )
    ):
        raise ValueError("Foundation recovery handover is not a verified matching recovery")
    claim = _json(recovery_directory / "recovery-apply-claim.json")
    _validate_claim(claim, review)
    if canonical_digest(claim) != receipt.get("claim_digest"):
        raise ValueError("Foundation recovery handover claim differs from the receipt")
    profile = load_profile(original_directory.parent / "profile.json")
    if (
        profile.target_binding != target_binding
        or profile.environment != "dev"
        or profile.transport != "manual"
    ):
        raise ValueError("Foundation recovery handover target or profile differs")
    verify_foundation_plan(
        directory=original_directory,
        profile=profile,
        expected_review_digest=str(review["original_review_digest"]),
        require_unexpired=False,
    )
    prior = _json(original_directory / "foundation-plan.json")
    original_claim = load_apply_claim(
        original_directory / "foundation-apply-claim.json", review=prior, profile=profile
    )
    if original_claim is None or canonical_digest(original_claim) != review.get(
        "original_claim_digest"
    ):
        raise ValueError("Foundation recovery handover original claim differs")
    context = cast(dict[str, Any], prior["context"])
    snapshot = verify_source_snapshot(
        source_snapshot, expected_digest=str(context["source_snapshot_digest"])
    )
    if (
        canonical_digest(snapshot) != context["source_input_digest"]
        or context["source_commit"] != receipt["source_commit"]
    ):
        raise ValueError("Foundation recovery handover original source differs")
    state_path = (
        original_directory
        / "foundation-apply-bundle/source/infra/genesis-foundation/terraform.tfstate"
    )
    state_bytes = read_private_bytes(state_path, max_bytes=64 * 1024 * 1024)
    if hashlib.sha256(state_bytes).hexdigest() != receipt.get("state_digest"):
        raise ValueError("Foundation recovery handover current state differs from the receipt")
    state = load_json_object(
        state_bytes, label="Foundation recovery state", max_bytes=64 * 1024 * 1024
    )
    if canonical_digest({"lineage": state.get("lineage")}) != review.get("original_lineage_digest"):
        raise ValueError("Foundation recovery handover state lineage differs")
    handoff = _json(recovery_directory / "recovery-private-handoff.json")
    if (
        canonical_digest(handoff) != receipt.get("handoff_digest")
        or handoff.get("source_commit") != receipt["source_commit"]
        or handoff.get("run_digest") != context["run_digest"]
        or compute_target_binding(
            tenant_id=str(handoff.get("tenant_id")),
            subscription_id=str(handoff.get("subscription_id")),
        )
        != target_binding
    ):
        raise ValueError("Foundation recovery private handoff context differs")
    return RecoveryHandoff(receipt, handoff, target_binding)


def require_enrollment_approval(
    path: Path | None, *, receipt_digest: str, source_commit: str
) -> str:
    """Require a fresh human approval of this recovered host, not the previous apply approval."""
    approval = load_genesis_approval(path, run_binding=receipt_digest, source_commit=source_commit)
    if (
        approval is None
        or not approval.authorizes("runner-enrollment", foundation_receipt_digest=receipt_digest)
        or approval.actor_digest != current_actor_digest(receipt_digest)
    ):
        raise ValueError("recovered host enrollment requires current exact human approval")
    return approval.actor_digest
