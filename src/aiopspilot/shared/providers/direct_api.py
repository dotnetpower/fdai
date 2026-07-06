"""Direct-API executor - CSP-neutral contract for the substrate-call path.

The `direct_api` execution path in
`docs/roadmap/execution-model.md § 5.2 Direct API` calls the substrate
API (Azure ARM, `kubectl`, Redis, ...) rather than opening a
remediation PR. `core/` only knows this Protocol; concrete adapters
live under `delivery/azure/direct_api.py` (fork territory beyond the
skeleton).

Why a dedicated contract (vs re-using the PR publisher)
-------------------------------------------------------

- The direct-API path executes a **mutation on the substrate** and its
  rollback is contract-driven (`scripted` / `pitr` / `snapshot_restore`),
  not "revert the merge commit". A PR publisher cannot represent that
  shape.
- Idempotency is enforced by the adapter's remote (an ARM 409, an
  `If-None-Match`, or a scripted precondition check) plus a per-key
  ledger the executor consults on retry.
- The executor still writes exactly one audit entry per attempt,
  including the fallback path when a `direct_api` dispatch degrades to
  `pr_manual` mid-flight - see the fallback-idempotency invariant in
  `docs/roadmap/execution-model.md § 5.4`.

Shadow-mode invariant
---------------------

The upstream Day-1 wiring binds :class:`RecordingDirectApiExecutor`
(under ``shared/providers/testing/``) so no substrate is mutated. A
fork replaces the binding with a live adapter and gates it behind the
same ActionType `promotion_gate` the PR path uses. An executor that
receives an intent whose ``mode`` is
:attr:`~aiopspilot.shared.contracts.models.Mode.ENFORCE` and whose
ActionType has not yet been promoted MUST fail-closed with
:class:`DirectApiPromotionError`, exactly mirroring the PR publisher's
enforce-label check.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from aiopspilot.shared.contracts.models import Mode


class DirectApiOutcome(StrEnum):
    """Terminal state of one :meth:`DirectApiExecutor.execute` call.

    Every value writes exactly one audit entry. The executor never
    silently retries; a retry is a fresh call with the same
    ``idempotency_key`` and MUST land on :attr:`ALREADY_APPLIED` if
    the first call succeeded.
    """

    SUCCEEDED = "succeeded"
    """The substrate call completed and post-conditions verified."""

    ALREADY_APPLIED = "already_applied"
    """Idempotency ledger hit - a prior call for the same key
    succeeded. The receipt echoes the earlier receipt."""

    PRECONDITION_FAILED = "precondition_failed"
    """An ActionType ``precondition`` did not hold at dispatch time
    (e.g. the resource is no longer in the expected state). No
    mutation attempted."""

    STOPPED = "stopped"
    """A ``stop_condition`` fired mid-flight (blast radius exceeded,
    error rate spiked). The adapter rolled back whatever partial
    mutation it made."""

    FAILED = "failed"
    """The substrate call raised or the response was non-2xx. The
    adapter attempted a rollback per the ActionType's
    ``rollback_contract`` and reports the result via
    ``rollback_succeeded``."""


class DirectApiError(RuntimeError):
    """Base class for direct-API failures the executor surfaces to audit.

    Subclasses carry a distinct ``kind`` so the audit log can classify
    without parsing the message string.
    """

    __slots__ = ("kind",)

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class DirectApiPromotionError(DirectApiError):
    """Raised when an enforce-mode intent references an ActionType
    whose ``promotion_gate`` has not been satisfied.

    This is the direct-API mirror of the PR-publisher's
    ``enforce-label`` check; both paths share the same shadow-first
    promotion contract.
    """

    def __init__(self, message: str) -> None:
        super().__init__(kind="promotion", message=message)


class DirectApiPreconditionError(DirectApiError):
    """Raised when a precondition declared on the ActionType does not
    hold at dispatch time. The adapter MUST NOT attempt the mutation."""

    def __init__(self, message: str) -> None:
        super().__init__(kind="precondition", message=message)


@dataclass(frozen=True, slots=True)
class DirectApiRequest:
    """One direct-API dispatch intent handed to the executor.

    Frozen so a caller cannot rewrite the intent between dispatch and
    audit. The rendered ``arguments`` block is what the adapter serialises
    onto the wire; ``core/`` never assembles a substrate-specific payload
    itself (that is adapter territory).
    """

    action_id: UUID
    """Correlates back to :class:`~aiopspilot.shared.contracts.models.Action`."""

    idempotency_key: str
    """Stable key from the source event; the adapter's ledger MUST
    consult this before touching the substrate. A retried request with
    the same key returns :attr:`DirectApiOutcome.ALREADY_APPLIED`."""

    action_type_name: str
    """Which ActionType is being dispatched (e.g. ``ops.restart-service``).
    The adapter uses it to pick the substrate-specific handler and to
    look up ``rollback_contract`` / ``stop_conditions`` values."""

    rule_ids: tuple[str, ...]
    """Citing rules; recorded in the audit entry so the mutation is
    grounded."""

    resource_ref: str
    """Opaque substrate identifier - an ARM id, a k8s object ref, ...
    Adapters interpret it; ``core/`` treats it as a correlation string."""

    arguments: Mapping[str, object] = field(default_factory=dict)
    """Rendered per-ActionType argument bundle. MUST match the
    ActionType's ``argument_schema``; the executor is responsible for
    validating it before this call."""

    labels: tuple[str, ...] = ("shadow",)
    """Every P1 dispatch carries at least ``shadow``. An ``enforce``
    dispatch MUST also carry the ``enforce`` label; the executor
    rejects otherwise."""

    mode: Mode = Mode.SHADOW
    """New actions ship shadow-first."""

    metadata: Mapping[str, str] = field(default_factory=dict)
    """Optional adapter-neutral k/v pairs (correlation id, tenant
    label, ...). Never carries secrets."""


@dataclass(frozen=True, slots=True)
class DirectApiReceipt:
    """Adapter-issued receipt for one dispatch attempt.

    Every field is either an outcome the audit log records or an
    opaque correlation string. ``receipt_ref`` is the adapter's
    remote-issued identifier (an ARM ``operationId``, a k8s
    ``resourceVersion``, ...); consumers treat it as a string only.
    """

    outcome: DirectApiOutcome
    receipt_ref: str
    already_existed: bool = False
    """``True`` iff the idempotency ledger already had a successful
    entry for this key. Mirrors
    :attr:`~aiopspilot.shared.providers.remediation_pr.PublishReceipt.already_existed`."""

    rollback_succeeded: bool | None = None
    """Only populated for :attr:`DirectApiOutcome.FAILED` and
    :attr:`DirectApiOutcome.STOPPED`. ``None`` on success. ``False``
    escalates to the operator - the audit entry MUST show a manual
    rollback is required."""

    detail: str | None = None
    """Human-readable one-line summary for the audit log (no secrets)."""


@runtime_checkable
class DirectApiExecutor(Protocol):
    """Dispatch a mutation via the substrate API.

    Implementations MUST:

    - be **idempotent by** ``request.idempotency_key`` - a second call
      with the same key returns
      :attr:`DirectApiOutcome.ALREADY_APPLIED` and MUST NOT re-execute;
    - reject an intent whose ``mode`` is enforce and whose ``labels``
      do not include ``enforce``, by raising
      :class:`DirectApiPromotionError`;
    - never bypass ``stop_conditions`` - on breach, roll back and
      return :attr:`DirectApiOutcome.STOPPED`;
    - never mutate the audit log; the caller writes exactly one audit
      entry per attempt.
    """

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt: ...


__all__ = [
    "DirectApiError",
    "DirectApiExecutor",
    "DirectApiOutcome",
    "DirectApiPreconditionError",
    "DirectApiPromotionError",
    "DirectApiReceipt",
    "DirectApiRequest",
]
