"""HIL reject reason materialization pipeline (Wave 3 step B pipeline).

Bridges the existing HIL approval channel and the operator-memory
store. When a HIL reviewer rejects an action with a written reason,
that reason MAY carry operationally useful guidance ("do not restart
this VM during business hours"). Turning it into a durable
:class:`OperatorMemoryEntry` requires a **second, distinct** operator
to review and approve the memory-worthy content - otherwise a single
rejecter would be able to plant self-approved notes into the composer.
This module is the pure domain logic for that second-approval step;
the HTTP / ChatOps callback that invokes it lands in a follow-up
slice.

Design invariants
-----------------
- Second-approval separation. ``first_approver`` (the rejecter, taken
  from :attr:`HilResponse.approver_id`) and ``second_approver`` (the
  argument to :meth:`HilRejectMaterializer.materialize`) MUST be
  distinct principals - case-insensitive after ``strip()``. This
  mirrors :func:`_reject_policy_violations`'s ``self_approval`` check
  but rejects earlier, with a pipeline-specific code, so the caller's
  UI can differentiate "you cannot self-approve" from "the store
  rejected the write for a different reason".
- The rejection **must** be a real rejection with content. A poll that
  timed out or came back APPROVE has no reason to materialize; a REJECT
  with empty ``reason`` is not memory-worthy either. Both cases raise
  :class:`HilMaterializationError` before the store is touched.
- The store is authoritative. The materializer never mutates a stored
  entry, never bypasses the shared ``_reject_policy_violations`` gate,
  and does not swallow store-side errors (a duplicate id or an
  injection marker in the reason surfaces as
  :class:`OperatorMemoryPolicyError`).
- Kept ``core/``-safe: this module imports only from
  ``aiopspilot.core.operator_memory`` and
  ``aiopspilot.shared.providers.hil_channel`` (a Protocol package),
  never from ``aiopspilot.delivery.*``.

See also
--------
- ``docs/roadmap/prompt-composition.md``
  § Wave 3 step B pipeline - what shipped
- ``.github/instructions/architecture.instructions.md`` § Human Override
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid4

from aiopspilot.core.operator_memory.store import OperatorMemoryStore
from aiopspilot.core.operator_memory.types import (
    MemoryCategory,
    MemorySource,
    OperatorMemoryEntry,
    ScopeKind,
)
from aiopspilot.shared.providers.hil_channel import HilDecision, HilResponse


class HilMaterializationError(ValueError):
    """Raised when the second-approval step refuses to build an entry.

    Structured with a stable ``code`` so a caller (a future HTTP
    handler or ChatOps command) can dispatch on it for telemetry and
    UI messages without pattern-matching on the human-readable text.

    Codes
    -----
    ``wrong_decision``
        The referenced :class:`HilResponse` is not a REJECT.
    ``empty_reason``
        The rejecter typed no reason - nothing to materialize.
    ``missing_first_approver``
        :attr:`HilResponse.approver_id` is ``None`` or blank; without
        it the store cannot record the ``author`` field.
    ``missing_second_approver``
        The pipeline was invoked without a second, non-blank approver.
    ``same_principal``
        First and second approvers are the same after normalization.
        Distinct from the store's ``self_approval`` code so the UI
        can differentiate the two rejection points.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code: Final[str] = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class HilRejectMaterial:
    """Everything the materializer needs beyond the raw :class:`HilResponse`.

    ``scope_*`` and ``category`` come from whichever workflow triggers
    the second approval (a ChatOps command, an HTTP endpoint, or a
    reconciler poll). ``source_ref`` is the audit-trail pointer -
    conventionally ``hil.reject:<approval_id>`` so a reader can trace
    the entry back to the exact HIL run.

    ``ttl_seconds`` defaults to ``None`` (indefinite) because most
    HIL-derived guidance is long-lived per the Human Override policy;
    the caller MAY narrow it when the guidance is known to be
    temporary (e.g. a maintenance-window preference).
    """

    scope_kind: ScopeKind
    scope_ref: str
    category: MemoryCategory
    source_ref: str
    ttl_seconds: int | None = None
    metadata: dict[str, str] = field(default_factory=dict)


