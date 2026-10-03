"""Prepare the managed-host application workspace from verified private inputs."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from fdai_deployment_cli.application_state_adoption import ApplicationStateAdoption
from fdai_deployment_cli.catalog_review_profile import (
    CatalogReviewDeploymentProfile,
    stage_catalog_review_profile,
)
from fdai_deployment_cli.control_package import PACKAGE_ROOT, ControlPackage
from fdai_deployment_cli.foundation_adoption_transport import stage_foundation_context
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile


def prepare_remote(
    tunnel: Any,
    *,
    remote_root: str,
    remote_archive: str,
    archive: Path | None,
    archive_digest: str | None,
    handoff_path: Path,
    remote_handoff: str,
    entra_path: Path | None,
    remote_entra: str | None,
    app_work: str,
    source_archive: Path | None = None,
    source_archive_digest: str | None = None,
    source_receiver: Path | None = None,
    source_receiver_digest: str | None = None,
    source_snapshot_digest: str | None = None,
    runtime_profile: RuntimeDeploymentProfile | None = None,
    application_state_adoption: ApplicationStateAdoption | None = None,
    remote_adoption_state: str = "",
    remote_adoption_models: str = "",
    remote_adoption_descriptor: str = "",
    timeout_seconds: int,
    catalog_review_profile: CatalogReviewDeploymentProfile | None = None,
    control_package: ControlPackage | None = None,
) -> dict[str, object]:
    """Transfer exact inputs and invoke the value-free host preparation command.

    With a verified ``control_package``, the host installs ``fdai-deployment-cli`` only from
    that signed wheelhouse after a remote digest match; the kit still supplies every runtime
    payload. Without it, the host installs the CLI from the kit wheels.
    """

    selected_runtime = runtime_profile or RuntimeDeploymentProfile.create(
        runtime_platform="container-apps",
        database_placement="postgres-flex",
    )
    source_mode = source_archive is not None
    if source_mode:
        if not all(
            value is not None
            for value in (
                source_archive_digest,
                source_receiver,
                source_receiver_digest,
                source_snapshot_digest,
            )
        ):
            raise ValueError("source managed-host preparation inputs are incomplete")
        if archive is not None or archive_digest is not None or control_package is not None:
            raise ValueError("source managed-host preparation cannot use kit inputs")
    elif archive is None or archive_digest is None:
        raise ValueError("kit managed-host preparation inputs are incomplete")
    created = tunnel.ssh(("install", "-d", "-m", "0700", remote_root), timeout=60)
    if created.returncode != 0:
        raise ValueError("standalone remote work directory is unavailable")
    removed = tunnel.ssh(("rm", "-f", "--", remote_archive), timeout=60)
    if removed.returncode != 0:
        raise ValueError("standalone remote archive reset failed")
    remote_source_archive = f"{remote_root}/source-transfer.tar"
    remote_source_receiver = f"{remote_root}/source-receiver.pyz"
    if source_mode:
        assert source_archive is not None
        assert source_receiver is not None
        tunnel.copy_to(source_archive, remote_source_archive, timeout=min(1800, timeout_seconds))
        tunnel.copy_to(source_receiver, remote_source_receiver, timeout=300)
    else:
        assert archive is not None
        tunnel.copy_to(archive, remote_archive, timeout=min(1800, timeout_seconds))
    foundation = stage_foundation_context(
        tunnel,
        handoff_path,
        remote_handoff,
        entra_path,
        remote_entra,
        remote_root,
    )
    if application_state_adoption is not None:
        if not all((remote_adoption_state, remote_adoption_models, remote_adoption_descriptor)):
            raise ValueError("standalone application adoption destinations are incomplete")
        tunnel.copy_to(application_state_adoption.state, remote_adoption_state, timeout=300)
        tunnel.copy_to(
            application_state_adoption.resolved_models, remote_adoption_models, timeout=120
        )
        tunnel.copy_to(
            application_state_adoption.descriptor, remote_adoption_descriptor, timeout=120
        )
    if source_mode:
        assert source_archive_digest is not None
        assert source_receiver_digest is not None
        archive_digest_result = tunnel.ssh(("sha256sum", remote_source_archive), timeout=300)
        receiver_digest_result = tunnel.ssh(("sha256sum", remote_source_receiver), timeout=120)
        if (
            archive_digest_result.returncode != 0
            or archive_digest_result.stdout.split(maxsplit=1)[0] != source_archive_digest
            or receiver_digest_result.returncode != 0
            or receiver_digest_result.stdout.split(maxsplit=1)[0] != source_receiver_digest
        ):
            raise ValueError("source transport digest differs")
        install_cli = _source_cli_installation(remote_root)
    else:
        digest = tunnel.ssh(("sha256sum", remote_archive), timeout=300)
        if digest.returncode != 0 or digest.stdout.split(maxsplit=1)[0] != archive_digest:
            raise ValueError("standalone transport archive digest differs")
        install_cli = _kit_cli_installation(remote_root)
    if control_package is not None:
        install_cli = _stage_control_package(tunnel, remote_root, control_package)
    try:
        catalog_review_arguments = stage_catalog_review_profile(
            catalog_review_profile or CatalogReviewDeploymentProfile.unselected(),
            tunnel=tunnel,
            prepared_root=handoff_path.parent,
            remote_root=remote_root,
        )
        prepare_arguments = (
            f"{remote_root}/venv/bin/python",
            "-m",
            "fdai_deployment_cli.standalone_host",
            "--work-dir",
            app_work,
            *(
                (
                    "prepare-source",
                    "--source-snapshot",
                    f"{remote_root}/source-snapshot",
                    "--source-snapshot-digest",
                    str(source_snapshot_digest),
                )
                if source_mode
                else ("prepare", "--kit", f"{remote_root}/kit")
            ),
            "--handoff",
            foundation.handoff,
            *(("--entra", foundation.entra) if foundation.entra is not None else ()),
            *foundation.adoption_arguments,
            "--runtime-platform",
            selected_runtime.runtime_platform.value,
            "--database-placement",
            selected_runtime.database_placement.value,
            "--system-node-count",
            str(selected_runtime.system_node_count),
            "--system-node-sku",
            selected_runtime.system_node_sku,
            "--user-node-min-count",
            str(selected_runtime.user_node_min_count),
            "--user-node-max-count",
            str(selected_runtime.user_node_max_count),
            "--user-node-sku",
            selected_runtime.user_node_sku,
            *(
                ("--database-sku", selected_runtime.database_sku)
                if selected_runtime.database_sku is not None
                else ()
            ),
            *(
                value
                for add_on in selected_runtime.product_profile.add_ons
                for value in ("--product-add-on", add_on.value)
            ),
            *(
                value
                for source in selected_runtime.product_profile.observation_permissions.selected_sources
                for value in ("--observation-source", source.value)
            ),
            *catalog_review_arguments,
            *(
                (
                    "--adoption-state",
                    remote_adoption_state,
                    "--adoption-models",
                    remote_adoption_models,
                    "--adoption-descriptor",
                    remote_adoption_descriptor,
                )
                if application_state_adoption is not None
                else ()
            ),
        )
        commands = (
            *(
                (
                    ("clean-source", ("rm", "-rf", "--", f"{remote_root}/source-snapshot"), 300),
                    (
                        "receive-source",
                        (
                            "python3",
                            remote_source_receiver,
                            "--archive",
                            remote_source_archive,
                            "--destination",
                            f"{remote_root}/source-snapshot",
                            "--archive-digest",
                            str(source_archive_digest),
                            "--snapshot-digest",
                            str(source_snapshot_digest),
                        ),
                        1800,
                    ),
                )
                if source_mode
                else (
                    ("clean-kit", ("rm", "-rf", "--", f"{remote_root}/kit"), 300),
                    ("extract-kit", ("tar", "-xzf", remote_archive, "-C", remote_root), 1800),
                )
            ),
            ("clean-venv", ("rm", "-rf", "--", f"{remote_root}/venv"), 300),
            ("create-venv", ("python3", "-m", "venv", f"{remote_root}/venv"), 300),
            *install_cli,
            ("create-workdir", ("install", "-d", "-m", "0700", app_work), 60),
            ("prepare", prepare_arguments, 1800),
        )
        setup = None
        for step, command, limit in commands:
            setup = tunnel.ssh(command, timeout=min(limit, timeout_seconds))
            if setup.returncode != 0:
                raise ValueError(f"standalone managed-host preparation failed: step={step}")
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as setup_failure:
        try:
            _cleanup_catalog_review_staging(tunnel, remote_root=remote_root)
        except ValueError as cleanup_failure:
            raise cleanup_failure from setup_failure
        raise
    _cleanup_catalog_review_staging(tunnel, remote_root=remote_root)
    if setup is None:
        raise ValueError("standalone managed-host preparation returned no result")
    try:
        result = json.loads(setup.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("standalone managed-host preparation returned invalid output") from exc
    if (
        not isinstance(result, dict)
        or result.get("state") != "prepared"
        or type(result.get("focused_private_access")) is not bool
    ):
        raise ValueError("standalone managed-host preparation result is invalid")
    return {str(key): value for key, value in result.items()}


def _kit_cli_installation(remote_root: str) -> tuple[tuple[str, tuple[str, ...], int], ...]:
    return (
        (
            "install-kit-cli",
            (
                f"{remote_root}/venv/bin/pip",
                "install",
                "--no-index",
                "--no-cache-dir",
                "--find-links",
                f"{remote_root}/kit/python",
                "fdai-deployment-cli",
            ),
            900,
        ),
    )


def _source_cli_installation(remote_root: str) -> tuple[tuple[str, tuple[str, ...], int], ...]:
    return (
        (
            "install-source-cli",
            (
                f"{remote_root}/venv/bin/pip",
                "install",
                "--no-cache-dir",
                f"{remote_root}/source-snapshot/tree/packages/deployment-cli",
            ),
            900,
        ),
    )


def _stage_control_package(
    tunnel: Any, remote_root: str, control_package: ControlPackage
) -> tuple[tuple[str, tuple[str, ...], int], ...]:
    """Copy the locally verified wheelhouse and require the same bytes on the host."""

    remote_control = f"{remote_root}/control.tar.gz"
    control_root = f"{remote_root}/control"
    if tunnel.ssh(("rm", "-f", "--", remote_control), timeout=60).returncode != 0:
        raise ValueError("standalone control package reset failed")
    tunnel.copy_to(control_package.archive, remote_control, timeout=300)
    digest = tunnel.ssh(("sha256sum", remote_control), timeout=120)
    if (
        digest.returncode != 0
        or digest.stdout.split(maxsplit=1)[0] != control_package.archive_digest
    ):
        raise ValueError("standalone control package digest differs")
    package = f"{control_root}/{PACKAGE_ROOT}"
    return (
        ("clean-control-package", ("rm", "-rf", "--", control_root), 120),
        ("create-control-package-dir", ("install", "-d", "-m", "0700", control_root), 60),
        ("extract-control-package", ("tar", "-xzf", remote_control, "-C", control_root), 300),
        (
            "install-control-package",
            (
                f"{remote_root}/venv/bin/pip",
                "install",
                "--no-index",
                "--no-cache-dir",
                "--find-links",
                f"{package}/wheels",
                "--requirement",
                f"{package}/requirements.txt",
            ),
            900,
        ),
    )


def _cleanup_catalog_review_staging(tunnel: Any, *, remote_root: str) -> None:
    """Require removal and absence readback for both staged credential files."""

    try:
        cleanup = tunnel.ssh(
            (
                "rm",
                "-f",
                "--",
                f"{remote_root}/catalog-review-profile.json",
                f"{remote_root}/catalog-review-private-key.pem",
            ),
            timeout=60,
        )
        profile_absent = tunnel.ssh(
            ("test", "!", "-e", f"{remote_root}/catalog-review-profile.json"),
            timeout=60,
        )
        key_absent = tunnel.ssh(
            ("test", "!", "-e", f"{remote_root}/catalog-review-private-key.pem"),
            timeout=60,
        )
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        raise ValueError("standalone catalog review profile cleanup is incomplete") from exc
    if any(result.returncode != 0 for result in (cleanup, profile_absent, key_absent)):
        raise ValueError("standalone catalog review profile cleanup is incomplete")


__all__ = ["prepare_remote"]
