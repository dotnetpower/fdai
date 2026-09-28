"""Deployment selection of the full-authority development profile fails closed."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fdai.core.control_loop.development_request import (
    CONFIRMATION_FIELD,
    development_authority_inputs,
)
from fdai.delivery.development_bindings import PreparedDevelopmentBindingRegistry
from fdai.runtime.development_authority import (
    EXECUTOR_ENV,
    PROFILE_ENV,
    development_control_loop_kwargs,
    load_development_profile,
    pantheon_development_bindings,
)
from fdai.shared.contracts.models import Event
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.contracts.test_development_authority import NOW, _binding, _confirmation, _profile
from tests.core.executor.test_direct_api_executor import _action as _direct_action
from tests.core.risk_gate.test_development_authority import _action as _action_type


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


def _event(payload: dict[str, Any]) -> Event:
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000011",
            "idempotency_key": "event-idem",
            "source": "operator",
            "event_type": "operator_request",
            "resource_ref": "resource:example/rg/vm1",
            "payload": payload,
            "detected_at": NOW.isoformat(),
            "ingested_at": NOW.isoformat(),
            "mode": "shadow",
        }
    )


def test_only_a_confirmed_request_takes_the_development_path() -> None:
    profile = _profile()
    source = object()
    action = _direct_action()
    common = {
        "profile": profile,
        "binding_source": source,
        "executor_principal": profile.executor_principal,
        "action": action,
        "action_type": _action_type(),
        "now": NOW,
    }
    confirmation = _confirmation(profile, _binding(profile))

    assert development_authority_inputs(event=_event({}), **common) == {}  # type: ignore[arg-type]
    assert (
        development_authority_inputs(
            event=_event({CONFIRMATION_FIELD: confirmation.model_dump(mode="json")}),
            **{**common, "profile": None},
        )
        == {}
    )  # type: ignore[arg-type]
    malformed = development_authority_inputs(
        event=_event({CONFIRMATION_FIELD: {"schema_version": "1.0.0"}}), **common
    )  # type: ignore[arg-type]
    assert malformed["development_confirmation"] is None
    admitted = development_authority_inputs(
        event=_event({CONFIRMATION_FIELD: confirmation.model_dump(mode="json")}), **common
    )  # type: ignore[arg-type]
    request = admitted["development_binding_request"]
    assert admitted["development_confirmation"] == confirmation
    assert admitted["development_binding_source"] is source
    assert (request.action_id, request.target_ref, request.requester_principal) == (
        str(action.action_id),
        action.target_resource_ref,
        profile.owner_principal,
    )
    assert request.rollback_contract == action.rollback_ref.kind.value
