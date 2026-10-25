from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_catalog_roles import root_to_wire
from lifecycle.hub.tests.tuf_helpers import Authority, ident, new_key
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from starlette.testclient import TestClient

from fdai_lifecycle_hub.adoption_policy import AdoptionConfig, evaluate_policy, policy_input
from fdai_lifecycle_hub.catalog_adoption import CatalogUpdater
from fdai_lifecycle_hub.catalog_integrity import payload_digest
from fdai_lifecycle_hub.catalog_trust import CatalogTrust, parse_metadata
from fdai_lifecycle_hub.migrations import migrate
from fdai_lifecycle_hub.remote import CatalogRolesConfig, RemoteConfig
from fdai_lifecycle_hub.remote_catalog import (
    CatalogSource,
    FetchedExport,
    RemoteCatalog,
    bind_catalog,
    initialize_trust,
)
from fdai_lifecycle_hub.remote_catalog import metadata as trust_metadata
from fdai_release_hub import catalog_roles
from fdai_release_hub.api import create_app as create_release_app
from fdai_release_hub.catalog_roles import CatalogRoleKeys
from fdai_release_hub.role_tables import catalog_role_state, catalog_roots
from fdai_release_hub.store import CatalogError, Change, ReleaseStore

needs_opa = pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary not on PATH")
START = datetime(2026, 10, 5, 3, tzinfo=UTC)
LOOPBACK = {"base_url": "http://127.0.0.1:8091", "client": ("127.0.0.1", 50001)}


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def pem_of(key) -> str:
    return key.public_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()


@dataclass
class Vendor:
    store: ReleaseStore
    authority: Authority
    clock: Clock

    def root(self, version, **kwargs):
        return self.authority.root(version, export_key=self.store.key, now=self.clock.now, **kwargs)

    def install(self, root):
        payload = json.dumps(root_to_wire(root)).encode()
        return self.store.install_root(payload, actor="vendor-operator")


@pytest.fixture
def clock() -> Clock:
    return Clock()


def build_vendor(
    tmp_path,
    key,
    catalog,
    clock,
    *,
    timestamp_ttl=timedelta(hours=24),
    install=True,
    database=None,
):
    authority = Authority()
    keys = CatalogRoleKeys(
        snapshot=authority.snapshot, timestamp=authority.timestamp, timestamp_ttl=timestamp_ttl
    )
    store = ReleaseStore(database or tmp_path / "vendor.db", key, clock=clock, role_keys=keys)
    vendor = Vendor(store, authority, clock)
    publish(store, catalog, "1.5.0", clock)
    if install:
        vendor.install(vendor.root(1))
    return vendor


@pytest.fixture
def vendor(tmp_path, key, catalog, clock) -> Vendor:
    return build_vendor(tmp_path, key, catalog, clock)


def publish(store, catalog, version, clock, *, channel=None) -> None:
    clock.advance(minutes=1)
    actions = (("register", None), ("publish", None))
    if channel is not None:
        actions += (("contribute", channel),)
    for action, target_channel in actions:
        store.change(
            action,
            version,
            Change(
                revision=store.snapshot()["revision"],
                confirmation=version,
                reason="Synthetic development validation",
                manifest=canonical_bytes(catalog.releases[version].to_mapping()).decode()
                if action == "register"
                else None,
                channel=target_channel,
            ),
        )


def recall(store, version, clock) -> None:
    clock.advance(minutes=1)
    store.change(
        "recall",
        version,
        Change(
            revision=store.snapshot()["revision"],
            confirmation=version,
            reason="Synthetic recall",
        ),
    )


def serve_from(vendor: Vendor):
    def fetch(source, *, accepted_digest=None):
        signed = vendor.store.signed_export()
        if accepted_digest == signed.digest:
            return None
        return FetchedExport(signed.raw, signed.signature, signed.key_id)

    return fetch, lambda source: vendor.store.signed_metadata().raw


def frozen_from(vendor: Vendor):
    """Capture what the Release Hub serves now, so the Lifecycle Hub reads it later."""

    signed, metadata = vendor.store.signed_export(), vendor.store.signed_metadata().raw

    def fetch(source, *, accepted_digest=None):
        if accepted_digest == signed.digest:
            return None
        return FetchedExport(signed.raw, signed.signature, signed.key_id)

    return fetch, lambda source: metadata


def auto(**extra):
    return {
        "mode": "auto",
        "allowed_channels": ("DEV",),
        "authorized_by": "customer-owner",
        "authorization_expires_at": "2026-12-01T00:00:00+00:00",
        **extra,
    }


