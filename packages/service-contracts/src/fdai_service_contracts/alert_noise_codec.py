"""Exact signed alert wire codecs; decoding is neither authentication nor readiness."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, NoReturn

from fdai_service_contracts.alert_noise_base import AlertContractBase
from fdai_service_contracts.alert_noise_content import canonical_alert_json
from fdai_service_contracts.alert_noise_wire import (
    SignedAlertCommand,
    SignedAlertReadiness,
    SignedAlertResult,
)
from fdai_service_contracts.codec import ConsumerCodec, ProducerCodec
from fdai_service_contracts.compatibility import CompatibilityError

ALERT_RESULT_WIRE_BYTES = 950_000
ALERT_WIRE_MODELS: Mapping[str, type[AlertContractBase]] = {
    "alert-noise-command": SignedAlertCommand,
    "alert-noise-result": SignedAlertResult,
    "alert-noise-readiness": SignedAlertReadiness,
}


class AlertUnavailable(AlertContractBase):
    """Offline N-1 capability marker; never publish or admit this as active traffic."""

    schema_version: Literal["0.0.0"]
    capability: Literal["unavailable"]


def _limit(contract_id: str) -> int:
    if contract_id not in ALERT_WIRE_MODELS:
        raise CompatibilityError("unknown alert wire contract")
    return ALERT_RESULT_WIRE_BYTES if contract_id == "alert-noise-result" else 16_384


def _encode(contract_id: str, payload: Mapping[str, Any]) -> bytes:
    try:
        encoded = canonical_alert_json(dict(payload)).encode("utf-8")
        if len(encoded) > _limit(contract_id):
            raise ValueError("alert wire bound exceeded")
        return encoded
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise CompatibilityError("alert wire must be bounded strict JSON") from None


def _validate(contract_id: str, payload: Mapping[str, Any], versions: tuple[str, ...]) -> None:
    """Pin the existing envelope shape, not a fabricated top-level version field.

    Command/result versions are inside their signed records; readiness is pinned by its
    closed kind and schema artifact. Unknown fields/versions are never dropped, and no
    caller can use the offline sentinel to obtain an authenticated runtime record.
    """
    version = "0.0.0" if payload.get("schema_version") == "0.0.0" else "1.0.0"
    if version not in versions:
        raise CompatibilityError("alert wire version is not accepted by this peer")
    try:
        model = AlertUnavailable if version == "0.0.0" else ALERT_WIRE_MODELS[contract_id]
        model.model_validate(payload)
    except (KeyError, ValueError, TypeError, RecursionError):
        raise CompatibilityError("alert wire does not match its exact schema") from None


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CompatibilityError("alert wire contains duplicate JSON keys")
        result[key] = value
    return result


def _constant(_: str) -> NoReturn:
    raise CompatibilityError("alert wire contains a non-finite number")


@dataclass(frozen=True, slots=True)
class AlertProducerCodec(ProducerCodec):
    """Encode one exact alert schema without re-signing or truncating the record."""

    def encode(self, payload: Mapping[str, Any]) -> bytes:
        encoded = _encode(self.contract_id, payload)
        _validate(self.contract_id, payload, (self.schema_version,))
        return encoded

    def encode_mapping(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Apply the identical byte/schema boundary before an EventBus mapping send."""
        value: dict[str, Any] = json.loads(self.encode(payload))
        return value


@dataclass(frozen=True, slots=True)
class AlertConsumerCodec(ConsumerCodec):
    """Decode strict bounded JSON; callers still verify signatures and exact lineage."""

    def decode(self, encoded: bytes) -> dict[str, Any]:
        if type(encoded) is not bytes or len(encoded) > _limit(self.contract_id):
            raise CompatibilityError("alert wire exceeds its byte bound")
        try:
            payload = json.loads(
                encoded.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant
            )
        except (ValueError, TypeError, RecursionError):
            raise CompatibilityError("alert wire must be strict UTF-8 JSON") from None
        if type(payload) is not dict:
            raise CompatibilityError("alert wire must contain an object")
        _encode(self.contract_id, payload)
        _validate(self.contract_id, payload, self.accepted_versions)
        return payload

    def decode_mapping(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Validate a bus mapping under alert bounds, not the generic 256 KiB limit."""
        return self.decode(_encode(self.contract_id, payload))
