"""The one canonical installation enrollment signing implementation.

The Lifecycle Hub's offline `sign-enrollment` and the Lifecycle Agent's online `enroll` both build
the signed request here, so the two cannot drift: the Hub verifies exactly these bytes.
"""

from __future__ import annotations

import hashlib
from base64 import b64encode
from collections.abc import Mapping
from datetime import datetime, timedelta

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fdai_deployment_cli.contracts import canonical_bytes

# The Hub rejects a proof whose request time differs from its clock by more than this.
ENROLLMENT_PROOF_WINDOW = timedelta(minutes=5)


def raw_installation_public_key(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def installation_key_id(public_key: bytes) -> str:
    """The id an approver compares with the key the installation shows out of band."""

    return "installation-" + hashlib.sha256(public_key).hexdigest()[:16]


def sign_enrollment_payload(
    template: Mapping[str, object], key: Ed25519PrivateKey, at: datetime
) -> tuple[bytes, bytes]:
    """Add the installation key and `at` to `template`, and return the payload and its proof."""

    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("requested_at must be timezone-aware")
    fields = {
        "installation_key": b64encode(raw_installation_public_key(key)).decode("ascii"),
        "requested_at": at.isoformat(),
    }
    payload = canonical_bytes({**template, **fields})
    return payload, key.sign(payload)
