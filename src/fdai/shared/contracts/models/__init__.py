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

Package layout
--------------

The pydantic models live in per-domain submodules (G-4 refactor, tracker
#14). Every public symbol is re-exported here so the pre-refactor import
path (``from fdai.shared.contracts.models import Event``) still works
unchanged; there is no need to import from the submodules directly.

- :mod:`._base` - :class:`_Base`, :data:`SemVer`, :data:`IdempotencyKey`
- :mod:`.enums` - every :class:`~enum.StrEnum` used across the domains
- :mod:`.event` - the normalised event contract
- :mod:`.incident` - the incident-lifecycle contract
- :mod:`.action` - autonomous action + blast-radius + rollback-ref
- :mod:`.rule` - the CSP-neutral rule / catalog entry
- :mod:`.ontology` - ObjectType / LinkType / ActionType declarations
- :mod:`.workflow` - the process-automation contract
"""

from __future__ import annotations

from ._base import ContractBase, IdempotencyKey, SemVer, _Base
from .action import Action, BlastRadius, RollbackRef
from .document import (
    AccessDescriptor,
    DocumentEnvelope,
    DocumentPurpose,
    DocumentState,
    DocumentVersion,
    IngestionCapabilities,
    MalwareVerdict,
    ProtectionState,
    RetentionPolicy,
    SourceStorageMode,
    StructuralUnit,
    UploadSession,
)
from .enums import (
    CEILING_ROLE_RANK,
    ActionCategory,
    ActionInterface,
    Autonomy,
    BlastRadiusComputation,
    BlastRadiusScope,
    Category,
    CeilingRole,
    CheckLogicKind,
    Decision,
    EnvScope,
    ExecutionPath,
    IncidentCorrelation,
    IncidentSeverity,
    IncidentState,
    LinkCardinality,
    Mode,
    Operation,
    PreconditionKind,
    PropertyType,
    Redistribution,
    RollbackKind,
    RuleSource,
    Severity,
    StopConditionKind,
    Tier,
    TriggerKind,
    WorkflowStepKind,
    WorkflowTriggerKind,
)
from .event import Event
from .incident import Incident
from .ontology import (
    ActionBlastRadius,
    ActionPrecondition,
    ActionStopCondition,
    CeilingByTier,
    OntologyActionType,
    OntologyLinkType,
    OntologyObjectType,
    ProdDowngrade,
    PromotionGate,
    PropertyDecl,
    TierCeiling,
    TriggerKindDecl,
)
from .rule import CheckLogic, Provenance, Remediation, Rule
from .workflow import Workflow, WorkflowStep, WorkflowTrigger

__all__ = [
    # enums
    "AccessDescriptor",
    "ActionCategory",
    "ActionInterface",
    "Autonomy",
    "BlastRadiusComputation",
    "BlastRadiusScope",
    "Category",
    "CeilingRole",
    "CEILING_ROLE_RANK",
    "CheckLogicKind",
    "Decision",
    "EnvScope",
    "ExecutionPath",
    "IncidentCorrelation",
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
    "WorkflowStepKind",
    # aliases + base
    "ContractBase",
    "IdempotencyKey",
    "SemVer",
    "_Base",
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
    "DocumentEnvelope",
    "DocumentVersion",
    "DocumentPurpose",
    "DocumentState",
    "IngestionCapabilities",
    "MalwareVerdict",
    "SourceStorageMode",
    "ProtectionState",
    "RetentionPolicy",
    "StructuralUnit",
    "UploadSession",
]
