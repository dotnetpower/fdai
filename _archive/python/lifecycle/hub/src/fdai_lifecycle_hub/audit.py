"""The Hub's hash-chained audit.

Each record hashes its content together with the previous record's hash. The sequence is the
primary key, so two concurrent writers can't both extend the chain from the same record; the later
one fails and its transaction rolls back.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fdai_lifecycle_hub.models import AuditRecord

GENESIS_HASH = "0" * 64


def append(
    session: Session,
    now: datetime,
    action: str,
    installation_id: str,
    subject: str,
    payload: dict[str, Any] | None = None,
) -> None:
    last = session.scalars(
        select(AuditRecord).order_by(AuditRecord.sequence.desc()).limit(1)
    ).one_or_none()
    record = AuditRecord(
        sequence=last.sequence + 1 if last else 1,
        recorded_at=now,
        action=action,
        installation_id=installation_id,
        subject=subject,
        payload=payload or {},
        previous_hash=last.record_hash if last else GENESIS_HASH,
    )
    record.record_hash = record_hash(record)
    session.add(record)


def chain_intact(session: Session) -> bool:
    previous_hash = GENESIS_HASH
    records = session.scalars(select(AuditRecord).order_by(AuditRecord.sequence))
    for expected_sequence, record in enumerate(records, start=1):
        if (
            record.sequence != expected_sequence
            or record.previous_hash != previous_hash
            or record.record_hash != record_hash(record)
        ):
            return False
        previous_hash = record.record_hash
    return True


def record_hash(record: AuditRecord) -> str:
    body = {
        "sequence": record.sequence,
        "recorded_at": record.recorded_at.astimezone(UTC).isoformat(),
        "action": record.action,
        "installation_id": record.installation_id,
        "subject": record.subject,
        "payload": record.payload,
        "previous_hash": record.previous_hash,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
