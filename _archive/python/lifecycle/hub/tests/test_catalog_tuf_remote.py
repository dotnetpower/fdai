"""Remote entry points and the offline ceremony for signed catalog roles."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from lifecycle.hub.tests.tuf_helpers import ident
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from fdai_lifecycle_hub import remote
from fdai_lifecycle_hub.catalog_integrity import IntegrityFloors, assess_roles
from fdai_lifecycle_hub.catalog_trust import (
    CatalogTrust,
    online_key_from_environment,
    parse_metadata,
)
from fdai_lifecycle_hub.signing import load_public_key
from fdai_release_hub.cli import main as release_cli
from fdai_release_hub.root_ceremony import main as ceremony


def pem(key: Ed25519PrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def run_ceremony(*arguments: object) -> int:
    return ceremony([str(item) for item in arguments])


@pytest.fixture
def holders(tmp_path: Path) -> Path:
    directory = tmp_path / "ceremony"
    assert run_ceremony("keygen", "--out-dir", directory, "--name", "root", "--count", 3) == 0
    for name in ("snapshot", "timestamp", "export"):
        assert run_ceremony("keygen", "--out-dir", directory, "--name", name) == 0
    return directory


def build_root(holders: Path, *, out: Path, version: int = 1, threshold: int = 2, **extra) -> int:
    roots = [holders / f"root-{index}.pub.pem" for index in (1, 2, 3)]
    return run_ceremony(
        "build",
        "--out",
        out,
        "--version",
        version,
        "--threshold",
        threshold,
        "--root-public",
        *roots,
        "--snapshot-public",
        holders / "snapshot-1.pub.pem",
        "--timestamp-public",
        holders / "timestamp-1.pub.pem",
        "--export-public",
        extra.get("export", holders / "export-1.pub.pem"),
    )


def test_ceremony_generates_private_keys_signs_with_a_threshold_and_verifies(
    holders: Path, tmp_path: Path, capsys
):
    for index in (1, 2, 3):
        mode = (holders / f"root-{index}.pem").stat().st_mode & 0o777
        assert mode == 0o600
    record = tmp_path / "root-v1.json"
    assert build_root(holders, out=record) == 0
    unsigned = json.loads(record.read_text())
    assert unsigned["signatures"] == {} and unsigned["version"] == 1
    assert run_ceremony("verify", "--record", record) == 1
    assert "catalog_root_signature_invalid" in capsys.readouterr().out
    assert run_ceremony("sign", "--record", record, "--key", holders / "root-1.pem") == 0
    assert run_ceremony("verify", "--record", record) == 1
    assert run_ceremony("sign", "--record", record, "--key", holders / "root-2.pem") == 0
    assert run_ceremony("verify", "--record", record) == 0
    assert '"verified": true' in capsys.readouterr().out
    signed = json.loads(record.read_text())
    assert len(signed["signatures"]) == 2
    assert "PRIVATE" not in record.read_text()


def test_ceremony_refuses_unsafe_inputs(holders: Path, tmp_path: Path, capsys):
    record = tmp_path / "root.json"
    assert build_root(holders, out=record) == 0
    assert build_root(holders, out=record) == 1  # never overwrites an existing record
    loose = holders / "root-1.pem"
    loose.chmod(0o640)
    assert run_ceremony("sign", "--record", record, "--key", loose) == 1
    loose.chmod(0o600)
    stranger = tmp_path / "stranger"
    assert run_ceremony("keygen", "--out-dir", stranger, "--name", "other") == 0
    assert run_ceremony("sign", "--record", record, "--key", stranger / "other-1.pem") == 1
    assert "not named" in capsys.readouterr().err
    assert build_root(holders, out=tmp_path / "high.json", threshold=4) == 1
    inside = Path(__file__).resolve().parents[3] / "ceremony-test-output"
    assert run_ceremony("keygen", "--out-dir", inside) == 2
    assert not inside.exists()


def test_rotation_needs_signatures_from_the_previous_holders(holders: Path, tmp_path: Path, capsys):
    first = tmp_path / "root-v1.json"
    assert build_root(holders, out=first) == 0
    keys = [holders / "root-1.pem", holders / "root-2.pem"]
    assert run_ceremony("sign", "--record", first, "--key", *keys) == 0
    successor = tmp_path / "next"
    assert run_ceremony("keygen", "--out-dir", successor, "--name", "new", "--count", 3) == 0
    second = tmp_path / "root-v2.json"
    roots = [successor / f"new-{index}.pub.pem" for index in (1, 2, 3)]
    assert (
        run_ceremony(
            "build",
            "--out",
            second,
            "--version",
            2,
            "--threshold",
            2,
            "--root-public",
            *roots,
            "--snapshot-public",
            holders / "snapshot-1.pub.pem",
            "--timestamp-public",
            holders / "timestamp-1.pub.pem",
            "--export-public",
            holders / "export-1.pub.pem",
        )
        == 0
    )
    new_keys = [successor / "new-1.pem", successor / "new-2.pem"]
    assert run_ceremony("sign", "--record", second, "--key", *new_keys) == 0
    assert run_ceremony("verify", "--record", second, "--previous", first) == 1
    assert "unsigned_by_previous" in capsys.readouterr().out
    assert run_ceremony("sign", "--record", second, "--key", *keys, "--previous", first) == 0
    assert run_ceremony("verify", "--record", second, "--previous", first) == 0


def test_local_release_hub_installs_a_ceremony_root_and_serves_it(
    holders: Path, tmp_path: Path, monkeypatch
):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    assert release_cli(["dev-init", str(state)]) == 0
    assert release_cli(["tuf-init", str(state)]) == 0
    with pytest.raises(SystemExit):
        release_cli(["tuf-init", str(state)])
    # The ceremony names this Hub's own online and export public keys.
    record = tmp_path / "root.json"
    roots = [holders / f"root-{index}.pub.pem" for index in (1, 2, 3)]
    assert (
        run_ceremony(
            "build",
            "--out",
            record,
            "--version",
            1,
            "--threshold",
            2,
            "--root-public",
            *roots,
            "--snapshot-public",
            state / "snapshot.pub.pem",
            "--timestamp-public",
            state / "timestamp.pub.pem",
            "--export-public",
            state / "development.pub.pem",
        )
        == 0
    )
    keys = [holders / "root-1.pem", holders / "root-3.pem"]
    assert run_ceremony("sign", "--record", record, "--key", *keys) == 0
    assert release_cli(["install-root", str(state), "--root", str(record)]) == 0
    with pytest.raises(SystemExit):
        release_cli(["install-root", str(state)])
    pin = CatalogTrust(
        mode="tuf",
        root_key_ids=tuple(ident_of(path) for path in roots),
        root_threshold=2,
    )
    captured = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.append(app))
    assert release_cli(["serve", str(state)]) == 0
    assert "/v1/catalog/metadata" in {route.path for route in captured[0].routes}
    client = TestClient(captured[0], base_url="http://127.0.0.1:8091", client=("127.0.0.1", 1))
    served = parse_metadata(client.get("/v1/catalog/metadata").content)
    verdict = assess_roles(
        served, trust=pin, floors=IntegrityFloors(), now=datetime.now(UTC) + timedelta(minutes=1)
    )
    assert verdict.verified, verdict.reason_code


def ident_of(path: Path) -> str:
    from fdai_lifecycle_hub.catalog_trust import key_id_of

    return key_id_of(load_public_key(path))


def test_the_remote_release_hub_installs_a_root_and_reads_role_keys_once(
    holders: Path, tmp_path: Path, monkeypatch
):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    monkeypatch.setattr(remote, "remote_engine", lambda _: engine)
    export, snapshot, timestamp = (Ed25519PrivateKey.generate() for _ in range(3))
    record = tmp_path / "root.json"
    key_dir = tmp_path / "online"
    key_dir.mkdir()
    pubs = {}
    for name, key in (("snapshot", snapshot), ("timestamp", timestamp), ("export", export)):
        path = key_dir / f"{name}.pub.pem"
        path.write_bytes(
            key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )
        pubs[name] = path
    roots = [holders / f"root-{index}.pub.pem" for index in (1, 2, 3)]
    assert (
        run_ceremony(
            "build",
            "--out",
            record,
            "--version",
            1,
            "--threshold",
            2,
            "--root-public",
            *roots,
            "--snapshot-public",
            pubs["snapshot"],
            "--timestamp-public",
            pubs["timestamp"],
            "--export-public",
            pubs["export"],
        )
        == 0
    )
    keys = [holders / "root-1.pem", holders / "root-2.pem"]
    assert run_ceremony("sign", "--record", record, "--key", *keys) == 0
    config = {
        "kind": "release",
        "origin": "https://release.example.com",
        "catalog_roles": {},
        "timestamp_renewal_check_seconds": 60,
    }
    monkeypatch.setenv("FDAI_HUB_REMOTE_CONFIG", json.dumps(config))
    monkeypatch.setattr(sys, "argv", ["remote", "migrate"])
    remote._run()

    def provision() -> None:
        monkeypatch.setenv("FDAI_HUB_DEVELOPMENT_SIGNING_KEY", pem(export))
        monkeypatch.setenv(remote.CATALOG_SNAPSHOT_KEY_ENV, pem(snapshot))
        monkeypatch.setenv(remote.CATALOG_TIMESTAMP_KEY_ENV, pem(timestamp))

    monkeypatch.setattr(
        sys, "argv", ["remote", "install-catalog-root", "--request", str(record), "--actor", "ops"]
    )
    monkeypatch.delenv(remote.CATALOG_SNAPSHOT_KEY_ENV, raising=False)
    with pytest.raises(ValueError, match="secret reference"):
        monkeypatch.setenv("FDAI_HUB_DEVELOPMENT_SIGNING_KEY", pem(export))
        remote._run()
    provision()
    remote._run()
    assert remote.CATALOG_SNAPSHOT_KEY_ENV not in os.environ
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM catalog_role_root")) == 1
    assert "catalog_role_state" in inspect(engine).get_table_names()
    # A role-less Release Hub or a Lifecycle Hub cannot install roots.
    monkeypatch.setenv(
        "FDAI_HUB_REMOTE_CONFIG",
        json.dumps({"kind": "release", "origin": "https://release.example.com"}),
    )
    provision()
    with pytest.raises(ValueError, match="requires a Release Hub with catalog roles"):
        remote._run()
    monkeypatch.setenv("FDAI_HUB_REMOTE_CONFIG", json.dumps(config))
    monkeypatch.setattr(sys, "argv", ["remote", "install-catalog-root", "--actor", "ops"])
    with pytest.raises(ValueError, match="one request source"):
        remote._run()
    # The operation Job passes the public root through its request environment variable.
    monkeypatch.setenv("SYNTHETIC_ROOT_REQUEST", record.read_text())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "remote",
            "install-catalog-root",
            "--request-env",
            "SYNTHETIC_ROOT_REQUEST",
            "--actor",
            "ops",
        ],
    )
    provision()
    with pytest.raises(ValueError, match="chain_invalid"):
        remote._run()
    assert "SYNTHETIC_ROOT_REQUEST" not in os.environ

    monkeypatch.setattr(sys, "argv", ["remote", "serve"])
    provision()
    captured = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.append(app))
    remote._run()
    assert "/v1/catalog/metadata" in {route.path for route in captured[0].routes}


def test_online_keys_come_from_a_secret_reference_that_is_read_once(monkeypatch):
    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv("SYNTHETIC_ROLE_KEY", pem(key))
    online = online_key_from_environment("SYNTHETIC_ROLE_KEY")
    assert online.key_id == ident(key)
    assert "SYNTHETIC_ROLE_KEY" not in os.environ
    with pytest.raises(ValueError, match="secret reference"):
        online_key_from_environment("SYNTHETIC_ROLE_KEY")
    monkeypatch.setenv("SYNTHETIC_ROLE_KEY", "not a key")
    with pytest.raises(ValueError):
        online_key_from_environment("SYNTHETIC_ROLE_KEY")
    monkeypatch.setenv("SYNTHETIC_ROLE_KEY", "")
    with pytest.raises(ValueError, match="secret reference"):
        online_key_from_environment("SYNTHETIC_ROLE_KEY")