def tuf_source(vendor: Vendor, **adoption) -> CatalogSource:
    return CatalogSource(
        url="https://release.example.com/v1/catalog/export",
        access="anonymous",
        trust=vendor.authority.pin(),
        adoption=AdoptionConfig(**adoption),
    )


def tuf_updater(
    tmp_path, key, vendor, store, clock, *, adoption, serve=None, name="trust.db", engine=None
):
    source = tuf_source(vendor, **adoption)
    engine = engine or create_engine(f"sqlite:///{tmp_path / name}")
    migrate(engine, "lifecycle_hub", lambda c: initialize_trust(c, source))
    fetch, roles = serve or serve_from(vendor)
    catalog = RemoteCatalog(engine, source, fetch_signed=fetch, fetch_roles=roles)
    return CatalogUpdater(catalog, store, key, clock=clock)


# --- Release Hub: metadata endpoint, caching, renewal and root installation ---------------


def test_metadata_is_absent_without_roles_and_unavailable_before_a_root(
    tmp_path, key, catalog, clock
):
    plain = ReleaseStore(tmp_path / "plain.db", key, clock=clock)
    client = TestClient(create_release_app(plain), **LOOPBACK)
    assert client.get("/v1/catalog/metadata").status_code == 404
    assert client.get("/v1/catalog/export").status_code == 200
    pending = build_vendor(tmp_path, key, catalog, clock, install=False)
    client = TestClient(create_release_app(pending.store), **LOOPBACK)
    response = client.get("/v1/catalog/metadata")
    assert response.status_code == 503 and "not installed" in response.json()["error"]


def test_metadata_serves_one_signed_bundle_with_conditional_reads(vendor):
    client = TestClient(create_release_app(vendor.store), **LOOPBACK)
    first = client.get("/v1/catalog/metadata")
    assert first.status_code == 200
    bundle = parse_metadata(first.content)
    export = vendor.store.signed_export()
    assert bundle.snapshot.export_digest == export.digest
    assert bundle.snapshot.export_revision == json.loads(export.raw)["revision"]
    assert (bundle.snapshot.version, bundle.timestamp.version) == (1, 1)
    again = client.get("/v1/catalog/metadata", headers={"If-None-Match": first.headers["etag"]})
    weak = client.get(
        "/v1/catalog/metadata", headers={"If-None-Match": "W/" + first.headers["etag"]}
    )
    assert again.status_code == 304 and again.content == b""
    assert weak.status_code == 304
    assert client.head("/v1/catalog/metadata").status_code == 200


def test_a_request_storm_costs_one_export_and_one_signing_per_state(vendor, catalog, monkeypatch):
    exports, snapshots, timestamps = [], [], []
    original_export = vendor.store.export
    monkeypatch.setattr(
        vendor.store, "export", lambda *a, **k: exports.append(1) or original_export(*a, **k)
    )
    service = vendor.store.roles
    sign_snapshot, sign_timestamp = service._sign_snapshot, service._sign_timestamp
    monkeypatch.setattr(
        service, "_sign_snapshot", lambda *a: snapshots.append(1) or sign_snapshot(*a)
    )
    monkeypatch.setattr(
        service, "_sign_timestamp", lambda *a: timestamps.append(1) or sign_timestamp(*a)
    )
    client = TestClient(create_release_app(vendor.store), **LOOPBACK)
    etags = {client.get("/v1/catalog/metadata").headers["etag"] for _ in range(40)}
    for _ in range(40):
        etag = client.get("/v1/catalog/metadata").headers["etag"]
        assert (
            client.get("/v1/catalog/metadata", headers={"If-None-Match": etag}).status_code == 304
        )
    assert len(etags) == 1
    assert (len(exports), len(snapshots), len(timestamps)) == (1, 1, 1)
    publish(vendor.store, catalog, "1.6.0", vendor.clock)
    changed = client.get("/v1/catalog/metadata").headers["etag"]
    assert changed not in etags
    assert (len(exports), len(snapshots), len(timestamps)) == (2, 2, 2)


