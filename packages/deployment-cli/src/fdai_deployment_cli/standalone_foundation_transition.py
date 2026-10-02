"""Detect and bind offline Foundation lineage transitions."""

from __future__ import annotations

import hashlib
import json
import re
import select
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai_deployment_cli.bundle import verify_bundle
from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.deployment_kit import DeploymentKit
from fdai_deployment_cli.foundation_adoption import write_lineage_adoption_receipt
from fdai_deployment_cli.foundation_plan import REVIEW_NAME
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from fdai_deployment_cli.trust_roots import deployment_bundle_root_pem

_COMMIT = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_PLAN_REF = re.compile(r"foundation-plan-attempt-[1-9][0-9]*")
_TRANSITION_REF = re.compile(r"foundation-transition-attempt-[1-9][0-9]*")
_ACTION_KEYS = frozenset({"create", "update", "delete", "replace", "read", "no-op"})
_INPUT_KEYS = (
    "terraform_root_digest",
    "provider_lock_digest",
    "bootstrap_artifacts_digest",
    "runner_image_toolchain_digest",
    "terraform_digest",
    "runner_image_observation_digest",
)


@dataclass(frozen=True, slots=True)
class TransitionDecision:
    """Foundation input comparison result for an offline kit upgrade."""

    changed: bool
    current_inputs: dict[str, str]
    retained_inputs: dict[str, str]
    changed_keys: tuple[str, ...]


TransitionRunner = Callable[..., dict[str, object]]


def decide_foundation_transition(
    *,
    kit: DeploymentKit,
    run_root: Path,
    retained_plan_ref: str,
) -> TransitionDecision:
    """Compare precise Foundation inputs while failing closed without the retained baseline."""

    retained_plan = _retained_plan_dir(run_root, retained_plan_ref)
    retained_review = _load_review(retained_plan, allow_expired=True, require_summary=False)
    current = _current_input_digests(kit, retained_review)
    retained = _verified_transition_inputs(run_root) or _retained_input_digests(
        retained_plan, retained_review
    )
    changed = tuple(key for key in _INPUT_KEYS if current.get(key) != retained.get(key))
    return TransitionDecision(
        changed=bool(changed),
        current_inputs=current,
        retained_inputs=retained,
        changed_keys=changed,
    )


