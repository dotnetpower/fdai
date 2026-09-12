#!/usr/bin/env python3
"""Prepare private exact-source artifacts for supervised Azure Genesis."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.__about__ import __version__
from fdai_deployment_cli.contracts import ProvisionProfile
from fdai_deployment_cli.deployment_kit import DeploymentKit
from fdai_deployment_cli.foundation_input import snapshot_foundation_input
from fdai_deployment_cli.offline_kit import OfflineKitVerification, verify_offline_kit
from fdai_deployment_cli.plan_input import read_plan_input, write_plan_input
from fdai_deployment_cli.private_output import (
    read_private_bytes,
    write_private_bytes,
    write_private_output,
)
from fdai_deployment_cli.profile import load_profile, write_profile
from fdai_deployment_cli.target import compute_target_binding
from fdai_deployment_cli.trust_roots import (
    deployment_bundle_root_pem,
    deployment_release_root_pem,
)
from genesis_prepare_inputs import foundation_values
from genesis_subprocess import run_with_heartbeat

_COMMIT = re.compile(r"[0-9a-f]{40}")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


@dataclass(frozen=True, slots=True)
class PreparedGenesis:
    """Private paths and bindings produced without an Azure resource mutation."""

    root: Path
    stage: Path
    profile: Path
    variables: Path
    ssh_private_key: Path
    source_commit: str
    target_binding: str
    run_binding: str
    kit_manifest_digest: str
    offline_kit: Path
    release_root: Path
    bundle_public_key: Path
    terraform: Path


def prepare_genesis(
    *,
    repository_root: Path,
    repository: str,
    source_commit: str,
    tenant_id: str,
    subscription_id: str,
    region: str,
    monthly_cost_ceiling: int,
    root: Path,
) -> PreparedGenesis:
    """Create or verify local inputs, overlapping independent kit and target discovery."""

    if (
        _COMMIT.fullmatch(source_commit) is None
        or _REPOSITORY.fullmatch(repository) is None
        or not re.fullmatch(r"[a-z][a-z0-9]+", region)
        or type(monthly_cost_ceiling) is not int
        or monthly_cost_ceiling <= 0
    ):
        raise ValueError("Genesis preparation input is invalid")
    _private_directory(root)
    release_key = root / "release-signing-key.pem"
    bundle_key = root / "bundle-signing-key.pem"
    ssh_key = root / "runner_ed25519"
    _ensure_ed25519_key(release_key, openssh=False)
    _ensure_ed25519_key(bundle_key, openssh=False)
    _ensure_ed25519_key(ssh_key, openssh=True)
    ssh_public = root / "runner_ed25519.pub"
    _ensure_ssh_public_key(ssh_key, ssh_public)
    target_binding = compute_target_binding(
        tenant_id=tenant_id,
        subscription_id=subscription_id,
    )
    run_binding = hashlib.sha256(
        (
            f"{tenant_id.lower()}:{subscription_id.lower()}:{region}:dev:"
            f"{repository}:runner-image=true"
        ).encode()
    ).hexdigest()
    profile_path = root / "profile.json"
    desired_profile = ProvisionProfile(
        environment="dev",
        region=region,
        target_binding=target_binding,
        connectivity="offline",
        host="managed-vm",
        transport="manual",
        access_method="bastion",
        shadow_only=True,
        approval_quorum=1,
        monthly_cost_ceiling=monthly_cost_ceiling,
    )
    stage = root / "stage"
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        kit_future = executor.submit(
            _ensure_kit,
            repository_root=repository_root,
            stage=stage,
            release_key=release_key,
            bundle_key=bundle_key,
            source_commit=source_commit,
        )
        if profile_path.exists():
            if load_profile(profile_path) != desired_profile:
                raise ValueError("existing Genesis profile differs from the requested deployment")
        else:
            write_profile(profile_path, desired_profile)
        variables_path = root / "foundation-variables.json"
        check = root / ".foundation-variables-check.json"
        check.unlink(missing_ok=True)
        if variables_path.exists():
            try:
                snapshot_foundation_input(
                    variables_path,
                    check,
                    expected_target_binding=target_binding,
                    expected_region=region,
                    expected_environment="dev",
                )
            finally:
                check.unlink(missing_ok=True)
            values = read_plan_input(variables_path)
            if values.get("source_commit") != source_commit:
                raise ValueError("existing Foundation variables use another source revision")
        else:
            values = foundation_values(
                repository_root=repository_root,
                source_commit=source_commit,
                tenant_id=tenant_id,
                subscription_id=subscription_id,
                region=region,
                target_binding=target_binding,
                run_binding=run_binding,
                ssh_public_key=read_private_bytes(ssh_public, max_bytes=16_384)
                .decode("ascii")
                .strip(),
            )
            write_plan_input(variables_path, values)
            try:
                snapshot_foundation_input(
                    variables_path,
                    check,
                    expected_target_binding=target_binding,
                    expected_region=region,
                    expected_environment="dev",
                )
            finally:
                check.unlink(missing_ok=True)
        verification = kit_future.result()
    return PreparedGenesis(
        root=root,
        stage=stage,
        profile=profile_path,
        variables=variables_path,
        ssh_private_key=ssh_key,
        source_commit=source_commit,
        target_binding=target_binding,
        run_binding=run_binding,
        kit_manifest_digest=verification.manifest_digest,
        offline_kit=stage / "kit",
        release_root=stage / "release-root.pub",
        bundle_public_key=stage / "bundle-key.pub",
        terraform=stage / "kit/terraform/terraform",
    )


def prepare_standalone_genesis(
    *,
    deployment_kit: DeploymentKit,
    tenant_id: str,
    subscription_id: str,
    region: str,
    monthly_cost_ceiling: int,
    connectivity: str,
    root: Path,
) -> PreparedGenesis:
    """Create target-bound inputs from an independently verified complete kit."""

    source_commit = deployment_kit.source_commit
    if (
        connectivity not in {"online", "offline"}
        or not re.fullmatch(r"[a-z][a-z0-9]+", region)
        or type(monthly_cost_ceiling) is not int
        or monthly_cost_ceiling <= 0
    ):
        raise ValueError("standalone Genesis preparation input is invalid")
    _private_directory(root)
    ssh_key = root / "runner_ed25519"
    _ensure_ed25519_key(ssh_key, openssh=True)
    ssh_public = root / "runner_ed25519.pub"
    _ensure_ssh_public_key(ssh_key, ssh_public)
    target_binding = compute_target_binding(
        tenant_id=tenant_id,
        subscription_id=subscription_id,
    )
    run_binding = hashlib.sha256(
        (
            f"{tenant_id.lower()}:{subscription_id.lower()}:{region}:dev:"
            "signed-kit:runner-image=true"
        ).encode()
    ).hexdigest()
    profile_path = root / "profile.json"
    desired_profile = ProvisionProfile(
        environment="dev",
        region=region,
        target_binding=target_binding,
        connectivity=connectivity,
        host="managed-vm",
        transport="manual",
        access_method="bastion",
        shadow_only=True,
        approval_quorum=1,
        monthly_cost_ceiling=monthly_cost_ceiling,
    )
    if profile_path.exists():
        if load_profile(profile_path) != desired_profile:
            raise ValueError("existing Genesis profile differs from the requested deployment")
    else:
        write_profile(profile_path, desired_profile)
    variables_path = root / "foundation-variables.json"
    if variables_path.exists():
        values = read_plan_input(variables_path)
        if values.get("source_commit") != source_commit:
            raise ValueError("existing Foundation variables use another source revision")
    else:
        values = foundation_values(
            repository_root=deployment_kit.bundle_root,
            source_commit=source_commit,
            tenant_id=tenant_id,
            subscription_id=subscription_id,
            region=region,
            target_binding=target_binding,
            run_binding=run_binding,
            ssh_public_key=read_private_bytes(ssh_public, max_bytes=16_384).decode("ascii").strip(),
            execution_transport="manual",
        )
        write_plan_input(variables_path, values)
    check = root / ".foundation-variables-check.json"
    check.unlink(missing_ok=True)
    try:
        snapshot_foundation_input(
            variables_path,
            check,
            expected_target_binding=target_binding,
            expected_region=region,
            expected_environment="dev",
        )
    finally:
        check.unlink(missing_ok=True)
    release_root = root / "deployment-release-root.pub"
    bundle_root = root / "deployment-bundle-root.pub"
    if not release_root.exists():
        write_private_bytes(release_root, deployment_release_root_pem())
    if not bundle_root.exists():
        write_private_bytes(bundle_root, deployment_bundle_root_pem())
    terraform = deployment_kit.materialized_root / deployment_kit.verification.terraform_binary
    return PreparedGenesis(
        root=root,
        stage=deployment_kit.materialized_root,
        profile=profile_path,
        variables=variables_path,
        ssh_private_key=ssh_key,
        source_commit=source_commit,
        target_binding=target_binding,
        run_binding=run_binding,
        kit_manifest_digest=deployment_kit.verification.manifest_digest,
        offline_kit=deployment_kit.root,
        release_root=release_root,
        bundle_public_key=bundle_root,
        terraform=terraform,
    )


def _ensure_kit(
    *,
    repository_root: Path,
    stage: Path,
    release_key: Path,
    bundle_key: Path,
    source_commit: str,
) -> OfflineKitVerification:
    marker = stage.parent / "kit-source.json"
    if marker.exists():
        value = read_plan_input(marker)
        if value.get("source_commit") != source_commit:
            raise ValueError("existing offline kit uses another source revision")
    else:
        source_epoch = _capture(
            ("git", "show", "-s", "--format=%ct", source_commit),
            cwd=repository_root,
        )
        environment = {**os.environ, "SOURCE_DATE_EPOCH": source_epoch}
        completed = run_with_heartbeat(
            (
                "bash",
                str(repository_root / "scripts/deployment/release/stage-offline-kit.sh"),
                "--out",
                str(stage),
                "--release-key",
                str(release_key),
                "--bundle-key",
                str(bundle_key),
                "--bundle-version",
                "0.1.0",
            ),
            cwd=repository_root,
            env=environment,
            timeout=1800,
            capture_output=False,
            umask=0o077,
        )
        if completed.returncode != 0:
            raise ValueError("signed offline kit staging failed")
        write_private_output(
            marker,
            json.dumps({"source_commit": source_commit}, sort_keys=True) + "\n",
        )
    release_root = _read_regular(stage / "release-root.pub", max_bytes=65_536)
    return verify_offline_kit(
        stage / "kit",
        release_root_pem=release_root,
        cli_version=__version__,
        platform_tag=_runtime_platform_tag(),
    )


def _ensure_ed25519_key(path: Path, *, openssh: bool) -> None:
    if path.exists():
        read_private_bytes(path, max_bytes=65_536)
        return
    key = Ed25519PrivateKey.generate()
    payload = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH if openssh else serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    write_private_bytes(path, payload)


def _ensure_ssh_public_key(private_path: Path, public_path: Path) -> None:
    private_key = serialization.load_ssh_private_key(
        read_private_bytes(private_path, max_bytes=65_536), password=None
    )
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("Genesis SSH key must be Ed25519")
    payload = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.OpenSSH,
            serialization.PublicFormat.OpenSSH,
        )
        .decode("ascii")
    )
    if public_path.exists():
        if read_private_bytes(public_path, max_bytes=16_384).decode("ascii").strip() != payload:
            raise ValueError("Genesis SSH public key differs from its private key")
        return
    write_private_output(public_path, payload + "\n")


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    details = path.lstat()
    if (
        not path.is_absolute()
        or not stat.S_ISDIR(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o700
        or details.st_uid != os.geteuid()
    ):
        raise PermissionError("Genesis work directory must be current-UID mode 0700")


def _capture(arguments: tuple[str, ...], *, cwd: Path) -> str:
    completed = subprocess.run(
        arguments,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise ValueError("Genesis preparation command failed")
    return completed.stdout.strip()


def _runtime_platform_tag() -> str:
    """Return the signed-kit platform identity derived from the current host."""

    architecture = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
    }.get(platform.machine().casefold())
    if sys.platform != "linux" or architecture is None:
        raise ValueError("Genesis preparation supports Linux x86_64 or aarch64")
    return f"linux-{architecture}"


def _read_regular(path: Path, *, max_bytes: int) -> bytes:
    """Read one bounded current-UID regular artifact without following links."""

    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.geteuid()
            or details.st_nlink != 1
            or not 0 < details.st_size <= max_bytes
        ):
            raise ValueError("Genesis artifact is not a bounded current-UID regular file")
        content = stream.read(max_bytes + 1)
        after = os.fstat(stream.fileno())
        if (
            len(content) != details.st_size
            or after.st_size != details.st_size
            or after.st_mtime_ns != details.st_mtime_ns
            or after.st_ctime_ns != details.st_ctime_ns
        ):
            raise ValueError("Genesis artifact changed while being read")
        return content


def main() -> int:
    """Prepare one exact-source private run from the active Azure CLI account."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--region", default="koreacentral")
    parser.add_argument("--monthly-cost-ceiling", type=int, default=1000)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[3]
    account = json.loads(
        _capture(
            (
                "az",
                "account",
                "show",
                "--query",
                "{subscription_id:id,tenant_id:tenantId,user_type:user.type}",
                "--output",
                "json",
                "--only-show-errors",
            ),
            cwd=repository_root,
        )
    )
    if not isinstance(account, dict) or account.get("user_type") != "user":
        raise ValueError("Genesis preparation requires an authenticated Azure human")
    prepared = prepare_genesis(
        repository_root=repository_root,
        repository=args.repository,
        source_commit=args.source_commit,
        tenant_id=str(account.get("tenant_id", "")),
        subscription_id=str(account.get("subscription_id", "")),
        region=args.region,
        monthly_cost_ceiling=args.monthly_cost_ceiling,
        root=args.work_dir,
    )
    print(
        json.dumps(
            {
                "schema_version": "fdai.genesis-prepared.v1",
                "source_commit": prepared.source_commit,
                "target_binding": prepared.target_binding,
                "run_binding": prepared.run_binding,
                "kit_manifest_digest": prepared.kit_manifest_digest,
                "work_dir": str(prepared.root),
                "profile": str(prepared.profile),
                "foundation_variables": str(prepared.variables),
                "ssh_private_key": str(prepared.ssh_private_key),
                "offline_kit": str(prepared.offline_kit),
                "release_root": str(prepared.release_root),
                "bundle_public_key": str(prepared.bundle_public_key),
                "mutation_performed": False,
                "subscription_ready": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
