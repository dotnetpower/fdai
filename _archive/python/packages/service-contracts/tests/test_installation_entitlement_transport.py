import json
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from fdai_service_contracts.installation_entitlement_transport import (
    MAX_ENTITLEMENT_CARRIER_BYTES,
    MAX_ENTITLEMENT_TOKEN_BYTES,
    EntitlementRecipient,
    EntitlementTransportError,
    entitlement_recipient,
    seal_entitlement_token,
    unseal_entitlement_token,
)


def binding(key: X25519PrivateKey) -> EntitlementRecipient:
    return entitlement_recipient(
        key.public_key(), installation_binding="a" * 64, deployment_binding="b" * 64
    )


@pytest.mark.parametrize("size", [1, MAX_ENTITLEMENT_TOKEN_BYTES])
def test_original_bytes_round_trip_without_verifying_or_granting_a_license(size: int) -> None:
    key = X25519PrivateKey.generate()
    recipient = binding(key)
    token = b"x" * size
    carrier = seal_entitlement_token(token, recipient=recipient, public_key=key.public_key())
    assert len(carrier) < MAX_ENTITLEMENT_CARRIER_BYTES
    assert unseal_entitlement_token(carrier, recipient=recipient, private_key=key) == token
    assert b'"token"' not in carrier


def test_resealing_the_same_original_token_creates_independent_ciphertext_only() -> None:
    key = X25519PrivateKey.generate()
    recipient = binding(key)
    first = seal_entitlement_token(
        b"untrusted-original", recipient=recipient, public_key=key.public_key()
    )
    second = seal_entitlement_token(
        b"untrusted-original", recipient=recipient, public_key=key.public_key()
    )
    assert first != second
    assert unseal_entitlement_token(first, recipient=recipient, private_key=key) == (
        unseal_entitlement_token(second, recipient=recipient, private_key=key)
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "fdai.configuration-container.v2"),
        ("purpose", "fdai.configuration.v1"),
        ("installation_binding", "c" * 64),
        ("deployment_binding", "d" * 64),
        ("recipient_fingerprint", "e" * 64),
        ("ephemeral_public_key", "A" * 43),
        ("nonce", "A" * 16),
        ("ciphertext", "A" * 24),
    ],
)
def test_authenticated_header_and_ciphertext_cannot_be_changed(field: str, value: str) -> None:
    key = X25519PrivateKey.generate()
    recipient = binding(key)
    carrier = seal_entitlement_token(
        b"original-token", recipient=recipient, public_key=key.public_key()
    )
    document = json.loads(carrier)
    document[field] = value
    changed = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(EntitlementTransportError):
        unseal_entitlement_token(changed, recipient=recipient, private_key=key)


def test_a_different_key_cannot_borrow_the_recipient_identity() -> None:
    key = X25519PrivateKey.generate()
    other = X25519PrivateKey.generate()
    recipient = binding(key)
    carrier = seal_entitlement_token(b"token", recipient=recipient, public_key=key.public_key())
    with pytest.raises(EntitlementTransportError):
        seal_entitlement_token(b"token", recipient=recipient, public_key=other.public_key())
    with pytest.raises(EntitlementTransportError):
        unseal_entitlement_token(carrier, recipient=recipient, private_key=other)
    with pytest.raises(EntitlementTransportError):
        unseal_entitlement_token(
            carrier,
            recipient=replace(recipient, deployment_binding="c" * 64),
            private_key=key,
        )


@pytest.mark.parametrize("token", [b"", b"x" * (MAX_ENTITLEMENT_TOKEN_BYTES + 1)])
def test_plaintext_byte_bounds_precede_encryption(token: bytes) -> None:
    key = X25519PrivateKey.generate()
    with pytest.raises(EntitlementTransportError):
        seal_entitlement_token(token, recipient=binding(key), public_key=key.public_key())


@pytest.mark.parametrize(
    "carrier",
    [
        b"",
        b"{}",
        b"x" * (MAX_ENTITLEMENT_CARRIER_BYTES + 1),
        b'{"purpose":"one","purpose":"two"}',
        b'{"purpose":null}',
        b"[]",
    ],
)
def test_invalid_or_oversized_carriers_are_rejected_before_decryption(carrier: bytes) -> None:
    key = X25519PrivateKey.generate()
    with pytest.raises(EntitlementTransportError):
        unseal_entitlement_token(carrier, recipient=binding(key), private_key=key)


def test_noncanonical_whitespace_and_duplicate_members_are_rejected() -> None:
    key = X25519PrivateKey.generate()
    recipient = binding(key)
    carrier = seal_entitlement_token(b"token", recipient=recipient, public_key=key.public_key())
    with pytest.raises(EntitlementTransportError):
        unseal_entitlement_token(b" " + carrier, recipient=recipient, private_key=key)
    document = json.loads(carrier)
    repeated = (
        b'{"purpose":'
        + json.dumps(document["purpose"]).encode()
        + b","
        + carrier.removeprefix(b"{")
    )
    with pytest.raises(EntitlementTransportError):
        unseal_entitlement_token(repeated, recipient=recipient, private_key=key)
