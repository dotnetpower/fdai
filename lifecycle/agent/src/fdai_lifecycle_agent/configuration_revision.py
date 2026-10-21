"""Installation-local full revision consumption; no enrollment or execution authority."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fdai_deployment_cli.lifecycle_configuration_entities import validate_entity_ids
from fdai_deployment_cli.lifecycle_configuration_package import (
    ConfigurationHistoryBinding,
    SignedConfigurationPackage,
    decrypt_installation_configuration_identifiers,
    verify_installation_configuration_package,
)
from fdai_deployment_cli.lifecycle_configuration_sealing import encryption_key_digest, read_object
from fdai_deployment_cli.lifecycle_plan import LifecyclePlan
from fdai_deployment_cli.private_output import read_private_bytes

from fdai_lifecycle_agent.inputs import (
    ArtifactStore,
    InputProblem,
    InputRejectedError,
    SignedArtifact,
    VerifiedConfiguration,
    VerifiedRelease,
)
from fdai_lifecycle_agent.signatures import load_ed25519_public_key

_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
# These reference names are the only private identifiers understood by existing renderers.
_RENDER_IDENTIFIERS = frozenset({"operator_config_map_name"})
_NON_IDENTIFIER_KEYS = frozenset(
    {"region", "replicas", "workload_profile", "namespace", "capability_modes", "entity_ids"}
)


class _VerificationInputs(TypedDict):
    configuration_key: Ed25519PublicKey
    configuration_schema: Mapping[str, object]
    sealed_keys: frozenset[str]
    entity_ids: frozenset[str]
    release_version: str
    release_digest: str
    history: list[SignedConfigurationPackage]
    history_bindings: list[ConfigurationHistoryBinding]


@dataclass(frozen=True, slots=True)
class RetainedRevision:
    digest: str
    trust: ConfigurationHistoryBinding


@dataclass(frozen=True, slots=True, kw_only=True)
class FullRevisionBinding:
    """Independent local provisioning inputs, never package-selected keys or permission.

    ``active_digest`` is retained independently of delivered artifacts. Historical trust
    authenticates original accepted bytes only; it does not grant current signing authority.
    """

    installation_id: str
    active_digest: str
    entity_bindings: Mapping[str, str]
    sealed_keys: frozenset[str]
    configuration_key: Ed25519PublicKey = field(repr=False)
    installation_key: X25519PrivateKey = field(repr=False)
    history: tuple[RetainedRevision, ...] = ()

    def consume(
        self,
        plan: LifecyclePlan,
        verified: SignedArtifact,
        store: ArtifactStore,
        release: VerifiedRelease,
        managed_entities: frozenset[str],
    ) -> VerifiedConfiguration:
        """Authenticate every Entity before returning private in-memory render inputs."""
        if (
            self.installation_id != plan.audience
            or self.active_digest != plan.configuration_revision_digest
            or set(self.entity_bindings) != managed_entities
            or not plan.entity_ids <= self.entity_bindings.keys()
            or len(set(self.entity_bindings.values())) != len(self.entity_bindings)
            or self.sealed_keys & _NON_IDENTIFIER_KEYS
            or len(self.history) > 256
            or self.configuration_key.public_bytes_raw()
            == self.installation_key.public_key().public_bytes_raw()
        ):
            raise ValueError("configuration local binding does not match")
        ids = frozenset(self.entity_bindings.values())
        validate_entity_ids(ids)
        schema = release.configuration_schema
        if schema is None or schema.release_version != plan.target_release_id:
            raise ValueError("configuration Release version does not match")
        artifact = _load(store, self.active_digest)
        if artifact.payload != verified.payload:
            raise ValueError("configuration artifact changed")
        ancestors: list[SignedConfigurationPackage] = []
        history_bytes = 0
        for retained in self.history:
            ancestor = _load(store, retained.digest)
            history_bytes += len(ancestor.payload)
            if history_bytes > 16 * 1024 * 1024:
                raise ValueError("configuration history exceeds its bound")
            ancestors.append(ancestor)
        bindings = [retained.trust for retained in self.history]
        kwargs: _VerificationInputs = {
            "configuration_key": self.configuration_key,
            "configuration_schema": schema.to_mapping(),
            "sealed_keys": self.sealed_keys,
            "entity_ids": ids,
            "release_version": plan.target_release_id,
            "release_digest": release.digest,
            "history": ancestors,
            "history_bindings": bindings,
        }
        resolution = verify_installation_configuration_package(
            artifact,
            installation_key_digest=encryption_key_digest(self.installation_key.public_key()),
            **kwargs,
        )
        public: dict[str, Mapping[str, object]] = {}
        private: dict[str, Mapping[str, object]] = {}
        for entity, opaque in self.entity_bindings.items():
            identifiers = decrypt_installation_configuration_identifiers(
                artifact, entity_id=opaque, installation_key=self.installation_key, **kwargs
            )
            values = resolution.entities[opaque].values
            public[entity] = values
            private[entity] = {
                **values,
                **{key: value for key, value in identifiers.items() if key in _RENDER_IDENTIFIERS},
            }
        return VerifiedConfiguration(self.active_digest, {}, public, private)


def load_full_revision_binding(
    path: Path, encryption_key_path: Path, configuration_key_path: Path
) -> FullRevisionBinding | None:
    """Load private bindings and a role-separated X25519 PEM; absent prerequisites hold."""
    try:
        document = read_object(read_private_bytes(path, max_bytes=128 * 1024))
        if (
            set(document)
            != {
                "format",
                "installation_id",
                "active_digest",
                "entity_bindings",
                "sealed_keys",
                "history",
            }
            or document["format"] != "fdai.lifecycle-agent-configuration-binding.v1"
        ):
            raise ValueError("configuration binding fields are invalid")
        key = load_pem_private_key(
            read_private_bytes(encryption_key_path, max_bytes=16384), password=None
        )
        if not isinstance(key, X25519PrivateKey):
            raise ValueError("installation encryption key must be X25519")
        entity_map = read_object_from_value(document["entity_bindings"])
        if not all(isinstance(value, str) for value in entity_map.values()):
            raise ValueError("configuration Entity mapping is invalid")
        entities = {entity: _text(opaque) for entity, opaque in entity_map.items()}
        validate_entity_ids(frozenset(entities.values()))
        if len(set(entities.values())) != len(entities):
            raise ValueError("configuration Entity mapping is not one-to-one")
        sealed = document["sealed_keys"]
        if not isinstance(sealed, list) or any(
            not isinstance(item, str) or not item for item in sealed
        ):
            raise ValueError("configuration sealed keys are invalid")
        if len(set(sealed)) != len(sealed):
            raise ValueError("configuration sealed keys are duplicated")
        history = document["history"]
        if not isinstance(history, list) or len(history) > 256:
            raise ValueError("configuration history is invalid")
        retained: list[RetainedRevision] = []
        for entry in history:
            item = read_object_from_value(entry)
            if set(item) != {"digest", "configuration_key_file", "installation_key_digest"}:
                raise ValueError("configuration historical trust is invalid")
            retained.append(
                RetainedRevision(
                    _digest(item["digest"]),
                    ConfigurationHistoryBinding(
                        load_ed25519_public_key(Path(_text(item["configuration_key_file"]))),
                        _digest(item["installation_key_digest"]),
                    ),
                )
            )
        return FullRevisionBinding(
            installation_id=_text(document["installation_id"]),
            active_digest=_digest(document["active_digest"]),
            entity_bindings=entities,
            sealed_keys=frozenset(sealed),
            configuration_key=load_ed25519_public_key(configuration_key_path),
            installation_key=key,
            history=tuple(retained),
        )
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, UnsupportedAlgorithm):
        raise ValueError(
            "configuration binding or independent encryption input is invalid"
        ) from None


def _load(store: ArtifactStore, digest: str) -> SignedConfigurationPackage:
    try:
        artifact = store.load("configuration", digest)
    except (OSError, ValueError, TypeError):
        raise InputRejectedError("configuration", InputProblem.UNREADABLE) from None
    if artifact is None:
        raise InputRejectedError("configuration", InputProblem.UNAVAILABLE)
    package = SignedConfigurationPackage(artifact.payload, artifact.signature)
    if package.digest != digest:
        raise ValueError("configuration package digest does not match")
    return package


def read_object_from_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("configuration field is not an object")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("configuration field is not text")
    return value


def _digest(value: object) -> str:
    text = _text(value)
    if not _DIGEST.fullmatch(text):
        raise ValueError("configuration digest is invalid")
    return text
