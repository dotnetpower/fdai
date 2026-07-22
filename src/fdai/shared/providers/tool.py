"""Tool executor - CSP-neutral contract for the tool-call execution path.

The `tool_call` execution path in
`docs/roadmap/decisioning/execution-model.md § 5.6 Tool call` invokes a **registered
function** (generate a PDF report, send a notification, open a ticket, ...)
rather than mutating a cloud substrate or opening a remediation PR. It is
the ontology-native counterpart to the way an LLM calls a tool: a
`tool.*` ActionType names one registered tool, the executor dispatches it
here, and the delivery adapter under `delivery/` runs the concrete
function. `core/` only knows this Protocol.

Why a dedicated contract (vs re-using DirectApiExecutor)
--------------------------------------------------------

- `direct_api` means "mutate the substrate" (Azure ARM, `kubectl`,
  Redis); its receipt is a substrate operation id and its rollback is a
  substrate contract (`pitr` / `snapshot_restore`). A tool call has no
  substrate resource - it produces an **artifact** (a document, a
  message, a ticket) or a side effect whose rollback is usually
  `state_forward_only` (delete the artifact) or `scripted`. Re-using the
  substrate contract would misrepresent both the target and the rollback
  shape.
- The tool registry is the natural attach point for an MCP adapter: an
  `McpToolExecutor` implementing this Protocol maps one MCP server tool
  onto a `tool.*` ActionType, so "the ontology action calls a function"
  and "an LLM calls an MCP tool" collapse to the same seam.

Shadow-mode invariant
---------------------

The upstream Day-1 wiring binds
:class:`~fdai.shared.providers.testing.tool.RecordingToolExecutor` so no
real function runs. A fork replaces the binding with a live adapter (a
native Python registry, an MCP client, an HTTP callout) and gates it
behind the same ActionType `promotion_gate` the PR path uses. An
executor that receives an intent whose ``mode`` is
:attr:`~fdai.shared.contracts.models.Mode.ENFORCE` and whose ActionType
has not yet been promoted MUST fail-closed with
:class:`ToolPromotionError`, mirroring the direct-API promotion check.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from fdai.shared.contracts.models import Mode


class ToolCallOutcome(StrEnum):
    """Terminal state of one :meth:`ToolExecutor.execute` call.

    Every value writes exactly one audit entry. The executor never
    silently retries; a retry is a fresh call with the same
    ``idempotency_key`` and MUST land on :attr:`ALREADY_APPLIED` if the
    first call succeeded.
    """

    SUCCEEDED = "succeeded"
    """The tool ran and post-conditions verified."""

    ALREADY_APPLIED = "already_applied"
    """Idempotency ledger hit - a prior call for the same key succeeded.
    The receipt echoes the earlier receipt (e.g. the same artifact ref)."""

    PRECONDITION_FAILED = "precondition_failed"
    """An ActionType ``precondition`` did not hold at dispatch time. The
    tool was not invoked."""

    STOPPED = "stopped"
    """A ``stop_condition`` fired mid-flight (blast radius exceeded, the
    tool timed out). The adapter rolled back whatever partial artifact it
    produced."""

    FAILED = "failed"
    """The tool raised or reported failure. The adapter attempted a
    rollback per the ActionType's ``rollback_contract`` and reports the
    result via ``rollback_succeeded``."""


class ToolError(RuntimeError):
    """Base class for tool-call failures the executor surfaces to audit.

    Subclasses carry a distinct ``kind`` so the audit log can classify
    without parsing the message string.
    """

    __slots__ = ("kind",)

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class ToolPromotionError(ToolError):
    """Raised when an enforce-mode intent references an ActionType whose
    ``promotion_gate`` has not been satisfied.

    The tool-call mirror of :class:`DirectApiPromotionError`; both paths
    share the same shadow-first promotion contract.
    """

    def __init__(self, message: str) -> None:
        super().__init__(kind="promotion", message=message)


class ToolPreconditionError(ToolError):
    """Raised when a precondition declared on the ActionType does not
    hold at dispatch time. The adapter MUST NOT invoke the tool."""

    def __init__(self, message: str) -> None:
        super().__init__(kind="precondition", message=message)


@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    """One tool-call dispatch intent handed to the executor.

    Frozen so a caller cannot rewrite the intent between dispatch and
    audit. The rendered ``arguments`` block is what the adapter passes to
    the concrete function; ``core/`` never assembles a tool-specific
    payload itself (that is adapter territory).
    """

    action_id: UUID
    """Correlates back to :class:`~fdai.shared.contracts.models.Action`."""

    idempotency_key: str
    """Stable key from the source event; the adapter's ledger MUST
    consult this before invoking the tool. A retried request with the
    same key returns :attr:`ToolCallOutcome.ALREADY_APPLIED`."""

    action_type_name: str
    """Which ActionType is being dispatched (e.g. ``tool.generate-pdf``).
    The adapter uses it to look up the registered tool handler and the
    ActionType's ``rollback_contract`` / ``stop_conditions`` values."""

    rule_ids: tuple[str, ...]
    """Citing rules (or the operator request id); recorded in the audit
    entry so the invocation is grounded."""

    tool_ref: str
    """Opaque target the tool acts on or produces - a document key, a
    channel id, a ticket queue. Adapters interpret it; ``core/`` treats
    it as a correlation string. Mirrors ``resource_ref`` on the
    direct-API path but names an artifact/target, not a substrate id."""

    arguments: Mapping[str, object] = field(default_factory=dict)
    """Rendered per-ActionType argument bundle. MUST match the
    ActionType's ``argument_schema``; the executor validates it before
    this call."""

    labels: tuple[str, ...] = ("shadow",)
    """Every P1 dispatch carries at least ``shadow``. An ``enforce``
    dispatch MUST also carry the ``enforce`` label; the executor rejects
    otherwise."""

    mode: Mode = Mode.SHADOW
    """New actions ship shadow-first."""

    metadata: Mapping[str, str] = field(default_factory=dict)
    """Optional adapter-neutral k/v pairs (correlation id, locale, ...).
    Never carries secrets."""


