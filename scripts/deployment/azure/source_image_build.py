"""Build source-only OCI inputs locally; private registry operations remain on the managed host."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.oci_archive import validate_oci_archive
from fdai_deployment_cli.private_output import (
    _open_private_parent,
    read_private_bytes,
    write_private_bytes,
)
from fdai_deployment_cli.runtime_release import RUNTIME_SERVICES
from fdai_deployment_cli.source_snapshot import verify_source_snapshot
from genesis_checks import CheckError, trusted_tool


def inspect_source_image_builder(*, timeout_seconds: int = 60) -> dict[str, object]:
    """Observe the local Docker engine and Buildx without building or contacting a registry.

    Remote Docker contexts and BuildKit endpoints are excluded. Missing or invalid tools
    return a blocked record rather than installing software, prompting, or creating images.
    This is prerequisite evidence only, not source, artifact or deployment authorization.
    """
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 300:
        raise ValueError("source image builder probe requires a bounded timeout")
    deadline = DeploymentDeadline(timeout_seconds)
    try:
        docker = trusted_tool("docker")
        prefix = (docker, "--host", "unix:///var/run/docker.sock")
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("DOCKER_", "BUILDX_", "BUILDKIT_"))
        }
        versions = []
        for arguments in (("version", "--format", "{{.Server.Version}}"), ("buildx", "version")):
            result = subprocess.run(
                (*prefix, *arguments),
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
                timeout=deadline.remaining(),
            )
            if result.returncode != 0 or len(result.stdout) > 4096:
                raise ValueError("source image builder is unavailable")
            versions.append(result.stdout.strip())
        if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9._-]+)?", versions[0]) is None:
            raise ValueError("source image Docker engine version is invalid")
        buildx = re.fullmatch(
            r"github\.com/docker/buildx (v?[0-9]+\.[0-9]+\.[0-9]+)(?: [A-Za-z0-9._+~-]+)?",
            versions[1],
        )
        if buildx is None:
            raise ValueError("source image Buildx version is invalid")
    except (OSError, ValueError, CheckError, subprocess.SubprocessError):
        return {
            "schema_version": "fdai.source-image-builder.v1",
            "state": "blocked",
            "reason_code": "local_docker_buildx_required",
            "mutation_performed": False,
            "deployment_ready": False,
        }
    receipt: dict[str, object] = {
        "schema_version": "fdai.source-image-builder.v1",
        "state": "available",
        "docker_version": versions[0],
        "buildx_version": buildx.group(1),
        "docker_endpoint": "local-unix",
        "mutation_performed": False,
        "deployment_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    return receipt


def build_source_image(
    snapshot: Path,
    work_dir: Path,
    *,
    snapshot_digest: str,
    service: str,
    timeout_seconds: int,
    verify_only: bool = False,
) -> dict[str, object]:
    """Build one baseline service into a private OCI archive, without a kit or registry push.

    Exact snapshot, source revision and platform bind a pre-build claim. A successful
    receipt requires independent OCI content validation; a retained ambiguous claim is
    never rebuilt. Existing success is reusable only after source and archive revalidation.
    The bounded repository runner limits build duration and output silence, and generated
    artifacts remain outside the source. Image validity does not prove runtime readiness.
    Explicit verification-only recovery may validate completed bytes after interruption,
    but cannot invoke Docker, overwrite an archive, or repair incomplete build content.
    """
    deadline = DeploymentDeadline(timeout_seconds)
    if service not in RUNTIME_SERVICES:
        raise ValueError("source image service is outside the baseline inventory")
    if not work_dir.is_absolute() or any(character in str(work_dir) for character in ",\r\n"):
        raise ValueError("source image work directory is invalid")
    source = verify_source_snapshot(snapshot, expected_digest=snapshot_digest)
    if work_dir.resolve().is_relative_to(snapshot.resolve()):
        raise ValueError("source image outputs must remain outside the immutable snapshot")
    source_commit = str(source["source_commit"])
    tree = snapshot / "tree"
    dockerfile = tree / "services" / service / "docker/Dockerfile"
    supervisor = tree / "scripts/automation/run-bounded-command.py"
    if not dockerfile.is_file() or not supervisor.is_file():
        raise ValueError("source image build inputs are unavailable")
    if not work_dir.exists():
        parent = _open_private_parent(work_dir)
        try:
            os.mkdir(work_dir.name, 0o700, dir_fd=parent)
        finally:
            os.close(parent)
    archive = work_dir / f"{service}.oci.tar"
    metadata = work_dir / f"{service}.metadata.json"
    claim_path = work_dir / f"{service}.claim.json"
    receipt_path = work_dir / f"{service}.receipt.json"
    claim = {
        "schema_version": "fdai.source-image-build-claim.v1",
        "source_commit": source_commit,
        "snapshot_digest": snapshot_digest,
        "service": service,
        "platform_tag": "linux-x86_64",
    }
    recovery = claim_path.exists() or claim_path.is_symlink()
    if verify_only and not recovery:
        raise ValueError("source image verification requires a retained exact build claim")
    if recovery:
        if _read_json(claim_path) != claim:
            raise ValueError("source image build claim differs; preserve the work directory")
        if not receipt_path.exists() and not verify_only:
            raise ValueError("source image build is incomplete; do not automatically rebuild")
        retained = _read_json(receipt_path) if receipt_path.exists() else None
        if retained is not None:
            digest = retained.pop("receipt_digest", None)
            if canonical_digest(retained) != digest:
                raise ValueError("source image receipt digest differs")
    else:
        builder = inspect_source_image_builder(timeout_seconds=deadline.remaining(60))
        if builder["state"] != "available":
            return builder
        if any(path.exists() or path.is_symlink() for path in (archive, metadata, receipt_path)):
            raise ValueError("source image outputs already exist without a claim")
        write_private_bytes(claim_path, canonical_bytes(claim))
        log_path = work_dir / f"{service}.build.log"
        parent = _open_private_parent(log_path)
        try:
            descriptor = os.open(
                log_path.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
        finally:
            os.close(parent)
        remaining = deadline.remaining(3600)
        command = (
            sys.executable,
            str(supervisor),
            "--label",
            f"source-image-{service}",
            "--timeout-seconds",
            str(remaining),
            "--no-progress-seconds",
            str(min(300, remaining)),
            "--",
            trusted_tool("docker"),
            "--host",
            "unix:///var/run/docker.sock",
            "buildx",
            "build",
            "--builder",
            "default",
            "--progress=plain",
            "--platform",
            "linux/amd64",
            "--provenance=false",
            "--sbom=false",
            "--file",
            str(dockerfile),
            "--label",
            f"org.opencontainers.image.revision={source_commit}",
            "--metadata-file",
            str(metadata),
            "--output",
            f"type=oci,dest={archive}",
            str(tree),
        )
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("DOCKER_", "BUILDX_", "BUILDKIT_"))
        }
        with os.fdopen(descriptor, "wb") as log:
            result = subprocess.run(
                command,
                cwd=tree,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
                umask=0o077,
            )
            log.flush()
            os.fsync(log.fileno())
        if result.returncode != 0:
            raise ValueError("source image build failed; preserve the claim and private build log")
        retained = None
    deadline.remaining()
    verify_source_snapshot(snapshot, expected_digest=snapshot_digest)
    _seal_build_metadata(metadata)
    image_digest = _read_json(metadata).get("containerimage.digest")
    if (
        not isinstance(image_digest, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest) is None
    ):
        raise ValueError("source image build did not report one content digest")
    archive_digest = hashlib.sha256(
        read_private_bytes(archive, max_bytes=512 * 1024 * 1024)
    ).hexdigest()
    verified = validate_oci_archive(
        archive,
        expected_archive_sha256=archive_digest,
        expected_manifest_digest=image_digest,
        expected_source_commit=source_commit,
        expected_platform_tag="linux-x86_64",
    )
    deadline.remaining()
    receipt: dict[str, object] = {
        **claim,
        "schema_version": "fdai.source-image-build-receipt.v1",
        "state": "built",
        "archive_ref": archive.name,
        "archive_sha256": verified.archive_sha256,
        "image_digest": verified.manifest.digest,
        "provenance": "operator-selected-source",
        "release_signature_verified": False,
        "registry_published": False,
        "apply_authorized": False,
        "deployment_ready": False,
        "mutation_performed": False,
    }
    if retained is not None and receipt != retained:
        raise ValueError("retained source image receipt differs from verified content")
    receipt["receipt_digest"] = canonical_digest(receipt)
    if retained is None:
        write_private_bytes(receipt_path, canonical_bytes(receipt))
    return receipt


def _seal_build_metadata(path: Path) -> None:
    """Tighten Buildx's owner-created 0644 metadata through a held private parent."""
    parent = _open_private_parent(path)
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            details = os.fstat(descriptor)
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_uid != os.geteuid()
                or details.st_nlink != 1
                or stat.S_IMODE(details.st_mode) not in {0o600, 0o644}
                or not 0 < details.st_size <= 65536
            ):
                raise ValueError("source image metadata ownership or file shape is invalid")
            if stat.S_IMODE(details.st_mode) != 0o600:
                os.fchmod(descriptor, 0o600)
                os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        os.close(parent)


