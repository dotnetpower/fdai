"""Plan-bound Hub artifact download with installation-local verified caching."""

from __future__ import annotations

from pathlib import Path

from fdai_lifecycle_agent.hub_client import HttpHubClient
from fdai_lifecycle_agent.inputs import (
    ArtifactStore,
    DirectoryArtifactStore,
    InputKind,
    SignedArtifact,
    stage_artifact,
    validate_artifact,
)
from fdai_lifecycle_agent.signatures import ArtifactVerifier


class CachedHubArtifactStore(ArtifactStore):
    """Fetch an absent Plan artifact once, verify it, and reuse its exact private bytes."""

    def __init__(
        self,
        root: Path,
        hub: HttpHubClient,
        installation_id: str,
        *,
        release_verifier: ArtifactVerifier,
        configuration_verifier: ArtifactVerifier,
    ) -> None:
        self._root = root
        self._local = DirectoryArtifactStore(root)
        self._hub = hub
        self._installation_id = installation_id
        self._verifiers = {
            "release": release_verifier,
            "configuration": configuration_verifier,
        }

    def load(self, kind: InputKind, digest: str) -> SignedArtifact | None:
        try:
            cached = self._local.load(kind, digest)
            if cached is not None:
                validate_artifact(kind, digest, cached, self._verifiers[kind])
                return cached
        except ValueError:
            # A bounded, Plan-pinned fetch may repair corrupt or interrupted cache bytes.
            pass
        artifact = self._hub.fetch_artifact(self._installation_id, kind, digest)
        if artifact is None:
            return None
        staged = SignedArtifact(artifact.payload, artifact.signature)
        stage_artifact(self._root, kind, digest, staged, self._verifiers[kind])
        persisted = self._local.load(kind, digest)
        if persisted is None:
            raise ValueError("Staged Hub artifact was not durably readable.")
        if persisted != staged:
            raise ValueError("Staged Hub artifact differs from the verified bytes.")
        return persisted


__all__ = ["CachedHubArtifactStore"]
