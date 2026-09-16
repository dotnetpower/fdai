"""Resume recovered source Foundation without changing its original application snapshot."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import genesis_foundation_state as state_command
import genesis_foundation_state_contract as state_contract
import genesis_runner_enrollment as enrollment_command
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes
from fdai_deployment_cli.profile import load_profile
from fdai_deployment_cli.runtime_release import RUNTIME_SERVICES
from fdai_deployment_cli.source_input import inspect_source
from fdai_deployment_cli.source_recovery import retained_source_run
from genesis_approval import GenesisApprovalExpiredError, load_genesis_approval
from genesis_checks import _GITHUB_REMOTE, CheckError, GenesisChecks
from genesis_foundation_recovery_handoff import load_recovery_evidence, recovery_lock
from genesis_foundation_recovery_plan import _json
from genesis_foundation_recovery_state import prepare_recovery_migration
from source_application_transport import transfer_application_source
from source_image_build import build_source_images


def resume(args: argparse.Namespace) -> dict[str, object]:
    """Advance only receipt-bound host enrollment and state migration, never Foundation apply.

    Each effect owns the original execution lock in its existing entrypoint. Source and
    installation context are independently checked; progress is a separate immutable
    record and does not rewrite old status or promote deployment readiness.
    """
    deadline = DeploymentDeadline(args.timeout_seconds)
    source = inspect_source(Path(__file__).resolve().parents[3])
    work, recovery = args.work_dir.absolute(), args.recovery_directory.absolute()
    prepared = retained_source_run(
        work,
        runtime_profile_digest=args.runtime_profile_digest,
        region=args.region,
        monthly_cost_ceiling=args.monthly_cost_ceiling,
    )
    foundation_root = work / "foundation"
    marker = _json(foundation_root / "source-genesis.json")
    marker_digest = marker.pop("receipt_digest", None)
    profile = load_profile(foundation_root / "profile.json")
    review = _json(recovery / "recovery-review.json")
    review_digest = review.pop("review_digest", None)
    if (
        canonical_digest(marker) != marker_digest
        or marker.get("source_commit") != prepared["source_commit"]
        or marker.get("source_input_digest") != prepared["source_input_digest"]
        or marker.get("target_binding") != profile.target_binding
        or profile.region != args.region
        or profile.monthly_cost_ceiling != args.monthly_cost_ceiling
        or profile.environment != "dev"
        or profile.transport != "manual"
        or profile.connectivity != "online"
        or canonical_digest(review) != review_digest
        or review.get("schema_version") != "fdai.foundation-recovery-review.v1"
        or review.get("source_commit") != prepared["source_commit"]
        or review.get("target_binding") != profile.target_binding
    ):
        raise ValueError("source recovery differs from the original target, source or profile")
    status = _json(foundation_root / "status.json")
    report = status.get("foundation_report")
    plan = report.get("foundation_plan") if isinstance(report, dict) else None
    plan_ref = plan.get("plan_ref") if isinstance(plan, dict) else None
    if (
        not isinstance(plan_ref, str)
        or re.fullmatch(r"foundation-plan-attempt-[1-9][0-9]*", plan_ref) is None
    ):
        raise ValueError("source recovery requires the original bounded Foundation plan reference")
    original = foundation_root / plan_ref
    foundation_digest: str | None = None

    def finish(stage: str, reason: str, **evidence: object) -> dict[str, object]:
        source.reverify()
        deadline.remaining()
        result: dict[str, object] = {
            "schema_version": "fdai.source-recovery-progress.v1",
            "state": "review",
            "stage": stage,
            "reason_code": reason,
            "source_commit": prepared["source_commit"],
            "execution_source_commit": source.commit,
            "source_preparation_digest": prepared["receipt_digest"],
            "runtime_profile_digest": args.runtime_profile_digest,
            "snapshot_digest": prepared["source_snapshot_digest"],
            "target_binding": profile.target_binding,
            "recovery_review_digest": review_digest,
            "foundation_receipt_digest": foundation_digest,
            "provenance": "operator-selected-source",
            "release_signature_verified": False,
            "apply_authorized": False,
            "deployment_ready": False,
            "subscription_ready": False,
            "mutation_performed": foundation_digest is not None,
            **evidence,
        }
        result["receipt_digest"] = canonical_digest(result)
        path = recovery / f"source-recovery-progress-{result['receipt_digest']}.json"
        data = canonical_bytes(result)
        if path.exists() or path.is_symlink():
            if read_private_bytes(path, max_bytes=65536) != data:
                raise ValueError("source recovery progress evidence changed")
        else:
            write_private_bytes(path, data)
        return result

    receipt_path = recovery / "recovery-apply-receipt.json"
    if not receipt_path.exists() and not receipt_path.is_symlink():
        return finish("foundation-apply", "exact_foundation_recovery_apply_required")
    foundation_digest = str(_json(receipt_path).get("receipt_digest"))
    with recovery_lock(original):
        recovered = load_recovery_evidence(
            original_directory=original,
            recovery_directory=recovery,
            source_snapshot=work / "source-snapshot",
            expected_digest=foundation_digest,
            target_binding=profile.target_binding,
        )
        if recovered.handoff.get("run_digest") != marker.get("run_binding"):
            raise ValueError("source recovery run differs from its original Foundation")
    try:
        approval = load_genesis_approval(
            args.approval_file, run_binding=foundation_digest, source_commit=source.commit
        )
    except GenesisApprovalExpiredError:
        approval = None
    checks = GenesisChecks(source.root)
    remote = checks.capture(("git", "remote", "get-url", "origin"), "source_repository_unavailable")
    match = _GITHUB_REMOTE.fullmatch(remote)
    if match is None:
        raise ValueError("source recovery requires a recognized repository origin")
    repository = match.group("repository")
    common = [
        "--foundation-plan-directory",
        str(original),
        "--profile",
        str(foundation_root / "profile.json"),
        "--repository",
        repository,
        "--ssh-private-key",
        str(foundation_root / "runner_ed25519"),
        "--expected-foundation-receipt-digest",
        foundation_digest,
        "--foundation-recovery-directory",
        str(recovery),
        *(
            ("--recovery-approval-file", str(args.approval_file.absolute()))
            if args.approval_file is not None
            else ()
        ),
    ]
    enrollment_started = any(
        (recovery / name).exists() or (recovery / name).is_symlink()
        for name in (
            enrollment_command.CLAIM_NAME,
            enrollment_command.RECEIPT_NAME,
        )
    )
    if not enrollment_started and (
        approval is None
        or not approval.authorizes("runner-enrollment", foundation_receipt_digest=foundation_digest)
    ):
        return finish("runner-enrollment", "recovered_host_enrollment_approval_required")
    migration_started = any(
        (recovery / name).exists() or (recovery / name).is_symlink()
        for name in (
            state_command.CLAIM_NAME,
            state_command.RECEIPT_NAME,
        )
    )
    source.reverify()
    if migration_started:
        enrolled = state_contract.load_receipt(
            recovery / enrollment_command.RECEIPT_NAME,
            schema="fdai.genesis-runner-enrollment-receipt.v1",
            expected_digest=None,
        )
    else:
        enrolled = enrollment_command._execute(
            enrollment_command._parser().parse_args(
                [
                    *common,
                    "--original-source-snapshot",
                    str(work / "source-snapshot"),
                    "--timeout-seconds",
                    str(deadline.remaining(3600)),
                    "--resume-verification" if enrollment_started else "--approve",
                ]
            )
        )
    enrollment_digest = str(enrolled["receipt_digest"])
    if not migration_started and (
        approval is None
        or not approval.authorizes(
            "foundation-state",
            foundation_receipt_digest=foundation_digest,
            enrollment_receipt_digest=enrollment_digest,
        )
    ):
        return finish(
            "foundation-state",
            "recovered_state_migration_approval_required",
            enrollment_receipt_digest=enrollment_digest,
        )
    state_args = state_command._parser().parse_args(
        [
            *common,
            "--variables-file",
            str(recovery / "recovery-variables.json"),
            "--expected-enrollment-receipt-digest",
            enrollment_digest,
            "--source-snapshot",
            str(work / "source-snapshot"),
            "--source-snapshot-digest",
            str(prepared["source_snapshot_digest"]),
            "--terraform",
            str(work / "source-tools/terraform"),
            "--timeout-seconds",
            str(deadline.remaining(7200)),
            "--resume-verification" if migration_started else "--approve",
        ]
    )
    source.reverify()
    state = state_command._execute(state_args)
    with recovery_lock(original):
        context = prepare_recovery_migration(
            state_args,
            original_directory=original,
            root=source.root,
            profile=profile,
        )
        source.reverify()
        transfer = transfer_application_source(
            foundation_root=foundation_root,
            snapshot=work / "source-snapshot",
            snapshot_digest=str(prepared["source_snapshot_digest"]),
            source_commit=str(prepared["source_commit"]),
            target_binding=profile.target_binding,
            report={"state_handoff": state},
            timeout_seconds=deadline.remaining(),
            recovery=context,
        )
    images = build_source_images(
        work / "source-snapshot",
        work / "source-images",
        snapshot_digest=str(prepared["source_snapshot_digest"]),
        timeout_seconds=deadline.remaining(),
    )
    if (
        images.get("schema_version") == "fdai.source-image-builder.v1"
        and images.get("state") == "blocked"
    ):
        return finish(
            "source-image-tools", "local_docker_buildx_required", source_host_transfer=transfer
        )
    services = images.get("services")
    if (
        images.get("schema_version") != "fdai.source-images.v1"
        or images.get("state") != "built"
        or images.get("source_commit") != prepared["source_commit"]
        or images.get("snapshot_digest") != prepared["source_snapshot_digest"]
        or images.get("provenance") != "operator-selected-source"
        or not isinstance(services, dict)
        or set(services) != RUNTIME_SERVICES
        or any(
            images.get(key) is not False
            for key in (
                "registry_published",
                "dependency_images_verified",
                "apply_authorized",
                "deployment_ready",
                "mutation_performed",
            )
        )
        or canonical_digest(
            {key: value for key, value in images.items() if key != "receipt_digest"}
        )
        != images.get("receipt_digest")
    ):
        raise ValueError(
            "source recovery image inventory differs from the original application snapshot"
        )
    return finish(
        "application-plan",
        "source_application_execution_not_connected",
        enrollment_receipt_digest=enrollment_digest,
        state_handoff_digest=state["receipt_digest"],
        source_host_transfer=transfer,
        source_images=images,
    )


def main() -> int:
    """Run explicit noninteractive recovery and emit only sanitized progress."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--recovery-directory", type=Path, required=True)
    parser.add_argument("--runtime-profile-digest", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--monthly-cost-ceiling", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=14400)
    parser.add_argument("--approval-file", type=Path)
    try:
        print(json.dumps(resume(parser.parse_args()), sort_keys=True))
        return 0
    except (CheckError, OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        print(
            "source recovery failed; preserve original state, claims and private diagnostics",
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
