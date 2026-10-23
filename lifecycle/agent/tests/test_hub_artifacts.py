from __future__ import annotations

from pathlib import Path
from typing import cast

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest

from fdai_lifecycle_agent.hub_artifacts import CachedHubArtifactStore
from fdai_lifecycle_agent.hub_client import FetchedArtifact, HttpHubClient
from fdai_lifecycle_agent.inputs import SignedArtifact
from fdai_lifecycle_agent.signatures import Ed25519ArtifactVerifier


class _Hub:
    def __init__(self, artifact: FetchedArtifact) -> None:
        self.artifact = artifact
        self.calls = 0

    def fetch_artifact(self, installation_id: str, kind: str, digest: str) -> FetchedArtifact:
        assert installation_id == "installation-alpha"
        assert kind == "release"
        assert digest == canonical_digest({"schema_version": "example.v1"})
        self.calls += 1
        return self.artifact


def test_verified_hub_artifact_is_cached_with_exact_bytes(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    payload = canonical_bytes({"schema_version": "example.v1"})
    artifact = FetchedArtifact(payload, key.sign(payload))
    expected = SignedArtifact(artifact.payload, artifact.signature)
    hub = _Hub(artifact)
    verifier = Ed25519ArtifactVerifier(key.public_key())
    store = CachedHubArtifactStore(
        tmp_path / "cache",
        cast(HttpHubClient, hub),
        "installation-alpha",
        release_verifier=verifier,
        configuration_verifier=verifier,
    )
    digest = canonical_digest({"schema_version": "example.v1"})

    assert store.load("release", digest) == expected
    assert store.load("release", digest) == expected
    assert hub.calls == 1
    assert (tmp_path / "cache/releases" / f"{digest}.json").read_bytes() == payload