def test_renewal_re_signs_only_the_timestamp_and_never_appends_an_event(vendor):
    store = vendor.store
    before_export, before = store.signed_export(), parse_metadata(store.signed_metadata().raw)
    revision = store.snapshot()["revision"]
    vendor.clock.advance(hours=1)
    assert store.renew_if_due() is False
    vendor.clock.advance(hours=12)
    assert store.renew_if_due() is True
    after_export, after = store.signed_export(), parse_metadata(store.signed_metadata().raw)
    assert after_export.raw == before_export.raw and after_export.digest == before_export.digest
    assert store.snapshot()["revision"] == revision
    assert [event["action"] for event in store.snapshot()["events"]].count("renew") == 0
    assert after.snapshot == before.snapshot
    assert after.timestamp.version == before.timestamp.version + 1
    assert after.timestamp.expires_at > before.timestamp.expires_at
    assert store.renew_if_due() is False


def test_concurrent_requests_for_one_new_state_sign_exactly_once(vendor, catalog, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    service = vendor.store.roles
    signed = []
    sign_snapshot, sign_timestamp = service._sign_snapshot, service._sign_timestamp
    monkeypatch.setattr(
        service, "_sign_snapshot", lambda *a: signed.append("s") or sign_snapshot(*a)
    )
    monkeypatch.setattr(
        service, "_sign_timestamp", lambda *a: signed.append("t") or sign_timestamp(*a)
    )
    publish(vendor.store, catalog, "1.6.0", vendor.clock)
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: vendor.store.signed_metadata().raw, range(36)))
    assert len(set(results)) == 1
    assert sorted(signed) == ["s", "t"]


def test_snapshot_is_re_signed_before_it_expires_and_versions_only_increase(vendor):
    store = vendor.store
    first = parse_metadata(store.signed_metadata().raw)
    seen = [(first.snapshot.version, first.timestamp.version)]
    for _ in range(20):
        vendor.clock.advance(hours=13)
        store.renew_if_due()
        latest = parse_metadata(store.signed_metadata().raw)
        seen.append((latest.snapshot.version, latest.timestamp.version))
    assert seen == sorted(seen) and len(set(seen)) == len(seen)
    assert seen[-1][0] > 1
    assert latest.snapshot.expires_at > vendor.clock.now


def test_legacy_renewal_is_unchanged_without_roles(tmp_path, key, catalog, clock):
    plain = ReleaseStore(tmp_path / "legacy.db", key, clock=clock)
    publish(plain, catalog, "1.5.0", clock)
    assert plain.renew_if_due() is False
    clock.advance(hours=13)
    assert plain.renew_if_due() is True
    assert plain.snapshot()["events"][0]["action"] == "renew"


def test_renewal_stays_legacy_until_a_signed_root_is_installed(tmp_path, key, catalog, clock):
    pending = build_vendor(tmp_path, key, catalog, clock, install=False)
    assert pending.store.roles is not None and not pending.store.roles.installed()
    clock.advance(hours=13)
    assert pending.store.renew_if_due() is True
    assert pending.store.snapshot()["events"][0]["action"] == "renew"
    pending.install(pending.root(1))
    assert pending.store.roles.installed()
    events = len(pending.store.snapshot()["events"])
    clock.advance(hours=13)
    assert pending.store.renew_if_due() is True
    assert len(pending.store.snapshot()["events"]) == events


def test_root_installation_requires_a_threshold_and_authorized_online_keys(vendor):
    successor = Authority(root_keys=[new_key() for _ in range(3)], threshold=2)
    successor.snapshot, successor.timestamp = vendor.authority.snapshot, vendor.authority.timestamp

    def rotation(**kwargs):
        return successor.root(2, export_key=vendor.store.key, now=vendor.clock.now, **kwargs)

    with pytest.raises(CatalogError, match="rotation_unsigned_by_previous"):
        vendor.install(rotation())
    with pytest.raises(CatalogError, match="rotation_unsigned_by_previous"):
        vendor.install(rotation(also_signed_by=vendor.authority.root_keys[:1]))
    with pytest.raises(CatalogError, match="chain_invalid"):
        vendor.install(vendor.root(3))
    with pytest.raises(CatalogError, match="already expired"):
        vendor.install(
            successor.root(
                2,
                export_key=vendor.store.key,
                now=vendor.clock.now - timedelta(days=500),
                valid_days=1,
                also_signed_by=vendor.authority.root_keys[:2],
            )
        )
    stranger = Authority(root_keys=successor.root_keys, threshold=2)
    retired = stranger.root(
        2,
        export_key=vendor.store.key,
        now=vendor.clock.now,
        also_signed_by=vendor.authority.root_keys[:2],
    )
    with pytest.raises(CatalogError, match="does not authorize"):
        vendor.install(retired)
    accepted = vendor.install(rotation(also_signed_by=vendor.authority.root_keys[:2]))
    assert accepted["version"] == 2
    chain = parse_metadata(vendor.store.signed_metadata().raw).root_chain
    assert [root.version for root in chain] == [1, 2]
    with pytest.raises(CatalogError):
        vendor.store.install_root(b"{}", actor="vendor-operator")
    with pytest.raises(CatalogError, match="attributed"):
        vendor.store.install_root(b"{}", actor=" ")


