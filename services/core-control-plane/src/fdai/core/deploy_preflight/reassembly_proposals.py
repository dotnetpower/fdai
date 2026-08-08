"""Render a cleared reassembly into executor Action proposals (granularity A).

The bounded reassembly loop in :mod:`fdai.core.deploy_preflight.reassemble`
decides *what* to reassemble; this module turns a ``CLEARED``
:class:`~fdai.core.deploy_preflight.reassemble.ReassemblyOutcome` into **one
proposal per applied toggle** (the granularity-A decision) for the
``remediate.apply-preflight-toggle`` ActionType, and submits each through an
injected pipeline sink (Huginn -> Forseti -> Var -> Thor), shadow-first.

Design: ``docs/roadmap/deployment/preflight-active-reassembly.md``.

Boundaries
----------
Pure ``core/`` logic. This module constructs no cloud SDK, opens no PR, and
never executes - it builds proposal envelopes and hands them to the same typed
pipeline seam an operator command re-enters through
(:data:`fdai.agents.bragi.ProposalSink`). Forseti judges each proposal, Thor
executes shadow-first, and all seven safeguards come from the executor path,
not from here. An escalated outcome yields **no** proposals (the caller routes
it to ``hil``); a partial reassembly is never submitted.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fdai.core.deploy_preflight.reassemble import (
    AppliedToggle,
    ReassemblyOutcome,
    ReassemblyStatus,
)

ACTION_TYPE = "remediate.apply-preflight-toggle"

#: Same seam an operator command re-enters through (see ``bragi.ProposalSink``):
#: an async callable that accepts one proposal envelope and returns a status
#: dict (or ``None``). The pipeline (Huginn ingest -> ...) lives behind it.
ProposalSink = Callable[[Mapping[str, Any]], Awaitable[Mapping[str, Any] | None]]


def _idempotency_key(toggle: AppliedToggle) -> str:
    """Deterministic key so a redelivered reassembly does not double-submit.

    Keyed on scope + finding + the sorted override pairs, so the same toggle
    for the same finding in the same scope always maps to one key.
    """

    vars_part = ",".join(f"{k}={v}" for k, v in sorted(toggle.set_vars.items()))
    return f"{ACTION_TYPE}:{toggle.scope}:{toggle.finding_id}:{vars_part}"


@dataclass(frozen=True, slots=True)
class ToggleActionProposal:
    """One ``remediate.apply-preflight-toggle`` proposal, one applied toggle.

    ``to_dict`` renders the envelope the pipeline sink consumes; ``params`` is
    exactly the ActionType ``argument_schema`` (``scope``, ``finding_id``,
    ``toggle_module``, ``set_vars``, ``reason``) so downstream schema validation
    is the authority on eligibility.
    """

    idempotency_key: str
    initiator_principal: str
    scope: str
    finding_id: str
    toggle_module: str
    set_vars: Mapping[str, str]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "idempotency_key": self.idempotency_key,
            "correlation_id": self.idempotency_key,
            "initiator_principal": self.initiator_principal,
            "operator_initiated": False,
            "action_type": ACTION_TYPE,
            "resource_id": self.scope,
            "event_type": "rule_violation",
            "params": {
                "scope": self.scope,
                "finding_id": self.finding_id,
                "toggle_module": self.toggle_module,
                "set_vars": dict(self.set_vars),
                "reason": self.reason,
            },
        }


def build_toggle_proposals(
    outcome: ReassemblyOutcome,
    *,
    initiator_principal: str,
    reason: str | None = None,
) -> tuple[ToggleActionProposal, ...]:
    """Return one proposal per applied toggle for a ``CLEARED`` outcome.

    An escalated (or empty) outcome yields an empty tuple - the caller routes
    those to ``hil`` and submits nothing. ``reason`` defaults to a grounded,
    audit-safe sentence per toggle when not supplied.
    """

    if outcome.status is not ReassemblyStatus.CLEARED:
        return ()

    proposals: list[ToggleActionProposal] = []
    for toggle in outcome.applied_toggles:
        # module is guaranteed non-empty by the loop's autofix eligibility gate.
        module = toggle.module or ""
        toggle_reason = reason or (
            f"preflight active reassembly cleared blocker {toggle.finding_id} via {module}"
        )
        proposals.append(
            ToggleActionProposal(
                idempotency_key=_idempotency_key(toggle),
                initiator_principal=initiator_principal,
                scope=toggle.scope,
                finding_id=toggle.finding_id,
                toggle_module=module,
                set_vars=dict(toggle.set_vars),
                reason=toggle_reason,
            )
        )
    return tuple(proposals)


async def submit_toggle_proposals(
    outcome: ReassemblyOutcome,
    *,
    sink: ProposalSink,
    initiator_principal: str,
    reason: str | None = None,
) -> tuple[Mapping[str, Any] | None, ...]:
    """Build and submit one proposal per applied toggle through ``sink``.

    Submits sequentially so ordering is deterministic and one sink failure
    surfaces before the next submit. Returns the sink's status envelope per
    proposal, in the same order. A non-``CLEARED`` outcome submits nothing and
    returns an empty tuple. Propagates any exception the sink raises
    (fail-closed: the caller degrades to ``hil``).
    """

    proposals = build_toggle_proposals(
        outcome, initiator_principal=initiator_principal, reason=reason
    )
    results: list[Mapping[str, Any] | None] = []
    for proposal in proposals:
        results.append(await sink(proposal.to_dict()))
    return tuple(results)


__all__ = [
    "ACTION_TYPE",
    "ProposalSink",
    "ToggleActionProposal",
    "build_toggle_proposals",
    "submit_toggle_proposals",
]
