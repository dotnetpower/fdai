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
from fdai_deployment_cli.license import (
    INSTALLATION_ENTITLEMENT_SCHEMA,
    inspect_installation_entitlement,
    inspect_license,
)
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from fdai_deployment_cli.trust_roots import license_public_key_pem

_ISSUER_KEY = Path("secrets/integrity-signing-key.pem")
_MAX_KEY_BYTES = 65_536


def discover_license_signing_key() -> Path | None:
    """Return the checkout's upstream integrity key, or None to keep the Trial.

    Only the fixed `secrets/integrity-signing-key.pem` of the working checkout is
    considered. A present key that is not an owner-only regular file matching the
    packaged public key raises instead of silently selecting the Trial.
    """

    path = Path.cwd() / _ISSUER_KEY
    if not path.exists() and not path.is_symlink():
        return None
    _read_private_key(path)
    return path


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


def deployment_license_token(
    *,
    trial_token: Path | None,
    image_digest: str,
    deployment_binding: str,
    work_ref: str,
    installation_binding: str | None = None,
) -> str | None:
    """Return the key holder's grant, a verified supplied token, or None for observation-only.

    A key holder whose runtime supplies an installation binding receives the no-expiry
    installation entitlement; otherwise the key holder keeps the 30-day v1 token.
    """

    issuer = discover_license_signing_key()
    if issuer is not None and installation_binding is not None:
        return issue_installation_entitlement(
            private_key=issuer,
            entitlement_id=f"ent-{work_ref}",
            installation_binding=installation_binding,
            deployment_binding=deployment_binding,
        )
    if issuer is not None:
        return issue_deployment_license(
            private_key=issuer,
            image_digest=image_digest,
            deployment_binding=deployment_binding,
            license_id=f"lic-{work_ref}",
        )
    if trial_token is None:
        return None
    path = trial_token if trial_token.is_absolute() else Path.cwd() / trial_token
    token = read_private_bytes(path, max_bytes=8192).decode("ascii")
    inspect_license(
        token,
        public_key_pem=license_public_key_pem(),
        expected_image_digest=image_digest,
        expected_tenant_binding=deployment_binding,
    )
    return token


def issue_installation_entitlement(
    *,
    private_key: Path,
    entitlement_id: str,
    installation_binding: str,
    deployment_binding: str,
) -> str:
    """Issue and reverify one no-expiry, complete-catalog grant for one installation.

    The document carries no image digest and no validity window, so upgrades and
    restarts keep it valid; its exact installation and deployment digests are its
    only limit, and it is useless anywhere else.
    """

    payload: dict[str, object] = {
        "schema_version": INSTALLATION_ENTITLEMENT_SCHEMA,
        "entitlement_id": entitlement_id,
        "distribution_id": "fdai-upstream",
        "installation_binding": installation_binding,
        "deployment_binding": deployment_binding,
        "issued_at": _moment(datetime.now(UTC).replace(microsecond=0)),
    }
    document = canonical_bytes(payload)
    key = _read_private_key(private_key)
    token = f"{_encode(document)}.{_encode(key.sign(document))}"
    inspect_installation_entitlement(
        token,
        public_key_pem=license_public_key_pem(),
        expected_installation_binding=installation_binding,
        expected_deployment_binding=deployment_binding,
    )
    return token


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
        key = load_pem_private_key(_read_key_bytes(path), password=None)
        public = load_pem_public_key(license_public_key_pem())
    except (TypeError, ValueError) as exc:
        raise ValueError("license signing key is invalid") from exc
    if not isinstance(key, Ed25519PrivateKey) or not isinstance(public, Ed25519PublicKey):
        raise ValueError("license signing key must be Ed25519")
    if key.public_key().public_bytes_raw() != public.public_bytes_raw():
        raise ValueError("license signing key does not match the packaged public key")
    return key


def _read_key_bytes(path: Path) -> bytes:
    """Read the key file under the same custody rule Core's issuer check applies.

    The descriptor never follows a link or blocks on a special file. Unlike a
    private deployment output, the key's directory needs no owner-only mode.
    """

    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(details.st_mode)
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.geteuid()
            or details.st_nlink != 1
        ):
            raise PermissionError(
                "license signing key must be a current-UID mode-0600 regular file"
            )
        if not 0 < details.st_size <= _MAX_KEY_BYTES:
            raise ValueError("license signing key is empty or exceeds 65536 bytes")
        content = stream.read(_MAX_KEY_BYTES + 1)
    if len(content) != details.st_size:
        raise ValueError("license signing key changed while being read")
    return content


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