def run_foundation_transition(
    *,
    kit: DeploymentKit,
    run_root: Path,
    retained_plan_ref: str,
    transition_plan_ref: str | None,
    application_source_commit: str,
    kit_manifest_digest: str,
    runtime_release_digest: str,
    tenant_id: str,
    subscription_id: str,
    region: str,
    monthly_cost_ceiling: int,
    transition_runner: TransitionRunner | None = None,
    plan_runner: TransitionRunner | None = None,
) -> dict[str, object]:
    """Run plan-review-approve-apply-verify, then return the adoption receipt."""

    runner = transition_runner or plan_runner or default_transition_runner
    retained_plan = _retained_plan_dir(run_root, retained_plan_ref)
    decision = decide_foundation_transition(
        kit=kit,
        run_root=run_root,
        retained_plan_ref=retained_plan_ref,
    )
    if not decision.changed:
        return write_lineage_adoption_receipt(
            run_root=run_root,
            plan_directory=retained_plan,
            application_source_commit=application_source_commit,
            kit_manifest_digest=kit_manifest_digest,
            runtime_release_digest=runtime_release_digest,
            tenant_id=tenant_id,
            subscription_id=subscription_id,
            region=region,
            monthly_cost_ceiling=monthly_cost_ceiling,
        )
    transition_ref = _select_transition_ref(run_root, transition_plan_ref)
    transition_dir = run_root / transition_ref
    transition_dir.mkdir(mode=0o700, exist_ok=True)
    claim_exists = (transition_dir / "foundation-transition-claim.json").exists()
    receipt_exists = (transition_dir / "foundation-transition-remote-receipt.json").exists()
    if claim_exists or receipt_exists:
        review = _load_review(transition_dir, require_summary=True)
        plan_result = _plan_result_from_review(review)
    else:
        plan_result = runner(
            operation="plan",
            kit=kit,
            run_root=run_root,
            retained_plan_ref=retained_plan_ref,
            transition_plan_ref=transition_ref,
            decision=decision,
        )
        review = _write_transition_review(transition_dir, plan_result)
    if not (claim_exists or receipt_exists):
        approve_transition_plan(transition_dir)
    operation = (
        "verify" if claim_exists or plan_result.get("zero_change_verified") is True else "apply"
    )
    apply_result = runner(
        operation=operation,
        kit=kit,
        run_root=run_root,
        retained_plan_ref=retained_plan_ref,
        transition_plan_ref=transition_ref,
        decision=decision,
        expected_review_digest=plan_result["review_digest"],
        expected_plan_digest=plan_result["plan_digest"],
    )
    adoption = write_lineage_adoption_receipt(
        run_root=run_root,
        plan_directory=retained_plan,
        application_source_commit=application_source_commit,
        kit_manifest_digest=kit_manifest_digest,
        runtime_release_digest=runtime_release_digest,
        tenant_id=tenant_id,
        subscription_id=subscription_id,
        region=region,
        monthly_cost_ceiling=monthly_cost_ceiling,
    )
    receipt = _transition_receipt(
        adoption=adoption,
        decision=decision,
        retained_plan_ref=retained_plan_ref,
        transition_ref=transition_ref,
        review=review,
        apply_result=apply_result,
        application_source_commit=application_source_commit,
        kit_manifest_digest=kit_manifest_digest,
        runtime_release_digest=runtime_release_digest,
    )
    _write_verified_receipt(run_root / "foundation-lineage-transition-receipt.json", receipt)
    return adoption


def approve_transition_plan(plan_directory: Path) -> None:
    """Approve one reviewed transition plan, with exact extra confirmation for destruction."""

    review = _load_review(plan_directory, require_summary=True)
    destructive = _destructive_count(review)
    print(json.dumps(review, indent=2, sort_keys=True), file=sys.stderr)
    print("Approved by this invocation: foundation-transition-apply", file=sys.stderr, flush=True)
    if destructive:
        print(
            f"Foundation transition contains {destructive} delete or replacement action(s); "
            "type foundation-transition-apply-destructive to approve: ",
            end="",
            file=sys.stderr,
            flush=True,
        )
        if _approval_input(timeout_seconds=600) != "foundation-transition-apply-destructive":
            raise ValueError("standalone destructive Foundation transition approval was denied")


def default_transition_runner(**kwargs: object) -> dict[str, object]:
    """Call the verified kit's transition transport script with supported options only."""

    kit = kwargs["kit"]
    run_root = kwargs["run_root"]
    retained_plan_ref = kwargs["retained_plan_ref"]
    transition_plan_ref = kwargs["transition_plan_ref"]
    operation = kwargs["operation"]
    if (
        not hasattr(kit, "root")
        or not hasattr(kit, "bundle_root")
        or not isinstance(run_root, Path)
        or not isinstance(retained_plan_ref, str)
        or not isinstance(transition_plan_ref, str)
        or operation not in {"plan", "apply", "verify"}
    ):
        raise TypeError("Foundation transition runner received invalid inputs")
    command = [
        sys.executable,
        str(kit.bundle_root / "scripts/deployment/azure/genesis_foundation_transition.py"),
        str(operation),
        "--retained-plan-directory",
        str(run_root / retained_plan_ref),
        "--transition-directory",
        str(run_root / transition_plan_ref),
        "--profile",
        str(run_root / "profile.json"),
        "--variables-file",
        str(run_root / "foundation-variables.json"),
        "--offline-kit",
        str(kit.root),
        "--release-root",
        str(run_root / "deployment-release-root.pub"),
        "--bundle-public-key",
        str(run_root / "deployment-bundle-root.pub"),
        "--ssh-private-key",
        str(run_root / "runner_ed25519"),
        "--expected-foundation-receipt-digest",
        _status_receipt_digest(run_root, "foundation_apply"),
        "--expected-enrollment-receipt-digest",
        _status_receipt_digest(run_root, "runner_enrollment"),
        "--output",
        "json",
    ]
    script_operation = "verify" if operation == "verify" else str(operation)
    command[2] = script_operation
    if operation in {"apply", "verify"}:
        command.extend(
            [
                "--expected-review-digest",
                str(kwargs["expected_review_digest"]),
                "--expected-plan-digest",
                str(kwargs["expected_plan_digest"]),
            ]
        )
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=14_415)
    if completed.returncode != 0:
        raise ValueError("Foundation transition remote operation failed")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise ValueError("Foundation transition result is invalid")
    return {str(key): item for key, item in value.items()}


