"""Typed contract models mirroring the JSON schemas in this package.

The **JSON schemas are the source of truth**; these pydantic models are their
generated (hand-authored, sha-pinned) Python view. Consumers should:

- Prefer these models for programmatic construction and serialization.
- Use :mod:`fdai.shared.contracts.validation` when accepting data across
  an untrusted boundary (event ingress, config load, catalog import) - even
  when the pydantic model succeeds, the JSON Schema re-check guards against a
  drift between the two views.

Dependency-injection notes
--------------------------
These models are *data*, not services, so they are not themselves DI seams.
The seams sit next to them:

- :class:`fdai.shared.contracts.registry.SchemaRegistry` - swap the
  source of raw schemas (default: package resources; a fork MAY point at a
  remote registry).
- :class:`fdai.shared.contracts.validation.EventValidator` - swap the
  validation policy (default: JSON Schema draft-2020-12; a fork MAY layer in
  domain-specific checks).

Every core module that consumes contracts depends on the Protocols above,
never on a concrete implementation, so a fork can register its own without
touching ``core/``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Shared enums - kept as StrEnum so JSON serialization matches the schema.
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


class CheckLogicKind(StrEnum):
    REGO = "rego"
    EXPRESSION = "expression"


class Redistribution(StrEnum):
    """Whether a rule source's raw text may be redistributed in this repo.

    Two independent axes govern a source: ``license`` (an SPDX identifier or
    ``LicenseRef-reference-only``) records **what** the license is;
    ``redistribution`` records **what the collector may commit** - the
    enforcement value, not the license name (see
    ``docs/roadmap/rule-catalog-collection.md § Licensing``).
    """

    EMBEDDABLE = "embeddable"
    REFERENCE_ONLY = "reference-only"


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


class EnvScope(StrEnum):
    """Which environments an ActionType may fire in (action-ontology.md 2)."""

    PROD = "prod"
    NON_PROD = "non_prod"
    ANY = "any"


# Aliases mirroring the JSON Schema pattern for semver strings.
SemVer = Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$", min_length=5)]
IdempotencyKey = Annotated[str, Field(min_length=1, max_length=512)]


class _Base(BaseModel):
    """Base config shared by every contract model."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------


class Event(_Base):
    """Normalized event entering the control loop.

    Payloads (``payload`` field) are untrusted; the verifier and policy re-check
    are the authority, never model or event text.
    """

    schema_version: SemVer
    event_id: UUID
    idempotency_key: IdempotencyKey
    correlation_id: str | None = None
    source: Annotated[str, Field(min_length=1)]
    event_type: Annotated[str, Field(min_length=1)]
    resource_ref: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    detected_at: datetime
    ingested_at: datetime
    tier: Tier | None = None
    decision: Decision | None = None
    mode: Mode


# ---------------------------------------------------------------------------
# Incident (first-class correlation entity - see docs/roadmap/scope-expansion.md
# § 3.1). Groups many Events / Findings / Actions under one lifecycle so
# postmortems, on-call handoffs, and after-action reviews have a durable
# anchor. The state machine is enforced by ``core/incident``; this model is
# the wire shape only.
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


class Incident(_Base):
    """First-class incident record.

    Field docstrings mirror the JSON Schema at
    ``shared/contracts/incident/schema.json`` - the schema stays the source
    of truth; this pydantic view is the typed programmatic surface for
    ``core/incident``.

    ``incident_id`` is deterministic: UUID5(NAMESPACE_URL, sorted-tuple of
    ``correlation_keys``). Re-emitting the same key set yields the same id,
    which is the mechanism ``core/incident/registry`` uses for idempotent
    correlation.
    """

    schema_version: SemVer
    incident_id: UUID
    state: IncidentState
    severity: IncidentSeverity
    opened_at: datetime
    mitigated_at: datetime | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    correlation_keys: tuple[str, ...] = Field(min_length=1)
    member_event_ids: tuple[UUID, ...] = Field(min_length=1)
    related_finding_ids: tuple[str, ...] = ()
    related_action_ids: tuple[UUID, ...] = ()
    assignee_oid: str | None = None
    mitigation_summary: str | None = None
    postmortem_ref: str | None = None

    @field_validator(
        "correlation_keys",
        "member_event_ids",
        "related_finding_ids",
        "related_action_ids",
        mode="before",
    )
    @classmethod
    def _list_to_tuple(cls, v: Any) -> Any:
        if isinstance(v, list):
            return tuple(v)
        return v


