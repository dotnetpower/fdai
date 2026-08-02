"""Effective-scope projection and GET-only route tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient

from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.delivery.operator_api.auth import build_authenticator
from fdai.delivery.operator_api.main import OperatorApiConfig, build_app
from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.operator_api.routes.scope import (
    StaticScopeSource,
    build_scope_view,
    project_scope_axis,
)
from fdai.rule_catalog.schema.scope import ScopeBinding, ScopeRef

_ORG = "example-org"
_SUB = "00000000-0000-0000-0000-000000000001"


def _monitoring() -> ScopeBinding:
    return ScopeBinding(
        includes=(ScopeRef(segments=(_ORG, _SUB)),),
        excludes=(ScopeRef(segments=(_ORG, _SUB, "rg-sandbox")),),
    )


def _action() -> ScopeBinding:
    return ScopeBinding(
        includes=(ScopeRef(segments=(_ORG, _SUB, "rg-app")),),
        excludes=(),
    )


def test_project_scope_axis_decodes_subscription_and_rg_levels() -> None:
    axis = project_scope_axis("monitoring", _monitoring())
    assert axis.axis == "monitoring"
    included = [e for e in axis.entries if e.state == "included"]
    excluded = [e for e in axis.entries if e.state == "excluded"]
    assert included[0].level == "subscription"
    assert included[0].subscription == _SUB
    assert included[0].resource_group is None
    assert included[0].address == f"scope://{_ORG}/{_SUB}"
    assert excluded[0].level == "resource_group"
    assert excluded[0].resource_group == "rg-sandbox"


def test_project_scope_axis_rejects_out_of_granularity_address() -> None:
    org_only = ScopeBinding(includes=(ScopeRef(segments=(_ORG,)),))
    with pytest.raises(ValueError, match="subscription- or resource-group-level"):
        project_scope_axis("action", org_only)


def test_build_scope_view_composes_two_axes_and_executor_boundary() -> None:
    view = build_scope_view(
        monitoring=_monitoring(),
        action=_action(),
        executor_resource_groups=("rg-app",),
        executor_note="RG-scoped identity",
    )
    data = view.to_dict()
    assert data["monitoring"]["axis"] == "monitoring"
    assert data["action"]["axis"] == "action"
    assert data["executor_boundary"]["resource_groups"] == ["rg-app"]
    assert data["executor_boundary"]["note"] == "RG-scoped identity"


@pytest.fixture
def dev_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("FDAI_OPERATOR_API_DEV_MODE", "1")
    yield


def _client(*, with_scope: bool) -> TestClient:
    mapping = GroupMapping(
        reader_group_id="reader",
        contributor_group_id="contributor",
        approver_group_id="approver",
        owner_group_id="owner",
        break_glass_group_id="break-glass",
    )
    auth = build_authenticator(
        verifier=lambda _: {"oid": "unused"},
        resolver=RoleResolver(group_mapping=mapping),
    )
    scope_source = (
        StaticScopeSource(
            build_scope_view(
                monitoring=_monitoring(),
                action=_action(),
                executor_resource_groups=("rg-app",),
            )
        )
        if with_scope
        else None
    )
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=OperatorApiConfig(dev_mode=True, scope_source=scope_source),
    )
    return TestClient(app)


def test_scope_route_returns_view_and_is_get_only(dev_env: None) -> None:
    del dev_env
    client = _client(with_scope=True)
    response = client.get("/scope")
    assert response.status_code == 200
    body = response.json()
    assert body["monitoring"]["axis"] == "monitoring"
    assert body["action"]["axis"] == "action"
    assert body["executor_boundary"]["resource_groups"] == ["rg-app"]
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert client.request(method, "/scope").status_code == 405


def test_scope_route_absent_when_unwired(dev_env: None) -> None:
    del dev_env
    client = _client(with_scope=False)
    assert client.get("/scope").status_code == 404
