"""Signed Operator-to-Core request receipt contract."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, override

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import Field, field_validator, model_serializer, model_validator

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.executor_models import ContractBase, Digest

_MAX_RECEIPT_LIFETIME = timedelta(minutes=15)
_WORKFLOW_ACTION_ABSENT_SENTINEL = "__fdai_operator_request_workflow_action_absent__"


_RECEIPT_SCHEMA_VERSION = Literal["1.0.0", "1.1.0", "1.2.0"]


class OperatorRequestReceiptBody(ContractBase):
    """Bound facts the Operator signs before a request enters Core ingress."""

    schema_version: _RECEIPT_SCHEMA_VERSION = "1.1.0"
    idempotency_key: Annotated[str, Field(min_length=1, max_length=512)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=512)]
    initiator_principal: Annotated[str, Field(min_length=1, max_length=512)]
    action_type: Annotated[str, Field(min_length=1, max_length=512)]
    canonical_params_digest: Digest
    resource_id: Annotated[str, Field(min_length=1, max_length=512)]
    canonical_workflow_action_digest: Digest | None = None
    producer_service_identity: Annotated[str, Field(min_length=1, max_length=512)]
    issued_at: datetime
    expires_at: datetime
    authenticated_at: datetime | None = None
    principal_roles: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...] = ()
    max_auth_age_seconds: int | None = None

    @field_validator("issued_at", "expires_at", "authenticated_at")
    @classmethod
    def _normalize_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("operator request receipt time MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _bounded_validity(self) -> OperatorRequestReceiptBody:
        if not self.issued_at < self.expires_at <= self.issued_at + _MAX_RECEIPT_LIFETIME:
            raise ValueError("operator request receipt validity MUST be positive and bounded")
        if self.schema_version == "1.0.0" and self.canonical_workflow_action_digest is not None:
            raise ValueError("operator request receipt v1.0 MUST NOT bind workflow action")
        if self.schema_version == "1.1.0" and self.canonical_workflow_action_digest is None:
            raise ValueError("operator request receipt v1.1 MUST bind workflow action digest")
        if self.schema_version in {"1.0.0", "1.1.0"}:
            if (
                self.authenticated_at is not None
                or self.principal_roles
                or self.max_auth_age_seconds is not None
            ):
                raise ValueError("operator request receipt v1.0/v1.1 MUST NOT bind auth context")
        elif (
            self.authenticated_at is None
            or not self.principal_roles
            or self.max_auth_age_seconds is None
            or self.max_auth_age_seconds <= 0
            or self.max_auth_age_seconds > 3600
        ):
            raise ValueError("operator request receipt v1.2 MUST bind bounded auth context")
        if self.principal_roles != tuple(sorted(set(self.principal_roles))):
            raise ValueError("operator request receipt principal_roles MUST be unique and ordered")
        return self

    @override
    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        exclude = set(kwargs.pop("exclude", set()) or set())
        if self.schema_version in {"1.0.0", "1.1.0"}:
            exclude.update({"authenticated_at", "principal_roles", "max_auth_age_seconds"})
        return super().model_dump(*args, exclude=exclude, **kwargs)

    @override
    def model_dump_json(self, *args: Any, **kwargs: Any) -> str:
        exclude = set(kwargs.pop("exclude", set()) or set())
        if self.schema_version in {"1.0.0", "1.1.0"}:
            exclude.update({"authenticated_at", "principal_roles", "max_auth_age_seconds"})
        return super().model_dump_json(*args, exclude=exclude, **kwargs)

    @model_serializer(mode="wrap")
    def _serialize_without_new_auth_fields_for_legacy_versions(self, handler: Any) -> Any:
        data = handler(self)
        if self.schema_version in {"1.0.0", "1.1.0"} and isinstance(data, dict):
            data.pop("authenticated_at", None)
            data.pop("principal_roles", None)
            data.pop("max_auth_age_seconds", None)
        return data


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

        payload = _receipt_body_payload(body)
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


def canonical_workflow_action_digest(workflow_action: Mapping[str, Any] | None) -> str:
    """Return the stable digest for optional workflow lineage presence and content."""

    if workflow_action is None:
        return canonical_digest({"presence": _WORKFLOW_ACTION_ABSENT_SENTINEL})
    return canonical_digest({"presence": "present", "workflow_action": dict(workflow_action)})


def operator_request_receipt_digest(body: OperatorRequestReceiptBody) -> str:
    """Return the content digest covered by the receipt signature."""

    return canonical_digest(_receipt_body_payload(body))


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
    schema_version: str = "1.1.0",
) -> OperatorRequestReceiptBody:
    """Build a receipt body from a flat raw-ingress operator request."""

    if "operator_request_receipt_schema_version" in event:
        schema_version = str(event["operator_request_receipt_schema_version"])
    workflow_action = event.get("workflow_action")
    workflow_action_digest = (
        canonical_workflow_action_digest(
            workflow_action if isinstance(workflow_action, Mapping) else None
        )
        if schema_version in {"1.1.0", "1.2.0"}
        else None
    )
    values = {
        "schema_version": schema_version,
        "idempotency_key": event.get("idempotency_key"),
        "correlation_id": event.get("correlation_id"),
        "initiator_principal": event.get("initiator_principal"),
        "action_type": event.get("action_type"),
        "canonical_params_digest": canonical_params_digest(
            event.get("params") if isinstance(event.get("params"), Mapping) else None
        ),
        "resource_id": event.get("resource_id"),
        "canonical_workflow_action_digest": workflow_action_digest,
        "producer_service_identity": producer_service_identity,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
    if schema_version == "1.2.0":
        values["authenticated_at"] = event.get("authenticated_at")
        values["principal_roles"] = tuple(
            str(role) for role in event.get("principal_roles", ()) if isinstance(role, str)
        )
        values["max_auth_age_seconds"] = event.get("max_auth_age_seconds")
    return OperatorRequestReceiptBody.model_validate(values)


def _receipt_body_payload(body: OperatorRequestReceiptBody) -> dict[str, Any]:
    excluded = {"authenticated_at", "principal_roles", "max_auth_age_seconds"}
    if body.schema_version == "1.2.0":
        excluded = set()
    return body.model_dump(mode="json", exclude=excluded)


__all__ = [
    "OperatorRequestReceipt",
    "OperatorRequestReceiptBody",
    "canonical_params_digest",
    "canonical_workflow_action_digest",
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
