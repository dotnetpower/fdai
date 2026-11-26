"""Core-side helpers for signed raw-ingress operator_request receipts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai_service_contracts.operator_request_receipt import sign_operator_request_receipt

CORE_OPERATOR_REQUEST_PRODUCER_ID = "core-control-plane"
CORE_OPERATOR_REQUEST_SIGNING_SEED_ENV = "FDAI_OPERATOR_REQUEST_CORE_SIGNING_SEED"
CORE_OPERATOR_REQUEST_PRODUCER_ID_ENV = "FDAI_OPERATOR_REQUEST_CORE_PRODUCER_ID"


@dataclass(frozen=True, slots=True)
class CoreOperatorRequestReceiptIssuer:
    """Issue signed receipts for Core-internal raw-topic proposals."""

    private_key_seed: str
    producer_service_identity: str = CORE_OPERATOR_REQUEST_PRODUCER_ID
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    lifetime: timedelta = timedelta(minutes=5)

    def attach(self, event: Mapping[str, Any]) -> dict[str, object]:
        """Return a copy of ``event`` with a receipt bound to its exact fields."""

        mutable = dict(event)
        issued_at = self.clock().astimezone(UTC)
        mutable["operator_request_receipt"] = sign_operator_request_receipt(
            mutable,
            producer_service_identity=self.producer_service_identity,
            private_key_seed=self.private_key_seed,
            issued_at=issued_at,
            expires_at=issued_at + self.lifetime,
        ).model_dump(mode="json")
        return mutable


def core_operator_request_receipt_issuer_from_env(
    environ: Mapping[str, str],
) -> CoreOperatorRequestReceiptIssuer | None:
    """Build the Core raw-topic signer only from an explicit seed binding."""

    seed = environ.get(CORE_OPERATOR_REQUEST_SIGNING_SEED_ENV, "").strip()
    if not seed:
        return None
    producer_id = environ.get(
        CORE_OPERATOR_REQUEST_PRODUCER_ID_ENV,
        CORE_OPERATOR_REQUEST_PRODUCER_ID,
    ).strip()
    if producer_id != CORE_OPERATOR_REQUEST_PRODUCER_ID:
        raise RuntimeError("Core operator_request receipts MUST sign as core-control-plane")
    return CoreOperatorRequestReceiptIssuer(private_key_seed=seed)


__all__ = [
    "CORE_OPERATOR_REQUEST_PRODUCER_ID",
    "CORE_OPERATOR_REQUEST_PRODUCER_ID_ENV",
    "CORE_OPERATOR_REQUEST_SIGNING_SEED_ENV",
    "CoreOperatorRequestReceiptIssuer",
    "core_operator_request_receipt_issuer_from_env",
]
