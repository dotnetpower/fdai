"""Atomic scope-partitioned case cohort retention for Muninn."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai.core.case_history.derived import CaseHistoryProjectionStore
from fdai.core.operational_learning.patterns import PatternCase
from fdai.shared.providers.case_history import CaseHistoryRevisionRecord
from fdai.shared.providers.state_store import StateStore

_COHORT_PREFIX = "operational-case-fingerprint-cohort:v2:"
_MAX_CASES = 100
_MAX_DELETION_FENCES = 1000
_LEGACY_METADATA = (
    "action_type",
    "failure_fingerprint",
    "fdai_revision",
    "scenario_set_version",
    "source_kind",
)


def cohort_state_key(
    *,
    access_scope_digest: str,
    purpose: str,
    failure_fingerprint: str,
    action_type: str,
    fdai_revision: str,
    scenario_set_version: str,
    source_kind: str,
    source_synthetic: bool,
) -> str:
    """Return the stable cohort key shared by new-layout and legacy projections."""

    material = {
        "access_scope_digest": access_scope_digest,
        "purpose": purpose,
        "failure_fingerprint": failure_fingerprint,
        "action_type": action_type,
        "fdai_revision": fdai_revision,
        "scenario_set_version": scenario_set_version,
        "source_kind": source_kind,
        "source_synthetic": source_synthetic,
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"{_COHORT_PREFIX}{digest}"


async def retain_cohort_case(
    store: StateStore | CaseHistoryProjectionStore,
    *,
    key: str,
    case: PatternCase,
    access_scope_digest: str,
    purpose: str,
    recorded_at: datetime,
) -> dict[str, Any]:
    """Merge a case by revision with bounded CAS retries and an atomic state audit."""
    for _attempt in range(3):
        state = await store.read_state(key)
        revision, raw_cases, deleted_case_ids = _cohort_state(
            state,
            access_scope_digest=access_scope_digest,
            purpose=purpose,
        )
        if case.case_id in deleted_case_ids:
            raise PermissionError("operational cohort deletion fence blocks case recreation")
        records: list[dict[str, Any]] = []
        for raw in raw_cases:
            if not isinstance(raw, Mapping) or not isinstance(raw.get("case"), Mapping):
                raise ValueError("operational cohort case record is invalid")
            existing = PatternCase.from_mapping(raw["case"])
            if existing.case_id == case.case_id:
                if existing.revision > case.revision:
                    return dict(state or {})
                if existing.revision == case.revision:
                    if existing != case:
                        raise ValueError("operational cohort immutable case conflict")
                    return dict(state or {})
                continue
            records.append(dict(raw))
        records.append({"recorded_at": recorded_at.isoformat(), "case": case.to_mapping()})
        records.sort(key=lambda record: (record["recorded_at"], record["case"]["case_id"]))
        cohort = {
            "schema_version": "2.0.0",
            "revision": revision + 1,
            "access_scope_digest": access_scope_digest,
            "purpose": purpose,
            "failure_fingerprint": case.failure_fingerprint,
            "cases": records[-100:],
            "deleted_case_ids": deleted_case_ids,
        }
        audit_entry = {
            "action_kind": "case_history.cohort_retained",
            "owner_agent": "Muninn",
            "correlation_id": key,
            "idempotency_key": f"{key}:{revision + 1}",
            "timestamp": recorded_at.isoformat(),
            "case_manifest_digest": case.manifest_digest,
            "execution_authority": False,
        }
        applied = (
            await store.write_state_with_audit_if_absent(key, cohort, audit_entry)
            if state is None
            else await store.compare_and_set_state_with_audit(
                key,
                cohort,
                expected_revision=revision,
                audit_entry=audit_entry,
            )
        )
        if applied:
            return cohort
    raise RuntimeError("operational cohort concurrent update budget exhausted")


class LegacyCaseCohortRetention:
    """Purge legacy v2 cohort bodies and retain a restart-safe per-case fence."""

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def purge(self, record: CaseHistoryRevisionRecord) -> None:
        """Remove one case from both possible legacy synthetic-source partitions."""

        if record.kind == "prediction":
            return
        if record.legal_hold or record.deletion_started_at is None:
            raise PermissionError("legacy cohort purge requires an unheld source deletion claim")
        metadata = dict(record.metadata)
        if any(not metadata.get(field) for field in _LEGACY_METADATA):
            raise ValueError("legacy cohort purge requires complete operational metadata")
        for source_synthetic in (False, True):
            await self._purge_key(
                cohort_state_key(
                    access_scope_digest=record.access_scope_digest,
                    purpose=record.purpose,
                    failure_fingerprint=metadata["failure_fingerprint"],
                    action_type=metadata["action_type"],
                    fdai_revision=metadata["fdai_revision"],
                    scenario_set_version=metadata["scenario_set_version"],
                    source_kind=metadata["source_kind"],
                    source_synthetic=source_synthetic,
                ),
                record=record,
            )

    async def _purge_key(self, key: str, *, record: CaseHistoryRevisionRecord) -> None:
        if record.deletion_started_at is None:
            raise PermissionError("legacy cohort purge requires a source deletion claim")
        for _attempt in range(3):
            state = await self._store.read_state(key)
            if state is None:
                fenced = {
                    "schema_version": "2.0.0",
                    "revision": 1,
                    "access_scope_digest": record.access_scope_digest,
                    "purpose": record.purpose,
                    "failure_fingerprint": dict(record.metadata)["failure_fingerprint"],
                    "cases": [],
                    "deleted_case_ids": [record.case_id],
                }
                if await self._store.write_state_with_audit_if_absent(
                    key,
                    fenced,
                    self._audit_entry(key, record=record, revision=1),
                ):
                    await self._verify_fence(key, record=record)
                    return
                continue
            revision, raw_cases, deleted_case_ids = _cohort_state(
                state,
                access_scope_digest=record.access_scope_digest,
                purpose=record.purpose,
            )
            records = []
            for raw in raw_cases:
                if not isinstance(raw, Mapping) or not isinstance(raw.get("case"), Mapping):
                    raise ValueError("operational cohort case record is invalid")
                case = PatternCase.from_mapping(raw["case"])
                if case.case_id != record.case_id:
                    records.append(dict(raw))
            if record.case_id in deleted_case_ids and len(records) == len(raw_cases):
                return
            if len(deleted_case_ids) >= _MAX_DELETION_FENCES:
                raise RuntimeError("legacy cohort deletion fence capacity exhausted")
            next_deleted_case_ids = sorted({*deleted_case_ids, record.case_id})
            updated = {
                "schema_version": "2.0.0",
                "revision": revision + 1,
                "access_scope_digest": record.access_scope_digest,
                "purpose": record.purpose,
                "failure_fingerprint": state.get("failure_fingerprint"),
                "cases": records,
                "deleted_case_ids": next_deleted_case_ids,
            }
            if not await self._store.compare_and_set_state_with_audit(
                key,
                updated,
                expected_revision=revision,
                audit_entry=self._audit_entry(key, record=record, revision=revision + 1),
            ):
                continue
            await self._verify_fence(key, record=record)
            return
        raise RuntimeError("legacy cohort deletion contention budget exhausted")

    @staticmethod
    def _audit_entry(
        key: str,
        *,
        record: CaseHistoryRevisionRecord,
        revision: int,
    ) -> dict[str, object]:
        deletion_started_at = record.deletion_started_at
        if deletion_started_at is None:
            raise PermissionError("legacy cohort purge requires a source deletion claim")
        return {
            "action_kind": "case_history.legacy_cohort_purged",
            "owner_agent": "Muninn",
            "correlation_id": record.correlation_id,
            "idempotency_key": f"{key}:{record.case_id}:{revision}",
            "timestamp": deletion_started_at.isoformat(),
            "case_id": record.case_id,
            "execution_authority": False,
        }

    async def _verify_fence(self, key: str, *, record: CaseHistoryRevisionRecord) -> None:
        observed = await self._store.read_state(key)
        if observed is None:
            raise RuntimeError("legacy cohort purge readback is unavailable")
        _, observed_cases, observed_deleted = _cohort_state(
            observed,
            access_scope_digest=record.access_scope_digest,
            purpose=record.purpose,
        )
        if (
            any(
                PatternCase.from_mapping(raw["case"]).case_id == record.case_id
                for raw in observed_cases
            )
            or record.case_id not in observed_deleted
        ):
            raise RuntimeError("legacy cohort purge readback did not preserve the fence")


def _cohort_state(
    state: Mapping[str, Any] | None,
    *,
    access_scope_digest: str,
    purpose: str,
) -> tuple[int, list[Any], list[str]]:
    if state is None:
        return 0, [], []
    required = {
        "schema_version",
        "revision",
        "access_scope_digest",
        "purpose",
        "failure_fingerprint",
        "cases",
    }
    failure_fingerprint = state.get("failure_fingerprint")
    if (
        not required.issubset(state)
        or not set(state).issubset(required | {"deleted_case_ids"})
        or state.get("schema_version") != "2.0.0"
        or not isinstance(failure_fingerprint, str)
        or len(failure_fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in failure_fingerprint)
    ):
        raise ValueError("operational cohort state schema is invalid")
    if state.get("access_scope_digest") != access_scope_digest or state.get("purpose") != purpose:
        raise ValueError("operational cohort scope identity conflict")
    revision = state.get("revision", 0)
    raw_cases = state.get("cases", [])
    deleted_case_ids = state.get("deleted_case_ids", [])
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("operational cohort revision is invalid")
    if not isinstance(raw_cases, list) or len(raw_cases) > _MAX_CASES:
        raise ValueError("operational cohort cases are invalid")
    if (
        not isinstance(deleted_case_ids, list)
        or len(deleted_case_ids) > _MAX_DELETION_FENCES
        or len(set(deleted_case_ids)) != len(deleted_case_ids)
        or any(
            not isinstance(case_id, str) or not case_id or len(case_id) > 256
            for case_id in deleted_case_ids
        )
    ):
        raise ValueError("operational cohort deletion fences are invalid")
    return revision, raw_cases, sorted(deleted_case_ids)


__all__ = ["LegacyCaseCohortRetention", "cohort_state_key", "retain_cohort_case"]
