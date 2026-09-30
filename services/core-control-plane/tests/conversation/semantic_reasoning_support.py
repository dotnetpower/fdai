"""Shared fixtures for ontology reasoning compiler tests.

The production manifest comes from the reviewed rule catalog, and the fixture
graph uses generic, customer-free names.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from fdai.composition.semantic_query_instance_candidates import declare_instance_candidate_query
from fdai.composition.semantic_query_value_domains import (
    incident_lifecycle_value_domains,
    resource_location_value_domains,
    resource_type_value_domains,
)
from fdai.core.conversation.semantic_reasoning_admission import (
    FormAdmission,
    SpanAccounting,
    admit_question_form,
)
from fdai.core.conversation.semantic_reasoning_binding import (
    AnchorBinding,
    AnchorBindingReceipt,
    AnchorOutcome,
    GatewayAnchorResolver,
    anchor_mentions,
    bind_anchors,
)
from fdai.core.conversation.semantic_reasoning_concepts import (
    ConceptBinding,
    ConceptOutcome,
    ConceptSelectionReceipt,
)
from fdai.core.conversation.semantic_reasoning_form import (
    MentionDomain,
    SemanticQuestionForm,
)
from fdai.core.ontology_platform import (
    AggregateNodeHandler,
    OntologyQueryPlanExecutor,
    OntologyQueryPlanVerifier,
    QueryManifest,
    SetOperationNodeHandler,
)
from fdai.core.ontology_platform.interfaces import compile_interfaces
from fdai.core.ontology_platform.object_sets import ObjectSetService
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.core.ontology_platform.query_manifest import build_query_manifest
from fdai.core.ontology_platform.query_source_handlers import (
    SecuredObjectSetNodeHandler,
    SecuredRelationshipTraversalNodeHandler,
)
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog, load_ontology_catalog
from fdai.rule_catalog.schema.provider_region import load_provider_region_registry_from_mapping
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore
from fdai_service_contracts.ontology_query import OntologyQueryPlan, QueryNodeKind

ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)
PURPOSE = "operations-review"
DEFAULT_LOOKBACK_SECONDS = 86_400
RESOURCE = "Resource"

# (id, name, type, parent) for a generic two-group topology with a shared name prefix.
FIXTURE_RESOURCES: tuple[tuple[str, str, str, str | None], ...] = (
    ("sub-1", "sub-example", "subscription", None),
    ("rg-1", "rg-app", "resource-group", "sub-1"),
    ("rg-2", "rg-app-dev", "resource-group", "sub-1"),
    ("aks-1", "aks-prod-01", "kubernetes-cluster", "rg-1"),
    ("vnet-1", "vnet-app", "network.vnet", "rg-1"),
    ("snet-1", "snet-app", "network.subnet", "vnet-1"),
    ("vm-1", "vm-app-01", "compute.vm", "rg-1"),
    ("sql-1", "sql-app", "sql-database", "rg-1"),
    ("kv-1", "kv-app", "secret-store", "rg-1"),
    ("ra-1", "ra-app-reader", "authorization.role-assignment", "rg-1"),
    ("vm-2", "vm-app-dev-01", "compute.vm", "rg-2"),
    ("vnet-2", "vnet-hub", "network.vnet", "rg-2"),
    ("agw-1", "agw-app", "network.application-gateway", "rg-2"),
)
FIXTURE_LINKS: tuple[tuple[str, str, str], ...] = (
    *(
        (parent, "contains", identity)
        for identity, _name, _type, parent in FIXTURE_RESOURCES
        if parent is not None
    ),
    ("vm-1", "depends_on", "sql-1"),
    ("aks-1", "depends_on", "kv-1"),
    ("aks-1", "depends_on", "sql-1"),
    ("vnet-1", "peered_with", "vnet-2"),
    ("agw-1", "routes_to", "aks-1"),
)


@lru_cache(maxsize=1)
def production_catalog() -> OntologyCatalog:
    root = ROOT / "rule-catalog"
    return declare_instance_candidate_query(
        load_ontology_catalog(
            root,
            schema_registry=PackageResourceSchemaRegistry(),
            probes_root=root / "probes" if (root / "probes").is_dir() else None,
        )
    )


@lru_cache(maxsize=2)
def production_manifest(
    role: CeilingRole = CeilingRole.READER,
    *,
    metric_labels: tuple[tuple[str, str], ...] = (),
    health_labels: tuple[tuple[str, tuple[str, ...]], ...] = (),
    unbound: tuple[str, ...] = (),
) -> QueryManifest:
    catalog = production_catalog()
    functions = operational_function_types(catalog.function_types)
    release = build_ontology_release(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        action_types=catalog.action_types,
        interface_types=catalog.interface_types,
        function_types=functions,
    )
    registry = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml").read_text(
                encoding="utf-8"
            )
        )
    )
    return build_query_manifest(
        release=release,
        principal_role=role,
        purposes=(PURPOSE,),
        principal_scope_digest="sha256:" + "a" * 64,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        interfaces=catalog.interface_types,
        action_types=catalog.action_types,
        functions=functions,
        bound_function_names=tuple(
            function.name for function in functions if function.name not in unbound
        ),
        metric_labels=dict(metric_labels),
        health_labels=dict(health_labels),
        property_values=(
            *resource_type_value_domains(registry),
            *resource_location_value_domains(
                load_provider_region_registry_from_mapping(
                    yaml.safe_load(
                        (ROOT / "rule-catalog" / "vocabulary" / "provider-regions.yaml").read_text(
                            encoding="utf-8"
                        )
                    )
                )
            ),
            *incident_lifecycle_value_domains(),
        ),
    )


def plan_verifier() -> OntologyQueryPlanVerifier:
    return OntologyQueryPlanVerifier(
        available_kinds=(
            QueryNodeKind.OBJECT_SET,
            QueryNodeKind.RELATIONSHIP_TRAVERSAL,
            QueryNodeKind.TYPED_PATH,
            QueryNodeKind.ONTOLOGY_INSTANCE_PATH,
            QueryNodeKind.FUNCTION,
            QueryNodeKind.UNION,
            QueryNodeKind.AGGREGATE,
        )
    )


def admitted(
    form: dict[str, Any] | SemanticQuestionForm,
    utterance: str,
    *,
    account_spans: bool = False,
) -> FormAdmission:
    """Admit a hand-built form; word accounting is off unless a test checks it."""

    parsed = (
        form
        if isinstance(form, SemanticQuestionForm)
        else SemanticQuestionForm.model_validate(form)
    )
    return admit_question_form(
        parsed, utterance=utterance, accounting=SpanAccounting(required=account_spans)
    )


def concepts(*bindings: tuple[str, MentionDomain, tuple[str, ...]]) -> ConceptSelectionReceipt:
    """Return an accepted concept receipt, as a completed shard selection would."""

    return ConceptSelectionReceipt(
        bindings=tuple(
            ConceptBinding(
                mention_id,
                domain,
                ConceptOutcome.ACCEPTED,
                candidate_ids=tuple(f"value:{value}" for value in values),
                values=values,
            )
            for mention_id, domain, values in bindings
        )
    )


def span(utterance: str, text: str) -> dict[str, int]:
    start = utterance.index(text)
    return {"start": start, "end": start + len(text)}


async def fixture_gateway() -> SecuredObjectSetQueryGateway:
    catalog = production_catalog()
    resource = next(item for item in catalog.object_types if item.name == RESOURCE)
    links = tuple(
        item
        for item in catalog.link_types
        if item.from_type == RESOURCE and item.to_type == RESOURCE
    )
    store = InMemoryOntologyInstanceStore(
        object_types=(resource,),
        link_types=links,
        source_complete=True,
        source_generation="fixture-generation",
    )
    for identity, name, resource_type, parent in FIXTURE_RESOURCES:
        properties: dict[str, Any] = {"id": identity, "name": name, "type": resource_type}
        if parent is not None:
            properties["parent_id"] = _provider_path(parent)
        await store.upsert_object(
            OntologyObjectRecord(id=identity, object_type="Resource", properties=properties)
        )
    for source, link_type, target in FIXTURE_LINKS:
        await store.upsert_link(
            OntologyLinkRecord(from_id=source, link_type=link_type, to_id=target)
        )
    service = ObjectSetService(
        store=store,
        interfaces=compile_interfaces(interfaces=(), implementations=(), object_types=(resource,)),
        object_type_names=frozenset({resource.name}),
    )
    return SecuredObjectSetQueryGateway(
        service=service,
        object_types={resource.name: resource},
        ontology_release=build_ontology_release(object_types=(resource,), link_types=links),
        evaluation_cutoff=lambda: NOW,
        graph_completeness=_complete,
        max_as_of_skew=timedelta(seconds=5),
    )


async def _complete() -> bool:
    return True


def _provider_path(identity: str) -> str:
    """Return a provider-style parent path, so group names share textual prefixes."""

    by_id = {item[0]: item for item in FIXTURE_RESOURCES}
    segments: list[str] = []
    current: str | None = identity
    while current is not None:
        _identity, name, _type, parent = by_id[current]
        segments.append(name)
        current = parent
    return "/" + "/".join(reversed(segments))


async def execute(plan: OntologyQueryPlan, gateway: SecuredObjectSetQueryGateway) -> Any:
    """Execute one ObjectSet, traversal, union, and count plan on the fixture graph."""

    handler_args: dict[str, Any] = {"caller_role": CeilingRole.READER, "purposes": (PURPOSE,)}
    executor = OntologyQueryPlanExecutor(
        handlers={
            QueryNodeKind.OBJECT_SET: SecuredObjectSetNodeHandler(gateway, **handler_args),
            QueryNodeKind.RELATIONSHIP_TRAVERSAL: SecuredRelationshipTraversalNodeHandler(
                gateway, **handler_args
            ),
            QueryNodeKind.UNION: SetOperationNodeHandler("union"),
            QueryNodeKind.AGGREGATE: AggregateNodeHandler(),
        },
        now=lambda: NOW,
    )
    return await executor.execute(
        plan,
        expected_release_digest=plan.ontology_release_digest,
        expected_manifest_digest=plan.semantic_catalog_digest,
        expected_role=plan.caller_role,
        expected_purpose=plan.purpose,
    )


def names(execution: Any, node_id: str) -> set[str]:
    """Return the Resource names of one completed table node."""

    table = execution.results[node_id].value
    return {row.values["properties"]["name"] for row in table.rows}


def synthetic_anchors(admission: FormAdmission) -> AnchorBindingReceipt:
    """Bind every anchor to a synthetic identity for compile-shape tests."""

    return AnchorBindingReceipt(
        tuple(
            AnchorBinding(item, AnchorOutcome.BOUND, object_id=f"object-{item}")
            for item in anchor_mentions(admission)
        )
    )


async def fixture_anchors(admission: FormAdmission) -> AnchorBindingReceipt:
    """Bind anchors by exact reads of the fixture graph, as the shadow runner does."""

    resolver = GatewayAnchorResolver(
        await fixture_gateway(),
        projection_request=ProjectionRequest(
            caller_role=CeilingRole.READER, declared_purposes=frozenset({PURPOSE})
        ),
        purpose=PURPOSE,
        as_of=NOW,
    )
    return await bind_anchors(admission, resolver)
