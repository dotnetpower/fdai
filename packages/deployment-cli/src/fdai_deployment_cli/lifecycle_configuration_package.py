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
    resolve_configuration_layers,
    validate_configuration_package_for_signing,
    validate_release_configuration_schema,
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
    recipient_digest = encryption_key_digest(installation_key)
    chain = _verify_history(history, signing_key.public_key(), recipient_digest)
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
    _validate_configuration(
        configuration, source.configuration_schema, source.release_version, set(source.sealed_keys)
    )
    validate_configuration_package_for_signing(sealed_values)
    _revision(source.revision_id)
    inputs: dict[str, object] = {
        "configuration": configuration,
        "release_version": source.release_version,
        "sealed_values": sealed_values,
        "installation_key_digest": recipient_digest,
        "sealed_keys": sorted(source.sealed_keys),
    }
    read_object(canonical_bytes(inputs))
    input_digest = canonical_digest(inputs)
    for package, previous in zip(history, chain, strict=True):
        if previous["revision_id"] == source.revision_id:
            if previous["input_digest"] != input_digest:
                raise ValueError(
                    "configuration revision was already packaged with different inputs"
                )
            return package
    document: dict[str, object] = {
        "format": _FORMAT,
        "revision_id": source.revision_id,
        "predecessor_digest": history[-1].digest if history else None,
        "release_version": source.release_version,
        "installation_key_digest": recipient_digest,
        "input_digest": input_digest,
        "configuration": configuration,
        "sealed_keys": sorted(source.sealed_keys),
    }
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
    chain = _verify_history(history, configuration_key, installation_key_digest)
    document = _verified_document(package, configuration_key, installation_key_digest)
    if _sealed_keys(document["sealed_keys"]) != sealed_keys:
        raise ValueError("sealed identifier keys do not match the trusted Release keys")
    if history and package == history[-1]:
        pass
    else:
        _check_successor(document, history[-1].digest if history else None, chain)
    configuration = _object(document["configuration"])
    release_version = _text(document["release_version"])
    return _validate_configuration(
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
    document = read_object(package.payload)
    envelope = _object(document.pop("sealed"))
    values = open_identifiers(envelope, installation_key, context=canonical_bytes(document))
    if set(values) != _sealed_keys(document["sealed_keys"]):
        raise ValueError("sealed identifier keys do not match the manifest")
    inputs = {
        "configuration": document["configuration"],
        "release_version": document["release_version"],
        "sealed_values": values,
        "installation_key_digest": document["installation_key_digest"],
        "sealed_keys": document["sealed_keys"],
    }
    if canonical_digest(inputs) != document["input_digest"]:
        raise ValueError("configuration input digest does not match")
    return values


def _verify_history(
    history: Sequence[SignedConfigurationPackage], key: Ed25519PublicKey, recipient_digest: str
) -> list[dict[str, object]]:
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
    if set(document) != _FIELDS or document.get("format") != _FORMAT:
        raise ValueError("configuration package fields or format are invalid")
    if canonical_bytes(document) != package.payload:
        raise ValueError("configuration package must use canonical JSON")
    _revision(_text(document["revision_id"]))
    for name in ("installation_key_digest", "input_digest"):
        if not _DIGEST.fullmatch(_text(document[name])):
            raise ValueError("configuration package digest is invalid")
    predecessor = document["predecessor_digest"]
    if predecessor is not None and not _DIGEST.fullmatch(_text(predecessor)):
        raise ValueError("configuration predecessor digest is invalid")
    if document["installation_key_digest"] != recipient_digest:
        raise ValueError("configuration package belongs to another installation key")
    _sealed_keys(document["sealed_keys"])
    validate_sealed_identifiers(_object(document["sealed"]), recipient_digest=recipient_digest)
    return document


def _validate_configuration(
    configuration: Mapping[str, object],
    schema: Mapping[str, object],
    release_version: str,
    sealed_keys: set[str],
) -> LayerResolution:
    if set(configuration) != {"schema", "environment", "entity_overrides"}:
        raise ValueError("configuration document fields are invalid")
    if canonical_bytes(configuration["schema"]) != canonical_bytes(schema):
        raise ValueError("configuration schema does not match the trusted Release schema")
    validate_release_configuration_schema(schema)
    defaults = {
        key: entry["default"]
        for key, raw_entry in schema.items()
        if "default" in (entry := _object(raw_entry))
    }
    validate_configuration_package_for_signing(
        {
            "defaults": defaults,
            "environment": configuration["environment"],
            "entity_overrides": configuration["entity_overrides"],
        }
    )
    overrides = configuration["entity_overrides"]
    if not isinstance(overrides, list | tuple):
        raise ValueError("configuration overrides must be a sequence")
    blocks = [_object(item) for item in overrides]
    for block in blocks:
        if set(block) != {"versions", "values"}:
            raise ValueError("configuration override fields are invalid")
        _reject_public_identifiers(block["values"], sealed_keys)
    _reject_public_identifiers(defaults, sealed_keys)
    _reject_public_identifiers(configuration["environment"], sealed_keys)
    return resolve_configuration_layers(
        release_version=release_version,
        configuration_schema=schema,
        environment_config=_object(configuration["environment"]),
        entity_overrides=blocks,
        sealed_keys=sealed_keys,
    )


def _reject_public_identifiers(value: object, sealed_keys: set[str]) -> None:
    if isinstance(value, Mapping):
        if sealed_keys.intersection(value):
            raise ValueError("sealed identifier belongs in the sealed section")
        for item in value.values():
            _reject_public_identifiers(item, sealed_keys)
    elif isinstance(value, list | tuple):
        for item in value:
            _reject_public_identifiers(item, sealed_keys)


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
