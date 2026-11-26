"""Local-only configuration packaging; file inputs never establish operational trust."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey

from fdai_deployment_cli.cli_help import command, command_group
from fdai_deployment_cli.lifecycle_configuration_artifact import (
    configuration_artifact_bytes as _encode,
    read_configuration_artifact as _decode,
)
from fdai_deployment_cli.lifecycle_configuration_entities import (
    EntityConfigurationInput,
    InstallationConfigurationInput,
    validate_entity_ids,
)
from fdai_deployment_cli.lifecycle_configuration_package import (
    ConfigurationPackageInput,
    SignedConfigurationPackage,
    build_configuration_package,
    build_installation_configuration_package,
    verify_configuration_package,
    verify_installation_configuration_package,
)
from fdai_deployment_cli.lifecycle_configuration_publication_cli import (
    register_publication_commands,
)
from fdai_deployment_cli.lifecycle_configuration_sealing import encryption_key_digest, read_object
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes

_MAX_INPUT = 1024 * 1024
_MAX_ARTIFACT = 2 * _MAX_INPUT
_MAX_HISTORY = 256


def register_configuration_commands(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Expose offline artifacts only, without enrollment, import, decryption or activation."""
    group = command(
        commands,
        "configuration",
        "Build, verify or publish local signed configuration packages",
        epilog="Local files only. No trust registration, qualified Release or deployment is created.",
    )
    operations = command_group(group)
    for operation in ("build", "verify"):
        parser = command(
            operations, operation, f"{operation.title()} one local configuration package"
        )
        for name, help_text in (
            (
                "release-input",
                "Independent JSON Release/schema, sealed keys and optional opaque Entity selection",
            ),
            ("configuration-key", "Independently supplied Ed25519 verification key in PEM format"),
            (
                "installation-key",
                "Explicitly supplied installation X25519 public key in PEM format",
            ),
        ):
            parser.add_argument(
                f"--{name}", type=Path, required=True, metavar="PRIVATE_FILE", help=help_text
            )
        parser.add_argument(
            "--history",
            type=Path,
            action="append",
            default=[],
            metavar="ACCEPTED_PACKAGE",
            help="Complete accepted chain, oldest first; repeat once per package (maximum 256)",
        )
        head = parser.add_mutually_exclusive_group(required=True)
        head.add_argument(
            "--initial-revision",
            action="store_true",
            help="Explicitly assert an empty accepted chain",
        )
        head.add_argument(
            "--expected-predecessor", help="Independently retained accepted head SHA-256"
        )
        if operation == "build":
            parser.add_argument(
                "--input",
                type=Path,
                required=True,
                metavar="PRIVATE_FILE",
                help="Private JSON revision, environment, Entity override blocks and sealed identifiers",
            )
            parser.add_argument(
                "--signing-key",
                type=Path,
                required=True,
                metavar="PRIVATE_PEM_FILE",
                help="Private unencrypted PKCS8 Ed25519 PEM file; never supply key bytes in argv",
            )
            parser.add_argument(
                "--destination",
                type=Path,
                required=True,
                metavar="NEW_PRIVATE_FILE",
                help="New absolute mode-0600 file in an existing private mode-0700 directory",
            )
        else:
            parser.add_argument(
                "--package",
                type=Path,
                required=True,
                metavar="PRIVATE_FILE",
                help="Existing signed configuration file to verify; no import or activation",
            )
        parser.add_argument("--output", choices=("text", "json"), default="text")
        parser.set_defaults(handler=_run, configuration_operation=operation)
    register_publication_commands(operations, _execute)


def _run(args: argparse.Namespace) -> int:
    """Suppress input-derived diagnostics; success follows independent reader verification."""
    try:
        package = _execute(args)
    except (ValueError, TypeError, OSError, OverflowError, RecursionError, UnsupportedAlgorithm):
        raise ValueError(
            "configuration operation refused; check private file permissions, input shapes, "
            "independent keys/Release inputs, complete history and a new destination"
        ) from None
    result = {
        "operation": args.configuration_operation,
        "package_digest": package.digest,
        "verified": True,
        "local_only": True,
        "trust_registered": False,
        "deployment_activated": False,
        "production_release_eligibility": "unverified",
    }
    print(
        json.dumps(result, sort_keys=True)
        if args.output == "json"
        else f"verified local configuration package sha256={package.digest}; no deployment or trust change"
    )
    return 0


