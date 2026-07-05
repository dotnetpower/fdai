"""Ontology types and event / action / rule schemas (versioned).

Ontology (Resource / Rule / Signal / Finding) plus event / action / rule
schemas. Public API. Re-exports the *interfaces* (Protocols, data models,
errors) that core modules depend on. Concrete implementations
(``PackageResourceSchemaRegistry``, ``JsonSchemaContractValidator``,
``JsonSchemaEventValidator``) are **intentionally not re-exported here** — they
must be imported from their submodules by the composition root only, so
``core/`` cannot accidentally depend on a concrete adapter (see
``docs/roadmap/project-structure.md § Customization via Dependency Injection``).
"""

from .models import (
    Action,
    ActionInterface,
    BlastRadius,
    BlastRadiusScope,
    Category,
    CheckLogic,
    CheckLogicKind,
    Decision,
    Event,
    IdempotencyKey,
    LinkCardinality,
    Mode,
    OntologyActionType,
    OntologyLinkType,
    OntologyObjectType,
    Operation,
    PropertyDecl,
    PropertyType,
    Provenance,
    Remediation,
    RollbackKind,
    RollbackRef,
    Rule,
    RuleSource,
    SemVer,
    Severity,
    Tier,
)
from .registry import SchemaNotFoundError, SchemaRegistry
from .validation import (
    ContractValidationError,
    ContractValidator,
    EventValidator,
    ValidationIssue,
)

__all__ = [
    # data — enums
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
    # data — aliases
    "IdempotencyKey",
    "SemVer",
    # data — models
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
    # DI seams (Protocols only — no concretes)
    "ContractValidator",
    "EventValidator",
    "SchemaRegistry",
    # error types
    "ContractValidationError",
    "SchemaNotFoundError",
    "ValidationIssue",
]