def test_the_role_tables_hold_public_records_only_and_are_optional(vendor, tmp_path, key, clock):
    engine = vendor.store.engine
    tables = set(inspect(engine).get_table_names())
    assert {"catalog_role_root", "catalog_role_state"} <= tables
    with engine.connect() as connection:
        stored = " ".join(
            str(value)
            for table in (catalog_roots, catalog_role_state)
            for row in connection.execute(select(table))
            for value in row
        )
    assert "PRIVATE" not in stored
    plain = ReleaseStore(tmp_path / "plain.db", key, clock=clock)
    assert "catalog_role_root" not in inspect(plain.engine).get_table_names()
    assert plain.roles is None
    with pytest.raises(CatalogError) as raised:
        plain.signed_metadata()
    assert raised.value.status == 404


def test_role_keys_must_be_distinct_and_bounded():
    authority = Authority()
    with pytest.raises(ValueError, match="different keys"):
        CatalogRoleKeys(snapshot=authority.snapshot, timestamp=authority.snapshot)
    for fields in (
        {"timestamp_ttl": timedelta(minutes=5)},
        {"timestamp_ttl": timedelta(days=8)},
        {"snapshot_ttl": timedelta(hours=2)},
        {"snapshot_ttl": timedelta(days=90)},
    ):
        with pytest.raises(ValueError):
            CatalogRoleKeys(snapshot=authority.snapshot, timestamp=authority.timestamp, **fields)


def test_a_root_that_retires_the_online_keys_stops_serving_metadata(vendor):
    replacement = Authority()
    replacement.root_keys = vendor.authority.root_keys
    chain_root = replacement.root(
        2, export_key=vendor.store.key, now=vendor.clock.now, signers=vendor.authority.root_keys
    )
    # Installing it directly is refused because this Hub's own keys are no longer authorized.
    with pytest.raises(CatalogError, match="does not authorize"):
        vendor.install(chain_root)
    assert vendor.store.signed_metadata()


# --- Lifecycle Hub: adoption under signed roles -----------------------------------------


def test_source_trust_modes_are_exclusive_and_validated(vendor, key):
    pin = vendor.authority.pin()
    base = {"url": "https://release.example.com/v1/catalog/export", "access": "anonymous"}
    legacy_pem = pem_of(key)
    with pytest.raises(ValueError, match="exactly one"):
        CatalogSource(**base)
    with pytest.raises(ValueError, match="exactly one"):
        CatalogSource(**base, release_public_key=legacy_pem, trust=pin)
    tuf = CatalogSource(**base, trust=pin)
    assert tuf.tuf and tuf.metadata_url == "https://release.example.com/v1/catalog/metadata"
    assert tuf.key_digest == pin.key_digest
    with pytest.raises(ValueError, match="signed roles"):
        tuf.public_key()
    legacy = CatalogSource(**base, release_public_key=legacy_pem)
    assert not legacy.tuf and legacy.key_digest != tuf.key_digest
    with pytest.raises(ValueError):
        CatalogSource(**base, trust={"mode": "pinned"})  # type: ignore[arg-type]


def test_remote_config_accepts_roles_only_for_the_release_hub():
    base = {"kind": "release", "origin": "https://release.example.com"}
    assert RemoteConfig.model_validate({**base, "catalog_roles": {}}).catalog_roles
    with pytest.raises(ValueError, match="Only Release Hub"):
        RemoteConfig.model_validate(
            {"kind": "target", "origin": "https://hub.example.com", "catalog_roles": {}}
        )
    with pytest.raises(ValueError, match="outlast"):
        CatalogRolesConfig(timestamp_ttl_seconds=86400, snapshot_ttl_seconds=3600)
    with pytest.raises(ValueError):
        CatalogRolesConfig(timestamp_ttl_seconds=60)