# ---------------------------------------------------------------------------
# Action (safety-invariant fields are mandatory)
# ---------------------------------------------------------------------------


class RollbackRef(_Base):
    kind: RollbackKind
    reference: str | None = None


class BlastRadius(_Base):
    scope: BlastRadiusScope
    count: int | None = Field(default=None, ge=1)
    rate_per_minute: int | None = Field(default=None, ge=1)


class Action(_Base):
    """Autonomous action proposed by a tier, subject to the risk gate.

    The four safety-invariant fields (``stop_condition``, ``rollback_ref``,
    ``blast_radius``, plus the audit entry that consumers of this model MUST
    write when they persist the action) are mandatory. An action missing any
    of them is incomplete and MUST NOT execute.
    """

    schema_version: SemVer
    action_id: UUID
    idempotency_key: IdempotencyKey
    event_id: UUID
    action_type: Annotated[str, Field(min_length=1)]
    target_resource_ref: Annotated[str, Field(min_length=1)]
    operation: Operation
    params: dict[str, Any] = Field(default_factory=dict)
    stop_condition: Annotated[str, Field(min_length=1)]
    rollback_ref: RollbackRef
    blast_radius: BlastRadius
    mode: Mode
    citing_rules: Annotated[list[str], Field(min_length=1)]
    created_at: datetime


# ---------------------------------------------------------------------------
# Rule (catalog entry)
# ---------------------------------------------------------------------------


class CheckLogic(_Base):
    kind: CheckLogicKind
    reference: Annotated[str, Field(min_length=1)]


class Remediation(_Base):
    template_ref: Annotated[str, Field(min_length=1)]
    cost_impact_monthly_usd: float | None = Field(default=None, ge=0)


class Provenance(_Base):
    """Auditable origin of a rule / catalog entry.

    Field names follow the canonical vocabulary in
    ``docs/roadmap/rule-catalog-collection.md`` (``resolved_ref``,
    ``retrieved_at``, ``redistribution`` as an enum) so a hand-authored
    YAML lifted from that doc validates against this model without any
    field-name gymnastics.
    """

    source_url: Annotated[str, Field(min_length=1)]
    source_version: Annotated[str, Field(min_length=1)] | None = None
    resolved_ref: Annotated[str, Field(min_length=1)]
    content_hash: Annotated[str, Field(min_length=1)]
    license: Annotated[str, Field(min_length=1)]
    redistribution: Redistribution
    retrieved_at: datetime
    mapped_by: Annotated[str, Field(min_length=1)] | None = None


class Rule(_Base):
    """Normalized, CSP-neutral rule entry.

    ``provenance`` is mandatory: a rule without grounded provenance is rejected
    at load, matching the discovery-loop rule in
    ``architecture.instructions.md § Design Principles``.

    ``remediates`` is the ontology dispatch field (M:1) declaring which
    :class:`OntologyActionType` this rule proposes on match; the catalog
    loader cross-checks it against ``rule-catalog/action-types/`` at load
    time. ``alternatives`` is a preference-ordered list of alternate
    ActionType names - T0 always uses ``remediates``; only the T2 quality
    gate may swap in an alternative. See
    ``docs/roadmap/llm-strategy.md § Rule as Ontology Artifact``.
    """

    schema_version: SemVer
    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")]
    version: SemVer
    source: RuleSource
    severity: Severity
    category: Category
    resource_type: Annotated[str, Field(min_length=1)]
    check_logic: CheckLogic
    remediation: Remediation
    remediates: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_\.\-]{0,79}$")]
    alternatives: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_\.\-]{0,79}$")]] = Field(
        default_factory=list
    )
    parameters: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance
    applies_to: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Ontology declarations
# ---------------------------------------------------------------------------


class PropertyDecl(_Base):
    type: PropertyType
    required: bool = False
    description: str | None = None
    access_scope: CeilingRole = CeilingRole.READER
    purpose_binding: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]] = Field(
        default_factory=list
    )


