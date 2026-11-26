"""Deployment selection of the full-authority development profile fails closed."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fdai.delivery.azure.target_revision import AzureTargetRevisionReader
from fdai.delivery.development_bindings import PreparedDevelopmentBindingRegistry
from fdai.runtime.development_authority import (
    EXECUTOR_ENV,
    PROFILE_ENV,
    development_control_loop_kwargs,
    load_development_profile,
    pantheon_development_bindings,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.contracts.test_development_authority import NOW, _profile


def _environment(**overrides: str) -> dict[str, str]:
    profile = _profile()
    return {
        PROFILE_ENV: profile.model_dump_json(),
        EXECUTOR_ENV: profile.executor_principal,
        **overrides,
    }


def test_absent_profile_keeps_the_multi_operator_composition() -> None:
    assert load_development_profile({}, now=NOW) is None
    assert development_control_loop_kwargs({}, store=None, clock=lambda: NOW) == {}


@pytest.mark.parametrize(
    ("overrides", "clock_offset", "store"),
    [
        ({PROFILE_ENV: "{not json"}, timedelta(0), InMemoryStateStore()),
        ({}, timedelta(hours=2), InMemoryStateStore()),
        ({EXECUTOR_ENV: "identity:someone-else"}, timedelta(0), InMemoryStateStore()),
        ({EXECUTOR_ENV: ""}, timedelta(0), InMemoryStateStore()),
        ({}, timedelta(0), None),
    ],
)
def test_malformed_expired_or_mismatched_selection_fails_startup(
    overrides: dict[str, str], clock_offset: timedelta, store: InMemoryStateStore | None
) -> None:
    with pytest.raises(RuntimeError):
        development_control_loop_kwargs(
            _environment(**overrides), store=store, clock=lambda: NOW + clock_offset
        )


def test_selected_profile_shares_one_trusted_source_with_the_pantheon() -> None:
    kwargs = development_control_loop_kwargs(
        _environment(), store=InMemoryStateStore(), clock=lambda: NOW
    )
    profile = kwargs["development_profile"]
    source = kwargs["development_binding_source"]
    assert isinstance(source, PreparedDevelopmentBindingRegistry)
    control_loop = SimpleNamespace(
        development_authority_parts=(profile, source, kwargs["development_executor_principal"])
    )

    bindings = pantheon_development_bindings(control_loop, clock=lambda: NOW)  # type: ignore[arg-type]
    expired = pantheon_development_bindings(  # type: ignore[arg-type]
        control_loop, clock=lambda: NOW + timedelta(hours=2)
    )

    assert bindings is not None and expired is not None
    assert bindings.profile == profile and bindings.binding_source is source
    assert bindings.owner_authorizer(profile.owner_principal.upper()) is True
    assert bindings.owner_authorizer("human:someone-else") is False
    assert expired.owner_authorizer(profile.owner_principal) is False
    assert pantheon_development_bindings(SimpleNamespace(development_authority_parts=None)) is None  # type: ignore[arg-type]


def test_revision_reader_requires_a_workload_identity_and_http_client() -> None:
    without = development_control_loop_kwargs(
        _environment(), store=InMemoryStateStore(), clock=lambda: NOW
    )
    with_reader = development_control_loop_kwargs(
        _environment(),
        store=InMemoryStateStore(),
        identity=object(),  # type: ignore[arg-type]
        http_client=object(),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )

    assert without["development_revision_reader"] is None
    assert isinstance(with_reader["development_revision_reader"], AzureTargetRevisionReader)
