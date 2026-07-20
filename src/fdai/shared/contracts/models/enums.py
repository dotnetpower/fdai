"""Shared StrEnum vocabulary for the contract models.

Every enum is a :class:`~enum.StrEnum` so JSON serialisation matches the
JSON Schema without an intermediate coercion pass. Enums are grouped here
so any domain file can import the vocabulary it needs without pulling in
another domain's models.
"""

from __future__ import annotations

from enum import StrEnum

# ---------------------------------------------------------------------------
# Pipeline vocabulary
# ---------------------------------------------------------------------------


class Tier(StrEnum):
    """Trust-router tier assignment."""

    T0 = "t0"
    T1 = "t1"
    T2 = "t2"


class Decision(StrEnum):
    """Risk-gate outcome."""

    AUTO = "auto"
    HIL = "hil"
    ABSTAIN = "abstain"
    DENY = "deny"


class Mode(StrEnum):
    """Autonomy mode at the time of processing.

    New capabilities always ship as :attr:`SHADOW`; promotion to
    :attr:`ENFORCE` is a separately reviewed change (see
    ``architecture.instructions.md § Safety Invariants``).
    """

    SHADOW = "shadow"
    ENFORCE = "enforce"


class IncidentCorrelation(StrEnum):
    """Whether an Event may be grouped into an Incident."""

    CORRELATE = "correlate"
    NONE = "none"


class Operation(StrEnum):
    """Executor operation vocabulary shared by Action and ontology ActionType."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    DISABLE = "disable"
    ENABLE = "enable"
    TAG = "tag"
    DROP = "drop"
    PURGE = "purge"
    SCALE = "scale"
    RESTART = "restart"
    FAILOVER = "failover"
    ROTATE = "rotate"
    REVERT = "revert"
    ATTACH = "attach"
    DETACH = "detach"
    QUARANTINE = "quarantine"


# ---------------------------------------------------------------------------
# Rule vocabulary
# ---------------------------------------------------------------------------


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Category(StrEnum):
    SECURITY = "security"
    RELIABILITY = "reliability"
    COST = "cost"
    CONFIG_DRIFT = "config_drift"
    COMPLIANCE = "compliance"


class RuleSource(StrEnum):
    WAF = "waf"
    AKS_BASELINE = "aks_baseline"
    MCSB = "mcsb"
    AZURE_POLICY = "azure_policy"
    AZURE_ADVISOR = "azure_advisor"
    CIS = "cis"
    OPA_GATEKEEPER = "opa_gatekeeper"
    CHECKOV = "checkov"
    TFSEC = "tfsec"
    KICS = "kics"
    TRIVY = "trivy"
    KUBE_BENCH = "kube_bench"
    CUSTOM = "custom"


class CheckLogicKind(StrEnum):
    REGO = "rego"
    EXPRESSION = "expression"


class Redistribution(StrEnum):
    """Whether a rule source's raw text may be redistributed in this repo.

    Two independent axes govern a source: ``license`` (an SPDX identifier or
    ``LicenseRef-reference-only``) records **what** the license is;
    ``redistribution`` records **what the collector may commit** - the
    enforcement value, not the license name (see
    ``docs/roadmap/rules-and-detection/rule-catalog-collection.md § Licensing``).
    """

    EMBEDDABLE = "embeddable"
    REFERENCE_ONLY = "reference-only"


# ---------------------------------------------------------------------------
# Action / blast-radius vocabulary
# ---------------------------------------------------------------------------


class BlastRadiusScope(StrEnum):
    RESOURCE = "resource"
    RESOURCE_GROUP = "resource_group"
    SUBSCRIPTION = "subscription"


class RollbackKind(StrEnum):
    PR_REVERT = "pr_revert"
    SCRIPTED = "scripted"
    PITR = "pitr"
    SNAPSHOT_RESTORE = "snapshot_restore"
    STATE_FORWARD_ONLY = "state_forward_only"


# ---------------------------------------------------------------------------
# Ontology vocabulary
# ---------------------------------------------------------------------------


class LinkCardinality(StrEnum):
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"


class ActionInterface(StrEnum):
    CONTROL_PLANE = "ControlPlane"
    DATA_PLANE_MUTATING = "DataPlaneMutating"
    IDEMPOTENT_BY_KEY = "IdempotentByKey"
    RATE_LIMITED = "RateLimited"
    REQUIRES_INVENTORY_FRESH = "RequiresInventoryFresh"
    GRAPH_TRAVERSAL_REQUIRED = "GraphTraversalRequired"
    CROSS_RESOURCE = "CrossResource"
    ASYMMETRIC_ROLLBACK = "AsymmetricRollback"
    REQUIRES_MAINTENANCE_WINDOW = "RequiresMaintenanceWindow"


class BlastRadiusComputation(StrEnum):
    STATIC_ENUM = "static_enum"
    GRAPH_DERIVED = "graph_derived"


class PreconditionKind(StrEnum):
    GRAPH_FRESH_WITHIN_SECONDS = "graph_fresh_within_seconds"
    LINK_EXISTS = "link_exists"
    LINK_ABSENT = "link_absent"
    NO_CONFLICTING_OPEN_ACTION_ON_RESOURCE = "no_conflicting_open_action_on_resource"
    MAINTENANCE_WINDOW_ACTIVE = "maintenance_window_active"
    RESOURCE_PROPERTY_EQUALS = "resource_property_equals"
    RESOURCE_TAG_PRESENT = "resource_tag_present"


class StopConditionKind(StrEnum):
    ERROR_RATE_ABOVE = "error_rate_above"
    LATENCY_P99_ABOVE_MS = "latency_p99_above_ms"
    DEPENDENT_RESOURCE_DEGRADED = "dependent_resource_degraded"
    TIME_BOX_EXCEEDED_SECONDS = "time_box_exceeded_seconds"
    PROVIDER_API_ERROR_STREAK = "provider_api_error_streak"


class PropertyType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"
    DATETIME = "datetime"


class TriggerKind(StrEnum):
    """Who initiates an ActionType invocation (action-ontology.md 1)."""

    RULE_VIOLATION = "rule_violation"
    OPERATOR_REQUEST = "operator_request"
    BOTH = "both"


class ActionCategory(StrEnum):
    """Top-level ActionType bucket (action-ontology.md 3)."""

    REMEDIATION = "remediation"
    OPS = "ops"
    GOVERNANCE = "governance"
    TOOL = "tool"


class Autonomy(StrEnum):
    """Per-tier autonomy ceiling level (execution-model.md 2)."""

    ENFORCE_AUTO = "enforce_auto"
    ENFORCE_HIL = "enforce_hil"
    SHADOW_ONLY = "shadow_only"


class CeilingRole(StrEnum):
    """Ordinary RBAC ladder used by a ceiling ``min_role``.

    BreakGlass is deliberately absent: it is off-ladder (a separate Entra
    group, not nested in Owner - see user-rbac-and-identity.md 2) and is
    never a ``min_role`` value.
    """

    READER = "reader"
    CONTRIBUTOR = "contributor"
    APPROVER = "approver"
    OWNER = "owner"


CEILING_ROLE_RANK: dict[CeilingRole, int] = {
    CeilingRole.READER: 0,
    CeilingRole.CONTRIBUTOR: 1,
    CeilingRole.APPROVER: 2,
    CeilingRole.OWNER: 3,
}
"""Numeric rank for :class:`CeilingRole` comparisons.

