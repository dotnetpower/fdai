from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.contracts import canonical_bytes
from starlette.testclient import TestClient

from fdai_lifecycle_hub.catalog_import import load_pinned_export
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_release_hub.api import create_app
from fdai_release_hub.store import CatalogError, Change, ReleaseStore

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


def test_storage_failure_is_explicit_503(client: TestClient, store: ReleaseStore) -> None:
    store.path.unlink()
    response = client.get("/v1/catalog")
    assert response.status_code == 503
    assert response.json()["error"] == "Local storage is unavailable."


def test_expired_state_is_visible(store: ReleaseStore) -> None:
    publish(store)
    store.clock = lambda: NOW + timedelta(days=2)
    assert store.snapshot()["expired"]
