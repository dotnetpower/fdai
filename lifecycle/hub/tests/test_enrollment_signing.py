from __future__ import annotations

from datetime import datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.lifecycle_enrollment import sign_enrollment_payload

from fdai_lifecycle_hub import schemas
from fdai_lifecycle_hub.signing import installation_key_id, raw_public_key


def test_hub_signing_uses_the_shared_canonical_enrollment_bytes(
    enrollment_template: dict[str, object], installation_key: Ed25519PrivateKey, now: datetime
) -> None:
    request = schemas.sign_enrollment(enrollment_template, installation_key, now)

    payload, proof = sign_enrollment_payload(enrollment_template, installation_key, now)

    assert (request.signed_payload, request.proof) == (payload, proof)
    assert request.installation_key_id == installation_key_id(raw_public_key(installation_key))
