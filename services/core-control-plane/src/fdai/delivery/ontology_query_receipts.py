"""Process-local issuer-backed trust for secured ontology query receipts."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryReceipt
from fdai.shared.contracts.models import OntologyReleaseRef


class HmacNetworkQueryReceiptAuthority:
    """Issue and verify query receipts in one opaque composition trust domain.

    Seals are intentionally process-local. A restart invalidates old seals and
    fails closed instead of accepting a receipt whose issuing process can no
    longer attest it. The HMAC key and opaque context never enter function
    arguments, logs, receipts, or persisted ontology state.
    """

    def __init__(
        self,
        *,
        key: bytes | None = None,
        max_receipts: int = 4096,
        max_receipt_age: timedelta = timedelta(minutes=10),
        max_future_skew: timedelta = timedelta(minutes=1),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        secret = key or secrets.token_bytes(32)
        if len(secret) < 32:
            raise ValueError("network query receipt authority key MUST contain at least 32 bytes")
        if not 1 <= max_receipts <= 65536:
            raise ValueError("network query receipt authority capacity MUST be bounded")
        if max_receipt_age <= timedelta(0) or max_future_skew < timedelta(0):
            raise ValueError("network query receipt authority time bounds are invalid")
        self._key = bytes(secret)
        self._max_receipts = max_receipts
        self._max_receipt_age = max_receipt_age
        self._max_future_skew = max_future_skew
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._context = object()
        self._seals: OrderedDict[str, bytes] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def verification_context(self) -> object:
        """Return the opaque context accepted by this authority's verifier."""

        return self._context

    def issue(self, receipt: SecuredObjectSetQueryReceipt) -> None:
        """Seal one gateway-created receipt after current-time validation."""

        copied = SecuredObjectSetQueryReceipt.model_validate(receipt.model_dump(mode="json"))
        now = self._now()
        cutoff = copied.observation_cutoff.astimezone(UTC)
        if not now - self._max_receipt_age <= cutoff <= now + self._max_future_skew:
            raise ValueError("network query receipt cutoff is stale or future-skewed")
        digest = _receipt_digest(copied)
        seal = hmac.digest(self._key, digest.encode("ascii"), "sha256")
        with self._lock:
            self._seals[digest] = seal
            self._seals.move_to_end(digest)
            while len(self._seals) > self._max_receipts:
                self._seals.popitem(last=False)

    def verify(
        self,
        *,
        receipt: SecuredObjectSetQueryReceipt,
        invocation_context: FunctionInvocationContext,
        expected_release: OntologyReleaseRef,
        expected_purpose: str,
        expected_result_digest: str,
        verification_context: object,
    ) -> bool:
        """Authenticate one exact receipt and invocation tuple without I/O."""

        try:
            copied = SecuredObjectSetQueryReceipt.model_validate(receipt.model_dump(mode="json"))
            now = self._now()
        except (TypeError, ValueError):
            return False
        cutoff = copied.observation_cutoff.astimezone(UTC)
        if (
            verification_context is not self._context
            or copied.ontology_release != expected_release
            or copied.purpose != expected_purpose
            or copied.projected_result_digest != expected_result_digest
            or copied.caller_role != invocation_context.caller_role
            or invocation_context.purposes != (expected_purpose,)
            or invocation_context.evidence_refs != (expected_result_digest,)
            or not now - self._max_receipt_age <= cutoff <= now + self._max_future_skew
        ):
            return False
        digest = _receipt_digest(copied)
        expected_seal = hmac.digest(self._key, digest.encode("ascii"), "sha256")
        with self._lock:
            seal = self._seals.get(digest)
            if seal is not None:
                self._seals.move_to_end(digest)
        return seal is not None and hmac.compare_digest(seal, expected_seal)

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise TypeError("network query receipt authority clock MUST return an aware datetime")
        return value.astimezone(UTC)


def _receipt_digest(receipt: SecuredObjectSetQueryReceipt) -> str:
    encoded = json.dumps(
        receipt.model_dump(mode="json"),
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["HmacNetworkQueryReceiptAuthority"]