@dataclass(frozen=True, slots=True)
class ToolCallReceipt:
    """Adapter-issued receipt for one dispatch attempt.

    Every field is either an outcome the audit log records or an opaque
    correlation string. ``receipt_ref`` is the adapter's identifier for
    the produced artifact or side effect (a document URI, a message id, a
    ticket number); consumers treat it as a string only.
    """

    outcome: ToolCallOutcome
    receipt_ref: str
    already_existed: bool = False
    """``True`` iff the idempotency ledger already had a successful entry
    for this key."""

    rollback_succeeded: bool | None = None
    """Only populated for :attr:`ToolCallOutcome.FAILED` and
    :attr:`ToolCallOutcome.STOPPED`. ``None`` on success. ``False``
    escalates to the operator - the audit entry MUST show a manual
    rollback is required."""

    detail: str | None = None
    """Human-readable one-line summary for the audit log (no secrets)."""

    tool_id: str | None = None
    transport: str | None = None
    operation_class: str | None = None
    queue_duration_ms: int = 0
    execution_duration_ms: int = 0
    result_count: int = 0
    truncated: bool = False
    cache_status: str | None = None
    recorded_at: datetime | None = None
    trace_ref: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("tool_id", self.tool_id),
            ("transport", self.transport),
            ("operation_class", self.operation_class),
            ("cache_status", self.cache_status),
            ("trace_ref", self.trace_ref),
        ):
            if value is not None and (
                not value.strip() or len(value) > 256 or any(ord(char) < 32 for char in value)
            ):
                raise ValueError(f"{name} MUST be a bounded identifier")
        if (
            min(
                self.queue_duration_ms,
                self.execution_duration_ms,
                self.result_count,
            )
            < 0
        ):
            raise ValueError("tool receipt measurements MUST be non-negative")
        if self.recorded_at is not None and self.recorded_at.tzinfo is None:
            raise ValueError("tool receipt recorded_at MUST be timezone-aware")


@runtime_checkable
class ToolExecutor(Protocol):
    """Invoke a registered tool (function) for the ``tool_call`` path.

    Implementations MUST:

    - be **idempotent by** ``request.idempotency_key`` - a second call
      with the same key returns
      :attr:`ToolCallOutcome.ALREADY_APPLIED` and MUST NOT re-run the
      tool;
    - reject an intent whose ``mode`` is enforce and whose ``labels`` do
      not include ``enforce``, by raising :class:`ToolPromotionError`;
    - never bypass ``stop_conditions`` - on breach, roll back and return
      :attr:`ToolCallOutcome.STOPPED`;
    - never mutate the audit log; the caller writes exactly one audit
      entry per attempt.
    """

    async def execute(self, request: ToolCallRequest) -> ToolCallReceipt: ...


__all__ = [
    "ToolCallOutcome",
    "ToolCallReceipt",
    "ToolCallRequest",
    "ToolError",
    "ToolExecutor",
    "ToolPreconditionError",
    "ToolPromotionError",
]
