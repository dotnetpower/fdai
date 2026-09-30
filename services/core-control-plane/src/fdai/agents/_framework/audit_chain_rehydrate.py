"""Restart helpers for provider-backed Saga audit chains."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.agents._framework.adapters import AuditEntry
from fdai.shared.providers.state_store import StateStore


async def rehydrate_audit_entries(store: StateStore) -> list[AuditEntry]:
    """Return Saga adapter entries restored from a verified durable chain."""

    if not await store.verify_chain():
        raise RuntimeError("durable audit hash chain verification failed")
    audit_entries = getattr(store, "audit_entries", None)
    if audit_entries is None:
        return []
    restored: list[AuditEntry] = []
    for record in audit_entries:
        entry = record.get("entry") if isinstance(record, Mapping) else None
        if not isinstance(entry, Mapping):
            raise RuntimeError("durable audit entry is malformed")
        if not _looks_like_saga_chain_entry(entry):
            continue
        restored.append(_audit_entry_from_state(entry))
    return restored


def _looks_like_saga_chain_entry(entry: Mapping[str, Any]) -> bool:
    required = {"seq", "prev_hash", "entry_hash", "principal", "topic", "correlation_id"}
    if required.issubset(entry):
        return True
    if entry.get("action_kind") == "audit.record":
        raise RuntimeError("durable audit entry is malformed")
    return False


def _audit_entry_from_state(entry: Mapping[str, Any]) -> AuditEntry:
    try:
        return AuditEntry(
            seq=int(entry["seq"]),
            prev_hash=str(entry["prev_hash"]),
            entry_hash=str(entry["entry_hash"]),
            principal=str(entry["principal"]),
            topic=str(entry["topic"]),
            correlation_id=str(entry["correlation_id"]),
            payload_digest=str(entry["payload_digest"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("durable audit entry is malformed") from exc


__all__ = ["rehydrate_audit_entries"]
