from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest

from fdai_lifecycle_hub.operations import ReleasePublicationRequest, publish_release
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_release_hub.store import ReleaseStore


def _manifest(*, image: str = "b") -> dict[str, object]:
    return {
        "schema_version": "fdai.application-release.v2",
        "product": "fdai",
        "release_version": "1.0.0",
        "source_commit": "a" * 40,
        "platform_tag": "linux-x86_64",
        "components": {
            "operator-service": {"image_digest": "sha256:" + image * 64},
        },
    }


def _request(manifest: dict[str, object]) -> ReleasePublicationRequest:
    return ReleasePublicationRequest(
        schema_version="fdai.release-publication-request.v1",
        request_id=str(uuid4()),
        release_id="1.0.0",
        manifest=canonical_bytes(manifest).decode(),
        manifest_digest=canonical_digest(manifest),
        channels=("DEV", "RELEASE_CANDIDATE"),
        reason="Verified development publication",
        confirmation="publish 1.0.0 to DEV,RELEASE_CANDIDATE",
    )


def test_trusted_publication_converges_and_reuses_exact_release(tmp_path: Path) -> None:
    key = HubSigningKey(Ed25519PrivateKey.generate(), epoch=1)
    store = ReleaseStore(tmp_path / "release.db", key)
    request = _request(_manifest())
    now = datetime(2026, 10, 24, tzinfo=UTC)

    first = publish_release(store.engine, key, request, actor="operator", now=now)
    repeated = publish_release(store.engine, key, request, actor="operator", now=now)

    assert first["catalog_revision"] == 3
    assert first["channels"] == ["DEV", "RELEASE_CANDIDATE"]
    assert first["mutation_performed"] is True
    assert repeated["catalog_revision"] == first["catalog_revision"]
    assert repeated["catalog_sha256"] == first["catalog_sha256"]
    assert repeated["mutation_performed"] is False


def test_trusted_publication_never_reuses_a_release_id_for_changed_bytes(
    tmp_path: Path,
) -> None:
    key = HubSigningKey(Ed25519PrivateKey.generate(), epoch=1)
    store = ReleaseStore(tmp_path / "release.db", key)
    now = datetime(2026, 10, 24, tzinfo=UTC)
    publish_release(store.engine, key, _request(_manifest()), actor="operator", now=now)

    with pytest.raises(ValueError, match="differs"):
        publish_release(
            store.engine,
            key,
            _request(_manifest(image="c")),
            actor="operator",
            now=now,
        )
