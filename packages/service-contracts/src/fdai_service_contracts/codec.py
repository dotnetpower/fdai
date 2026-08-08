"""Executable JSON codecs for independently packaged service boundaries."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai_service_contracts.compatibility import CompatibilityError
from fdai_service_contracts.schema import (
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
)

MAX_WIRE_BYTES = 256 * 1024


def encode_wire_object(payload: Mapping[str, Any]) -> bytes:
    """Canonically encode one JSON object and enforce the shared wire bound."""

    try:
        encoded = json.dumps(
            dict(payload),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise CompatibilityError("service contract must be canonical JSON") from exc
    if len(encoded) > MAX_WIRE_BYTES:
        raise CompatibilityError("encoded service contract exceeds 256 KiB")
    return encoded


@dataclass(frozen=True, slots=True)
class ProducerCodec:
    """Validate and canonically encode one contract release at a producer boundary."""

    contract_id: str
    release: str
    schema_version: str

    def encode(self, payload: Mapping[str, Any]) -> bytes:
        """Return one schema-valid canonical JSON object within the wire bound."""

        _validator().validate(self.contract_id, payload, version=self.schema_version)
        return encode_wire_object(payload)


@dataclass(frozen=True, slots=True)
class ConsumerCodec:
    """Decode and validate only versions accepted by one consumer release."""

    contract_id: str
    release: str
    accepted_versions: tuple[str, ...]

    def decode(self, encoded: bytes) -> dict[str, Any]:
        """Return a validated JSON object or fail closed before service logic."""

        if len(encoded) > MAX_WIRE_BYTES:
            raise CompatibilityError("encoded service contract exceeds 256 KiB")
        try:
            payload = json.loads(encoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CompatibilityError("service contract is not valid UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise CompatibilityError("service contract payload must be an object")
        version = payload.get("schema_version")
        if version not in self.accepted_versions:
            raise CompatibilityError(
                f"{self.contract_id} consumer {self.release} rejects version {version!r}"
            )
        _validator().validate(self.contract_id, payload, version=str(version))
        return payload

    def decode_mapping(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Validate an EventBus mapping through the same byte-bounded wire path."""

        return self.decode(encode_wire_object(payload))


def _validator() -> JsonSchemaContractValidator:
    return JsonSchemaContractValidator(PackageResourceSchemaRegistry())


__all__ = ["ConsumerCodec", "MAX_WIRE_BYTES", "ProducerCodec", "encode_wire_object"]
