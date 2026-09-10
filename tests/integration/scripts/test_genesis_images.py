"""Exact-main container image binding regressions for supervised Genesis."""

from __future__ import annotations

import io
import sys
from email.message import Message
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_images  # noqa: E402

SOURCE = "a" * 40
DIGEST = "sha256:" + "b" * 64


class _Response(io.BytesIO):
    def __init__(self, payload: bytes = b"", *, digest: str | None = None) -> None:
        super().__init__(payload)
        self.headers = Message()
        if digest is not None:
            self.headers["Docker-Content-Digest"] = digest


def test_resolve_exact_images_binds_digest_and_verifies_every_attestation(monkeypatch) -> None:
    requests = []
    verified = []

    def open_request(request):
        requests.append(request)
        if request.full_url.startswith("https://ghcr.io/token?"):
            return _Response(b'{"token":"registry-token"}')
        return _Response(digest=DIGEST)

    monkeypatch.setattr(genesis_images, "_github_token", lambda: "github-token")
    monkeypatch.setattr(
        genesis_images,
        "_verify_attestation",
        lambda repository, source, reference: verified.append((repository, source, reference)),
    )

    result = genesis_images.resolve_exact_images("example/fdai", SOURCE, opener=open_request)

    assert set(result) == {
        "fdai-core-control-plane",
        "fdai-operator-service",
        "fdai-document-ingestion-api",
    }
    assert all(reference.endswith("@" + DIGEST) for reference in result.values())
    assert [item[2] for item in verified] == list(result.values())
    assert sum(request.get_method() == "HEAD" for request in requests) == 3


def test_resolve_exact_images_rejects_unbound_manifest_digest(monkeypatch) -> None:
    def open_request(request):
        if request.full_url.startswith("https://ghcr.io/token?"):
            return _Response(b'{"token":"registry-token"}')
        return _Response(digest="latest")

    monkeypatch.setattr(genesis_images, "_github_token", lambda: "github-token")

    try:
        genesis_images.resolve_exact_images("example/fdai", SOURCE, opener=open_request)
    except ValueError as exc:
        assert "digest is invalid" in str(exc)
    else:
        raise AssertionError("an invalid registry digest must fail closed")
