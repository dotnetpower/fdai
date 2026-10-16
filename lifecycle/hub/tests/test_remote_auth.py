from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from fdai_lifecycle_hub.remote_auth import RemoteAuth, secure_app

TENANT = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def auth() -> RemoteAuth:
    return RemoteAuth(
        profile="remote-development",
        tenant_id=TENANT,
        audience="hub-api",
        origin="https://hub.example.com",
        spa_client_id="operator-browser",
        operator_scope="Hub.Access",
        operator_ids=frozenset({"approved-human"}),
        service_object_id="customer-service",
        service_client_id="customer-client",
    )


@pytest.fixture
def protected(auth):
    async def ok(request):
        return JSONResponse({"actor": request.state.operator})

    app = secure_app(
        Starlette(
            routes=[
                Route("/v1/catalog/export", ok),
                Route("/v1/catalog", ok),
                Route("/v1/releases/change", ok, methods=["POST"]),
            ]
        ),
        auth,
        vendor=True,
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    public["kid"] = "test-only"
    app.state.entra_verifier._keys = {"test-only": jwt.PyJWK.from_dict(public)}
    app.state.entra_verifier._refresh_after = time.monotonic() + 600

    def token(**changes):
        now = datetime.now(UTC)
        claims = {
            "iss": auth.issuer,
            "aud": auth.audience,
            "tid": TENANT,
            "ver": "2.0",
            "oid": "approved-human",
            "sub": "subject",
            "azp": "operator-browser",
            "scp": "Hub.Access",
            "iat": now,
            "nbf": now - timedelta(seconds=1),
            "exp": now + timedelta(minutes=5),
        }
        claims.update(changes)
        for name in [name for name, value in claims.items() if value is None]:
            del claims[name]
        return {
            "Authorization": "Bearer "
            + jwt.encode(
                claims,
                key,
                algorithm="RS256",
                headers={"kid": "test-only"},
            )
        }

    return app, token


def test_direct_jwt_not_aca_headers_and_exact_operator(protected):
    app, token = protected
    with TestClient(app, base_url="https://hub.example.com") as client:
        assert (
            client.get("/v1/catalog", headers={"X-MS-CLIENT-PRINCIPAL": "forged"}).status_code
            == 401
        )
        assert client.get("/v1/catalog", headers=token()).json() == {"actor": "approved-human"}
        assert client.get("/v1/catalog", headers=token(oid="other-human")).status_code == 403
        assert client.get("/v1/catalog", headers=token(azp="other-browser")).status_code == 403
        assert client.get("/v1/catalog", headers=token(scp="unrelated")).status_code == 403
        assert client.get("/v1/catalog", headers=token(aud="customer-api")).status_code == 401
        assert (
            client.get("/v1/catalog", headers=token(iss="https://other.example.com")).status_code
            == 401
        )
        assert client.get("/v1/catalog", headers=token(exp=0)).status_code == 401
        assert (
            client.get(
                "/v1/catalog", headers=token(nbf=datetime.now(UTC) + timedelta(hours=1))
            ).status_code
            == 401
        )
        assert client.get("/v1/catalog", headers=token(tid="other-tenant")).status_code == 401
        assert client.get("/v1/catalog", headers=token(oid=None)).status_code == 401
        assert (
            client.get(
                "/v1/catalog", headers={**token(), "Host": "untrusted.example.com"}
            ).status_code
            == 400
        )


def test_service_identity_is_read_export_only(protected):
    app, token = protected
    service = dict(
        oid="customer-service",
        azp="customer-client",
        idtyp="app",
        scp=None,
        roles=["Catalog.Read"],
    )
    with TestClient(app, base_url="https://hub.example.com") as client:
        assert client.get("/v1/catalog/export", headers=token(**service)).status_code == 200
        assert client.get("/v1/catalog", headers=token(**service)).status_code == 403
        assert (
            client.post("/v1/releases/change", headers=token(**service), json={}).status_code == 403
        )
        for changes in (
            {"oid": "vendor-service"},
            {"azp": "vendor-client"},
            {"roles": []},
            {"idtyp": None},
        ):
            assert (
                client.get("/v1/catalog/export", headers=token(**(service | changes))).status_code
                == 403
            )


def test_cross_origin_mutation_and_wrong_signature_are_denied(protected):
    app, token = protected
    with TestClient(app, base_url="https://hub.example.com") as client:
        assert client.post("/v1/releases/change", headers=token(), json={}).status_code == 200
        assert (
            client.post(
                "/v1/releases/change",
                headers={
                    **token(),
                    "Origin": "https://other.example.com",
                },
                json={},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/v1/releases/change",
                headers={
                    **token(),
                    "Origin": "https://hub.example.com",
                    "Sec-Fetch-Site": "cross-site",
                },
                json={},
            ).status_code
            == 403
        )
        forged = jwt.encode({"aud": "hub-api"}, "test-only-not-an-entra-key", algorithm="HS256")
        assert (
            client.get("/v1/catalog", headers={"Authorization": f"Bearer {forged}"}).status_code
            == 401
        )


def test_target_real_api_denies_agent_transport_and_binds_approval_actor(
    protected,
    auth,
    store,
    enrollment,
    now,
):
    from fdai_lifecycle_hub.api import create_app
    from fdai_lifecycle_hub.signing import verify_key_proof

    vendor, token = protected
    config = auth.model_copy(
        update={
            "service_object_id": None,
            "service_client_id": None,
            "audience": "customer-api",
        }
    )
    app = create_app(store, remote_auth=config, clock=lambda: now)
    app.state.entra_verifier._keys = vendor.state.entra_verifier._keys
    app.state.entra_verifier._refresh_after = time.monotonic() + 600
    store.request_enrollment(enrollment, verify=verify_key_proof, now=now)
    installation_id = enrollment.installation.installation_id
    with TestClient(app, base_url="https://hub.example.com") as client:
        headers = token(aud="customer-api")
        assert client.get("/v1/installations", headers=token()).status_code == 401
        assert client.get("/v1/installations").status_code == 401
        for path in ("state", "enrollment", "plans/unknown/reports"):
            assert (
                client.post(
                    f"/v1/installations/{installation_id}/{path}", json={}, headers=headers
                ).status_code
                == 403
            )
        assert (
            client.get(
                f"/v1/installations/{installation_id}/plan",
                headers=headers,
            ).status_code
            == 403
        )
        response = client.post(
            f"/v1/installations/{installation_id}/enrollment/approve",
            headers=headers,
            json={
                "approver": "forged-actor",
                "installation_key_id": enrollment.installation_key_id,
            },
        )
        assert response.status_code == 200
    from sqlalchemy import select

    from fdai_lifecycle_hub.models import AuditRecord

    with store.engine.connect() as connection:
        events = connection.scalars(select(AuditRecord.payload)).all()
    assert any("approved-human" in json.dumps(event) for event in events)
    assert all("forged-actor" not in json.dumps(event) for event in events)


def test_remote_readiness_rechecks_schema_and_default_business_routes_remain_protected(
    monkeypatch,
    tmp_path,
    auth,
    key,
    now,
):
    import sys

    import uvicorn
    from sqlalchemy import create_engine

    from fdai_lifecycle_hub import remote
    from fdai_release_hub.store import ReleaseStore

    engine = create_engine(f"sqlite:///{tmp_path / 'readiness.db'}")
    ReleaseStore(engine, key, clock=lambda: now).migrate()
    monkeypatch.setattr(remote, "remote_engine", lambda _: engine)
    monkeypatch.setattr(remote, "remote_key", lambda _: key)
    monkeypatch.setenv(
        "FDAI_HUB_REMOTE_CONFIG",
        json.dumps({"kind": "release", "auth": auth.model_dump(mode="json")}),
    )
    captured = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.append(app))
    monkeypatch.setattr(sys, "argv", ["fdai-hub-remote", "serve"])
    remote.main()
    with TestClient(captured[0], base_url="https://hub.example.com") as client:
        assert client.get("/readyz").json() == {"status": "ready"}
        assert client.get("/healthz").status_code == 200
        assert client.get("/v1/catalog").status_code == 401
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE release_hub_schema_revision")
        assert client.get("/readyz").status_code == 503
        assert client.get("/healthz").status_code == 200
