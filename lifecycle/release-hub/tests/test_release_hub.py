from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_promotion import (
    CanaryObservation,
    PromotionStageCriteria,
)
from starlette.testclient import TestClient

from fdai_lifecycle_hub.catalog_import import load_pinned_export
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_release_hub.api import MAX_CATALOG_VIEW_BYTES, create_app
from fdai_release_hub.cli import main
from fdai_release_hub.store import (
    CapabilityChange,
    CatalogConfirmation,
    CatalogError,
    Change,
    ReleaseStore,
)

NOW = datetime(2026, 10, 15, 13, tzinfo=UTC)
SAMPLES = Path(__file__).resolve().parents[2] / "hub" / "samples" / "catalog" / "releases"


@pytest.fixture
def store(tmp_path: Path) -> ReleaseStore:
    return ReleaseStore(
        tmp_path / "catalog.db", HubSigningKey(Ed25519PrivateKey.generate(), 1), clock=lambda: NOW
    )


@pytest.fixture
def client(store: ReleaseStore) -> TestClient:
    return TestClient(
        create_app(store), base_url="http://127.0.0.1:8091", client=("127.0.0.1", 50001)
    )


def change(store: ReleaseStore, action: str, release_id: str = "1.6.0", **fields: object) -> None:
    payload = {
        "revision": store.snapshot()["revision"],
        "confirmation": release_id,
        "reason": "Local test review",
        **fields,
    }
    store.change(action, release_id, Change.model_validate(payload))


def publish(store: ReleaseStore) -> None:
    change(store, "register", manifest=(SAMPLES / "1.6.0.json").read_text(), label="검토 릴리스")
    change(store, "publish")


def admit(store: ReleaseStore, **fields: object):
    raw, digest = store.export()
    return load_pinned_export(
        raw, expected_sha256=digest, public_key=store.key.public_key, now=NOW, **fields
    )


@pytest.mark.parametrize("port", ["0", "65536", "not-a-port"])
def test_cli_rejects_invalid_ports_before_opening_state(tmp_path: Path, port: str) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["serve", str(tmp_path / "missing"), "--port", port])
    assert raised.value.code == 2


def test_cli_rejects_non_directory_and_uninitialized_state(tmp_path: Path) -> None:
    state_file = tmp_path / "state-file"
    state_file.write_text("not a directory")
    with pytest.raises(SystemExit) as raised:
        main(["dev-init", str(state_file)])
    assert raised.value.code == 2
    missing = tmp_path / "missing"
    with pytest.raises(SystemExit) as raised:
        main(["serve", str(missing)])
    assert raised.value.code == 2
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    with pytest.raises(SystemExit) as raised:
        main(["serve", str(private)])
    assert raised.value.code == 2


def test_cli_requires_private_state_and_refuses_key_reinitialization(tmp_path: Path) -> None:
    exposed = tmp_path / "exposed"
    exposed.mkdir(mode=0o755)
    exposed.chmod(0o755)
    with pytest.raises(SystemExit) as raised:
        main(["dev-init", str(exposed)])
    assert raised.value.code == 2
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    assert main(["dev-init", str(private)]) == 0
    with pytest.raises(SystemExit) as raised:
        main(["dev-init", str(private)])
    assert raised.value.code == 2


def test_registration_publication_contribution_recall_and_restart(store: ReleaseStore) -> None:
    publish(store)
    change(store, "contribute", channel="RELEASE_CANDIDATE")
    change(store, "contribute", channel="RELEASE")
    catalog = admit(store)
    assert catalog.channels["RELEASE"] == frozenset({"1.6.0"})
    assert not catalog.recalls
    change(store, "recall")
    reopened = ReleaseStore(store.path, store.key, clock=lambda: NOW)
    snapshot = reopened.snapshot()
    assert snapshot["revision"] == 5
    assert snapshot["releases"][0]["state"] == "recalled"
    assert snapshot["releases"][0]["label"] == "검토 릴리스"
    assert admit(reopened).recalls[0].target == "1.6.0"
    assert len(snapshot["events"]) == 5


def test_custom_channel_creation_is_attributed_durable_and_changes_the_pin(store: ReleaseStore):
    publish(store)
    original, old_pin = store.export()
    change(store, "contribute", channel="custom-pilot", channel_confirmation="custom-pilot")
    reopened = ReleaseStore(store.path, store.key, clock=lambda: NOW)
    snapshot = reopened.snapshot()
    assert list(snapshot["channels"])[:3] == ["DEV", "RELEASE_CANDIDATE", "RELEASE"]
    assert snapshot["channels"]["custom-pilot"] == ["1.6.0"]
    assert snapshot["events"][0]["channel"] == "custom-pilot"
    assert snapshot["events"][0]["actor"] == "local-operator"
    assert snapshot["events"][0]["reason"] == "Local test review"
    assert admit(reopened).channels["custom-pilot"] == frozenset({"1.6.0"})
    assert reopened.export()[1] != old_pin
    with pytest.raises(ValueError, match="digest"):
        load_pinned_export(
            reopened.export()[0], expected_sha256=old_pin, public_key=store.key.public_key, now=NOW
        )
    assert (
        load_pinned_export(
            original, expected_sha256=old_pin, public_key=store.key.public_key, now=NOW
        ).channels.get("custom-pilot")
        is None
    )


