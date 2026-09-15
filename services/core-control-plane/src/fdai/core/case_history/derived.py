"""Bounded, scope-isolated derived records sharing one CAS deletion boundary."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.shared.providers.case_history import (
    CaseHistoryDerivedDataStore,
    CaseHistoryRevisionRecord,
)
from fdai.shared.providers.state_store import StateStore

from .service import CaseHistoryMaterializer


class CaseHistoryProjectionStore:
    """Retain only current-case projections; scope CAS serializes writes with deletion.

    Bounds apply before storage. Saturation backpressures publication instead of evicting
    evidence. Source metadata remains the deletion fence; no second lifecycle is created.
    """

    def __init__(
        self,
        *,
        store: StateStore,
        materializer: CaseHistoryMaterializer,
        access_scope_digest: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if len(access_scope_digest) != 64 or any(
            character not in "0123456789abcdef" for character in access_scope_digest
        ):
            raise ValueError("derived case scope MUST be SHA-256")
        self._store = store
        self._materializer = materializer
        self._scope = access_scope_digest
        self._clock = clock or (lambda: datetime.now(UTC))
        self._key = f"case-history-derived:v1:{access_scope_digest}"

    async def _state(self) -> dict[str, Any]:
        value = await self._store.read_state(self._key)
        if value is None:
            return {"revision": 0, "entries": {}}
        if (
            not isinstance(value.get("revision"), int)
            or isinstance(value["revision"], bool)
            or value["revision"] < 1
            or not isinstance(value.get("entries"), dict)
            or len(value["entries"]) > 512
        ):
            raise ValueError("derived case state is malformed")
        for key, entry in value["entries"].items():
            if (
                not isinstance(key, str)
                or len(key) > 512
                or not isinstance(entry, dict)
                or set(entry) != {"case_refs", "value"}
                or not isinstance(entry["value"], dict)
                or not isinstance(entry["case_refs"], list)
                or not 1 <= len(entry["case_refs"]) <= 100
                or any(
                    not isinstance(ref, str) or len(ref) > 512 or len(ref.split(":")) != 4
                    for ref in entry["case_refs"]
                )
            ):
                raise ValueError("derived case entry is malformed")
            source = entry["value"]
            if "cases" not in source:
                parent = value["entries"].get(
                    f"{key.split(':emitted:', 1)[0]}:snapshot:{source.get('digest')}"
                )
                source = parent["value"] if parent else {}
            if source.get("access_scope_digest") != self._scope or entry[
                "case_refs"
            ] != _case_references(source):
                raise ValueError("derived case lineage does not match retained content")
        return dict(value)

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        """Read an internal projection; external readers still require case authorization."""
        entry = (await self._state())["entries"].get(key)
        return dict(entry["value"]) if entry is not None else None

    async def pattern_records(self) -> tuple[Mapping[str, Any], ...]:
        """Return bounded internal pattern candidates for an already authorized reader."""
        state = await self._state()
        return tuple(
            dict(entry["value"])
            for key, entry in sorted(state["entries"].items())
            if ":pattern:" in key
        )

    async def write_state_if_absent(self, key: str, value: Mapping[str, Any]) -> bool:
        return await self._write(key, value, expected_revision=None)

    async def write_state_with_audit_if_absent(
        self,
        key: str,
        value: Mapping[str, Any],
        audit_entry: Mapping[str, Any],
    ) -> bool:
        return await self._write(key, value, expected_revision=None, audit_entry=audit_entry)

    async def compare_and_set_state_with_audit(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        return await self._write(
            key, value, expected_revision=expected_revision, audit_entry=audit_entry
        )

    async def _write(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int | None,
        audit_entry: Mapping[str, Any] | None = None,
    ) -> bool:
        if not isinstance(key, str) or not key or len(key) > 512:
            raise ValueError("derived case key MUST be bounded and non-empty")
        for _attempt in range(3):
            state = await self._state()
            entries = dict(state["entries"])
            existing = entries.get(key)
            if expected_revision is None and existing is not None:
                return False
            if expected_revision is not None and (
                existing is None or existing["value"].get("revision") != expected_revision
            ):
                return False
            parent = entries.get(f"{key.split(':emitted:', 1)[0]}:snapshot:{value.get('digest')}")
            source = value if "cases" in value else parent["value"] if parent else {}
            purpose = source.get("purpose")
            if source.get("access_scope_digest") != self._scope or not isinstance(purpose, str):
                raise ValueError("derived case source scope and purpose are required")
            references = _case_references(source)
            for reference in references:
                if not await self._materializer.current_revision_available(
                    case_ref=reference,
                    access_scope_digest=self._scope,
                    purpose=purpose,
                    now=self._clock(),
                ):
                    raise PermissionError(
                        "derived case source is not current or is pending deletion"
                    )
            entries[key] = {"case_refs": references, "value": dict(value)}
            if len(entries) > 512:
                raise RuntimeError("derived case scope capacity exhausted; retention is required")
            updated = {"revision": state["revision"] + 1, "entries": entries}
            if len(json.dumps(updated, allow_nan=False).encode()) > 4 * 1024 * 1024:
                raise RuntimeError("derived case scope byte capacity exhausted")
            if await self._commit(state, updated, audit_entry):
                return True
        raise RuntimeError("derived case concurrent update budget exhausted")

    async def _commit(
        self,
        prior: Mapping[str, Any],
        updated: Mapping[str, Any],
        audit_entry: Mapping[str, Any] | None = None,
    ) -> bool:
        audit = (
            dict(audit_entry)
            if audit_entry is not None
            else {
                "action_kind": "case_history.derived_updated",
                "owner_agent": "Muninn",
                "scope_digest": self._scope,
                "revision": updated["revision"],
                "timestamp": self._clock().isoformat(),
                "execution_authority": False,
            }
        )
        if prior["revision"] == 0:
            return await self._store.write_state_with_audit_if_absent(self._key, updated, audit)
        return await self._store.compare_and_set_state_with_audit(
            self._key,
            updated,
            expected_revision=prior["revision"],
            audit_entry=audit,
        )

    async def purge(self, record: CaseHistoryRevisionRecord) -> None:
        """Remove every copied projection for a claimed case before source tombstoning."""
        if (
            record.access_scope_digest != self._scope
            or record.legal_hold
            or record.deletion_started_at is None
        ):
            raise PermissionError("derived purge requires a same-scope source deletion claim")
        for _attempt in range(3):
            state = await self._state()
            entries = {
                key: entry
                for key, entry in state["entries"].items()
                if not any(
                    reference.split(":")[1] == record.case_id for reference in entry["case_refs"]
                )
            }
            if await self._commit(state, {"revision": state["revision"] + 1, "entries": entries}):
                return
        raise RuntimeError("derived case deletion contention budget exhausted")


class CaseHistoryDerivedRetention:
    """Resolve the source scope into the same projection store used by Muninn writers."""

    def __init__(
        self,
        *,
        store: StateStore,
        materializer: CaseHistoryMaterializer,
        downstream: tuple[CaseHistoryDerivedDataStore, ...] = (),
    ) -> None:
        self._store = store
        self._materializer = materializer
        self._downstream = downstream

    async def purge(self, record: CaseHistoryRevisionRecord) -> None:
        if record.legal_hold or record.deletion_started_at is None:
            raise PermissionError("derived purge requires an unheld source deletion claim")
        for downstream in self._downstream:
            await downstream.purge(record)
        await CaseHistoryProjectionStore(
            store=self._store,
            materializer=self._materializer,
            access_scope_digest=record.access_scope_digest,
        ).purge(record)


def _case_references(value: Mapping[str, Any]) -> list[str]:
    cases = value.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 100:
        raise ValueError("derived case records require bounded source references")
    references = []
    for item in cases:
        case = item.get("case", item) if isinstance(item, dict) else {}
        reference = (
            f"case-history:{case.get('case_id')}:{case.get('revision')}:"
            f"{case.get('manifest_digest')}"
        )
        references.append(reference)
    return sorted(set(references))