def _current_input_digests(
    kit: DeploymentKit, retained_review: Mapping[str, object]
) -> dict[str, str]:
    root = kit.bundle_root / "infra"
    context = _context(retained_review)
    return {
        "terraform_root_digest": _tree_digest(root / "genesis-foundation"),
        "provider_lock_digest": _file_digest(root / "genesis-foundation/.terraform.lock.hcl"),
        "bootstrap_artifacts_digest": _optional_tree_digest(root / "bootstrap"),
        "runner_image_toolchain_digest": _tree_digest(root / "genesis-runner-image"),
        "terraform_digest": str(
            dict(kit.verification.file_digests)[kit.verification.terraform_binary]
        ),
        "runner_image_observation_digest": str(context["runner_image_observation_digest"]),
    }


def _retained_input_digests(
    retained_plan: Path, retained_review: Mapping[str, object]
) -> dict[str, str]:
    context = _context(retained_review)
    root = _retained_bundle_root(retained_plan, context)
    infra = root / "infra"
    terraform_digest = _find_digest(retained_plan / "artifacts", str(context["terraform_digest"]))
    return {
        "terraform_root_digest": _tree_digest(infra / "genesis-foundation"),
        "provider_lock_digest": _file_digest_checked(
            infra / "genesis-foundation/.terraform.lock.hcl",
            str(context["provider_lock_digest"]),
        ),
        "bootstrap_artifacts_digest": _optional_tree_digest(infra / "bootstrap"),
        "runner_image_toolchain_digest": _tree_digest(infra / "genesis-runner-image"),
        "terraform_digest": terraform_digest,
        "runner_image_observation_digest": str(context["runner_image_observation_digest"]),
    }


def _verified_transition_inputs(run_root: Path) -> dict[str, str] | None:
    path = run_root / "foundation-lineage-transition-receipt.json"
    if not path.exists() and not path.is_symlink():
        return None
    value = load_json_object(read_private_bytes(path, max_bytes=1_048_576), label="transition")
    if not isinstance(value, dict):
        raise ValueError("Foundation transition receipt is invalid")
    digest = value.get("receipt_digest")
    unsigned = {key: item for key, item in value.items() if key != "receipt_digest"}
    inputs = value.get("current_input_digests")
    if (
        value.get("schema_version") != "fdai.foundation-lineage-transition.v2"
        or not isinstance(digest, str)
        or canonical_digest(unsigned) != digest
        or not isinstance(inputs, dict)
        or any(
            not isinstance(key, str) or not isinstance(item, str) for key, item in inputs.items()
        )
    ):
        raise ValueError("Foundation transition receipt is invalid")
    return {str(key): str(item) for key, item in inputs.items()}


