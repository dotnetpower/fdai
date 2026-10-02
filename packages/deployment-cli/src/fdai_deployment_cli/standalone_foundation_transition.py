"""Review and receipt helpers for offline Foundation lineage transitions."""

from __future__ import annotations

import json
import re
import select
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.foundation_adoption import write_lineage_adoption_receipt
from fdai_deployment_cli.foundation_plan import REVIEW_NAME
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output

_DIGEST = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_PLAN_REF = re.compile(r"foundation-plan-attempt-[1-9][0-9]*")
_ACTION_KEYS = frozenset({"create", "update", "delete", "replace", "read", "no-op"})


def approve_transition_plan(plan_directory: Path) -> None:
    """Approve one reviewed Foundation transition plan, with extra confirmation for destruction."""

    review = _load_transition_review(plan_directory)
    destructive = _destructive_count(review)
    expected = "foundation-transition-apply"
    print(json.dumps(review, indent=2, sort_keys=True), file=sys.stderr)
    print(f"Approved by this invocation: {expected}", file=sys.stderr, flush=True)
    if destructive:
        print(
            f"Foundation transition contains {destructive} delete or replacement action(s); "
            f"type {expected}-destructive to approve: ",
            end="",
            file=sys.stderr,
            flush=True,
        )
        if _approval_input(timeout_seconds=600) != f"{expected}-destructive":
            raise ValueError("standalone destructive Foundation transition approval was denied")


