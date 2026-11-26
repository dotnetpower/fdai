from __future__ import annotations

from base64 import b64encode
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from hashlib import sha256
from secrets import token_hex

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_configuration_package import (
    ConfigurationHistoryBinding,
    build_installation_configuration_package,
)
from lifecycle.hub.tests.configuration_key_helpers import remote_auth, request_for, tokens
from lifecycle.hub.tests.test_configuration_revision import PlanCase
from lifecycle.hub.tests.test_remote_catalog import approve, source_for
from sqlalchemy import Engine
from starlette.testclient import TestClient

from fdai_lifecycle_hub import models
from fdai_lifecycle_hub.api import create_app
from fdai_lifecycle_hub.configuration_import_contracts import (
    ImportContext,
    ScopeRequest,
    SignedImportRequest,
    SignedScopeRequest,
)
from fdai_lifecycle_hub.migrations import migrate, require_schema
from fdai_lifecycle_hub.remote import target_routes
from fdai_lifecycle_hub.remote_auth import DevelopmentRecoveryAuthorization, RemoteAuth
from fdai_lifecycle_hub.remote_catalog import RemoteCatalog, initialize_trust, metadata
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_lifecycle_hub.store import HubStore
from fdai_release_hub.store import ReleaseStore


def wire(value: bytes) -> str:
    return b64encode(value).decode("ascii")


@dataclass
class ImportHarness:
    engine: Engine
    store: HubStore
    catalog: RemoteCatalog
    case: PlanCase
    identity: Ed25519PrivateKey
    key: HubSigningKey
    now: datetime
    auth: RemoteAuth
    client: TestClient = field(init=False)
    token: Callable[..., dict[str, str]] = field(init=False)
    scope_digest: str = ""

    @property
    def iid(self):
        return self.case.installation.installation_id

    def post(self, suffix, value, *, actor="requester"):
        self.now += timedelta(seconds=1)
        return self.client.post(
            f"/v1/installations/{self.iid}/{suffix}",
            json=value.model_dump(mode="json") if hasattr(value, "model_dump") else value,
            headers=self.token(actor),
        )

    def register_keys(
        self,
        *,
        signer=None,
        recipient=None,
        version=1,
        predecessor=None,
        approver="approver",
        **changes,
    ):
        request, signed = request_for(
            self.identity,
            signer or self.case.signing,
            recipient or self.case.recipient,
            self.now,
            installation_id=self.iid,
            version=version,
            predecessor=predecessor,
            **changes,
        )
        response = self.post("configuration-keys/request", signed)
        assert response.status_code == 202, response.json()
        response = self.post(
            "configuration-keys/approve", {"request_digest": request.digest}, actor=approver
        )
        assert response.status_code == 202, response.json()
        return request

    def scope_request(self, **changes):
        release = self.case.catalog.releases["1.6.0"]
        fields = {
            "format": "fdai.configuration-scope.v1",
            "installation_id": self.iid,
            "requester": "requester",
            "request_id": token_hex(16),
            "release_version": "1.6.0",
            "release_digest": release.digest,
            "schema_digest": release.configuration_schema.digest,
            "entity_bindings": dict(self.case.candidate.entity_bindings),
            "sealed_keys": sorted(self.case.source.sealed_keys),
            "requested_at": self.now,
            "approval_expires_at": self.now + timedelta(minutes=10),
            "expires_at": self.now + timedelta(days=1),
        }
        fields.update(changes)
        scope = ScopeRequest.model_validate(fields)
        return scope, SignedScopeRequest(
            signed_payload=wire(scope.payload),
            identity_proof=wire(self.identity.sign(scope.payload)),
        )

    def approve_scope(self):
        scope, signed = self.scope_request()
        response = self.post("configuration-scope/request", signed)
        assert response.status_code == 202, response.json()
        inspection = self.client.get(
            f"/v1/installations/{self.iid}/configuration-scope/requests/{scope.digest}",
            headers=self.token("approver"),
        )
        assert inspection.status_code == 200
        assert inspection.json()["request"]["entity_bindings"] == scope.entity_bindings
        response = self.post(
            "configuration-scope/approve", {"digest": scope.digest}, actor="approver"
        )
        assert response.status_code == 202, response.json()
        self.scope_digest = scope.digest
        return scope

    def import_request(self, package=None, *, version=1, predecessor=None, **changes):
        package = package or self.case.candidate.package
        container = canonical_bytes(
            {
                "format": "fdai.lifecycle-configuration-file.v1",
                "payload": wire(package.payload),
                "signature": wire(package.signature),
            }
        )
        fields = {
            "format": "fdai.configuration-import.v1",
            "installation_id": self.iid,
            "requester": "requester",
            "package_digest": package.digest,
            "container_digest": sha256(container).hexdigest(),
            "binding_version": version,
            "scope_digest": self.scope_digest or "0" * 64,
            "predecessor_digest": predecessor,
            "requested_at": self.now,
        }
        fields.update(changes)
        context = ImportContext.model_validate(fields)
        return SignedImportRequest(
            signed_payload=wire(context.payload),
            identity_proof=wire(self.identity.sign(context.payload)),
            signed_container=wire(container),
        )

    def stage(self, signed=None):
        response = self.post("configuration/import", signed or self.import_request())
        assert response.status_code == 202, response.json()
        return response.json()

    def activate(self, decision, *, approver="approver", activator="requester"):
        response = self.post("configuration/approve", decision, actor=approver)
        assert response.status_code == 202, response.json()
        response = self.post("configuration/activate", decision, actor=activator)
        assert response.status_code == 202, response.json()

    def child(self, revision, *, history=None, signer=None, recipient=None, bindings=None):
        return build_installation_configuration_package(
            replace(self.case.source, revision_id=revision * 40),
            entity_ids=frozenset(dict(self.case.candidate.entity_bindings).values()),
            signing_key=signer or self.case.signing,
            installation_key=(recipient or self.case.recipient).public_key(),
            history=history or (self.case.candidate.package,),
            history_bindings=bindings,
        )

    def history_binding(self):
        return ConfigurationHistoryBinding(
            self.case.signing.public_key(), self.case.candidate.installation_key_digest
        )


