"""Escalation routing + workflow-change stakeholder computation.

Wires the handover map into notifications (decision B): for an agent event that
needs a human, build the ordered recipient chain ``accountable -> informed ->
maintainer``; for a workflow-change request, compute who to notify. This module
is pure (no network); group expansion and channel lookup take injected inputs so
the control loop never blocks on Graph.

Design authority:
[`agent-stewardship-and-handover.md § 6 / § 8`]
(../../../../docs/roadmap/interfaces/agent-stewardship-and-handover.md#6-runtime-effect-notification-and-escalation-decision-b).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from fdai.core.stewardship.directory import GroupMembershipProvider
from fdai.core.stewardship.model import StewardKind, StewardshipMap
from fdai.core.stewardship.names import AGENT_NAME_SET


class EscalationTier(StrEnum):
    """Which hop of the escalation chain a recipient sits on."""

    ACCOUNTABLE = "accountable"
    INFORMED = "informed"
    MAINTAINER = "maintainer"


@dataclass(frozen=True, slots=True)
class EscalationRecipient:
    """One notification target: an object id, its kind, and its tier."""

    kind: StewardKind
    id: str
    tier: EscalationTier


@dataclass(frozen=True, slots=True)
class EscalationPlan:
    """Ordered escalation chain for one agent."""

    agent_name: str
    recipients: tuple[EscalationRecipient, ...]
    hop_timeout_seconds: int

    def tier(self, tier: EscalationTier) -> tuple[EscalationRecipient, ...]:
        """Recipients on a specific tier, in order."""
        return tuple(r for r in self.recipients if r.tier is tier)


def build_escalation_plan(mp: StewardshipMap, agent_name: str) -> EscalationPlan:
    """Build the ``accountable -> informed -> maintainer`` chain for ``agent_name``.

    An autonomous agent (or one with no accountable steward) yields an empty
    accountable tier; the maintainer tier is always present so no event is ever
    left with no human.
    """
    agent = mp.agent(agent_name)
    recipients: list[EscalationRecipient] = []

    if not agent.is_autonomous:
        for s in agent.accountable:
            recipients.append(EscalationRecipient(s.kind, s.id, EscalationTier.ACCOUNTABLE))
    for s in agent.informed:
        recipients.append(EscalationRecipient(s.kind, s.id, EscalationTier.INFORMED))
    for oid in mp.maintainer_oids:
        recipients.append(EscalationRecipient(StewardKind.USER, oid, EscalationTier.MAINTAINER))

    return EscalationPlan(
        agent_name=agent_name,
        recipients=tuple(recipients),
        hop_timeout_seconds=mp.hop_timeout_seconds,
    )


def resolve_person_channel(mp: StewardshipMap, oid: str, fallback_channel_id: str) -> str:
    """Resolve the notification channel for a person.

    An explicit ``channels[oid]`` binding wins; otherwise the caller's
    fallback (the agent's category route in the notifications matrix) is used.
    Group subjects always use the fallback - a group has no personal channel.
    """
    return mp.channels.get(oid, fallback_channel_id)


async def expand_group_recipients(
    plan: EscalationPlan, provider: GroupMembershipProvider
) -> tuple[str, ...]:
    """Flatten a plan to distinct **user** object ids, expanding groups.

    Best-effort: a group the provider cannot resolve contributes its own id as
    one opaque unit (so it is still notified on the domain channel) rather than
    vanishing. Order is preserved; duplicates are dropped.
    """
    seen: dict[str, None] = {}
    for r in plan.recipients:
        if r.kind is StewardKind.USER:
            seen.setdefault(r.id, None)
            continue
        members = await provider.members_of(r.id)
        if members:
            for m in members:
                seen.setdefault(m, None)
        else:
            seen.setdefault(r.id, None)
    return tuple(seen.keys())


def affected_agents_from_workflow(workflow_raw: Mapping[str, object]) -> frozenset[str]:
    """Return the pantheon agents a workflow document references.

    Scans the parsed workflow mapping recursively for any string that is a
    pantheon agent name. Used to notify the right stewards when a workflow file
    change is proposed.
    """
    found: set[str] = set()

    def _walk(node: object) -> None:
        if isinstance(node, str):
            if node in AGENT_NAME_SET:
                found.add(node)
        elif isinstance(node, Mapping):
            for v in node.values():
                _walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                _walk(v)

    _walk(workflow_raw)
    return frozenset(found)


def affected_agents_from_stewardship_change(
    before: StewardshipMap,
    after: StewardshipMap,
) -> frozenset[str]:
    """Return agents affected by a validated stewardship-map replacement."""
    global_change = (
        before.maintainers != after.maintainers
        or dict(before.channels) != dict(after.channels)
        or before.hop_timeout_seconds != after.hop_timeout_seconds
        or before.over_assigned_max != after.over_assigned_max
    )
    if global_change:
        return AGENT_NAME_SET
    return frozenset(name for name in AGENT_NAME_SET if before.agents[name] != after.agents[name])


def stakeholders_for_change(
    mp: StewardshipMap, agents: Iterable[str]
) -> tuple[EscalationRecipient, ...]:
    """Compute the notify list for a change touching ``agents``.

    Union of each agent's accountable + informed stewards plus the maintainer
    set, de-duplicated by object id, ordered accountable-first. This is the
    recipient set for a workflow-change / stewardship-change notification.
    """
    seen: dict[str, EscalationRecipient] = {}

    def _add(rec: EscalationRecipient) -> None:
        # Keep the highest-priority tier if an id appears twice.
        existing = seen.get(rec.id)
        if existing is None or _tier_rank(rec.tier) < _tier_rank(existing.tier):
            seen[rec.id] = rec

    for name in agents:
        if name not in mp.agents:
            continue
        agent = mp.agents[name]
        for s in agent.accountable:
            _add(EscalationRecipient(s.kind, s.id, EscalationTier.ACCOUNTABLE))
        for s in agent.informed:
            _add(EscalationRecipient(s.kind, s.id, EscalationTier.INFORMED))
    for oid in mp.maintainer_oids:
        _add(EscalationRecipient(StewardKind.USER, oid, EscalationTier.MAINTAINER))

    return tuple(sorted(seen.values(), key=lambda r: _tier_rank(r.tier)))


def _tier_rank(tier: EscalationTier) -> int:
    return {
        EscalationTier.ACCOUNTABLE: 0,
        EscalationTier.INFORMED: 1,
        EscalationTier.MAINTAINER: 2,
    }[tier]


__all__ = [
    "EscalationPlan",
    "EscalationRecipient",
    "EscalationTier",
    "affected_agents_from_stewardship_change",
    "affected_agents_from_workflow",
    "build_escalation_plan",
    "expand_group_recipients",
    "resolve_person_channel",
    "stakeholders_for_change",
]
