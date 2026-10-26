from __future__ import annotations

import json
import time
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from urllib.parse import urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jwt.algorithms import RSAAlgorithm
from lifecycle.hub.tests.remote_auth_helpers import seed_entra_key_cache
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from fdai_lifecycle_hub.remote_auth import (
    MAX_JWKS_STALE_SECONDS,
    AgentPrincipal,
    DevelopmentRecoveryAuthorization,
    EntraVerifier,
    RemoteAuth,
    _strict_json,
    secure_app,
)


def test_development_recovery_authorization_is_exact_bounded_and_operator_owned():
    now = datetime.now(UTC)
    replacement = Ed25519PrivateKey.generate().public_key().public_bytes_raw().hex()
    recovery = DevelopmentRecoveryAuthorization(
        profile="full-authority-development",
        installation_id="installation-dev",
        scope="rg-fdai-dev",
        operator_id="approved-human",
        previous_identity_key_id="installation-0123456789abcdef",
        replacement_identity_public_key=replacement,
        authorized_at=now,
        authorization_expires_at=now + timedelta(days=14),
        allow_single_owner_configuration_approval=True,
        reason="Recover one exact development installation.",
    )
    configured = RemoteAuth(
        profile="remote-development",
        tenant_id="00000000-0000-0000-0000-000000000000",
        audience="hub-api",
        origin="https://hub.example.com",
        spa_client_id="browser",
        operator_scope="Hub.Access",
        operator_ids=frozenset({"approved-human"}),
        development_recovery=recovery,
    )

    assert configured.development_recovery is recovery
    assert recovery.is_current(
        installation_id="installation-dev", operator_id="approved-human", now=now
    )
    assert not recovery.is_current(installation_id="other", operator_id="approved-human", now=now)
    with pytest.raises(ValueError, match="invalid"):
        recovery.model_copy(
            update={"authorization_expires_at": now + timedelta(days=14, seconds=1)}
        ).validate_recovery()
    with pytest.raises(ValueError, match="operator"):
        configured.model_copy(
            update={"development_recovery": recovery.model_copy(update={"operator_id": "other"})}
        ).validate_boundary()
    with pytest.raises(ValueError, match="does not accept development recovery"):
        secure_app(Starlette(), configured, vendor=True)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"keys":[],"keys":[]}',
        b'{"keys":[],"value":NaN}',
        '{"keys":[]}'.encode("utf-16"),
    ],
)
def test_entra_signing_keys_require_strict_utf8_json(payload):
    with pytest.raises(ValueError, match="signing-key response is invalid"):
        _strict_json(payload)