@pytest.mark.parametrize(
    "channel",
    [
        "",
        "custom-",
        "custom-Pilot",
        "custom-a--b",
        "custom-a-",
        "custom- a",
        "custom-a\n",
        " custom-a",
        "development",
        "dev",
        "CUSTOM-a",
        "custom-\u200ba",
    ],
)
def test_custom_channel_names_fail_without_creating_membership(store, channel):
    publish(store)
    before = store.snapshot()
    with pytest.raises(CatalogError, match="channel"):
        change(store, "contribute", channel=channel, channel_confirmation=channel)
    assert store.snapshot() == before


@pytest.mark.parametrize(
    "fields",
    [
        {"channel_confirmation": None},
        {"channel_confirmation": "custom-other"},
        {"confirmation": "1.5.0"},
        {"revision": 0},
        {"reason": "   "},
    ],
)
def test_custom_channel_confirmation_and_revision_are_independent(store, fields):
    publish(store)
    before = store.snapshot()
    with pytest.raises(CatalogError):
        change(
            store,
            "contribute",
            **({"channel": "custom-pilot", "channel_confirmation": "custom-pilot"} | fields),
        )
    assert store.snapshot() == before


def test_custom_channel_membership_keeps_draft_recall_and_duplicate_holds(store):
    change(store, "register", manifest=(SAMPLES / "1.6.0.json").read_text())
    custom = {"channel": "custom-pilot", "channel_confirmation": "custom-pilot"}
    with pytest.raises(CatalogError, match="Publish"):
        change(store, "contribute", **custom)
    change(store, "publish")
    change(store, "contribute", **custom)
    before = store.snapshot()
    with pytest.raises(CatalogError, match="already belongs"):
        change(store, "contribute", **custom)
    assert store.snapshot() == before
    change(store, "recall")
    before = store.snapshot()
    with pytest.raises(CatalogError, match="Recalled"):
        change(store, "contribute", channel="custom-other", channel_confirmation="custom-other")
    assert store.snapshot() == before


def test_custom_channel_maximum_and_typed_input_boundary(store, client):
    publish(store)
    channel = "custom-" + "a" * 57
    change(store, "contribute", channel=channel, channel_confirmation=channel)
    assert channel in admit(store).channels
    before = store.snapshot()
    response = client.post(
        "/v1/releases/1.6.0/contribute",
        json={
            "revision": 3,
            "confirmation": "1.6.0",
            "reason": "Reviewed custom destination",
            "channel": channel + "a",
            "channel_confirmation": channel + "a",
        },
    )
    assert response.status_code == 422
    assert store.snapshot() == before


def test_custom_channel_requires_attributed_actor(store):
    publish(store)
    before = store.snapshot()
    with pytest.raises(CatalogError, match="attributed operator"):
        store.change(
            "contribute",
            "1.6.0",
            Change(
                revision=2,
                confirmation="1.6.0",
                reason="Reviewed destination",
                channel="custom-pilot",
                channel_confirmation="custom-pilot",
            ),
            actor="   ",
        )
    assert store.snapshot() == before


def test_custom_channel_audit_failure_rolls_back_membership(store, monkeypatch):
    publish(store)
    before = store.snapshot()

    def fail_audit(*args, **kwargs):
        raise CatalogError("Synthetic audit rejection", 503)

    monkeypatch.setattr(store, "_record_event", fail_audit)
    with pytest.raises(CatalogError, match="audit"):
        change(store, "contribute", channel="custom-pilot", channel_confirmation="custom-pilot")
    assert store.snapshot() == before


@pytest.mark.parametrize(
    "action,fields",
    [
        ("publish", {}),
        ("contribute", {"channel": "RELEASE"}),
        ("recall", {}),
    ],
)
def test_recall_blocks_future_mutation(store: ReleaseStore, action: str, fields: dict) -> None:
    publish(store)
    change(store, "recall")
    with pytest.raises(CatalogError, match="Recalled"):
        change(store, action, **fields)
    assert store.snapshot()["revision"] == 3


def test_revision_conflict_and_confirmation_do_not_mutate(store: ReleaseStore) -> None:
    publish(store)
    for fields in ({"revision": 0}, {"confirmation": "another-id"}):
        with pytest.raises(CatalogError):
            change(store, "recall", **fields)
    assert store.snapshot()["revision"] == 2


