"""Shared isolation for deployment CLI tests."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _restore_process_umask() -> Iterator[None]:
    """Keep the one-shot host checkpoint umask from leaking into later tests.

    ``standalone_host.main`` sets an owner-only umask for its own process. Tests call it in
    process, so restore the previous mask after each test instead of letting it change file
    modes that unrelated tests create later in the same worker.
    """
    previous = os.umask(0o022)
    os.umask(previous)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.fixture(autouse=True)
def _isolate_workstation_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep provision tests away from the real Azure CLI session and checkout key.

    Tests of the preflight itself call ``entitlement_preflight`` directly or restore
    the real functions on ``cli`` explicitly.
    """
    from fdai_deployment_cli import cli

    monkeypatch.setattr(cli, "select_entitlement_mode", lambda: "trial")
    monkeypatch.setattr(cli, "ensure_azure_session", lambda **_kwargs: None)


@pytest.fixture(autouse=True)
def _isolate_standalone_region_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep standalone package tests from reading Azure resource groups."""

    from fdai_deployment_cli import standalone_deploy
    from fdai_deployment_cli.azure_naming import azure_region_short_name

    monkeypatch.setattr(
        standalone_deploy,
        "selected_azure_region_short_name",
        lambda **kwargs: azure_region_short_name(str(kwargs["region"])),
    )


@pytest.fixture
def hub_image_catalog(tmp_path):
    import hashlib
    from base64 import b64encode
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from fdai_deployment_cli.contracts import canonical_bytes
    from fdai_deployment_cli.hub_image_trust import EXPORT_DOMAIN, INVENTORY

    tmp_path.chmod(0o700)
    key = Ed25519PrivateKey.generate()
    pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    manifest = {
        "schema_version": "fdai.application-release.v2",
        "product": "fdai",
        "release_version": "1.2.0",
        "source_commit": "a" * 40,
        "platform_tag": "linux-x86_64",
        "components": {
            name: {
                "image_digest": "sha256:" + hashlib.sha256(name.encode()).hexdigest(),
                "image_ref": f"registry.example.com/fdai/{name}@sha256:"
                + hashlib.sha256(name.encode()).hexdigest(),
            }
            for name in sorted(INVENTORY)
        },
    }
    document = {
        "revision": 4,
        "expires_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
        "releases": {},
        "channels": {"RELEASE": ["1.2.0"], "DEV": ["1.2.0"]},
        "recalls": [],
    }

    def export():
        manifest_bytes = canonical_bytes(manifest)
        document["releases"] = {
            "1.2.0": {
                "manifest": manifest_bytes.decode(),
                "signature": b64encode(key.sign(manifest_bytes)).decode(),
            }
        }
        raw = canonical_bytes(document)
        return raw, b64encode(key.sign(EXPORT_DOMAIN + raw)).decode()

    return SimpleNamespace(
        key=key, pem=pem, manifest=manifest, document=document, export=export, root=tmp_path
    )


@pytest.fixture
def hub_image_selection(hub_image_catalog):
    import hashlib

    from fdai_deployment_cli.hub_image_trust import (
        key_id,
        load_selection,
        selection_bytes,
        verify_export,
    )
    from fdai_deployment_cli.private_output import write_private_bytes

    catalog = hub_image_catalog
    raw, signature = catalog.export()
    selected = verify_export(
        raw,
        signature=signature,
        export_key_id=key_id(catalog.key.public_key()),
        trusted_pem=catalog.pem,
        channel="RELEASE",
    )
    content = selection_bytes(
        raw=raw,
        signature=signature,
        export_key_id=key_id(catalog.key.public_key()),
        pem=catalog.pem,
        hub_url="https://hub.example.com",
        channel="RELEASE",
        verified=selected,
    )
    path = catalog.root / "selection.json"
    write_private_bytes(path, content)
    return load_selection(path, hashlib.sha256(content).hexdigest())


@pytest.fixture
def hub_image_checkout(tmp_path):
    import subprocess

    root = tmp_path / "source"
    root.mkdir()
    for arguments in (
        ("init",),
        ("config", "user.email", "user@example.com"),
        ("config", "user.name", "Example"),
        ("config", "core.hooksPath", "/dev/null"),
    ):
        subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True)
    (root / "source.py").write_text("VALUE = 1\n")
    (root / ".gitignore").write_text(".cache/\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "fixture"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return root
