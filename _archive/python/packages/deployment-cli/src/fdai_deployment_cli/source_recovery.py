"""Resume an immutable source installation with explicitly selected recovery execution code."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.private_output import read_private_bytes
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
from fdai_deployment_cli.source_input import inspect_source
from fdai_deployment_cli.source_snapshot import verify_source_snapshot


@dataclass(frozen=True)
class RecoveredApplicationEvidence:
    """Verified recovered Foundation inputs for source application continuation."""

    status: dict[str, object]
    run_binding: str
    state_handoff_digest: str
    source_snapshot_digest: str


def retained_source_run(
    work_dir: Path,
    *,
    runtime_profile_digest: str,
    region: str,
    monthly_cost_ceiling: int,
) -> dict[str, object]:
    """Verify original application source and selected settings without rewriting the run."""
    intent = load_json_object(
        read_private_bytes(work_dir / "source-intent.json", max_bytes=65536),
        label="original source intent",
    )
    preparation = load_json_object(
        read_private_bytes(work_dir / "source-preparation.json", max_bytes=65536),
        label="original source preparation",
    )
    digest = preparation.pop("receipt_digest", None)
    if (
        canonical_digest(preparation) != digest
        or preparation.get("schema_version") != "fdai.source-deployment-preparation.v1"
        or preparation.get("state") != "prepared"
        or preparation.get("provenance") != "operator-selected-source"
        or preparation.get("release_signature_verified") is not False
        or any(
            preparation.get(key) is not False
            for key in (
                "apply_authorized",
                "mutation_performed",
                "deployment_ready",
                "subscription_ready",
            )
        )
        or preparation.get("intent_digest") != canonical_digest(intent)
        or intent.get("schema_version") != "fdai.source-deployment-intent.v1"
        or intent.get("environment") != "dev"
        or intent.get("region") != region
        or intent.get("monthly_cost_ceiling") != monthly_cost_ceiling
        or preparation.get("runtime_profile_digest") != runtime_profile_digest
        or not isinstance(intent.get("runtime_profile"), dict)
        or canonical_digest(intent["runtime_profile"]) != runtime_profile_digest
    ):
        raise ValueError("source recovery must preserve the original installation settings")
    snapshot = verify_source_snapshot(
        work_dir / "source-snapshot", expected_digest=str(preparation.get("source_snapshot_digest"))
    )
    if (
        snapshot != intent.get("source")
        or snapshot.get("source_commit") != preparation.get("source_commit")
        or canonical_digest(snapshot) != preparation.get("source_input_digest")
        or canonical_digest(snapshot) != intent.get("source_input_digest")
    ):
        raise ValueError("source recovery application snapshot differs from the original run")
    preparation["receipt_digest"] = digest
    return preparation


def recovered_application_evidence(
    *,
    work_dir: Path,
    recovery_directory: Path,
    progress: dict[str, object],
    runtime_profile_digest: str,
    region: str,
    monthly_cost_ceiling: int,
) -> RecoveredApplicationEvidence:
    """Reverify the complete recovered handoff before source application effects."""

    prepared = retained_source_run(
        work_dir,
        runtime_profile_digest=runtime_profile_digest,
        region=region,
        monthly_cost_ceiling=monthly_cost_ceiling,
    )
    if (
        progress.get("stage") != "application-plan"
        or progress.get("reason_code") != "source_application_continuation_ready"
        or progress.get("next_action") != "continue_with_original_source_snapshot"
    ):
        raise ValueError("source recovery is not ready for application continuation")

    foundation_root = work_dir / "foundation"
    marker = _private_record(foundation_root / "source-genesis.json", "source Genesis marker")
    marker_digest = marker.pop("receipt_digest", None)
    recovery = _private_record(
        recovery_directory / "recovery-apply-receipt.json",
        "Foundation recovery receipt",
    )
    recovery_digest = recovery.pop("receipt_digest", None)
    enrollment = _private_record(
        recovery_directory / "runner-enrollment-receipt.json",
        "recovered runner enrollment receipt",
    )
    enrollment_digest = enrollment.pop("receipt_digest", None)
    state = _private_record(
        recovery_directory / "foundation-state-handoff-receipt.json",
        "recovered Foundation state receipt",
    )
    state_digest = state.pop("receipt_digest", None)
    handoff = read_private_bytes(
        recovery_directory / "recovery-private-handoff.json",
        max_bytes=1024 * 1024,
    )
    status = _private_record(foundation_root / "status.json", "source Foundation status")
    required_state = (
        "effect_verified",
        "runner_attested",
        "remote_backend_authority_verified",
        "zero_change_verified",
        "remote_transient_deleted",
        "local_state_deleted",
    )
    if (
        canonical_digest(marker) != marker_digest
        or marker.get("source_commit") != prepared["source_commit"]
        or marker.get("run_binding") != progress.get("run_binding")
        or marker.get("target_binding") != progress.get("target_binding")
        or canonical_digest(recovery) != recovery_digest
        or recovery.get("schema_version") != "fdai.foundation-recovery-receipt.v1"
        or recovery.get("state") != "verified"
        or recovery.get("source_commit") != prepared["source_commit"]
        or recovery.get("control_plane_readback_verified") is not True
        or recovery.get("zero_change_verified") is not True
        or recovery_digest != progress.get("foundation_receipt_digest")
        or canonical_digest(enrollment) != enrollment_digest
        or enrollment.get("schema_version") != "fdai.genesis-runner-enrollment-receipt.v1"
        or enrollment.get("state") != "attested"
        or enrollment.get("foundation_receipt_digest") != recovery_digest
        or enrollment_digest != progress.get("enrollment_receipt_digest")
        or canonical_digest(state) != state_digest
        or state.get("schema_version") != "fdai.genesis-foundation-state-handoff-receipt.v1"
        or state.get("state") != "verified"
        or state.get("source_commit") != prepared["source_commit"]
        or state.get("target_binding") != progress.get("target_binding")
        or state.get("foundation_receipt_digest") != recovery_digest
        or state.get("enrollment_receipt_digest") != enrollment_digest
        or any(state.get(field) is not True for field in required_state)
        or state_digest != progress.get("state_handoff_digest")
        or canonical_digest(load_json_object(handoff, label="recovered Foundation handoff"))
        != recovery.get("handoff_digest")
    ):
        raise ValueError("recovered source application evidence differs from the verified handoff")
    return RecoveredApplicationEvidence(
        status=status,
        run_binding=str(marker["run_binding"]),
        state_handoff_digest=str(state_digest),
        source_snapshot_digest=str(prepared["source_snapshot_digest"]),
    )


def _private_record(path: Path, label: str) -> dict[str, object]:
    return load_json_object(
        read_private_bytes(path, max_bytes=1024 * 1024),
        label=label,
        max_bytes=1024 * 1024,
    )


def resume_source_installation(
    *,
    source_root: Path,
    work_dir: Path,
    recovery_directory: Path,
    runtime_profile: RuntimeDeploymentProfile,
    region: str,
    monthly_cost_ceiling: int,
    timeout_seconds: int,
    approval_file: Path | None,
) -> dict[str, object]:
    """Invoke current recovery code while retaining the original application's exact source.

    This explicit route never starts a new installation, renews an approval, or
    repeats Foundation apply. Only receipt-bound enrollment and migration may advance.
    """
    from fdai_deployment_cli.source_azure import _capture

    deadline = DeploymentDeadline(timeout_seconds)
    source = inspect_source(source_root)
    work_dir, recovery_directory = work_dir.absolute(), recovery_directory.absolute()
    prepared = retained_source_run(
        work_dir,
        runtime_profile_digest=runtime_profile.digest,
        region=region,
        monthly_cost_ceiling=monthly_cost_ceiling,
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        in {"HOME", "PATH", "AZURE_CONFIG_DIR", "LANG", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"}
    }
    environment["PYTHONPATH"] = str(source.root / "packages/deployment-cli/src")
    source.reverify()
    result = _capture(
        (
            sys.executable,
            str(source.root / "scripts/deployment/azure/source_recovery.py"),
            "--work-dir",
            str(work_dir),
            "--recovery-directory",
            str(recovery_directory),
            "--runtime-profile-digest",
            runtime_profile.digest,
            "--region",
            region,
            "--monthly-cost-ceiling",
            str(monthly_cost_ceiling),
            "--timeout-seconds",
            str(deadline.remaining(14400)),
            *(
                ("--approval-file", str(approval_file.absolute()))
                if approval_file is not None
                else ()
            ),
        ),
        source.root,
        environment,
        deadline.remaining(14400),
    )
    source.reverify()
    if (
        result.get("schema_version") != "fdai.source-recovery-progress.v1"
        or result.get("state") != "review"
        or result.get("source_commit") != prepared["source_commit"]
        or result.get("execution_source_commit") != source.commit
        or result.get("runtime_profile_digest") != runtime_profile.digest
        or result.get("provenance") != "operator-selected-source"
        or any(
            result.get(key) is not False
            for key in ("apply_authorized", "deployment_ready", "release_signature_verified")
        )
        or canonical_digest(
            {key: value for key, value in result.items() if key != "receipt_digest"}
        )
        != result.get("receipt_digest")
    ):
        raise ValueError("source recovery returned progress for a different execution context")
    return result
