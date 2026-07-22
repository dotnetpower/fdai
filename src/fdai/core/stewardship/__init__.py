"""Agent stewardship + handover - human <-> 15-agent pantheon accountability.

An accountability + notification **overlay** on the pantheon, orthogonal to
:mod:`fdai.core.rbac`: RBAC gates what a human may operate; stewardship routes
which human owns and is escalated for each agent's domain. It never holds or
grants the executor identity and never repoints a fork-locked ActionType role.

Sub-modules (each one responsibility, SRP):

- :mod:`.names` - canonical 15 agent names (parity-pinned to the pantheon).
- :mod:`.model` - pure dataclasses + enums for the handover map.
- :mod:`.resolver` - parse + fail-fast validate config into a :class:`StewardshipMap`.
- :mod:`.coverage` - non-blocking findings (bus-factor, over-assignment, stale OID).
- :mod:`.escalation` - escalation chains, person->channel bridge, change stakeholders.
- :mod:`.directory` - injected Graph seams (identity liveness, group expansion).

Design authority:
[`docs/roadmap/interfaces/agent-stewardship-and-handover.md`]
(../../../../docs/roadmap/interfaces/agent-stewardship-and-handover.md).
"""

from __future__ import annotations

from fdai.core.stewardship.coverage import (
    CoverageReport,
    Finding,
    Severity,
    audit_stale_oids,
    build_coverage_report,
)
from fdai.core.stewardship.directory import (
    GroupMembershipProvider,
    IdentityDirectory,
    StaticGroupMembershipProvider,
    StaticIdentityDirectory,
)
from fdai.core.stewardship.escalation import (
    EscalationPlan,
    EscalationRecipient,
    EscalationTier,
    affected_agents_from_stewardship_change,
    affected_agents_from_workflow,
    build_escalation_plan,
    expand_group_recipients,
    resolve_person_channel,
    stakeholders_for_change,
)
from fdai.core.stewardship.model import (
    AgentStewardship,
    Maintainer,
    Responsibility,
    StewardKind,
    StewardshipMap,
    StewardshipValidationError,
    StewardSubject,
)
from fdai.core.stewardship.names import AGENT_NAME_SET, AGENT_NAMES
from fdai.core.stewardship.notify import (
    CHANGE_CATEGORY,
    StewardshipChangeEvent,
    StewardshipChangePhase,
    build_change_audit_payload,
    build_change_notification,
)
from fdai.core.stewardship.resolver import (
    load_stewardship_from_mapping,
    load_stewardship_from_yaml,
)

__all__ = [
    "AGENT_NAMES",
    "AGENT_NAME_SET",
    "AgentStewardship",
    "CHANGE_CATEGORY",
    "CoverageReport",
    "EscalationPlan",
    "EscalationRecipient",
    "EscalationTier",
    "Finding",
    "GroupMembershipProvider",
    "IdentityDirectory",
    "Maintainer",
    "Responsibility",
    "Severity",
    "StaticGroupMembershipProvider",
    "StaticIdentityDirectory",
    "StewardKind",
    "StewardSubject",
    "StewardshipMap",
    "StewardshipValidationError",
    "StewardshipChangeEvent",
    "StewardshipChangePhase",
    "affected_agents_from_stewardship_change",
    "affected_agents_from_workflow",
    "audit_stale_oids",
    "build_change_audit_payload",
    "build_change_notification",
    "build_coverage_report",
    "build_escalation_plan",
    "expand_group_recipients",
    "load_stewardship_from_mapping",
    "load_stewardship_from_yaml",
    "resolve_person_channel",
    "stakeholders_for_change",
]
