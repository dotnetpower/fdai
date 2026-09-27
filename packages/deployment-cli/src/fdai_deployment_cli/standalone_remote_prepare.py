"""Prepare the managed-host application workspace from verified private inputs."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from fdai_deployment_cli.application_state_adoption import ApplicationStateAdoption
from fdai_deployment_cli.catalog_review_profile import (
    CatalogReviewDeploymentProfile,
    stage_catalog_review_profile,
)
from fdai_deployment_cli.foundation_adoption_transport import stage_foundation_context
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile


def prepare_remote(
    tunnel: Any,
    *,
    remote_root: str,
    remote_archive: str,
    archive: Path,
    archive_digest: str,
    handoff_path: Path,
    remote_handoff: str,
    entra_path: Path,
    remote_entra: str,
    app_work: str,
    runtime_profile: RuntimeDeploymentProfile | None = None,
    application_state_adoption: ApplicationStateAdoption | None = None,
    remote_adoption_state: str = "",
    remote_adoption_models: str = "",
    remote_adoption_descriptor: str = "",
    timeout_seconds: int,
    catalog_review_profile: CatalogReviewDeploymentProfile | None = None,
) -> None:
    """Transfer exact inputs and invoke the value-free host preparation command."""

    selected_runtime = runtime_profile or RuntimeDeploymentProfile.create(
        runtime_platform="container-apps",
        database_placement="postgres-flex",
    )
    created = tunnel.ssh(("install", "-d", "-m", "0700", remote_root), timeout=60)
    if created.returncode != 0:
        raise ValueError("standalone remote work directory is unavailable")
    removed = tunnel.ssh(("rm", "-f", "--", remote_archive), timeout=60)
    if removed.returncode != 0:
        raise ValueError("standalone remote archive reset failed")
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
    digest = tunnel.ssh(("sha256sum", remote_archive), timeout=300)
    if digest.returncode != 0 or digest.stdout.split(maxsplit=1)[0] != archive_digest:
        raise ValueError("standalone transport archive digest differs")
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
            "prepare",
            "--kit",
            f"{remote_root}/kit",
            "--handoff",
            foundation.handoff,
            "--entra",
            foundation.entra,
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
            (("rm", "-rf", "--", f"{remote_root}/kit"), 300),
            (("tar", "-xzf", remote_archive, "-C", remote_root), 1800),
            (("python3", "-m", "venv", f"{remote_root}/venv"), 300),
            (
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
            (("install", "-d", "-m", "0700", app_work), 60),
            (prepare_arguments, 1800),
        )
        for command, limit in commands:
            setup = tunnel.ssh(command, timeout=min(limit, timeout_seconds))
            if setup.returncode != 0:
                raise ValueError("standalone managed-host preparation failed")
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as setup_failure:
        try:
            _cleanup_catalog_review_staging(tunnel, remote_root=remote_root)
        except ValueError as cleanup_failure:
            raise cleanup_failure from setup_failure
        raise
    _cleanup_catalog_review_staging(tunnel, remote_root=remote_root)


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
