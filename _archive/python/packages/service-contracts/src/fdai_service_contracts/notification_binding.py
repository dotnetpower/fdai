"""Shared record contract for the locally saved Teams Workflows endpoint.

The Operator Service writes an encrypted endpoint record into the loopback
development database so a local profile never needs a plaintext file or a
plaintext environment variable. The Core control plane reads that same record
when a local deployment explicitly activates A2/A4 delivery.

Only the record shape, state key, and key-derivation parameters live here.
Neither service exports the endpoint value, and neither service may log it.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from typing import Final
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

LOCAL_TEAMS_BINDING_STATE_KEY: Final[str] = "operator-teams-workflow-binding:active"
LOCAL_TEAMS_BINDING_KIND: Final[str] = "operator.local-encrypted-teams-workflow-binding"
LOCAL_TEAMS_BINDING_HKDF_INFO: Final[bytes] = b"fdai/operator/teams-workflow-binding/v1"


class LocalTeamsBindingRecordError(RuntimeError):
    """The stored local binding record was malformed or could not be decrypted."""


def local_binding_key_material(dsn: str) -> str:
    """Return the role-independent DSN both local services derive the cipher from.

    Local services connect with role-scoped DSNs that differ only by the
    ``options=-c role=...`` parameter. Stripping that parameter gives the
    Operator writer and the Core reader one identical key material without
    copying any additional secret between processes.
    """
    parsed = urlsplit(dsn.strip())
    if not parsed.scheme:
        return dsn.strip()
    retained = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "options"
    ]
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(retained),
            "",
        )
    )


def local_binding_cipher(key_material: str) -> Fernet:
    """Derive the record cipher from local database key material.

    The key material never leaves the local process and is never persisted with
    the record, so a copied database file alone cannot reveal the endpoint.
    """
    if not key_material:
        raise LocalTeamsBindingRecordError("local Teams binding key material is unavailable")
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=LOCAL_TEAMS_BINDING_HKDF_INFO,
    ).derive(key_material.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derived))


def encode_local_binding_record(
    *,
    version: str,
    endpoint_digest: str,
    ciphertext: str,
) -> dict[str, object]:
    """Build the exact durable record both services agree on."""
    return {
        "kind": LOCAL_TEAMS_BINDING_KIND,
        "version": version,
        "endpoint_digest": endpoint_digest,
        "ciphertext": ciphertext,
    }


def decode_local_binding_record(
    record: Mapping[str, object] | None,
    *,
    key_material: str,
) -> tuple[str, str] | None:
    """Return ``(endpoint, version)`` from one stored record, or ``None``.

    Raises :class:`LocalTeamsBindingRecordError` when the record exists but is
    malformed, undecryptable, or fails its own digest check. The error message
    never contains the endpoint value.
    """
    if record is None:
        return None
    version = record.get("version")
    digest = record.get("endpoint_digest")
    ciphertext = record.get("ciphertext")
    if (
        record.get("kind") != LOCAL_TEAMS_BINDING_KIND
        or not isinstance(version, str)
        or not isinstance(digest, str)
        or not isinstance(ciphertext, str)
    ):
        raise LocalTeamsBindingRecordError("local Teams binding record is malformed")
    try:
        endpoint = (
            local_binding_cipher(key_material).decrypt(ciphertext.encode("ascii")).decode("utf-8")
        )
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise LocalTeamsBindingRecordError("local Teams binding decryption failed") from exc
    if hashlib.sha256(endpoint.encode("utf-8")).hexdigest() != digest:
        raise LocalTeamsBindingRecordError("local Teams binding digest mismatch")
    return endpoint, version


__all__ = [
    "LOCAL_TEAMS_BINDING_HKDF_INFO",
    "LOCAL_TEAMS_BINDING_KIND",
    "LOCAL_TEAMS_BINDING_STATE_KEY",
    "LocalTeamsBindingRecordError",
    "decode_local_binding_record",
    "encode_local_binding_record",
    "local_binding_cipher",
    "local_binding_key_material",
]
