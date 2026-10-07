"""DSSE envelopes that bind a remediation-pack manifest to an FDAI signing key.

The envelope follows the Dead Simple Signing Envelope (DSSE) v1 pre-authentication encoding, so
the signature covers both the payload type and the exact manifest bytes. The manifest already
lists the SHA-256 digest of every other pack file, so one signature authenticates the whole pack.
The envelope ships next to the manifest as ``pack.manifest.dsse.json``.
"""

from __future__ import annotations

import base64
import binascii
import json

from fdai.shared.providers.remediation_pack import PackSignatureVerifier, PackSigner

ENVELOPE_PATH = "pack.manifest.dsse.json"
PAYLOAD_TYPE = "application/vnd.fdai.remediation-pack-manifest+json"
_MAX_ENVELOPE_BYTES = 2_000_000


def pre_authentication_encoding(payload_type: str, payload: bytes) -> bytes:
    """Return the DSSE v1 PAE bytes that a signature covers."""
    kind = payload_type.encode("utf-8")
    return b"DSSEv1 %d %s %d %s" % (len(kind), kind, len(payload), payload)


def build_envelope(manifest: bytes, signer: PackSigner) -> bytes:
    """Sign ``manifest`` and return the serialized envelope."""
    signature = signer.sign(pre_authentication_encoding(PAYLOAD_TYPE, manifest))
    document = {
        "payloadType": PAYLOAD_TYPE,
        "payload": base64.b64encode(manifest).decode("ascii"),
        "signatures": [
            {"keyid": signer.key_id, "sig": base64.b64encode(signature).decode("ascii")}
        ],
    }
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def verify_envelope(
    envelope: bytes, manifest: bytes, verifier: PackSignatureVerifier
) -> str | None:
    """Return the verifying key id, or ``None`` when the envelope does not authenticate.

    The envelope payload must equal ``manifest`` byte for byte, so a valid signature over a
    different manifest never authenticates this pack.
    """
    if len(envelope) > _MAX_ENVELOPE_BYTES:
        return None
    try:
        document = json.loads(envelope.decode("utf-8"))
        payload = base64.b64decode(document["payload"], validate=True)
        signatures = document["signatures"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, binascii.Error):
        return None
    if document.get("payloadType") != PAYLOAD_TYPE or payload != manifest:
        return None
    message = pre_authentication_encoding(PAYLOAD_TYPE, payload)
    for entry in signatures if isinstance(signatures, list) else []:
        try:
            key_id = str(entry["keyid"])
            signature = base64.b64decode(entry["sig"], validate=True)
        except (KeyError, TypeError, binascii.Error):
            continue
        if verifier.verify(message, signature, key_id):
            return key_id
    return None


__all__ = [
    "ENVELOPE_PATH",
    "PAYLOAD_TYPE",
    "build_envelope",
    "pre_authentication_encoding",
    "verify_envelope",
]
