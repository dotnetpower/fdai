"""Composition-only injection for the full-authority development profile."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai.agents._framework.var_development_authority import (
    DevelopmentOwnerAuthorizer,
)
from fdai.agents.thor import Thor
from fdai.agents.var import ApproverAuthorizer, Var
from fdai.agents.vidar import RollbackExecutor, Vidar
from fdai.shared.contracts.development_authority import normalized_principal
from fdai.shared.contracts.models import (
    FullAuthorityDevelopmentProfile,
)
from fdai.shared.providers.development_authority import DevelopmentAuthorityBindingSource
from fdai.shared.providers.state_store import StateStore


@dataclass(frozen=True, slots=True)
class DevelopmentRuntimeBindings:
    """Exact deployment-owned profile and current identity readers."""

    profile: FullAuthorityDevelopmentProfile
    executor_principal: str
    owner_authorizer: DevelopmentOwnerAuthorizer
    binding_source: DevelopmentAuthorityBindingSource

    def __post_init__(self) -> None:
        if normalized_principal(self.executor_principal) != normalized_principal(
            self.profile.executor_principal
        ):
            raise ValueError("development executor does not match the selected profile")


def configure_authority_agents(
    agents: dict[str, Any],
    *,
    approver_authorizer: ApproverAuthorizer | None,
    var_state_store: StateStore | None,
    rollback_executors: Mapping[str, RollbackExecutor] | None,
    action_rollback_executors: Mapping[tuple[str, str], RollbackExecutor] | None,
    rollback_contracts_by_action_type: Mapping[str, str] | None,
    vidar_state_store: StateStore | None,
    development: DevelopmentRuntimeBindings | None,
) -> None:
    """Inject optional development evidence into existing Var and Vidar roles."""

    profile = development.profile if development is not None else None
    executor = development.executor_principal if development is not None else None
    owner_authorizer = development.owner_authorizer if development is not None else None
    if approver_authorizer is not None or var_state_store is not None or profile is not None:
        agents["Var"] = Var(
            approver_authorizer=approver_authorizer,
            state_store=var_state_store,
            development_profile=profile,
            development_executor_principal=executor,
            development_owner_authorizer=owner_authorizer,
            development_binding_source=(
                development.binding_source if development is not None else None
            ),
        )
    if (
        rollback_executors is not None
        or action_rollback_executors is not None
        or vidar_state_store is not None
        or profile is not None
    ):
        agents["Vidar"] = Vidar(
            executors=rollback_executors,
            action_executors=action_rollback_executors,
            state_store=vidar_state_store,
            rollback_contracts_by_action_type=rollback_contracts_by_action_type,
            development_profile=profile,
            development_executor_principal=executor,
            development_binding_source=(
                development.binding_source if development is not None else None
            ),
        )


def bind_thor_development_authority(
    thor: Thor,
    development: DevelopmentRuntimeBindings | None,
) -> None:
    """Bind the same selected profile to Thor without changing its role."""

    thor.set_development_authority(
        development.profile if development is not None else None,
        executor_principal=(development.executor_principal if development is not None else None),
        binding_source=(development.binding_source if development is not None else None),
    )


def development_requires_enforce_bindings(
    development: DevelopmentRuntimeBindings | None,
) -> bool:
    return development is not None


__all__ = [
    "DevelopmentRuntimeBindings",
    "bind_thor_development_authority",
    "configure_authority_agents",
    "development_requires_enforce_bindings",
]
