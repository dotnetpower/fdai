"""Consumer-side operational admission provider behind the unchanged ``admit`` seam.

It admits only records the verifier wrote under admitting registry pins, re-parses each record
with ``parse_decision_evidence_record``, rechecks the verifier binding and the separation
anchors on every call, and returns an attempt-scoped rejection only for the exact record an
attempt's response named. Everything else, including an older rejection, is unavailable.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

import psycopg
from fdai_service_contracts.operational_evidence import (
    OPERATIONAL_EVIDENCE_PURPOSES,
    OperationalEvidenceIssuanceResponse,
    OperationalEvidenceIssuanceStatus,
    OperationalEvidenceLookup,
    OperationalEvidenceRejectionRecord,
)
from pydantic import ValidationError

from fdai.core.operational_evidence.revision_history import RegistryHistory
from fdai.core.operational_evidence.trust_registry import DeploymentAnchors, purpose_defects
from fdai.delivery.persistence.postgres_operational_evidence import RetainedAdmissionRow
from fdai.delivery.persistence.state_store_decision_evidence import (
    DecisionEvidenceAdmissionRecordError,
    decision_evidence_lookup_digest,
    parse_decision_evidence_record,
)
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceAdmissionProvider,
    resolve_current_decision_evidence_admission,
)

_LOGGER = logging.getLogger(__name__)


class OperationalProofReader(Protocol):
    """SELECT-only proof-store reads a consumer needs."""

    async def newest_admissions(
        self, lookup_digest: str, pins_digests: frozenset[str], *, limit: int = 2
    ) -> tuple[RetainedAdmissionRow, ...]: ...

    async def rejection(
        self, *, record_digest: str, attempt_id: str
    ) -> Mapping[str, Any] | None: ...


class OperationalEvidenceAdmissionProvider:
    """Resolve verifier-issued admissions for the eleven operational purposes only."""

    def __init__(
        self,
        *,
        reader: OperationalProofReader,
        history: Callable[[], RegistryHistory | None],
        anchors: DeploymentAnchors,
        verifier_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._reader = reader
        self._history = history
        self._anchors = anchors
        self._verifier_id = verifier_id
        self._clock = clock or (lambda: datetime.now(UTC))

    async def admit(
        self,
        *,
        evidence_digest: str,
        scope_digest: str,
        purpose_id: str,
        source_revision: str,
    ) -> DecisionEvidenceAdmission | None:
        """Return one current, rebound admission or nothing; never raise for absence."""

        history = self._history()
        if purpose_id not in OPERATIONAL_EVIDENCE_PURPOSES or history is None:
            return None
        now = self._clock()
        trust = history.current.trust
        if purpose_defects(
            trust, self._anchors, purpose_id=purpose_id, verifier_id=self._verifier_id, at=now
        ):
            return None
        entry = trust.purpose(purpose_id)
        if entry is None:
            return None
        lookup = decision_evidence_lookup_digest(
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=purpose_id,
            source_revision=source_revision,
        )
        try:
            rows = await self._reader.newest_admissions(lookup, history.admitting_pins(), limit=2)
        except (OSError, RuntimeError, psycopg.Error) as exc:
            _LOGGER.warning(
                "operational_evidence_admission_unavailable",
                extra={"purpose_id": purpose_id, "error_type": type(exc).__name__},
            )
            return None
        for row in rows:
            try:
                retained = parse_decision_evidence_record(row.record)
            except DecisionEvidenceAdmissionRecordError:
                continue
            bundle = retained.verification_bundle
            binding = entry.binding(
                (bundle.verifier_id, bundle.verifier_version, bundle.trust_anchor_id)
            )
            # The record's own binding must still pass the readiness it passed at issuance
            # against the current anchors, whatever other bindings a rotation added.
            if (
                row.record.get("record_digest") != row.record_digest
                or retained.receipt.purpose_id != purpose_id
                or bundle.verifier_id != self._verifier_id
                or binding is None
                or not binding.window.active_at(now)
                or purpose_defects(
                    trust,
                    self._anchors,
                    purpose_id=purpose_id,
                    verifier_id=bundle.verifier_id,
                    at=now,
                    verifier_version=bundle.verifier_version,
                )
                or retained.receipt.source_identity not in entry.authoritative_source_ids()
            ):
                continue
            try:
                admission = resolve_current_decision_evidence_admission(
                    retained.admission,
                    expected_evidence_digest=evidence_digest,
                    expected_scope_digest=scope_digest,
                    expected_purpose_id=purpose_id,
                    expected_source_revision=source_revision,
                    evaluated_at=now,
                )
            except ValueError:
                continue
            if admission is not None:
                return admission
        return None

    async def outcome(
        self,
        response: OperationalEvidenceIssuanceResponse,
        *,
        lookup: OperationalEvidenceLookup,
    ) -> OperationalEvidenceRejectionRecord | None:
        """Return only the current rejection record this exact attempt named."""

        if (
            response.status is not OperationalEvidenceIssuanceStatus.REJECTED
            or response.record_digest is None
            or response.lookup_digest != lookup.lookup_digest
        ):
            return None
        try:
            raw = await self._reader.rejection(
                record_digest=response.record_digest, attempt_id=response.attempt_id
            )
        except (OSError, RuntimeError, psycopg.Error):
            return None
        if raw is None:
            return None
        try:
            record = OperationalEvidenceRejectionRecord.model_validate(raw)
        except (ValidationError, ValueError):
            return None
        history = self._history()
        if (
            history is None
            or record.record_digest != response.record_digest
            or record.attempt_id != response.attempt_id
            or record.lookup_digest != lookup.lookup_digest
            or record.purpose_id != lookup.purpose_id
            or record.verifier_id != self._verifier_id
            or (record.trust_registry_pin, record.grant_registry_pin)
            != (history.current.pins.trust_pin, history.current.pins.grant_pin)
            or not record.current_at(self._clock())
        ):
            return None
        return record


class PurposeRoutedAdmissionProvider:
    """Route the eleven operational purposes to the proof store and others to the fallback."""

    def __init__(
        self,
        *,
        operational: DecisionEvidenceAdmissionProvider,
        fallback: DecisionEvidenceAdmissionProvider | None,
    ) -> None:
        self._operational = operational
        self._fallback = fallback

    async def admit(
        self,
        *,
        evidence_digest: str,
        scope_digest: str,
        purpose_id: str,
        source_revision: str,
    ) -> DecisionEvidenceAdmission | None:
        provider = (
            self._operational if purpose_id in OPERATIONAL_EVIDENCE_PURPOSES else self._fallback
        )
        if provider is None:
            return None
        return await provider.admit(
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=purpose_id,
            source_revision=source_revision,
        )


__all__ = [
    "OperationalEvidenceAdmissionProvider",
    "OperationalProofReader",
    "PurposeRoutedAdmissionProvider",
]