def _read_json(path: Path) -> dict[str, object]:
    return load_json_object(
        read_private_bytes(path, max_bytes=65536), label="source image evidence", max_bytes=65536
    )


def build_source_images(
    snapshot: Path, work_dir: Path, *, snapshot_digest: str, timeout_seconds: int
) -> dict[str, object]:
    """Build or reverify all five baseline images within one shared deadline, without publishing."""
    deadline = DeploymentDeadline(timeout_seconds)
    source = verify_source_snapshot(snapshot, expected_digest=snapshot_digest)
    services = {}
    for service in sorted(RUNTIME_SERVICES):
        image = build_source_image(
            snapshot,
            work_dir,
            snapshot_digest=snapshot_digest,
            service=service,
            timeout_seconds=deadline.remaining(),
        )
        if image["state"] != "built":
            return image
        services[service] = image
    receipt: dict[str, object] = {
        "schema_version": "fdai.source-images.v1",
        "state": "built",
        "source_commit": source["source_commit"],
        "snapshot_digest": snapshot_digest,
        "services": services,
        "provenance": "operator-selected-source",
        "registry_published": False,
        "dependency_images_verified": False,
        "apply_authorized": False,
        "deployment_ready": False,
        "mutation_performed": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    return receipt


def main() -> int:
    """Emit sanitized source-image prerequisite or build evidence without registry publication."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-tools", action="store_true")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--snapshot-digest")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--service", choices=sorted(RUNTIME_SERVICES))
    parser.add_argument("--all-services", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    args = parser.parse_args()
    try:
        if args.check_tools:
            receipt = inspect_source_image_builder(timeout_seconds=min(60, args.timeout_seconds))
        elif args.all_services:
            if (
                args.service is not None
                or args.verify_only
                or any(
                    value is None for value in (args.snapshot, args.snapshot_digest, args.work_dir)
                )
            ):
                raise ValueError(
                    "source image inventory requires an exact snapshot without a service override"
                )
            receipt = build_source_images(
                args.snapshot,
                args.work_dir,
                snapshot_digest=args.snapshot_digest,
                timeout_seconds=args.timeout_seconds,
            )
        else:
            if any(
                value is None
                for value in (args.snapshot, args.snapshot_digest, args.work_dir, args.service)
            ):
                raise ValueError(
                    "source image build requires exact snapshot, work directory and service"
                )
            receipt = build_source_image(
                args.snapshot,
                args.work_dir,
                snapshot_digest=args.snapshot_digest,
                service=args.service,
                timeout_seconds=args.timeout_seconds,
                verify_only=args.verify_only,
            )
        print(canonical_bytes(receipt).decode())
        return 3 if receipt["state"] == "blocked" and not args.check_tools else 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        print(
            "source image build failed; preserve private evidence without retrying", file=sys.stderr
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