class OntologyObjectType(_Base):
    schema_version: SemVer
    name: Annotated[str, Field(pattern=r"^[A-Z][A-Za-z0-9]{0,63}$")]
    version: SemVer
    key: Annotated[str, Field(min_length=1)]
    properties: dict[str, PropertyDecl]
    description: str | None = None


class OntologyLinkType(_Base):
    schema_version: SemVer
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    version: SemVer
    from_type: Annotated[str, Field(min_length=1)]
    to_type: Annotated[str, Field(min_length=1)]
    cardinality: LinkCardinality
    is_transitive: bool = False
    is_causal: bool = False
    temporal_order: bool = False
    description: str | None = None


class PromotionGate(_Base):
    min_shadow_days: Annotated[int, Field(ge=1)]
    min_samples: Annotated[int, Field(ge=1)]
    min_accuracy: Annotated[float, Field(ge=0.0, le=1.0)]
    max_policy_escapes: Annotated[int, Field(ge=0)]


class ActionPrecondition(_Base):
    kind: PreconditionKind
    value: str | int | float | bool | None = None
    link_type: str | None = None
    property: str | None = None
    tag: str | None = None


class ActionStopCondition(_Base):
    kind: StopConditionKind
    threshold: float | None = None
    window_seconds: Annotated[int, Field(ge=1)] | None = None
    seconds: Annotated[int, Field(ge=1)] | None = None
    count: Annotated[int, Field(ge=1)] | None = None


class ActionBlastRadius(_Base):
    computation: BlastRadiusComputation
    static_bucket: BlastRadiusScope | None = None
    max_affected_resources: Annotated[int, Field(ge=1)] | None = None
    traversal_depth: Annotated[int, Field(ge=1, le=5)] = 2
    traversal_links: list[str] = Field(default_factory=lambda: ["contains", "depends_on"])


class TriggerKindDecl(_Base):
    """The ``trigger_kind`` axis on an ActionType (action-ontology.md 1)."""

    kind: TriggerKind
    restrict_to_scenarios: list[str] = Field(default_factory=list)


class TierCeiling(_Base):
    """One tier's ceiling: the highest autonomy and the lowest role."""

    max_autonomy: Autonomy
    min_role: CeilingRole


class CeilingByTier(_Base):
    """Per-tier autonomy/role ceilings (execution-model.md 2.2)."""

    t0: TierCeiling | None = None
    t1: TierCeiling | None = None
    t2: TierCeiling | None = None


class ProdDowngrade(_Base):
    """How an ActionType collapses in prod (execution-model.md 2.6).

    ``detection_ref`` resolves to the single environment classifier in
    risk-classification.md; it never defines a second prod rule here.
    """

    mode: Autonomy
    detection_ref: Annotated[str, Field(min_length=1)]

    @field_validator("mode")
    @classmethod
    def _mode_is_a_downgrade(cls, value: Autonomy) -> Autonomy:
        if value is Autonomy.ENFORCE_AUTO:
            raise ValueError(
                "prod_downgrade.mode cannot be enforce_auto (a downgrade never raises autonomy)"
            )
        return value


class OntologyActionType(_Base):
    schema_version: SemVer
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_\.\-]{0,79}$")]
    version: SemVer
    operation: Operation
    interfaces: list[ActionInterface] = Field(default_factory=list)
    rollback_contract: RollbackKind
    irreversible: bool = False
    default_mode: Mode = Mode.SHADOW
    promotion_gate: PromotionGate
    preconditions: list[ActionPrecondition] = Field(default_factory=list)
    stop_conditions: list[ActionStopCondition] = Field(default_factory=list)
    blast_radius: ActionBlastRadius | None = None
    description: str | None = None
    # --- Execution-authority extension (Day-1 non-breaking; all optional) ---
    # Populated by the ontology backfill (action-ontology.md 10); shipped
    # ActionTypes that predate it validate unchanged because every field
    # below is optional and ``exclude_none`` drops the empty ones on dump.
    category: ActionCategory | None = None
    trigger_kind: TriggerKindDecl | None = None
    execution_path: ExecutionPath | None = None
    ceiling_by_tier: CeilingByTier | None = None
    env_scope: EnvScope = EnvScope.ANY
    prod_downgrade: ProdDowngrade | None = None
    argument_schema: dict[str, Any] | None = None
    live_probe_ref: str | None = None