def _execute(
    args: argparse.Namespace,
    *,
    retained_history: Sequence[SignedConfigurationPackage] | None = None,
    retained_package: SignedConfigurationPackage | None = None,
    persist_output: bool = True,
) -> SignedConfigurationPackage:
    release = read_object(_read(args.release_input))
    multi_entity = "entity_ids" in release
    _fields(
        release,
        {"release_version", "configuration_schema", "sealed_keys"}
        | ({"entity_ids", "release_digest"} if multi_entity else set()),
    )
    version = _text(release["release_version"])
    schema = _object(release["configuration_schema"])
    keys = release["sealed_keys"]
    if not isinstance(keys, list) or any(not isinstance(key, str) or not key for key in keys):
        raise ValueError("sealed keys must be nonempty strings")
    sealed_keys = frozenset(_text(key) for key in keys)
    if len(sealed_keys) != len(keys):
        raise ValueError("sealed keys must be unique")
    entity_ids = _entity_ids(release["entity_ids"]) if multi_entity else frozenset()
    public_key = serialization.load_pem_public_key(_read(args.configuration_key, limit=16384))
    recipient = serialization.load_pem_public_key(_read(args.installation_key, limit=16384))
    if not isinstance(public_key, Ed25519PublicKey) or not isinstance(recipient, X25519PublicKey):
        raise ValueError("configuration signing and installation encryption key types are invalid")
    if len(args.history) > _MAX_HISTORY:
        raise ValueError("configuration history exceeds its bound")
    history = (
        list(retained_history)
        if retained_history is not None
        else [_decode(_read(path, limit=_MAX_ARTIFACT)) for path in args.history]
    )
    if len(history) > _MAX_HISTORY:
        raise ValueError("configuration history exceeds its bound")
    head = history[-1].digest if history else None
    if args.initial_revision:
        if history:
            raise ValueError("initial revision cannot have accepted history")
    elif head is None or args.expected_predecessor != head:
        raise ValueError("accepted history does not match the independently retained head")
    if args.configuration_operation == "build":
        private_key = serialization.load_pem_private_key(
            _read(args.signing_key, limit=16384), password=None
        )
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("configuration signing key must be Ed25519")
        if private_key.public_key().public_bytes_raw() != public_key.public_bytes_raw():
            raise ValueError("signing key does not match the independent verification key")
        source = read_object(_read(args.input))
        if multi_entity:
            _fields(source, {"revision_id", "environment", "entities", "sealed"})
            package = build_installation_configuration_package(
                InstallationConfigurationInput(
                    revision_id=_text(source["revision_id"]),
                    release_version=version,
                    release_digest=_text(release["release_digest"]),
                    configuration_schema=schema,
                    environment_config=_object(source["environment"]),
                    entities=_entities(source["entities"]),
                    sealed_values=_object(source["sealed"]),
                    sealed_keys=sealed_keys,
                ),
                entity_ids=entity_ids,
                signing_key=private_key,
                installation_key=recipient,
                history=history,
            )
        else:
            _fields(source, {"revision_id", "environment", "entity_overrides", "sealed"})
            package = build_configuration_package(
                ConfigurationPackageInput(
                    revision_id=_text(source["revision_id"]),
                    release_version=version,
                    configuration_schema=schema,
                    environment_config=_object(source["environment"]),
                    entity_overrides=_overrides(source["entity_overrides"]),
                    sealed_values=_object(source["sealed"]),
                    sealed_keys=sealed_keys,
                ),
                signing_key=private_key,
                installation_key=recipient,
                history=history,
            )
    else:
        package = (
            retained_package
            if retained_package is not None
            else _decode(_read(args.package, limit=_MAX_ARTIFACT))
        )
    if multi_entity:
        verify_installation_configuration_package(
            package,
            configuration_key=public_key,
            installation_key_digest=encryption_key_digest(recipient),
            configuration_schema=schema,
            sealed_keys=sealed_keys,
            entity_ids=entity_ids,
            release_version=version,
            release_digest=_text(release["release_digest"]),
            history=history,
        )
    else:
        verify_configuration_package(
            package,
            configuration_key=public_key,
            installation_key_digest=encryption_key_digest(recipient),
            configuration_schema=schema,
            sealed_keys=sealed_keys,
            history=history,
        )
    if read_object(package.payload)["release_version"] != version:
        raise ValueError("package does not match the expected Release")
    if args.configuration_operation == "build" and persist_output:
        content = _encode(package)
        write_private_bytes(args.destination, content)
        if read_private_bytes(args.destination, max_bytes=_MAX_ARTIFACT) != content:
            raise ValueError("configuration artifact readback does not match")
    return package


def _read(path: Path, *, limit: int = _MAX_INPUT) -> bytes:
    return read_private_bytes(path, max_bytes=limit)


def _entity_ids(value: object) -> frozenset[str]:
    if not isinstance(value, list):
        raise ValueError("selected Entities must be an array")
    ids = frozenset(_text(item) for item in value)
    if len(ids) != len(value):
        raise ValueError("selected Entities must be unique")
    validate_entity_ids(ids)
    return ids


def _overrides(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("entity overrides must be an array")
    return [_object(block) for block in value]


def _entities(value: object) -> list[EntityConfigurationInput]:
    if not isinstance(value, list):
        raise ValueError("Entities must be an array")
    result = []
    for raw in value:
        entry = _fields(_object(raw), {"entity_id", "entity_overrides", "sealed"})
        result.append(
            EntityConfigurationInput(
                entity_id=_text(entry["entity_id"]),
                entity_overrides=_overrides(entry["entity_overrides"]),
                sealed_values=_object(entry["sealed"]),
            )
        )
    return result


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("configuration field must be an object")
    return {str(key): item for key, item in value.items()}


def _fields(document: dict[str, object], fields: set[str]) -> dict[str, object]:
    if set(document) != fields:
        raise ValueError("configuration input fields are invalid")
    return document


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("configuration field must be nonempty text")
    return value
