"""Typed models for operator memory entries.

Kept dependency-free (frozen dataclasses + StrEnum) so ``core/``
remains importable without pydantic on the request path. The
Postgres schema in Wave 3 step B mirrors this shape directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ScopeKind(StrEnum):
    """Which scope hierarchy layer an operator note applies to.

    The **only** permitted values are ``resource-group`` and
    ``resource`` per the Human Override policy in
    ``.github/instructions/architecture.instructions.md``. Broader
    scopes (organization / account / vertical) are rejected at write
    time - disabling a rule everywhere is a **rule retirement**, not
    an operator memory entry, and MUST flow through the catalog
    pipeline.
    """

    RESOURCE_GROUP = "resource-group"
    RESOURCE = "resource"


class MemorySource(StrEnum):
    """Where an operator memory entry originated.

    Wave 3 step B initially populates only :attr:`HIL_REJECT`; later
    waves extend the source taxonomy so a fork can wire additional
    upstream events without changing the store contract.
    """

    HIL_REJECT = "hil.reject"
    HIL_APPROVE_REASON = "hil.approve.reason"
    OVERRIDE_CREATE = "override.create"
    CHATOPS_PREFERENCE = "chatops.preference"
    PR_REVIEW = "pr.review"


class MemoryCategory(StrEnum):
    """Semantic bucket used by the composer to decide relevance.

    Kept small and structured; free-form text without a category
    would be an injection vector because the composer would not know
    how to weigh it against other layers.
    """

    PREFERENCE = "preference"
    OVERRIDE_NOTE = "override-note"
    FORBIDDEN_ACTION = "forbidden-action"
    RUNBOOK_HINT = "runbook-hint"


@dataclass(frozen=True, slots=True)
class OperatorMemoryEntry:
    """One append-only operator memory row.

    ``author`` is the operator whose reasoning produced the entry
    (e.g. the HIL reject reason author). ``approved_by`` is the
    **second, distinct** operator who reviewed and approved the
    entry before it landed in the store; the store rejects any entry
    where the two match to prevent self-approval.

    ``superseded_by`` points to a later entry that replaces this one.
    Append-only means a "replacement" never edits the original row;
    the newer entry gets a fresh id and the older row's
    ``superseded_by`` field is filled via
    :meth:`OperatorMemoryStore.supersede`.
    """

    id: UUID
    scope_kind: ScopeKind
    scope_ref: str
    category: MemoryCategory
    body: str
    source_event: MemorySource
    source_ref: str
    author: str
    approved_by: str
    created_at: datetime
    superseded_by: UUID | None = None
    ttl_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class OperatorScope:
    """The composed scope the composer resolves against when injecting memory.

    An event carries a ``resource_group_ref`` at minimum (every Azure
    resource lives in one) and MAY carry a ``resource_ref`` when the
    event narrows down to a single resource. The composer queries
    :meth:`OperatorMemoryStore.list_active_for_scope` twice - once at
    the resource-group level, once at the resource level when a
    ``resource_ref`` is present - and concatenates the results in
    increasing-specificity order so the most specific note lands
    closest to the model's next turn.

    A ``None`` scope means "no operator memory this call" (startup
    composition, tests that only care about the base + pack layers).
    """

    resource_group_ref: str
    resource_ref: str | None = None


__all__ = [
    "MemoryCategory",
    "MemorySource",
    "OperatorMemoryEntry",
    "OperatorScope",
    "ScopeKind",
]
