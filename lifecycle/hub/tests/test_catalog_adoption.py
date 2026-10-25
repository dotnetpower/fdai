from __future__ import annotations

import asyncio
import hashlib
import json
import random
import shutil
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.contracts import canonical_bytes
from pydantic import ValidationError
from sqlalchemy import create_engine
from starlette.testclient import TestClient

from fdai_lifecycle_hub.adoption_policy import (
    AdoptionConfig,
    evaluate_policy,
    policy_input,
    summarize_change,
)
from fdai_lifecycle_hub.api import create_app
from fdai_lifecycle_hub.catalog_adoption import (
    CandidateChangedError,
    CatalogUpdater,
    run_periodic,
)
from fdai_lifecycle_hub.catalog_import import (
    export_signing_message,
    load_pinned_export,
    verify_export_signature,
)
from fdai_lifecycle_hub.migrations import migrate
from fdai_lifecycle_hub.remote import RemoteConfig, target_routes
from fdai_lifecycle_hub.remote_catalog import (
    CatalogSource,
    FetchedExport,
    RemoteCatalog,
    fetch_signed_export,
    initialize_trust,
)
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_release_hub.api import create_app as create_release_app
from fdai_release_hub.store import Change, ReleaseStore

needs_opa = pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary not on PATH")
START = datetime(2026, 10, 5, 3, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def vendor(tmp_path, key, catalog, clock) -> ReleaseStore:
    store = ReleaseStore(tmp_path / "vendor.db", key, clock=clock)
    publish(store, catalog, "1.5.0", clock)
    return store


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


def pem(key: HubSigningKey) -> str:
    return key.public_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()


def source_for(key, **adoption) -> CatalogSource:
    return CatalogSource(
        url="https://release.example.com/v1/catalog/export",
        access="anonymous",
        release_public_key=pem(key),
        adoption=AdoptionConfig(**adoption),
    )


def auto(**extra):
    return {
        "mode": "auto",
        "allowed_channels": ("DEV",),
        "authorized_by": "customer-owner",
        "authorization_expires_at": "2026-12-01T00:00:00+00:00",
        **extra,
    }


def fetch_from(vendor, *, mutate=None):
    def fetch(source, *, accepted_digest=None):
        signed = vendor.signed_export()
        if accepted_digest == signed.digest:
            return None
        raw, signature = signed.raw, signed.signature
        if mutate is not None:
            raw, signature = mutate(raw, signature)
        return FetchedExport(raw, signature, signed.key_id)

    return fetch


def updater_for(tmp_path, key, vendor, store, clock, *, adoption, fetch=None, **kwargs):
    source = source_for(key, **adoption)
    engine = create_engine(f"sqlite:///{tmp_path / 'trust.db'}")
    migrate(engine, "lifecycle_hub", lambda c: initialize_trust(c, source))
    catalog = RemoteCatalog(engine, source, fetch_signed=fetch or fetch_from(vendor))
    return CatalogUpdater(catalog, store, key, clock=clock, **kwargs)


def test_export_signature_binds_exact_bytes_and_is_domain_separated(vendor, key):
    signed = vendor.signed_export()
    public = key.public_key
    assert verify_export_signature(signed.raw, signed.signature, public)
    assert not verify_export_signature(signed.raw + b" ", signed.signature, public)
    assert not verify_export_signature(signed.raw, None, public)
    assert not verify_export_signature(signed.raw, "not base64!", public)
    other = HubSigningKey(Ed25519PrivateKey.generate(), 1)
    assert not verify_export_signature(signed.raw, signed.signature, other.public_key)
    # A signature over the bare bytes cannot stand in for the domain-separated message.
    import base64

    bare = base64.b64encode(key.sign(signed.raw)).decode()
    assert not verify_export_signature(signed.raw, bare, public)
    assert export_signing_message(signed.raw).startswith(b"fdai.catalog-export.v1\n")


def test_release_export_is_cached_by_revision_and_supports_conditional_reads(
    vendor, catalog, clock, monkeypatch
):
    calls = []
    original = vendor.export
    monkeypatch.setattr(vendor, "export", lambda *a, **k: calls.append(1) or original(*a, **k))
    app = create_release_app(vendor)
    client = TestClient(app, base_url="http://127.0.0.1:8091", client=("127.0.0.1", 50001))
    first = client.get("/v1/catalog/export")
    assert first.status_code == 200
    assert verify_export_signature(
        first.content, first.headers["x-fdai-export-signature"], vendor.key.public_key
    )
    assert first.headers["x-fdai-export-key-id"] == vendor.key.key_id
    again = client.get("/v1/catalog/export", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and again.content == b""
    weak = client.get("/v1/catalog/export", headers={"If-None-Match": "W/" + first.headers["etag"]})
    assert weak.status_code == 304
    assert len(calls) == 1
    publish(vendor, catalog, "1.6.0", clock)
    changed = client.get("/v1/catalog/export", headers={"If-None-Match": first.headers["etag"]})
    assert changed.status_code == 200 and changed.content != first.content
    assert len(calls) == 2


def test_timestamp_renewal_only_extends_reviewed_content(vendor, clock):
    before = vendor.signed_export()
    assert vendor.renew_if_due() is False
    clock.advance(hours=13)
    assert vendor.renew_if_due() is True
    after = vendor.signed_export()
    assert after.revision == before.revision + 1
    before_doc, after_doc = json.loads(before.raw), json.loads(after.raw)
    assert after_doc["releases"] == before_doc["releases"]
    assert after_doc["channels"] == before_doc["channels"]
    assert after_doc["recalls"] == before_doc["recalls"]
    assert after_doc["expires_at"] > before_doc["expires_at"]
    assert vendor.renew_if_due() is False
    event = vendor.snapshot()["events"][0]
    assert event["action"] == "renew" and event["actor"] == "system:timestamp-renewal"


@needs_opa
def test_policy_adopts_first_import_and_freshness_then_recalls_nothing_else(
    tmp_path, key, catalog, store, clock, vendor
):
    updater = updater_for(tmp_path, key, vendor, store, clock, adoption=auto())
    first = updater.check()
    assert (first.outcome, first.detail) == ("adopted", "policy_allow")
    assert updater.catalog.status()["imported"] is True
    assert updater.check().outcome == "unchanged"
    clock.advance(hours=13)
    vendor.renew_if_due()
    renewed = updater.check()
    assert renewed.outcome == "adopted"
    assert renewed.candidate["change"]["added_releases"] == []
    events = [event["action"] for event in updater.catalog.recent_events(20)]
    assert events.count("catalog.imported") == 2
    actors = {event["actor"] for event in updater.catalog.recent_events(20)}
    assert actors == {"policy:catalog-adoption"}


@needs_opa
def test_new_release_in_allowed_channel_adopts_and_disallowed_channel_waits_for_review(
    tmp_path, key, catalog, store, clock, vendor
):
    updater = updater_for(tmp_path, key, vendor, store, clock, adoption=auto())
    assert updater.check().outcome == "adopted"
    publish(vendor, catalog, "1.6.0", clock)
    assert updater.check().outcome == "adopted"
    clock.advance(minutes=5)
    vendor.change(
        "contribute",
        "1.6.0",
        Change(
            revision=vendor.snapshot()["revision"],
            confirmation="1.6.0",
            reason="Synthetic promotion",
            channel="RELEASE",
        ),
    )
    held = updater.check()
    assert held.outcome == "review_required"
    assert "channel_not_allowed:RELEASE" in held.candidate["decision"]["reasons"]
    accepted_before = updater.catalog.status()["accepted_sha256"]
    assert updater.check().outcome == "review_required"
    reviews = [
        e for e in updater.catalog.recent_events(20) if e["action"] == "check.review_required"
    ]
    assert len(reviews) == 1
    assert updater.catalog.status()["accepted_sha256"] == accepted_before
    with pytest.raises(CandidateChangedError):
        updater.apply(revision=held.candidate["revision"], sha256="0" * 64, actor="operator-oid")
    applied = updater.apply(
        revision=held.candidate["revision"], sha256=held.candidate["sha256"], actor="operator-oid"
    )
    assert applied.outcome == "adopted" and applied.detail == "operator_review"
    last = updater.catalog.recent_events(2)
    assert {event["actor"] for event in last} == {"operator-oid"}
    assert updater.check().outcome == "unchanged"


@needs_opa
def test_review_mode_and_expired_standing_authorization_never_adopt_automatically(
    tmp_path, key, store, clock, vendor
):
    review = updater_for(tmp_path, key, vendor, store, clock, adoption={})
    held = review.check()
    assert held.outcome == "review_required"
    assert "adoption_mode_review" in held.candidate["decision"]["reasons"]
    assert review.catalog.status()["imported"] is False
    (tmp_path / "other").mkdir()
    expired = updater_for(
        tmp_path / "other",
        key,
        vendor,
        store,
        clock,
        adoption=auto(authorization_expires_at="2026-10-05T03:00:30+00:00"),
    )
    clock.advance(minutes=1)
    outcome = expired.check()
    assert outcome.outcome == "review_required"
    assert outcome.candidate["decision"]["reasons"] == ["standing_authorization_expired"]


@pytest.mark.parametrize(
    ("mutate", "detail"),
    [
        (lambda raw, sig: (raw, None), "signature_missing"),
        (lambda raw, sig: (raw + b" ", sig), "signature_invalid"),
        (lambda raw, sig: (raw, "AAAA"), "signature_invalid"),
    ],
)
@needs_opa
def test_unsigned_or_tampered_candidates_never_change_trust(
    tmp_path, key, store, clock, vendor, mutate, detail
):
    updater = updater_for(
        tmp_path,
        key,
        vendor,
        store,
        clock,
        adoption=auto(),
        fetch=fetch_from(vendor, mutate=mutate),
    )
    outcome = updater.check()
    if detail == "signature_invalid" and outcome.detail == "candidate_invalid":
        detail = "candidate_invalid"  # trailing bytes already break the pinned digest/JSON
    assert outcome.outcome == "failed" and outcome.detail == detail
    assert updater.catalog.status()["imported"] is False
    with pytest.raises(ValueError):
        updater.apply(revision=1, sha256="0" * 64, actor="operator-oid")


@needs_opa
def test_candidate_signed_by_another_key_is_rejected(tmp_path, key, store, clock, vendor):
    forger = HubSigningKey(Ed25519PrivateKey.generate(), 1)

    def resign(raw, signature):
        import base64

        return raw, base64.b64encode(forger.sign(export_signing_message(raw))).decode()

    updater = updater_for(
        tmp_path,
        key,
        vendor,
        store,
        clock,
        adoption=auto(),
        fetch=fetch_from(vendor, mutate=resign),
    )
    outcome = updater.check()
    assert (outcome.outcome, outcome.detail) == ("failed", "signature_invalid")
    assert updater.catalog.status()["imported"] is False


@needs_opa
def test_rollback_and_expired_candidates_are_rejected(tmp_path, key, catalog, store, clock, vendor):
    updater = updater_for(tmp_path, key, vendor, store, clock, adoption=auto())
    old = vendor.signed_export()
    assert updater.check().outcome == "adopted"
    publish(vendor, catalog, "1.6.0", clock)
    assert updater.check().outcome == "adopted"
    replay = FetchedExport(old.raw, old.signature, old.key_id)
    updater.catalog.fetch_signed = lambda source, **_: replay
    assert updater.check().detail == "candidate_invalid"
    clock.advance(days=3)
    updater.catalog.fetch_signed = fetch_from(vendor, mutate=None)
    updater.catalog.fetch_signed = lambda source, **_: FetchedExport(
        vendor.signed_export().raw, vendor.signed_export().signature, "k"
    )
    assert updater.check().detail in {"candidate_invalid", "digest_already_accepted"}


def test_missing_policy_engine_denies_and_waits_for_review(tmp_path, key, store, clock, vendor):
    updater = updater_for(
        tmp_path,
        key,
        vendor,
        store,
        clock,
        adoption=auto(),
        evaluate=lambda document: evaluate_policy(document, opa_binary="missing-opa-binary"),
    )
    outcome = updater.check()
    assert outcome.outcome == "review_required"
    assert outcome.candidate["decision"]["reasons"] == ["policy_engine_unavailable"]
    assert updater.catalog.status()["imported"] is False


def test_policy_failures_deny_without_raising(monkeypatch):
    import subprocess

    document = {"anything": True}
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/opa")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("opa", 1)

    monkeypatch.setattr(subprocess, "run", timeout)
    assert evaluate_policy(document).reasons == ("policy_evaluation_failed",)

    class Completed:
        returncode = 0
        stdout = b'{"result":[{"expressions":[{"value":{"allow":true,"reasons":["x"]}}]}]}'

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Completed())
    assert evaluate_policy(document).reasons == ("policy_result_invalid",)
    Completed.stdout = b"not json"
    assert evaluate_policy(document).reasons == ("policy_evaluation_failed",)
    Completed.returncode = 2
    assert evaluate_policy(document).reasons == ("policy_evaluation_failed",)


@needs_opa
def test_policy_reasons_cover_every_risky_change(catalog):
    base = ReleaseCatalogFactory(catalog)
    config = AdoptionConfig(**auto())
    previous = base(["1.4.0"], {"DEV": ["1.4.0"]})
    candidate = base(["1.5.0"], {"DEV": ["1.5.0"], "RELEASE": ["1.5.0"], "custom-x": ["1.5.0"]})
    change = summarize_change(previous, candidate)
    assert change["removed_releases"] == ["1.4.0"]
    assert change["new_channels"] == ["RELEASE", "custom-x"]
    assert {item["channel"] for item in change["channel_additions"]} == {
        "DEV",
        "RELEASE",
        "custom-x",
    }
    document = policy_input(
        config=config,
        change=change,
        baseline_present=True,
        signature_verified=False,
        now=START,
    )
    reasons = set(evaluate_policy(document).reasons)
    assert {
        "signature_not_verified",
        "release_removed",
        "new_channel",
        "channel_membership_removed",
        "channel_not_allowed:RELEASE",
        "channel_not_allowed:custom-x",
    } <= reasons
    quiet = policy_input(
        config=config,
        change=summarize_change(candidate, candidate),
        baseline_present=True,
        signature_verified=True,
        now=START,
    )
    assert evaluate_policy(quiet).allow is True
    many = ReleaseCatalogFactory(catalog)(
        ["1.4.0", "1.5.0", "1.6.0"], {"DEV": ["1.4.0", "1.5.0", "1.6.0"]}
    )
    over = policy_input(
        config=AdoptionConfig(**auto(max_new_releases=1)),
        change=summarize_change(base([], {}), many),
        baseline_present=True,
        signature_verified=True,
        now=START,
    )
    assert "too_many_new_releases" in evaluate_policy(over).reasons


def ReleaseCatalogFactory(catalog):  # noqa: N802 - small test factory
    from fdai_lifecycle_hub.catalog import ReleaseCatalog

    def build(ids, channels):
        return ReleaseCatalog(
            releases={release_id: catalog.releases[release_id] for release_id in ids},
            channels={name: frozenset(members) for name, members in channels.items()},
        )

    return build


@needs_opa
def test_adoption_issues_plans_for_every_enrolled_installation_without_applying(
    tmp_path, key, catalog, installation, store, enroll, clock, vendor
):
    enroll(store, installation)
    updater = updater_for(tmp_path, key, vendor, store, clock, adoption=auto())
    record = updater.check()
    assert record.outcome == "adopted"
    assert [item["installation_id"] for item in record.plans] == ["installation-alpha"]
    assert record.plans[0]["outcome"] != "error"


def test_updates_routes_report_check_and_review_flow(
    tmp_path, key, catalog, store, clock, vendor, monkeypatch
):
    monkeypatch.setattr("fdai_lifecycle_hub.remote.utc_now", clock)
    updater = updater_for(tmp_path, key, vendor, store, clock, adoption={})
    app = create_app(store)
    app.routes[0:0] = target_routes(store, updater.catalog, key, updater=updater)
    with TestClient(app) as client:
        status = client.get("/v1/catalog/updates").json()
        assert status["mode"] == "review" and status["accepted"] is None
        checked = client.post("/v1/catalog/updates/check").json()
        candidate = checked["candidate"]
        assert checked["outcome"] == "review_required"
        wrong = client.post(
            "/v1/catalog/updates/apply",
            json={"revision": candidate["revision"], "sha256": "0" * 64},
        )
        assert wrong.status_code == 409 and wrong.json() == {"error": "candidate_changed"}
        invalid = client.post("/v1/catalog/updates/apply", json={"revision": -1, "sha256": "x"})
        assert invalid.status_code == 422
        ok = client.post(
            "/v1/catalog/updates/apply",
            json={"revision": candidate["revision"], "sha256": candidate["sha256"]},
        )
        assert ok.status_code == 200 and ok.json()["outcome"] == "adopted"
        after = client.get("/v1/catalog/updates").json()
        assert after["accepted"]["revision"] == candidate["revision"]
        assert after["accepted"]["release_count"] == 1
        assert client.get("/v1/catalog/releases").status_code == 200


def test_periodic_runner_backs_off_after_failures_and_survives_crashes():
    class Updater:
        interval_seconds = 3600
        outcomes = ["failed", "failed", "boom", "adopted"]

        def check(self):
            outcome = self.outcomes.pop(0)
            if outcome == "boom":
                raise RuntimeError("synthetic")
            return type("Record", (), {"outcome": outcome})()

    delays = []

    async def sleep(seconds):
        delays.append(seconds)
        if len(delays) >= 6:
            raise asyncio.CancelledError

    async def run():
        with pytest.raises(asyncio.CancelledError):
            await run_periodic(Updater(), sleep=sleep, rng=random.Random(1), jitter=0)  # noqa: S311

    asyncio.run(run())
    assert 5 <= delays[0] <= 30
    assert delays[1:] == [60, 120, 240, 3600, 60]
    disabled = type("Updater", (), {"interval_seconds": 0})()
    asyncio.run(run_periodic(disabled, sleep=sleep))


def test_configuration_boundaries_fail_closed(key):
    with pytest.raises(ValidationError):
        AdoptionConfig(mode="auto")
    with pytest.raises(ValidationError):
        AdoptionConfig(
            mode="auto", authorized_by="o", authorization_expires_at="2026-12-01T00:00:00"
        )
    with pytest.raises(ValidationError):
        AdoptionConfig(allowed_channels=("bad channel",))
    with pytest.raises(ValueError, match="five minutes"):
        source_for(key).model_copy(update={"check_interval_seconds": 60}).validate_source()
    with pytest.raises(ValueError, match="Anonymous"):
        CatalogSource(
            url="https://release.example.com/v1/catalog/export",
            access="anonymous",
            token_scope="api://x/.default",
            release_public_key=pem(key),
        )
    with pytest.raises(ValueError, match="Managed Identity"):
        CatalogSource(
            url="https://release.example.com/v1/catalog/export", release_public_key=pem(key)
        )
    base = {
        "kind": "release",
        "origin": "https://hub.example.com",
        "timestamp_renewal_check_seconds": 600,
    }
    assert RemoteConfig.model_validate_json(json.dumps(base)).timestamp_renewal_check_seconds == 600
    for invalid in (
        base | {"kind": "target"},
        base | {"timestamp_renewal_check_seconds": 30},
    ):
        with pytest.raises(ValueError):
            RemoteConfig.model_validate_json(json.dumps(invalid))


@pytest.mark.parametrize("mode", ["current", "changed", "unsigned"])
def test_signed_poll_is_conditional_anonymous_and_bounded(monkeypatch, key, mode):
    from contextlib import contextmanager

    seen = {}

    @contextmanager
    def stream(method, url, **kwargs):
        seen.update(kwargs["headers"])
        response = httpx.Response(
            304 if mode == "current" else 200,
            headers=(
                {"X-FDAI-Export-Signature": "c2ln", "X-FDAI-Export-Key-Id": "hub-1"}
                if mode == "changed"
                else {}
            ),
            stream=httpx.ByteStream(b"" if mode == "current" else b"catalog"),
        )
        try:
            yield response
        finally:
            response.close()

    monkeypatch.setattr(httpx, "stream", stream)
    result = fetch_signed_export(source_for(key), accepted_digest="a" * 64)
    assert "Authorization" not in seen and seen["If-None-Match"] == f'"{"a" * 64}"'
    if mode == "current":
        assert result is None
    elif mode == "changed":
        assert (result.raw, result.signature, result.key_id) == (b"catalog", "c2ln", "hub-1")
    else:
        assert result.signature is None and result.raw == b"catalog"


def test_unconditional_poll_does_not_send_validators(monkeypatch, key):
    from contextlib import contextmanager

    seen = {}

    @contextmanager
    def stream(method, url, **kwargs):
        seen.update(kwargs["headers"])
        response = httpx.Response(304, stream=httpx.ByteStream(b""))
        try:
            yield response
        finally:
            response.close()

    monkeypatch.setattr(httpx, "stream", stream)
    with pytest.raises(ValueError, match="successful export"):
        fetch_signed_export(source_for(key))
    assert "If-None-Match" not in seen


def test_signed_digest_matches_legacy_pin(vendor, key, now):
    signed = vendor.signed_export()
    assert signed.digest == hashlib.sha256(signed.raw).hexdigest()
    catalog = load_pinned_export(
        signed.raw,
        expected_sha256=signed.digest,
        public_key=key.public_key,
        now=START + timedelta(minutes=10),
    )
    assert set(catalog.releases) == {"1.5.0"}
