from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.contracts import canonical_digest

from fdai_lifecycle_agent.inputs import (
    DirectoryArtifactStore,
    InputKind,
    SignedArtifact,
    stage_artifact,
)
from fdai_lifecycle_agent.signatures import Ed25519ArtifactVerifier
from fdai_lifecycle_agent.state import AgentState, LocalStateStore

if TYPE_CHECKING:
    from conftest import Harness


def test_staging_preserves_signed_bytes_and_permissions(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    payload = b'{"region": "koreacentral"}\n'
    digest = canonical_digest({"region": "koreacentral"})
    artifact = SignedArtifact(payload, key.sign(payload))
    stage_artifact(
        tmp_path, "configuration", digest, artifact, Ed25519ArtifactVerifier(key.public_key())
    )
    assert DirectoryArtifactStore(tmp_path).load("configuration", digest) == artifact
    for path in (tmp_path / "configurations").iterdir():
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("fault", ["tamper", "digest", "signature", "large"])
def test_bad_input_never_publishes(tmp_path: Path, fault: str) -> None:
    key = Ed25519PrivateKey.generate()
    payload = b'{"region":"koreacentral"}'
    signature = key.sign(payload)
    digest = canonical_digest({"region": "koreacentral"})
    if fault == "tamper":
        payload += b" "
    elif fault == "digest":
        digest = "0" * 64
    elif fault == "signature":
        signature = b""
    else:
        payload = b"x" * (1024 * 1024 + 1)
    with pytest.raises(ValueError):
        stage_artifact(
            tmp_path,
            "configuration",
            digest,
            SignedArtifact(payload, signature),
            Ed25519ArtifactVerifier(key.public_key()),
        )
    assert list(tmp_path.iterdir()) == []


def test_replay_floor_survives_fresh_os_process(tmp_path: Path) -> None:
    store = LocalStateStore(tmp_path / "state")
    with store.lock():
        store.save(AgentState(last_accepted_sequence=42))
    script = (
        "import sys; from pathlib import Path; "
        "from fdai_lifecycle_agent.state import LocalStateStore; "
        "store=LocalStateStore(Path(sys.argv[1])); "
        "assert store.load().last_accepted_sequence == 42"
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter and test-owned code
        [sys.executable, "-c", script, str(tmp_path / "state")],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(path for path in sys.path if path)},
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("tamper", [False, True])
def test_staged_inputs_are_reverified_during_real_admission(
    harness: Harness,
    tmp_path: Path,
    tamper: bool,
) -> None:
    harness.serve(harness.plan())
    kinds: tuple[InputKind, ...] = ("release", "configuration")
    for kind in kinds:
        artifacts = harness.store.releases if kind == "release" else harness.store.configurations
        key = harness.release_key if kind == "release" else harness.configuration_key
        for digest, artifact in artifacts.items():
            stage_artifact(
                tmp_path, kind, digest, artifact, Ed25519ArtifactVerifier(key.public_key())
            )
    if tamper:
        path = next((tmp_path / "configurations").glob("*.json"))
        path.write_bytes(path.read_bytes() + b" ")
    result = harness.poll(artifact_store=DirectoryArtifactStore(tmp_path))
    assert result.outcome == ("rejected" if tamper else "dry-run-admitted")
    if tamper:
        assert result.reason_code == "configuration_signature_invalid"