def bind_foundation_lineage_transition(
    *,
    run_root: Path,
    plan_ref: str,
    application_source_commit: str,
    kit_manifest_digest: str,
    runtime_release_digest: str,
    tenant_id: str,
    subscription_id: str,
    region: str,
    monthly_cost_ceiling: int,
) -> dict[str, object]:
    """Write a receipt that binds the verified retained Foundation chain to the newer kit."""

    if _PLAN_REF.fullmatch(plan_ref) is None:
        raise ValueError("Foundation transition plan reference is invalid")
    plan_directory = run_root / plan_ref
    review = _load_transition_review(plan_directory, allow_expired=True)
    adoption = write_lineage_adoption_receipt(
        run_root=run_root,
        plan_directory=plan_directory,
        application_source_commit=application_source_commit,
        kit_manifest_digest=kit_manifest_digest,
        runtime_release_digest=runtime_release_digest,
        tenant_id=tenant_id,
        subscription_id=subscription_id,
        region=region,
        monthly_cost_ceiling=monthly_cost_ceiling,
    )
    receipt: dict[str, object] = {
        "schema_version": "fdai.foundation-lineage-transition.v1",
        "state": "verified",
        "foundation_source_commit": adoption["foundation_source_commit"],
        "application_source_commit": application_source_commit,
        "foundation_run_binding": adoption["foundation_run_binding"],
        "adopted_run_binding": adoption["adopted_run_binding"],
        "target_binding": adoption["target_binding"],
        "plan_ref": plan_ref,
        "transition_review_digest": review["review_digest"],
        "transition_plan_digest": review["plan_digest"],
        "foundation_adoption_receipt_digest": adoption["receipt_digest"],
        "foundation_apply_receipt_digest": adoption["foundation_recovery_receipt_digest"],
        "foundation_enrollment_receipt_digest": adoption["foundation_enrollment_receipt_digest"],
        "foundation_state_receipt_digest": adoption["foundation_state_receipt_digest"],
        "foundation_state_authority_digest": adoption["foundation_state_authority_digest"],
        "kit_manifest_digest": kit_manifest_digest,
        "runtime_release_digest": runtime_release_digest,
        "destructive_action_count": _destructive_count(review),
        "mutation_performed": _mutation_performed(review),
        "zero_change_verified": True,
        "deployment_ready": False,
        "subscription_ready": False,
        "verified_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    _validate_transition_receipt(receipt)
    receipt["receipt_digest"] = canonical_digest(receipt)
    path = run_root / "foundation-lineage-transition-receipt.json"
    content = json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
    if path.exists() or path.is_symlink():
        if read_private_bytes(path, max_bytes=65_536).decode("utf-8") == content:
            return receipt
        path.unlink()
    write_private_output(path, content)
    return receipt


def write_verified_source_lineage(
    path: Path,
    *,
    foundation_source_commit: str,
    application_source_commit: str,
    kit_manifest_digest: str,
    runtime_release_digest: str,
) -> None:
    """Persist the split source lineage only after transition verification succeeds."""

    if (
        _COMMIT.fullmatch(foundation_source_commit) is None
        or _COMMIT.fullmatch(application_source_commit) is None
        or _DIGEST.fullmatch(kit_manifest_digest) is None
        or _DIGEST.fullmatch(runtime_release_digest) is None
    ):
        raise ValueError("verified Foundation source lineage is invalid")
    payload = {
        "schema_version": "fdai.standalone-foundation-source-lineage.v1",
        "foundation_source_commit": foundation_source_commit,
        "application_source_commit": application_source_commit,
        "kit_manifest_digest": kit_manifest_digest,
        "runtime_release_digest": runtime_release_digest,
    }
    content = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    if path.exists() or path.is_symlink():
        if read_private_bytes(path, max_bytes=4096).decode("utf-8") == content:
            return
        path.unlink()
    write_private_output(path, content)


def _load_transition_review(plan_directory: Path, *, allow_expired: bool = False) -> dict[str, Any]:
    value = load_json_object(
        read_private_bytes(plan_directory / REVIEW_NAME, max_bytes=1_048_576),
        label="Foundation transition review",
    )
    _validate_transition_review(value, allow_expired=allow_expired)
    return {str(key): item for key, item in value.items()}


def _validate_transition_review(review: dict[str, Any], *, allow_expired: bool = False) -> None:
    summary = review.get("summary")
    if (
        review.get("schema_version") != "fdai.foundation-saved-plan.v1"
        or review.get("state") != "review"
        or review.get("apply_authorized") is not False
        or review.get("mutation_performed") is not False
        or review.get("subscription_ready") is not False
        or not isinstance(summary, dict)
    ):
        raise ValueError("Foundation transition review is invalid")
    for key in ("plan_digest", "plan_json_digest", "review_digest"):
        if not isinstance(review.get(key), str) or _DIGEST.fullmatch(str(review[key])) is None:
            raise ValueError("Foundation transition review is invalid")
    context = review.get("context")
    if (
        not isinstance(context, dict)
        or not isinstance(context.get("source_commit"), str)
        or _COMMIT.fullmatch(str(context["source_commit"])) is None
    ):
        raise ValueError("Foundation transition review context is invalid")
    expires = review.get("expires_at")
    if not isinstance(expires, str):
        raise ValueError("Foundation transition review is invalid")
    try:
        parsed = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Foundation transition review is invalid") from exc
    if parsed.tzinfo is None or (not allow_expired and parsed <= datetime.now(UTC)):
        raise ValueError("Foundation transition review is invalid or expired")
    unsigned = {key: value for key, value in review.items() if key != "review_digest"}
    if review["review_digest"] != canonical_digest(unsigned):
        raise ValueError("Foundation transition review digest differs")
    _summary_counts(summary)


def _summary_counts(summary: dict[str, Any]) -> dict[str, int]:
    counts = summary.get("action_counts")
    if (
        not isinstance(counts, dict)
        or set(counts) != _ACTION_KEYS
        or any(type(value) is not int or not 0 <= value <= 5000 for value in counts.values())
    ):
        raise ValueError("Foundation transition summary is invalid")
    changes = summary.get("resource_changes")
    if not isinstance(changes, list) or len(changes) > 5000:
        raise ValueError("Foundation transition summary is invalid")
    for change in changes:
        actions = change.get("actions") if isinstance(change, dict) else None
        address = change.get("address") if isinstance(change, dict) else None
        if (
            not isinstance(change, dict)
            or set(change) != {"address", "actions"}
            or not isinstance(address, str)
            or not 0 < len(address) <= 512
            or not address.isascii()
            or not address.isprintable()
            or not isinstance(actions, list)
            or any(not isinstance(action, str) or action not in _ACTION_KEYS for action in actions)
        ):
            raise ValueError("Foundation transition summary is invalid")
    return {str(key): int(value) for key, value in counts.items()}


def _destructive_count(review: dict[str, Any]) -> int:
    counts = _summary_counts(review["summary"])
    return counts["delete"] + counts["replace"]


def _mutation_performed(review: dict[str, Any]) -> bool:
    counts = _summary_counts(review["summary"])
    return any(counts[name] for name in ("create", "update", "delete", "replace"))


def _validate_transition_receipt(receipt: dict[str, object]) -> None:
    for key in (
        "foundation_run_binding",
        "adopted_run_binding",
        "target_binding",
        "transition_review_digest",
        "transition_plan_digest",
        "foundation_adoption_receipt_digest",
        "foundation_apply_receipt_digest",
        "foundation_enrollment_receipt_digest",
        "foundation_state_receipt_digest",
        "foundation_state_authority_digest",
        "kit_manifest_digest",
        "runtime_release_digest",
    ):
        if not isinstance(receipt.get(key), str) or _DIGEST.fullmatch(str(receipt[key])) is None:
            raise ValueError("Foundation transition receipt digest is invalid")
    if any(
        not isinstance(receipt.get(key), str) or _COMMIT.fullmatch(str(receipt[key])) is None
        for key in ("foundation_source_commit", "application_source_commit")
    ):
        raise ValueError("Foundation transition receipt source revision is invalid")
    destructive_action_count = receipt.get("destructive_action_count")
    if (
        receipt["foundation_source_commit"] == receipt["application_source_commit"]
        or type(destructive_action_count) is not int
        or destructive_action_count < 0
        or receipt.get("zero_change_verified") is not True
        or receipt.get("deployment_ready") is not False
        or receipt.get("subscription_ready") is not False
    ):
        raise ValueError("Foundation transition receipt is invalid")


def _approval_input(*, timeout_seconds: int = 600) -> str:
    """Treat a closed input stream as denial, never as approval or an implicit retry."""

    if timeout_seconds <= 0:
        raise TimeoutError("standalone approval deadline expired; no approval was granted")
    if not sys.stdin.isatty():
        raise ValueError("standalone approval requires an interactive terminal")
    try:
        readable, _, _ = select.select([sys.stdin], [], [], timeout_seconds)
    except (OSError, ValueError):
        raise ValueError("standalone approval input is unavailable") from None
    if not readable:
        raise TimeoutError("standalone approval input timed out; no approval was granted")
    try:
        return input("").strip()
    except EOFError as exc:
        raise ValueError("approval input closed; no new approval was granted") from exc
