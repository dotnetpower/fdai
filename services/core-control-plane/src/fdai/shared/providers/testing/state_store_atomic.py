"""Atomic multi-row helpers for the in-memory StateStore."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any


class InMemoryStateAtomicMixin:
    async def compare_and_set_state_pair_with_audit(
        self: Any,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        second_key: str,
        second_value: Mapping[str, Any],
        expected_second_revision: int,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        if expected_revision < 0 or expected_second_revision < 0 or key == second_key:
            raise ValueError("state pair expected revisions or keys are invalid")
        with self._lock:
            first = self._state.get(key)
            second = self._state.get(second_key)
            first_revision = first.get("revision", 0) if first is not None else 0
            second_revision = second.get("revision", 0) if second is not None else 0
            if (
                first_revision != expected_revision
                or second_revision != expected_second_revision
                or (expected_revision == 0 and first is not None)
                or (expected_second_revision == 0 and second is not None)
            ):
                return False
            snapshot = self._snapshot_keys_locked(key, second_key)
            audit_length_before = len(self._audit)
            try:
                self._write_locked(key, value)
                self._write_locked(second_key, second_value)
                self._append_audit_locked(audit_entry)
            except Exception:
                self._restore_keys_locked(snapshot)
                del self._audit[audit_length_before:]
                raise
            return True

    async def compare_and_set_state_with_audit_and_insert_before(
        self: Any,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        insert_key: str,
        insert_value: Mapping[str, Any],
        not_before: datetime,
        expires_at: datetime,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        with self._lock:
            current_time = self._linearization_clock()
            existing = self._state.get(key)
            current_revision = existing.get("revision", 0) if existing is not None else 0
            if (
                current_time.tzinfo is None
                or not_before.tzinfo is None
                or expires_at.tzinfo is None
                or not not_before <= current_time < expires_at
                or current_revision != expected_revision
                or insert_key in self._state
            ):
                return False
            snapshot = self._snapshot_keys_locked(key, insert_key)
            audit_length_before = len(self._audit)
            try:
                self._write_locked(key, value)
                self._write_locked(insert_key, insert_value)
                self._append_audit_locked(audit_entry)
            except Exception:
                self._restore_keys_locked(snapshot)
                del self._audit[audit_length_before:]
                raise
            return True

    async def compare_and_set_state_pair_with_audit_before(
        self: Any,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        second_key: str,
        second_value: Mapping[str, Any],
        expected_second_revision: int,
        not_before: datetime,
        expires_at: datetime,
        insert_key: str | None = None,
        insert_value: Mapping[str, Any] | None = None,
        guard_key: str | None = None,
        guard_value: Mapping[str, Any] | None = None,
        expected_guard_revision: int | None = None,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        with self._lock:
            current_time = self._linearization_clock()
            first = self._state.get(key)
            second = self._state.get(second_key)
            guard = self._state.get(guard_key) if guard_key is not None else None
            first_revision = first.get("revision", 0) if first is not None else 0
            second_revision = second.get("revision", 0) if second is not None else 0
            guard_revision = guard.get("revision", 0) if guard is not None else 0
            guard_supplied = (
                guard_key is not None
                and guard_value is not None
                and expected_guard_revision is not None
            )
            if (
                current_time.tzinfo is None
                or not_before.tzinfo is None
                or expires_at.tzinfo is None
                or not not_before <= current_time < expires_at
                or first_revision != expected_revision
                or second_revision != expected_second_revision
                or (expected_revision == 0 and first is not None)
                or (expected_second_revision == 0 and second is not None)
                or (insert_key is None) != (insert_value is None)
                or (insert_key is not None and insert_key in self._state)
                or any(
                    item is not None for item in (guard_key, guard_value, expected_guard_revision)
                )
                is not guard_supplied
                or (
                    guard_supplied
                    and (
                        expected_guard_revision is None or guard_revision != expected_guard_revision
                    )
                )
            ):
                return False
            snapshot_keys = tuple(
                item for item in (key, second_key, insert_key, guard_key) if item is not None
            )
            snapshot = self._snapshot_keys_locked(*snapshot_keys)
            audit_length_before = len(self._audit)
            try:
                self._write_locked(key, value)
                self._write_locked(second_key, second_value)
                if insert_key is not None and insert_value is not None:
                    self._write_locked(insert_key, insert_value)
                if guard_key is not None and guard_value is not None:
                    self._write_locked(guard_key, guard_value)
                self._append_audit_locked(audit_entry)
            except Exception:
                self._restore_keys_locked(snapshot)
                del self._audit[audit_length_before:]
                raise
            return True

    async def advance_state_with_epoch(
        self: Any,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        epoch_key: str,
        epoch_value: Mapping[str, Any],
        expected_epoch_revision: int,
        forbidden_keys: tuple[str, ...],
    ) -> bool:
        with self._lock:
            existing = self._state.get(key)
            epoch = self._state.get(epoch_key)
            current_revision = existing.get("revision", 0) if existing is not None else 0
            epoch_revision = epoch.get("revision", 0) if epoch is not None else 0
            if (
                current_revision != expected_revision
                or epoch_revision != expected_epoch_revision
                or (expected_revision == 0 and existing is not None)
                or any(forbidden in self._state for forbidden in forbidden_keys)
            ):
                return False
            self._write_locked(key, value)
            self._write_locked(epoch_key, epoch_value)
            return True


__all__ = ["InMemoryStateAtomicMixin"]
