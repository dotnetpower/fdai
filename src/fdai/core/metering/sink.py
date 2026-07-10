"""Metering sink / reader seams and the upstream in-memory default.

Recording an LLM invocation is a DI seam so a fork swaps the backend
(Postgres ``agent_transcript`` rows, an OTel metric, a billing export)
without editing ``core/``. Two Protocols split the roles per the
single-responsibility rule:

- :class:`MeteringSink` - **write** one invocation (called by the LLM
  adapters on the hot path; async because a real backend is I/O-bound).
- :class:`MeteringReader` - **read** the recorded invocations back
  (called by the read-API cost panel to build the summaries).

The upstream default :class:`InMemoryMeteringSink` implements both over
a process-lifetime list. It is deliberately non-durable (like the dev
read-model harness): it makes per-conversation / daily / monthly cost
work out of the box, and a production composition root injects a durable
implementation of the same Protocols. Recording never raises on a
backend hiccup path here because there is no backend - a durable
implementation MUST fail closed to the audit log instead of dropping a
record silently.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from fdai.core.metering.records import LlmInvocation

# Default ring-buffer cap for the in-memory sink. The upstream default is
# a single-process dev harness; without a cap a long-running process
# would grow the record list without bound. A durable fork sink ignores
# this and persists everything.
_DEFAULT_MAX_RECORDS: int = 50_000


@runtime_checkable
class MeteringSink(Protocol):
    """Append one measured LLM invocation to the metering store."""

    async def record(self, invocation: LlmInvocation) -> None:
        """Persist ``invocation``. MUST be idempotent-safe for retries."""
        ...


@runtime_checkable
class MeteringReader(Protocol):
    """Read recorded invocations back for cost aggregation."""

    async def invocations(self) -> tuple[LlmInvocation, ...]:
        """Return every recorded invocation (unordered by contract)."""
        ...


class InMemoryMeteringSink:
    """Upstream default: keep recorded invocations in a bounded ring buffer.

    Implements both :class:`MeteringSink` and :class:`MeteringReader`, so
    the composition root wires one instance to the LLM adapters (write)
    and the read-API cost panel (read).

    ``max_records`` caps retention (oldest records are evicted first) so a
    long-running single process cannot grow memory without bound; pass
    ``None`` for an explicitly unbounded buffer (tests / short runs). A
    production fork injects a durable sink instead of relying on this.
    """

    def __init__(
        self,
        initial: Iterable[LlmInvocation] = (),
        *,
        max_records: int | None = _DEFAULT_MAX_RECORDS,
    ) -> None:
        if max_records is not None and max_records < 1:
            raise ValueError("max_records MUST be >= 1 or None")
        self._records: deque[LlmInvocation] = deque(initial, maxlen=max_records)

    async def record(self, invocation: LlmInvocation) -> None:
        self._records.append(invocation)

    async def invocations(self) -> tuple[LlmInvocation, ...]:
        return tuple(self._records)

    def __len__(self) -> int:
        return len(self._records)


__all__ = ["InMemoryMeteringSink", "MeteringReader", "MeteringSink"]
