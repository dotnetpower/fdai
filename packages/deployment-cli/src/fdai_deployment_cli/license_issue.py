"""Issue a short-lived deployment-bound capability token from an operator-held key."""

from __future__ import annotations

import base64
import json
import os
import stat
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    load_pem_private_key,
    load_pem_public_key,
)

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.license import inspect_license
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from fdai_deployment_cli.trust_roots import license_public_key_pem

_DEFAULT_USER_KEY = Path.home() / ".config/fdai/license-signing-key.pem"
_SOURCE_KEY = Path("secrets/license-signing-key.pem")


def discover_license_signing_key(explicit: Path | None = None) -> Path | None:
    """Return the first explicit, configured, or documented issuer key that is safe to read."""

    configured = os.environ.get("FDAI_LICENSE_SIGNING_KEY_FILE")
    candidates = (
        (explicit, explicit is not None),
        (Path(configured) if configured else None, configured is not None),
        (_DEFAULT_USER_KEY, False),
        (Path.cwd() / _SOURCE_KEY, False),
    )
    for candidate, required in candidates:
        if candidate is None:
            continue
        path = candidate if candidate.is_absolute() else Path.cwd() / candidate
        if not path.exists() and not path.is_symlink():
            if required:
                raise ValueError("configured license signing key is unavailable")
            continue
        _read_private_key(path)
        return path
    return None


def issue_deployment_license(
    *,
    private_key: Path,
    image_digest: str,
    deployment_binding: str,
    license_id: str,
    valid_days: int = 30,
) -> str:
    """Issue and reverify one complete-catalog token for an exact image and deployment."""

    if not 1 <= valid_days <= 30:
        raise ValueError("license validity must be from 1 through 30 days")
    capabilities = _capabilities()
    now = datetime.now(UTC).replace(microsecond=0)
    payload: dict[str, object] = {
        "schema_version": "fdai.license.v1",
        "license_id": license_id,
        "distribution_id": "fdai-upstream",
        "capability_ids": list(capabilities),
        "not_before": _moment(now),
        "not_after": _moment(now + timedelta(days=valid_days)),
        "image_digest": image_digest,
        "tenant_binding": deployment_binding,
    }
    document = canonical_bytes(payload)
    key = _read_private_key(private_key)
    token = f"{_encode(document)}.{_encode(key.sign(document))}"
    inspect_license(
        token,
        public_key_pem=license_public_key_pem(),
        expected_image_digest=image_digest,
        expected_tenant_binding=deployment_binding,
    )
    return token


def write_license_token(path: Path, token: str) -> None:
    """Write a verified token to a new private file for stdin-only handoff."""

    inspect_license(token, public_key_pem=license_public_key_pem())
    write_private_output(path, token)


def _read_private_key(path: Path) -> Ed25519PrivateKey:
    details = path.lstat()
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_uid != os.geteuid()
        or details.st_nlink != 1
    ):
        raise PermissionError("license signing key must be a current-UID mode-0600 regular file")
    try:
        key = load_pem_private_key(read_private_bytes(path, max_bytes=65_536), password=None)
        public = load_pem_public_key(license_public_key_pem())
    except (TypeError, ValueError) as exc:
        raise ValueError("license signing key is invalid") from exc
    if not isinstance(key, Ed25519PrivateKey) or not isinstance(public, Ed25519PublicKey):
        raise ValueError("license signing key must be Ed25519")
    if key.public_key().public_bytes_raw() != public.public_bytes_raw():
        raise ValueError("license signing key does not match the packaged public key")
    return key


def _capabilities() -> tuple[str, ...]:
    raw = (
        files("fdai_deployment_cli")
        .joinpath("trust", "capabilities.json")
        .read_text(encoding="utf-8")
    )
    value = json.loads(raw)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
        or value != sorted(set(value))
    ):
        raise ValueError("packaged capability inventory is invalid")
    return tuple(value)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _moment(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
