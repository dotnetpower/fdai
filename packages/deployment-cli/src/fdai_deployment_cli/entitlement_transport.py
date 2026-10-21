"""Private offline carrier output; sealing original bytes grants no entitlement."""

from __future__ import annotations

import argparse
import hashlib
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
from fdai_service_contracts.installation_entitlement_transport import (
    MAX_ENTITLEMENT_TOKEN_BYTES,
    EntitlementTransportError,
    entitlement_recipient,
    seal_entitlement_token,
)

from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes


def seal_entitlement_command(args: argparse.Namespace) -> int:
    """Seal one existing private token to separately supplied recipient material."""
    token = read_private_bytes(args.token, max_bytes=MAX_ENTITLEMENT_TOKEN_BYTES)
    public = serialization.load_pem_public_key(
        read_private_bytes(args.recipient_public_key, max_bytes=16_384)
    )
    if not isinstance(public, X25519PublicKey):
        raise EntitlementTransportError("entitlement transport requires an X25519 recipient key")
    recipient = entitlement_recipient(
        public,
        installation_binding=args.installation_binding,
        deployment_binding=args.deployment_binding,
    )
    carrier = seal_entitlement_token(token, recipient=recipient, public_key=public)
    write_private_bytes(args.destination, carrier)
    print(
        json.dumps(
            {
                "schema_version": "fdai.entitlement-carrier-output.v1",
                "carrier_digest": hashlib.sha256(carrier).hexdigest(),
                "recipient_fingerprint": recipient.fingerprint,
                "execution_authority": False,
                "license_verified": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0