``a >= b`` at the role level is ``CEILING_ROLE_RANK[a] >= CEILING_ROLE_RANK[b]``.
Shared so ``shared/`` and ``core/`` can both order roles without either
side depending on the other. Kept as a module-level dict rather than an
:class:`~enum.IntEnum` because :class:`CeilingRole` MUST serialize as a
string in every audit / config artifact.
"""


class ExecutionPath(StrEnum):
    """How the executor applies an action (execution-model.md 5)."""

    PR_NATIVE = "pr_native"
    DIRECT_API = "direct_api"
    PR_MANUAL = "pr_manual"
    TOOL_CALL = "tool_call"


class EnvScope(StrEnum):
    """Which environments an ActionType may fire in (action-ontology.md 2)."""

    PROD = "prod"
    NON_PROD = "non_prod"
    ANY = "any"


# ---------------------------------------------------------------------------
# Incident vocabulary
# ---------------------------------------------------------------------------


class IncidentState(StrEnum):
    """Lifecycle states for an :class:`Incident`.

    Legal transitions (enforced by ``core/incident/state_machine.py``):

    - ``OPEN`` -> ``TRIAGING`` | ``MITIGATED``
    - ``TRIAGING`` -> ``MITIGATED`` | ``RESOLVED``
    - ``MITIGATED`` -> ``RESOLVED``
    - ``RESOLVED`` -> ``CLOSED`` | ``TRIAGING`` (re-open)
    - ``CLOSED`` -> terminal (no outgoing transitions)
    """

    OPEN = "open"
    TRIAGING = "triaging"
    MITIGATED = "mitigated"
    RESOLVED = "resolved"
    CLOSED = "closed"


class IncidentSeverity(StrEnum):
    """PagerDuty / Datadog-style severity levels.

    ``SEV1`` = customer-visible outage; ``SEV5`` = informational. Set at
    open; may be adjusted on re-open through the state machine.
    """

    SEV1 = "sev1"
    SEV2 = "sev2"
    SEV3 = "sev3"
    SEV4 = "sev4"
    SEV5 = "sev5"


# ---------------------------------------------------------------------------
# Workflow vocabulary
# ---------------------------------------------------------------------------


class WorkflowTriggerKind(StrEnum):
    """How a Workflow run is started (process-automation.md 2)."""

    SIGNAL = "signal"
    SCHEDULE = "schedule"


class WorkflowStepKind(StrEnum):
    """Typed behavior of one Workflow step."""

    ACTION = "action"
    WAIT = "wait"
    APPROVAL = "approval"
    DECISION = "decision"
    PARALLEL = "parallel"
    GATE = "gate"


__all__ = [
    # pipeline
    "Tier",
    "Decision",
    "Mode",
    "Operation",
    # rule
    "Severity",
    "Category",
    "RuleSource",
    "CheckLogicKind",
    "Redistribution",
    # action
    "BlastRadiusScope",
    "RollbackKind",
    # ontology
    "LinkCardinality",
    "ActionInterface",
    "BlastRadiusComputation",
    "PreconditionKind",
    "StopConditionKind",
    "PropertyType",
    "TriggerKind",
    "ActionCategory",
    "Autonomy",
    "CeilingRole",
    "CEILING_ROLE_RANK",
    "ExecutionPath",
    "EnvScope",
    # incident
    "IncidentState",
    "IncidentSeverity",
    # workflow
    "WorkflowTriggerKind",
    "WorkflowStepKind",
]