@needs_opa
def test_signed_roles_adopt_a_catalog_and_floors_survive_a_restart(
    tmp_path, key, catalog, store, clock, vendor
):
    updater = tuf_updater(tmp_path, key, vendor, store, clock, adoption=auto())
    first = updater.check()
    assert (first.outcome, first.detail) == ("adopted", "policy_allow")
    assert first.integrity["verified"] and first.integrity["root"]["version"] == 1
    shown = updater.status()
    assert shown["integrity"]["root_version"] == 1
    assert shown["integrity"]["timestamp_version"] == 1
    assert shown["accepted"]["expires_at"] == shown["integrity"]["timestamp_expires_at"]
    assert updater.catalog.status()["mode"] == "tuf-catalog-roles"
    old_metadata = vendor.store.signed_metadata().raw
    assert updater.check().outcome == "unchanged"
    publish(vendor.store, catalog, "1.6.0", clock)
    assert updater.check().outcome == "adopted"
    assert updater.status()["integrity"]["snapshot_version"] == 2

    reopened = tuf_updater(
        tmp_path, key, vendor, store, clock, adoption=auto(), serve=serve_from(vendor)
    )
    assert reopened.status()["integrity"]["snapshot_version"] == 2
    assert reopened.catalog.integrity_floors().max_recall_sequence == 0
    reopened.catalog.fetch_roles = lambda source: old_metadata
    replay = reopened.check()
    assert (replay.outcome, replay.detail) == ("failed", "integrity_not_verified")
    assert replay.integrity["reason"] == "catalog_version_rollback"
    assert reopened.status()["integrity"]["last"]["reason"] == "catalog_version_rollback"
    assert reopened.status()["integrity"]["snapshot_version"] == 2


@needs_opa
def test_renewal_advances_the_persisted_timestamp_without_new_content(
    tmp_path, key, store, clock, vendor
):
    updater = tuf_updater(tmp_path, key, vendor, store, clock, adoption=auto())
    assert updater.check().outcome == "adopted"
    accepted = updater.catalog.status()["accepted_sha256"]
    clock.advance(hours=13)
    assert vendor.store.renew_if_due()
    again = updater.check()
    assert again.outcome == "unchanged"
    assert updater.catalog.status()["accepted_sha256"] == accepted
    status = updater.status()["integrity"]
    assert status["timestamp_version"] == 2 and status["snapshot_version"] == 1
    events = [event["action"] for event in updater.catalog.recent_events(20)]
    assert events.count("catalog.imported") == 1


@needs_opa
def test_expired_timestamp_allows_only_recall_rolloff(tmp_path, key, catalog, store, clock):
    vendor = build_vendor(tmp_path, key, catalog, clock, timestamp_ttl=timedelta(hours=2))
    updater = tuf_updater(tmp_path, key, vendor, store, clock, adoption=auto())
    assert updater.check().outcome == "adopted"
    publish(vendor.store, catalog, "1.6.0", clock)
    updater.catalog.fetch_signed, updater.catalog.fetch_roles = frozen_from(vendor)
    clock.advance(hours=3)
    held = updater.check()
    assert held.outcome == "review_required"
    assert "timestamp_expired" in held.candidate["decision"]["reasons"]
    assert held.integrity["expired"] and held.integrity["allowed_plan_types"] == ["recall-rolloff"]
    assert updater.catalog.catalog(clock.now).plan_types == {"recall-rolloff"}
    with pytest.raises(ValueError, match="only recall"):
        updater.apply(
            revision=held.candidate["revision"], sha256=held.candidate["sha256"], actor="operator"
        )
    assert updater.catalog.status()["accepted_sha256"] != held.candidate["sha256"]


@needs_opa
def test_an_expired_timestamp_still_adopts_a_recall_so_roll_off_can_proceed(
    tmp_path, key, catalog, store, clock
):
    vendor = build_vendor(tmp_path, key, catalog, clock, timestamp_ttl=timedelta(hours=2))
    updater = tuf_updater(tmp_path, key, vendor, store, clock, adoption=auto())
    assert updater.check().outcome == "adopted"
    recall(vendor.store, "1.5.0", clock)
    updater.catalog.fetch_signed, updater.catalog.fetch_roles = frozen_from(vendor)
    clock.advance(hours=3)
    rolled = updater.check()
    assert (rolled.outcome, rolled.detail) == ("adopted", "policy_allow")
    assert rolled.candidate["change"]["new_recalls"] and rolled.integrity["expired"]
    assert updater.status()["integrity"]["last"]["expired"] is True
    accepted = updater.catalog.catalog(clock.now)
    assert accepted.recalls and accepted.plan_types == {"recall-rolloff"}