def test_duplicate_registration_and_contribution_are_explicit_conflicts(
    store: ReleaseStore,
) -> None:
    publish(store)
    with pytest.raises(CatalogError, match="cannot be reused"):
        change(store, "register", manifest=(SAMPLES / "1.6.0.json").read_text())
    with pytest.raises(CatalogError, match="already belongs"):
        change(store, "contribute", channel="DEV")
    assert store.snapshot()["revision"] == 2


def test_actor_attribution_preserves_existing_recall_notice_and_export_pins(store):
    publish(store)
    change(store, "recall")
    snapshot = store.snapshot()
    original, digest = store.export_snapshot(snapshot)
    for event in snapshot["events"]:
        assert event["actor"] == "local-operator"
        del event["actor"]
    assert store.export_snapshot(snapshot) == (original, digest)
    assert store.snapshot()["revision"] == 3


@pytest.mark.parametrize("release_id", ["../x", "1.0", "01.0.0", "1.0.0+build"])
def test_release_id_validation(store: ReleaseStore, release_id: str) -> None:
    with pytest.raises(CatalogError, match="SemVer"):
        change(store, "register", release_id)


def test_invalid_manifest_and_unsigned_contribution_fail_closed(store: ReleaseStore) -> None:
    with pytest.raises(ValueError):
        change(store, "register", manifest="{}")
    change(store, "register", manifest=(SAMPLES / "1.6.0.json").read_text())
    with pytest.raises(CatalogError, match="Publish"):
        change(store, "contribute", channel="RELEASE")
    assert admit(store).releases == {}


def test_export_pin_signature_expiry_and_revision_boundaries(store: ReleaseStore) -> None:
    publish(store)
    raw, digest = store.export()
    common = {"expected_sha256": digest, "public_key": store.key.public_key, "now": NOW}
    with pytest.raises(ValueError, match="digest"):
        load_pinned_export(raw + b" ", **common)
    with pytest.raises(ValueError, match="expired"):
        load_pinned_export(raw, **{**common, "now": NOW + timedelta(days=1)})
    with pytest.raises(ValueError, match="backwards"):
        load_pinned_export(raw, **common, minimum_revision=3)
    with pytest.raises(ValueError, match="without a new revision"):
        load_pinned_export(raw, **common, minimum_revision=2, previous_sha256="0" * 64)
    with pytest.raises(ValueError, match="signature"):
        load_pinned_export(
            raw, **{**common, "public_key": Ed25519PrivateKey.generate().public_key()}
        )
    forged = json.loads(raw)
    forged["releases"]["1.6.0"]["manifest"] += " "
    forged_raw = canonical_bytes(forged)
    with pytest.raises(ValueError, match="signature"):
        load_pinned_export(
            forged_raw, **{**common, "expected_sha256": hashlib.sha256(forged_raw).hexdigest()}
        )


def test_membership_and_recall_change_export_pin(store: ReleaseStore) -> None:
    publish(store)
    _, first = store.export()
    change(store, "contribute", channel="RELEASE")
    _, second = store.export()
    change(store, "recall")
    _, third = store.export()
    assert len({first, second, third}) == 3


def test_multi_release_export_above_one_mib_is_admitted(store: ReleaseStore) -> None:
    for release_id in ("1.5.0", "1.6.0"):
        manifest = (SAMPLES / f"{release_id}.json").read_text() + " " * 600_000
        change(store, "register", release_id, manifest=manifest)
        change(store, "publish", release_id)
    raw, _ = store.export()
    assert 1024 * 1024 < len(raw) < 8 * 1024 * 1024
    assert set(admit(store).releases) == {"1.5.0", "1.6.0"}


@pytest.mark.parametrize("extra_byte", [False, True])
def test_export_size_boundary(store: ReleaseStore, extra_byte: bool) -> None:
    publish(store)
    raw, _ = store.export()
    raw += b" " * (8 * 1024 * 1024 + int(extra_byte) - len(raw))
    arguments = {
        "expected_sha256": hashlib.sha256(raw).hexdigest(),
        "public_key": store.key.public_key,
        "now": NOW,
    }
    if extra_byte:
        with pytest.raises(ValueError, match="too large"):
            load_pinned_export(raw, **arguments)
    else:
        assert set(load_pinned_export(raw, **arguments).releases) == {"1.6.0"}


