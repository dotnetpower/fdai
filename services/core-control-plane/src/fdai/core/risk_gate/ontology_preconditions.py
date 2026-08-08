"""Read stateful ActionType precondition evidence from the runtime ontology."""

from __future__ import annotations

from datetime import datetime

from fdai.shared.providers.ontology_instance import OntologyInstanceStore

_TERMINAL_ACTION_STATUSES = frozenset(
    {
        "deny_dropped",
        "rejected",
        "rollback_failed",
        "rolled_back",
        "succeeded",
    }
)
_EFFECTIVE_WINDOW_STATUSES = frozenset({"active", "reviewed"})
_ALLOWING_WINDOW_KINDS = frozenset({"allow", "emergency", "maintenance"})
_BLOCKING_WINDOW_KINDS = frozenset({"freeze", "quiet"})


class OntologyOpenActionEvidenceProvider:
    """Detect conflicting non-terminal ActionRuns on one logical target."""

    def __init__(self, store: OntologyInstanceStore, *, query_limit: int = 500) -> None:
        if query_limit < 1:
            raise ValueError("query_limit MUST be positive")
        self._store = store
        self._query_limit = query_limit

    async def has_conflict(
        self,
        *,
        target_ref: str,
        excluding_idempotency_key: str,
    ) -> bool:
        snapshot = await self._store.query_objects(
            object_types=("ActionRun",),
            property_equals={"target_ref": target_ref},
            limit=self._query_limit,
        )
        if snapshot.truncated:
            return True
        for record in snapshot.objects:
            properties = record.properties
            if properties.get("idempotency_key") == excluding_idempotency_key:
                continue
            status = str(properties.get("status") or "").strip().casefold()
            if status not in _TERMINAL_ACTION_STATUSES:
                return True
        return False


class OntologyChangeWindowEvidenceProvider:
    """Resolve effective maintenance authority without granting execution authority."""

    def __init__(self, store: OntologyInstanceStore, *, query_limit: int = 500) -> None:
        if query_limit < 1:
            raise ValueError("query_limit MUST be positive")
        self._store = store
        self._query_limit = query_limit

    async def is_active(self, *, target_ref: str, at: datetime) -> bool:
        if at.tzinfo is None:
            raise ValueError("at MUST be timezone-aware")
        snapshot = await self._store.query_objects(
            object_types=("ChangeWindow",),
            property_equals={"scope_ref": target_ref},
            limit=self._query_limit,
        )
        if snapshot.truncated:
            return False
        allowing_window = False
        for record in snapshot.objects:
            properties = record.properties
            status = str(properties.get("status") or "").strip().casefold()
            if status not in _EFFECTIVE_WINDOW_STATUSES:
                continue
            effective_from = _parse_timestamp(properties.get("effective_from"))
            effective_to = _parse_timestamp(properties.get("effective_to"))
            if effective_from is None or effective_to is None or effective_from > effective_to:
                continue
            if not effective_from <= at <= effective_to:
                continue
            window_kind = str(properties.get("window_kind") or "").strip().casefold()
            if window_kind in _BLOCKING_WINDOW_KINDS:
                return False
            if window_kind in _ALLOWING_WINDOW_KINDS:
                allowing_window = True
        return allowing_window


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if not isinstance(value, str):
        return None
    try:
        resolved = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return resolved if resolved.tzinfo is not None else None


__all__ = [
    "OntologyChangeWindowEvidenceProvider",
    "OntologyOpenActionEvidenceProvider",
]
