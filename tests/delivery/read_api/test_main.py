"""Tests for :mod:`aiopspilot.delivery.read_api.main`.

Exercises the Starlette app through :class:`starlette.testclient.TestClient`.
No live network; no live Postgres. The in-memory fake
:class:`InMemoryConsoleReadModel` drives every route.

Coverage focus:

- Every route is GET-only (POST/PUT/DELETE return 405).
- Read-only invariant: no mutating side effect leaks through a GET.
- 401 on missing / bad token, 403 on insufficient role.
- Dev-mode bypass works only when both the config flag AND the env var
  are set.
- Query-string typos yield 400, not 500.
- Response shapes match :meth:`AuditItem.to_dict` etc.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Iterator
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from aiopspilot.core.rbac.enforcer import RoleEnforcer
from aiopspilot.core.rbac.resolver import GroupMapping, RoleResolver
from aiopspilot.delivery.read_api.auth import (
    AuthenticationError,
    Authenticator,
    build_authenticator,
)
from aiopspilot.delivery.read_api.main import ReadApiConfig, build_app
from aiopspilot.delivery.read_api.panels import ExampleFinOpsPanel
from aiopspilot.delivery.read_api.read_model import (
    HilQueueItem,
    InMemoryConsoleReadModel,
)

_DEV_MODE_ENV = "AIOPSPILOT_READ_API_DEV_MODE"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _mapping() -> GroupMapping:
    return GroupMapping(
        reader_group_id="reader-group",
        contributor_group_id="contributor-group",
        approver_group_id="approver-group",
        owner_group_id="owner-group",
        break_glass_group_id="break-glass-group",
    )


def _forge_token(claims: dict[str, Any]) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"RS256","typ":"JWT"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8")).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(b"sig").rstrip(b"=").decode()
    return f"{header}.{payload}.{sig}"


def _reader_token() -> str:
    return _forge_token({"oid": "user-reader", "roles": ["Reader"]})


def _no_role_token() -> str:
    return _forge_token({"oid": "user-noone", "roles": []})


def _bad_token() -> str:
    return "notajwt"


def _build_stack(
    *,
    dev_mode: bool = False,
    extra_panels: tuple[Any, ...] = (),
) -> tuple[Starlette, InMemoryConsoleReadModel]:
    resolver = RoleResolver(group_mapping=_mapping())
    verifier: Any
    if dev_mode:
        # In dev mode the verifier is never called; supply a fail-fast one so
        # the test proves it.
        def verifier(_: str) -> dict[str, Any]:
            raise AssertionError("verifier MUST NOT run in dev mode")
    else:
        # Prod-shape verifier fake: decodes forged claims (already used in
        # test_auth.py); real fork wires JWKS-backed verification.
        from aiopspilot.delivery.read_api.auth import UnsafeClaimsExtractor

        verifier = UnsafeClaimsExtractor()
    authenticator = build_authenticator(verifier=verifier, resolver=resolver)
    read_model = InMemoryConsoleReadModel()
    config = ReadApiConfig(dev_mode=dev_mode, extra_panels=extra_panels)
    app = build_app(authenticator=authenticator, read_model=read_model, config=config)
    return app, read_model


@pytest.fixture
def dev_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(_DEV_MODE_ENV, "1")
    yield


@pytest.fixture
def no_dev_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(_DEV_MODE_ENV, raising=False)
    yield


# ---------------------------------------------------------------------------
# build_app / config
# ---------------------------------------------------------------------------


class TestBuildApp:
    def test_dev_mode_without_env_var_refuses(self, no_dev_env: None) -> None:
        # Even if the code sets dev_mode=True, the env var gate MUST stop the
        # boot to avoid an accidental production build with dev auth.
        del no_dev_env
        resolver = RoleResolver(group_mapping=_mapping())
        auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=resolver)
        with pytest.raises(ValueError, match=_DEV_MODE_ENV):
            build_app(
                authenticator=auth,
                read_model=InMemoryConsoleReadModel(),
                config=ReadApiConfig(dev_mode=True),
            )

    def test_default_config_is_secure(self, no_dev_env: None) -> None:
        del no_dev_env
        resolver = RoleResolver(group_mapping=_mapping())
        auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=resolver)
        app = build_app(authenticator=auth, read_model=InMemoryConsoleReadModel())
        client = TestClient(app)
        # No Authorization header → 401
        response = client.get("/audit")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# read-only invariant
# ---------------------------------------------------------------------------


class TestReadOnlyInvariant:
    """The console API MUST NOT expose a mutating verb on any route."""

    @pytest.mark.parametrize("path", ["/audit", "/kpi", "/hil-queue"])
    @pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
    def test_mutating_verbs_return_405(self, dev_env: None, path: str, method: str) -> None:
        del dev_env
        app, _ = _build_stack(dev_mode=True)
        client = TestClient(app)
        response = client.request(method, path)
        assert response.status_code == 405, (
            f"{method} {path} must be 405 to preserve the read-only invariant"
        )

    def test_only_expected_routes_registered(self, dev_env: None) -> None:
        del dev_env
        app, _ = _build_stack(dev_mode=True)
        registered = sorted(r.path for r in app.routes if hasattr(r, "path"))
        assert registered == ["/audit", "/healthz", "/hil-queue", "/kpi"]


# ---------------------------------------------------------------------------
# GET /audit
# ---------------------------------------------------------------------------


class TestAuditRoute:
    def test_returns_empty_page(self, dev_env: None) -> None:
        del dev_env
        app, _ = _build_stack(dev_mode=True)
        client = TestClient(app)
        response = client.get("/audit")
        assert response.status_code == 200
        assert response.json() == {"items": [], "next_cursor": None}

    def test_returns_seeded_entries_newest_first(self, dev_env: None) -> None:
        del dev_env
        app, model = _build_stack(dev_mode=True)
        for i in range(3):
            model.record_audit_entry(
                {"event_id": f"e-{i}", "action_kind": f"k-{i}", "mode": "shadow"}
            )
        client = TestClient(app)
        response = client.get("/audit")
        body = response.json()
        assert response.status_code == 200
        assert len(body["items"]) == 3
        seqs = [row["seq"] for row in body["items"]]
        assert seqs == [3, 2, 1]

    def test_limit_and_cursor(self, dev_env: None) -> None:
        del dev_env
        app, model = _build_stack(dev_mode=True)
        for i in range(5):
            model.record_audit_entry(
                {"event_id": f"e-{i}", "action_kind": f"k-{i}", "mode": "shadow"}
            )
        client = TestClient(app)
        first = client.get("/audit?limit=2").json()
        assert [row["seq"] for row in first["items"]] == [5, 4]
        assert first["next_cursor"] == "4"

        second = client.get(f"/audit?limit=2&cursor={first['next_cursor']}").json()
        assert [row["seq"] for row in second["items"]] == [3, 2]

    def test_bad_limit_returns_400(self, dev_env: None) -> None:
        del dev_env
        app, _ = _build_stack(dev_mode=True)
        client = TestClient(app)
        response = client.get("/audit?limit=abc")
        assert response.status_code == 400
        assert "limit" in response.json()["error"]["message"]

    def test_bad_cursor_returns_400(self, dev_env: None) -> None:
        del dev_env
        app, model = _build_stack(dev_mode=True)
        model.record_audit_entry({"event_id": "e-0", "mode": "shadow"})
        client = TestClient(app)
        response = client.get("/audit?cursor=nan")
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# GET /kpi
# ---------------------------------------------------------------------------


class TestKpiRoute:
    def test_zero_state(self, dev_env: None) -> None:
        del dev_env
        app, _ = _build_stack(dev_mode=True)
        client = TestClient(app)
        response = client.get("/kpi")
        assert response.status_code == 200
        body = response.json()
        assert body["event_count"] == 0
        assert body["hil_pending"] == 0

    def test_populated(self, dev_env: None) -> None:
        del dev_env
        app, model = _build_stack(dev_mode=True)
        model.record_audit_entry({"event_id": "e", "action_kind": "a", "mode": "shadow"})
        model.record_audit_entry({"event_id": "e", "action_kind": "b", "mode": "enforce"})
        model.record_hil_pending(
            HilQueueItem(
                idempotency_key="k",
                event_id="e",
                action_kind="a",
                reason="r",
                requested_at="2026-07-06T00:00:00+00:00",
            )
        )
        client = TestClient(app)
        body = client.get("/kpi").json()
        assert body["event_count"] == 2
        assert body["shadow_share"] == 0.5
        assert body["enforce_share"] == 0.5
        assert body["hil_pending"] == 1
        assert body["by_action_kind"] == {"a": 1, "b": 1}


# ---------------------------------------------------------------------------
# GET /hil-queue
# ---------------------------------------------------------------------------


class TestHilQueueRoute:
    def test_empty(self, dev_env: None) -> None:
        del dev_env
        app, _ = _build_stack(dev_mode=True)
        client = TestClient(app)
        response = client.get("/hil-queue")
        assert response.status_code == 200
        assert response.json() == {"items": []}

    def test_lists_pending(self, dev_env: None) -> None:
        del dev_env
        app, model = _build_stack(dev_mode=True)
        model.record_hil_pending(
            HilQueueItem(
                idempotency_key="k-1",
                event_id="e-1",
                action_kind="ak",
                reason="policy-violation",
                requested_at="2026-07-06T00:00:00+00:00",
                correlation_id="corr-1",
            )
        )
        client = TestClient(app)
        body = client.get("/hil-queue").json()
        assert len(body["items"]) == 1
        assert body["items"][0]["idempotency_key"] == "k-1"
        assert body["items"][0]["correlation_id"] == "corr-1"

    def test_bad_limit_returns_400(self, dev_env: None) -> None:
        del dev_env
        app, _ = _build_stack(dev_mode=True)
        client = TestClient(app)
        response = client.get("/hil-queue?limit=nope")
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Auth surface
# ---------------------------------------------------------------------------


class TestAuthenticationGate:
    def test_missing_bearer_returns_401(self, no_dev_env: None) -> None:
        del no_dev_env
        app, _ = _build_stack(dev_mode=False)
        client = TestClient(app)
        response = client.get("/audit")
        assert response.status_code == 401
        assert response.json()["error"]["status"] == 401

    def test_malformed_bearer_returns_401(self, no_dev_env: None) -> None:
        del no_dev_env
        app, _ = _build_stack(dev_mode=False)
        client = TestClient(app)
        response = client.get("/audit", headers={"authorization": f"Bearer {_bad_token()}"})
        assert response.status_code == 401

    def test_reader_can_read_audit(self, no_dev_env: None) -> None:
        del no_dev_env
        app, _ = _build_stack(dev_mode=False)
        client = TestClient(app)
        response = client.get("/audit", headers={"authorization": f"Bearer {_reader_token()}"})
        assert response.status_code == 200

    def test_user_without_role_gets_403(self, no_dev_env: None) -> None:
        del no_dev_env
        app, _ = _build_stack(dev_mode=False)
        client = TestClient(app)
        response = client.get("/audit", headers={"authorization": f"Bearer {_no_role_token()}"})
        assert response.status_code == 403

    def test_contributor_can_read(self, no_dev_env: None) -> None:
        del no_dev_env
        app, _ = _build_stack(dev_mode=False)
        client = TestClient(app)
        token = _forge_token({"oid": "u", "roles": ["Contributor"]})
        response = client.get("/audit", headers={"authorization": f"Bearer {token}"})
        assert response.status_code == 200

    def test_owner_can_read(self, no_dev_env: None) -> None:
        del no_dev_env
        app, _ = _build_stack(dev_mode=False)
        client = TestClient(app)
        token = _forge_token({"oid": "u", "roles": ["Owner"]})
        response = client.get("/kpi", headers={"authorization": f"Bearer {token}"})
        assert response.status_code == 200

    def test_verifier_error_wrapped_to_401(self, no_dev_env: None) -> None:
        del no_dev_env
        resolver = RoleResolver(group_mapping=_mapping())

        def verifier(_: str) -> dict[str, Any]:
            raise AuthenticationError("expired")

        authenticator = Authenticator(
            verifier=verifier,
            resolver=resolver,
            enforcer=RoleEnforcer(),
        )
        app = build_app(
            authenticator=authenticator,
            read_model=InMemoryConsoleReadModel(),
            config=ReadApiConfig(dev_mode=False),
        )
        client = TestClient(app)
        response = client.get("/audit", headers={"authorization": "Bearer whatever"})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Dev mode
# ---------------------------------------------------------------------------


class TestDevMode:
    def test_dev_mode_allows_anonymous(self, dev_env: None) -> None:
        del dev_env
        app, _ = _build_stack(dev_mode=True)
        client = TestClient(app)
        response = client.get("/audit")
        assert response.status_code == 200

    def test_healthz_is_public(self, no_dev_env: None) -> None:
        del no_dev_env
        app, _ = _build_stack(dev_mode=False)
        client = TestClient(app)
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


class TestCors:
    def test_cors_disabled_by_default(self, no_dev_env: None) -> None:
        del no_dev_env
        app, _ = _build_stack(dev_mode=False)
        client = TestClient(app)
        # Preflight should not get CORS headers when unconfigured.
        response = client.options(
            "/audit",
            headers={
                "origin": "https://console.example.com",
                "access-control-request-method": "GET",
            },
        )
        # Starlette returns 405 for OPTIONS on a GET-only route when no CORS
        # middleware is registered - the key assertion is "no allow-origin".
        assert "access-control-allow-origin" not in response.headers

    def test_cors_configured_allows_console_origin(self, no_dev_env: None) -> None:
        del no_dev_env
        resolver = RoleResolver(group_mapping=_mapping())
        auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=resolver)
        app = build_app(
            authenticator=auth,
            read_model=InMemoryConsoleReadModel(),
            config=ReadApiConfig(
                cors_allow_origins=("https://console.example.com",),
            ),
        )
        client = TestClient(app)
        response = client.options(
            "/audit",
            headers={
                "origin": "https://console.example.com",
                "access-control-request-method": "GET",
            },
        )
        # Preflight OK
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "https://console.example.com"

    def test_cors_preflight_denies_post(self, no_dev_env: None) -> None:
        del no_dev_env
        resolver = RoleResolver(group_mapping=_mapping())
        auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=resolver)
        app = build_app(
            authenticator=auth,
            read_model=InMemoryConsoleReadModel(),
            config=ReadApiConfig(
                cors_allow_origins=("https://console.example.com",),
            ),
        )
        client = TestClient(app)
        response = client.options(
            "/audit",
            headers={
                "origin": "https://console.example.com",
                "access-control-request-method": "POST",
            },
        )
        # POST is not in allow_methods, so preflight is denied.
        assert (
            response.status_code == 400
            or response.headers.get("access-control-allow-methods", "").lower() == "get"
        )


# ---------------------------------------------------------------------------
# Sanity: env var value edge cases
# ---------------------------------------------------------------------------


class TestDevModeEnvValidation:
    def test_env_set_to_other_value_still_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_DEV_MODE_ENV, "true")  # not "1" - refused
        resolver = RoleResolver(group_mapping=_mapping())
        auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=resolver)
        with pytest.raises(ValueError, match=_DEV_MODE_ENV):
            build_app(
                authenticator=auth,
                read_model=InMemoryConsoleReadModel(),
                config=ReadApiConfig(dev_mode=True),
            )

    def test_env_removed_after_build_still_works(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # dev_mode is bound at build time; removing the env after does not
        # revoke it. That is intentional - the env check is a boot-time
        # tripwire, not a per-request kill switch.
        monkeypatch.setenv(_DEV_MODE_ENV, "1")
        app, _ = _build_stack(dev_mode=True)
        monkeypatch.delenv(_DEV_MODE_ENV, raising=False)
        client = TestClient(app)
        response = client.get("/audit")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Fork-extensible read panels (ReadPanel seam)
# ---------------------------------------------------------------------------


class _FakePanel:
    """Minimal :class:`ReadPanel` used to drive path-validation tests.

    Unlike :class:`ExampleFinOpsPanel`, it does not validate its own path -
    that is the point: it lets the tests prove ``build_app`` fails fast on
    a malformed / colliding path.
    """

    def __init__(
        self,
        path: str,
        *,
        name: str = "fake",
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._path = path
        self._name = name
        self._payload = payload or {"ok": True}

    @property
    def path(self) -> str:
        return self._path

    @property
    def name(self) -> str:
        return self._name

    async def render(self, *, params: dict[str, str]) -> dict[str, Any]:
        del params
        return self._payload


def _build_with_panels(
    *panels: Any, dev_mode: bool = True
) -> tuple[Starlette, InMemoryConsoleReadModel]:
    resolver = RoleResolver(group_mapping=_mapping())

    def verifier(_: str) -> dict[str, Any]:
        raise AssertionError("verifier MUST NOT run in these tests")

    authenticator = build_authenticator(verifier=verifier, resolver=resolver)
    read_model = InMemoryConsoleReadModel()
    config = ReadApiConfig(dev_mode=dev_mode, extra_panels=tuple(panels))
    app = build_app(authenticator=authenticator, read_model=read_model, config=config)
    return app, read_model


class TestExtensionPanels:
    """The ``ReadPanel`` seam: forks add read-only routes without editing core."""

    def test_no_panels_by_default_keeps_ui_minimal(self, dev_env: None) -> None:
        del dev_env
        app, _ = _build_stack(dev_mode=True)
        registered = sorted(r.path for r in app.routes if hasattr(r, "path"))
        assert registered == ["/audit", "/healthz", "/hil-queue", "/kpi"]

    def test_panel_registered_as_get_route(self, dev_env: None) -> None:
        del dev_env
        app, _ = _build_with_panels(_FakePanel("/finops", payload={"vertical": "finops"}))
        client = TestClient(app)
        response = client.get("/finops")
        assert response.status_code == 200
        assert response.json() == {"vertical": "finops"}

    @pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
    def test_panel_is_get_only(self, dev_env: None, method: str) -> None:
        del dev_env
        app, _ = _build_with_panels(_FakePanel("/finops"))
        client = TestClient(app)
        response = client.request(method, "/finops")
        assert response.status_code == 405, (
            f"{method} /finops must be 405 - panels are read-only too"
        )

    def test_panel_requires_reader_role(self, no_dev_env: None) -> None:
        del no_dev_env
        resolver = RoleResolver(group_mapping=_mapping())
        from aiopspilot.delivery.read_api.auth import UnsafeClaimsExtractor

        authenticator = build_authenticator(verifier=UnsafeClaimsExtractor(), resolver=resolver)
        app = build_app(
            authenticator=authenticator,
            read_model=InMemoryConsoleReadModel(),
            config=ReadApiConfig(dev_mode=False, extra_panels=(_FakePanel("/finops"),)),
        )
        client = TestClient(app)
        # No token -> 401; token without role -> 403.
        assert client.get("/finops").status_code == 401
        assert (
            client.get(
                "/finops", headers={"authorization": f"Bearer {_no_role_token()}"}
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/finops", headers={"authorization": f"Bearer {_reader_token()}"}
            ).status_code
            == 200
        )

    def test_panel_path_must_start_with_slash(self) -> None:
        with pytest.raises(ValueError, match="MUST start with"):
            _build_with_panels(_FakePanel("finops"), dev_mode=False)

    def test_panel_path_collision_with_core_rejected(self) -> None:
        with pytest.raises(ValueError, match="collides with a core route"):
            _build_with_panels(_FakePanel("/kpi"), dev_mode=False)

    def test_duplicate_panel_paths_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate panel path"):
            _build_with_panels(
                _FakePanel("/finops"), _FakePanel("/finops", name="other"), dev_mode=False
            )

    def test_example_finops_panel_derives_from_audit(self, dev_env: None) -> None:
        del dev_env
        read_model = InMemoryConsoleReadModel()
        read_model.record_audit_entry(
            {"event_id": "e1", "action_kind": "shutdown", "estimated_savings": 12.5},
            mode="enforce",
        )
        read_model.record_audit_entry(
            {"event_id": "e2", "action_kind": "right_size", "estimated_savings": 7.25},
            mode="enforce",
        )
        read_model.record_audit_entry(
            {"event_id": "e3", "action_kind": "shutdown"},
            mode="shadow",
        )
        # A non-FinOps action is ignored by the panel.
        read_model.record_audit_entry(
            {"event_id": "e4", "action_kind": "restart"},
            mode="shadow",
        )
        panel = ExampleFinOpsPanel(read_model)
        app = build_app(
            authenticator=build_authenticator(
                verifier=lambda _: {"oid": "u"},
                resolver=RoleResolver(group_mapping=_mapping()),
            ),
            read_model=read_model,
            config=ReadApiConfig(dev_mode=True, extra_panels=(panel,)),
        )
        client = TestClient(app)
        body = client.get("/finops").json()
        assert body["vertical"] == "finops"
        assert body["total_actions"] == 3
        assert body["by_kind"] == {"shutdown": 2, "right_size": 1}
        assert body["estimated_monthly_savings"] == 19.75

    def test_example_finops_panel_rejects_bad_path(self) -> None:
        with pytest.raises(ValueError, match="MUST start with"):
            ExampleFinOpsPanel(InMemoryConsoleReadModel(), path="finops")


def _clear_env() -> None:
    os.environ.pop(_DEV_MODE_ENV, None)
