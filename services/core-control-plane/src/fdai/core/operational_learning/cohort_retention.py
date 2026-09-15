"""Atomic scope-partitioned case cohort retention for Muninn."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai.core.case_history.derived import CaseHistoryProjectionStore
from fdai.core.operational_learning.patterns import PatternCase
from fdai.shared.providers.state_store import StateStore


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
        if state is not None and (
            state.get("access_scope_digest") != access_scope_digest
            or state.get("purpose") != purpose
        ):
            raise ValueError("operational cohort scope identity conflict")
        revision = state.get("revision", 0) if state is not None else 0
        raw_cases = state.get("cases", []) if state is not None else []
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError("operational cohort revision is invalid")
        if not isinstance(raw_cases, list) or len(raw_cases) > 100:
            raise ValueError("operational cohort cases are invalid")
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
