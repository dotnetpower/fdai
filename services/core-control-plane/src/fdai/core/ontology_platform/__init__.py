"""Typed operational ontology platform primitives."""

from .action_plans import compile_action_mutation_plan, validate_action_plan_semantics
from .catalog_projection import (
    CatalogOntologyProjection,
    CatalogOntologyProjector,
    build_catalog_ontology_projection,
    merge_catalog_ontology_projections,
)
from .functions import (
    ContextualOntologyFunction,
    FunctionInvocationContext,
    FunctionInvocationReceipt,
    OntologyFunction,
    OntologyFunctionRegistry,
    ontology_function_digest,
)
from .interfaces import CompiledInterfaceCatalog, compile_interfaces
from .introspection import platform_manifest
from .kinetics import (
    ActionArgumentBinding,
    ActionReadSetReceipt,
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
    ObjectPredicateOperator,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
    ObjectSetTruncationReason,
    ObjectTraversal,
    OntologyInterfaceType,
)
from .object_sets import ObjectSetService
from .planning import build_mutation_plan, validate_plan_revisions
from .projection import project_source_records, reconcile_expected_effects
from .query_execution import (
    ObjectSetNodeHandler,
    OntologyQueryPlanExecutor,
    QueryNodeHandler,
    QueryNodeResult,
    QueryPlanExecution,
)
from .query_handlers import (
    AggregateNodeHandler,
    OrderNodeHandler,
    ProjectNodeHandler,
    SetOperationNodeHandler,
)
from .query_manifest import QueryManifest, build_query_manifest
from .query_source_handlers import FunctionNodeHandler, SecuredObjectSetNodeHandler
from .query_values import QueryRow, QueryTable
from .query_verification import OntologyQueryPlanVerifier
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
    "ActionArgumentBinding",
    "ActionReadSetReceipt",
    "ActiveSemanticCatalog",
    "AggregateNodeHandler",
    "CatalogOntologyProjection",
    "CatalogOntologyProjector",
    "CompiledInterfaceCatalog",
    "AuthorityClass",
    "CriterionResult",
    "ContextualOntologyFunction",
    "GeneratedOntologySdk",
    "FunctionInvocationContext",
    "FunctionInvocationReceipt",
    "FunctionNodeHandler",
    "InterfaceImplementation",
    "InterpretationCandidateSource",
    "ObjectPredicate",
    "ObjectPredicateOperator",
    "ObjectSelector",
    "ObjectSelectorKind",
    "ObjectSetDefinition",
    "ObjectSetNodeHandler",
    "ObjectSetMaterialization",
    "ObjectSetTruncationReason",
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
    "OntologyQueryPlanExecutor",
    "OntologyQueryPlanVerifier",
    "OrderNodeHandler",
    "ProjectionBinding",
    "ProjectNodeHandler",
    "QueryManifest",
    "QueryNodeHandler",
    "QueryNodeResult",
    "QueryPlanExecution",
    "QueryRow",
    "QueryTable",
    "ReconciliationReceipt",
    "ReconciliationStatus",
    "SemanticBasisValidator",
    "SemanticInterpretationCandidate",
    "SemanticOperationClass",
    "SecuredObjectSetNodeHandler",
    "SetOperationNodeHandler",
    "TargetRevision",
    "VerifiedInterpretationBasis",
    "VerifiedSemanticPlan",
    "build_mutation_plan",
    "build_query_manifest",
    "compile_action_mutation_plan",
    "build_semantic_candidate",
    "build_catalog_ontology_projection",
    "merge_catalog_ontology_projections",
    "compile_interfaces",
    "generate_ontology_sdk",
    "platform_manifest",
    "project_source_records",
    "reconcile_expected_effects",
    "validate_plan_revisions",
    "validate_action_plan_semantics",
    "verify_semantic_candidate",
]
