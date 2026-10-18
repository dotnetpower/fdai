"""Public CLI input selection for one source service update."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from fdai_deployment_cli.development_authority_cli import (
    selected_development_authority,
)
from fdai_deployment_cli.development_authority_profile import (
    DevelopmentAuthorityDeploymentProfile,
)


def source_service_update_inputs(
    args: argparse.Namespace,
) -> tuple[
    Path,
    Path,
    Path,
    DevelopmentAuthorityDeploymentProfile | None,
    bool,
]:
    """Resolve paths and the Core-only development-authority operation."""

    source = args.source.absolute()
    application = args.application_work_dir.absolute()
    selected = args.work_dir
    if selected is None:
        commit = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=source,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        selected = Path.home() / ".local/state/fdai/source-service-updates" / commit / args.service
    profile, clear = selected_development_authority(args, cwd=Path.cwd())
    if (profile is not None or clear) and args.service != "core-control-plane":
        raise ValueError("development authority changes require a Core service update")
    return source, application, selected, profile, clear


__all__ = ["source_service_update_inputs"]
