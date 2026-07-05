"""Typed contract models mirroring the JSON schemas in this package.

The **JSON schemas are the source of truth**; these pydantic models are their
generated (hand-authored, sha-pinned) Python view. Consumers should:

- Prefer these models for programmatic construction and serialization.
- Use :mod:`aiopspilot.shared.contracts.validation` when accepting data across
  an untrusted boundary (event ingress, config load, catalog import) — even
  when the pydantic model succeeds, the JSON Schema re-check guards against a
  drift between the two views.

Dependency-injection notes
--------------------------
These models are *data*, not services, so they are not themselves DI seams.
The seams sit next to them:

- :class:`aiopspilot.shared.contracts.registry.SchemaRegistry` — swap the
  source of raw schemas (default: package resources; a fork MAY point at a
  remote registry).
- :class:`aiopspilot.shared.contracts.validation.EventValidator` — swap the
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

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Shared enums — kept as StrEnum so JSON serialization matches the schema.
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
    NONE = "none"


class CheckLogicKind(StrEnum):
    REGO = "rego"
    EXPRESSION = "expression"


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


class PropertyType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"
    DATETIME = "datetime"


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
    source_url: Annotated[str, Field(min_length=1)]
    resolved_revision: Annotated[str, Field(min_length=1)]
    content_hash: Annotated[str, Field(min_length=1)]
    license: Annotated[str, Field(min_length=1)]
    redistribution: bool
    imported_at: datetime


class Rule(_Base):
    """Normalized, CSP-neutral rule entry.

    ``provenance`` is mandatory: a rule without grounded provenance is rejected
    at load, matching the discovery-loop rule in
    ``architecture.instructions.md § Design Principles``.
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
    provenance: Provenance
    applies_to: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Ontology declarations
# ---------------------------------------------------------------------------


class PropertyDecl(_Base):
    type: PropertyType
    required: bool = False
    description: str | None = None


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
    description: str | None = None


class OntologyActionType(_Base):
    schema_version: SemVer
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    version: SemVer
    operation: Operation
    interfaces: list[ActionInterface] = Field(default_factory=list)
    rollback_contract: RollbackKind
    description: str | None = None


__all__ = [
    # enums
    "ActionInterface",
    "BlastRadiusScope",
    "Category",
    "CheckLogicKind",
    "Decision",
    "LinkCardinality",
    "Mode",
    "Operation",
    "PropertyType",
    "RollbackKind",
    "RuleSource",
    "Severity",
    "Tier",
    # aliases
    "IdempotencyKey",
    "SemVer",
    # models
    "Action",
    "BlastRadius",
    "CheckLogic",
    "Event",
    "OntologyActionType",
    "OntologyLinkType",
    "OntologyObjectType",
    "PropertyDecl",
    "Provenance",
    "Remediation",
    "RollbackRef",
    "Rule",
]