class WorkflowTriggerKind(StrEnum):
    """How a Workflow run is started (process-automation.md 2)."""

    SIGNAL = "signal"
    SCHEDULE = "schedule"


class WorkflowTrigger(_Base):
    """The event or schedule that starts a Workflow run."""

    kind: WorkflowTriggerKind
    signal_type: str | None = None
    schedule: str | None = None

    @model_validator(mode="after")
    def _payload_matches_kind(self) -> WorkflowTrigger:
        if self.kind is WorkflowTriggerKind.SIGNAL and not self.signal_type:
            raise ValueError("trigger.kind=signal requires a non-empty signal_type")
        if self.kind is WorkflowTriggerKind.SCHEDULE and not self.schedule:
            raise ValueError("trigger.kind=schedule requires a non-empty schedule")
        return self


class WorkflowStep(_Base):
    """One step in a Workflow: an ActionType invocation plus optional
    guard, saga-compensation, and on-failure branch. A step never carries
    its own mutation logic - it delegates to ``action_type_ref`` so it
    inherits that ActionType's four safety invariants."""

    id: Annotated[str, Field(min_length=1)]
    action_type_ref: Annotated[str, Field(min_length=1)]
    guard_rule_ref: str | None = None
    compensated_by: str | None = None
    on_failure: str | None = None


class Workflow(_Base):
    """A declarative business process (process-automation.md 2).

    Ordered list of :class:`WorkflowStep`, each referencing one ontology
    ActionType, plus a trigger, a promotion gate, and a default mode.
    Structural invariants (unique step ids; every ``on_failure`` target
    exists) are enforced here; cross-references to the ActionType and rule
    catalogs are enforced by the loader in
    :mod:`fdai.rule_catalog.schema.workflow`.
    """

    schema_version: SemVer
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_\.\-]{0,79}$")]
    version: SemVer
    trigger: WorkflowTrigger
    default_mode: Mode = Mode.SHADOW
    promotion_gate: PromotionGate
    steps: Annotated[list[WorkflowStep], Field(min_length=1)]
    description: Annotated[str, Field(max_length=200)] | None = None
    anti_scope: str | None = None

    @model_validator(mode="after")
    def _structural_invariants(self) -> Workflow:
        seen: set[str] = set()
        for step in self.steps:
            if step.id in seen:
                raise ValueError(f"duplicate step id {step.id!r}")
            seen.add(step.id)
        for step in self.steps:
            if step.on_failure is not None:
                if step.on_failure == step.id:
                    raise ValueError(
                        f"step {step.id!r} on_failure points at itself; "
                        "a step cannot be its own failure fallback"
                    )
                if step.on_failure not in seen:
                    raise ValueError(
                        f"step {step.id!r} on_failure -> unknown step {step.on_failure!r}"
                    )
        return self


__all__ = [
    # enums
    "ActionCategory",
    "ActionInterface",
    "Autonomy",
    "BlastRadiusComputation",
    "BlastRadiusScope",
    "Category",
    "CeilingRole",
    "CheckLogicKind",
    "Decision",
    "EnvScope",
    "ExecutionPath",
    "LinkCardinality",
    "Mode",
    "Operation",
    "PreconditionKind",
    "PropertyType",
    "Redistribution",
    "RollbackKind",
    "RuleSource",
    "Severity",
    "StopConditionKind",
    "Tier",
    "TriggerKind",
    "WorkflowTriggerKind",
    # aliases
    "IdempotencyKey",
    "SemVer",
    # models
    "Action",
    "ActionBlastRadius",
    "ActionPrecondition",
    "ActionStopCondition",
    "PromotionGate",
    "BlastRadius",
    "CeilingByTier",
    "CheckLogic",
    "Event",
    "Incident",
    "IncidentSeverity",
    "IncidentState",
    "OntologyActionType",
    "ProdDowngrade",
    "TierCeiling",
    "TriggerKindDecl",
    "OntologyLinkType",
    "OntologyObjectType",
    "PropertyDecl",
    "Provenance",
    "Remediation",
    "RollbackRef",
    "Rule",
    "Workflow",
    "WorkflowStep",
    "WorkflowTrigger",
]
