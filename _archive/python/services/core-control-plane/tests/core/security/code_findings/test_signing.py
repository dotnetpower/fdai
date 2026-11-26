"""Tests for pack signing: stdlib Ed25519 verification and DSSE envelopes."""

from __future__ import annotations

import base64
import json
import random

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fdai.core.security.code_findings import ed25519_verify
from fdai.core.security.code_findings.signing import build_envelope, verify_envelope


class _Signer:
    def __init__(self, key: Ed25519PrivateKey) -> None:
        self._key = key
        raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.key_id = ed25519_verify.key_id(raw)
        self.raw = raw

    def sign(self, message: bytes) -> bytes:
        return self._key.sign(message)


class _Verifier:
    def __init__(self, signer: _Signer) -> None:
        self._signer = signer

    def verify(self, message: bytes, signature: bytes, key_id: str) -> bool:
        return key_id == self._signer.key_id and ed25519_verify.verify(
            self._signer.raw, message, signature
        )


def test_stdlib_verifier_agrees_with_cryptography() -> None:
    rng = random.Random(7)  # noqa: S311 - deterministic test data, not cryptography
    for _ in range(8):
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        message = rng.randbytes(rng.randint(0, 300))
        signature = key.sign(message)
        assert ed25519_verify.verify(public, message, signature)
        assert not ed25519_verify.verify(public, message + b"x", signature)
        tampered = bytearray(signature)
        tampered[5] ^= 1
        assert not ed25519_verify.verify(public, message, bytes(tampered))


def test_public_key_parsing_accepts_pem_and_hex_only() -> None:
    key = Ed25519PrivateKey.generate().public_key()
    raw = key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    pem = key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    assert ed25519_verify.parse_public_key(pem) == raw
    assert ed25519_verify.parse_public_key(raw.hex()) == raw
    with pytest.raises(ValueError):
        ed25519_verify.parse_public_key(
            "-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----"
        )


def test_envelope_authenticates_exact_manifest_only() -> None:
    signer = _Signer(Ed25519PrivateKey.generate())
    manifest = b'{"pack_id": "abc"}\n'
    envelope = build_envelope(manifest, signer)
    assert verify_envelope(envelope, manifest, _Verifier(signer)) == signer.key_id
    assert verify_envelope(envelope, manifest + b" ", _Verifier(signer)) is None
    other = _Signer(Ed25519PrivateKey.generate())
    assert verify_envelope(envelope, manifest, _Verifier(other)) is None
    document = json.loads(envelope)
    document["payloadType"] = "application/json"
    assert verify_envelope(json.dumps(document).encode(), manifest, _Verifier(signer)) is None
    forged = build_envelope(b'{"pack_id": "evil"}\n', other)
    swapped = json.loads(forged)
    swapped["signatures"] = json.loads(envelope)["signatures"]
    assert (
        verify_envelope(
            json.dumps(swapped).encode(), base64.b64decode(swapped["payload"]), _Verifier(signer)
        )
        is None
    )
    assert verify_envelope(b"not json", manifest, _Verifier(signer)) is None
