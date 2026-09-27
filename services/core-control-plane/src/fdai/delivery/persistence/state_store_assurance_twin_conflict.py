"""Conflict-marker transitions shared by Assurance Twin posture and review rows."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai.shared.providers.state_store import StateStore


class AssuranceTwinConflictMixin:
    """Writer-owned source-conflict transition shared by the posture ledger."""

    _store: StateStore

    async def mark_source_conflict(
        self,
        *,
        owner: str,
        source_key: str,
        generated_at: str,
        source_revision: str,
        rejected_evidence_digest: str,
        correlation_id: str,
    ) -> bool:
        from fdai.delivery.persistence.state_store_assurance_twin_posture import (
            POSTURE_CONFLICT_REASON_CODE,
            REVIEW_CONFLICT_REASON_CODE,
            change_review_state_key,
            posture_report_state_key,
        )

        if owner not in {"Heimdall", "Forseti"}:
            raise ValueError("assurance twin source conflict owner is invalid")
        return await mark_source_conflict(
            store=self._store,
            owner=owner,
            key=(
                posture_report_state_key(source_key)
                if owner == "Heimdall"
                else change_review_state_key(source_key)
            ),
            identity_field="scope" if owner == "Heimdall" else "review_key",
            source_key=source_key,
            generated_at=generated_at,
            source_revision=source_revision,
            rejected_evidence_digest=rejected_evidence_digest,
            correlation_id=correlation_id,
            reason=(
                POSTURE_CONFLICT_REASON_CODE if owner == "Heimdall" else REVIEW_CONFLICT_REASON_CODE
            ),
            max_attempts=16,
        )


async def mark_source_conflict(
    *,
    store: StateStore,
    owner: str,
    key: str,
    identity_field: str,
    source_key: str,
    generated_at: str,
    source_revision: str,
    rejected_evidence_digest: str,
    correlation_id: str,
    reason: str,
    max_attempts: int,
) -> bool:
    canonical_time = _canonical_timestamp(generated_at)
    for _attempt in range(max_attempts):
        existing = await store.read_state(key)
        if existing is not None:
            existing_generated = _stored_time(existing)
            if existing_generated is not None and existing_generated > canonical_time:
                return False
            if has_conflict_marker(existing) and existing_generated == canonical_time:
                return True
        if existing is None:
            placeholder = {
                identity_field: source_key,
                "generated_at": canonical_time,
                "evidence_source_revision": source_revision,
                "mode": "shadow",
                "freshness": "unavailable",
                "reason_codes": [reason],
                "findings": [],
                "evidence_digest": rejected_evidence_digest,
                "revision": 1,
                "publication_outbox": None,
                "conflict": {
                    "reason_code": reason,
                    "stored_evidence_digest": None,
                    "rejected_evidence_digest": rejected_evidence_digest,
                },
            }
            if await store.write_state_with_audit_if_absent(
                key,
                placeholder,
                source_conflict_audit(
                    owner=owner,
                    key=key,
                    correlation_id=correlation_id,
                    source_revision=source_revision,
                    rejected_evidence_digest=rejected_evidence_digest,
                ),
            ):
                return True
            continue
        revision = _revision(existing)
        tombstoned = {
            **with_conflict_marker(
                existing,
                reason_code=reason,
                stored_evidence_digest=_digest(existing),
                rejected_evidence_digest=rejected_evidence_digest,
            ),
            "generated_at": canonical_time,
            "evidence_source_revision": source_revision,
            "revision": revision + 1,
            "publication_outbox": None,
        }
        if await store.compare_and_set_state_with_audit(
            key,
            tombstoned,
            expected_revision=revision,
            audit_entry=source_conflict_audit(
                owner=owner,
                key=key,
                correlation_id=correlation_id,
                source_revision=source_revision,
                rejected_evidence_digest=rejected_evidence_digest,
            ),
        ):
            return True
    raise RuntimeError("assurance twin source conflict exceeded its retry bound")


def has_conflict_marker(existing: Mapping[str, Any] | None) -> bool:
    return existing is not None and isinstance(existing.get("conflict"), Mapping)


def with_conflict_marker(
    existing: Mapping[str, Any],
    *,
    reason_code: str,
    stored_evidence_digest: str | None,
    rejected_evidence_digest: str,
) -> dict[str, Any]:
    return {
        **existing,
        "conflict": {
            "reason_code": reason_code,
            "stored_evidence_digest": stored_evidence_digest,
            "rejected_evidence_digest": rejected_evidence_digest,
        },
    }


def source_conflict_audit(
    *,
    owner: str,
    key: str,
    correlation_id: str,
    source_revision: str,
    rejected_evidence_digest: str,
) -> dict[str, Any]:
    return {
        "action_kind": "assurance_twin.source_conflict_marked",
        "actor": owner,
        "mode": "shadow",
        "correlation_id": _privacy_safe(correlation_id),
        "evidence_source_revision": source_revision,
        "idempotency_key": (
            f"assurance-twin-source-conflict:{_privacy_safe(key)}:{rejected_evidence_digest}"
        ),
        "execution_authority": False,
    }


def _canonical_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("assurance twin generated_at MUST include a timezone")
    return parsed.isoformat()


def _stored_time(existing: Mapping[str, Any]) -> str | None:
    value = existing.get("generated_at")
    return _canonical_timestamp(value) if isinstance(value, str) else None


def _revision(existing: Mapping[str, Any]) -> int:
    value = existing.get("revision")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RuntimeError("assurance twin durable revision is invalid")
    return value


def _digest(existing: Mapping[str, Any]) -> str | None:
    value = existing.get("evidence_digest")
    return value if isinstance(value, str) else None


def _privacy_safe(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


__all__ = [
    "AssuranceTwinConflictMixin",
    "has_conflict_marker",
    "mark_source_conflict",
    "source_conflict_audit",
    "with_conflict_marker",
]
