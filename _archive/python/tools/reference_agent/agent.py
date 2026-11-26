"""Pinned reference agent for Phase 0 baseline measurement.

The reference agent is the **fixed comparison system** measured in Phase 0:
one model, no tiering, no quality gate. Every autonomy claim later stated
by FDAI is measured against this agent on the frozen scenario set.

Real deployments will swap this stub for a hosted LLM. Today the stub is
intentionally simple:

- **Single decision rule**: always route to HIL. That mirrors a
  conservative "single-model, no tiering" baseline that a human operator
  would sign off on every action.
- **Deterministic**: no randomness, no wall-clock - two runs on the same
  scenario version yield byte-identical results.
- **Cost-free**: no LLM call, no network. Tests can invoke it in-process.

This is the shape the baseline runner consumes. When the real reference
agent lands, it MUST honour the same :class:`AgentDecision` contract so
the runner (and its report artifact) do not change.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

Tier = Literal["t0", "t1", "t2"]
Decision = Literal["auto", "hil", "abstain", "deny"]


@dataclass(frozen=True, slots=True)
class AgentDecision:
    """The reference agent's verdict for one event."""

    tier: Tier
    decision: Decision
    citing_rule_ids: tuple[str, ...]

    @property
    def touched_by_human(self) -> bool:
        """Whether this decision counts as a human touchpoint (metric 4)."""
        return self.decision == "hil"


class ReferenceAgent:
    """Fixed, deterministic single-model / no-tiering baseline."""

    VERSION = "reference-agent-stub@1.0.0"

    def decide(self, event: Mapping[str, Any]) -> AgentDecision:  # noqa: ARG002
        """Return the same conservative verdict for every event.

        Ignoring the event body is intentional - the reference agent is a
        *fixed* baseline. When a real LLM replaces this stub, it MAY use
        the event body, but its output remains an :class:`AgentDecision`.
        """
        return AgentDecision(tier="t2", decision="hil", citing_rule_ids=())


__all__ = ["AgentDecision", "Decision", "ReferenceAgent", "Tier"]
