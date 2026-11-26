"""TUF-style catalog trust: the pinned initial root, role signing and role verification.

The Release Hub signs with these helpers and the Lifecycle Hub verifies with them, so both sides
share one domain-separation rule. Verification never touches the network or a database.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fdai_deployment_cli.contracts import canonical_bytes
from fdai_service_contracts.catalog_integrity import catalog_key_id, role_signing_message
from fdai_service_contracts.catalog_metadata import (
    MAX_METADATA_BYTES as MAX_METADATA_BYTES,
)
from fdai_service_contracts.catalog_metadata import (
    METADATA_SCHEMA as METADATA_SCHEMA,
)
from fdai_service_contracts.catalog_metadata import (
    MetadataBundle as MetadataBundle,
)
from fdai_service_contracts.catalog_metadata import (
    parse_metadata as parse_metadata,
)
from fdai_service_contracts.catalog_metadata import (
    role_of,
)
from fdai_service_contracts.catalog_metadata import (
    role_verifier as role_verifier,
)
from fdai_service_contracts.catalog_roles import root_from_wire
from pydantic import BaseModel, ConfigDict, Field, model_validator

_KEY_ID = re.compile(r"^ed25519-[0-9a-f]{64}$")


class CatalogTrust(BaseModel):
    """The initial root a Lifecycle Hub trusts: its offline key ids and signing threshold.

    The pin names keys, not a Release Hub address. Every later root must be signed by a
    threshold of the keys of the root before it, so the pin never has to change for a rotation.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    mode: Literal["tuf"]
    root_key_ids: tuple[str, ...] = Field(min_length=1, max_length=16)
    root_threshold: int = Field(ge=1, le=16)

    @model_validator(mode="after")
    def validate_pin(self) -> CatalogTrust:
        if any(_KEY_ID.fullmatch(key_id) is None for key_id in self.root_key_ids):
            raise ValueError("Catalog root pins must be ed25519 key ids.")
        if len(set(self.root_key_ids)) != len(self.root_key_ids):
            raise ValueError("Catalog root pins must be unique.")
        if self.root_threshold > len(self.root_key_ids):
            raise ValueError("Catalog root threshold exceeds the pinned key count.")
        return self

    @property
    def root_key_id_set(self) -> frozenset[str]:
        return frozenset(self.root_key_ids)

    @property
    def key_digest(self) -> str:
        """Stable identity of the pin, persisted so a changed pin cannot silently replace it."""

        return canonical_digest_hex(
            {
                "mode": self.mode,
                "root_key_ids": sorted(self.root_key_ids),
                "root_threshold": self.root_threshold,
            }
        )


