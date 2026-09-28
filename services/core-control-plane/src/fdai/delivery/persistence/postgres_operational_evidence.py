"""Insert-only PostgreSQL operational evidence proof store.

The verifier's database role is the only writer: a trigger refuses every insert by another role,
and further triggers refuse every update, delete, and truncate. Consumer roles hold SELECT only.
A grants readback reports ``self_verified`` whenever another role could write proofs.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceStatus,
    OperationalEvidenceRejectionRecord,
)
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.core.operational_evidence.issuance import IssuedEvidence, StoredAttempt
from fdai.core.operational_evidence.readback.base import LineageRecord
from fdai.core.operational_evidence.revision_history import LineageBinding, RegistryPins
from fdai.delivery.persistence.state_store_decision_evidence import (
    RetainedDecisionEvidence,
    decision_evidence_record_mapping,
)

VERIFIER_ROLE = "fdai_operational_evidence_verifier"
READER_ROLE = "fdai_operational_evidence_reader"
PROOF_TABLES = (
    "operational_evidence_admission",
    "operational_evidence_authentication",
    "operational_evidence_bundle",
    "operational_evidence_readback",
    "operational_evidence_rejection",
)
EXPECTED_GUARDS = tuple(
    sorted(
        f"{table.removeprefix('operational_')}_{kind}"
        for table in PROOF_TABLES
        for kind in ("immutable", "table_guard", "writer")
    )
)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVERSE_EPOCH_MS = 10**13 - 1


class OperationalProofStoreError(RuntimeError):
    """A proof write conflicted with retained immutable content or used the wrong role."""


@dataclass(frozen=True, slots=True)
class PostgresOperationalEvidenceConfig:
    """Connection settings for one role-bound proof-store or source connection."""

    dsn: str
    expected_role: str
    statement_timeout_ms: int = 2_000
    connect_timeout_s: int = 5

    def __post_init__(self) -> None:
        if not self.dsn.strip() or not self.expected_role.strip():
            raise ValueError("operational evidence database dsn and role are required")
        if not 0 < self.statement_timeout_ms <= 10_000 or not 0 < self.connect_timeout_s <= 10:
            raise ValueError("operational evidence database timeouts are out of bounds")


@asynccontextmanager
async def role_bound_connection(
    config: PostgresOperationalEvidenceConfig,
) -> AsyncIterator[psycopg.AsyncConnection[dict[str, Any]]]:
    """Open one bounded transaction that refuses any role other than the configured one."""

    async with await psycopg.AsyncConnection.connect(
        config.dsn, row_factory=dict_row, connect_timeout=config.connect_timeout_s
    ) as connection:
        async with connection.transaction():
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(config.statement_timeout_ms),),
            )
            row = await (await connection.execute("SELECT current_user AS role")).fetchone()
            if row is None or row["role"] != config.expected_role:
                raise PermissionError("operational evidence connection uses an unexpected role")
            yield connection


def record_key(pins: RegistryPins, lookup_digest: str, at: datetime, digest: str) -> str:
    """Return ``<registry-pins>/<lookup>/<reverse-time>-<record>`` for one immutable record."""

    reverse = _REVERSE_EPOCH_MS - int(at.astimezone(UTC).timestamp() * 1000)
    return (
        f"{pins.digest.removeprefix('sha256:')}/{lookup_digest.removeprefix('sha256:')}/"
        f"{reverse:013d}-{digest.removeprefix('sha256:')}"
    )


class PostgresOperationalProofWriter:
    """Create-only writer bound to the verifier role; a replayed attempt returns its record."""

    def __init__(self, config: PostgresOperationalEvidenceConfig) -> None:
        if config.expected_role != VERIFIER_ROLE:
            raise ValueError("operational proof writer requires the verifier role")
        self._config = config

    async def attempt_outcome(self, attempt_id: str) -> StoredAttempt | None:
        """Return the one outcome already retained for an attempt, or nothing."""

        async with role_bound_connection(self._config) as connection:
            return await _stored_attempt(connection, attempt_id)

    async def write_admission(self, issued: IssuedEvidence) -> str:
        """Insert one admission once; a replayed attempt returns its retained record digest."""

        record = decision_evidence_record_mapping(
            RetainedDecisionEvidence(
                receipt=issued.receipt,
                verification_bundle=issued.bundle,
                admission=issued.admission,
            )
        )
        record_digest = str(record["record_digest"])
        receipt_digest = issued.receipt.receipt_digest
        lineage = {
            "matched_grants": list(issued.binding.matched_grants),
            "pins_digest": issued.pins.digest,
            "purpose_id": issued.binding.purpose_id,
            "trust_anchor_id": issued.binding.trust_anchor_id,
            "verifier_id": issued.binding.verifier_id,
            "verifier_version": issued.binding.verifier_version,
        }
        try:
            async with role_bound_connection(self._config) as connection:
                stored = await _stored_attempt(connection, issued.attempt_id)
                if stored is not None:
                    return _replayed(stored, OperationalEvidenceIssuanceStatus.ISSUED)
                for receipt in issued.authentication_receipts:
                    await connection.execute(
                        "INSERT INTO operational_evidence_authentication (receipt_digest, receipt) "
                        "VALUES (%s, %s) ON CONFLICT (receipt_digest) DO NOTHING",
                        (receipt["receipt_digest"], Jsonb(dict(receipt))),
                    )
                await connection.execute(
                    "INSERT INTO operational_evidence_readback (receipt_digest, lookup_digest, "
                    "purpose_id, pins_digest, receipt, readback) VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        receipt_digest,
                        issued.lookup_digest,
                        issued.purpose_id,
                        issued.pins.digest,
                        Jsonb(issued.receipt.model_dump(mode="json")),
                        Jsonb(dict(issued.readback)),
                    ),
                )
                await connection.execute(
                    "INSERT INTO operational_evidence_bundle (bundle_digest, receipt_digest, "
                    "bundle) VALUES (%s, %s, %s)",
                    (
                        issued.bundle.bundle_digest,
                        receipt_digest,
                        Jsonb(issued.bundle.model_dump(mode="json")),
                    ),
                )
                await connection.execute(
                    "INSERT INTO operational_evidence_admission (record_key, pins_digest, "
                    "lookup_digest, purpose_id, attempt_id, receipt_digest, record_digest, record, "
                    "lineage, verified_at, valid_until) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        record_key(
                            issued.pins,
                            issued.lookup_digest,
                            issued.admission.verified_at,
                            receipt_digest,
                        ),
                        issued.pins.digest,
                        issued.lookup_digest,
                        issued.purpose_id,
                        issued.attempt_id,
                        receipt_digest,
                        record_digest,
                        Jsonb(record),
                        Jsonb(lineage),
                        issued.admission.verified_at,
                        issued.admission.valid_until,
                    ),
                )
        except psycopg.errors.UniqueViolation:
            return await self._after_race(
                issued.attempt_id, OperationalEvidenceIssuanceStatus.ISSUED
            )
        return record_digest

    async def write_rejection(self, record: OperationalEvidenceRejectionRecord) -> str:
        """Insert one rejection once; a replayed attempt returns its retained record digest."""

        pins = RegistryPins(
            trust_pin=record.trust_registry_pin, grant_pin=record.grant_registry_pin
        )
        try:
            async with role_bound_connection(self._config) as connection:
                stored = await _stored_attempt(connection, record.attempt_id)
                if stored is not None:
                    return _replayed(stored, OperationalEvidenceIssuanceStatus.REJECTED)
                await connection.execute(
                    "INSERT INTO operational_evidence_rejection (record_key, pins_digest, "
                    "lookup_digest, purpose_id, attempt_id, rejection_class, record_digest, "
                    "record, recorded_at, valid_until) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        record_key(
                            pins, record.lookup_digest, record.recorded_at, record.record_digest
                        ),
                        pins.digest,
                        record.lookup_digest,
                        record.purpose_id,
                        record.attempt_id,
                        record.rejection_class.value,
                        record.record_digest,
                        Jsonb(record.model_dump(mode="json")),
                        record.recorded_at,
                        record.valid_until,
                    ),
                )
        except psycopg.errors.UniqueViolation:
            return await self._after_race(
                record.attempt_id, OperationalEvidenceIssuanceStatus.REJECTED
            )
        return record.record_digest

    async def _after_race(self, attempt_id: str, status: OperationalEvidenceIssuanceStatus) -> str:
        stored = await self.attempt_outcome(attempt_id)
        if stored is None:
            raise OperationalProofStoreError("proof record conflicts with retained content")
        return _replayed(stored, status)


async def _stored_attempt(
    connection: psycopg.AsyncConnection[dict[str, Any]], attempt_id: str
) -> StoredAttempt | None:
    rows = await (
        await connection.execute(
            "SELECT 'issued' AS status, lookup_digest, record_digest "
            "FROM operational_evidence_admission WHERE attempt_id=%(attempt)s "
            "UNION ALL SELECT 'rejected', lookup_digest, record_digest "
            "FROM operational_evidence_rejection WHERE attempt_id=%(attempt)s",
            {"attempt": attempt_id},
        )
    ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise OperationalProofStoreError("attempt retained more than one outcome")
    return StoredAttempt(
        status=OperationalEvidenceIssuanceStatus(rows[0]["status"]),
        lookup_digest=str(rows[0]["lookup_digest"]),
        record_digest=str(rows[0]["record_digest"]),
    )


def _replayed(stored: StoredAttempt, status: OperationalEvidenceIssuanceStatus) -> str:
    if stored.status is not status:
        raise OperationalProofStoreError("attempt already retained another outcome")
    return stored.record_digest


@dataclass(frozen=True, slots=True)
class RetainedAdmissionRow:
    """One admission row as a consumer or the verifier reads it back."""

    record: Mapping[str, Any]
    record_digest: str
    pins_digest: str
    lineage: Mapping[str, Any]


class PostgresOperationalProofReader:
    """SELECT-only reader for consumers and for the verifier's own lineage checks."""

    def __init__(self, config: PostgresOperationalEvidenceConfig) -> None:
        self._config = config

    async def newest_admissions(
        self, lookup_digest: str, pins_digests: frozenset[str], *, limit: int = 2
    ) -> tuple[RetainedAdmissionRow, ...]:
        """Return at most the two newest admissions under admitting pins; none extends another."""

        if _DIGEST.fullmatch(lookup_digest) is None or not 1 <= limit <= 2 or not pins_digests:
            return ()
        async with role_bound_connection(self._config) as connection:
            rows = await (
                await connection.execute(
                    "SELECT record, record_digest, pins_digest, lineage "
                    "FROM operational_evidence_admission "
                    "WHERE lookup_digest=%s AND pins_digest = ANY(%s) "
                    "ORDER BY verified_at DESC, record_key LIMIT %s",
                    (lookup_digest, sorted(pins_digests), limit),
                )
            ).fetchall()
        return tuple(
            RetainedAdmissionRow(
                record=row["record"],
                record_digest=row["record_digest"],
                pins_digest=row["pins_digest"],
                lineage=row["lineage"],
            )
            for row in rows
        )

    async def rejection(self, *, record_digest: str, attempt_id: str) -> Mapping[str, Any] | None:
        """Return the exact rejection one attempt named, or nothing."""

        if _DIGEST.fullmatch(record_digest) is None:
            return None
        async with role_bound_connection(self._config) as connection:
            row = await (
                await connection.execute(
                    "SELECT record FROM operational_evidence_rejection "
                    "WHERE record_digest=%s AND attempt_id=%s",
                    (record_digest, attempt_id),
                )
            ).fetchone()
        return row["record"] if row is not None else None

    async def admission_by_receipt(self, receipt_digest: str) -> LineageRecord | None:
        """Return lineage facts of one retained admission for the verifier's lineage check."""

        if _DIGEST.fullmatch(receipt_digest) is None:
            return None
        async with role_bound_connection(self._config) as connection:
            row = await (
                await connection.execute(
                    "SELECT purpose_id, lookup_digest, receipt_digest, pins_digest, lineage, "
                    "verified_at, valid_until FROM operational_evidence_admission "
                    "WHERE receipt_digest=%s",
                    (receipt_digest,),
                )
            ).fetchone()
        if row is None:
            return None
        lineage = row["lineage"]
        return LineageRecord(
            purpose_id=row["purpose_id"],
            lookup_digest=row["lookup_digest"],
            receipt_digest=row["receipt_digest"],
            pins_digest=row["pins_digest"],
            binding=LineageBinding(
                purpose_id=str(lineage["purpose_id"]),
                verifier_id=str(lineage["verifier_id"]),
                verifier_version=str(lineage["verifier_version"]),
                trust_anchor_id=str(lineage["trust_anchor_id"]),
                matched_grants=tuple(str(item) for item in lineage["matched_grants"]),
            ),
            verified_at=row["verified_at"],
            valid_until=row["valid_until"],
        )


__all__ = [
    "EXPECTED_GUARDS",
    "PROOF_TABLES",
    "READER_ROLE",
    "VERIFIER_ROLE",
    "OperationalProofStoreError",
    "PostgresOperationalEvidenceConfig",
    "PostgresOperationalProofReader",
    "PostgresOperationalProofWriter",
    "RetainedAdmissionRow",
    "record_key",
    "role_bound_connection",
]