def _retained_bundle_root(retained_plan: Path, context: Mapping[str, object]) -> Path:
    candidates = []
    for parent in (retained_plan / "foundation-apply-bundle", retained_plan / "bundle"):
        if parent.exists() and parent.is_dir() and not parent.is_symlink():
            children = [child for child in parent.iterdir() if child.is_dir()]
            candidates.extend(children or [parent])
    for candidate in candidates:
        try:
            verification = verify_bundle(
                candidate,
                public_key_pem=deployment_bundle_root_pem(),
            )
        except ValueError:
            continue
        if verification.manifest_digest == context["deployment_bundle_digest"]:
            return candidate
    raise ValueError("foundation_transition_baseline_unverifiable")


def _find_digest(root: Path, expected: str) -> str:
    if not root.exists() or not root.is_dir():
        raise ValueError("foundation_transition_baseline_unverifiable")
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink() and _file_digest(path) == expected:
            return expected
    raise ValueError("foundation_transition_baseline_unverifiable")


def _write_transition_review(directory: Path, result: Mapping[str, object]) -> dict[str, object]:
    summary = result.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("Foundation transition plan summary is invalid")
    review: dict[str, object] = {
        "schema_version": "fdai.foundation-transition-review.v1",
        "state": "review",
        "plan_digest": _required_digest(result, "plan_digest"),
        "plan_json_digest": _required_digest(result, "plan_json_digest"),
        "remote_state_digest": _required_digest(result, "remote_state_digest"),
        "archive_digest": _required_digest(result, "archive_digest"),
        "helper_digest": _required_digest(result, "helper_digest"),
        "transport_review_digest": _required_digest(result, "review_digest"),
        "summary": summary,
        "transport_zero_change_verified": result.get("zero_change_verified") is True,
        "mutation_performed": False,
        "subscription_ready": False,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    review["review_digest"] = canonical_digest(review)
    _write_verified_receipt(directory / REVIEW_NAME, review)
    return review


def _transition_receipt(
    *,
    adoption: Mapping[str, object],
    decision: TransitionDecision,
    retained_plan_ref: str,
    transition_ref: str,
    review: Mapping[str, object],
    apply_result: Mapping[str, object],
    application_source_commit: str,
    kit_manifest_digest: str,
    runtime_release_digest: str,
) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": "fdai.foundation-lineage-transition.v2",
        "state": "verified",
        "foundation_source_commit": adoption["foundation_source_commit"],
        "application_source_commit": application_source_commit,
        "foundation_run_binding": adoption["foundation_run_binding"],
        "adopted_run_binding": adoption["adopted_run_binding"],
        "target_binding": adoption["target_binding"],
        "retained_plan_ref": retained_plan_ref,
        "transition_plan_ref": transition_ref,
        "changed_input_keys": list(decision.changed_keys),
        "current_input_digests": decision.current_inputs,
        "retained_input_digests": decision.retained_inputs,
        "transition_review_digest": review["review_digest"],
        "transition_transport_review_digest": review["transport_review_digest"],
        "transition_plan_digest": review["plan_digest"],
        "transition_plan_json_digest": review["plan_json_digest"],
        "transition_plan_summary_digest": _summary_digest(review),
        "transition_remote_state_digest": apply_result["remote_state_digest"],
        "transition_remote_plan_digest": apply_result["plan_json_digest"],
        "transition_remote_receipt_digest": apply_result["receipt_digest"],
        "foundation_adoption_receipt_digest": adoption["receipt_digest"],
        "foundation_apply_receipt_digest": adoption["foundation_recovery_receipt_digest"],
        "foundation_enrollment_receipt_digest": adoption["foundation_enrollment_receipt_digest"],
        "foundation_state_receipt_digest": adoption["foundation_state_receipt_digest"],
        "foundation_state_authority_digest": adoption["foundation_state_authority_digest"],
        "kit_manifest_digest": kit_manifest_digest,
        "runtime_release_digest": runtime_release_digest,
        "destructive_action_count": _destructive_count(review),
        "mutation_performed": apply_result.get("mutation_performed") is True,
        "zero_change_verified": apply_result.get("zero_change_verified") is True,
        "deployment_ready": False,
        "subscription_ready": False,
        "verified_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    return receipt


def _load_review(
    plan_directory: Path, *, allow_expired: bool = False, require_summary: bool = False
) -> dict[str, Any]:
    value = load_json_object(
        read_private_bytes(plan_directory / REVIEW_NAME, max_bytes=1_048_576),
        label="Foundation transition review",
    )
    if not isinstance(value, dict):
        raise ValueError("Foundation transition review is invalid")
    review = {str(key): item for key, item in value.items()}
    if review.get("schema_version") == "fdai.foundation-transition-review.v1":
        _validate_transition_review(review)
    else:
        _validate_retained_review(review, allow_expired=allow_expired)
        if require_summary and "summary" not in review:
            raise ValueError("Foundation transition review summary is invalid")
    return review


def _validate_retained_review(review: Mapping[str, object], *, allow_expired: bool) -> None:
    if (
        review.get("schema_version") != "fdai.foundation-saved-plan.v1"
        or review.get("state") != "review"
        or review.get("apply_authorized") is not False
        or review.get("mutation_performed") is not False
        or review.get("subscription_ready") is not False
    ):
        raise ValueError("Foundation transition review is invalid")
    _context(review)
    _validate_review_digest(review)
    expires = review.get("expires_at")
    if not isinstance(expires, str):
        raise ValueError("Foundation transition review is invalid")
    parsed = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    if parsed.tzinfo is None or (not allow_expired and parsed <= datetime.now(UTC)):
        raise ValueError("Foundation transition review is invalid or expired")


def _validate_transition_review(review: Mapping[str, object]) -> None:
    if (
        review.get("schema_version") != "fdai.foundation-transition-review.v1"
        or review.get("state") != "review"
        or review.get("mutation_performed") is not False
        or review.get("subscription_ready") is not False
    ):
        raise ValueError("Foundation transition review is invalid")
    for key in (
        "plan_digest",
        "plan_json_digest",
        "remote_state_digest",
        "archive_digest",
        "transport_review_digest",
    ):
        _required_digest(review, key)
    _summary_counts(review)
    _summary_digest(review)
    _validate_review_digest(review)


def _validate_review_digest(review: Mapping[str, object]) -> None:
    digest = review.get("review_digest")
    unsigned = {key: value for key, value in review.items() if key != "review_digest"}
    if not isinstance(digest, str) or canonical_digest(unsigned) != digest:
        raise ValueError("Foundation transition review digest differs")


def _context(review: Mapping[str, object]) -> Mapping[str, object]:
    context = review.get("context")
    if not isinstance(context, dict):
        raise ValueError("Foundation transition review context is invalid")
    for key in (
        "source_commit",
        "provider_lock_digest",
        "terraform_digest",
        "runner_image_observation_digest",
        "deployment_bundle_digest",
        "foundation_context_digest",
    ):
        value = context.get(key)
        pattern = _COMMIT if key == "source_commit" else _DIGEST
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise ValueError("Foundation transition review context is invalid")
    return context


def _destructive_count(review: Mapping[str, object]) -> int:
    counts = _summary_counts(review)
    return counts["delete"] + counts["replace"]


def _summary_counts(review: Mapping[str, object]) -> dict[str, int]:
    summary = review.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("Foundation transition review summary is invalid")
    counts = summary.get("action_counts")
    if (
        not isinstance(counts, dict)
        or set(counts) != _ACTION_KEYS
        or any(type(counts[key]) is not int or counts[key] < 0 for key in _ACTION_KEYS)
    ):
        raise ValueError("Foundation transition review summary is invalid")
    return {key: int(counts[key]) for key in _ACTION_KEYS}


def _summary_digest(review: Mapping[str, object]) -> str:
    summary = review.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("Foundation transition review summary is invalid")
    digest = summary.get("summary_digest")
    unsigned = {key: value for key, value in summary.items() if key != "summary_digest"}
    if not isinstance(digest, str) or canonical_digest(unsigned) != digest:
        raise ValueError("Foundation transition review summary digest differs")
    return digest


def _retained_plan_dir(run_root: Path, value: str) -> Path:
    if _PLAN_REF.fullmatch(value) is None:
        raise ValueError("Foundation retained plan reference is invalid")
    return run_root / value


def _transition_ref(value: str) -> str:
    if _TRANSITION_REF.fullmatch(value) is None:
        raise ValueError("Foundation transition reference is invalid")
    return value


def _next_transition_attempt(run_root: Path) -> int:
    attempts = [
        int(path.name.rsplit("-", 1)[1])
        for path in run_root.glob("foundation-transition-attempt-*")
        if _TRANSITION_REF.fullmatch(path.name)
    ]
    return max(attempts, default=0) + 1


def _select_transition_ref(run_root: Path, value: str | None) -> str:
    if value is not None:
        return _transition_ref(value)
    attempts = sorted(
        (
            path
            for path in run_root.glob("foundation-transition-attempt-*")
            if _TRANSITION_REF.fullmatch(path.name)
        ),
        key=lambda path: int(path.name.rsplit("-", 1)[1]),
        reverse=True,
    )
    for attempt in attempts:
        claim = attempt / "foundation-transition-claim.json"
        remote_receipt = attempt / "foundation-transition-remote-receipt.json"
        if claim.exists() and not remote_receipt.exists():
            return attempt.name
        if remote_receipt.exists():
            return attempt.name
    return f"foundation-transition-attempt-{_next_transition_attempt(run_root)}"


def _plan_result_from_review(review: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": "fdai.genesis-foundation-transition-plan.v1",
        "state": "review",
        "review_digest": review["transport_review_digest"],
        "archive_digest": review["archive_digest"],
        "helper_digest": review["helper_digest"],
        "remote_state_digest": review["remote_state_digest"],
        "plan_digest": review["plan_digest"],
        "plan_json_digest": review["plan_json_digest"],
        "summary": review["summary"],
        "zero_change_verified": review.get("transport_zero_change_verified") is True,
        "mutation_performed": False,
        "subscription_ready": False,
    }


def _status_receipt_digest(run_root: Path, field: str) -> str:
    status = load_json_object(
        read_private_bytes(run_root / "status.json", max_bytes=1_048_576),
        label="Foundation status",
    )
    report = status.get("foundation_report") if isinstance(status, dict) else None
    value = report.get(field) if isinstance(report, dict) else None
    digest = value.get("receipt_digest") if isinstance(value, dict) else None
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        raise ValueError("Foundation transition retained receipt digest is unavailable")
    return digest


def _required_digest(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or _DIGEST.fullmatch(item) is None:
        raise ValueError(f"Foundation transition {key} is invalid")
    return item


def _tree_digest(root: Path) -> str:
    if not root.exists() or not root.is_dir() or root.is_symlink():
        raise ValueError("foundation_transition_baseline_unverifiable")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if ".terraform" in relative.parts:
            continue
        details = path.lstat()
        if stat.S_ISDIR(details.st_mode):
            continue
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise ValueError("Foundation input tree contains an unsafe file")
        digest.update(relative.as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _optional_tree_digest(root: Path) -> str:
    return _tree_digest(root) if root.exists() else "0" * 64


def _file_digest(path: Path) -> str:
    details = path.lstat()
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        raise ValueError("Foundation input file is unsafe")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_digest_checked(path: Path, expected: str) -> str:
    observed = _file_digest(path)
    if observed != expected:
        raise ValueError("foundation_transition_baseline_unverifiable")
    return observed


def _write_verified_receipt(path: Path, receipt: Mapping[str, object]) -> None:
    content = json.dumps(dict(receipt), sort_keys=True, separators=(",", ":")) + "\n"
    if path.exists() or path.is_symlink():
        if read_private_bytes(path, max_bytes=1_048_576).decode("utf-8") == content:
            return
        path.unlink()
    write_private_output(path, content)


def _approval_input(*, timeout_seconds: int) -> str:
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
