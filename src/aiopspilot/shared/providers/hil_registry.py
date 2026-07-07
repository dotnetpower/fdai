"""HIL approval registry - Approver-scoped queue for `approve_hil` / `list_hil`.

The read-API's :class:`~aiopspilot.delivery.read_api.read_model.HilQueueItem`
is the **Reader** projection (dashboard tile: count + short reason). This
module ships the **Approver** projection: the full item detail
(including ``submitter_oid``) that the console's `approve_hil` /
`list_hil` tools consume, plus a write-side to record the operator's
decision.

Why a distinct projection

- **Distinct visibility**: exposing the submitter identity or the
  proposed action's full argument bundle to Reader would leak sensitive
  intent (see the Week-1 write/approve/runbook section of
  ``docs/roadmap/operator-console.md``).
- **Distinct write surface**: recording a decision needs an authoritative
  ledger the executor observes; the read-API is deliberately read-only
  (`docs/roadmap/deploy-and-onboard.md`).

Wave scope

- **This module (Wave W1.1 partial)** - Protocol + record types.
- **In-memory fake** at
  :mod:`aiopspilot.shared.providers.testing.hil_registry`.
- **Real backend** (Postgres-backed HIL queue on the state store) is
  fork territory.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class HilApprovalDecision(StrEnum):
    """Terminal decision an approver records.

    Matches the terminal values of
    :class:`~aiopspilot.shared.providers.hil_channel.HilDecision`
    (``approve`` / ``reject``); intentionally excludes
    :attr:`~aiopspilot.shared.providers.hil_channel.HilDecision.TIMEOUT`
    (a system-generated terminal, not an operator decision) and
    :attr:`~aiopspilot.shared.providers.hil_channel.HilDecision.PENDING`
    (not a terminal).
    """

    APPROVE = "approve"
    REJECT = "reject"


class MutationTarget(StrEnum):
    """Which executor an approved HIL item would dispatch to.

    Surfaced on :attr:`HilPendingItem.mutation_target` so an Approver
    knows whether the approval will result in a merged remediation PR
    (``PR_NATIVE``) or a direct substrate mutation (``DIRECT_API``).
    The value mirrors
    :class:`~aiopspilot.shared.contracts.models.ExecutionPath` and is
    populated at HIL enqueue time from
    :attr:`~aiopspilot.shared.contracts.models.OntologyActionType.execution_path`.

    Left absent (``None``) for pending items authored before the field
    landed, so a Postgres backend that predates Wave W2.3f can round-trip
    the row unchanged.
    """

    PR_NATIVE = "pr_native"
    DIRECT_API = "direct_api"


@dataclass(frozen=True, slots=True)
class HilPendingItem:
    """Full-detail projection of one pending HIL approval.

    Kept frozen so it survives round-trips through the audit log
    without accidental mutation. ``submitter_oid`` is the Entra OID of
    the principal that authored the pending action; it is the sole
    identity the ``no_self_approval`` invariant compares against
    (never ``upn`` or ``email`` - those can be renamed / aliased,
    see the API-token-validation section of
    ``docs/roadmap/user-rbac-and-identity.md``).
    """

    idempotency_key: str
    approval_id: str
    """Opaque, single-use id the decision endpoint validates. Matches
    the ``approval_id`` on :class:`HilApprovalRequest` when the item
    was raised via the ChatOps channel."""

    event_id: str
    action_id: str
    action_kind: str
    """ActionType name (e.g. ``remediate.disable-public-access``)."""

    target_resource_ref: str
    reason: str
    """Short, pre-redacted human-readable summary. NEVER a raw event
    payload or secret."""

    submitter_oid: str
    """Entra OID of the principal that authored the pending action.
    The ``no_self_approval`` invariant refuses when
    ``approver.oid == submitter_oid``."""

    citing_rule_ids: tuple[str, ...] = ()
    """Rules that authored the pending action; empty tuple is legal
    for policy-only actions."""

    requested_at: datetime | None = None
    correlation_id: str | None = None
    action_hash: str = ""
    """Optional opaque hash binding the approval to the exact pending
    action. When present, an ``approve_hil`` tool MAY re-verify it
    upstream before honoring the decision."""

    mutation_target: MutationTarget | None = None
    """Executor sibling the approval will dispatch to (Wave W2.3f).

    Populated at enqueue time from
    :attr:`~aiopspilot.shared.contracts.models.OntologyActionType.execution_path`
    so an Approver knows whether the change lands as a PR (``PR_NATIVE``)
    or a substrate mutation (``DIRECT_API``) before deciding. Rows
    predating the field carry ``None``; a fork's Postgres backend MUST
    tolerate the missing column so an in-place migration is not
    required to consume older rows.
    """

    metadata: Mapping[str, str] = field(default_factory=dict)
    """Optional adapter-neutral k/v pairs. Never carries secrets."""


@dataclass(frozen=True, slots=True)
class HilDecisionReceipt:
    """Registry-issued receipt for one recorded decision.

    ``receipt_ref`` is opaque; consumers treat it as a correlation
    string only. ``already_recorded`` is ``True`` when the registry
    detected a prior decision for the same ``idempotency_key`` and
    returned it unchanged - idempotency mirrors
    :class:`~aiopspilot.shared.providers.remediation_pr.PublishReceipt`.
    """

    approval_id: str
    idempotency_key: str
    decision: HilApprovalDecision
    approver_oid: str
    decided_at: datetime
    receipt_ref: str = ""
    already_recorded: bool = False
    justification: str = ""


class HilRegistryError(RuntimeError):
    """Base class for registry failures.

    Subclasses carry a distinct ``kind`` so audit records classify
    without parsing the message.
    """

    __slots__ = ("kind",)

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class HilItemNotFoundError(HilRegistryError):
    """Raised when ``record_decision`` targets an unknown key."""

    def __init__(self, idempotency_key: str) -> None:
        super().__init__(
            kind="not_found",
            message=f"no pending HIL item for idempotency_key={idempotency_key!r}",
        )


class HilItemAlreadyResolvedError(HilRegistryError):
    """Raised when ``record_decision`` targets a key that has already
    reached a terminal state (approve / reject / timeout).

    The registry returns the prior receipt as
    :class:`HilDecisionReceipt` with ``already_recorded=True`` for
    same-decision idempotent replays; this error covers the
    conflicting-decision case (approve after reject, etc.).
    """

    def __init__(self, idempotency_key: str, prior_decision: str) -> None:
        super().__init__(
            kind="already_resolved",
            message=(
                f"HIL item {idempotency_key!r} is already resolved "
                f"(prior_decision={prior_decision!r}); cannot overwrite"
            ),
        )


@runtime_checkable
class HilApprovalRegistry(Protocol):
    """Authoritative store for pending HIL items + recorded decisions.

    Implementations MUST:

    - be **idempotent by** ``idempotency_key`` - a second
      ``record_decision`` with the same ``(idempotency_key, decision)``
      returns the prior receipt with ``already_recorded=True`` and
      MUST NOT double-record;
    - reject a **conflicting** re-decision (different ``decision`` on
      the same key) with :class:`HilItemAlreadyResolvedError`; the operator
      MUST cancel + reraise upstream if they need to revise;
    - never mutate the audit log directly - the console tool that
      calls ``record_decision`` writes exactly one
      ``console.approve_hil`` audit entry, and the registry's write is
      what the executor observes.
    """

    async def list_pending(self, *, limit: int = 50) -> Sequence[HilPendingItem]: ...

    async def get_pending(self, idempotency_key: str) -> HilPendingItem | None: ...

    async def record_decision(
        self,
        *,
        idempotency_key: str,
        decision: HilApprovalDecision,
        approver_oid: str,
        justification: str = "",
        decided_at: datetime | None = None,
    ) -> HilDecisionReceipt: ...


__all__ = [
    "HilApprovalDecision",
    "HilApprovalRegistry",
    "HilDecisionReceipt",
    "HilItemAlreadyResolvedError",
    "HilItemNotFoundError",
    "HilPendingItem",
    "HilRegistryError",
    "MutationTarget",
]