def test_oversized_export_rolls_back_publication_atomically(store: ReleaseStore) -> None:
    sample = (SAMPLES / "1.6.0.json").read_text()
    manifest = sample + " " * (950_000 - len(sample))
    revision = 0
    for patch in range(9):
        release_id = f"1.0.{patch}"
        result = store.change(
            "register",
            release_id,
            Change(
                revision=revision,
                confirmation=release_id,
                reason="Bounded catalog test",
                manifest=manifest,
            ),
        )
        revision = result["revision"]
        publication = Change(
            revision=revision,
            confirmation=release_id,
            reason="Bounded catalog test",
        )
        if patch == 8:
            with pytest.raises(CatalogError, match="8 MiB consumer limit"):
                store.change("publish", release_id, publication)
            break
        result = store.change("publish", release_id, publication)
        revision = result["revision"]
    with store.connect() as db:
        assert db.exec_driver_sql("SELECT count(*) FROM events").scalar_one() == 17
        assert db.exec_driver_sql("SELECT count(*) FROM membership").scalar_one() == 8
        assert (
            db.exec_driver_sql("SELECT signature FROM releases WHERE id='1.0.8'").scalar_one()
            is None
        )
    assert len(store.export()[0]) <= 8 * 1024 * 1024


def test_exact_signed_payload_and_canonical_digest_are_distinct(store: ReleaseStore) -> None:
    document = json.loads((SAMPLES / "1.6.0.json").read_text())
    raw = json.dumps(document, indent=4) + "\n"
    change(store, "register", manifest=raw)
    change(store, "publish")
    release = store.snapshot()["releases"][0]
    assert release["manifest"] == raw
    assert release["signed_payload_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert release["digest"] == hashlib.sha256(canonical_bytes(document)).hexdigest()
    assert release["digest"] != release["signed_payload_sha256"]
    assert admit(store).releases["1.6.0"].digest == release["digest"]
    with pytest.raises(ValueError, match="non-negative"):
        admit(store, minimum_revision=-1)


def test_static_ui_brand_and_unknown_api_routes(store: ReleaseStore, tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "brand").mkdir()
    (tmp_path / "index.html").write_text("<main>Release Hub</main>")
    (tmp_path / "brand" / "logo.svg").write_text("<svg/>")
    client = TestClient(
        create_app(store, static_dir=tmp_path),
        base_url="http://127.0.0.1:8091",
        client=("127.0.0.1", 50001),
    )
    assert client.get("/releases/1.6.0").text == "<main>Release Hub</main>"
    assert client.get("/brand/logo.svg").text == "<svg/>"
    assert client.get("/v1/unknown").status_code == 404
    assert "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]


def test_api_errors_origin_and_loopback_boundary(client: TestClient, store: ReleaseStore) -> None:
    assert client.get("/v1/catalog").json()["releases"] == []
    payload = {"revision": 0, "confirmation": "1.6.0", "reason": "Review"}
    assert client.post("/v1/releases/1.6.0/publish", json=payload).status_code == 404
    assert (
        client.post(
            "/v1/releases/1.6.0/register", json=payload, headers={"Origin": "https://example.com"}
        ).status_code
        == 403
    )
    assert client.post("/v1/releases/1.6.0/register", content="x").status_code == 415
    assert (
        client.post(
            "/v1/releases/1.6.0/register", content="{", headers={"Content-Type": "application/json"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/releases/1.6.0/register",
            content="x" * (2 * 1024 * 1024 + 1),
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )
    remote = TestClient(create_app(store), base_url="http://127.0.0.1", client=("192.0.2.1", 50001))
    assert remote.get("/v1/catalog").status_code == 403
    assert client.get("/v1/catalog", headers={"Host": "example.com"}).status_code == 400


def test_api_normalizes_json_media_type_and_rejects_encoded_bodies(client: TestClient) -> None:
    payload = {"revision": 0, "confirmation": "1.6.0", "reason": "Review"}
    accepted = client.post(
        "/v1/releases/1.6.0/publish",
        content=json.dumps(payload),
        headers={"Content-Type": " Application/JSON ; charset=utf-8"},
    )
    assert accepted.status_code == 404
    encoded = client.post(
        "/v1/releases/1.6.0/publish",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert encoded.status_code == 415
    assert encoded.json() == {"error": "Encoded request bodies are not supported."}


def test_api_stream_limit_rejects_chunked_body_without_buffering_past_limit(
    client: TestClient,
) -> None:
    chunks = iter((b"x" * (1024 * 1024), b"x" * (1024 * 1024), b"x"))
    response = client.post(
        "/v1/catalog/renew",
        content=chunks,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json() == {"error": "Request body is too large."}


def test_catalog_view_has_an_explicit_response_limit(
    client: TestClient, store: ReleaseStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = store.snapshot()
    snapshot["events"] = [
        {
            "revision": 0,
            "action": "register",
            "release_id": "1.0.0",
            "channel": None,
            "reason": "x" * MAX_CATALOG_VIEW_BYTES,
            "occurred_at": NOW.isoformat(),
            "actor": "local-operator",
        }
    ]
    monkeypatch.setattr(store, "snapshot", lambda: snapshot)
    response = client.get("/v1/catalog")
    assert response.status_code == 503
    assert response.json() == {"error": "Catalog view exceeds the 16 MiB service limit."}


@pytest.mark.parametrize(
    ("declared_length", "status", "message"),
    [
        ("invalid", 400, "Content-Length must be an integer."),
        ("-1", 400, "Content-Length cannot be negative."),
        (str(2 * 1024 * 1024 + 1), 413, "Request body is too large."),
    ],
)
def test_api_rejects_invalid_declared_body_lengths_before_parsing(
    client: TestClient, declared_length: str, status: int, message: str
) -> None:
    response = client.post(
        "/v1/catalog/renew",
        content="{}",
        headers={"Content-Type": "application/json", "Content-Length": declared_length},
    )
    assert response.status_code == status
    assert response.json() == {"error": message}


def test_api_real_mutation_readback_and_export(client: TestClient) -> None:
    payload = {
        "revision": 0,
        "confirmation": "1.6.0",
        "reason": "Reviewed metadata",
        "manifest": (SAMPLES / "1.6.0.json").read_text(),
    }
    assert (
        client.post(
            "/v1/releases/1.6.0/register", json=payload, headers={"Origin": "http://127.0.0.1:8091"}
        ).status_code
        == 200
    )
    payload.pop("manifest")
    payload["revision"] = 1
    assert client.post("/v1/releases/1.6.0/publish", json=payload).status_code == 200
    state = client.get("/v1/catalog").json()
    exported = client.get("/v1/catalog/export")
    assert hashlib.sha256(exported.content).hexdigest() == state["export_sha256"]
    assert state["releases"][0]["signature_status"] == "development-key-verified"
    assert exported.headers["cache-control"] == "no-store"


def test_corrupt_signature_is_unavailable_not_verified(
    client: TestClient, store: ReleaseStore
) -> None:
    publish(store)
    with store.connect() as db:
        db.exec_driver_sql("UPDATE releases SET signature='invalid'")
    response = client.get("/v1/catalog")
    assert response.status_code == 503
    assert "failed verification" in response.json()["error"]


@pytest.mark.parametrize(
    ("action", "fields"),
    [
        ("contribute", {"channel": "RELEASE_CANDIDATE"}),
        ("recall", {}),
    ],
)
def test_corrupt_signature_blocks_release_mutation_before_commit(
    store: ReleaseStore, action: str, fields: dict[str, str]
) -> None:
    publish(store)
    with store.connect() as db:
        db.exec_driver_sql("UPDATE releases SET signature='invalid'")
    attempted = Change(
        revision=2,
        confirmation="1.6.0",
        reason="Must not commit",
        **fields,
    )
    with pytest.raises(CatalogError, match="failed verification"):
        store.change(action, "1.6.0", attempted)
    with store.connect() as db:
        assert db.exec_driver_sql("SELECT count(*) FROM events").scalar_one() == 2
        assert db.exec_driver_sql("SELECT count(*) FROM membership").scalar_one() == 1
        assert db.exec_driver_sql("SELECT recalled_at FROM releases").scalar_one() is None


def test_corrupt_lifting_release_blocks_capability_lift_before_commit(store: ReleaseStore) -> None:
    publish(store)
    capability_id = "action:scale-service"
    store.change_capability(
        "recall",
        capability_id,
        CapabilityChange(
            revision=2,
            confirmation=capability_id,
            reason="Safety regression",
        ),
    )
    with store.connect() as db:
        db.exec_driver_sql("UPDATE releases SET signature='invalid'")
    with pytest.raises(CatalogError, match="failed verification"):
        store.change_capability(
            "lift",
            capability_id,
            CapabilityChange(
                revision=3,
                confirmation=capability_id,
                reason="Must not commit",
                lifting_release_id="1.6.0",
            ),
        )
    with store.connect() as db:
        assert db.exec_driver_sql("SELECT count(*) FROM events").scalar_one() == 3


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        ("UPDATE releases SET signature=NULL", "signature failed verification"),
        ("UPDATE releases SET published_at=NULL", "publication state is inconsistent"),
        (
            "UPDATE releases SET signature=NULL, published_at=NULL, "
            "recalled_at='2026-10-15T13:00:00+00:00'",
            "signature failed verification",
        ),
    ],
)
def test_inconsistent_publication_metadata_is_unavailable(
    store: ReleaseStore, statement: str, message: str
) -> None:
    publish(store)
    with store.connect() as db:
        db.exec_driver_sql(statement)
    with pytest.raises(CatalogError, match=message):
        store.snapshot()


def test_storage_failure_is_explicit_503(client: TestClient, store: ReleaseStore) -> None:
    store.path.unlink()
    response = client.get("/v1/catalog")
    assert response.status_code == 503
    assert response.json()["error"] == "Local storage is unavailable."


def test_expired_state_is_visible(store: ReleaseStore) -> None:
    publish(store)
    store.clock = lambda: NOW + timedelta(days=2)
    assert store.snapshot()["expired"]


def test_expired_renewal_preserves_content_and_requires_new_customer_pin(
    store: ReleaseStore, client: TestClient
) -> None:
    publish(store)
    change(store, "register", "1.5.0", manifest=(SAMPLES / "1.5.0.json").read_text())
    change(store, "publish", "1.5.0")
    change(store, "contribute", channel="RELEASE")
    change(store, "recall", "1.5.0")
    before = store.snapshot()
    old_raw, old_pin = store.export()
    later = NOW + timedelta(days=2)
    store.clock = lambda: later
    assert client.get("/v1/catalog").json()["expired"]
    assert client.get("/v1/catalog/export").content == old_raw
    assert store.snapshot()["revision"] == before["revision"]
    with pytest.raises(ValueError, match="expired"):
        load_pinned_export(
            old_raw, expected_sha256=old_pin, public_key=store.key.public_key, now=later
        )
    payload = {
        "revision": before["revision"],
        "confirmation": f"renew {before['revision']}",
        "reason": "Reviewed releases, channels and recalls",
    }
    response = client.post("/v1/catalog/renew", json=payload)
    assert response.status_code == 200
    after = response.json()
    assert after["revision"] == before["revision"] + 1
    assert not after["expired"]
    assert after["expires_at"] == (later + timedelta(hours=24)).isoformat()
    for field in ("releases", "channels", "key_id", "mode"):
        assert after[field] == before[field]
    assert after["events"][0] == {
        "revision": after["revision"],
        "action": "renew",
        "release_id": "catalog",
        "channel": None,
        "reason": payload["reason"],
        "occurred_at": later.isoformat(),
        "actor": "local-operator",
    }
    new_raw, new_pin = store.export()
    read_back = client.get("/v1/catalog").json()
    assert new_pin == read_back["export_sha256"] != old_pin
    assert read_back["revision"] == after["revision"]
    old_export, new_export = json.loads(old_raw), json.loads(new_raw)
    for field in old_export.keys() - {"revision", "expires_at"}:
        assert new_export[field] == old_export[field]
    with pytest.raises(ValueError, match="pin"):
        load_pinned_export(
            new_raw, expected_sha256=old_pin, public_key=store.key.public_key, now=later
        )
    accepted = load_pinned_export(
        new_raw,
        expected_sha256=new_pin,
        public_key=store.key.public_key,
        now=later,
        minimum_revision=before["revision"],
        previous_sha256=old_pin,
    )
    assert accepted.channels["RELEASE"] == frozenset({"1.6.0"})
    assert accepted.recalls[0].target == "1.5.0"
    reopened = ReleaseStore(store.path, store.key, clock=lambda: later)
    assert reopened.export() == (new_raw, new_pin)
    assert client.post("/v1/catalog/renew", json=payload).status_code == 409
    assert reopened.export() == (new_raw, new_pin)


@pytest.mark.parametrize(
    "fields,status",
    [
        ({"revision": 0, "confirmation": "renew 0"}, 409),
        ({"confirmation": "1.6.0"}, 422),
        ({"reason": "   "}, 422),
        ({"reason": "x" * 501}, 422),
        ({"revision": True}, 422),
        ({"manifest": "unexpected"}, 422),
        ({"actor": "forged"}, 422),
    ],
)
def test_invalid_renewal_is_unchanged(
    store: ReleaseStore, client: TestClient, fields: dict, status: int
) -> None:
    publish(store)
    store.clock = lambda: NOW + timedelta(days=2)
    before = store.export()
    payload = {"revision": 2, "confirmation": "renew 2", "reason": "Reviewed", **fields}
    assert client.post("/v1/catalog/renew", json=payload).status_code == status
    assert store.export() == before


@pytest.mark.parametrize("signature", ["invalid", "AAAA", "", None])
def test_renewal_rejects_corrupt_or_missing_signature_without_event(
    store: ReleaseStore, client: TestClient, signature: str | None
) -> None:
    publish(store)
    with store.connect() as db:
        db.exec_driver_sql("UPDATE releases SET signature=?", (signature,))
    store.clock = lambda: NOW + timedelta(days=2)
    response = client.post(
        "/v1/catalog/renew",
        json={"revision": 2, "confirmation": "renew 2", "reason": "Reviewed"},
    )
    assert response.status_code == 503
    assert "signature failed verification" in response.json()["error"]
    with store.connect() as db:
        assert db.exec_driver_sql("SELECT COUNT(*) FROM events").scalar_one() == 2
        assert db.exec_driver_sql("SELECT COUNT(*) FROM release_event_actor").scalar_one() == 2


@pytest.mark.parametrize("delta", [timedelta(0), timedelta(seconds=-1)])
def test_renewal_rejects_nonadvancing_clock(store: ReleaseStore, delta: timedelta) -> None:
    publish(store)
    before = store.export()
    store.clock = lambda: NOW + delta
    with pytest.raises(CatalogError, match="clock must advance"):
        store.renew(CatalogConfirmation(revision=2, confirmation="renew 2", reason="Reviewed"))
    assert store.export() == before


def test_concurrent_renewal_advances_once(store: ReleaseStore) -> None:
    publish(store)
    store.clock = lambda: NOW + timedelta(days=2)
    confirmation = CatalogConfirmation(revision=2, confirmation="renew 2", reason="Reviewed")

    def attempt() -> int:
        try:
            return int(store.renew(confirmation)["revision"])
        except CatalogError as error:
            assert error.status == 409
            return -1

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: attempt(), range(2))) == [-1, 3]
    assert store.snapshot()["revision"] == 3


def test_renewal_rejects_naive_clock(store: ReleaseStore) -> None:
    publish(store)
    before = store.export()
    store.clock = lambda: NOW.replace(tzinfo=None)
    with pytest.raises(CatalogError, match="clock must advance"):
        store.renew(CatalogConfirmation(revision=2, confirmation="renew 2", reason="Reviewed"))
    store.clock = lambda: NOW
    assert store.export() == before


@pytest.mark.parametrize("actor", ["", "   ", "x" * 161])
def test_renewal_requires_bounded_operator_attribution(store: ReleaseStore, actor: str) -> None:
    publish(store)
    store.clock = lambda: NOW + timedelta(days=2)
    before = store.export()
    with pytest.raises(CatalogError, match="attributed operator"):
        store.renew(
            CatalogConfirmation(revision=2, confirmation="renew 2", reason="Reviewed"),
            actor=actor,
        )
    assert store.export() == before


def test_renewal_origin_and_bounded_body(client: TestClient) -> None:
    payload = {"revision": 0, "confirmation": "renew 0", "reason": "Reviewed"}
    assert (
        client.post(
            "/v1/catalog/renew", json=payload, headers={"Origin": "https://other.example.com"}
        ).status_code
        == 403
    )
    assert client.post("/v1/catalog/renew", content="{}").status_code == 415
    assert (
        client.post(
            "/v1/catalog/renew",
            content="x" * (2 * 1024 * 1024 + 1),
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )


def test_capability_recall_blocks_repromotion_until_lifted_and_exports_records(
    store: ReleaseStore, client: TestClient
) -> None:
    for release_id in ("1.5.0", "1.6.0"):
        change(store, "register", release_id, manifest=(SAMPLES / f"{release_id}.json").read_text())
        change(store, "publish", release_id)
    rev = store.snapshot()["revision"]
    response = client.post(
        "/v1/capabilities/action:scale-service/recall",
        json={
            "revision": rev,
            "confirmation": "action:scale-service",
            "reason": "Safety regression in scale-service",
        },
    )
    assert response.status_code == 200
    rev = response.json()["revision"]
    # Duplicate active capability recall is rejected.
    assert (
        client.post(
            "/v1/capabilities/action:scale-service/recall",
            json={
                "revision": rev,
                "confirmation": "action:scale-service",
                "reason": "Duplicate recall",
            },
        ).status_code
        == 409
    )
    # Promoting either Release while its capability is actively recalled is blocked.
    for release_id in ("1.5.0", "1.6.0"):
        with pytest.raises(CatalogError, match="active recalled capability"):
            change(store, "contribute", release_id, channel="RELEASE_CANDIDATE")
    # Lifting with an unpublished Release is rejected.
    assert (
        client.post(
            "/v1/capabilities/action:scale-service/lift",
            json={
                "revision": rev,
                "confirmation": "action:scale-service",
                "reason": "Unpublished lift",
                "lifting_release_id": "1.9.0",
            },
        ).status_code
        == 409
    )
    # Lifting at 1.6.0 succeeds, keeps 1.5.0 blocked from promotion, and allows 1.6.0 promotion.
    lift_resp = client.post(
        "/v1/capabilities/action:scale-service/lift",
        json={
            "revision": rev,
            "confirmation": "action:scale-service",
            "reason": "Fixed in 1.6.0",
            "lifting_release_id": "1.6.0",
        },
    )
    assert lift_resp.status_code == 200
    with pytest.raises(CatalogError, match="active recalled capability"):
        change(store, "contribute", "1.5.0", channel="RELEASE_CANDIDATE")
    change(store, "contribute", "1.6.0", channel="RELEASE_CANDIDATE")
    admitted = admit(store)
    assert admitted.channels["RELEASE_CANDIDATE"] == frozenset({"1.6.0"})
    assert [(r.scope, r.target, r.action, r.lifting_release_id) for r in admitted.recalls] == [
        ("capability", "action:scale-service", "recall", None),
        ("capability", "action:scale-service", "lift", "1.6.0"),
    ]


def test_promotion_pipeline_enforces_labels_soak_canary_health_and_timeouts(
    store: ReleaseStore,
) -> None:
    publish(store)
    rc_stage = PromotionStageCriteria(
        source_channel="DEV",
        target_channel="RELEASE_CANDIDATE",
        required_labels=frozenset({"security-reviewed", "qa-passed"}),
        min_soak_seconds=3600,
        min_healthy_canaries=2,
        max_stage_timeout_seconds=7200,
    )
    rev = store.snapshot()["revision"]
    base_change = Change(revision=rev, confirmation="1.6.0", reason="Pipeline stage promotion")
    healthy_canaries = (
        CanaryObservation(
            installation_id="canary-1", release_id="1.6.0", healthy=True, soak_seconds=4000
        ),
        CanaryObservation(
            installation_id="canary-2", release_id="1.6.0", healthy=True, soak_seconds=3600
        ),
    )

    # 1. Missing required label is blocked.
    with pytest.raises(CatalogError, match="promotion_labels_missing"):
        store.promote_stage(
            "1.6.0",
            rc_stage,
            base_change,
            labels=frozenset({"security-reviewed"}),
            canary_observations=healthy_canaries,
            elapsed_stage_seconds=4000,
        )

    # 2. Unhealthy canary is blocked.
    with pytest.raises(CatalogError, match="promotion_canary_unhealthy"):
        store.promote_stage(
            "1.6.0",
            rc_stage,
            base_change,
            labels=frozenset({"security-reviewed", "qa-passed"}),
            canary_observations=(
                healthy_canaries[0],
                CanaryObservation(
                    installation_id="canary-2",
                    release_id="1.6.0",
                    healthy=False,
                    soak_seconds=4000,
                ),
            ),
            elapsed_stage_seconds=4000,
        )

    # 3. Insufficient soak time is blocked.
    with pytest.raises(CatalogError, match="promotion_soak_incomplete"):
        store.promote_stage(
            "1.6.0",
            rc_stage,
            base_change,
            labels=frozenset({"security-reviewed", "qa-passed"}),
            canary_observations=(
                healthy_canaries[0],
                CanaryObservation(
                    installation_id="canary-2",
                    release_id="1.6.0",
                    healthy=True,
                    soak_seconds=1800,
                ),
            ),
            elapsed_stage_seconds=4000,
        )

    # 4. Stage timeout exceeded is blocked.
    with pytest.raises(CatalogError, match="promotion_stage_timed_out"):
        store.promote_stage(
            "1.6.0",
            rc_stage,
            base_change,
            labels=frozenset({"security-reviewed", "qa-passed"}),
            canary_observations=healthy_canaries,
            elapsed_stage_seconds=7201,
        )

    # 5. All criteria satisfied advances 1.6.0 to RELEASE_CANDIDATE, then to RELEASE.
    store.promote_stage(
        "1.6.0",
        rc_stage,
        base_change,
        labels=frozenset({"security-reviewed", "qa-passed"}),
        canary_observations=healthy_canaries,
        elapsed_stage_seconds=4000,
    )
    release_stage = PromotionStageCriteria(
        source_channel="RELEASE_CANDIDATE",
        target_channel="RELEASE",
        required_labels=frozenset({"security-reviewed", "release-approved"}),
        min_soak_seconds=7200,
        min_healthy_canaries=2,
        max_stage_timeout_seconds=14400,
    )
    store.promote_stage(
        "1.6.0",
        release_stage,
        Change(
            revision=store.snapshot()["revision"],
            confirmation="1.6.0",
            reason="Promote to RELEASE",
        ),
        labels=frozenset({"security-reviewed", "release-approved"}),
        canary_observations=(
            CanaryObservation(
                installation_id="canary-1", release_id="1.6.0", healthy=True, soak_seconds=7500
            ),
            CanaryObservation(
                installation_id="canary-2", release_id="1.6.0", healthy=True, soak_seconds=7200
            ),
        ),
        elapsed_stage_seconds=7500,
    )
    admitted = admit(store)
    assert admitted.channels["RELEASE_CANDIDATE"] == frozenset({"1.6.0"})
    assert admitted.channels["RELEASE"] == frozenset({"1.6.0"})
