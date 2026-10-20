"""Offline signed configuration packages using the existing configuration validators.

Callers own trust registration and atomic durable history. This library neither enrolls keys
nor imports packages into the Hub or changes the existing Agent artifact protocol.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.lifecycle_configuration import (
    LayerResolution,
    validate_configuration_package_for_signing,
)
from fdai_deployment_cli.lifecycle_configuration_document import (
    validate_configuration_document,
)
from fdai_deployment_cli.lifecycle_configuration_entities import (
    INSTALLATION_CONFIGURATION_FORMAT,
    InstallationConfigurationInput,
    InstallationLayerResolution,
    prepare_installation_configuration,
    resolve_installation_configuration,
)
from fdai_deployment_cli.lifecycle_configuration_sealing import (
    encryption_key_digest,
    open_identifiers,
    read_object,
    seal_identifiers,
    validate_sealed_identifiers,
)

_FORMAT = "fdai.lifecycle-configuration-package.v1"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z", re.ASCII)
_MAX_BYTES = 1024 * 1024
_FIELDS = frozenset(
    {
        "format",
        "revision_id",
        "predecessor_digest",
        "release_version",
        "installation_key_digest",
        "input_digest",
        "configuration",
        "sealed_keys",
        "sealed",
    }
)


@dataclass(frozen=True, slots=True)
class SignedConfigurationPackage:
    """Immutable detached-signature artifact; safe to persist without plaintext identifiers."""

    payload: bytes
    signature: bytes

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfigurationPackageInput:
    """One complete customer revision for the existing single-Entity configuration contract."""

    revision_id: str
    release_version: str
    configuration_schema: Mapping[str, object]
    environment_config: Mapping[str, object]
    entity_overrides: Sequence[Mapping[str, object]]
    sealed_values: Mapping[str, object]
    sealed_keys: frozenset[str]


def build_configuration_package(
    source: ConfigurationPackageInput,
    *,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PublicKey,
    history: Sequence[SignedConfigurationPackage] = (),
) -> SignedConfigurationPackage:
    """Validate, seal, and sign a revision, or return its exact prior bytes on retry.

    History must be the complete accepted chain in order. A caller must serialize builds
    and persist the result atomically; passing an empty or stale history cannot prove that.
    No key material is read from files or discovered from the environment.
    """
    sealed_values = read_object(canonical_bytes(source.sealed_values))
    if set(sealed_values) != source.sealed_keys:
        raise ValueError("sealed identifier values do not match the trusted sealed keys")
    configuration = read_object(
        canonical_bytes(
            {
                "schema": source.configuration_schema,
                "environment": source.environment_config,
                "entity_overrides": source.entity_overrides,
            }
        )
    )
    validate_configuration_document(
        configuration, source.configuration_schema, source.release_version, set(source.sealed_keys)
    )
    return _build_signed_revision(
        revision_id=source.revision_id,
        release_version=source.release_version,
        configuration=configuration,
        sealed_values=sealed_values,
        sealed_keys=source.sealed_keys,
        package_format=_FORMAT,
        release_digest=None,
        signing_key=signing_key,
        installation_key=installation_key,
        history=history,
    )


def _build_signed_revision(
    *,
    revision_id: str,
    release_version: str,
    configuration: dict[str, object],
    sealed_values: dict[str, object],
    sealed_keys: frozenset[str],
    package_format: str,
    release_digest: str | None,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PublicKey,
    history: Sequence[SignedConfigurationPackage],
) -> SignedConfigurationPackage:
    recipient_digest = encryption_key_digest(installation_key)
    chain = _verify_history(history, signing_key.public_key(), recipient_digest)
    validate_configuration_package_for_signing(sealed_values)
    _revision(revision_id)
    _sealed_keys(sorted(sealed_keys))
    inputs: dict[str, object] = {
        "configuration": configuration,
        "release_version": release_version,
        "sealed_values": sealed_values,
        "installation_key_digest": recipient_digest,
        "sealed_keys": sorted(sealed_keys),
    }
    if release_digest is not None:
        if not _DIGEST.fullmatch(release_digest):
            raise ValueError("configuration Release manifest digest is invalid")
        inputs["release_digest"] = release_digest
    read_object(canonical_bytes(inputs))
    input_digest = canonical_digest(inputs)
    for package, previous in zip(history, chain, strict=True):
        if previous["revision_id"] == revision_id:
            if package != history[-1] or previous["input_digest"] != input_digest:
                raise ValueError(
                    "configuration revision was already packaged with different inputs"
                )
            return package
    document: dict[str, object] = {
        "format": package_format,
        "revision_id": revision_id,
        "predecessor_digest": history[-1].digest if history else None,
        "release_version": release_version,
        "installation_key_digest": recipient_digest,
        "input_digest": input_digest,
        "configuration": configuration,
        "sealed_keys": sorted(sealed_keys),
    }
    if release_digest is not None:
        document["release_digest"] = release_digest
    context = canonical_bytes(document)
    document["sealed"] = seal_identifiers(sealed_values, installation_key, context=context)
    payload = canonical_bytes(document)
    if len(payload) > _MAX_BYTES:
        raise ValueError("configuration package exceeds the size limit")
    return SignedConfigurationPackage(payload, signing_key.sign(payload))


def verify_configuration_package(
    package: SignedConfigurationPackage,
    *,
    configuration_key: Ed25519PublicKey,
    installation_key_digest: str,
    configuration_schema: Mapping[str, object],
    sealed_keys: frozenset[str],
    history: Sequence[SignedConfigurationPackage] = (),
) -> LayerResolution:
    """Verify an import candidate against trusted schema, recipient, and complete history.

    An exact retry of the current head is a no-op. An older revision cannot become current.
    The returned values are public configuration only, never decrypted identifiers.
    """
    document = _verify_candidate(
        package, configuration_key, installation_key_digest, sealed_keys, history
    )
    if document["format"] != _FORMAT:
        raise ValueError("single-Entity reader cannot consume an installation revision")
    configuration = _object(document["configuration"])
    release_version = _text(document["release_version"])
    return validate_configuration_document(
        configuration, configuration_schema, release_version, _sealed_keys(document["sealed_keys"])
    )


def decrypt_configuration_identifiers(
    package: SignedConfigurationPackage,
    *,
    configuration_key: Ed25519PublicKey,
    installation_key: X25519PrivateKey,
    configuration_schema: Mapping[str, object],
    sealed_keys: frozenset[str],
    history: Sequence[SignedConfigurationPackage] = (),
) -> dict[str, object]:
    """Authenticate the package and its chain before installation-local decryption."""
    verify_configuration_package(
        package,
        configuration_key=configuration_key,
        installation_key_digest=encryption_key_digest(installation_key.public_key()),
        configuration_schema=configuration_schema,
        sealed_keys=sealed_keys,
        history=history,
    )
    return _decrypt_values(package, installation_key)


def _decrypt_values(
    package: SignedConfigurationPackage, installation_key: X25519PrivateKey
) -> dict[str, object]:
    document = read_object(package.payload)
    envelope = _object(document.pop("sealed"))
    values = open_identifiers(envelope, installation_key, context=canonical_bytes(document))
    if document["format"] == _FORMAT and set(values) != _sealed_keys(document["sealed_keys"]):
        raise ValueError("sealed identifier keys do not match the manifest")
    inputs = {
        "configuration": document["configuration"],
        "release_version": document["release_version"],
        "sealed_values": values,
        "installation_key_digest": document["installation_key_digest"],
        "sealed_keys": document["sealed_keys"],
    }
    if document["format"] == INSTALLATION_CONFIGURATION_FORMAT:
        inputs["release_digest"] = document["release_digest"]
    if canonical_digest(inputs) != document["input_digest"]:
        raise ValueError("configuration input digest does not match")
    return values


def _verify_history(
    history: Sequence[SignedConfigurationPackage], key: Ed25519PublicKey, recipient_digest: str
) -> list[dict[str, object]]:
    if len(history) > 256:
        raise ValueError("configuration history exceeds its bound")
    chain: list[dict[str, object]] = []
    predecessor: str | None = None
    for package in history:
        document = _verified_document(package, key, recipient_digest)
        _check_successor(document, predecessor, chain)
        chain.append(document)
        predecessor = package.digest
    return chain


def _check_successor(
    document: Mapping[str, object], predecessor: str | None, chain: Sequence[Mapping[str, object]]
) -> None:
    if document["predecessor_digest"] != predecessor:
        raise ValueError("configuration predecessor gap or fork")
    if any(item["revision_id"] == document["revision_id"] for item in chain):
        raise ValueError("configuration revision was already imported")


def _verified_document(
    package: SignedConfigurationPackage, key: Ed25519PublicKey, recipient_digest: str
) -> dict[str, object]:
    if not package.signature:
        raise ValueError("configuration package signature is missing")
    if len(package.payload) > _MAX_BYTES:
        raise ValueError("configuration package exceeds the size limit")
    try:
        key.verify(package.signature, package.payload)
    except InvalidSignature:
        raise ValueError("configuration package signature is invalid") from None
    document = read_object(package.payload)
    package_format = document.get("format")
    fields = _FIELDS | (
        {"release_digest"} if package_format == INSTALLATION_CONFIGURATION_FORMAT else set()
    )
    if set(document) != fields or package_format not in (
        _FORMAT,
        INSTALLATION_CONFIGURATION_FORMAT,
    ):
        raise ValueError("configuration package fields or format are invalid")
    if canonical_bytes(document) != package.payload:
        raise ValueError("configuration package must use canonical JSON")
    _revision(_text(document["revision_id"]))
    for name in ("installation_key_digest", "input_digest"):
        if not _DIGEST.fullmatch(_text(document[name])):
            raise ValueError("configuration package digest is invalid")
    if package_format == INSTALLATION_CONFIGURATION_FORMAT and not _DIGEST.fullmatch(
        _text(document["release_digest"])
    ):
        raise ValueError("configuration Release manifest digest is invalid")
    predecessor = document["predecessor_digest"]
    if predecessor is not None and not _DIGEST.fullmatch(_text(predecessor)):
        raise ValueError("configuration predecessor digest is invalid")
    if document["installation_key_digest"] != recipient_digest:
        raise ValueError("configuration package belongs to another installation key")
    _sealed_keys(document["sealed_keys"])
    validate_sealed_identifiers(_object(document["sealed"]), recipient_digest=recipient_digest)
    return document


def _verify_candidate(
    package: SignedConfigurationPackage,
    configuration_key: Ed25519PublicKey,
    recipient_digest: str,
    sealed_keys: frozenset[str],
    history: Sequence[SignedConfigurationPackage],
) -> dict[str, object]:
    chain = _verify_history(history, configuration_key, recipient_digest)
    document = _verified_document(package, configuration_key, recipient_digest)
    if _sealed_keys(document["sealed_keys"]) != sealed_keys:
        raise ValueError("sealed identifier keys do not match the trusted Release keys")
    if not history or package != history[-1]:
        _check_successor(document, history[-1].digest if history else None, chain)
    return document


def build_installation_configuration_package(
    source: InstallationConfigurationInput,
    *,
    entity_ids: frozenset[str],
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PublicKey,
    history: Sequence[SignedConfigurationPackage] = (),
) -> SignedConfigurationPackage:
    """Produce one signed full revision, checked against the independently selected Entity set."""
    configuration, sealed_values = prepare_installation_configuration(source, entity_ids=entity_ids)
    return _build_signed_revision(
        revision_id=source.revision_id,
        release_version=source.release_version,
        configuration=configuration,
        sealed_values=sealed_values,
        sealed_keys=source.sealed_keys,
        package_format=INSTALLATION_CONFIGURATION_FORMAT,
        release_digest=source.release_digest,
        signing_key=signing_key,
        installation_key=installation_key,
        history=history,
    )


def verify_installation_configuration_package(
    package: SignedConfigurationPackage,
    *,
    configuration_key: Ed25519PublicKey,
    installation_key_digest: str,
    configuration_schema: Mapping[str, object],
    sealed_keys: frozenset[str],
    entity_ids: frozenset[str],
    release_version: str,
    release_digest: str,
    history: Sequence[SignedConfigurationPackage] = (),
) -> InstallationLayerResolution:
    """Authenticate the full revision against independent Release, selection, keys and history."""
    document = _verify_candidate(
        package, configuration_key, installation_key_digest, sealed_keys, history
    )
    if (
        document["format"] != INSTALLATION_CONFIGURATION_FORMAT
        or document["release_version"] != release_version
        or document["release_digest"] != release_digest
    ):
        raise ValueError("installation configuration format or Release does not match")
    return resolve_installation_configuration(
        _object(document["configuration"]),
        configuration_schema=configuration_schema,
        release_version=release_version,
        sealed_keys=sealed_keys,
        entity_ids=entity_ids,
    )


def decrypt_installation_configuration_identifiers(
    package: SignedConfigurationPackage,
    *,
    entity_id: str,
    configuration_key: Ed25519PublicKey,
    installation_key: X25519PrivateKey,
    configuration_schema: Mapping[str, object],
    sealed_keys: frozenset[str],
    entity_ids: frozenset[str],
    release_version: str,
    release_digest: str,
    history: Sequence[SignedConfigurationPackage] = (),
) -> dict[str, object]:
    """Verify the whole revision before returning identifiers for exactly one selected Entity."""
    verify_installation_configuration_package(
        package,
        configuration_key=configuration_key,
        installation_key_digest=encryption_key_digest(installation_key.public_key()),
        configuration_schema=configuration_schema,
        sealed_keys=sealed_keys,
        entity_ids=entity_ids,
        release_version=release_version,
        release_digest=release_digest,
        history=history,
    )
    if entity_id not in entity_ids:
        raise ValueError("requested Entity is not selected")
    values = _decrypt_values(package, installation_key)
    if set(values) != entity_ids or any(
        set(_object(item)) != sealed_keys for item in values.values()
    ):
        raise ValueError("sealed Entity identifier coverage does not match")
    return _object(values[entity_id])


def _sealed_keys(value: object) -> set[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError("sealed identifier keys are invalid")
    keys = {_text(item) for item in value}
    if len(keys) != len(value):
        raise ValueError("sealed identifier keys are duplicated")
    return keys


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError("configuration field must be an object")
    return {str(key): item for key, item in value.items()}


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("configuration field must be text")
    return value


def _revision(value: str) -> None:
    if not _REVISION.fullmatch(value):
        raise ValueError("configuration revision must be a full Git commit identifier")
