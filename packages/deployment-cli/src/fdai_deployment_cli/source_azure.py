"""Advance a connected source installation to its first exact human plan boundary."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from fdai_deployment_cli.aks_preflight import inspect_aks_target
from fdai_deployment_cli.contracts import canonical_bytes, load_json_object
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
from fdai_deployment_cli.source_deploy import prepare_source_deployment
from fdai_deployment_cli.source_foundation import _copy_terraform
from fdai_deployment_cli.source_input import inspect_source


def plan_source_installation(
    *,
    source_root: Path,
    work_dir: Path,
    runtime_profile: RuntimeDeploymentProfile,
    region: str,
    monthly_cost_ceiling: int,
    timeout_seconds: int,
) -> dict[str, object]:
    """Prepare source, inspect capacity and generate a runner image plan without applying.

    No kit construction, signature fallback, image publication, state migration or
    licence activation occurs here. The result must retain deployment_ready=false.
    """
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
    _capture(
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
    plan_dir = foundation / "runner-image-attempt-1"
    if plan_dir.exists():
        raise ValueError(
            "retained source image plan requires exact review; it is not reapplied or replaced"
        )
    source.reverify()
    result = _capture(
        (
            sys.executable,
            str(scripts / "genesis_runner_image.py"),
            "plan",
            "--work-dir",
            str(plan_dir),
            "--profile",
            str(foundation / "profile.json"),
            "--foundation-variables",
            str(foundation / "foundation-variables.json"),
            "--terraform",
            str(terraform),
            "--timeout-seconds",
            str(deadline.remaining(7800)),
            "--output",
            "json",
        ),
        source.root,
        environment,
        deadline.remaining(7800),
    )
    source.reverify()
    if (
        result.get("schema_version") != "fdai.genesis-runner-image-plan-result.v1"
        or result.get("state") != "review"
        or result.get("apply_authorized") is not False
        or result.get("mutation_performed") is not False
    ):
        raise ValueError("source runner image plan did not return a review-only result")
    response = {
        **result,
        "stage": "runner-image-plan",
        "source_commit": source.commit,
        "provenance": "operator-selected-source",
        "release_signature_verified": False,
        "deployment_ready": False,
        "next_action": "review_exact_runner_image_plan",
    }
    write_private_bytes(foundation / "source-plan-review.json", canonical_bytes(response))
    return response


def _capture(
    command: tuple[str, ...], root: Path, environment: dict[str, str], timeout: int
) -> dict[str, object]:
    result = subprocess.run(
        command,
        cwd=root,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise ValueError(
            "source planning stage failed; preserve private state and do not repeat effects"
        )
    return load_json_object(result.stdout, label="source planning result", max_bytes=1024 * 1024)
