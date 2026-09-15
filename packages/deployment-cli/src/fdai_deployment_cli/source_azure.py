"""Supervise connected source Foundation with exact human checkpoint approvals."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from fdai_deployment_cli.aks_preflight import inspect_aks_target
from fdai_deployment_cli.contracts import load_json_object
from fdai_deployment_cli.deployment_cost import inspect_aks_compute_cost
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.installation_scope import InstallationOptions, confirm_installation_scope
from fdai_deployment_cli.private_output import read_private_bytes
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
from fdai_deployment_cli.runtime_release import RUNTIME_SERVICES
from fdai_deployment_cli.source_deploy import prepare_source_deployment
from fdai_deployment_cli.source_foundation import _copy_terraform
from fdai_deployment_cli.source_input import inspect_source
from fdai_deployment_cli.source_transport import prepare_source_transport
from fdai_deployment_cli.standalone_status import current_status, prior_attempt


def plan_source_installation(
    *,
    source_root: Path,
    work_dir: Path,
    runtime_profile: RuntimeDeploymentProfile,
    region: str,
    monthly_cost_ceiling: int,
    timeout_seconds: int,
    interactive: bool = False,
    approval_file: Path | None = None,
    installation_options: InstallationOptions | None = None,
    confirm_initial: bool = False,
    foundation_recovery_directory: Path | None = None,
) -> dict[str, object]:
    """Advance source Foundation through exact human approvals, or stop for review.

    No kit construction, signature fallback or licence activation occurs here.
    Noninteractive use passes only an explicitly supplied approval to the shared
    verifier and never prompts or adopts an ambient approval. Foundation handoff
    alone keeps deployment_ready=false until application acceptance is connected.
    """
    if interactive and approval_file is not None:
        raise ValueError("explicit source approval cannot be combined with interactive approval")
    if foundation_recovery_directory is not None:
        from fdai_deployment_cli.source_recovery import resume_source_installation

        if interactive or confirm_initial or installation_options is not None:
            raise ValueError("source recovery cannot replace the retained initial scope or prompt")
        return resume_source_installation(
            source_root=source_root,
            work_dir=work_dir,
            recovery_directory=foundation_recovery_directory,
            runtime_profile=runtime_profile,
            region=region,
            monthly_cost_ceiling=monthly_cost_ceiling,
            timeout_seconds=timeout_seconds,
            approval_file=approval_file,
        )
    deadline = DeploymentDeadline(timeout_seconds)
    prepared = prepare_source_deployment(
        source_root=source_root,
        work_dir=work_dir,
        runtime_profile=runtime_profile,
        region=region,
        monthly_cost_ceiling=monthly_cost_ceiling,
    )
    source = inspect_source(source_root, expected_commit=str(prepared["source_commit"]))
    preflight = inspect_aks_target(
        profile=runtime_profile, region=region, timeout_seconds=deadline.remaining(180)
    )
    if preflight["state"] != "feasible":
        return {**preflight, "stage": "aks-preflight"}
    work_dir = work_dir.absolute()
    if installation_options is not None:
        confirmation = confirm_installation_scope(
            work_dir=work_dir,
            binding={
                "source_commit": source.commit,
                "target_binding": preflight["target_binding"],
                "preparation_digest": prepared["receipt_digest"],
                "runtime_profile_digest": runtime_profile.digest,
                "region": region,
                "monthly_cost_ceiling": monthly_cost_ceiling,
            },
            runtime_profile=runtime_profile,
            options=installation_options,
            interactive=confirm_initial,
            timeout_seconds=deadline.remaining(86400),
        )
        source.reverify()
        if confirmation["state"] != "confirmed":
            return {**confirmation, "source_commit": source.commit}
    cost_review = inspect_aks_compute_cost(
        profile=runtime_profile,
        region=region,
        monthly_cost_ceiling=monthly_cost_ceiling,
        timeout_seconds=deadline.remaining(120),
    )
    source.reverify()
    if cost_review["state"] == "blocked":
        return {**cost_review, "source_commit": source.commit}
    tools = work_dir / "source-tools"
    tools.mkdir(mode=0o700, exist_ok=True)
    terraform = tools / "terraform"
    toolchain = load_json_object(
        (source.root / "infra/genesis-runner-image/toolchain.json").read_bytes(),
        label="source toolchain",
    )
    digest = toolchain.get("terraform_binary_sha256")
    if terraform.exists():
        import hashlib

        if hashlib.sha256(terraform.read_bytes()).hexdigest() != digest:
            raise ValueError("retained source Terraform differs; preserve the run")
    else:
        installed = shutil.which("terraform")
        if installed is None:
            raise ValueError("install the source-pinned Terraform before planning")
        _copy_terraform(Path(installed), terraform, expected_digest=digest)
    scripts = source.root / "scripts/deployment/azure"
    foundation = work_dir / "foundation"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        in {"HOME", "PATH", "AZURE_CONFIG_DIR", "LANG", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"}
    }
    environment["PYTHONPATH"] = str(source.root / "packages/deployment-cli/src")
    source.reverify()
    builder = _capture(
        (
            sys.executable,
            str(scripts / "source_image_build.py"),
            "--check-tools",
            "--timeout-seconds",
            str(deadline.remaining(60)),
        ),
        source.root,
        environment,
        deadline.remaining(90),
    )
    source.reverify()
    if (
        builder.get("schema_version") != "fdai.source-image-builder.v1"
        or builder.get("state") not in {"available", "blocked"}
        or builder.get("mutation_performed") is not False
        or builder.get("deployment_ready") is not False
    ):
        raise ValueError("source image builder returned invalid prerequisite evidence")
    if builder["state"] == "blocked":
        return {**builder, "stage": "source-image-tools", "source_commit": source.commit}
    preparation = _capture(
        (
            sys.executable,
            str(scripts / "source_genesis.py"),
            "--work-dir",
            str(foundation),
            "--source-commit",
            source.commit,
            "--target-binding",
            str(preflight["target_binding"]),
            "--region",
            region,
            "--monthly-cost-ceiling",
            str(monthly_cost_ceiling),
        ),
        source.root,
        environment,
        deadline.remaining(900),
    )
    values = load_json_object(
        read_private_bytes(foundation / "foundation-variables.json", max_bytes=65536),
        label="source Foundation variables",
    )
    environment["AZURE_SUBSCRIPTION_ID"] = str(values["subscription_id"])
    environment["AZURE_TENANT_ID"] = str(values["tenant_id"])
    run_binding = preparation.get("run_binding")
    if not isinstance(run_binding, str):
        raise ValueError("source Foundation preparation has no retained run binding")
    approval = (
        approval_file.absolute()
        if approval_file is not None
        else foundation / "current-source-approval.json"
    )
    status_path = foundation / "status.json"
    while True:
        source.reverify()
        previous = prior_attempt(status_path)
        result = _capture(
            (
                sys.executable,
                str(scripts / "source_genesis.py"),
                "--advance",
                "--work-dir",
                str(foundation),
                "--source-commit",
                source.commit,
                "--target-binding",
                str(preflight["target_binding"]),
                "--region",
                region,
                "--monthly-cost-ceiling",
                str(monthly_cost_ceiling),
                "--source-snapshot",
                str(work_dir / "source-snapshot"),
                "--source-snapshot-digest",
                str(prepared["source_snapshot_digest"]),
                "--terraform",
                str(terraform),
                "--timeout-seconds",
                str(deadline.remaining(14400)),
                *(
                    ("--approval-file", str(approval))
                    if approval_file is not None or (interactive and approval.exists())
                    else ()
                ),
            ),
            source.root,
            environment,
            deadline.remaining(14400),
        )
        source.reverify()
        if (
            result.get("schema_version") != "fdai.source-foundation-progress.v1"
            or result.get("state") != "review"
            or result.get("source_commit") != source.commit
            or result.get("run_binding") != run_binding
            or result.get("provenance") != "operator-selected-source"
            or result.get("release_signature_verified") is not False
            or result.get("apply_authorized") is not False
            or type(result.get("mutation_performed")) is not bool
            or result.get("deployment_ready") is not False
        ):
            raise ValueError("source Foundation did not return a bound review result")
        status = current_status(
            status_path, previous=previous, source_commit=source.commit, run_binding=run_binding
        )
        if (
            result.get("attempt") != status["attempt"]
            or result.get("stage") != status.get("current_stage")
            or result["mutation_performed"] != status.get("mutation_performed")
        ):
            raise ValueError("source Foundation progress differs from its current status")
        if result["stage"] == "application-plan":
            report = status.get("foundation_report")
            handoff = report.get("state_handoff") if isinstance(report, dict) else None
            plan = report.get("foundation_plan") if isinstance(report, dict) else None
            plan_ref = plan.get("plan_ref") if isinstance(plan, dict) else None
            completed = status.get("completed_stages")
            if (
                not isinstance(handoff, dict)
                or not isinstance(plan_ref, str)
                or re.fullmatch(r"foundation-plan-attempt-[1-9][0-9]*", plan_ref) is None
            ):
                raise ValueError("source application transfer requires verified Foundation handoff")
            expected_handoff_digest = handoff.get("receipt_digest")
            handoff = load_json_object(
                read_private_bytes(
                    foundation / plan_ref / "foundation-state-handoff-receipt.json",
                    max_bytes=1024 * 1024,
                ),
                label="source Foundation handoff receipt",
                max_bytes=1024 * 1024,
            )
            if (
                status.get("route") != "private-runner"
                or not isinstance(completed, list)
                or "foundation-state" not in completed
                or not isinstance(handoff, dict)
                or handoff.get("schema_version")
                != "fdai.genesis-foundation-state-handoff-receipt.v1"
                or handoff.get("state") != "verified"
                or handoff.get("source_commit") != source.commit
                or handoff.get("target_binding") != preflight["target_binding"]
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
                raise ValueError("source application transfer requires verified Foundation handoff")
            from fdai_deployment_cli.contracts import canonical_digest

            if (
                canonical_digest(
                    {key: value for key, value in handoff.items() if key != "receipt_digest"}
                )
                != expected_handoff_digest
                or handoff.get("receipt_digest") != expected_handoff_digest
            ):
                raise ValueError("source Foundation handoff digest differs")
            deadline.remaining()
            transfer = prepare_source_transport(
                work_dir / "source-snapshot",
                work_dir,
                snapshot_digest=str(prepared["source_snapshot_digest"]),
            )
            source.reverify()
            deadline.remaining()
            host_transfer = result.get("source_host_transfer")
            if host_transfer is not None and (
                not isinstance(host_transfer, dict)
                or host_transfer.get("schema_version") != "fdai.source-host-transfer-receipt.v1"
                or host_transfer.get("state") != "verified"
                or host_transfer.get("source_commit") != source.commit
                or host_transfer.get("target_binding") != preflight["target_binding"]
                or host_transfer.get("snapshot_digest") != prepared["source_snapshot_digest"]
                or host_transfer.get("archive_digest") != transfer.get("archive_digest")
                or host_transfer.get("state_handoff_digest") != expected_handoff_digest
                or host_transfer.get("remote_transfer_verified") is not True
                or host_transfer.get("deployment_ready") is not False
                or host_transfer.get("apply_authorized") is not False
                or canonical_digest(
                    {key: value for key, value in host_transfer.items() if key != "receipt_digest"}
                )
                != host_transfer.get("receipt_digest")
            ):
                raise ValueError("source host transfer differs from current local evidence")
            images: dict[str, object] | None = None
            if host_transfer is not None:
                images = _capture(
                    (
                        sys.executable,
                        str(scripts / "source_image_build.py"),
                        "--all-services",
                        "--snapshot",
                        str(work_dir / "source-snapshot"),
                        "--snapshot-digest",
                        str(prepared["source_snapshot_digest"]),
                        "--work-dir",
                        str(work_dir / "source-images"),
                        "--timeout-seconds",
                        str(deadline.remaining(14400)),
                    ),
                    source.root,
                    environment,
                    deadline.remaining(14400),
                )
                source.reverify()
                services = images.get("services")
                if (
                    images.get("schema_version") != "fdai.source-images.v1"
                    or images.get("state") != "built"
                    or images.get("source_commit") != source.commit
                    or images.get("snapshot_digest") != prepared["source_snapshot_digest"]
                    or not isinstance(services, dict)
                    or set(services) != RUNTIME_SERVICES
                    or images.get("registry_published") is not False
                    or images.get("apply_authorized") is not False
                    or images.get("deployment_ready") is not False
                    or canonical_digest(
                        {key: value for key, value in images.items() if key != "receipt_digest"}
                    )
                    != images.get("receipt_digest")
                ):
                    raise ValueError("source image inventory differs from current installation")
            return {
                **result,
                "cost_review": cost_review,
                "source_transfer": transfer,
                **({"source_images": images} if images is not None else {}),
                "reason_code": "source_application_execution_not_connected",
                "next_action": (
                    "transfer_verified_images_for_private_registry_import_and_validate_application_inputs"
                    if host_transfer is not None
                    else "transfer_verified_source_to_attested_host_and_validate_application_inputs"
                ),
            }
        if not interactive or result["stage"] not in {
            "runner-image-apply",
            "foundation-apply",
            "runner-enrollment",
            "foundation-state",
        }:
            return {**result, "cost_review": cost_review}
        approval.unlink(missing_ok=True)
        prompt = subprocess.run(
            (
                sys.executable,
                str(scripts / "genesis_approval_prompt.py"),
                "--status",
                str(status_path),
                "--output",
                str(approval),
            ),
            cwd=source.root,
            env=environment,
            stdout=sys.stderr,
            check=False,
            timeout=deadline.remaining(600),
        )
        if prompt.returncode != 0:
            raise ValueError("source Foundation exact approval was not granted")


def _capture(
    command: tuple[str, ...], root: Path, environment: dict[str, str], timeout: int
) -> dict[str, object]:
    result = subprocess.run(
        command,
        cwd=root,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise ValueError(
            "source planning stage failed; preserve private state and do not repeat effects"
        )
    return load_json_object(result.stdout, label="source planning result", max_bytes=1024 * 1024)
