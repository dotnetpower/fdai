"""Verifier own-role readback for deployed startup safety."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class VerifierOwnRoleReadbackError(RuntimeError):
    """Own-role readback was unavailable or malformed."""


@dataclass(frozen=True, slots=True)
class VerifierRoleAssignment:
    """One Azure role assignment observed for the verifier principal."""

    scope: str
    role_definition_id: str
    role_name: str
    actions: tuple[str, ...] = ()
    data_actions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VerifierOwnRoleReadback:
    """The complete role-assignment readback for one verifier principal."""

    principal_id: str
    assignments: tuple[VerifierRoleAssignment, ...]
    complete: bool
    observed_scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OwnRolePolicy:
    """Allowed verifier role boundary."""

    verifier_principal_id: str
    allowed_role_scopes: Mapping[str, tuple[str, ...]]
    allowed_management_read_roles: tuple[str, ...] = (
        "AcrPull",
        "Key Vault Secrets User",
        "Reader",
        "Monitoring Reader",
    )


def evaluate_verifier_own_roles(
    readback: VerifierOwnRoleReadback,
    *,
    policy: OwnRolePolicy,
) -> tuple[str, ...]:
    """Return fail-closed reasons for unsafe or incomplete verifier role assignments."""

    reasons: list[str] = []
    if readback.principal_id != policy.verifier_principal_id:
        reasons.append("role_readback_principal_mismatch")
    if not readback.complete:
        reasons.append("role_readback_partial")
    if not readback.observed_scopes:
        reasons.append("role_readback_unavailable")
    for assignment in readback.assignments:
        role_name = assignment.role_name.strip()
        if not role_name or (not assignment.actions and not assignment.data_actions):
            reasons.append("role_definition_unresolved")
            continue
        if not _scope_is_exact(assignment.scope, policy.allowed_role_scopes.get(role_name, ())):
            reasons.append("role_scope_not_allowed")
            continue
        if _has_write_access(assignment):
            reasons.append("write_role_outside_proof_store")
            continue
        if (
            _has_data_plane_access(assignment)
            and role_name not in policy.allowed_management_read_roles
        ):
            reasons.append("data_plane_role_outside_proof_store")
            continue
        if role_name not in policy.allowed_management_read_roles:
            reasons.append("unapproved_role_outside_proof_store")
    return tuple(sorted(set(reasons)))


def _scope_is_exact(scope: str, allowed: tuple[str, ...]) -> bool:
    normalized = scope.rstrip("/")
    return bool(normalized) and normalized in {item.rstrip("/") for item in allowed}


def _has_data_plane_access(assignment: VerifierRoleAssignment) -> bool:
    role = assignment.role_name.casefold()
    return bool(assignment.data_actions) or "data " in role or role.endswith(" data reader")


def _has_write_access(assignment: VerifierRoleAssignment) -> bool:
    role = assignment.role_name.casefold()
    if any(token in role for token in ("owner", "contributor", "administrator", "officer")):
        return True
    for action in (*assignment.actions, *assignment.data_actions):
        lowered = action.casefold()
        if lowered in {
            "microsoft.keyvault/vaults/secrets/getsecret/action",
            "microsoft.operationalinsights/workspaces/search/action",
        }:
            continue
        if lowered == "*" or lowered.endswith("/write") or lowered.endswith("/delete"):
            return True
        if lowered.endswith("/action") and "/read" not in lowered:
            return True
    return False


__all__ = [
    "OwnRolePolicy",
    "VerifierOwnRoleReadback",
    "VerifierOwnRoleReadbackError",
    "VerifierRoleAssignment",
    "evaluate_verifier_own_roles",
]
