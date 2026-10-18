"""Managed-host selection and reconciliation of development authority."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from fdai_deployment_cli.development_authority_profile import (
    DevelopmentAuthorityDeploymentProfile,
    apply_development_authority_profile,
    clear_development_authority_profile,
    staged_development_authority_profile_from_path,
    validate_deployment_target,
)


@dataclass(frozen=True, slots=True)
class ManagedDevelopmentAuthority:
    """One explicitly selected profile operation on the managed host."""

    profile: DevelopmentAuthorityDeploymentProfile | None
    clear: bool

    @property
    def input_digest(self) -> str:
        return self.profile.input_digest if self.profile is not None else ""


def development_authority_from_args(
    args: argparse.Namespace,
    *,
    absolute: Callable[[Path], Path],
) -> ManagedDevelopmentAuthority:
    """Load the staged profile and reject an ambiguous select-and-clear request."""

    path = getattr(args, "development_authority_profile", None)
    profile = staged_development_authority_profile_from_path(
        absolute(path) if path is not None else None
    )
    clear = bool(getattr(args, "clear_development_authority_profile", False))
    if profile is not None and clear:
        raise ValueError("development authority profile and clear request are mutually exclusive")
    return ManagedDevelopmentAuthority(profile=profile, clear=clear)


def reconcile_retained_development_authority(
    selection: ManagedDevelopmentAuthority,
    *,
    retained: dict[str, object],
    values: dict[str, object],
    tenant_id: str,
    subscription_id: str,
    resource_groups: tuple[str, ...],
) -> bool:
    """Apply an explicit select or clear operation after source rebinding."""

    if selection.clear:
        changed = clear_development_authority_profile(values)
        return retained.pop("development_authority_profile_digest", None) is not None or changed
    if selection.profile is None:
        return False
    validate_deployment_target(
        selection.profile,
        tenant_id=tenant_id,
        subscription_id=subscription_id,
        resource_groups=resource_groups,
        source_revision=str(retained.get("source_commit", "")),
    )
    apply_development_authority_profile(values, selection.profile)
    changed = retained.get("development_authority_profile_digest") != selection.profile.input_digest
    retained["development_authority_profile_digest"] = selection.profile.input_digest
    return changed


def apply_initial_development_authority(
    selection: ManagedDevelopmentAuthority,
    *,
    values: dict[str, object],
    tenant_id: str,
    subscription_id: str,
    resource_groups: tuple[str, ...],
    source_revision: str,
) -> str:
    """Bind a selected profile on a new install, or reject an impossible clear."""

    if selection.clear:
        raise ValueError("development authority profile cannot be cleared on a new installation")
    if selection.profile is None:
        return ""
    validate_deployment_target(
        selection.profile,
        tenant_id=tenant_id,
        subscription_id=subscription_id,
        resource_groups=resource_groups,
        source_revision=source_revision,
    )
    apply_development_authority_profile(values, selection.profile)
    return selection.profile.input_digest


__all__ = [
    "ManagedDevelopmentAuthority",
    "apply_initial_development_authority",
    "development_authority_from_args",
    "reconcile_retained_development_authority",
]
