"""Authenticated notification publication receipt contract."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fdai_service_contracts.notification_receipt import (
    NOTIFICATION_DELIVERY_RECEIPT_SCHEMA,
    NOTIFICATION_DELIVERY_RECEIPT_SCHEMA_VERSION,
    NotificationDeliveryReceipt,
    NotificationReceiptAuthenticationError,
    NotificationReceiptFormatError,
    compute_receipt_signature,
    decode_notification_delivery_receipt,
    encode_notification_delivery_receipt,
    parse_receipt_body,
    verify_receipt_signature,
)
from fdai_service_contracts.schema import (
    ContractValidationError,
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
)

NOW = datetime(2026, 9, 4, 7, 0, tzinfo=UTC)
SECRET = "synthetic-receipt-secret"  # noqa: S105 - test fixture, not a credential


def _signed(body: bytes, *, at: datetime = NOW) -> dict[str, str]:
    timestamp = at.isoformat()
    return {
        "X-FDAI-Timestamp": timestamp,
        "X-FDAI-Signature": f"sha256={
            compute_receipt_signature(secret=SECRET, timestamp=timestamp, body=body)
        }",
    }


def _body(**overrides: object) -> bytes:
    payload: dict[str, object] = {
        "audit_id": "audit-1",
        "channel_id": "teams-ops",
        "publication_result": "published",
        "provider_message_id": "run-1",
    }
    payload.update(overrides)
    return json.dumps(payload, separators=(",", ":")).encode()


def test_valid_signature_parses_a_bounded_receipt() -> None:
    body = _body()

    verify_receipt_signature(secret=SECRET, headers=_signed(body), body=body, now=NOW)
    receipt = parse_receipt_body(body, observed_at=NOW)

    assert receipt.published is True
    assert receipt.provider_message_id == "run-1"
    assert receipt.idempotency_key == receipt.idempotency_key


def test_signature_mismatch_and_stale_timestamp_are_refused() -> None:
    body = _body()
    tampered = dict(_signed(body))
    tampered["X-FDAI-Signature"] = "sha256=deadbeef"

    with pytest.raises(NotificationReceiptAuthenticationError, match="mismatch"):
        verify_receipt_signature(secret=SECRET, headers=tampered, body=body, now=NOW)

    stale = _signed(body, at=NOW - timedelta(hours=1))
    with pytest.raises(NotificationReceiptAuthenticationError, match="window"):
        verify_receipt_signature(secret=SECRET, headers=stale, body=body, now=NOW)


def test_non_ascii_signature_is_refused_as_an_authentication_error() -> None:
    body = _body()
    malformed = dict(_signed(body))
    malformed["X-FDAI-Signature"] = "sha256=" + chr(0xE9) * 64

    with pytest.raises(NotificationReceiptAuthenticationError, match="mismatch"):
        verify_receipt_signature(secret=SECRET, headers=malformed, body=body, now=NOW)


def test_unsupported_body_fields_and_results_are_refused() -> None:
    with pytest.raises(NotificationReceiptFormatError, match="unsupported fields"):
        parse_receipt_body(_body(message="must not be carried"), observed_at=NOW)
    with pytest.raises(NotificationReceiptFormatError):
        parse_receipt_body(_body(publication_result="delivered"), observed_at=NOW)
    with pytest.raises(NotificationReceiptFormatError, match="limit"):
        parse_receipt_body(b"x" * 5000, observed_at=NOW)


def test_envelope_round_trips_and_validates_against_the_package_schema() -> None:
    receipt = parse_receipt_body(_body(), observed_at=NOW)
    payload = encode_notification_delivery_receipt(receipt)

    JsonSchemaContractValidator(PackageResourceSchemaRegistry()).validate(
        NOTIFICATION_DELIVERY_RECEIPT_SCHEMA,
        payload,
        version=NOTIFICATION_DELIVERY_RECEIPT_SCHEMA_VERSION,
    )

    assert decode_notification_delivery_receipt(payload) == receipt


def test_envelope_with_a_forged_receipt_id_is_refused() -> None:
    payload = encode_notification_delivery_receipt(parse_receipt_body(_body(), observed_at=NOW))
    payload["receipt_id"] = "0" * 64

    with pytest.raises(NotificationReceiptFormatError, match="receipt_id"):
        decode_notification_delivery_receipt(payload)


def test_schema_refuses_an_endpoint_bearing_envelope() -> None:
    payload = encode_notification_delivery_receipt(parse_receipt_body(_body(), observed_at=NOW))
    payload["webhook_url"] = "https://example.invalid/trigger"

    with pytest.raises(ContractValidationError):
        JsonSchemaContractValidator(PackageResourceSchemaRegistry()).validate(
            NOTIFICATION_DELIVERY_RECEIPT_SCHEMA,
            payload,
            version=NOTIFICATION_DELIVERY_RECEIPT_SCHEMA_VERSION,
        )


def test_receipt_requires_timezone_aware_observation() -> None:
    with pytest.raises(NotificationReceiptFormatError, match="timezone-aware"):
        NotificationDeliveryReceipt(
            audit_id="audit-1",
            channel_id="teams-ops",
            publication_result="published",
            observed_at=datetime(2026, 9, 4, 7, 0),  # noqa: DTZ001 - refusal under test
        )
