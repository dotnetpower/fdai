"""Typed operational ontology platform primitives."""

from .catalog_projection import (
    CatalogOntologyProjection,
    CatalogOntologyProjector,
    build_catalog_ontology_projection,
)
from .functions import (
    FunctionInvocationContext,
    FunctionInvocationReceipt,
    OntologyFunction,
    OntologyFunctionRegistry,
)
from .interfaces import CompiledInterfaceCatalog, compile_interfaces
from .introspection import platform_manifest
from .kinetics import (
    AuthorityClass,
    CriterionResult,
    MutationEffect,
    MutationEffectKind,
    MutationPlan,
    OntologyFunctionKind,
    OntologyFunctionType,
    ProjectionBinding,
    ReconciliationReceipt,
    ReconciliationStatus,
    TargetRevision,
)
from .models import (
    InterfaceImplementation,
    ObjectPredicate,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
    ObjectTraversal,
    OntologyInterfaceType,
)
from .object_sets import ObjectSetService
from .planning import build_mutation_plan, validate_plan_revisions
from .projection import project_source_records, reconcile_expected_effects
from .sdk_codegen import GeneratedOntologySdk, generate_ontology_sdk

__all__ = [
    "CatalogOntologyProjection",
    "CatalogOntologyProjector",
    "CompiledInterfaceCatalog",
    "AuthorityClass",
    "CriterionResult",
    "GeneratedOntologySdk",
    "FunctionInvocationContext",
    "FunctionInvocationReceipt",
    "InterfaceImplementation",
    "ObjectPredicate",
    "ObjectSelector",
    "ObjectSelectorKind",
    "ObjectSetDefinition",
    "ObjectSetMaterialization",
    "ObjectSetService",
    "ObjectTraversal",
    "MutationEffect",
    "MutationEffectKind",
    "MutationPlan",
    "OntologyFunction",
    "OntologyFunctionKind",
    "OntologyFunctionRegistry",
    "OntologyFunctionType",
    "OntologyInterfaceType",
    "ProjectionBinding",
    "ReconciliationReceipt",
    "ReconciliationStatus",
    "TargetRevision",
    "build_mutation_plan",
    "build_catalog_ontology_projection",
    "compile_interfaces",
    "generate_ontology_sdk",
    "platform_manifest",
    "project_source_records",
    "reconcile_expected_effects",
    "validate_plan_revisions",
]
