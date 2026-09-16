#!/usr/bin/env python3
"""Prepare and advance exact-approved source Foundation without building a deployment kit."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fdai_deployment_cli.contracts import ProvisionProfile, canonical_digest
from fdai_deployment_cli.plan_input import read_plan_input, write_plan_input
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes
from fdai_deployment_cli.profile import load_profile, write_profile
from fdai_deployment_cli.source_input import SourceDeploymentInput, inspect_source
from fdai_deployment_cli.source_snapshot import verify_source_snapshot
from fdai_deployment_cli.standalone_deploy import active_azure_target
from fdai_deployment_cli.target import compute_target_binding
from genesis_approval import GenesisApprovalExpiredError, load_genesis_approval
from genesis_checks import _GITHUB_REMOTE, CheckError, GenesisChecks
from genesis_foundation import SourceFoundationPlanInputs
from genesis_prepare import _ensure_ed25519_key, _ensure_ssh_public_key, _private_directory
from genesis_prepare_inputs import foundation_values
from genesis_private_errors import PrivateExecutionError, PrivateExecutionWaitError
from genesis_private_execution import PrivateExecutionConfig, PrivateExecutionCoordinator
from genesis_status import StatusStore
from resource_provider_reconcile import reconcile_resource_providers


def prepare(args: argparse.Namespace) -> dict[str, object]:
    """Persist exact target/source inputs and an SSH key, never an artifact-signing key."""
    if re.fullmatch(r"[a-z][a-z0-9]{1,11}", args.workload) is None:
        raise ValueError("source Foundation workload token is invalid")
    source = inspect_source(Path(__file__).resolve().parents[3], expected_commit=args.source_commit)
    target = active_azure_target()
    binding = compute_target_binding(
        tenant_id=target.tenant_id, subscription_id=target.subscription_id
    )
    if binding != args.target_binding:
        raise ValueError("source Foundation target changed after preflight")
    root = args.work_dir.absolute()
    _private_directory(root)
    profile = ProvisionProfile(
        environment="dev",
        region=args.region,
        target_binding=binding,
        connectivity="online",
        host="managed-vm",
        transport="manual",
        access_method="bastion",
        shadow_only=True,
        approval_quorum=1,
        monthly_cost_ceiling=args.monthly_cost_ceiling,
    )
    profile_path = root / "profile.json"
    if profile_path.exists():
        if load_profile(profile_path) != profile:
            raise ValueError("source Foundation profile differs from retained input")
    else:
        write_profile(profile_path, profile)
    run_binding = canonical_digest(
        {
            "target_binding": binding,
            "source_input_digest": source.digest,
            "region": args.region,
            "provenance": "operator-selected-source",
            "runner_bootstrap_mode": "online",
            "workload": args.workload,
        }
    )
    ssh_key = root / "runner_ed25519"
    _ensure_ed25519_key(ssh_key, openssh=True)
    _ensure_ssh_public_key(ssh_key, root / "runner_ed25519.pub")
    variables = root / "foundation-variables.json"
    if variables.exists():
        values = read_plan_input(variables)
        if (
            values.get("source_commit") != source.commit
            or values.get("run_digest") != run_binding
            or values.get("target_binding") != binding
            or values.get("runner_bootstrap_mode") != "online"
            or values.get("workload") != args.workload
            or values.get("runner_source_image_id") != ""
            or not isinstance(values.get("runner_marketplace_image_version"), str)
            or not values["runner_marketplace_image_version"]
        ):
            raise ValueError("source Foundation retained variables differ")
    else:
        values = foundation_values(
            repository_root=source.root,
            source_commit=source.commit,
            tenant_id=target.tenant_id,
            subscription_id=target.subscription_id,
            region=args.region,
            target_binding=binding,
            run_binding=run_binding,
            ssh_public_key=read_private_bytes(root / "runner_ed25519.pub", max_bytes=16384)
            .decode("ascii")
            .strip(),
            execution_transport="manual",
            evidence_directory=root,
            create_runner_image=False,
            workload=args.workload,
        )
        write_plan_input(variables, values)
    source.reverify()
    result = {
        "schema_version": "fdai.source-genesis-preparation.v1",
        "state": "prepared",
        "source_commit": source.commit,
        "source_input_digest": source.digest,
        "target_binding": binding,
        "run_binding": run_binding,
        "mutation_performed": False,
        "deployment_ready": False,
    }
    result["receipt_digest"] = canonical_digest(result)
    marker = root / "source-genesis.json"
    data = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    if not marker.exists():
        write_private_bytes(marker, data)
    elif read_private_bytes(marker, max_bytes=65536) != data:
        raise ValueError("source Foundation preparation receipt differs")
    return result


def advance(args: argparse.Namespace) -> dict[str, object]:
    """Advance source Foundation checkpoints under a lock and exact per-stage approval."""
    if os.environ.get("FDAI_SIGNED_SOURCE_EVIDENCE") is not None:
        raise ValueError("source Foundation cannot adopt signed release evidence")
    if not 1800 <= args.timeout_seconds <= 14400:
        raise ValueError(
            "source Foundation execution budget must be from 1800 through 14400 seconds"
        )
    source = inspect_source(Path(__file__).resolve().parents[3], expected_commit=args.source_commit)
    snapshot = verify_source_snapshot(
        args.source_snapshot, expected_digest=args.source_snapshot_digest
    )
    if snapshot != source.to_mapping():
        raise ValueError("source Foundation snapshot differs from the active checkout")
    root = args.work_dir.absolute()
    _private_directory(root)
    marker = json.loads(read_private_bytes(root / "source-genesis.json", max_bytes=65536))
    marker_digest = marker.pop("receipt_digest", None)
    if (
        canonical_digest(marker) != marker_digest
        or marker.get("source_input_digest") != source.digest
        or marker.get("source_commit") != source.commit
        or marker.get("target_binding") != args.target_binding
        or read_plan_input(root / "foundation-variables.json").get("workload") != args.workload
    ):
        raise ValueError("source Foundation preparation receipt differs from execution")
    lock = os.open(
        root / "source-execution.lock",
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
        0o600,
    )
    try:
        details = os.fstat(lock)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.geteuid()
            or details.st_nlink != 1
            or stat.S_IMODE(details.st_mode) != 0o600
        ):
            raise ValueError("source Foundation execution lock is invalid")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("source Foundation execution is already active") from None
        return _advance_locked(args, source, root, str(marker["run_binding"]))
    finally:
        os.close(lock)


def _advance_locked(
    args: argparse.Namespace, source: SourceDeploymentInput, root: Path, run_binding: str
) -> dict[str, object]:
    target = active_azure_target()
    if (
        compute_target_binding(tenant_id=target.tenant_id, subscription_id=target.subscription_id)
        != args.target_binding
    ):
        raise ValueError("source Foundation human target changed")
    profile = load_profile(root / "profile.json")
    if (
        profile.target_binding != args.target_binding
        or profile.region != args.region
        or profile.environment != "dev"
        or profile.connectivity != "online"
        or profile.transport != "manual"
    ):
        raise ValueError("source Foundation profile differs from execution")
    store = StatusStore(
        path=root / "status.json",
        source_commit=source.commit,
        target_binding=run_binding,
        mode="apply",
        deadline_at=(datetime.now(UTC) + timedelta(seconds=args.timeout_seconds)).isoformat(),
    )
    checks = GenesisChecks(source.root)
    stage = "toolchain"
    try:
        checks.verify_toolchain(apply=False)
        store.update(stage=stage, state="running", completed=True)
        stage = "target"
        checks.verify_target(
            subscription_id=target.subscription_id, tenant_id=target.tenant_id, region=args.region
        )
        store.update(stage=stage, state="running", completed=True)
        remote = checks.capture(
            ("git", "remote", "get-url", "origin"), "source_repository_unavailable"
        )
        match = _GITHUB_REMOTE.fullmatch(remote)
        if match is None:
            raise ValueError("source Foundation requires a recognized repository origin")
        repository = match.group("repository")
        try:
            approval = load_genesis_approval(
                args.approval_file, run_binding=run_binding, source_commit=source.commit
            )
        except GenesisApprovalExpiredError:
            approval = None
        if approval is not None or store.mutation_performed:
            stage = "source"
            checks.verify_toolchain(apply=True)
            checks.verify_source(source_commit=source.commit, repository=repository, apply=True)
            store.update(stage=stage, state="running", completed=True)
            checks.prepare_access_tools(timeout=min(600, store.remaining_seconds()))
        stage = "providers"
        providers = reconcile_resource_providers(
            subscription_id=target.subscription_id,
            profile="foundation",
            apply=False,
            timeout_seconds=min(180, store.remaining_seconds()),
        )
        store.provider_report = providers.to_mapping()
        if providers.state != "ready":
            store.update(
                stage=stage,
                state="waiting",
                reason_code="source_foundation_providers_unregistered",
                next_action="review_required_provider_registration_without_automatic_mutation",
            )
            return _progress_result(store, source.commit)
        store.update(stage=stage, state="running", completed=True)
        stage = "policy"
        policies = checks.capture(
            (
                "az",
                "policy",
                "assignment",
                "list",
                "--scope",
                f"/subscriptions/{target.subscription_id}",
                "--disable-scope-strict-match",
                "true",
                "--output",
                "json",
                "--only-show-errors",
            ),
            "source_policy_observation_failed",
            strip=False,
            timeout=min(90, store.remaining_seconds()),
        )
        assignments = json.loads(policies)
        if not isinstance(assignments, list) or any(
            not isinstance(entry, dict) for entry in assignments
        ):
            raise ValueError("source policy assignments are incomplete")
        store.policy_report = {
            "state": "observed",
            "assignment_count": len(assignments),
            "evidence_digest": canonical_digest({"assignments": assignments}),
            "policy_compliance_verified": False,
            "mutation_performed": False,
        }
        store.update(stage=stage, state="running", completed=True)
        store.route = "private-runner"
        store.update(stage="route", state="running", completed=True)
        inputs = SourceFoundationPlanInputs(
            source_snapshot=args.source_snapshot,
            source_snapshot_digest=args.source_snapshot_digest,
            terraform=args.terraform,
            profile=root / "profile.json",
            variables_file=root / "foundation-variables.json",
        )
        source.reverify()
        coordinator = PrivateExecutionCoordinator(
            config=PrivateExecutionConfig(
                repository_root=source.root,
                repository=repository,
                subscription_id=target.subscription_id,
                tenant_id=target.tenant_id,
                source_commit=source.commit,
                work_dir=root,
                foundation_inputs=inputs,
                approval=approval,
                approval_path=args.approval_file if approval is not None else None,
                create_runner_image=False,
                runner_image_terraform=None,
                runner_ssh_private_key=root / "runner_ed25519",
                execution_timeout_seconds=args.timeout_seconds,
            ),
            store=store,
            checks=checks,
        )
        coordinator.run()
        raise ValueError("source Foundation coordinator did not return a bounded checkpoint")
    except PrivateExecutionWaitError as exc:
        source.reverify()
        store.update(
            stage=exc.stage,
            state="waiting",
            reason_code=exc.reason_code,
            next_action=exc.next_action,
        )
        if exc.stage == "application-plan":
            from source_application_transport import transfer_application_source

            try:
                transfer = transfer_application_source(
                    foundation_root=root,
                    snapshot=args.source_snapshot,
                    snapshot_digest=args.source_snapshot_digest,
                    source_commit=source.commit,
                    target_binding=args.target_binding,
                    report=store.foundation_report,
                    timeout_seconds=store.remaining_seconds(),
                )
                source.reverify()
                store.update(
                    stage=exc.stage,
                    state="waiting",
                    reason_code="source_application_execution_not_connected",
                    next_action="build_source_images_on_attested_host_and_validate_application_inputs",
                )
                return {**_progress_result(store, source.commit), "source_host_transfer": transfer}
            except (OSError, ValueError, RuntimeError):
                store.update(
                    stage=exc.stage,
                    state="failed",
                    reason_code="source_application_transfer_failed",
                )
                raise
        return _progress_result(store, source.commit)
    except (CheckError, PrivateExecutionError) as exc:
        store.update(
            stage=getattr(exc, "stage", stage), state="failed", reason_code=exc.reason_code
        )
        raise
    except (OSError, ValueError, RuntimeError):
        store.update(stage=stage, state="failed", reason_code="source_foundation_execution_failed")
        raise


def _progress_result(store: StatusStore, source_commit: str) -> dict[str, object]:
    return {
        "schema_version": "fdai.source-foundation-progress.v1",
        "state": "review",
        "stage": store.payload["current_stage"],
        "reason_code": store.payload["reason_code"],
        "source_commit": source_commit,
        "run_binding": store.target_binding,
        "attempt": store.attempt,
        "provenance": "operator-selected-source",
        "release_signature_verified": False,
        "apply_authorized": False,
        "mutation_performed": store.mutation_performed,
        "deployment_ready": False,
        "subscription_ready": False,
        "next_action": store.payload["next_action"],
    }


def main() -> int:
    """Prepare inputs or advance exact-approved checkpoints, returning sanitized progress."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--target-binding", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--monthly-cost-ceiling", type=int, required=True)
    parser.add_argument("--workload", default="fdai")
    parser.add_argument("--advance", action="store_true")
    parser.add_argument("--source-snapshot", type=Path)
    parser.add_argument("--source-snapshot-digest")
    parser.add_argument("--terraform", type=Path)
    parser.add_argument("--approval-file", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=14400)
    try:
        args = parser.parse_args()
        if args.advance and any(
            value is None
            for value in (args.source_snapshot, args.source_snapshot_digest, args.terraform)
        ):
            raise ValueError("source Foundation advance requires its exact snapshot and Terraform")
        print(json.dumps(advance(args) if args.advance else prepare(args), sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError):
        print("source Foundation preparation failed; preserve retained evidence", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