def test_entra_signing_keys_reject_duplicate_key_ids(auth, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    public["kid"] = "duplicate"

    class Response:
        headers = {"content-encoding": "identity"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

        def iter_raw(self):
            yield json.dumps({"keys": [public, public]}).encode()

    monkeypatch.setattr("fdai_lifecycle_hub.remote_auth.httpx.stream", lambda *_a, **_k: Response())

    with pytest.raises(ValueError, match="duplicate key id"):
        EntraVerifier(auth)._refresh()


def test_entra_signing_key_trickle_observes_total_refresh_deadline(auth, monkeypatch):
    class Response:
        headers = {"content-encoding": "identity"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

        def iter_raw(self):
            yield b"{"
            yield b'"'

    clock = iter((100.0, 104.0, 105.0))
    monkeypatch.setattr("fdai_lifecycle_hub.remote_auth.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("fdai_lifecycle_hub.remote_auth.httpx.stream", lambda *_a, **_k: Response())

    with pytest.raises(ValueError, match="exceeded its bound"):
        EntraVerifier(auth)._refresh()


def test_entra_unknown_key_refreshes_once_inside_cache_window(auth, monkeypatch):
    old_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    new_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    old_public = json.loads(RSAAlgorithm.to_jwk(old_key.public_key()))
    new_public = json.loads(RSAAlgorithm.to_jwk(new_key.public_key()))
    old_public["kid"] = "old"
    new_public["kid"] = "new"
    verifier = EntraVerifier(auth)
    seed_entra_key_cache(
        verifier,
        {"old": jwt.PyJWK.from_dict(old_public, algorithm="RS256")},
        unknown_kid_refresh_after=0,
    )
    refreshes = 0

    def refresh():
        nonlocal refreshes
        refreshes += 1
        seed_entra_key_cache(
            verifier,
            {"new": jwt.PyJWK.from_dict(new_public, algorithm="RS256")},
        )

    monkeypatch.setattr(verifier, "_refresh", refresh)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": auth.issuer,
            "aud": auth.audience,
            "exp": now + timedelta(minutes=5),
            "iat": now,
            "nbf": now,
            "tid": auth.tenant_id,
            "oid": "approved-human",
            "sub": "approved-human",
            "azp": auth.spa_client_id,
            "ver": "2.0",
        },
        new_key,
        algorithm="RS256",
        headers={"kid": "new"},
    )

    assert verifier.verify(token)["oid"] == "approved-human"
    assert refreshes == 1


def test_concurrent_unknown_keys_single_flight_the_jwks_refresh(auth, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    public["kid"] = "new"
    verifier = EntraVerifier(auth)
    verifier._last_successful_refresh = time.monotonic()
    verifier._refresh_after = time.monotonic() + 600
    verifier._unknown_kid_refresh_after = 0
    started = Event()
    release = Event()
    barrier = Barrier(9)
    refreshes = 0

    def refresh():
        nonlocal refreshes
        refreshes += 1
        started.set()
        assert release.wait(timeout=2)
        seed_entra_key_cache(
            verifier,
            {"new": jwt.PyJWK.from_dict(public, algorithm="RS256")},
        )

    monkeypatch.setattr(verifier, "_refresh", refresh)
    token = _token(auth, key, kid="new")
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_verify_after, barrier, verifier, token) for _ in range(8)]
        barrier.wait(timeout=2)
        assert started.wait(timeout=2)
        release.set()
        claims = [future.result(timeout=2) for future in futures]

    assert {claim["oid"] for claim in claims} == {"approved-human"}
    assert refreshes == 1


def test_failed_jwks_refresh_retains_keys_and_starts_cooldown(auth, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    public["kid"] = "old"
    verifier = EntraVerifier(auth)
    seed_entra_key_cache(
        verifier,
        {"old": jwt.PyJWK.from_dict(public, algorithm="RS256")},
        refreshed_at=50.0,
        refresh_after=0,
        unknown_kid_refresh_after=0,
    )
    clock = [100.0]
    refreshes = 0

    def fail_refresh():
        nonlocal refreshes
        refreshes += 1
        raise ValueError("synthetic JWKS failure")

    monkeypatch.setattr("fdai_lifecycle_hub.remote_auth.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(verifier, "_refresh", fail_refresh)
    old_token = _token(auth, key, kid="old")
    unknown_token = _token(auth, key, kid="unknown")

    assert verifier.verify(old_token)["oid"] == "approved-human"
    with pytest.raises(ValueError, match="not trusted"):
        verifier.verify(unknown_token)
    assert refreshes == 1
    assert verifier._keys["old"].key is not None
    assert verifier._refresh_after == 130
    assert verifier._unknown_kid_refresh_after == 130

    clock[0] = 131
    assert verifier.verify(old_token)["oid"] == "approved-human"
    assert refreshes == 2


def test_failed_jwks_refresh_rejects_keys_after_stale_deadline(auth, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    public["kid"] = "old"
    verifier = EntraVerifier(auth)
    seed_entra_key_cache(
        verifier,
        {"old": jwt.PyJWK.from_dict(public, algorithm="RS256")},
        refreshed_at=100.0,
        refresh_after=0,
        unknown_kid_refresh_after=0,
    )
    clock = [100.0 + MAX_JWKS_STALE_SECONDS - 1]
    refreshes = 0

    def fail_refresh():
        nonlocal refreshes
        refreshes += 1
        raise ValueError("synthetic JWKS failure")

    monkeypatch.setattr("fdai_lifecycle_hub.remote_auth.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(verifier, "_refresh", fail_refresh)
    token = _token(auth, key, kid="old")

    assert verifier.verify(token)["oid"] == "approved-human"
    assert refreshes == 1

    clock[0] += 1
    with pytest.raises(ValueError, match="exceeded their stale lifetime"):
        verifier.verify(token)
    assert refreshes == 1


def test_concurrent_expired_keys_fail_closed_after_one_refresh(auth, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    public["kid"] = "old"
    verifier = EntraVerifier(auth)
    seed_entra_key_cache(
        verifier,
        {"old": jwt.PyJWK.from_dict(public, algorithm="RS256")},
        refreshed_at=100.0,
        refresh_after=0,
        unknown_kid_refresh_after=0,
    )
    clock = [100.0 + MAX_JWKS_STALE_SECONDS]
    started = Event()
    release = Event()
    barrier = Barrier(9)
    refreshes = 0

    def fail_refresh():
        nonlocal refreshes
        refreshes += 1
        started.set()
        assert release.wait(timeout=2)
        raise ValueError("synthetic JWKS failure")

    monkeypatch.setattr("fdai_lifecycle_hub.remote_auth.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(verifier, "_refresh", fail_refresh)
    token = _token(auth, key, kid="old")
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_verify_after, barrier, verifier, token) for _ in range(8)]
        barrier.wait(timeout=2)
        assert started.wait(timeout=2)
        release.set()
        errors = [future.exception(timeout=2) for future in futures]

    assert all(
        isinstance(error, ValueError) and "exceeded their stale lifetime" in str(error)
        for error in errors
    )
    assert refreshes == 1


def _verify_after(barrier: Barrier, verifier: EntraVerifier, token: str) -> dict[str, object]:
    barrier.wait(timeout=2)
    return verifier.verify(token)


def _token(auth: RemoteAuth, key, *, kid: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": auth.issuer,
            "aud": auth.audience,
            "exp": now + timedelta(minutes=5),
            "iat": now,
            "nbf": now,
            "tid": auth.tenant_id,
            "oid": "approved-human",
            "sub": "approved-human",
            "azp": auth.spa_client_id,
            "ver": "2.0",
        },
        key,
        algorithm="RS256",
        headers={"kid": kid},
    )


def test_agent_exact_identity_installation_role_and_methods(auth, protected):
    original, token = protected
    principal = AgentPrincipal(
        installation_id="installation-alpha", object_id="agent-object", client_id="agent-client"
    )
    config = RemoteAuth.model_validate_json(
        auth.model_copy(update={"agent_principals": (principal,)}).model_dump_json()
    )

    async def ok(request):
        assert not hasattr(request.state, "operator")
        return JSONResponse({"actor": request.state.principal})

    plan = "/v1/installations/installation-alpha/plan"
    artifact = "/v1/installations/installation-alpha/artifacts/release/" + "a" * 64
    state = "/v1/installations/installation-alpha/state"
    reports = "/v1/installations/installation-alpha/plans/plan-one/reports"
    completion = "/v1/installations/installation-alpha/native-transition-completion"
    plan_detail = "/v1/installations/installation-alpha/plans/plan-one"
    app = secure_app(
        Starlette(
            routes=[
                Route(plan, ok),
                Route(artifact, ok),
                Route(state, ok, methods=["POST"]),
                Route(reports, ok, methods=["POST"]),
                Route(completion, ok, methods=["POST"]),
                Route(plan_detail, ok),
                Route("/v1/catalog", ok),
            ]
        ),
        config,
        vendor=False,
    )
    seed_entra_key_cache(
        app.state.entra_verifier,
        original.state.entra_verifier._keys,
    )
    service = dict(oid="agent-object", azp="agent-client", scp=None, roles=["Agent.Access"])
    with TestClient(app, base_url=config.origin) as client:
        assert client.get(plan, headers=token(**service)).status_code == 200
        assert client.get(artifact, headers=token(**service)).status_code == 200
        assert client.post(state, headers=token(**service), json={}).status_code == 200
        assert client.post(reports, headers=token(**service), json={}).status_code == 200
        assert client.post(completion, headers=token(**service), json={}).status_code == 200
        for path in (
            "/v1/catalog",
            "/v1/catalog/releases",
            "/v1/configurations",
            "/v1/installations/other/plan",
            "/v1/installations/installation-alpha/enrollment",
            "/v1/installations/installation-alpha/enrollment/approve",
            "/v1/installations/installation-alpha/recompute",
            "/v1/installations/installation-alpha/application-binding",
            "/v1/installations/installation-alpha/native-ownership",
            plan_detail,
        ):
            assert client.get(path, headers=token(**service)).status_code == 403
            assert client.post(path, headers=token(**service), json={}).status_code == 403
        assert client.post(plan, headers=token(**service), json={}).status_code == 403
        assert client.post(artifact, headers=token(**service), json={}).status_code == 403
        assert client.get(state, headers=token(**service)).status_code == 403
        assert client.get(plan, headers=token()).status_code == 403
        for changes in (
            {"oid": "other"},
            {"azp": "other"},
            {"idtyp": "user"},
            {"roles": []},
            {"roles": ["Catalog.Read"]},
            {"scp": "Hub.Access"},
        ):
            assert client.get(plan, headers=token(**(service | changes))).status_code == 403


def test_agent_bindings_do_not_change_default_or_vendor_authority(auth):
    principal = AgentPrincipal(
        installation_id="installation-alpha", object_id="agent-object", client_id="agent-client"
    )
    config = auth.model_copy(update={"agent_principals": (principal,)})
    with pytest.raises(ValueError, match="Release Hub"):
        secure_app(Starlette(), config, vendor=True)
    for invalid in (
        (principal, principal),
        (principal.model_copy(update={"object_id": "approved-human"}),),
        (principal.model_copy(update={"client_id": "operator-browser"}),),
        (principal.model_copy(update={"object_id": "customer-service"}),),
    ):
        with pytest.raises(ValueError, match="unique|distinct"):
            RemoteAuth.model_validate_json(
                auth.model_copy(update={"agent_principals": invalid}).model_dump_json()
            )


def test_application_binding_requires_verified_operator(
    enrollment_remote, enrolled_store, installation
):
    from uuid import uuid4

    factory, token = enrollment_remote
    identifier = installation.installation_id
    path = f"/v1/installations/{identifier}/application-binding"
    with factory(target_store=enrolled_store) as client:
        assert client.get(path).status_code == 401
        assert client.post(path, json={}).status_code == 401
        before = client.get(path, headers=token())
        assert before.status_code == 200
        assert before.json()["product"] is None
        digest = before.json()["settings_digest"]
        body = {
            "request_id": str(uuid4()),
            "expected_settings_digest": digest,
            "product": "example-web",
            "reason_code": "operator_application_binding",
            "confirmation": f"bind application {identifier} example-web {digest}",
        }
        agent = token(
            oid="agent-object", azp="agent-client", scp=None, idtyp="app", roles=["Agent.Access"]
        )
        assert client.get(path, headers=agent).status_code == 403
        assert client.post(path, headers=agent, json=body).status_code == 403
        assert (
            client.post(path, headers=token(), json={**body, "operator": "forged"}).status_code
            == 422
        )
        duplicate = json.dumps(body)[:-1] + ',"product":"different-app"}'
        assert (
            client.post(
                path, headers={**token(), "Content-Type": "application/json"}, content=duplicate
            ).status_code
            == 422
        )
        updated = client.post(path, headers=token(), json=body)
        assert updated.status_code == 200
        assert updated.json()["changed"] is True
        assert client.get(path, headers=token()).json()["product"] == "example-web"
        assert client.post(path, headers=token(), json=body).json()["changed"] is False


def test_native_creation_acceptance_requires_separate_verified_operator(
    enrollment_remote, enrolled_store, installation, installation_key, now
):
    from lifecycle.hub.tests.test_application_binding import command
    from lifecycle.hub.tests.test_native_ownership import acceptance

    from fdai_lifecycle_hub import models
    from fdai_lifecycle_hub.api import create_app
    from fdai_lifecycle_hub.migrations import migrate

    identifier = installation.installation_id
    migrate(enrolled_store.engine, "lifecycle_hub", models.Base.metadata.create_all)
    enrolled_store.bind_application(
        identifier,
        command(enrolled_store, identifier, "example-app"),
        operator="owner",
        now=now,
    )
    request = acceptance(enrolled_store, installation_key)
    body = json.loads(request.model_dump_json())
    factory, token = enrollment_remote
    path = f"/v1/installations/{identifier}/native-ownership"
    with TestClient(create_app(enrolled_store)) as local:
        assert local.post(path, json=body).status_code == 403
    with factory(target_store=enrolled_store) as client:
        assert client.post(path, json=body).status_code == 401
        agent = token(
            oid="agent-object", azp="agent-client", scp=None, idtyp="app", roles=["Agent.Access"]
        )
        assert client.post(path, headers=agent, json=body).status_code == 403
        assert (
            client.post(path, headers=token(), json={**body, "operator": "forged"}).status_code
            == 422
        )
        duplicate = json.dumps(body)[:-1] + ',"reason":"duplicate"}'
        assert (
            client.post(
                path, headers={**token(), "Content-Type": "application/json"}, content=duplicate
            ).status_code
            == 422
        )
        assert (
            client.post(
                path, headers={**token(), "Origin": "https://foreign.example.test"}, json=body
            ).status_code
            == 403
        )
        response = client.post(path, headers=token(), json=body)
        assert response.status_code == 200
        assert response.json()["changed"] is True
        assert client.post(path, headers=token(), json=body).json()["changed"] is False


TENANT = "00000000-0000-0000-0000-000000000000"


def test_execution_settings_require_verified_operator(
    enrollment_remote, enrolled_store, installation
):
    from uuid import uuid4

    factory, token = enrollment_remote
    identifier = installation.installation_id
    path = f"/v1/installations/{identifier}/execution-settings"
    with factory(target_store=enrolled_store) as client:
        assert client.get(path).status_code == 401
        assert client.post(path, json={}).status_code == 401
        before = client.get(path, headers=token())
        assert before.status_code == 200
        digest = before.json()["settings_digest"]
        body = {
            "request_id": str(uuid4()),
            "expected_settings_digest": digest,
            "windows": [],
            "plan_duration_minutes": 20,
            "reason_code": "operator_schedule_change",
            "confirmation": f"update execution settings {identifier} {digest}",
        }
        agent = token(
            oid="agent-object", azp="agent-client", scp=None, idtyp="app", roles=["Agent.Access"]
        )
        assert client.get(path, headers=agent).status_code == 403
        assert client.post(path, headers=agent, json=body).status_code == 403
        updated = client.post(path, headers=token(), json=body)
        assert updated.status_code == 200
        assert updated.json()["changed"] is True
        assert client.post(path, headers=token(), json=body).json()["changed"] is False
        invalid = body | {"operator": "forged"}
        assert client.post(path, headers=token(), json=invalid).status_code == 422
        assert (
            client.post(
                path,
                headers=token() | {"Content-Type": "application/json"},
                content=b"x" * 8193,
            ).status_code
            == 413
        )


def test_configuration_inventory_requires_operator_identity(enrollment_remote):
    factory, token = enrollment_remote
    with factory() as client:
        assert client.get("/v1/configurations").status_code == 401
        assert client.get("/v1/configurations", headers=token()).status_code == 200
        agent = token(
            oid="agent-object", azp="agent-client", scp=None, idtyp="app", roles=["Agent.Access"]
        )
        assert client.get("/v1/configurations", headers=agent).status_code == 403


def test_native_proof_transport_is_agent_only_and_never_accepts_ownership(
    enrollment_remote, enrolled_store, installation, installation_key, now
):
    from lifecycle.hub.tests.test_application_binding import command
    from lifecycle.hub.tests.test_native_ownership import acceptance

    from fdai_lifecycle_hub import models
    from fdai_lifecycle_hub.migrations import migrate

    identifier = installation.installation_id
    migrate(enrolled_store.engine, "lifecycle_hub", models.Base.metadata.create_all)
    enrolled_store.bind_application(
        identifier,
        command(enrolled_store, identifier, "example-app"),
        operator="owner",
        now=now,
    )
    proof = acceptance(enrolled_store, installation_key).proof
    body = json.loads(proof.model_dump_json())
    before = enrolled_store.load(identifier)
    factory, token = enrollment_remote
    path = f"/v1/installations/{identifier}/native-proofs"
    service = dict(
        oid="agent-object", azp="agent-client", scp=None, idtyp="app", roles=["Agent.Access"]
    )
    with factory(target_store=enrolled_store) as client:
        assert client.post(path, json=body).status_code == 401
        assert client.post(path, headers=token(), json=body).status_code == 403
        agent = token(**service)
        assert client.get(path, headers=agent).status_code == 403
        for changes in (
            {"oid": "other"},
            {"azp": "other"},
            {"idtyp": "user"},
            {"roles": []},
        ):
            assert (
                client.post(path, headers=token(**(service | changes)), json=body).status_code
                == 403
            )
        assert (
            client.post(
                "/v1/installations/other/native-proofs", headers=agent, json=body
            ).status_code
            == 403
        )
        assert (
            client.post(path, headers=agent, json=body | {"operator": "forged"}).status_code == 422
        )
        assert (
            client.post(
                path,
                headers=agent | {"Content-Type": "application/json"},
                content=b"x" * 8193,
            ).status_code
            == 413
        )
        duplicate = proof.model_dump_json()[:-1] + ',"signature":"duplicate"}'
        assert (
            client.post(
                path, headers=agent | {"Content-Type": "application/json"}, content=duplicate
            ).status_code
            == 422
        )
        first = client.post(path, headers=agent, json=body)
        assert first.status_code == 202
        assert first.json() == {"received": True, "changed": True}
        exact_limit = proof.model_dump_json().encode().ljust(8192, b" ")
        assert (
            client.post(
                path, headers=agent | {"Content-Type": "application/json"}, content=exact_limit
            ).status_code
            == 202
        )
        assert client.post(path, headers=agent, json=body).json() == {
            "received": True,
            "changed": False,
        }
        assert (
            client.post(
                f"/v1/installations/{identifier}/native-ownership", headers=agent, json={}
            ).status_code
            == 403
        )
    assert enrolled_store.load(identifier) == before


@pytest.fixture
def enrollment_remote(auth, protected, store, now):
    from fdai_lifecycle_hub.api import create_app

    vendor, token = protected

    def client(*, bound=True, target_store=store, origin=auth.origin):
        config = auth.model_copy(
            update={
                "origin": origin,
                "service_object_id": None,
                "service_client_id": None,
                "agent_principals": (
                    (
                        AgentPrincipal(
                            installation_id="installation-alpha",
                            object_id="agent-object",
                            client_id="agent-client",
                        ),
                    )
                    if bound
                    else ()
                ),
            }
        )
        app = create_app(target_store, remote_auth=config, clock=lambda: now)
        seed_entra_key_cache(
            app.state.entra_verifier,
            vendor.state.entra_verifier._keys,
        )
        return TestClient(app, base_url=config.origin)

    return client, token


def signed_enrollment_body(enrollment):
    return {
        "signed_payload": b64encode(enrollment.signed_payload).decode("ascii"),
        "proof": b64encode(enrollment.proof).decode("ascii"),
    }


@pytest.fixture
def https_enrollment_remote(enrollment_remote, tmp_path):
    import ipaddress
    import socket
    import ssl
    import threading
    from contextlib import contextmanager

    import httpx
    import uvicorn
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import NameOID

    make_client, token = enrollment_remote
    tls_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "loopback-test")])
    at = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(tls_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(at - timedelta(minutes=1))
        .not_valid_after(at + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(tls_key, hashes.SHA256())
    )
    certificate_path, key_path = tmp_path / "tls-cert.pem", tmp_path / "tls-key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.touch(mode=0o600)
    key_path.write_bytes(
        tls_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    trust = ssl.create_default_context(cafile=str(certificate_path))

    @contextmanager
    def live_client(*, target_store):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            origin = f"https://127.0.0.1:{listener.getsockname()[1]}"
            app_client = make_client(target_store=target_store, origin=origin)
            server = uvicorn.Server(
                uvicorn.Config(
                    app_client.app,
                    log_level="warning",
                    access_log=False,
                    ssl_certfile=str(certificate_path),
                    ssl_keyfile=str(key_path),
                    timeout_graceful_shutdown=2,
                )
            )
            thread = threading.Thread(
                target=server.run, kwargs={"sockets": [listener]}, daemon=True
            )
            try:
                thread.start()
                deadline = time.monotonic() + 10
                while not server.started:
                    if not thread.is_alive() or time.monotonic() >= deadline:
                        pytest.fail("the local HTTPS Hub did not start within 10 seconds")
                    time.sleep(0.01)
                with httpx.Client(
                    base_url=origin, verify=trust, timeout=5, trust_env=False
                ) as client:
                    yield client
            finally:
                server.should_exit = True
                thread.join(timeout=10)
                app_client.close()
                assert not thread.is_alive(), "the local HTTPS Hub did not stop"

    try:
        yield live_client, token, trust
    finally:
        key_path.unlink()
        certificate_path.unlink()


def test_operator_submits_bound_enrollment_without_approving_it(
    enrollment_remote, enrollment, store
):
    from sqlalchemy import select

    from fdai_lifecycle_hub.models import AuditRecord

    make_client, token = enrollment_remote
    path = "/v1/enrollments/installation-alpha/requests"
    with make_client() as client:
        response = client.post(path, json=signed_enrollment_body(enrollment), headers=token())
        assert response.status_code == 202
        assert response.json()["enrollment"] == "pending"
        pending = client.get("/v1/enrollments/pending", headers=token())
        assert len(pending.json()["enrollments"]) == 1
        assert client.get("/v1/installations", headers=token()).json() == {"installations": []}
        assert (
            client.post(path, json=signed_enrollment_body(enrollment), headers=token()).status_code
            == 409
        )
    with store.engine.connect() as connection:
        payload = connection.scalar(
            select(AuditRecord.payload).where(AuditRecord.action == "enrollment.requested")
        )
    assert payload["requested_by"] == "approved-human"
    assert store.enrollment_status("installation-alpha").value == "pending"


def test_operator_lists_bound_installations_without_typing_ids(
    enrollment_remote, enrollment, store
):
    make_client, token = enrollment_remote
    with make_client() as client:
        listed = client.get("/v1/enrollments/bindable", headers=token())
        assert listed.status_code == 200
        assert listed.json() == {
            "installations": [{"installation_id": "installation-alpha", "status": "unrequested"}]
        }
        path = "/v1/enrollments/installation-alpha/requests"
        assert (
            client.post(path, json=signed_enrollment_body(enrollment), headers=token()).status_code
            == 202
        )
        pending = client.get("/v1/enrollments/bindable", headers=token()).json()
        assert pending["installations"][0]["status"] == "pending"
        assert client.get("/v1/enrollments/bindable").status_code == 401
        agent = token(
            oid="agent-object",
            azp="agent-client",
            scp=None,
            idtyp="app",
            roles=["Agent.Access"],
        )
        assert client.get("/v1/enrollments/bindable", headers=agent).status_code == 403
    with make_client(bound=False) as unbound:
        assert unbound.get("/v1/enrollments/bindable", headers=token()).status_code == 404


def test_bound_enrollment_agent_protocol_and_durable_hub_restart(
    https_enrollment_remote, enrollment, installation, planner, key, now, tmp_path
):
    import httpx

    from fdai_lifecycle_agent.hub_client import HttpHubClient, HubProtocolError, PlanReport
    from fdai_lifecycle_hub import schemas
    from fdai_lifecycle_hub.domain import Issued, IssuedPlan
    from fdai_lifecycle_hub.signing import signature_verifier
    from fdai_lifecycle_hub.store import HubStore

    make_client, token, trust = https_enrollment_remote
    installation_id = installation.installation_id
    base = f"/v1/installations/{installation_id}"
    database_url = f"sqlite:///{tmp_path / 'remote-hub.db'}"
    store = HubStore.connect(database_url)
    store.create_schema()

    def agent_authorization():
        return token(
            oid="agent-object",
            azp="agent-client",
            scp=None,
            idtyp="app",
            roles=["Agent.Access"],
        )["Authorization"].removeprefix("Bearer ")

    try:
        with (
            make_client(target_store=store) as operator,
            HttpHubClient(
                str(operator.base_url),
                authorization=agent_authorization,
                transport=httpx.HTTPTransport(verify=trust, retries=0),
            ) as agent,
        ):
            response = operator.post(
                f"/v1/enrollments/{installation_id}/requests",
                json=signed_enrollment_body(enrollment),
                headers=token(),
            )
            assert response.status_code == 202
            assert agent.fetch_plan(installation_id) is None
            assert operator.get("/v1/installations", headers=token()).json() == {
                "installations": []
            }
            assert (
                operator.post(
                    f"{base}/enrollment/approve",
                    headers={"Authorization": f"Bearer {agent_authorization()}"},
                    json={
                        "approver": "approved-human",
                        "installation_key_id": enrollment.installation_key_id,
                    },
                ).status_code
                == 403
            )
            approved = operator.post(
                f"{base}/enrollment/approve",
                headers=token(),
                json={
                    "approver": "approved-human",
                    "installation_key_id": enrollment.installation_key_id,
                },
            )
            assert approved.status_code == 200
            assert (
                len(operator.get("/v1/installations", headers=token()).json()["installations"]) == 1
            )
            assert agent.fetch_plan(installation_id) is None
            for entity in installation.entities:
                if entity.ownership is not None:
                    store.record_ownership(
                        installation_id,
                        entity.entity_id,
                        entity.ownership,
                        operator="approved-human",
                        now=now,
                    )
                if entity.settings is not None:
                    store.manage(
                        installation_id,
                        entity.entity_id,
                        entity.settings,
                        operator="approved-human",
                        now=now,
                    )
            issued = store.recompute(installation_id, planner, now=now)
            assert isinstance(issued, Issued)
            fetched = agent.fetch_plan(installation_id)
            assert fetched is not None
            assert fetched.signed_payload == issued.plan.signed_payload
            assert signature_verifier({key.key_id: key.public_key})(
                key.key_id, fetched.signed_payload, fetched.signature
            )
            report = PlanReport(
                attempt=1,
                outcome="dry-run-admitted",
                reason_code="admitted",
                exact_plan_digest=IssuedPlan.from_signed(issued.plan).digest,
                summary="dry run admitted",
                reported_at=now,
            )
            agent.submit_report(installation_id, issued.plan.plan_id, report)
            snapshot = schemas.reported_state_json.dump_python(installation.reported, mode="json")
            snapshot["observed_at"] = (now + timedelta(seconds=1)).isoformat()
            agent.submit_state(installation_id, snapshot)
            with pytest.raises(HubProtocolError, match="403"):
                agent.fetch_plan("other-installation")
    finally:
        store.engine.dispose()

    reopened = HubStore.connect(database_url)
    try:
        with (
            make_client(target_store=reopened) as operator,
            HttpHubClient(
                str(operator.base_url),
                authorization=agent_authorization,
                transport=httpx.HTTPTransport(verify=trust, retries=0),
            ) as agent,
        ):
            assert operator.get("/v1/enrollments/pending", headers=token()).json() == {
                "enrollments": []
            }
            assert (
                len(operator.get("/v1/installations", headers=token()).json()["installations"]) == 1
            )
            assert agent.fetch_plan(installation_id) == fetched
            agent.submit_report(installation_id, issued.plan.plan_id, report)
            assert len(reopened.reports(installation_id)) == 1
            assert reopened.load(installation_id).reported.observed_at == now + timedelta(seconds=1)
            with pytest.raises(HubProtocolError, match="stale_state"):
                agent.submit_state(installation_id, snapshot)
            assert reopened.audit_chain_intact()
    finally:
        reopened.engine.dispose()


@pytest.mark.parametrize(
    ("changes", "status"),
    [
        (None, 401),
        ({"oid": "other-operator"}, 403),
        (
            {
                "oid": "agent-object",
                "azp": "agent-client",
                "scp": None,
                "idtyp": "app",
                "roles": ["Agent.Access"],
            },
            403,
        ),
        ({"Origin": "https://other.example.com"}, 403),
        ({"Sec-Fetch-Site": "cross-site"}, 403),
    ],
)
def test_operator_enrollment_rejects_untrusted_callers(
    enrollment_remote, enrollment, store, changes, status
):
    make_client, token = enrollment_remote
    if changes is None:
        headers = {}
    elif "Origin" in changes or "Sec-Fetch-Site" in changes:
        headers = token() | changes
    else:
        headers = token(**changes)
    with make_client() as client:
        response = client.post(
            "/v1/enrollments/installation-alpha/requests",
            json=signed_enrollment_body(enrollment),
            headers=headers,
        )
    assert response.status_code == status
    assert store.list_pending_enrollments() == ()


def test_operator_enrollment_keeps_unbound_and_default_routes_closed(
    enrollment_remote, enrollment, store
):
    make_client, token = enrollment_remote
    body = signed_enrollment_body(enrollment)
    with make_client(bound=False) as client:
        assert (
            client.post(
                "/v1/enrollments/installation-alpha/requests", json=body, headers=token()
            ).status_code
            == 404
        )
    with make_client() as client:
        assert (
            client.post(
                "/v1/enrollments/other-installation/requests", json=body, headers=token()
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/v1/installations/installation-alpha/enrollment", json=body, headers=token()
            ).status_code
            == 403
        )
    assert store.list_pending_enrollments() == ()


@pytest.mark.parametrize("invalid", ["signature", "stale", "path", "json", "size", "actor"])
def test_operator_enrollment_keeps_proof_and_request_bounds(
    enrollment_remote, enrollment, store, sign, installation, now, invalid
):
    from sqlalchemy import select

    from fdai_lifecycle_hub.api import MAX_ENROLLMENT_BYTES
    from fdai_lifecycle_hub.models import AuditRecord

    make_client, token = enrollment_remote
    if invalid == "stale":
        enrollment = sign(installation, now - timedelta(minutes=6))
    body = signed_enrollment_body(enrollment)
    if invalid == "signature":
        body["proof"] = b64encode(b"invalid-signature").decode("ascii")
    elif invalid == "path":
        payload = json.loads(enrollment.signed_payload)
        payload["installation_id"] = "other-installation"
        body["signed_payload"] = b64encode(json.dumps(payload).encode()).decode("ascii")
    elif invalid == "actor":
        body["requested_by"] = "forged-actor"
    if invalid == "json":
        content = b"{"
    elif invalid == "size":
        content = b" " * (MAX_ENROLLMENT_BYTES + 1)
    else:
        content = json.dumps(body).encode()
    with make_client() as client:
        response = client.post(
            "/v1/enrollments/installation-alpha/requests",
            content=content,
            headers=token() | {"Content-Type": "application/json"},
        )
    assert response.status_code == (
        403 if invalid in {"signature", "stale"} else 413 if invalid == "size" else 422
    )
    assert store.list_pending_enrollments() == ()
    if invalid in {"signature", "stale"}:
        with store.engine.connect() as connection:
            payload = connection.scalar(
                select(AuditRecord.payload).where(AuditRecord.action == "enrollment.proof_failed")
            )
        assert payload["requested_by"] == "approved-human"


AGENT_CLAIMS = {
    "oid": "agent-object",
    "azp": "agent-client",
    "scp": None,
    "idtyp": "app",
    "roles": ["Agent.Access"],
}
AGENT_ENROLLMENT_PATH = "/v1/installations/installation-alpha/enrollment-request"


def test_agent_submits_only_a_pending_enrollment_for_its_installation(
    enrollment_remote, enrollment, store
):
    from sqlalchemy import select

    from fdai_lifecycle_hub.models import AuditRecord

    make_client, token = enrollment_remote
    agent = token(**AGENT_CLAIMS)
    with make_client() as client:
        response = client.post(
            AGENT_ENROLLMENT_PATH, json=signed_enrollment_body(enrollment), headers=agent
        )
        assert response.status_code == 202
        assert response.json() == {
            "enrollment": "pending",
            "installation_key_id": enrollment.installation_key_id,
        }
        assert client.get("/v1/installations", headers=token()).json() == {"installations": []}
        assert (
            client.get("/v1/installations/installation-alpha/plan", headers=agent).status_code
            == 204
        )
        detail = client.get("/v1/enrollments/pending/installation-alpha", headers=token()).json()
        assert detail["requested_by"] == "agent-object"
        assert detail["requested_via"] == "agent"
        assert (
            client.post(
                AGENT_ENROLLMENT_PATH, json=signed_enrollment_body(enrollment), headers=agent
            ).status_code
            == 409
        )
    with store.engine.connect() as connection:
        payload = connection.scalar(
            select(AuditRecord.payload).where(AuditRecord.action == "enrollment.requested")
        )
    assert payload["requested_by"] == "agent-object"
    assert payload["requested_via"] == "agent"
    assert store.enrollment_status("installation-alpha").value == "pending"


def test_operator_submission_is_attributed_to_the_operator(enrollment_remote, enrollment, store):
    make_client, token = enrollment_remote
    with make_client() as client:
        assert (
            client.post(
                "/v1/enrollments/installation-alpha/requests",
                json=signed_enrollment_body(enrollment),
                headers=token(),
            ).status_code
            == 202
        )
        detail = client.get("/v1/enrollments/pending/installation-alpha", headers=token()).json()
    assert (detail["requested_by"], detail["requested_via"]) == ("approved-human", "operator")


@pytest.mark.parametrize(
    "changes",
    [
        {"oid": "other"},
        {"azp": "other"},
        {"idtyp": "user"},
        {"roles": []},
        {"roles": ["Catalog.Read"]},
        {"roles": None},
        {"scp": "Hub.Access"},
    ],
)
def test_agent_enrollment_requires_the_exact_binding_role_and_no_delegation(
    enrollment_remote, enrollment, store, changes
):
    make_client, token = enrollment_remote
    with make_client() as client:
        response = client.post(
            AGENT_ENROLLMENT_PATH,
            json=signed_enrollment_body(enrollment),
            headers=token(**(AGENT_CLAIMS | changes)),
        )
    assert response.status_code == 403
    assert store.list_pending_enrollments() == ()


def test_agent_enrollment_rejects_other_unbound_and_non_agent_callers(
    enrollment_remote, enrollment, store
):
    make_client, token = enrollment_remote
    body = signed_enrollment_body(enrollment)
    agent = token(**AGENT_CLAIMS)
    with make_client() as client:
        other = "/v1/installations/other-installation/enrollment-request"
        assert client.post(other, json=body, headers=agent).status_code == 403
        assert client.post(AGENT_ENROLLMENT_PATH, json=body).status_code == 401
        assert client.post(AGENT_ENROLLMENT_PATH, json=body, headers=token()).status_code == 403
        assert client.get(AGENT_ENROLLMENT_PATH, headers=agent).status_code == 403
        assert client.put(AGENT_ENROLLMENT_PATH, json=body, headers=agent).status_code == 403
        for headers in (
            agent | {"Origin": "https://attacker.example"},
            agent | {"Sec-Fetch-Site": "cross-site"},
            agent | {"Content-Type": "text/plain"},
        ):
            assert (
                client.post(AGENT_ENROLLMENT_PATH, content=b"{}", headers=headers).status_code
                == 403
            )
    with make_client(bound=False) as unbound:
        assert unbound.post(AGENT_ENROLLMENT_PATH, json=body, headers=agent).status_code == 403
    assert store.list_pending_enrollments() == ()


def test_agent_enrollment_is_closed_on_release_hub_and_without_a_binding(auth):
    principal = AgentPrincipal(
        installation_id="installation-alpha", object_id="agent-object", client_id="agent-client"
    )
    with pytest.raises(ValueError, match="Release Hub"):
        secure_app(
            Starlette(), auth.model_copy(update={"agent_principals": (principal,)}), vendor=True
        )


@pytest.mark.parametrize(
    "invalid", ["signature", "stale", "path", "json", "size", "actor", "replay"]
)
def test_agent_enrollment_keeps_proof_and_request_bounds(
    enrollment_remote, enrollment, store, sign, installation, now, invalid
):
    from sqlalchemy import select

    from fdai_lifecycle_hub.api import MAX_ENROLLMENT_BYTES
    from fdai_lifecycle_hub.models import AuditRecord

    make_client, token = enrollment_remote
    if invalid == "stale":
        enrollment = sign(installation, now - timedelta(minutes=6))
    body = signed_enrollment_body(enrollment)
    if invalid == "signature":
        body["proof"] = b64encode(b"invalid-signature").decode("ascii")
    elif invalid == "path":
        payload = json.loads(enrollment.signed_payload)
        payload["installation_id"] = "other-installation"
        body["signed_payload"] = b64encode(json.dumps(payload).encode()).decode("ascii")
    elif invalid == "actor":
        body["requested_by"] = "forged-actor"
    if invalid == "json":
        content = b"{"
    elif invalid == "size":
        content = b" " * (MAX_ENROLLMENT_BYTES + 1)
    else:
        content = json.dumps(body).encode()
    headers = token(**AGENT_CLAIMS) | {"Content-Type": "application/json"}
    with make_client() as client:
        if invalid == "replay":
            assert (
                client.post(AGENT_ENROLLMENT_PATH, content=content, headers=headers).status_code
                == 202
            )
        response = client.post(AGENT_ENROLLMENT_PATH, content=content, headers=headers)
    assert response.status_code == (
        403
        if invalid in {"signature", "stale"}
        else 413
        if invalid == "size"
        else 409
        if invalid == "replay"
        else 422
    )
    assert len(store.list_pending_enrollments()) == (1 if invalid == "replay" else 0)
    if invalid in {"signature", "stale"}:
        with store.engine.connect() as connection:
            payload = connection.scalar(
                select(AuditRecord.payload).where(AuditRecord.action == "enrollment.proof_failed")
            )
        assert payload["requested_by"] == "agent-object"


def test_agent_can_neither_decide_nor_reach_any_other_route(enrollment_remote, enrollment, store):
    import re

    from starlette.routing import Route as StarletteRoute

    make_client, token = enrollment_remote
    agent = token(**AGENT_CLAIMS)
    allowed = {
        ("GET", "/v1/installations/{installation_id}/plan"),
        ("POST", "/v1/installations/{installation_id}/state"),
        ("POST", "/v1/installations/{installation_id}/plans/{plan_id}/reports"),
        ("POST", "/v1/installations/{installation_id}/native-proofs"),
        ("POST", "/v1/installations/{installation_id}/native-transition-completion"),
        ("POST", "/v1/installations/{installation_id}/enrollment-request"),
    }
    with make_client() as client:
        assert (
            client.post(
                AGENT_ENROLLMENT_PATH, json=signed_enrollment_body(enrollment), headers=agent
            ).status_code
            == 202
        )
        reached = set()
        for route in client.app.routes:
            if not isinstance(route, StarletteRoute) or not route.path.startswith("/v1/"):
                continue
            concrete = re.sub(
                r"\{([a-z_]+)\}",
                lambda match: "a" * 64 if "digest" in match[1] else "installation-alpha",
                route.path,
            )
            for method in ("GET", "POST", "PUT", "DELETE"):
                status = client.request(method, concrete, json={}, headers=agent).status_code
                if status != 403:
                    reached.add((method, route.path))
        assert reached <= allowed
        for decision in ("approve", "reject"):
            path = f"/v1/installations/installation-alpha/enrollment/{decision}"
            body = {
                "approver": "agent-object",
                "installation_key_id": enrollment.installation_key_id,
            }
            assert client.post(path, json=body | {"reason": "x"}, headers=agent).status_code == 403
        assert (
            client.post(
                "/v1/enrollments/installation-alpha/requests",
                json=signed_enrollment_body(enrollment),
                headers=agent,
            ).status_code
            == 403
        )
    assert store.enrollment_status("installation-alpha").value == "pending"


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
                Route("/v1/catalog/metadata", ok),
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
    seed_entra_key_cache(
        app.state.entra_verifier,
        {"test-only": jwt.PyJWK.from_dict(public)},
    )

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


def _redirecting_app(auth, *hosts):
    async def ok(request):
        return JSONResponse({"actor": "reached"})

    return secure_app(
        Starlette(
            routes=[Route("/healthz", ok), Route("/v1/catalog", ok, methods=["GET", "POST"])]
        ),
        auth.model_copy(update={"redirect_hosts": hosts}),
        vendor=True,
    )


def test_former_host_redirects_reads_to_the_fixed_origin(auth):
    former = "old-hub.example.com"
    with TestClient(
        _redirecting_app(auth, former), base_url=f"https://{former}", follow_redirects=False
    ) as client:
        response = client.get("/healthz")
        assert response.status_code == 308
        assert response.headers["location"] == "https://hub.example.com/healthz"
        assert response.headers["cache-control"] == "no-store"
        assert client.head("/healthz").status_code == 308
        assert (
            client.get("/v1/catalog?x=1&y=%2F").headers["location"]
            == "https://hub.example.com/v1/catalog?x=1&y=%2F"
        )
        # The destination host is never taken from the request path.
        hostile = client.get("//evil.example.com/x").headers["location"]
        assert urlsplit(hostile).hostname == "hub.example.com"


def test_former_host_does_not_serve_writes_or_other_hosts(auth):
    former = "old-hub.example.com"
    app = _redirecting_app(auth, former)
    with TestClient(app, base_url=f"https://{former}", follow_redirects=False) as client:
        assert client.post("/v1/catalog").status_code in {400, 401}
        assert client.delete("/v1/catalog").status_code in {400, 401, 405}
    with TestClient(
        app, base_url="https://untrusted.example.com", follow_redirects=False
    ) as client:
        assert client.get("/healthz").status_code == 400
    with TestClient(app, base_url="https://hub.example.com", follow_redirects=False) as client:
        assert client.get("/healthz").status_code == 200


def test_without_redirect_hosts_a_former_host_is_refused(auth):
    with TestClient(
        _redirecting_app(auth), base_url="https://old-hub.example.com", follow_redirects=False
    ) as client:
        assert client.get("/healthz").status_code in {400, 401}


@pytest.mark.parametrize(
    "hosts",
    [
        ("hub.example.com",),
        ("OLD.example.com",),
        ("old-hub.example.com", "old-hub.example.com"),
        ("old-hub.example.com:8443",),
        ("*.example.com",),
        ("localhost",),
        tuple(f"old{n}.example.com" for n in range(5)),
    ],
)
def test_redirect_hosts_must_be_distinct_dns_names_other_than_the_origin(auth, hosts):
    with pytest.raises(ValueError):
        auth.model_copy(update={"redirect_hosts": hosts}).model_validate(
            {**auth.model_dump(), "redirect_hosts": hosts}
        )


def test_service_identity_is_read_export_only(protected):
    app, token = protected
    service = dict(
        oid="customer-service",
        azp="customer-client",
        scp=None,
        roles=["Catalog.Read"],
    )
    with TestClient(app, base_url="https://hub.example.com") as client:
        assert client.get("/v1/catalog/export", headers=token(**service)).status_code == 200
        assert client.get("/v1/catalog/metadata", headers=token(**service)).status_code == 200
        assert client.get("/v1/catalog", headers=token(**service)).status_code == 403
        assert (
            client.post("/v1/releases/change", headers=token(**service), json={}).status_code == 403
        )
        for changes in (
            {"oid": "vendor-service"},
            {"azp": "vendor-client"},
            {"roles": []},
            {"idtyp": "user"},
        ):
            assert (
                client.get("/v1/catalog/export", headers=token(**(service | changes))).status_code
                == 403
            )


@pytest.mark.parametrize("operation", ["renew", "custom-contribution"])
def test_release_catalog_renewal_requires_attributed_vendor_operator(
    auth, protected, tmp_path, catalog, operation
):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fdai_deployment_cli.contracts import canonical_bytes

    from fdai_lifecycle_hub.signing import HubSigningKey
    from fdai_release_hub.api import create_app
    from fdai_release_hub.store import Change, ReleaseStore

    now = datetime(2026, 10, 15, tzinfo=UTC)
    store = ReleaseStore(
        tmp_path / "vendor.db", HubSigningKey(Ed25519PrivateKey.generate(), 1), clock=lambda: now
    )
    store.clock = lambda: now + timedelta(seconds=1)
    if operation == "custom-contribution":
        for action in ("register", "publish"):
            store.change(
                action,
                "1.6.0",
                Change(
                    revision=store.snapshot()["revision"],
                    confirmation="1.6.0",
                    reason="Prepare reviewed synthetic publication",
                    manifest=canonical_bytes(catalog.releases["1.6.0"].to_mapping()).decode()
                    if action == "register"
                    else None,
                ),
            )
    original, token = protected
    app = create_app(store, remote_auth=auth, remote_origin=auth.origin)
    seed_entra_key_cache(
        app.state.entra_verifier,
        original.state.entra_verifier._keys,
    )
    payload = {"revision": 0, "confirmation": "renew 0", "reason": "Reviewed current catalog"}
    route = "/v1/catalog/renew"
    revision = 0
    if operation == "custom-contribution":
        route = "/v1/releases/1.6.0/contribute"
        revision = 2
        payload = {
            "revision": 2,
            "confirmation": "1.6.0",
            "reason": "Reviewed custom destination",
            "channel": "custom-pilot",
            "channel_confirmation": "custom-pilot",
        }
    with TestClient(app, base_url=auth.origin) as client:
        assert client.post(route, json=payload).status_code == 401
        for identity in (
            dict(
                oid="customer-service",
                azp="customer-client",
                scp=None,
                idtyp="app",
                roles=["Catalog.Read"],
            ),
            dict(
                oid="agent-object",
                azp="agent-client",
                scp=None,
                idtyp="app",
                roles=["Agent.Access"],
            ),
            dict(oid="other-human"),
        ):
            assert client.post(route, headers=token(**identity), json=payload).status_code == 403
        assert (
            client.post(
                route,
                headers={**token(), "Origin": "https://other.example.com"},
                json=payload,
            ).status_code
            == 403
        )
        assert store.snapshot()["revision"] == revision
        response = client.post(route, headers={**token(), "Origin": auth.origin}, json=payload)
        assert response.status_code == 200
        assert response.json()["revision"] == revision + 1
        assert response.json()["events"][0]["actor"] == "approved-human"
        if operation == "custom-contribution":
            assert response.json()["channels"]["custom-pilot"] == ["1.6.0"]


def test_target_local_curation_requires_current_operator_and_exact_request(
    auth, protected, tmp_path, key, catalog, now, monkeypatch
):
    from lifecycle.hub.tests.test_local_channels import prepare, request_for

    from fdai_lifecycle_hub.api import create_app
    from fdai_lifecycle_hub.remote import target_routes

    _vendor, target, store = prepare(tmp_path, key, catalog, now)
    original, token = protected
    monkeypatch.setattr("fdai_lifecycle_hub.remote.utc_now", lambda: now)
    app = create_app(store, remote_auth=auth)
    app.routes[0:0] = target_routes(store, target, key)
    seed_entra_key_cache(
        app.state.entra_verifier,
        original.state.entra_verifier._keys,
    )
    target.fetch = lambda _: pytest.fail("Local curation must not fetch or import a source.")
    route = "/v1/catalog/local-channels"
    payload = request_for(target, catalog, now).model_dump()
    with TestClient(app, base_url=auth.origin) as client:
        assert client.post(route, json=payload).status_code == 401
        for identity in (
            dict(oid="other-human"),
            dict(
                oid="customer-service",
                azp="customer-client",
                idtyp="app",
                scp=None,
                roles=["Catalog.Read"],
            ),
            dict(oid="agent", azp="agent-client", idtyp="app", scp=None, roles=["Agent.Access"]),
        ):
            assert client.post(route, headers=token(**identity), json=payload).status_code == 403
        assert (
            client.post(
                route, headers={**token(), "Origin": "https://other.example.com"}, json=payload
            ).status_code
            == 403
        )
        assert (
            client.post(
                route, headers=token(), json={**payload, "confirmation": "unreviewed"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                route, headers={**token(), "Content-Type": "application/json"}, content=b"x" * 4097
            ).status_code
            == 413
        )
        assert target.local_channels(now=now)["revision"] == 0
        response = client.post(route, headers=token(), json=payload)
        assert response.status_code == 200
        assert response.json()["entries"][0]["actor"] == "approved-human"
        assert response.json()["execution_authority"] is False
        assert client.post(route, headers=token(), json=payload).status_code == 409
        assert client.get(route, headers=token()).json()["revision"] == 1
        from sqlalchemy.exc import OperationalError

        def unavailable(*args, **kwargs):
            raise OperationalError("synthetic metadata operation", {}, RuntimeError("synthetic"))

        monkeypatch.setattr(target, "add_local_channel", unavailable)
        uncertain = client.post(route, headers=token(), json=payload)
        assert uncertain.status_code == 503
        assert "not confirmed" in uncertain.json()["error"]
        assert "refresh retained evidence" in uncertain.json()["error"]
        monkeypatch.setattr(target, "local_channels", unavailable)
        assert client.get(route, headers=token()).status_code == 503


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
    seed_entra_key_cache(
        app.state.entra_verifier,
        vendor.state.entra_verifier._keys,
    )
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


def test_public_catalog_export_opens_only_the_signed_read_path(auth):
    async def served(request):
        return JSONResponse({"served": request.url.path})

    def vendor_app(config, *, vendor=True):
        return secure_app(
            Starlette(
                routes=[
                    Route("/v1/catalog/export", served, methods=["GET", "POST"]),
                    Route("/v1/catalog/metadata", served, methods=["GET", "POST"]),
                    Route("/v1/catalog", served),
                ]
            ),
            config,
            vendor=vendor,
        )

    public = auth.model_copy(update={"public_catalog_export": True})
    with TestClient(vendor_app(public), base_url=public.origin) as client:
        assert client.get("/v1/catalog/export").status_code == 200
        assert client.get("/v1/catalog/metadata").status_code == 200
        assert client.head("/v1/catalog/metadata").status_code == 200
        assert client.post("/v1/catalog/metadata", json={}).status_code == 401
        assert client.head("/v1/catalog/export").status_code == 200
        assert client.post("/v1/catalog/export", json={}).status_code == 401
        assert client.get("/v1/catalog").status_code == 401
    with TestClient(vendor_app(auth), base_url=auth.origin) as closed:
        assert closed.get("/v1/catalog/export").status_code == 401
    with pytest.raises(ValueError, match="Only Release Hub"):
        vendor_app(public, vendor=False)