@needs_opa
def test_a_stale_signed_timestamp_narrows_planning_to_recall_rolloff(
    tmp_path, key, catalog, store, clock
):
    vendor = build_vendor(tmp_path, key, catalog, clock, timestamp_ttl=timedelta(hours=2))
    updater = tuf_updater(tmp_path, key, vendor, store, clock, adoption=auto())
    assert updater.check().outcome == "adopted"
    fresh = updater.catalog.catalog(clock.now)
    assert fresh.plan_types is None
    clock.advance(hours=3)
    stale = updater.catalog.catalog(clock.now)
    assert stale.plan_types == {"recall-rolloff"}
    assert stale.releases.keys() == fresh.releases.keys()


@needs_opa
def test_root_rotation_always_waits_for_a_person_even_in_automatic_mode(
    tmp_path, key, store, clock, vendor
):
    updater = tuf_updater(tmp_path, key, vendor, store, clock, adoption=auto())
    assert updater.check().outcome == "adopted"
    successor = Authority(root_keys=[new_key() for _ in range(3)], threshold=2)
    successor.snapshot, successor.timestamp = vendor.authority.snapshot, vendor.authority.timestamp
    rotated = successor.root(
        2, export_key=vendor.store.key, now=clock.now, also_signed_by=vendor.authority.root_keys[:2]
    )
    clock.advance(minutes=1)
    vendor.install(rotated)
    held = updater.check()
    assert held.outcome == "review_required"
    assert held.detail == "root_rotation_requires_review"
    assert held.integrity["root_rotation"] and held.integrity["root"]["version"] == 2
    assert updater.status()["integrity"]["root_version"] == 1
    again = updater.check()
    assert again.outcome == "review_required"
    reviews = [
        e for e in updater.catalog.recent_events(20) if e["action"] == "check.review_required"
    ]
    assert len(reviews) == 1
    applied = updater.apply(
        revision=held.candidate["revision"], sha256=held.candidate["sha256"], actor="operator-oid"
    )
    assert applied.outcome == "adopted" and applied.detail.startswith("operator_review")
    assert updater.status()["integrity"]["root_version"] == 2
    settled = updater.check()
    assert settled.outcome == "unchanged" and not settled.integrity["root_rotation"]


@needs_opa
def test_a_rotation_the_old_holders_did_not_sign_never_verifies(
    tmp_path, key, store, clock, vendor
):
    updater = tuf_updater(tmp_path, key, vendor, store, clock, adoption=auto())
    assert updater.check().outcome == "adopted"
    attacker = Authority(root_keys=[new_key() for _ in range(3)], threshold=2)
    attacker.snapshot, attacker.timestamp = vendor.authority.snapshot, vendor.authority.timestamp
    hostile = attacker.root(2, export_key=vendor.store.key, now=clock.now)
    metadata = vendor.store.signed_metadata().raw
    document = json.loads(metadata)
    document["root_chain"].append(root_to_wire(hostile))
    updater.catalog.fetch_roles = lambda source: json.dumps(document).encode()
    outcome = updater.check()
    assert outcome.outcome == "failed" and outcome.detail == "integrity_not_verified"
    assert outcome.integrity["reason"] == "catalog_root_rotation_unsigned_by_previous"
    assert updater.status()["integrity"]["root_version"] == 1


@needs_opa
def test_tampered_or_mismatched_exports_fail_closed(tmp_path, key, catalog, store, clock, vendor):
    import base64

    from fdai_lifecycle_hub.catalog_import import export_signing_message

    updater = tuf_updater(tmp_path, key, vendor, store, clock, adoption=auto())
    export = vendor.store.signed_export()
    updater.catalog.fetch_signed = lambda source, **_: FetchedExport(
        export.raw + b" ", export.signature, export.key_id
    )
    assert updater.check().detail == "signature_invalid"
    forged = new_key()
    forged_signature = base64.b64encode(forged.sign(export_signing_message(export.raw))).decode()
    updater.catalog.fetch_signed = lambda source, **_: FetchedExport(
        export.raw, forged_signature, "k"
    )
    assert updater.check().detail == "signature_invalid"
    updater.catalog.fetch_signed = lambda source, **_: FetchedExport(export.raw, None, None)
    assert updater.check().detail == "signature_missing"
    # Correctly signed bytes that the signed snapshot does not describe are not adopted either.
    _fetch, old_roles = frozen_from(vendor)
    publish(vendor.store, catalog, "1.6.0", clock)
    newer = vendor.store.signed_export()
    updater.catalog.fetch_roles = old_roles
    updater.catalog.fetch_signed = lambda source, **_: FetchedExport(
        newer.raw, newer.signature, newer.key_id
    )
    mismatch = updater.check()
    assert (mismatch.outcome, mismatch.detail) == ("failed", "integrity_not_verified")
    assert mismatch.integrity["reason"] == "export_digest_mismatch"
    assert updater.status()["integrity"]["last"]["reason"] == "export_digest_mismatch"
    assert updater.catalog.status()["imported"] is False
    with pytest.raises(ValueError):
        updater.apply(revision=1, sha256="0" * 64, actor="operator")


