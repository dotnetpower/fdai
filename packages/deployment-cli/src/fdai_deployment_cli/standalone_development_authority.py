"""Managed-host selection and reconciliation of development authority."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fdai_deployment_cli.development_authority_profile import (
    DevelopmentAuthorityDeploymentProfile,
    apply_development_authority_profile,
    clear_development_authority_profile,
    load_development_authority_profile,
    staged_development_authority_profile_from_path,
    validate_deployment_target,
)
from fdai_deployment_cli.standalone_operational_evidence import bind_service_database_role

_PROFILE_ENV = "FDAI_FULL_AUTHORITY_DEVELOPMENT_PROFILE_JSON"
_EXECUTOR_ENV = "FDAI_FULL_AUTHORITY_DEVELOPMENT_EXECUTOR_PRINCIPAL"


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
    if path is not None and not isinstance(path, Path):
        raise TypeError("development authority profile path is invalid")
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


def apply_service_update_development_authority(
    args: argparse.Namespace,
    *,
    context: dict[str, object],
    workload: dict[str, object],
    source_revision: str,
) -> tuple[str, str]:
    """Apply one explicit Core select/clear operation to retained workload variables."""

    component = workload.get("component")
    environment = workload.get("environment")
    if component is not None:
        if not isinstance(component, str) or not isinstance(environment, dict):
            raise TypeError("service workload database-role inputs are invalid")
        workload["environment"] = bind_service_database_role(component, environment)
    path = getattr(args, "development_authority_profile", None)
    if path is not None and not isinstance(path, Path):
        raise TypeError("development authority profile path is invalid")
    clear = bool(getattr(args, "clear_development_authority_profile", False))
    if path is not None and clear:
        raise ValueError("development authority profile and clear request are mutually exclusive")
    if path is None and not clear:
        return "preserve", ""
    environment = workload.get("environment")
    if not isinstance(environment, dict):
        raise TypeError("Core workload environment is invalid")
    if clear:
        changed = environment.pop(_PROFILE_ENV, None) is not None
        changed = environment.pop(_EXECUTOR_ENV, None) is not None or changed
        if not changed:
            raise ValueError("Core workload has no retained development profile to clear")
        return "clear", ""
    if path is None:
        raise RuntimeError("development authority profile is unavailable")
    profile = load_development_authority_profile(path.absolute())
    validate_deployment_target(
        profile,
        tenant_id=str(context["tenant_id"]),
        subscription_id=str(context["subscription_id"]),
        resource_groups=(
            str(context["resource_group_name"]),
            str(context["state_resource_group"]),
        ),
        source_revision=source_revision,
    )
    environment[_PROFILE_ENV] = profile.profile_json
    environment[_EXECUTOR_ENV] = profile.executor_principal
    return "select", profile.input_digest


__all__ = [
    "ManagedDevelopmentAuthority",
    "apply_initial_development_authority",
    "apply_service_update_development_authority",
    "development_authority_from_args",
    "reconcile_retained_development_authority",
]
