"""CLI selection rules for the source development-authority input."""

from __future__ import annotations

import argparse
from pathlib import Path

from fdai_deployment_cli.development_authority_profile import (
    DevelopmentAuthorityDeploymentProfile,
    load_development_authority_profile,
)


def selected_development_authority(
    args: argparse.Namespace,
    *,
    cwd: Path,
) -> tuple[DevelopmentAuthorityDeploymentProfile | None, bool]:
    """Load and validate the mutually exclusive select/clear operation."""

    selected_path = args.development_authority_profile
    profile = (
        None
        if selected_path is None
        else load_development_authority_profile(
            selected_path if selected_path.is_absolute() else cwd / selected_path
        )
    )
    clear = bool(args.clear_development_authority_profile)
    if profile is not None and clear:
        raise ValueError(
            "--development-authority-profile and --clear-development-profile are mutually exclusive"
        )
    return profile, clear


def validate_development_authority_command(
    args: argparse.Namespace,
    *,
    profile: DevelopmentAuthorityDeploymentProfile | None,
    clear: bool,
) -> None:
    """Restrict authority changes to one source-AKS application run."""

    if profile is None and not clear:
        return
    if args.source is None or args.runtime != "aks":
        raise ValueError("development authority changes require source AKS deployment")
    if args.prepare_only or args.preflight_only or args.teardown:
        raise ValueError("development authority changes require an application deployment run")


__all__ = [
    "selected_development_authority",
    "validate_development_authority_command",
]