@needs_opa
def test_metadata_from_an_unpinned_authority_or_garbage_is_rejected(
    tmp_path, key, store, clock, vendor
):
    updater = tuf_updater(tmp_path, key, vendor, store, clock, adoption=auto())
    updater.catalog.fetch_roles = lambda source: b"not json"
    assert updater.check().detail == "integrity_not_verified"
    updater.catalog.fetch_roles = lambda source: (_ for _ in ()).throw(ValueError("down"))
    assert updater.check().detail == "source_unavailable"
    unpinned = Authority()
    wrong = CatalogSource(
        url="https://release.example.com/v1/catalog/export",
        access="anonymous",
        trust=unpinned.pin(),
        adoption=AdoptionConfig(**auto()),
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'wrong.db'}")
    migrate(engine, "lifecycle_hub", lambda c: initialize_trust(c, wrong))
    fetch, roles = serve_from(vendor)
    pinned_wrongly = CatalogUpdater(
        RemoteCatalog(engine, wrong, fetch_signed=fetch, fetch_roles=roles), store, key, clock=clock
    )
    outcome = pinned_wrongly.check()
    assert outcome.detail == "integrity_not_verified"
    assert outcome.integrity["reason"] == "catalog_root_pin_mismatch"


def test_manual_pin_flow_and_unsigned_adoption_are_unavailable_with_signed_roles(
    tmp_path, key, store, clock, vendor
):
    updater = tuf_updater(tmp_path, key, vendor, store, clock, adoption={})
    catalog = updater.catalog
    with pytest.raises(ValueError, match="Manual pin"):
        catalog.approve(None, actor="x", now=clock.now)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Manual pin"):
        catalog.import_once(actor="x", now=clock.now)
    export = vendor.store.signed_export()
    fetched = FetchedExport(export.raw, export.signature, export.key_id)
    with pytest.raises(ValueError, match="roles are required"):
        catalog.adopt(
            fetched, expected_previous_digest=None, actor="x", reason="test", now=clock.now
        )
    roles = parse_metadata(vendor.store.signed_metadata().raw)
    adopted = catalog.adopt(
        fetched, expected_previous_digest=None, actor="x", reason="test", now=clock.now, roles=roles
    )
    assert adopted["adopted"] is True
    assert catalog.integrity_floors().root_version == 1


def test_binding_a_database_creates_the_integrity_state_and_pin_changes_fail(tmp_path, vendor):
    source = tuf_source(vendor)
    engine = create_engine(f"sqlite:///{tmp_path / 'bind.db'}")
    migrate(engine, "lifecycle_hub", lambda c: trust_metadata.create_all(c))
    bind_catalog(engine, source, actor="owner", reason="initial bind")
    assert "catalog_integrity_state" in inspect(engine).get_table_names()
    bind_catalog(engine, source, actor="owner", reason="idempotent")
    other = source.model_copy(
        update={
            "trust": CatalogTrust(
                mode="tuf",
                root_key_ids=(ident(new_key()),),
                root_threshold=1,
            )
        }
    )
    with pytest.raises(ValueError, match="explicit key rotation"):
        bind_catalog(engine, other, actor="owner", reason="swap")
    catalog = RemoteCatalog(engine, source)
    assert catalog.integrity_floors().root_version == 0
    assert catalog.integrity_status()["last"] is None


