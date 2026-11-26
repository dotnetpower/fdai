"""Resumable removal of historical top-level cohort snapshot and Pattern bodies."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from fdai.shared.providers.case_history import CaseHistoryRevisionRecord
from fdai.shared.providers.state_store import StateStore, StateStoreKeysetReader

from .cohort_retention import _cohort_state, legacy_cohort_keys
from .patterns import PatternCase

_PAGE_SIZE = 64


class LegacyCaseSuffixRetention:
    """Scan historical immutable keys without offset drift from concurrent CAS writes.

    A cursor is an audited content-free checkpoint. The second pass catches keys
    inserted before a checkpoint while the first pass was in progress. Old
    snapshot and Pattern keys remain in place as retired replay fences.
    """

    def __init__(self, *, store: StateStore) -> None:
        self._store = store
        self._keyset = (
            store
            if isinstance(store, StateStoreKeysetReader)
            and callable(getattr(store, "read_state_keys", None))
            else None
        )

    async def purge(self, record: CaseHistoryRevisionRecord) -> None:
        if record.kind == "prediction":
            return
        if record.legal_hold or record.deletion_started_at is None:
            raise PermissionError("legacy suffix purge requires an unheld source deletion claim")
        if self._keyset is None:
            raise RuntimeError("historical suffix cleanup requires a keyset-capable state store")
        for cohort_key in legacy_cohort_keys(record):
            await self._page(cohort_key, record)

    async def _page(self, cohort_key: str, record: CaseHistoryRevisionRecord) -> None:
        prefix = f"{cohort_key}:"
        cursor_key = (
            "case-history:legacy-suffix-scan:v1:"
            + hashlib.sha256(f"{cohort_key}:{record.case_id}".encode()).hexdigest()
        )
        checkpoint = await self._store.read_state(cursor_key)
        if checkpoint is not None and (
            set(checkpoint) != {"revision", "case_id", "cohort_key", "phase", "after"}
            or checkpoint.get("case_id") != record.case_id
            or checkpoint.get("cohort_key") != cohort_key
            or checkpoint.get("phase") not in {"purge", "verify"}
            or not isinstance(checkpoint.get("after"), str)
            or (checkpoint["after"] and not self._valid_suffix_key(checkpoint["after"], cohort_key))
            or type(checkpoint.get("revision")) is not int
            or checkpoint["revision"] < 1
        ):
            raise ValueError("legacy suffix scan checkpoint is invalid")
        phase = checkpoint["phase"] if checkpoint is not None else "purge"
        after = checkpoint["after"] if checkpoint is not None else ""
        if self._keyset is None:
            raise RuntimeError("historical suffix keyset reader is unavailable")
        keys = await self._keyset.read_state_keys(prefix, after=after, limit=_PAGE_SIZE)
        for key in keys:
            if key.startswith(f"{cohort_key}:snapshot:"):
                await self._snapshot(key, record, cohort_key)
            elif key.startswith(f"{cohort_key}:pattern:"):
                await self._pattern(key, record, cohort_key)
            elif key.startswith(f"{cohort_key}:emitted:"):
                await self._emission(key, record, cohort_key)
            else:
                raise ValueError("unknown historical cohort suffix blocks deletion")
        if not keys and phase == "verify":
            return
        next_phase = "verify" if not keys else phase
        next_after = "" if not keys else keys[-1]
        revision = 1 if checkpoint is None else checkpoint["revision"] + 1
        updated = {
            "revision": revision,
            "case_id": record.case_id,
            "cohort_key": cohort_key,
            "phase": next_phase,
            "after": next_after,
        }
        audit = self._audit(record, cursor_key, revision)
        committed = (
            await self._store.write_state_with_audit_if_absent(cursor_key, updated, audit)
            if checkpoint is None
            else await self._store.compare_and_set_state_with_audit(
                cursor_key, updated, expected_revision=revision - 1, audit_entry=audit
            )
        )
        if not committed or await self._store.read_state(cursor_key) != updated:
            raise RuntimeError("legacy suffix scan checkpoint was not confirmed")
        raise RuntimeError("legacy suffix cleanup pending; resume at the audited checkpoint")

    async def _snapshot(self, key: str, record: CaseHistoryRevisionRecord, cohort_key: str) -> None:
        digest = self._digest_suffix(key, f"{cohort_key}:snapshot:")
        state = await self._store.read_state(key)
        if state is None:
            raise RuntimeError("historical cohort snapshot disappeared during scan")
        revision, raw_cases, deleted = _cohort_state(
            state, access_scope_digest=record.access_scope_digest, purpose=record.purpose
        )
        if state["failure_fingerprint"] != dict(record.metadata)["failure_fingerprint"]:
            raise ValueError("historical cohort snapshot fingerprint conflict")
        cases = self._remaining(raw_cases, record.case_id)
        if state.get("retired") is not True and digest != self._digest(raw_cases):
            raise ValueError("historical cohort snapshot digest conflict")
        if len(cases) != len(raw_cases):
            updated = {
                **state,
                "revision": revision + 1,
                "cases": cases,
                "retired": True,
                "deleted_case_ids": sorted({*deleted, record.case_id}),
            }
            await self._replace(key, state, updated, record)
        if await self._store.read_state(key) != (
            updated if len(cases) != len(raw_cases) else state
        ):
            raise RuntimeError("historical cohort snapshot readback changed")
        if record.case_id in deleted or len(cases) != len(raw_cases):
            await self._emission(
                f"{cohort_key}:emitted:{digest}",
                record,
                cohort_key,
                optional=True,
            )

    async def _pattern(self, key: str, record: CaseHistoryRevisionRecord, cohort_key: str) -> None:
        pattern_id = self._digest_suffix(key, f"{cohort_key}:pattern:")
        state = await self._store.read_state(key)
        if state is None:
            raise RuntimeError("historical Pattern disappeared during scan")
        if (
            state.get("pattern_id") != pattern_id
            or state.get("cohort_key") != cohort_key
            or state.get("access_scope_digest") != record.access_scope_digest
            or state.get("purpose") != record.purpose
            or not isinstance(state.get("cases"), list)
        ):
            raise ValueError("historical Pattern identity conflict")
        cases = self._remaining(state["cases"], record.case_id, wrapped=False)
        deleted = state.get("deleted_case_ids", [])
        if (
            not isinstance(deleted, list)
            or len(deleted) > 1000
            or any(not isinstance(item, str) for item in deleted)
        ):
            raise ValueError("historical Pattern deletion fences are invalid")
        candidate_mentions_case = "candidate" in state and record.case_id in json.dumps(
            state["candidate"], sort_keys=True
        )
        needs_scrub = (
            len(cases) != len(state["cases"])
            or (record.case_id in deleted and "candidate" in state)
            or candidate_mentions_case
        )
        if needs_scrub:
            revision = state.get("revision", 0)
            if type(revision) is not int or revision < 0:
                raise ValueError("historical Pattern revision is invalid")
            updated = {
                "schema_version": state.get("schema_version"),
                "pattern_id": pattern_id,
                "cohort_key": cohort_key,
                "access_scope_digest": record.access_scope_digest,
                "purpose": record.purpose,
                "cases": cases,
                "revision": revision + 1,
                "retired": True,
                "deleted_case_ids": sorted({*deleted, record.case_id}),
                "execution_authority": False,
                "promotion_authority": False,
            }
            await self._replace(key, state, updated, record)
        if await self._store.read_state(key) != (updated if needs_scrub else state):
            raise RuntimeError("historical Pattern readback changed")

    async def _emission(
        self,
        key: str,
        record: CaseHistoryRevisionRecord,
        cohort_key: str,
        *,
        optional: bool = False,
    ) -> None:
        digest = self._digest_suffix(key, f"{cohort_key}:emitted:")
        state = await self._store.read_state(key)
        if state is None:
            if optional:
                return
            raise RuntimeError("historical emission disappeared during scan")
        if state.get("digest") != digest or type(state.get("revision")) is not int:
            raise ValueError("historical emission marker identity conflict")
        snapshot = await self._store.read_state(f"{cohort_key}:snapshot:{digest}")
        if snapshot is None:
            # An orphan marker contains no case body and cannot establish case lineage.
            return
        _, cases, deleted = _cohort_state(
            snapshot, access_scope_digest=record.access_scope_digest, purpose=record.purpose
        )
        if record.case_id not in deleted and len(self._remaining(cases, record.case_id)) == len(
            cases
        ):
            return
        if state.get("retired") is not True:
            updated = {**state, "retired": True, "revision": state["revision"] + 1}
            await self._replace(key, state, updated, record)
        elif await self._store.read_state(key) != state:
            raise RuntimeError("historical emission marker readback changed")

    async def _replace(
        self,
        key: str,
        before: Mapping[str, Any],
        updated: Mapping[str, Any],
        record: CaseHistoryRevisionRecord,
    ) -> None:
        revision = before.get("revision", 0)
        if type(revision) is not int or revision < 0:
            raise ValueError("historical row revision is invalid")
        if (
            not await self._store.compare_and_set_state_with_audit(
                key,
                updated,
                expected_revision=revision,
                audit_entry=self._audit(record, key, revision + 1),
            )
            or await self._store.read_state(key) != updated
        ):
            raise RuntimeError("historical row CAS or independent deletion readback failed")

    @staticmethod
    def _remaining(raw_cases: list[Any], case_id: str, *, wrapped: bool = True) -> list[Any]:
        if len(raw_cases) > 100:
            raise ValueError("historical case set exceeds the bound")
        remaining = []
        for raw in raw_cases:
            if not isinstance(raw, Mapping):
                raise ValueError("historical case record is invalid")
            data = raw.get("case") if wrapped else raw
            if not isinstance(data, Mapping):
                raise ValueError("historical case record is invalid")
            case = PatternCase.from_mapping(data)
            if case.case_id != case_id:
                remaining.append(dict(raw))
        return remaining

    @staticmethod
    def _digest(raw_cases: list[Any]) -> str:
        return hashlib.sha256(
            json.dumps(raw_cases, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()

    @staticmethod
    def _digest_suffix(key: str, prefix: str) -> str:
        suffix = key.removeprefix(prefix)
        if (
            not key.startswith(prefix)
            or len(suffix) != 64
            or any(char not in "0123456789abcdef" for char in suffix)
        ):
            raise ValueError("historical cohort key is invalid")
        return suffix

    @classmethod
    def _valid_suffix_key(cls, key: str, cohort_key: str) -> bool:
        for suffix in ("snapshot", "pattern", "emitted"):
            prefix = f"{cohort_key}:{suffix}:"
            if key.startswith(prefix):
                cls._digest_suffix(key, prefix)
                return True
        return False

    @staticmethod
    def _audit(record: CaseHistoryRevisionRecord, key: str, revision: int) -> dict[str, object]:
        if record.deletion_started_at is None:
            raise PermissionError("legacy suffix audit requires a source deletion claim")
        return {
            "action_kind": "case_history.legacy_suffix_purged",
            "owner_agent": "Muninn",
            "correlation_id": record.correlation_id,
            "idempotency_key": f"{key}:{record.case_id}:{revision}",
            "timestamp": record.deletion_started_at.isoformat(),
            "case_id": record.case_id,
            "execution_authority": False,
        }
