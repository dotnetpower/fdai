"""Core verification gate for signed Operator request receipts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from fdai_service_contracts.operator_request_receipt import operator_request_public_key_from_seed

from fdai.agents import OperatorRequestReceiptGate
from fdai.delivery.operator_request_receipt import (
    CORE_OPERATOR_REQUEST_PRODUCER_ID,
    CORE_OPERATOR_REQUEST_PRODUCER_ID_ENV,
    CORE_OPERATOR_REQUEST_SIGNING_SEED_ENV,
)
from fdai.shared.providers.state_store import StateStore

OPERATOR_REQUEST_OPERATOR_TRUST_SEED_ENV = "FDAI_OPERATOR_REQUEST_OPERATOR_TRUST_SEED"
OPERATOR_REQUEST_OPERATOR_PRODUCER_ID_ENV = "FDAI_OPERATOR_REQUEST_OPERATOR_PRODUCER_ID"


def operator_request_receipt_gate(
    environment: Mapping[str, str],
    state_store: StateStore,
) -> OperatorRequestReceiptGate | None:
    core_seed = environment.get(CORE_OPERATOR_REQUEST_SIGNING_SEED_ENV, "").strip()
    operator_seed = environment.get(OPERATOR_REQUEST_OPERATOR_TRUST_SEED_ENV, "").strip()
    if not core_seed and not operator_seed:
        return None
    if not core_seed or not operator_seed:
        raise RuntimeError(
            "operator request receipt verification requires both Core and Operator seeds"
        )
    core_producer = environment.get(
        CORE_OPERATOR_REQUEST_PRODUCER_ID_ENV,
        CORE_OPERATOR_REQUEST_PRODUCER_ID,
    ).strip()
    operator_producer = environment.get(
        OPERATOR_REQUEST_OPERATOR_PRODUCER_ID_ENV,
        "operator-service",
    ).strip()
    if core_producer != CORE_OPERATOR_REQUEST_PRODUCER_ID:
        raise RuntimeError("Core operator_request receipts MUST sign as core-control-plane")
    if not operator_producer or operator_producer == core_producer:
        raise RuntimeError("Operator request receipt producer ids MUST be distinct")
    trusted_keys = {
        core_producer: operator_request_public_key_from_seed(core_seed),
        operator_producer: operator_request_public_key_from_seed(operator_seed),
    }
    return OperatorRequestReceiptGate(
        verifier=_UnboundOperatorReceiptVerifier(),
        state_store=state_store,
        clock=lambda: datetime.now(UTC),
        trusted_producer_public_keys=trusted_keys,
    )


class _UnboundOperatorReceiptVerifier:
    def verify_operator_request_receipt(self, *, receipt: object, signing_bytes: bytes) -> bool:
        del receipt, signing_bytes
        return False


__all__ = [
    "OPERATOR_REQUEST_OPERATOR_PRODUCER_ID_ENV",
    "OPERATOR_REQUEST_OPERATOR_TRUST_SEED_ENV",
    "operator_request_receipt_gate",
]
