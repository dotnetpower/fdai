"""Create source-bound Foundation plans with locked tools and no kit or apply fallback."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fdai_deployment_cli.contracts import ProvisionProfile, canonical_digest, load_json_object
from fdai_deployment_cli.foundation_image import verify_foundation_runner_image
from fdai_deployment_cli.foundation_input import snapshot_foundation_input
from fdai_deployment_cli.foundation_plan import save_foundation_plan, source_foundation_plan_context
from fdai_deployment_cli.plan_input import read_plan_input
from fdai_deployment_cli.private_output import write_private_bytes
from fdai_deployment_cli.source_snapshot import verify_source_snapshot


def prepare_source_foundation_plan(
    *,
    snapshot: Path,
    snapshot_digest: str,
    terraform: Path,
    profile: ProvisionProfile,
    variables_file: Path,
    work_dir: Path,
    environment_builder: Callable[..., dict[str, str]],
) -> dict[str, object]:
    """Save one exact source plan after input, target and image verification.

    The caller validates the active human target and creates an empty private work
    directory. Provider installation is connected and lockfile-readonly; no source,
    Terraform binary, provider lock or approval is selected from a release fallback.
    """
    if (
        profile.environment != "dev"
        or profile.connectivity != "online"
        or profile.transport != "manual"
    ):
        raise ValueError("source Foundation requires connected manual development")
    source = verify_source_snapshot(snapshot, expected_digest=snapshot_digest)
    root = snapshot / "tree"
    infra = root / "infra/genesis-foundation"
    lock = infra / ".terraform.lock.hcl"
    toolchain = load_json_object(
        (root / "infra/genesis-runner-image/toolchain.json").read_bytes(), label="source toolchain"
    )
    tool_digest = toolchain.get("terraform_binary_sha256")
    executable = _copy_terraform(terraform, work_dir / "terraform", expected_digest=tool_digest)
    config = work_dir / "source.tfrc"
    write_private_bytes(
        config, b'provider_installation { direct { include = ["registry.terraform.io/*/*"] } }\n'
    )
    normalized = work_dir / "variables.json"
    binding = snapshot_foundation_input(
        variables_file,
        normalized,
        expected_target_binding=profile.target_binding,
        expected_region=profile.region,
        expected_environment=profile.environment,
    )
    try:
        values = read_plan_input(normalized)
        if values["source_commit"] != source.get("source_commit"):
            raise ValueError("source Foundation variables do not match the selected source")
        if profile.access_method == "bastion" and values.get("enable_bastion") is not True:
            raise ValueError("source Foundation requires its selected Bastion path")
        import shutil

        environment = environment_builder(
            work_dir=work_dir,
            config=config,
            source=os.environ,
            subscription_id=binding.subscription_id,
            tenant_id=binding.tenant_id,
            azure_cli_path=Path(azure_cli) if (azure_cli := shutil.which("az")) else None,
        )
        image_observation = verify_foundation_runner_image(values, expected_region=profile.region)
        provider_lock = lock.read_bytes()
        context = source_foundation_plan_context(
            profile=profile,
            variables=values,
            source_input_digest=canonical_digest(source),
            source_snapshot_digest=snapshot_digest,
            terraform_digest=str(tool_digest),
            provider_lock=provider_lock,
            runner_image_observation_digest=image_observation,
        )
        for arguments in (
            ("init", "-backend=false", "-input=false", "-lockfile=readonly"),
            ("validate", "-no-color"),
        ):
            _run((str(executable), *arguments), infra, environment)
        with TemporaryDirectory(prefix="source-plan-", dir=work_dir) as temporary:
            plan = Path(temporary) / "plan.tfplan"
            _run(
                (
                    str(executable),
                    "plan",
                    "-input=false",
                    "-no-color",
                    f"-var-file={normalized}",
                    f"-out={plan}",
                ),
                infra,
                environment,
            )
            if lock.read_bytes() != provider_lock:
                raise ValueError("source Foundation provider lock changed")
            verify_source_snapshot(snapshot, expected_digest=snapshot_digest)
            if hashlib.sha256(executable.read_bytes()).hexdigest() != tool_digest:
                raise ValueError("source Foundation Terraform changed during planning")
            review = save_foundation_plan(
                plan=plan,
                destination=work_dir,
                terraform=executable,
                root=infra,
                environment=environment,
                context=context,
                variables=values,
            )
        return {
            "schema_version": "fdai.provision-source-plan.v1",
            "stage": "foundation",
            "state": "review",
            "saved_plan": review,
            "source_snapshot_digest": snapshot_digest,
            "provenance": "operator-selected-source",
            "release_signature_verified": False,
            "apply_authorized": False,
            "mutation_performed": False,
            "deployment_ready": False,
            "subscription_ready": False,
        }
    finally:
        normalized.unlink(missing_ok=True)


def _copy_terraform(source: Path, destination: Path, *, expected_digest: Any) -> Path:
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_mode & 0o022
            or details.st_uid not in {0, os.geteuid()}
            or not 0 < details.st_size <= 128 * 1024 * 1024
        ):
            raise ValueError("source Terraform must be an owned bounded non-writable executable")
        data = stream.read(128 * 1024 * 1024 + 1)
        if len(data) != details.st_size or hashlib.sha256(data).hexdigest() != expected_digest:
            raise ValueError("source Terraform does not match the committed toolchain digest")
    write_private_bytes(destination, data)
    destination.chmod(0o700)
    return destination


def _run(command: tuple[str, ...], root: Path, environment: dict[str, str]) -> None:
    result = subprocess.run(
        command,
        cwd=root,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=900,
        umask=0o077,
    )
    if result.returncode != 0:
        raise ValueError(f"source Foundation {command[1]} failed; preserve private plan evidence")