class HilRejectMaterializer:
    """Turn a HIL reject reason into a persisted :class:`OperatorMemoryEntry`.

    Dependency-injected so tests can supply a
    :class:`~aiopspilot.core.operator_memory.store.InMemoryOperatorMemoryStore`
    and a deterministic ``entry_id_fn`` / ``now_fn`` clock. The
    Postgres-backed adapter plugs in via the same
    :class:`OperatorMemoryStore` Protocol without touching this class.
    """

    def __init__(
        self,
        *,
        store: OperatorMemoryStore,
        entry_id_fn: Callable[[], UUID] | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._store: Final[OperatorMemoryStore] = store
        self._entry_id_fn: Final[Callable[[], UUID]] = entry_id_fn or uuid4
        self._now_fn: Final[Callable[[], datetime] | None] = now_fn

    async def materialize(
        self,
        *,
        hil_response: HilResponse,
        second_approver: str,
        material: HilRejectMaterial,
    ) -> OperatorMemoryEntry:
        """Validate the inputs, build an entry, and persist it via the store.

        Returns the persisted entry so the caller does not need to
        re-read from the store. Raises :class:`HilMaterializationError`
        for pipeline-level violations (wrong decision, empty reason,
        missing / same-principal approvers) and propagates
        :class:`OperatorMemoryPolicyError` unchanged when the store's
        deeper policy check refuses the write.
        """

        self._reject_pipeline_violations(hil_response=hil_response, second_approver=second_approver)
        # Types narrow after validation: ``approver_id`` and ``reason``
        # are guaranteed non-empty by _reject_pipeline_violations above.
        assert hil_response.approver_id is not None  # noqa: S101 - narrows for mypy
        assert hil_response.reason is not None  # noqa: S101 - narrows for mypy
        entry = OperatorMemoryEntry(
            id=self._entry_id_fn(),
            scope_kind=material.scope_kind,
            scope_ref=material.scope_ref,
            category=material.category,
            body=hil_response.reason,
            source_event=MemorySource.HIL_REJECT,
            source_ref=material.source_ref,
            author=hil_response.approver_id,
            approved_by=second_approver,
            created_at=self._now(),
            ttl_seconds=material.ttl_seconds,
        )
        return await self._store.append(entry)

    def _now(self) -> datetime:
        if self._now_fn is None:
            return datetime.now(tz=UTC)
        return self._now_fn()

    @staticmethod
    def _reject_pipeline_violations(
        *,
        hil_response: HilResponse,
        second_approver: str,
    ) -> None:
        if hil_response.decision is not HilDecision.REJECT:
            raise HilMaterializationError(
                "wrong_decision",
                f"HIL response decision MUST be REJECT to materialize a memory "
                f"entry, got {hil_response.decision!r}",
            )
        if not hil_response.reason or not hil_response.reason.strip():
            raise HilMaterializationError(
                "empty_reason",
                "HIL reject reason is empty - nothing to materialize",
            )
        first_approver = hil_response.approver_id
        if first_approver is None or not first_approver.strip():
            raise HilMaterializationError(
                "missing_first_approver",
                "HIL response is missing approver_id - the store cannot "
                "record the memory entry's author",
            )
        if not second_approver or not second_approver.strip():
            raise HilMaterializationError(
                "missing_second_approver",
                "second_approver MUST be a non-empty principal",
            )
        if first_approver.strip().lower() == second_approver.strip().lower():
            raise HilMaterializationError(
                "same_principal",
                "first and second approvers MUST be distinct - "
                "the rejecter cannot self-approve the memory entry",
            )


__all__ = [
    "HilMaterializationError",
    "HilRejectMaterial",
    "HilRejectMaterializer",
]
