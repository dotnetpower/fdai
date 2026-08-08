"""Shadow-vs-authoritative divergence ledger.

The pantheon runs as a shadow of the P1 control loop: it judges the same
events but never mutates (``enforce=False``). "Shadow before enforce"
only becomes a *promotion* decision once we can measure how often the
shadow's judgment matches the authoritative P1 decision. This ledger is
that measurement seam.

It is deliberately core-agnostic: it stores plain decision strings keyed
by ``correlation_id`` and never imports ``core`` (so ``agents`` stays off
the P1 control-loop import graph, per ``check-core-imports``). The
composition root feeds it from both sides:

- the pantheon observer records the pantheon's would-be decision
  (Forseti verdict ``risk_verdict``);
- the P1 consumer records the authoritative :class:`ControlLoopResult`
  decision (normalized by the caller).

Matching is incremental and memory-bounded: when both sides have reported
a ``correlation_id`` the pair is finalized into counters and dropped from
the pending map, which is itself LRU-capped so a long-lived process can
never leak.
"""

from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Any

_PANTHEON = "pantheon"
_AUTHORITATIVE = "authoritative"


@dataclass
class ShadowDivergenceLedger:
    """Join pantheon (shadow) and P1 (authoritative) decisions by id.

    Both sides call ``record_*`` with a ``correlation_id`` and a
    normalized decision string (``auto`` / ``hil`` / ``deny`` /
    ``abstain`` / ``dedupe``). :meth:`report` returns the agreement rate
    and a divergence breakdown - the baseline a promotion gate reads.
    """

    max_pending: int = 100_000
    _pending: OrderedDict[str, tuple[str, str]] = field(default_factory=OrderedDict)
    matched: int = 0
    diverged: int = 0
    evicted: int = 0
    pantheon_total: int = 0
    authoritative_total: int = 0
    breakdown: Counter[str] = field(default_factory=Counter)

    def record_pantheon(self, correlation_id: str, decision: str) -> None:
        self.pantheon_total += 1
        self._record(_PANTHEON, correlation_id, decision)

    def record_authoritative(self, correlation_id: str, decision: str) -> None:
        self.authoritative_total += 1
        self._record(_AUTHORITATIVE, correlation_id, decision)

    def _record(self, side: str, correlation_id: str, decision: str) -> None:
        if not correlation_id:
            return
        other = self._pending.get(correlation_id)
        if other is None:
            self._pending[correlation_id] = (side, decision)
            self._pending.move_to_end(correlation_id)
            if len(self._pending) > self.max_pending:
                self._pending.popitem(last=False)
                self.evicted += 1
            return
        other_side, other_decision = other
        if other_side == side:
            # Same side reported twice (re-delivery); keep the latest and
            # stay pending for the opposite side.
            self._pending[correlation_id] = (side, decision)
            return
        del self._pending[correlation_id]
        pantheon = decision if side == _PANTHEON else other_decision
        authoritative = decision if side == _AUTHORITATIVE else other_decision
        if pantheon == authoritative:
            self.matched += 1
        else:
            self.diverged += 1
            # authoritative -> pantheon, so the pair reads "what P1 did ->
            # what the shadow would have done".
            self.breakdown[f"{authoritative}->{pantheon}"] += 1

    def report(self) -> dict[str, Any]:
        resolved = self.matched + self.diverged
        return {
            "matched": self.matched,
            "diverged": self.diverged,
            "agreement_rate": (self.matched / resolved) if resolved else None,
            "pending": len(self._pending),
            "evicted": self.evicted,
            "pantheon_total": self.pantheon_total,
            "authoritative_total": self.authoritative_total,
            "breakdown": dict(self.breakdown),
        }


__all__ = ["ShadowDivergenceLedger"]
