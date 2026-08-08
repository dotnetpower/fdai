"""HIL approval channel Protocol - Adaptive Card dispatch + decision poll.

Realizes the wire-level contract every ChatOps adapter under
``delivery/chatops/`` implements when the risk-gate returns
:class:`~fdai.core.risk_gate.gate.RiskDecisionOutcome.HIL`. The
scope is deliberately narrow - Category **A1** (approval) traffic
only, per ``docs/roadmap/interfaces/channels-and-notifications.md § 3``.
A2/A3/A4 (alerts, chat commands, digests) get their own contracts in
later phases and MUST NOT reuse this Protocol.

Design boundaries
-----------------

- ``core/`` MAY reference this Protocol (it lives under
  ``fdai.shared.providers``) but MUST NOT import a concrete
  adapter. The Teams / Slack / etc. bindings happen at the composition
  root; the fake under
  :mod:`fdai.shared.providers.testing.hil_channel` never leaks
  through ``core/``.
- Every operation is ``async`` because a real adapter makes an HTTP
  round trip (Teams Incoming Webhook or Bot Framework REST).
- The Protocol is state-free: the caller owns a
  :class:`HilApprovalReceipt` and hands it back on :meth:`HilChannel.poll`.

Wire model (P1)
---------------

P1 uses a **polling** callback model - the adapter's :meth:`send`
delivers the Adaptive Card and returns a receipt; the caller polls
:meth:`poll` until a decision surfaces or the request TTL elapses. A
webhook trigger (Azure Functions HTTP callback) is deferred to a later
phase; the Protocol accommodates either by treating ``poll`` as the
sole way ``core/`` observes a decision. Adapters without a native
back-channel (a pure Incoming Webhook) surface :data:`HilDecision.PENDING`
on every poll - the caller then falls back to its persisted HIL queue.

Security invariants
-------------------

Per ``docs/roadmap/interfaces/channels-and-notifications.md § 3
(Category boundaries MUST)``:

- The Adaptive Card body carries an **opaque** ``approval_id`` only;
  the decision is re-verified by ``fdai-api`` against the
  ``action_hash`` before it is honored. Adapters MUST NOT trust the
  raw click payload as an authorization.
- Messages are **pre-redacted** by the caller. Adapters SHOULD scan
  for known secret patterns before dispatch as defense in depth, but
  the Protocol assumes the caller has already sanitized the fields.
- No secret material (tokens, connection strings, tenant / subscription
  ids) may appear in :class:`HilApprovalRequest` fields; only opaque
  identifiers and the pre-approved summary blast-radius bucket.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class HilDecision(StrEnum):
    """Terminal-or-intermediate outcome the caller observes on :meth:`HilChannel.poll`.

    Rendered as the audit ``decision`` field when the caller writes the
    HIL entry (see ``docs/roadmap/architecture/security-and-identity.md
    § HIL Approval Integrity``).
    """

    APPROVE = "approve"
    """The approver clicked Approve. The caller MUST re-verify the
    approver's identity + action hash upstream before acting."""

    REJECT = "reject"
    """The approver clicked Reject. Terminal - the executor takes no
    action and writes the reject reason."""

    TIMEOUT = "timeout"
    """The request TTL elapsed without a decision. Fail-closed no-op
    per the routing policy in
    ``docs/roadmap/interfaces/channels-and-notifications.md § 6
    (TTL fail-closed)``."""

    PENDING = "pending"
    """The adapter has no decision yet - keep polling until TTL. Never
    written to the audit log; a caller loop distinguishes ``PENDING``
    from the three terminal values."""


@dataclass(frozen=True, slots=True)
class HilApprovalRequest:
    """Envelope handed to :meth:`HilChannel.send`.

    Frozen so the adapter cannot rewrite the payload between dispatch
    and audit. Every field is either an opaque identifier or a
    pre-redacted human-readable summary - never a raw event payload,
    secret, or vendor-specific reference (per
    ``docs/roadmap/interfaces/channels-and-notifications.md § 1
    (Design Principles)``).
    """

    approval_id: str
    """Opaque, single-use id. The decision endpoint (``fdai-api``)
    is what actually authorizes - a leaked card cannot forge an
    approval because the ``approval_id`` alone is insufficient."""

    correlation_id: str
    """Cross-service correlation id - matches the audit entry."""

    action_id: str
    """Correlates back to the pending
    :class:`~fdai.shared.contracts.models.Action`."""

    action_type: str
    """ActionType name (e.g. ``remediate.tag-missing-owner``); shown
    verbatim on the card so the approver sees exactly what will run."""

    rule_ids: tuple[str, ...]
    """Citing rules that authored the action. Empty tuple is legal -
    the card renders "no rule citation" for policy-only actions."""

    target_resource_ref: str
    """Human-readable resource reference (ARM id or a short display
    label). NEVER a tenant / subscription id in isolation - the caller
    strips those before passing the request in."""

    blast_radius_summary: str
    """Short, human-readable blast-radius summary (e.g.
    ``\"1 resource in rg-example\"``). The card MUST NOT re-compute this
    - the caller has already normalized it."""

    reasons: tuple[str, ...] = ()
    """Reasons the risk gate escalated (mirrors
    :attr:`~fdai.core.risk_gate.gate.RiskDecision.reasons`). Empty
    tuple is legal - the card falls back to a generic message."""

    ttl_seconds: int = 1800
    """Approval TTL. Matches the routing config in
    ``docs/roadmap/interfaces/channels-and-notifications.md § 6``
    (30 minutes)."""

    action_hash: str = ""
    """Opaque hash binding the approval to the exact pending action.
    ``fdai-api`` re-computes this before honoring an
    :attr:`HilDecision.APPROVE`. Empty string is legal in dev / smoke
    fixtures; production wiring populates it."""

    metadata: Mapping[str, str] = field(default_factory=dict)
    """Optional adapter-neutral k/v pairs (severity, category tag, ...).
    Never carries secrets."""


