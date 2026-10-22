from __future__ import annotations

import json
import time
from base64 import b64encode
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from fdai_lifecycle_hub.remote_auth import AgentPrincipal, RemoteAuth, secure_app


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
    state = "/v1/installations/installation-alpha/state"
    reports = "/v1/installations/installation-alpha/plans/plan-one/reports"
    app = secure_app(
        Starlette(
            routes=[
                Route(plan, ok),
                Route(state, ok, methods=["POST"]),
                Route(reports, ok, methods=["POST"]),
                Route("/v1/catalog", ok),
            ]
        ),
        config,
        vendor=False,
    )
    app.state.entra_verifier._keys = original.state.entra_verifier._keys
    app.state.entra_verifier._refresh_after = time.monotonic() + 600
    service = dict(
        oid="agent-object", azp="agent-client", scp=None, idtyp="app", roles=["Agent.Access"]
    )
    with TestClient(app, base_url=config.origin) as client:
        assert client.get(plan, headers=token(**service)).status_code == 200
        assert client.post(state, headers=token(**service), json={}).status_code == 200
        assert client.post(reports, headers=token(**service), json={}).status_code == 200
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
        ):
            assert client.get(path, headers=token(**service)).status_code == 403
            assert client.post(path, headers=token(**service), json={}).status_code == 403
        assert client.post(plan, headers=token(**service), json={}).status_code == 403
        assert client.get(state, headers=token(**service)).status_code == 403
        assert client.get(plan, headers=token()).status_code == 403
        for changes in (
            {"oid": "other"},
            {"azp": "other"},
            {"idtyp": None},
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
            {"idtyp": None},
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
        app.state.entra_verifier._keys = vendor.state.entra_verifier._keys
        app.state.entra_verifier._refresh_after = time.monotonic() + 600
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
    app.state.entra_verifier._keys = original.state.entra_verifier._keys
    app.state.entra_verifier._refresh_after = time.monotonic() + 600
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
    app.state.entra_verifier._keys = original.state.entra_verifier._keys
    app.state.entra_verifier._refresh_after = time.monotonic() + 600
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
