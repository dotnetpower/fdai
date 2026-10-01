"""Signed Operator-to-Core request receipt contract."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.executor_models import ContractBase, Digest

_MAX_RECEIPT_LIFETIME = timedelta(minutes=15)


class OperatorRequestReceiptBody(ContractBase):
    """Bound facts the Operator signs before a request enters Core ingress."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    idempotency_key: Annotated[str, Field(min_length=1, max_length=512)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=512)]
    initiator_principal: Annotated[str, Field(min_length=1, max_length=512)]
    action_type: Annotated[str, Field(min_length=1, max_length=512)]
    canonical_params_digest: Digest
    resource_id: Annotated[str, Field(min_length=1, max_length=512)]
    producer_service_identity: Annotated[str, Field(min_length=1, max_length=512)]
    issued_at: datetime
    expires_at: datetime

    @field_validator("issued_at", "expires_at")
    @classmethod
    def _normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("operator request receipt time MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _bounded_validity(self) -> OperatorRequestReceiptBody:
        if not self.issued_at < self.expires_at <= self.issued_at + _MAX_RECEIPT_LIFETIME:
            raise ValueError("operator request receipt validity MUST be positive and bounded")
        return self


class OperatorRequestReceipt(OperatorRequestReceiptBody):
    """Signed immutable receipt. Possession alone grants no execution authority."""

    receipt_digest: Digest
    signature_alg: Literal["Ed25519"] = "Ed25519"
    signature: Annotated[str, Field(min_length=1, max_length=512)]

    @model_validator(mode="after")
    def _digest_matches(self) -> OperatorRequestReceipt:
        expected = operator_request_receipt_digest(
            OperatorRequestReceiptBody.model_validate(
                self.model_dump(
                    mode="json", exclude={"receipt_digest", "signature_alg", "signature"}
                )
            )
        )
        if self.receipt_digest != expected:
            raise ValueError("operator request receipt digest mismatched")
        try:
            base64.b64decode(self.signature.encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError) as exc:
            raise ValueError("operator request receipt signature MUST be base64") from exc
        return self

    @classmethod
    def create(
        cls,
        *,
        body: OperatorRequestReceiptBody,
        signature: bytes,
    ) -> OperatorRequestReceipt:
        """Attach a signature to a validated body and compute its digest."""

        payload = body.model_dump(mode="json")
        return cls.model_validate(
            {
                **payload,
                "receipt_digest": operator_request_receipt_digest(body),
                "signature_alg": "Ed25519",
                "signature": base64.b64encode(signature).decode("ascii"),
            }
        )

    def signature_bytes(self) -> bytes:
        """Return the decoded signature for an injected verifier."""

        return base64.b64decode(self.signature.encode("ascii"), validate=True)


def canonical_params_digest(params: Mapping[str, Any] | None) -> str:
    """Return the stable digest for the exact operator request params."""

    return canonical_digest(dict(params or {}))


def operator_request_receipt_digest(body: OperatorRequestReceiptBody) -> str:
    """Return the content digest covered by the receipt signature."""

    return canonical_digest(body.model_dump(mode="json"))


def operator_request_receipt_signing_bytes(body: OperatorRequestReceiptBody) -> bytes:
    """Return the canonical bytes an Ed25519 signer/verifier covers."""

    return operator_request_receipt_digest(body).encode("ascii")


def operator_request_public_key_from_seed(seed: str) -> str:
    """Return the URL-safe raw Ed25519 public key for one configured seed."""

    return _b64url_no_padding(
        _private_key_from_seed(seed).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
    )


def sign_operator_request_receipt(
    event: Mapping[str, Any],
    *,
    producer_service_identity: str,
    private_key_seed: str,
    issued_at: datetime,
    expires_at: datetime,
) -> OperatorRequestReceipt:
    """Create a receipt from the same seed shape used by deployment secrets."""

    body = operator_request_receipt_body_from_event(
        event,
        producer_service_identity=producer_service_identity,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    signature = _private_key_from_seed(private_key_seed).sign(
        operator_request_receipt_signing_bytes(body)
    )
    return OperatorRequestReceipt.create(body=body, signature=signature)


def verify_operator_request_receipt_with_public_key(
    *,
    receipt: OperatorRequestReceipt,
    signing_bytes: bytes,
    public_key: str,
) -> bool:
    """Verify a receipt with one URL-safe raw Ed25519 public key."""

    try:
        Ed25519PublicKey.from_public_bytes(_b64url_decode(public_key)).verify(
            receipt.signature_bytes(),
            signing_bytes,
        )
    except (InvalidSignature, ValueError):
        return False
    return True


def operator_request_receipt_body_from_event(
    event: Mapping[str, Any],
    *,
    producer_service_identity: str,
    issued_at: datetime,
    expires_at: datetime,
) -> OperatorRequestReceiptBody:
    """Build a receipt body from a flat raw-ingress operator request."""

    return OperatorRequestReceiptBody.model_validate(
        {
            "idempotency_key": event.get("idempotency_key"),
            "correlation_id": event.get("correlation_id"),
            "initiator_principal": event.get("initiator_principal"),
            "action_type": event.get("action_type"),
            "canonical_params_digest": canonical_params_digest(
                event.get("params") if isinstance(event.get("params"), Mapping) else None
            ),
            "resource_id": event.get("resource_id"),
            "producer_service_identity": producer_service_identity,
            "issued_at": issued_at,
            "expires_at": expires_at,
        }
    )


__all__ = [
    "OperatorRequestReceipt",
    "OperatorRequestReceiptBody",
    "canonical_params_digest",
    "operator_request_receipt_body_from_event",
    "operator_request_receipt_digest",
    "operator_request_receipt_signing_bytes",
    "operator_request_public_key_from_seed",
    "sign_operator_request_receipt",
    "verify_operator_request_receipt_with_public_key",
]


def _private_key_from_seed(seed: str) -> Ed25519PrivateKey:
    raw = _b64url_decode(seed)
    if len(raw) != 32:
        raise ValueError("operator request signing seed MUST decode to 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(raw)


def _b64url_decode(value: str) -> bytes:
    trimmed = value.strip()
    padding = "=" * (-len(trimmed) % 4)
    return base64.urlsafe_b64decode((trimmed + padding).encode("ascii"))


def _b64url_no_padding(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
