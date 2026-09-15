"""Supervise connected source Foundation with exact human checkpoint approvals."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from fdai_deployment_cli.aks_preflight import inspect_aks_target
from fdai_deployment_cli.contracts import load_json_object
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.private_output import read_private_bytes
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
from fdai_deployment_cli.source_deploy import prepare_source_deployment
from fdai_deployment_cli.source_foundation import _copy_terraform
from fdai_deployment_cli.source_input import inspect_source
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
) -> dict[str, object]:
    """Advance source Foundation through exact human approvals, or stop for review.

    No kit construction, signature fallback or licence activation occurs here.
    Noninteractive use passes only an explicitly supplied approval to the shared
    verifier and never prompts or adopts an ambient approval. Foundation handoff
    alone keeps deployment_ready=false until application acceptance is connected.
    """
    if interactive and approval_file is not None:
        raise ValueError("explicit source approval cannot be combined with interactive approval")
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
        if not interactive or result["stage"] not in {
            "runner-image-apply",
            "foundation-apply",
            "runner-enrollment",
            "foundation-state",
        }:
            return result
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