def make_harness(
    engine,
    case,
    identity,
    key,
    now,
    sign,
    tmp_path,
    monkeypatch,
    *,
    plan_duration=timedelta(minutes=20),
    recovery: DevelopmentRecoveryAuthorization | None = None,
):
    source = source_for(key)

    def initialize(connection):
        models.Base.metadata.create_all(connection)
        metadata.create_all(connection)
        initialize_trust(connection, source)

    migrate(engine, "lifecycle_hub", initialize)
    require_schema(engine, "lifecycle_hub")
    store = HubStore(engine)
    target = replace(
        case.installation,
        settings=replace(case.installation.settings, plan_duration=plan_duration),
    )
    enrollment = sign(target, now)
    # Exercise the ordinary SignedEnrollment HTTP parser, never a renamed Entity fixture.
    with TestClient(create_app(store, clock=lambda: now), base_url="http://127.0.0.1") as local:
        response = local.post(
            f"/v1/installations/{target.installation_id}/enrollment",
            json={
                "signed_payload": wire(enrollment.signed_payload),
                "proof": wire(enrollment.proof),
            },
        )
        assert response.status_code == 202, response.json()
        response = local.post(
            f"/v1/installations/{target.installation_id}/enrollment/approve",
            json={"approver": "approver", "installation_key_id": enrollment.installation_key_id},
        )
        assert response.status_code == 200, response.json()
    for entity in target.entities:
        if entity.ownership is not None:
            store.record_ownership(
                target.installation_id,
                entity.entity_id,
                entity.ownership,
                operator="approver",
                now=now,
            )
        if entity.settings is not None:
            store.manage(
                target.installation_id,
                entity.entity_id,
                entity.settings,
                operator="approver",
                now=now,
            )
    raw = ReleaseStore(tmp_path / "release.db", key, clock=lambda: now).export()[0]
    catalog = RemoteCatalog(engine, source, fetch=lambda _: raw)
    approve(catalog, raw, now)
    catalog.import_once(actor="approver", now=now)
    auth = remote_auth(recovery)
    harness = ImportHarness(engine, store, catalog, case, identity, key, now, auth)
    app = create_app(store, clock=lambda: harness.now, remote_auth=auth)
    monkeypatch.setattr("fdai_lifecycle_hub.remote.utc_now", lambda: harness.now)
    # This is exactly the default configured composition. No candidate/map injection.
    app.routes[0:0] = target_routes(store, catalog, key, recovery_authorization=recovery)
    harness.client = TestClient(app, base_url=auth.origin)
    harness.token = tokens(app, auth)
    return harness
