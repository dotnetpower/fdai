"""Typed operational ontology platform primitives."""

from .catalog_projection import (
    CatalogOntologyProjection,
    CatalogOntologyProjector,
    build_catalog_ontology_projection,
    merge_catalog_ontology_projections,
)
from .functions import (
    FunctionInvocationContext,
    FunctionInvocationReceipt,
    OntologyFunction,
    OntologyFunctionRegistry,
    ontology_function_digest,
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
from .semantic_plans import (
    ActiveSemanticCatalog,
    InterpretationCandidateSource,
    SemanticBasisValidator,
    SemanticInterpretationCandidate,
    SemanticOperationClass,
    VerifiedInterpretationBasis,
    VerifiedSemanticPlan,
    build_semantic_candidate,
    verify_semantic_candidate,
)

__all__ = [
    "ActiveSemanticCatalog",
    "CatalogOntologyProjection",
    "CatalogOntologyProjector",
    "CompiledInterfaceCatalog",
    "AuthorityClass",
    "CriterionResult",
    "GeneratedOntologySdk",
    "FunctionInvocationContext",
    "FunctionInvocationReceipt",
    "InterfaceImplementation",
    "InterpretationCandidateSource",
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
    "ontology_function_digest",
    "OntologyFunctionType",
    "OntologyInterfaceType",
    "ProjectionBinding",
    "ReconciliationReceipt",
    "ReconciliationStatus",
    "SemanticBasisValidator",
    "SemanticInterpretationCandidate",
    "SemanticOperationClass",
    "TargetRevision",
    "VerifiedInterpretationBasis",
    "VerifiedSemanticPlan",
    "build_mutation_plan",
    "build_semantic_candidate",
    "build_catalog_ontology_projection",
    "merge_catalog_ontology_projections",
    "compile_interfaces",
    "generate_ontology_sdk",
    "platform_manifest",
    "project_source_records",
    "reconcile_expected_effects",
    "validate_plan_revisions",
    "verify_semantic_candidate",
]
