"""Tests for :mod:`fdai.delivery.read_api.main`.

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
import logging
import os
from collections.abc import Iterator
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient

from fdai.core.rbac.enforcer import RoleEnforcer
from fdai.core.rbac.resolver import GroupMapping, Principal, RoleResolver
from fdai.core.rbac.roles import Role
from fdai.delivery.read_api.auth import (
    AuthenticationError,
    Authenticator,
    build_authenticator,
)
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import (
    HilQueueItem,
    InMemoryConsoleReadModel,
)
from fdai.delivery.read_api.routes.auxiliary_registration import registered_cors_methods
from fdai.delivery.read_api.routes.panels import ExampleFinOpsPanel

_DEV_MODE_ENV = "FDAI_READ_API_DEV_MODE"
_LOCAL_AZURE_CLI_ENV = "FDAI_READ_API_LOCAL_AZURE_CLI"


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
        from fdai.delivery.read_api.auth import UnsafeClaimsExtractor

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

    def test_local_cli_mode_requires_explicit_env(self, no_dev_env: None) -> None:
        del no_dev_env
        resolver = RoleResolver(group_mapping=_mapping())
        auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=resolver)
        with pytest.raises(ValueError, match=_LOCAL_AZURE_CLI_ENV):
            build_app(
                authenticator=auth,
                read_model=InMemoryConsoleReadModel(),
                config=ReadApiConfig(
                    local_cli_principal=Principal(
                        oid="cli-user",
                        roles=frozenset({Role.CONTRIBUTOR}),
                    ),
                    local_cli_profile={"oid": "cli-user", "username": "user@example.com"},
                ),
            )

    def test_local_cli_mode_serves_profile_and_authorizes_without_bearer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_LOCAL_AZURE_CLI_ENV, "1")
        resolver = RoleResolver(group_mapping=_mapping())
        auth = build_authenticator(
            verifier=lambda _: (_ for _ in ()).throw(AssertionError("verifier MUST NOT run")),
            resolver=resolver,
        )
        app = build_app(
            authenticator=auth,
            read_model=InMemoryConsoleReadModel(),
            config=ReadApiConfig(
                local_cli_principal=Principal(
                    oid="cli-user",
                    roles=frozenset({Role.CONTRIBUTOR}),
                ),
                local_cli_profile={
                    "oid": "cli-user",
                    "username": "user@example.com",
                    "roles": ["Contributor"],
                    "source": "azure-cli",
                },
            ),
        )
        client = TestClient(app)

        assert client.get("/audit").status_code == 200
        profile = client.get("/local-auth/me")
        assert profile.status_code == 200
        assert profile.json()["oid"] == "cli-user"
        assert profile.headers["cache-control"] == "no-store"

    def test_local_cli_mode_is_refused_in_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_LOCAL_AZURE_CLI_ENV, "1")
        monkeypatch.setenv("RUNTIME_ENV", "prod")
        resolver = RoleResolver(group_mapping=_mapping())
        auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=resolver)
        with pytest.raises(ValueError, match="prohibited"):
            build_app(
                authenticator=auth,
                read_model=InMemoryConsoleReadModel(),
                config=ReadApiConfig(
                    local_cli_principal=Principal(oid="cli-user"),
                    local_cli_profile={"oid": "cli-user"},
                ),
            )


# ---------------------------------------------------------------------------
# read-only invariant
# ---------------------------------------------------------------------------


class TestReadOnlyInvariant:
    """The console API MUST NOT expose a mutating verb on any route."""

    @pytest.mark.parametrize("path", ["/audit", "/kpi", "/hil-queue", "/incidents", "/rca"])
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
        assert registered == [
            "/audit",
            "/audit/{correlation_id}/trace",
            "/healthz",
            "/hil-queue",
            "/incidents",
            "/kpi",
            "/rca",
            "/system/data-sources",
        ]


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

    def test_filters_before_limit_and_validates_window(self, dev_env: None) -> None:
        del dev_env
        app, model = _build_stack(dev_mode=True)
        model.record_audit_entry(
            {
                "event_id": "target",
                "action_kind": "risk_gate.shadow_authority",
                "mode": "shadow",
                "tier": "t2",
                "outcome": "hil",
                "vertical": "change_safety",
            }
        )
        for index in range(30):
            model.record_audit_entry(
                {"event_id": f"other-{index}", "action_kind": "other", "mode": "shadow"}
            )
        client = TestClient(app)
        response = client.get(
            "/audit?limit=25&tier=t2&outcome=hil&vertical=change-safety&window=30d"
        )
        assert response.status_code == 200
        assert [item["event_id"] for item in response.json()["items"]] == ["target"]
        assert client.get("/audit?window=0d").status_code == 400
        assert client.get("/audit?tier=t9").status_code == 400

    def test_sequence_range_is_inclusive_and_validated(self, dev_env: None) -> None:
        del dev_env
        app, model = _build_stack(dev_mode=True)
        for index in range(4):
            model.record_audit_entry({"event_id": f"event-{index}", "mode": "shadow", "tier": "T0"})
        client = TestClient(app)

        response = client.get("/audit?from_seq=2&through_seq=3&tier=t0")

        assert response.status_code == 200
        assert [item["seq"] for item in response.json()["items"]] == [3, 2]
        assert client.get("/audit?from_seq=0").status_code == 400
        assert client.get("/audit?through_seq=not-a-number").status_code == 400
        assert client.get("/audit?from_seq=4&through_seq=3").status_code == 400
        assert client.get("/audit?from_seq=9223372036854775808").status_code == 400


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
        assert response.json() == {"items": [], "total": 0, "detail_level": "full"}

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

    def test_reader_sees_count_without_sensitive_item_detail(self, no_dev_env: None) -> None:
        del no_dev_env
        app, model = _build_stack(dev_mode=False)
        model.record_hil_pending(
            HilQueueItem(
                idempotency_key="k-reader",
                event_id="e-reader",
                action_kind="compute.restart",
                reason="policy requires review",
                requested_at="2026-07-15T00:00:00+00:00",
                target_resource_ref="resource-sensitive",
            )
        )
        client = TestClient(app)
        response = client.get(
            "/hil-queue",
            headers={"authorization": f"Bearer {_reader_token()}"},
        )
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 1, "detail_level": "count_only"}

    def test_approver_sees_full_item_detail(self, no_dev_env: None) -> None:
        del no_dev_env
        app, model = _build_stack(dev_mode=False)
        model.record_hil_pending(
            HilQueueItem(
                idempotency_key="k-approver",
                event_id="e-approver",
                action_kind="compute.restart",
                reason="policy requires review",
                requested_at="2026-07-15T00:00:00+00:00",
                target_resource_ref="resource-visible-to-approver",
            )
        )
        client = TestClient(app)
        token = _forge_token({"oid": "approver", "roles": ["Approver"]})
        response = client.get(
            "/hil-queue",
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["detail_level"] == "full"
        assert response.json()["items"][0]["target_resource_ref"] == "resource-visible-to-approver"


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

    def test_authentication_failure_is_logged_without_credentials(
        self,
        no_dev_env: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        del no_dev_env
        app, _ = _build_stack(dev_mode=False)
        caplog.set_level(logging.WARNING, logger="fdai.delivery.read_api.app.factory")

        response = TestClient(app).get(
            "/audit",
            headers={"authorization": "Bearer highly-sensitive-token"},
        )

        assert response.status_code == 401
        record = next(
            item for item in caplog.records if item.message == "read_api_authentication_failed"
        )
        assert record.path == "/audit"  # type: ignore[attr-defined]
        assert record.error_type == "AuthenticationError"  # type: ignore[attr-defined]
        assert "highly-sensitive-token" not in caplog.text

    def test_authorization_failure_is_logged_without_identity(
        self,
        no_dev_env: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        del no_dev_env
        app, _ = _build_stack(dev_mode=False)
        caplog.set_level(logging.WARNING, logger="fdai.delivery.read_api.app.factory")

        response = TestClient(app).get(
            "/audit",
            headers={"authorization": f"Bearer {_no_role_token()}"},
        )

        assert response.status_code == 403
        record = next(
            item for item in caplog.records if item.message == "read_api_authorization_failed"
        )
        assert record.path == "/audit"  # type: ignore[attr-defined]
        assert record.error_type == "RoleRequiredError"  # type: ignore[attr-defined]
        assert "user-noone" not in caplog.text

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

    def test_cors_preflight_allows_post_for_console_action(self, no_dev_env: None) -> None:
        del no_dev_env
        resolver = RoleResolver(group_mapping=_mapping())
        auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=resolver)
        app = build_app(
            authenticator=auth,
            read_model=InMemoryConsoleReadModel(),
            config=ReadApiConfig(
                cors_allow_origins=("https://console.example.com",),
                console_action=object(),
            ),
        )
        client = TestClient(app)

        response = client.options(
            "/chat/action",
            headers={
                "origin": "https://console.example.com",
                "access-control-request-method": "POST",
            },
        )

        assert response.status_code == 200
        assert "POST" in response.headers["access-control-allow-methods"]

    def test_cors_methods_follow_registered_routes(self, no_dev_env: None) -> None:
        del no_dev_env
        routes = [
            Route("/read", lambda request: Response(), methods=["GET"]),
            Route("/owned-record", lambda request: Response(), methods=["PUT", "DELETE"]),
        ]

        assert registered_cors_methods(routes) == ["DELETE", "GET", "PUT"]


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

    def test_no_extra_panels_keeps_only_builtin_surfaces(self, dev_env: None) -> None:
        del dev_env
        app, _ = _build_stack(dev_mode=True)
        registered = sorted(r.path for r in app.routes if hasattr(r, "path"))
        assert registered == [
            "/audit",
            "/audit/{correlation_id}/trace",
            "/healthz",
            "/hil-queue",
            "/incidents",
            "/kpi",
            "/rca",
            "/system/data-sources",
        ]

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
        from fdai.delivery.read_api.auth import UnsafeClaimsExtractor

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


class TestCapabilityCatalogPanel:
    """The capability catalog panel (SRE-agent slide 20)."""

    def test_capabilities_route_lists_metadata(self, dev_env: None) -> None:
        from fdai.delivery.read_api.routes.panels import CapabilityCatalogPanel

        app, _ = _build_with_panels(CapabilityCatalogPanel())
        client = TestClient(app)
        body = client.get("/capabilities").json()

        assert body["surface"] == "capabilities"
        assert body["source"] == "static-catalog"
        assert body["execution_eligibility"] is False
        assert body["count"] >= 1
        ids = {c["capability_id"] for c in body["capabilities"]}
        assert "investigation.run" in ids
        # Every mutating capability advertises shadow as its default mode.
        for cap in body["capabilities"]:
            if cap["side_effect_class"] in {"execute", "breakglass"}:
                assert cap["default_mode"] == "shadow"

    def test_capabilities_route_filters_by_category(self, dev_env: None) -> None:
        from fdai.delivery.read_api.routes.panels import CapabilityCatalogPanel

        app, _ = _build_with_panels(CapabilityCatalogPanel())
        client = TestClient(app)
        body = client.get("/capabilities?category=chaos").json()

        assert body["count"] >= 1
        assert all(c["category"] == "chaos" for c in body["capabilities"])


def _clear_env() -> None:
    os.environ.pop(_DEV_MODE_ENV, None)
