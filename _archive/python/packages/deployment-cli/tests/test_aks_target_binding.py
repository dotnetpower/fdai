"""The active-target binding is available before any AKS capacity read."""

from __future__ import annotations

import json

import pytest

from fdai_deployment_cli import aks_preflight
from fdai_deployment_cli.target import compute_target_binding

_SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
_TENANT = "00000000-0000-0000-0000-000000000002"


def _account(monkeypatch, **overrides: object) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []
    value = {
        "id": _SUBSCRIPTION,
        "tenantId": _TENANT,
        "state": "Enabled",
        "userType": "user",
    }
    value.update(overrides)

    def fake(arguments, deadline):
        calls.append(tuple(arguments))
        return json.loads(json.dumps(value))

    monkeypatch.setattr(aks_preflight, "_json", fake)
    return calls


def test_binding_matches_the_one_the_capacity_preflight_reports(monkeypatch) -> None:
    calls = _account(monkeypatch)

    binding = aks_preflight.current_target_binding()

    assert binding == compute_target_binding(subscription_id=_SUBSCRIPTION, tenant_id=_TENANT)
    # One read-only account lookup; no capacity, quota, or catalog call is made.
    assert [call[:2] for call in calls] == [("account", "show")]


@pytest.mark.parametrize(
    "override",
    [{"state": "Disabled"}, {"userType": "servicePrincipal"}, {"id": None}, {"tenantId": 3}],
)
def test_binding_refuses_an_unusable_target(monkeypatch, override: dict[str, object]) -> None:
    _account(monkeypatch, **override)
    with pytest.raises(ValueError):
        aks_preflight.current_target_binding()
