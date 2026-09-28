"""Deployment-selected full-authority development profile composition.

The profile, the distinct executor principal, and the trusted binding source are injected only
when deployment configuration selects them, and the ControlLoop and the Pantheon share one
registry. Without ``FDAI_FULL_AUTHORITY_DEVELOPMENT_PROFILE_JSON`` the multi-operator rule stays
in force. A malformed, not-yet-valid, or expired profile, or an
executor principal that differs from the profile, fails startup closed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fdai.agents import DevelopmentRuntimeBindings
from fdai.delivery.development_bindings import PreparedDevelopmentBindingRegistry
from fdai.shared.contracts.development_authority import normalized_principal
from fdai.shared.contracts.models import FullAuthorityDevelopmentProfile
from fdai.shared.providers.state_store import StateStore

if TYPE_CHECKING:
    from fdai.core.control_loop import ControlLoop

PROFILE_ENV = "FDAI_FULL_AUTHORITY_DEVELOPMENT_PROFILE_JSON"
EXECUTOR_ENV = "FDAI_FULL_AUTHORITY_DEVELOPMENT_EXECUTOR_PRINCIPAL"


def load_development_profile(
    environment: Mapping[str, str],
    *,
    now: datetime,
) -> FullAuthorityDevelopmentProfile | None:
    """Return the selected current profile, ``None`` when unselected, or fail closed."""
    raw = environment.get(PROFILE_ENV, "").strip()
    if not raw:
        return None
    try:
        profile = FullAuthorityDevelopmentProfile.model_validate_json(raw)
    except ValueError:
        raise RuntimeError("full-authority development profile is malformed") from None
    if not profile.valid_from <= now < profile.valid_until:
        raise RuntimeError("full-authority development profile is not current")
    return profile


def development_control_loop_kwargs(
    environment: Mapping[str, str],
    *,
    store: StateStore | None,
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
) -> dict[str, Any]:
    """Return ControlLoop development keywords, or none when no profile is selected."""
    profile = load_development_profile(environment, now=clock())
    if profile is None:
        return {}
    executor = environment.get(EXECUTOR_ENV, "").strip()
    if not executor or normalized_principal(executor) != normalized_principal(
        profile.executor_principal
    ):
        raise RuntimeError("development executor principal does not match the selected profile")
    if store is None:
        raise RuntimeError("development profile requires a durable state store")
    return {
        "development_profile": profile,
        "development_binding_source": PreparedDevelopmentBindingRegistry(
            profile=profile, store=store, clock=clock
        ),
        "development_executor_principal": executor,
    }


def pantheon_development_bindings(
    control_loop: ControlLoop,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
) -> DevelopmentRuntimeBindings | None:
    """Share the ControlLoop's selected profile and trusted source with the Pantheon."""
    # A control-loop double without development support selects the multi-operator rule.
    parts = getattr(control_loop, "development_authority_parts", None)
    if parts is None:
        return None
    profile, source, executor = parts
    owner = normalized_principal(profile.owner_principal)

    def owner_authorizer(principal: str) -> bool:
        current = profile.valid_from <= clock() < profile.valid_until
        return current and normalized_principal(principal) == owner

    return DevelopmentRuntimeBindings(
        profile=profile,
        executor_principal=executor,
        owner_authorizer=owner_authorizer,
        binding_source=source,
    )


__all__ = [
    "EXECUTOR_ENV",
    "PROFILE_ENV",
    "development_control_loop_kwargs",
    "load_development_profile",
    "pantheon_development_bindings",
]