@dataclass(frozen=True, slots=True)
class HilApprovalReceipt:
    """Adapter-issued receipt for one :meth:`HilChannel.send` call.

    ``channel_ref`` is opaque to ``core/`` - a Teams adapter uses a
    conversation / message id (``"teams:conv-42/msg-7"``), a fake uses
    a monotonic counter. Consumers MUST treat it as a correlation
    string only.
    """

    approval_id: str
    """Round-trips the request's ``approval_id`` so a poll can look up
    the pending record without re-consulting the channel."""

    channel_ref: str
    sent_at: datetime


@dataclass(frozen=True, slots=True)
class HilResponse:
    """Terminal outcome returned by :meth:`HilChannel.poll`.

    The adapter surfaces whatever the user clicked; ``fdai-api``
    is the sole authority that re-verifies identity + action hash. This
    struct is intentionally free of privileged decision fields - the
    executor MUST NOT act on it directly, only propagate it upstream
    per ``docs/roadmap/interfaces/channels-and-notifications.md § 5
    (Channel Interface - MUST)``.
    """

    approval_id: str
    decision: HilDecision
    approver_id: str | None = None
    """Adapter-visible principal id (Entra OID for Teams SSO, Slack
    userId, ...). Not a substitute for identity re-verification - the
    upstream API MUST re-authenticate. ``None`` is legal when the
    adapter cannot expose an id (e.g. Incoming Webhook has no
    per-user identity)."""

    received_at: datetime | None = None
    """When the adapter observed the decision (not when the user
    clicked - a delayed poll may report a stale timestamp)."""

    reason: str | None = None
    """Optional free-form reason the approver typed in the card's
    input field. Pre-redacted by the adapter (secret-scan regex set)
    before surfacing."""


class HilChannelError(RuntimeError):
    """Raised by a :class:`HilChannel` on any unrecoverable failure.

    The message is safe to log - implementations MUST NOT embed raw
    tokens, tenant ids, or vendor error bodies larger than a short
    truncated snippet.
    """

    def __init__(
        self,
        message: str,
        *,
        approval_id: str,
        status_code: int | None = None,
    ) -> None:
        code = f" (HTTP {status_code})" if status_code is not None else ""
        super().__init__(f"{message}{code} [approval_id={approval_id}]")
        self.message = message
        self.approval_id = approval_id
        self.status_code = status_code


@runtime_checkable
class HilChannel(Protocol):
    """Dispatch an approval card and observe the returned decision.

    The two operations map onto both P1 target substrates:

    +---------------+-------------------------------------------+---------------------------------+
    | Op            | Teams (Incoming Webhook / Bot Framework)  | InMemory fake                   |
    +===============+===========================================+=================================+
    | ``send``      | POST Adaptive Card to the channel URL     | append to an in-process queue   |
    | ``poll``      | (P1) always :data:`HilDecision.PENDING`   | return the pre-programmed value |
    +---------------+-------------------------------------------+---------------------------------+

    :meth:`poll` MUST be idempotent - repeated polling on the same
    ``receipt`` returns the same terminal value (or :data:`HilDecision.PENDING`
    until a decision surfaces). A caller loop is responsible for the
    poll cadence and the TTL stop-condition; the Protocol stays a
    one-shot query.
    """

    async def send(self, request: HilApprovalRequest) -> HilApprovalReceipt:
        """Deliver the Adaptive Card and return a receipt.

        Raises :class:`HilChannelError` on immediate failure (invalid
        webhook URL, missing auth, 4xx/5xx) so the caller can escalate
        to the persisted HIL queue without touching the channel state.
        """
        ...

    async def poll(self, receipt: HilApprovalReceipt) -> HilResponse:
        """Return the current decision for the request.

        Adapters without a native back-channel MUST return a response
        with :data:`HilDecision.PENDING` - never a synthetic APPROVE /
        REJECT / TIMEOUT. The caller owns the TTL clock.
        """
        ...


__all__ = [
    "HilApprovalReceipt",
    "HilApprovalRequest",
    "HilChannel",
    "HilChannelError",
    "HilDecision",
    "HilResponse",
]
