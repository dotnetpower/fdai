"""Read stateful ActionType precondition evidence from the runtime ontology."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from fdai.core.operational_context.operating_intent_admission import (
    OperatingIntentAdmission,
)
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


@runtime_checkable
class OperatingIntentAdmissionReader(Protocol):
    """Resolve whether the deployment-owned intent source currently backs authority."""

    async def resolve(self, *, now: datetime) -> OperatingIntentAdmission: ...


class OntologyChangeWindowEvidenceProvider:
    """Resolve effective maintenance authority without granting execution authority.

    A truncated read and an effective freeze or quiet window with unusable
    bounds both deny: neither proves that the target is inside an open
    maintenance window.

    A projected ``ChangeWindow`` is a graph object, not a standing grant. When an
    ``intent_admission`` reader is bound, a window may only open while the
    deployment-owned operating-intent source is *currently* admitted at the decision
    instant. A source that has since gone stale, missing, cross-release, or
    unreachable quarantines the whole maintenance-authority surface even though its
    objects remain readable as evidence and history. Denying every window - rather
    than only the quarantined source's own - is the fail-closed direction, because a
    quarantined admission names no ownership at all.

    An admitted source vouches only for the identities its own manifest owns. The
    generic ``FDAI_OPERATING_MODEL_PATH`` snapshot and the continuous operating-model
    worker can both project a ``ChangeWindow``, and neither is covered by the intent
    source's pin, so an admitted intent source MUST NOT bless a window it never
    supplied. An *allowing* window therefore opens only when the admission owns its
    id. A *blocking* window still blocks whoever supplied it: refusing to act is
    never the unsafe direction.
    """

    def __init__(
        self,
        store: OntologyInstanceStore,
        *,
        query_limit: int = 500,
        intent_admission: OperatingIntentAdmissionReader | None = None,
    ) -> None:
        if query_limit < 1:
            raise ValueError("query_limit MUST be positive")
        self._store = store
        self._query_limit = query_limit
        self._intent_admission = intent_admission

    async def is_active(self, *, target_ref: str, at: datetime) -> bool:
        if at.tzinfo is None:
            raise ValueError("at MUST be timezone-aware")
        owned_object_ids: frozenset[str] | None = None
        if self._intent_admission is not None:
            admission = await self._intent_admission.resolve(now=at)
            if not admission.grants_intent_authority:
                return False
            owned_object_ids = admission.owned_object_ids
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
            window_kind = str(properties.get("window_kind") or "").strip().casefold()
            effective_from = _parse_timestamp(properties.get("effective_from"))
            effective_to = _parse_timestamp(properties.get("effective_to"))
            if effective_from is None or effective_to is None or effective_from > effective_to:
                # An effective blocking window whose bounds cannot be resolved
                # is not proof that the freeze is over, so it denies instead of
                # being skipped.
                if window_kind in _BLOCKING_WINDOW_KINDS:
                    return False
                continue
            if not effective_from <= at <= effective_to:
                continue
            if window_kind in _BLOCKING_WINDOW_KINDS:
                return False
            if window_kind in _ALLOWING_WINDOW_KINDS:
                if owned_object_ids is not None and record.id not in owned_object_ids:
                    # An admitted intent source vouches only for what it supplied.
                    continue
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
    "OperatingIntentAdmissionReader",
]