def canonical_digest_hex(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def raw_public_key(public_key: Ed25519PublicKey) -> bytes:
    return public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def key_id_of(public_key: Ed25519PublicKey) -> str:
    return catalog_key_id(raw_public_key(public_key))


def sign_role(private_key: Ed25519PrivateKey, payload: bytes) -> bytes:
    """Sign one role payload in the domain its own `role` field selects."""

    role = role_of(payload)
    if role is None:
        raise ValueError("catalog role payload names no role")
    return private_key.sign(role_signing_message(role, payload))


@dataclass(frozen=True, slots=True)
class OnlineRoleKey:
    """An online snapshot or timestamp key. It is never the offline root key."""

    private_key: Ed25519PrivateKey

    @property
    def exportable(self) -> bool:
        return True

    @property
    def key_id(self) -> str:
        return key_id_of(self.private_key.public_key())

    def sign(self, payload: bytes) -> bytes:
        return sign_role(self.private_key, payload)


class ManagedKeyCustodyService(Protocol):
    """Non-exportable key service (Azure Key Vault / Managed HSM) for online role signing."""

    def sign_role_message(
        self,
        *,
        key_uri: str,
        role: Literal["snapshot", "timestamp"],
        message: bytes,
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class AzureKeyVaultRoleSigningService:
    """Out-of-process Azure Key Vault / Managed HSM `/sign` client with zero local private keys."""

    allowed_vault_hosts: frozenset[str]
    get_bearer_token: Callable[[], str]
    post_json: Callable[[str, Mapping[str, str], Mapping[str, str]], Mapping[str, object]]
    api_version: str = "7.4"
    signer_process_id: int | None = None

    def __post_init__(self) -> None:
        if not self.allowed_vault_hosts or any(
            not host or any(ch.isspace() for ch in host) for host in self.allowed_vault_hosts
        ):
            raise ValueError("AzureKeyVaultRoleSigningService requires non-empty vault hostnames.")
        if self.signer_process_id is not None and self.signer_process_id == os.getpid():
            raise ValueError(
                "Managed key signer process ID must be isolated from the Hub OS process."
            )

    def sign_role_message(
        self,
        *,
        key_uri: str,
        role: Literal["snapshot", "timestamp"],
        message: bytes,
    ) -> bytes:
        parsed = urlsplit(key_uri)
        if (
            parsed.scheme != "https"
            or parsed.netloc not in self.allowed_vault_hosts
            or "/keys/" not in parsed.path
        ):
            raise ValueError(f"Key URI {key_uri!r} is not in allowed Key Vault hosts.")
        token = self.get_bearer_token().strip()
        if not token:
            raise PermissionError("Key Vault signing requires a non-empty bearer token.")
        sign_url = f"{key_uri.rstrip('/')}/sign?api-version={self.api_version}"
        encoded_msg = base64.urlsafe_b64encode(message).rstrip(b"=").decode("ascii")
        response = self.post_json(
            sign_url,
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            {
                "alg": "EdDSA",
                "value": encoded_msg,
                "fdai_role": role,
            },
        )
        raw_sig = str(response.get("value") or "").strip()
        if not raw_sig:
            raise ValueError("Key Vault /sign response omitted signature value.")
        padded = raw_sig + "=" * (-len(raw_sig) % 4)
        signature = base64.urlsafe_b64decode(padded.encode("ascii"))
        if len(signature) != 64:
            raise ValueError("Key Vault /sign response must be a 64-byte Ed25519 signature.")
        return signature


@dataclass(frozen=True, slots=True)
class ManagedOnlineRoleKey:
    """Non-exportable online snapshot or timestamp key backed by a managed key custody service.

    Private key bytes never enter Release Hub memory or database state; signing is delegated to
    the configured key custody service and restricted to the declared role domain.
    """

    key_vault_key_uri: str
    role: Literal["snapshot", "timestamp"]
    public_key: Ed25519PublicKey
    service: ManagedKeyCustodyService

    def __post_init__(self) -> None:
        parsed = urlsplit(self.key_vault_key_uri)
        if parsed.scheme != "https" or not parsed.netloc or "/keys/" not in parsed.path:
            raise ValueError(
                "Managed online role key requires an https://.../keys/... key service URI."
            )
        if self.role not in {"snapshot", "timestamp"}:
            raise ValueError("Managed online role key role must be 'snapshot' or 'timestamp'.")
        if hasattr(self.service, "private_key") or hasattr(self.service, "_keys"):
            raise ValueError(
                "ManagedOnlineRoleKey service must not hold raw Ed25519PrivateKey in-process."
            )

    @property
    def exportable(self) -> Literal[False]:
        return False

    @property
    def private_key(self) -> Ed25519PrivateKey:
        raise PermissionError("Managed online role keys are non-exportable.")

    def export_private_key(self) -> bytes:
        raise PermissionError("Managed online role keys are non-exportable.")

    @property
    def key_id(self) -> str:
        return key_id_of(self.public_key)

    def sign(self, payload: bytes) -> bytes:
        payload_role = role_of(payload)
        if payload_role != self.role:
            raise ValueError(
                f"Managed online role key for {self.role!r} refuses to sign {payload_role!r}."
            )
        signature = self.service.sign_role_message(
            key_uri=self.key_vault_key_uri,
            role=self.role,
            message=role_signing_message(self.role, payload),
        )
        if not role_verifier({self.key_id: raw_public_key(self.public_key)})(
            self.key_id, payload, signature
        ):
            raise ValueError("Managed key service returned an invalid role signature.")
        return signature


@dataclass(frozen=True, slots=True)
class ManagedKeyCustodyReceipt:
    """Auditable custody receipt proving threshold offline root and non-exportable online keys."""

    custody_mode: Literal["managed_hsm_or_key_vault"]
    root_version: int
    root_threshold: int
    root_key_ids: tuple[str, ...]
    independent_root_holders: tuple[str, ...]
    root_private_keys_entered_hub: Literal[False]
    snapshot_key_id: str
    snapshot_key_uri: str
    snapshot_exportable: Literal[False]
    timestamp_key_id: str
    timestamp_key_uri: str
    timestamp_exportable: Literal[False]
    export_key_id: str
    hub_process_id: int | None = None
    ceremony_process_id: int | None = None
    vault_signer_process_id: int | None = None

    def __post_init__(self) -> None:
        if self.root_threshold < 2 or len(self.root_key_ids) < self.root_threshold:
            raise ValueError("ManagedKeyCustodyReceipt requires a threshold >= 2 offline root.")
        if len(set(self.root_key_ids)) != len(self.root_key_ids):
            raise ValueError("ManagedKeyCustodyReceipt root_key_ids must be unique.")
        if len(set(self.independent_root_holders)) != len(self.root_key_ids):
            raise ValueError(
                "Each offline root key must be held by a distinct independent custodian."
            )
        online_ids = {self.snapshot_key_id, self.timestamp_key_id, self.export_key_id}
        if len(online_ids) != 3 or (online_ids & set(self.root_key_ids)):
            raise ValueError(
                "Root, snapshot, timestamp, and export role keys must be pairwise disjoint."
            )
        if (
            self.hub_process_id is not None
            and self.ceremony_process_id is not None
            and self.hub_process_id == self.ceremony_process_id
        ):
            raise ValueError(
                "Offline root ceremony process ID must be isolated from Hub process ID."
            )
        if (
            self.hub_process_id is not None
            and self.vault_signer_process_id is not None
            and self.hub_process_id == self.vault_signer_process_id
        ):
            raise ValueError("Vault signer process ID must be isolated from Hub process ID.")

    @classmethod
    def from_verified_custody(
        cls,
        *,
        root_envelope_bytes: bytes,
        independent_root_holders: tuple[str, ...],
        snapshot_key: ManagedOnlineRoleKey,
        timestamp_key: ManagedOnlineRoleKey,
        export_key_id: str,
        hub_process_id: int,
        ceremony_process_id: int,
        vault_signer_process_id: int,
    ) -> ManagedKeyCustodyReceipt:
        if not isinstance(snapshot_key, ManagedOnlineRoleKey) or snapshot_key.role != "snapshot":
            raise ValueError("snapshot_key must be a non-exportable ManagedOnlineRoleKey.")
        if not isinstance(timestamp_key, ManagedOnlineRoleKey) or timestamp_key.role != "timestamp":
            raise ValueError("timestamp_key must be a non-exportable ManagedOnlineRoleKey.")
        root_record = root_from_wire(json.loads(root_envelope_bytes.decode("utf-8")))
        root_key_ids = tuple(sorted(root_record.root_key_ids))
        root_threshold = int(root_record.threshold)
        public_map = {
            kid: root_record.public_keys[kid]
            for kid in root_key_ids
            if kid in root_record.public_keys
        }
        verify = role_verifier(public_map)
        signed_bytes = root_record.canonical_payload()
        valid_root_sigs = {
            kid
            for kid, sig_bytes in root_record.signatures.items()
            if kid in public_map and verify(kid, signed_bytes, sig_bytes)
        }
        if len(valid_root_sigs) < root_threshold:
            raise ValueError("Root envelope failed cryptographic threshold verification.")
        if root_record.snapshot_key_ids != frozenset({snapshot_key.key_id}):
            raise ValueError("Root snapshot role delegation does not match ManagedOnlineRoleKey.")
        if root_record.timestamp_key_ids != frozenset({timestamp_key.key_id}):
            raise ValueError("Root timestamp role delegation does not match ManagedOnlineRoleKey.")
        if root_record.export_key_ids != frozenset({export_key_id}):
            raise ValueError("Root export role delegation does not match export_key_id.")
        return cls(
            custody_mode="managed_hsm_or_key_vault",
            root_version=int(root_record.version),
            root_threshold=root_threshold,
            root_key_ids=root_key_ids,
            independent_root_holders=independent_root_holders,
            root_private_keys_entered_hub=False,
            snapshot_key_id=snapshot_key.key_id,
            snapshot_key_uri=snapshot_key.key_vault_key_uri,
            snapshot_exportable=False,
            timestamp_key_id=timestamp_key.key_id,
            timestamp_key_uri=timestamp_key.key_vault_key_uri,
            timestamp_exportable=False,
            export_key_id=export_key_id,
            hub_process_id=hub_process_id,
            ceremony_process_id=ceremony_process_id,
            vault_signer_process_id=vault_signer_process_id,
        )

    @property
    def digest(self) -> str:
        payload: dict[str, object] = {
            "custody_mode": self.custody_mode,
            "root_version": self.root_version,
            "root_threshold": self.root_threshold,
            "root_key_ids": list(self.root_key_ids),
            "independent_root_holders": list(self.independent_root_holders),
            "root_private_keys_entered_hub": self.root_private_keys_entered_hub,
            "snapshot_key_id": self.snapshot_key_id,
            "snapshot_key_uri": self.snapshot_key_uri,
            "snapshot_exportable": self.snapshot_exportable,
            "timestamp_key_id": self.timestamp_key_id,
            "timestamp_key_uri": self.timestamp_key_uri,
            "timestamp_exportable": self.timestamp_exportable,
            "export_key_id": self.export_key_id,
        }
        if self.hub_process_id is not None:
            payload["process_isolation"] = {
                "ceremony_isolated_from_hub": self.ceremony_process_id != self.hub_process_id,
                "vault_isolated_from_hub": self.vault_signer_process_id != self.hub_process_id,
            }
        return "sha256:" + canonical_digest_hex(payload)


def online_key_from_environment(name: str) -> OnlineRoleKey:
    """Read a secret-referenced PEM key once and remove it from the process environment."""

    value = os.environ.pop(name, "")
    if not value:
        raise ValueError("Provision the catalog role key through a secret reference.")
    key = serialization.load_pem_private_key(value.encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Catalog role keys must be Ed25519.")
    return OnlineRoleKey(key)
