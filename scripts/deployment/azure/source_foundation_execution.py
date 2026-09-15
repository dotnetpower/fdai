"""Prepare source-bound Foundation execution files without a release-kit fallback."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.private_output import write_private_bytes
from fdai_deployment_cli.source_foundation import _copy_terraform
from fdai_deployment_cli.source_snapshot import verify_source_snapshot
from genesis_foundation_workspace import verify_execution_copy

if TYPE_CHECKING:
    from genesis_foundation_apply import VerifiedSnapshot


def prepare_source_execution(
    *,
    plan_directory: Path,
    source_snapshot: Path,
    source_snapshot_digest: str,
    terraform: Path,
    context: dict[str, object],
) -> VerifiedSnapshot:
    """Reverify immutable source/tools and retain state in the existing apply layout.

    Provider acquisition is connected but lockfile-bound. The returned mirror is
    suitable for the existing private state handoff; no Azure resource is mutated.
    The source snapshot itself never receives Terraform data or state files.
    """
    from genesis_foundation_apply import VerifiedSnapshot, _required

    source = verify_source_snapshot(source_snapshot, expected_digest=source_snapshot_digest)
    if (
        context.get("source_snapshot_digest") != source_snapshot_digest
        or context.get("source_input_digest") != canonical_digest(source)
        or context.get("source_commit") != source.get("source_commit")
        or "offline_manifest_digest" in context
        or "deployment_bundle_digest" in context
    ):
        raise ValueError("Foundation execution source differs from the exact plan")
    infra = source_snapshot / "tree/infra"
    lock = infra / "genesis-foundation/.terraform.lock.hcl"
    if hashlib.sha256(lock.read_bytes()).hexdigest() != context.get("provider_lock_digest"):
        raise ValueError("Foundation execution provider lock differs from the exact plan")
    temporary = TemporaryDirectory(prefix="foundation-source-execution-", dir=plan_directory)
    temporary_root = Path(temporary.name)
    try:
        executable = _copy_terraform(
            terraform, temporary_root / "terraform", expected_digest=context.get("terraform_digest")
        )
        authenticated = temporary_root / "source"
        authenticated.mkdir(mode=0o700)
        _copy_private_tree(infra, authenticated / "infra")
        verify_source_snapshot(source_snapshot, expected_digest=source_snapshot_digest)
        persistent_bundle = plan_directory / "foundation-apply-bundle"
        persistent_root = persistent_bundle / "source"
        if persistent_bundle.exists() or persistent_bundle.is_symlink():
            if persistent_bundle.is_symlink() or {
                path.name for path in persistent_bundle.iterdir()
            } != {"source"}:
                raise ValueError("Foundation source execution cannot adopt another bundle")
        else:
            persistent_bundle.mkdir(mode=0o700)
            _copy_private_tree(authenticated, persistent_root)
        verify_execution_copy(persistent_root, authenticated_source=authenticated)
        infra_root = persistent_root / "infra/genesis-foundation"
        data_dir = temporary_root / "terraform-data"
        data_dir.mkdir(mode=0o700)
        config = temporary_root / "providers.tfrc"
        write_private_bytes(
            config,
            b'provider_installation { direct { include = ["registry.terraform.io/*/*"] } }\n',
        )
        environment = {
            key: value
            for key, value in os.environ.items()
            if key
            in {"HOME", "PATH", "LANG", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"}
        }
        environment.update(
            {
                "TF_DATA_DIR": str(data_dir),
                "TF_CLI_CONFIG_FILE": str(config),
                "TF_INPUT": "0",
                "TF_IN_AUTOMATION": "1",
            }
        )
        _required(
            [str(executable), "init", "-backend=false", "-input=false", "-lockfile=readonly"],
            cwd=infra_root,
            env=environment,
            timeout=300,
            reason="source Foundation provider initialization failed",
        )
        mirror = temporary_root / "mirror"
        _required(
            [
                str(executable),
                "providers",
                "mirror",
                "-platform=linux_amd64",
                "-lock-file=true",
                str(mirror),
            ],
            cwd=infra_root,
            env=environment,
            timeout=300,
            reason="source Foundation locked provider mirror failed",
        )
        verify_execution_copy(persistent_root, authenticated_source=authenticated)
        verify_source_snapshot(source_snapshot, expected_digest=source_snapshot_digest)
        if hashlib.sha256(executable.read_bytes()).hexdigest() != context.get("terraform_digest"):
            raise ValueError("source Foundation Terraform changed during preparation")
        mirror_config = temporary_root / "mirror.tfrc"
        write_private_bytes(
            mirror_config,
            (
                "provider_installation {\n  filesystem_mirror {\n"
                f"    path = {json.dumps(str(mirror))}\n"
                '    include = ["registry.terraform.io/*/*"]\n  }\n'
                '  direct { exclude = ["registry.terraform.io/*/*"] }\n}\n'
            ).encode(),
        )
        return VerifiedSnapshot(
            temporary=temporary,
            terraform=executable,
            mirror=mirror,
            infra_root=infra_root,
            cli_config=mirror_config,
            data_dir=data_dir,
        )
    except BaseException:
        temporary.cleanup()
        raise


def _copy_private_tree(source: Path, destination: Path) -> None:
    if source.is_symlink() or any(path.is_symlink() for path in source.rglob("*")):
        raise ValueError("Foundation executable infrastructure must not contain symlinks")
    shutil.copytree(source, destination)
    destination.chmod(0o700)
    for path in destination.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
