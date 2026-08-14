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
  ``fdai.core.operator_memory`` and
  ``fdai.shared.providers.hil_channel`` (a Protocol package),
  never from ``fdai.delivery.*``.

See also
--------
- ``docs/roadmap/decisioning/prompt-composition.md``
  § Wave 3 step B pipeline - what shipped
- ``.github/instructions/architecture.instructions.md`` § Human Override
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final
from uuid import NAMESPACE_DNS, UUID, uuid5

from fdai.core.operator_memory.store import OperatorMemoryPolicyError, OperatorMemoryStore
from fdai.core.operator_memory.types import (
    MemoryCategory,
    MemorySource,
    OperatorMemoryEntry,
    ScopeKind,
)
from fdai.shared.providers.hil_channel import HilDecision, HilResponse

DEFAULT_SECOND_APPROVAL_WINDOW_SECONDS: Final = 3600
"""How long after a rejection a second approval still counts, by default."""

_ENTRY_NAMESPACE: Final = uuid5(NAMESPACE_DNS, "hil-second-approval.operator-memory.fdai.invalid")
"""Derived, not literal, so the repository carries no fixed GUID value."""


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
    ``missing_response_time``
        The referenced :class:`HilResponse` carries no ``received_at``,
        so the second approval cannot prove it happened inside its
        window. Timeliness is never assumed.
    ``approval_expired``
        The second approval arrived after the rejection's approval
        window closed. Stale consent never materializes guidance.
    ``already_materialized``
        This exact second approval was already materialized. A
        redelivery is refused rather than producing a second entry.
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

    ``approval_window_seconds`` bounds how long after the rejection a
    second approval still counts. It is deliberately not optional: a
    consent with no deadline is standing authority, which this pipeline
    never grants.
    """

    scope_kind: ScopeKind
    scope_ref: str
    category: MemoryCategory
    source_ref: str
    ttl_seconds: int | None = None
    approval_window_seconds: int = DEFAULT_SECOND_APPROVAL_WINDOW_SECONDS
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.approval_window_seconds < 1:
            raise ValueError("approval_window_seconds MUST be >= 1")


class HilRejectMaterializer:
    """Turn a HIL reject reason into a persisted :class:`OperatorMemoryEntry`.

    Dependency-injected so tests can supply a
    :class:`~fdai.core.operator_memory.store.InMemoryOperatorMemoryStore`
    and a deterministic ``entry_id_fn`` / ``now_fn`` clock. Leaving
    ``entry_id_fn`` unset derives the entry id from the approval
    identity, which is what makes a redelivered second approval collide
    with its own prior entry instead of duplicating it. The
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
        self._entry_id_fn: Final[Callable[[], UUID] | None] = entry_id_fn
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
        missing / same-principal approvers, an unprovable or expired
        approval window, or a redelivery of an already-materialized
        approval) and propagates :class:`OperatorMemoryPolicyError`
        unchanged when the store's deeper policy check refuses the write.

        The entry id is derived from the approval identity and the second
        approver, so a redelivered approval collides with its own prior
        entry instead of planting a second copy of the same guidance.

        ``approval_expired`` is terminal, not transient. The window is
        checked before the store is touched, so an approval that arrives
        past its window is refused whether or not the same approval was
        already materialized inside the window. A caller MUST NOT retry it;
        the earlier entry, if any, is already durable and unchanged.
        """

        second_approver = second_approver.strip()
        self._reject_pipeline_violations(hil_response=hil_response, second_approver=second_approver)
        self._reject_stale_approval(hil_response=hil_response, material=material)
        # Types narrow after validation: ``approver_id`` and ``reason``
        # are guaranteed non-empty by _reject_pipeline_violations above.
        assert hil_response.approver_id is not None  # noqa: S101 - narrows for mypy
        assert hil_response.reason is not None  # noqa: S101 - narrows for mypy
        entry = OperatorMemoryEntry(
            id=self._entry_id(hil_response=hil_response, second_approver=second_approver),
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
        try:
            return await self._store.append(entry)
        except OperatorMemoryPolicyError as exc:
            if exc.code != "duplicate_id":
                raise
            raise HilMaterializationError(
                "already_materialized",
                f"second approval {entry.id} was already materialized; "
                "a redelivery never creates a second entry",
            ) from exc

    def _entry_id(self, *, hil_response: HilResponse, second_approver: str) -> UUID:
        if self._entry_id_fn is not None:
            return self._entry_id_fn()
        identity = f"{hil_response.approval_id}|{_normalize(second_approver)}"
        return uuid5(_ENTRY_NAMESPACE, identity)

    def _reject_stale_approval(
        self,
        *,
        hil_response: HilResponse,
        material: HilRejectMaterial,
    ) -> None:
        received_at = hil_response.received_at
        if received_at is None:
            raise HilMaterializationError(
                "missing_response_time",
                "HIL response has no received_at, so the second approval "
                "cannot prove it happened inside its window",
            )
        elapsed = (self._now() - received_at).total_seconds()
        if elapsed > material.approval_window_seconds:
            raise HilMaterializationError(
                "approval_expired",
                f"second approval arrived {elapsed:.0f}s after the rejection, "
                f"past the {material.approval_window_seconds}s window",
            )

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
        if first_approver.strip().lower() == _normalize(second_approver):
            raise HilMaterializationError(
                "same_principal",
                "first and second approvers MUST be distinct - "
                "the rejecter cannot self-approve the memory entry",
            )


def _normalize(principal: str) -> str:
    """Canonical principal form shared by the entry id and the identity checks."""
    return principal.strip().lower()


__all__ = [
    "DEFAULT_SECOND_APPROVAL_WINDOW_SECONDS",
    "HilMaterializationError",
    "HilRejectMaterial",
    "HilRejectMaterializer",
]