@needs_opa
def test_a_legacy_source_still_reads_a_release_hub_that_also_serves_roles(
    tmp_path, key, store, clock, vendor
):
    source = CatalogSource(
        url="https://release.example.com/v1/catalog/export",
        access="anonymous",
        release_public_key=pem_of(key),
        adoption=AdoptionConfig(**auto()),
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    migrate(engine, "lifecycle_hub", lambda c: initialize_trust(c, source))
    fetch, _roles = serve_from(vendor)
    catalog = RemoteCatalog(engine, source, fetch_signed=fetch)
    updater = CatalogUpdater(catalog, store, key, clock=clock)
    assert "catalog_integrity_state" not in inspect(engine).get_table_names()
    shown = updater.status()
    assert "integrity" not in shown and catalog.integrity_status() is None
    assert catalog.status()["mode"] == "development-pinned-export"
    assert "integrity" not in updater.check().to_json()
    assert updater.status()["last_check"]["outcome"] == "adopted"


@needs_opa
def test_the_policy_denies_each_integrity_failure_and_ignores_legacy_inputs():
    config = AdoptionConfig(**auto())
    change = {
        "added_releases": [],
        "removed_releases": [],
        "changed_releases": [],
        "channel_additions": [],
        "channel_removals": [],
        "new_channels": [],
        "new_recalls": [],
        "lifted_recalls": [],
        "removed_recalls": [],
        "schema_widened": False,
    }

    def decide(integrity, **overrides):
        document = policy_input(
            config=config,
            change={**change, **overrides},
            baseline_present=True,
            signature_verified=True,
            now=START,
            integrity=integrity,
        )
        return set(evaluate_policy(document).reasons)

    healthy = {"verified": True, "expired": False, "root_rotation": False}
    assert decide(None) == set()
    assert decide(healthy) == set()
    assert decide({**healthy, "verified": False}) == {"integrity_not_verified"}
    assert decide({**healthy, "root_rotation": True}) == {"root_rotation_requires_review"}
    assert decide({**healthy, "expired": True}) == {"timestamp_expired"}
    recall = {"scope": "release", "target": "1.5.0", "sequence": 3}
    assert decide({**healthy, "expired": True}, new_recalls=[recall]) == set()
    addition = {"release_id": "1.6.0", "channels": ["DEV"], "schema_target": None}
    assert decide(
        {**healthy, "expired": True}, new_recalls=[recall], added_releases=[addition]
    ) == {"timestamp_expired"}


@needs_opa
def test_integrity_status_never_exposes_key_material_or_signatures(
    tmp_path, key, store, clock, vendor
):
    updater = tuf_updater(tmp_path, key, vendor, store, clock, adoption=auto())
    outcome = updater.check()
    shown = json.dumps([updater.status(), outcome.to_json()])
    bundle = parse_metadata(vendor.store.signed_metadata().raw)
    assert payload_digest(bundle.root_chain[0]) not in shown
    assert 'signature"' not in shown.replace('"signature_verified"', "")
    assert "ed25519-" not in shown
    assert catalog_roles.NOT_INSTALLED.endswith(".")


@pytest.fixture
def postgres_schemas():
    """Two task-owned schemas on the isolated validation cluster, never the runtime database."""

    value = os.environ.get("FDAI_DATABASE_URL")
    if not value:
        pytest.skip("Run through with-local-test-database.py for PostgreSQL 5433 evidence.")
    url = make_url(value)
    assert url.host in {"127.0.0.1", "localhost", "::1"} and url.port == 5433
    schemas = {kind: f"tuf_{kind}_" + uuid4().hex for kind in ("release", "target")}
    admin = create_engine(url, hide_parameters=True)
    with admin.begin() as connection:
        for name in schemas.values():
            connection.execute(text(f'CREATE SCHEMA "{name}"'))
    engines = {
        kind: create_engine(
            url, connect_args={"options": f"-csearch_path={name}"}, hide_parameters=True
        )
        for kind, name in schemas.items()
    }
    try:
        yield engines
    finally:
        for engine in engines.values():
            engine.dispose()
        with admin.begin() as connection:
            for name in schemas.values():
                connection.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
        admin.dispose()


@needs_opa
def test_signed_roles_work_on_postgresql_with_locked_version_counters(
    tmp_path, key, catalog, store, clock, postgres_schemas
):
    release, target = postgres_schemas["release"], postgres_schemas["target"]
    vendor = build_vendor(tmp_path, key, catalog, clock, database=release)
    updater = tuf_updater(tmp_path, key, vendor, store, clock, adoption=auto(), engine=target)
    assert updater.check().outcome == "adopted"
    clock.advance(hours=13)
    assert vendor.store.renew_if_due()
    assert updater.check().outcome == "unchanged"
    assert updater.status()["integrity"]["timestamp_version"] == 2
    second = ReleaseStore(release, key, clock=clock, role_keys=vendor.store.roles.keys)
    clock.advance(hours=13)
    assert second.renew_if_due() and not vendor.store.renew_if_due()
    versions = parse_metadata(vendor.store.signed_metadata().raw)
    assert versions.timestamp.version == 3
    assert "catalog_integrity_state" in inspect(target).get_table_names()
    assert {"catalog_role_root", "catalog_role_state"} <= set(inspect(release).get_table_names())
