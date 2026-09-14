"""Decode exact private alert records and retain their independent evidence admissions."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from fdai_service_contracts.decision_evidence import (
    DecisionCriticalEvidenceReceipt,
    EvidenceConflictStatus,
)
from fdai_service_contracts.ontology_query import content_digest
from pydantic import BaseModel

from fdai.core.detection.alert_noise.execution import AlertExecutionHeld
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceAdmissionProvider,
    assess_decision_evidence_admission,
)
from fdai.shared.providers.state_store import StateStore

_DIGEST = re.compile(r"sha256:[a-f0-9]{64}")
_REF = re.compile(r"[a-z][a-z0-9_.:-]{0,159}")
_SOURCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,511}")


def _json(value: object) -> str:
    """Detach bounded JSON without coercing keys, scalar types, or non-JSON objects."""
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > 32 or count > 100_000:
            raise AlertExecutionHeld("alert_record_bound_exceeded")
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise AlertExecutionHeld("alert_record_invalid")
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif item is not None and type(item) not in {str, bool, int, float}:
            raise AlertExecutionHeld("alert_record_invalid")
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    if len(encoded) > 2_000_000:
        raise AlertExecutionHeld("alert_record_bound_exceeded")
    return encoded


def exact_alert_model[Model: BaseModel](model: type[Model], value: object) -> Model:
    """Decode a complete canonical JSON record; defaults and coercion cannot repair claims."""
    try:
        decoded = model.model_validate(value)
        if _json(value) != _json(decoded.model_dump(mode="json")):
            raise AlertExecutionHeld("alert_record_not_canonical")
        return decoded
    except AlertExecutionHeld:
        raise
    except Exception:
        raise AlertExecutionHeld("alert_record_invalid") from None


def alert_scope_digest(*, tenant_ref: str, scope_ref: str) -> str:
    """Bind an admission to exact opaque tenant and scope references, without normalization."""
    if any(type(ref) is not str or _REF.fullmatch(ref) is None for ref in (tenant_ref, scope_ref)):
        raise ValueError("alert scope references MUST be exact opaque references")
    return content_digest({"tenant_ref": tenant_ref, "scope_ref": scope_ref})


@dataclass(frozen=True, slots=True)
class AdmittedAlertRecord:
    """Detached private record and its shared admission; source identities stay out of repr."""

    _record_json: str = field(repr=False)
    _receipt: DecisionCriticalEvidenceReceipt = field(repr=False)
    admission: DecisionEvidenceAdmission
    _key: str = field(repr=False)

    @property
    def payload(self) -> dict[str, Any]:
        """Return a detached JSON payload, never an alias into the authoritative store."""
        return dict(json.loads(self._record_json)["payload"])

    @property
    def receipt_digest(self) -> str:
        """Expose the receipt content address, not its private authenticated source identity."""
        return self._receipt.receipt_digest

    def matches(self, raw: Mapping[str, Any] | None) -> bool:
        """Compare exact retained bytes; a replaced or in-place-mutated record is not current."""
        return raw is not None and _json(dict(raw)) == self._record_json

    async def require_unchanged(self, store: StateStore) -> None:
        """Re-read the original key after I/O; callers still recheck the trusted clock."""
        if not self.matches(await store.read_state(self._key)):
            raise AlertExecutionHeld("alert_record_changed")

    def require_current(self, *, now: datetime) -> None:
        """Recheck receipt and admission intervals after I/O; this never renews either proof."""
        receipt, admission = self._receipt, self.admission
        if (
            now.tzinfo is None
            or now.utcoffset() is None
            or not receipt.recorded_at <= admission.verified_at <= now < admission.valid_until
            or admission.valid_until > receipt.fresh_until
            or admission.receipt_digest != receipt.receipt_digest
            or admission.execution_authority is not False
            or admission.promotion_authority is not False
            or assess_decision_evidence_admission(
                admission,
                expected_evidence_digest=receipt.evidence_digest,
                expected_scope_digest=receipt.scope_digest,
                expected_purpose_id=receipt.purpose_id,
                expected_source_revision=receipt.source_revision,
                evaluated_at=now,
            )
        ):
            raise AlertExecutionHeld("alert_record_admission_mismatch")


async def read_admitted_alert_record(
    store: StateStore,
    admissions: DecisionEvidenceAdmissionProvider | None,
    key: str,
    purpose: str,
    scope_digest: str,
    source_revision: str,
    now: datetime,
) -> AdmittedAlertRecord | None:
    """Read exact ``{payload, receipt}`` JSON and independently admit its complete content.

    Absence of the record or admission returns None. Malformation, conflict, replacement,
    synthetic evidence and I/O failure raise a content-free hold. The shared content_digest
    also imposes its existing 64-KiB payload ceiling inside the 2-MB outer-record limit.
    Callers must recheck require_current with their trusted clock after subsequent awaits.
    """
    try:
        if (
            type(key) is not str
            or not key.startswith("alert-noise:")
            or len(key) > 1024
            or re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", purpose) is None
            or _DIGEST.fullmatch(scope_digest) is None
            or _SOURCE.fullmatch(source_revision) is None
            or now.tzinfo is None
            or now.utcoffset() is None
        ):
            raise AlertExecutionHeld("alert_record_lookup_invalid")
        async with asyncio.timeout(10):
            raw = await store.read_state(key)
            if raw is None or admissions is None:
                return None
            encoded = _json(dict(raw))
            detached = json.loads(encoded)
            if set(detached) != {"payload", "receipt"} or type(detached["payload"]) is not dict:
                raise AlertExecutionHeld("alert_record_shape_invalid")
            receipt_raw = detached["receipt"]
            if (
                type(receipt_raw) is not dict
                or receipt_raw.get("synthetic") is not False
                or receipt_raw.get("execution_authority") is not False
            ):
                raise AlertExecutionHeld("alert_record_receipt_invalid")
            receipt = exact_alert_model(DecisionCriticalEvidenceReceipt, receipt_raw)
            digest = content_digest(detached["payload"])
            if (
                receipt.evidence_digest != digest
                or receipt.scope_digest != scope_digest
                or receipt.purpose_id != purpose
                or receipt.source_revision != source_revision
                or receipt.completeness_basis_points != 10_000
                or receipt.conflict_status is not EvidenceConflictStatus.CLEAR
                or not receipt.recorded_at <= now < receipt.fresh_until
            ):
                raise AlertExecutionHeld("alert_record_receipt_mismatch")
            admission = await admissions.admit(
                evidence_digest=digest,
                scope_digest=scope_digest,
                purpose_id=purpose,
                source_revision=source_revision,
            )
            if admission is None:
                return None
            if type(admission) is not DecisionEvidenceAdmission:
                raise AlertExecutionHeld("alert_record_admission_invalid")
            admission = DecisionEvidenceAdmission(**asdict(admission))
            result = AdmittedAlertRecord(encoded, receipt, admission, key)
            await result.require_unchanged(store)
            result.require_current(now=now)
            return result
    except AlertExecutionHeld:
        raise
    except Exception:
        raise AlertExecutionHeld("alert_record_unavailable") from None
