from __future__ import annotations

import hashlib
import json
from base64 import b64decode, b64encode
from datetime import UTC, datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_enrollment import (
    installation_key_id,
    raw_installation_public_key,
    sign_enrollment_payload,
)

AT = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


def test_payload_is_canonical_and_the_proof_verifies_over_exactly_those_bytes() -> None:
    key = Ed25519PrivateKey.generate()
    template = {"installation_id": "alpha", "settings": {"channel": "stable"}}

    payload, proof = sign_enrollment_payload(template, key, AT)

    raw = raw_installation_public_key(key)
    assert payload == canonical_bytes(
        template | {"installation_key": raw_b64(raw), "requested_at": AT.isoformat()}
    )
    key.public_key().verify(proof, payload)
    assert sign_enrollment_payload(template, key, AT) == (payload, proof)


def test_key_id_is_a_stable_digest_prefix_of_the_raw_public_key() -> None:
    raw = raw_installation_public_key(Ed25519PrivateKey.generate())

    assert installation_key_id(raw) == "installation-" + hashlib.sha256(raw).hexdigest()[:16]


def test_the_installation_key_and_time_override_the_template() -> None:
    key = Ed25519PrivateKey.generate()
    other = raw_b64(raw_installation_public_key(Ed25519PrivateKey.generate()))

    payload, _ = sign_enrollment_payload(
        {"installation_key": other, "requested_at": "2000-01-01T00:00:00+00:00"}, key, AT
    )

    assert b64decode(json.loads(payload)["installation_key"]) == raw_installation_public_key(key)
    assert AT.isoformat().encode() in payload


@pytest.mark.parametrize("at", [datetime(2026, 10, 25, 9, 0), datetime(2026, 10, 25)])
def test_requested_at_must_be_timezone_aware(at: datetime) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        sign_enrollment_payload({}, Ed25519PrivateKey.generate(), at)


def test_a_non_utc_offset_is_preserved_in_the_signed_time() -> None:
    zone = timezone(timedelta(hours=9))

    payload, _ = sign_enrollment_payload(
        {}, Ed25519PrivateKey.generate(), datetime(2026, 10, 25, 18, 0, tzinfo=zone)
    )

    assert b"2026-10-25T18:00:00+09:00" in payload


def raw_b64(raw: bytes) -> str:
    return b64encode(raw).decode("ascii")
