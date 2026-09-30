"""Durable delivery and restart recovery for Norns operational candidates."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Protocol

from fdai.agents._framework.adapters import canonical_json_digest
from fdai.agents._framework.bounded import BoundedLruSet
from fdai.agents._framework.norns_case_history import operational_candidate_cases_are_current
from fdai.agents._framework.norns_consensus import NornsConsensus
from fdai.core.case_history import CaseHistoryMaterializer
from fdai.core.operational_learning import ShadowDwellLedger
from fdai.shared.providers.state_store import StateStore

_STATE_PREFIX = "pantheon/norns/operational-candidates"
_KIND = "norns_operational_candidate"
_TERMINAL = frozenset({"held", "invalidated", "published"})
_MAX_EMPTY_RECOVERY_PAGES = 16
_MAX_SOURCE_SCRUB_RECORDS = 50_000
_RECOVERY_BUDGET_SECONDS = 5.0
_DEFAULT_PROVIDER_TIMEOUT_SECONDS = 5.0


class _IssueDeduplicator(Protocol):
    async def observe(self, state: Any, payload: Mapping[str, Any]) -> None: ...

    async def recover(self, state: Any) -> int: ...

    async def after_flush(self, state: Any) -> None: ...


class NornsOperationalCandidateJournal:
    """Retain one exact candidate and Pattern envelope until terminal delivery."""

    def __init__(self, store: StateStore | None, *, capacity: int) -> None:
        self._store = store
        self._capacity = capacity
        self._last_pending_total = 0

    @property
    def durable(self) -> bool:
        return self._store is not None

    @property
    def last_pending_total(self) -> int:
        return self._last_pending_total

    async def retain(
        self,
        *,
        candidate: Mapping[str, Any],
        pattern: Mapping[str, Any],
    ) -> bool:
        store = self._store
        if store is None:
            return True
        pattern_id = _pattern_id(candidate, pattern)
        candidate_digest = _digest(candidate)
        pattern_digest = _digest(pattern)
        value = {
            "kind": _KIND,
            "revision": 1,
            "status": "pending",
            "pattern_id": pattern_id,
            "candidate_digest": candidate_digest,
            "pattern_digest": pattern_digest,
            "pattern_published": False,
            "candidate": dict(candidate),
            "pattern": dict(pattern),
        }
        key = _state_key(pattern_id)
        await store.write_state_with_audit_if_absent(
            key,
            value,
            {
                "kind": "norns_operational_candidate_pending",
                "principal": "Norns",
                "pattern_id": pattern_id,
                "candidate_digest": candidate_digest,
                "pattern_digest": pattern_digest,
                "grants_authority": False,
            },
        )
        retained = await store.read_state(key)
        if retained is None:
            raise RuntimeError("Norns operational candidate pending record is unavailable")
        if retained.get("status") == "pending":
            _validate_pending(retained, candidate=candidate, pattern=pattern)
            return True
        _validate_terminal_identity(retained, candidate=candidate, pattern=pattern)
        return False

    async def pending(
        self,
    ) -> tuple[tuple[tuple[dict[str, Any], dict[str, Any], bool], ...], int]:
        return await self.pending_page(limit=self._capacity)

    async def pending_page(
        self,
        *,
        limit: int,
        offset: int = 0,
    ) -> tuple[tuple[tuple[dict[str, Any], dict[str, Any], bool], ...], int]:
        store = self._store
        if store is None:
            self._last_pending_total = 0
            return (), 0
        rows, total = await store.read_state_page(
            f"{_STATE_PREFIX}/",
            limit=limit,
            offset=offset,
            field="status",
            value="pending",
        )
        recovered: list[tuple[dict[str, Any], dict[str, Any], bool]] = []
        self._last_pending_total = total
        for row in rows:
            candidate = row.get("candidate")
            pattern = row.get("pattern")
            if not isinstance(candidate, Mapping) or not isinstance(pattern, Mapping):
                raise ValueError("Norns operational candidate durable payload is invalid")
            _validate_pending(row, candidate=candidate, pattern=pattern)
            recovered.append(
                (
                    dict(candidate),
                    dict(pattern),
                    row.get("pattern_published") is True,
                )
            )
        return tuple(recovered), total

    async def mark_pattern_published(
        self,
        *,
        candidate: Mapping[str, Any],
        pattern: Mapping[str, Any],
    ) -> None:
        """Checkpoint the completed Pattern leg before candidate publication."""
        store = self._store
        if store is None:
            return
        key = _state_key(_pattern_id(candidate, pattern))
        current = await store.read_state(key)
        if current is None:
            raise RuntimeError("Norns operational candidate pending record is unavailable")
        _validate_pending(current, candidate=candidate, pattern=pattern)
        if current.get("pattern_published") is True:
            return
        revision = _revision(current)
        updated = {
            **dict(current),
            "revision": revision + 1,
            "pattern_published": True,
        }
        if not await store.compare_and_set_state_with_audit(
            key,
            updated,
            expected_revision=revision,
            audit_entry={
                "kind": "norns_operational_pattern_published",
                "principal": "Norns",
                "pattern_id": current["pattern_id"],
                "candidate_digest": current["candidate_digest"],
                "pattern_digest": current["pattern_digest"],
                "grants_authority": False,
            },
        ):
            raise RuntimeError("Norns operational Pattern checkpoint CAS failed")
        if await store.read_state(key) != updated:
            raise RuntimeError("Norns operational Pattern checkpoint readback failed")

    async def mark_terminal(
        self,
        *,
        candidate: Mapping[str, Any],
        pattern: Mapping[str, Any],
        status: str,
        reason: str,
    ) -> None:
        if status not in _TERMINAL:
            raise ValueError("Norns operational candidate terminal status is invalid")
        store = self._store
        if store is None:
            return
        pattern_id = _pattern_id(candidate, pattern)
        key = _state_key(pattern_id)
        current = await store.read_state(key)
        if current is None:
            return
        candidate_digest = _digest(candidate)
        pattern_digest = _digest(pattern)
        _validate_pending(current, candidate=candidate, pattern=pattern)
        revision = _revision(current)
        terminal = {
            "kind": _KIND,
            "revision": revision + 1,
            "status": status,
            "pattern_id": pattern_id,
            "candidate_digest": candidate_digest,
            "pattern_digest": pattern_digest,
            "reason": reason,
        }
        if not await store.compare_and_set_state_with_audit(
            key,
            terminal,
            expected_revision=revision,
            audit_entry={
                "kind": f"norns_operational_candidate_{status}",
                "principal": "Norns",
                "pattern_id": pattern_id,
                "candidate_digest": candidate_digest,
                "pattern_digest": pattern_digest,
                "reason": reason,
                "grants_authority": False,
            },
        ):
            raise RuntimeError("Norns operational candidate terminal CAS failed")
        if await store.read_state(key) != terminal:
            raise RuntimeError("Norns operational candidate terminal readback failed")


class NornsCandidateDeliveryMixin:
    """Own Norns candidate buffering, durable recovery, and bounded publication."""

    pending_candidates: list[dict[str, Any]]
    _candidate_publication_gate: Callable[[], bool] | None
    _case_history_materializer: CaseHistoryMaterializer | None
    _clock: Callable[[], datetime]
    _consensus: NornsConsensus
    _consensus_holds: deque[dict[str, object]]
    _flush_cursor: int
    _durable_source_scrub_offset: int
    _issue_deduplicator: _IssueDeduplicator
    _learning_lock: Any
    _max_pending_candidates: int
    _operating_pattern_ids: Any
    _operational_journal: NornsOperationalCandidateJournal
    _pattern_publications: dict[str, dict[str, Any]]
    _published_pattern_ids: BoundedLruSet[str]
    _pending_by_pattern_id: dict[str, dict[str, Any]]
    _provider_timeout_seconds: float
    _shadow_dwell: ShadowDwellLedger
    bus: Any
    spec: Any

    def _init_candidate_delivery(
        self,
        *,
        store: StateStore | None,
        max_pending_candidates: int,
    ) -> None:
        self.pending_candidates = []
        self._candidate_publication_gate = None
        self._flush_cursor = 0
        self._durable_source_scrub_offset = 0
        self._operational_journal = NornsOperationalCandidateJournal(
            store, capacity=max_pending_candidates
        )
        self._published_pattern_ids = BoundedLruSet(max_pending_candidates)
        self._pending_by_pattern_id = {}

    async def retain_operational_candidate(self, pattern_id: str) -> None:
        """Persist the exact candidate and Pattern before transport acknowledgement."""
        pattern = self._pattern_publications.get(pattern_id)
        candidate = self._pending_by_pattern_id.get(pattern_id)
        if candidate is None:
            self._rebuild_pending_pattern_index()
            candidate = self._pending_by_pattern_id.get(pattern_id)
        if pattern is not None and candidate is not None:
            retained = await self._operational_journal.retain(candidate=candidate, pattern=pattern)
            if not retained:
                self.pending_candidates.remove(candidate)
                self._pattern_publications.pop(pattern_id, None)
                self.record_behavior("operational_case_candidate_terminal_duplicate")

    async def recover_operational_candidates(self) -> int:
        """Restore one bounded shared-store batch without blocking on overflow."""
        for _ in range(_MAX_EMPTY_RECOVERY_PAGES):
            rows, total = await self._operational_journal.pending()
            if not rows:
                return 0
            recovered = 0
            for candidate, pattern, pattern_published in rows:
                pattern_id = _pattern_id(candidate, pattern)
                if pattern_id in self._operating_pattern_ids:
                    continue
                if not await self._operational_candidate_cases_are_current(candidate):
                    await self._operational_journal.mark_terminal(
                        candidate=candidate,
                        pattern=pattern,
                        status="invalidated",
                        reason="source_no_longer_current",
                    )
                    self.record_behavior("operational_case_candidate_source_invalidated")
                    continue
                self._ensure_pending_capacity()
                self.pending_candidates.append(candidate)
                self._index_pending_candidate(candidate)
                self._pattern_publications[pattern_id] = pattern
                if pattern_published:
                    self._published_pattern_ids.add(pattern_id)
                self._operating_pattern_ids.add(pattern_id)
                recovered += 1
            if recovered:
                if total > len(rows):
                    self.record_behavior(
                        "operational_candidate_recovery_deferred", total - len(rows)
                    )
                return recovered
            if total <= len(rows):
                return 0
        self.record_behavior("operational_candidate_recovery_deferred")
        return 0

    async def flush_candidates(self) -> int:
        async with self._learning_lock:
            return await self._flush_candidates_unlocked()

    def bind_candidate_publication_gate(self, gate: Callable[[], bool]) -> None:
        """Bind the runtime policy ceiling for inert candidate publication once."""
        if self._candidate_publication_gate is not None:
            raise RuntimeError("Norns candidate publication gate is already bound")
        self._candidate_publication_gate = gate

    def _proposal_rate_limiter(self) -> Any:
        raise NotImplementedError

    def _record_candidate_terminal(self, candidate: Mapping[str, Any], outcome: str) -> None:
        raise NotImplementedError

    async def _flush_candidates_unlocked(self) -> int:
        published = 0
        issue_recovery_count = 0
        deadline = asyncio.get_running_loop().time() + _RECOVERY_BUDGET_SECONDS
        while True:
            published += await self._flush_candidate_batch_unlocked()
            if self.pending_candidates:
                return published
            recovered_issue = await self._issue_deduplicator.recover(self)
            issue_recovery_count += recovered_issue
            if issue_recovery_count >= self._max_pending_candidates:
                raise RuntimeError("Norns candidate recovery capacity exceeded")
            recovered_operational = await self.recover_operational_candidates()
            if not recovered_issue and not recovered_operational:
                return published
            if asyncio.get_running_loop().time() >= deadline:
                self.record_behavior("candidate_recovery_deferred")
                return published

    async def _flush_candidate_batch_unlocked(self) -> int:
        """Publish one queued batch and complete its durable delivery state."""
        await self._scrub_source_invalidated_candidates()
        await self._scrub_durable_source_invalidated_candidates()
        if self._candidate_publication_gate is not None and not self._candidate_publication_gate():
            for candidate in self.pending_candidates:
                self._record_candidate_terminal(candidate, "disabled")
            self.record_behavior("rule_candidate_publication_disabled")
            return 0
        published = 0
        while self._flush_cursor < len(self.pending_candidates):
            candidate = self.pending_candidates[self._flush_cursor]
            pattern_id = str(candidate.get("suggested_pattern", ""))
            pattern = self._pattern_publications.get(pattern_id)
            if not await self._operational_candidate_cases_are_current(candidate):
                self._record_candidate_terminal(candidate, "invalidated")
                if pattern is not None:
                    await self._operational_journal.mark_terminal(
                        candidate=candidate,
                        pattern=pattern,
                        status="invalidated",
                        reason="source_no_longer_current",
                    )
                    self._forget_published_pattern(pattern_id)
                self._pattern_publications.pop(pattern_id, None)
                self._flush_cursor += 1
                continue
            consensus = self._consensus.evaluate(candidate)
            if not consensus.unanimous:
                if pattern is not None:
                    await self._operational_journal.mark_terminal(
                        candidate=candidate,
                        pattern=pattern,
                        status="held",
                        reason="consensus_held",
                    )
                    self._forget_published_pattern(pattern_id)
                self._pattern_publications.pop(pattern_id, None)
                self._consensus_holds.append(
                    {
                        "decision": "hold",
                        "source_signal": str(candidate.get("source_signal", "")),
                        "proposal_kind": str(candidate.get("proposal_kind", "")),
                        "holding_perspectives": consensus.holding_perspectives(),
                        "reason_codes": consensus.reason_codes(),
                    }
                )
                self._flush_cursor += 1
                self._record_candidate_terminal(candidate, "held")
                self.record_behavior("rule_candidate_consensus_held")
                continue
            payload = {
                "producer_principal": "Norns",
                "correlation_id": _candidate_correlation_id(candidate),
                "idempotency_key": _candidate_idempotency_key(candidate),
                **candidate,
                "norns_consensus": consensus.summary(),
            }
            dwell = self._shadow_dwell.evidence_for(str(candidate.get("target_rule_id") or ""))
            if dwell is not None:
                payload["shadow_dwell"] = dwell.to_mapping()
            if pattern is not None and pattern_id not in self._published_pattern_ids:
                if not await self._publish_proposal("object.pattern", pattern):
                    break
                mark_task = asyncio.create_task(
                    self._operational_journal.mark_pattern_published(
                        candidate=candidate,
                        pattern=pattern,
                    )
                )
                try:
                    await asyncio.shield(mark_task)
                except asyncio.CancelledError:
                    await mark_task
                    raise
                self._published_pattern_ids.add(pattern_id)
            if not await self._publish_rule_candidate(candidate, pattern, payload):
                break
            if pattern is not None:
                self._pattern_publications.pop(pattern_id, None)
                self._forget_published_pattern(pattern_id)
            self._flush_cursor += 1
            self._record_candidate_terminal(candidate, "published")
            self.record_behavior("rule_candidate_published")
            published += 1
        if self._flush_cursor:
            del self.pending_candidates[: self._flush_cursor]
            self._rebuild_pending_pattern_index()
            self._flush_cursor = 0
        await self._issue_deduplicator.after_flush(self)
        return published

    async def _publish_rule_candidate(
        self,
        candidate: Mapping[str, Any],
        pattern: Mapping[str, Any] | None,
        payload: dict[str, Any],
    ) -> bool:
        if pattern is None:
            return await self._publish_proposal("object.rule-candidate", payload)
        if self.bus is None:
            return False
        if not self._proposal_rate_limiter().allow():
            self._record_candidate_terminal(candidate, "rate_limited")
            self.record_behavior("rate_limit_exceeded")
            return False
        await self.bus.publish(self.spec.name, "object.rule-candidate", payload)
        mark_task = asyncio.create_task(
            self._operational_journal.mark_terminal(
                candidate=candidate,
                pattern=pattern,
                status="published",
                reason="candidate_published",
            )
        )
        try:
            await asyncio.shield(mark_task)
        except asyncio.CancelledError:
            await mark_task
            raise
        return True

    async def _scrub_source_invalidated_candidates(self) -> None:
        retained: list[dict[str, Any]] = []
        for candidate in self.pending_candidates:
            if await self._operational_candidate_cases_are_current(candidate):
                retained.append(candidate)
                continue
            self._record_candidate_terminal(candidate, "invalidated")
            pattern_id = str(candidate.get("suggested_pattern", ""))
            pattern = self._pattern_publications.pop(pattern_id, None)
            if pattern is not None:
                await self._operational_journal.mark_terminal(
                    candidate=candidate,
                    pattern=pattern,
                    status="invalidated",
                    reason="source_no_longer_current",
                )
            self._forget_published_pattern(pattern_id)
        self.pending_candidates[:] = retained
        self._rebuild_pending_pattern_index()
        self._flush_cursor = 0

    async def _scrub_durable_source_invalidated_candidates(self) -> None:
        _first, total = await self._operational_journal.pending_page(limit=1)
        if not total:
            self._durable_source_scrub_offset = 0
            return
        offset = min(self._durable_source_scrub_offset, max(total - 1, 0))
        rows, _ = await self._operational_journal.pending_page(
            limit=min(self._max_pending_candidates, _MAX_SOURCE_SCRUB_RECORDS),
            offset=offset,
        )
        for candidate, pattern, _pattern_published in rows:
            if await self._operational_candidate_cases_are_current(candidate):
                continue
            self._record_candidate_terminal(candidate, "invalidated")
            await self._operational_journal.mark_terminal(
                candidate=candidate,
                pattern=pattern,
                status="invalidated",
                reason="source_no_longer_current",
            )
        self._durable_source_scrub_offset = 0 if offset + len(rows) >= total else offset + len(rows)
        if self._durable_source_scrub_offset:
            self.record_behavior(
                "operational_candidate_source_scrub_deferred", total - offset - len(rows)
            )

    def _index_pending_candidate(self, candidate: dict[str, Any]) -> None:
        pattern_id = str(candidate.get("suggested_pattern") or "")
        if pattern_id:
            self._pending_by_pattern_id[pattern_id] = candidate

    def _rebuild_pending_pattern_index(self) -> None:
        self._pending_by_pattern_id = {}
        for candidate in self.pending_candidates:
            self._index_pending_candidate(candidate)

    def _forget_published_pattern(self, pattern_id: str) -> None:
        retained = BoundedLruSet[str](self._max_pending_candidates)
        for retained_id in self._published_pattern_ids:
            if retained_id != pattern_id:
                retained.add(retained_id)
        self._published_pattern_ids = retained

    async def _publish_proposal(self, topic: str, payload: dict[str, Any]) -> bool:
        raise NotImplementedError

    async def _operational_candidate_cases_are_current(
        self,
        candidate: Mapping[str, Any],
    ) -> bool:
        try:
            async with asyncio.timeout(
                getattr(self, "_provider_timeout_seconds", _DEFAULT_PROVIDER_TIMEOUT_SECONDS)
            ):
                return await operational_candidate_cases_are_current(self, candidate)
        except TimeoutError:
            self.record_behavior("operational_case_candidate_source_timeout")
            return False

    def _ensure_pending_capacity(self) -> None:
        raise NotImplementedError

    def record_behavior(self, key: str, count: int = 1) -> None:
        raise NotImplementedError


def _candidate_identity(candidate: Mapping[str, Any]) -> str:
    provenance = candidate.get("provenance")
    if isinstance(provenance, Mapping):
        pattern_id = provenance.get("pattern_id")
        if isinstance(pattern_id, str) and pattern_id:
            return pattern_id
    suggested = candidate.get("suggested_pattern")
    if isinstance(suggested, str) and suggested:
        return suggested
    return canonical_json_digest(candidate)


def _candidate_correlation_id(candidate: Mapping[str, Any]) -> str:
    return f"norns:{_candidate_identity(candidate)[:64]}"


def _candidate_idempotency_key(candidate: Mapping[str, Any]) -> str:
    return f"rule-candidate:{_candidate_identity(candidate)}"


def _pattern_id(candidate: Mapping[str, Any], pattern: Mapping[str, Any]) -> str:
    pattern_id = candidate.get("suggested_pattern")
    if (
        not isinstance(pattern_id, str)
        or len(pattern_id) != 64
        or any(character not in "0123456789abcdef" for character in pattern_id)
        or pattern.get("pattern_id") != pattern_id
    ):
        raise ValueError("Norns operational candidate Pattern identity is invalid")
    return pattern_id


def _state_key(pattern_id: str) -> str:
    return f"{_STATE_PREFIX}/{pattern_id}"


def _digest(value: Mapping[str, Any]) -> str:
    return canonical_json_digest(value)


def _required_digest(record: Mapping[str, Any], field: str) -> str:
    value = record.get(field)
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"Norns operational candidate {field} is invalid")
    return value


def _validate_pending(
    record: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
    pattern: Mapping[str, Any],
) -> None:
    pattern_id = _pattern_id(candidate, pattern)
    if (
        record.get("kind") != _KIND
        or record.get("status") != "pending"
        or record.get("pattern_id") != pattern_id
        or _required_digest(record, "candidate_digest") != _digest(candidate)
        or _required_digest(record, "pattern_digest") != _digest(pattern)
        or not isinstance(record.get("pattern_published"), bool)
        or record.get("candidate") != dict(candidate)
        or record.get("pattern") != dict(pattern)
    ):
        raise ValueError("Norns operational candidate durable identity conflict")


def _validate_terminal_identity(
    record: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
    pattern: Mapping[str, Any],
) -> None:
    if (
        record.get("kind") != _KIND
        or record.get("status") not in _TERMINAL
        or record.get("pattern_id") != _pattern_id(candidate, pattern)
        or _required_digest(record, "candidate_digest") != _digest(candidate)
        or _required_digest(record, "pattern_digest") != _digest(pattern)
    ):
        raise ValueError("Norns operational candidate terminal identity conflict")


def _revision(record: Mapping[str, Any]) -> int:
    revision = record.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("Norns operational candidate revision is invalid")
    return revision


__all__ = ["NornsCandidateDeliveryMixin", "NornsOperationalCandidateJournal"]
