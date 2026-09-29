"""Stated catalog values ground judgment evidence and hold contradictory schema meaning."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from fdai.composition.semantic_query_value_domains import resource_type_value_domains
from fdai.core.conversation import semantic_planning_judgment
from fdai.core.conversation.semantic_catalog_value_mentions import stated_catalog_values
from fdai.core.conversation.semantic_manifest_planning import manifest_catalog_value_conflict
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_judgment import _semantic_judgment_capabilities
from fdai.core.conversation.semantic_planning_models import (
    ClarificationRequirement,
    SemanticPlanningDisposition,
)
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import OntologyQueryPlanVerifier, build_query_manifest
from fdai.core.ontology_platform.manifest_queries import ontology_manifest_function_type
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.core.ontology_platform.property_values import PropertyValueDomain, PropertyValueGroup
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release
from fdai_service_contracts.ontology_query import QueryNodeKind
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

ROOT = Path(__file__).resolve().parents[4]
DIGEST = "sha256:" + "c" * 64
NOW = datetime(2026, 9, 27, tzinfo=UTC)
_AKS = PropertyValueGroup(
    id="kubernetes-cluster",
    values=("kubernetes-cluster",),
    terms=("aks", "kubernetes cluster", "클러스터"),
)
_VM = PropertyValueGroup(id="compute.vm", values=("compute.vm",), terms=("vm", "vms"))


def _manifest(*, role: CeilingRole = CeilingRole.READER) -> Any:
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "type": PropertyDecl(type=PropertyType.STRING, required=True),
            "name": PropertyDecl(type=PropertyType.STRING),
        },
    )
    functions = (ontology_manifest_function_type(),)
    release = build_ontology_release(object_types=(resource,), function_types=functions)
    return build_query_manifest(
        release=release,
        principal_role=role,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(resource,),
        functions=functions,
        bound_function_names=tuple(function.name for function in functions),
        property_values=(
            PropertyValueDomain(
                object_type="Resource",
                property_name="type",
                values=("compute.vm", "kubernetes-cluster"),
                groups=(_AKS, _VM),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("utterance", "text", "span"),
    (
        ("aks 목록을 보여줘", "aks", (0, 3)),
        ("Show me the AKS clusters", "AKS", (12, 15)),
        ("쿠버네티스 클러스터를 보여줘", "클러스터", (6, 10)),
    ),
)
def test_stated_value_reports_exact_source_span(
    utterance: str,
    text: str,
    span: tuple[int, int],
) -> None:
    (stated,) = stated_catalog_values(utterance, _manifest().descriptors)

    assert (stated.text, stated.source_start, stated.source_end) == (text, *span)
    assert utterance[stated.source_start : stated.source_end] == text
    assert stated.values == ("kubernetes-cluster",)
    assert stated.capability_hint() == {
        "property": "Resource.type",
        "text": text,
        "source_start": span[0],
        "source_end": span[1],
        "values": ["kubernetes-cluster"],
    }


@pytest.mark.parametrize(
    "utterance",
    (
        "aks-prod-cluster 상태 알려줘",
        "Check aks_node now",
        "List vm and aks resources",
        "What object types can I read?",
        "Straße aks 목록",
    ),
)
def test_identifiers_ambiguity_and_unmapped_text_state_no_value(utterance: str) -> None:
    assert stated_catalog_values(utterance, _manifest().descriptors) == ()


def test_capabilities_carry_stated_values_only_for_an_utterance() -> None:
    descriptors = tuple(_manifest().descriptors)

    plain = _semantic_judgment_capabilities(descriptors)
    enriched = _semantic_judgment_capabilities(descriptors, utterance="aks 목록을 보여줘")

    assert [item["name"] for item in enriched] == [item["name"] for item in plain]
    resource = next(item for item in enriched if item["name"] == "Resource")
    assert resource["stated_values"] == [
        {
            "property": "Resource.type",
            "text": "aks",
            "source_start": 0,
            "source_end": 3,
            "values": ["kubernetes-cluster"],
        }
    ]
    assert all("stated_values" not in item for item in plain)


def test_capability_hints_never_displace_a_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    descriptors = tuple(_manifest().descriptors)
    plain = _semantic_judgment_capabilities(descriptors)
    plain_bytes = len(
        json.dumps(plain, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    )
    monkeypatch.setattr(semantic_planning_judgment, "_MAX_JUDGMENT_CAPABILITY_BYTES", plain_bytes)

    bounded = _semantic_judgment_capabilities(descriptors, utterance="aks 목록을 보여줘")

    assert bounded == plain


class _ManifestProvider:
    def __init__(self, manifest: Any) -> None:
        self.manifest = manifest

    def manifest_for(self, *, principal: Principal, purpose: str) -> Any:
        assert principal.role is Role.READER
        assert purpose == "operations-review"
        return self.manifest


class _Model:
    def __init__(self) -> None:
        self.frame_calls = 0
        self.plan_calls = 0

    def propose_frame(self, **_kwargs: Any) -> None:
        self.frame_calls += 1

    def propose_plan(self, **_kwargs: Any) -> None:
        self.plan_calls += 1


class _Judgment:
    def __init__(self, proposal: SemanticJudgmentProposal) -> None:
        self.proposal = proposal
        self.capabilities: tuple[dict[str, Any], ...] = ()

    def preflight(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(observations=(), attempted=False, failure_kind=None, proposal=None)

    def judge(self, **kwargs: Any) -> Any:
        self.capabilities = tuple(kwargs["capabilities"])
        return SimpleNamespace(
            accepted=True,
            observations=(),
            proposal=self.proposal,
            receipt=SimpleNamespace(
                disposition=SimpleNamespace(value="accepted"),
                tier=SimpleNamespace(value="t1"),
            ),
        )


def _manifest_list(**updates: Any) -> SemanticJudgmentProposal:
    return SemanticJudgmentProposal(
        primary_intent="query.manifest",
        requested_facets=("readable", "object_types"),
        confidence=0.96,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
    ).model_copy(update=updates)


def _plan(utterance: str, judgment: _Judgment, *, locale: str) -> tuple[Any, _Model]:
    model = _Model()
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(_manifest()),
        verifier=OntologyQueryPlanVerifier(
            available_kinds=(QueryNodeKind.OBJECT_SET, QueryNodeKind.FUNCTION)
        ),
        now=lambda: NOW,
        semantic_judgment=judgment,
    )
    outcome = service.plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        locale=locale,
    )
    return outcome, model


@pytest.mark.parametrize(
    ("utterance", "locale", "expected"),
    (
        ("aks 목록을 보여줘", "ko", "카탈로그 리소스 유형 `kubernetes-cluster`(요청의 `aks`)"),
        ("Show me the AKS clusters", "en", "catalog type `kubernetes-cluster` (from `AKS`)"),
    ),
)
def test_targetless_manifest_meaning_with_a_stated_subtype_is_held(
    utterance: str,
    locale: str,
    expected: str,
) -> None:
    judgment = _Judgment(_manifest_list())

    outcome, model = _plan(utterance, judgment, locale=locale)

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.reason == "semantic_clarification_required"
    assert outcome.plan is None
    assert outcome.clarification is not None and expected in outcome.clarification
    assert outcome.clarification.endswith("?")
    assert outcome.frame is not None and outcome.frame.output_shape == "ontology_manifest"
    assert outcome.frame.unresolved_terms == ("subject_kind",)
    assert model.frame_calls == model.plan_calls == 0
    resource = next(item for item in judgment.capabilities if item["name"] == "Resource")
    assert resource["stated_values"][0]["values"] == ["kubernetes-cluster"]


def test_declaration_list_without_a_stated_subtype_still_plans() -> None:
    outcome, model = _plan(
        "What object types can I read?", _Judgment(_manifest_list()), locale="en"
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None and outcome.frame.output_shape == "ontology_manifest"
    assert model.frame_calls == model.plan_calls == 0


@pytest.mark.parametrize(
    "updates",
    (
        {"secondary_intents": ("query.contextual_resources",)},
        {"ambiguous": True, "unresolved_terms": ("subject",), "clarification": "Which one?"},
        {"primary_intent": "query.contextual_resources"},
    ),
)
def test_conflict_hold_requires_one_complete_targetless_schema_meaning(
    updates: dict[str, Any],
) -> None:
    assert (
        manifest_catalog_value_conflict(
            _manifest_list(**updates),
            judgment_accepted=True,
            utterance="aks 목록을 보여줘",
            context=(),
            descriptors=tuple(_manifest().descriptors),
            locale="ko",
        )
        is None
    )


def test_conflict_hold_requires_accepted_meaning() -> None:
    assert (
        manifest_catalog_value_conflict(
            _manifest_list(),
            judgment_accepted=False,
            utterance="aks 목록을 보여줘",
            context=(),
            descriptors=tuple(_manifest().descriptors),
            locale="ko",
        )
        is None
    )


def test_conflict_hold_uses_a_typed_subject_requirement() -> None:
    held = manifest_catalog_value_conflict(
        _manifest_list(requested_facets=("object_type_count",)),
        judgment_accepted=True,
        utterance="aks 몇 개야?",
        context=(),
        descriptors=tuple(_manifest().descriptors),
        locale="ko",
    )

    assert held is not None
    proposal, _frame = held
    assert proposal.clarification_requirements == (ClarificationRequirement.SUBJECT,)


@pytest.fixture(scope="module")
def catalog_descriptors() -> tuple[dict[str, Any], ...]:
    catalog = load_ontology_catalog(
        ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
    )
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
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        interfaces=catalog.interface_types,
        action_types=catalog.action_types,
        functions=functions,
        bound_function_names=tuple(function.name for function in functions),
        property_values=resource_type_value_domains(registry),
    )
    return tuple(manifest.descriptors)


@pytest.mark.parametrize(
    ("utterance", "values"),
    (
        ("aks 목록을 보여줘", ("kubernetes-cluster",)),
        ("AKS 클러스터 목록", ("kubernetes-cluster",)),
        ("List the virtual machines", ("compute.vm",)),
        ("스토리지 계정 목록 보여줘", ("object-storage",)),
        ("읽을 수 있는 ObjectType 목록을 보여줘", ()),
        ("What object types can I read?", ()),
        ("List the readable link types", ()),
        ("내가 조회할 수 있는 객체 유형 목록", ()),
        ("aks-prod-cluster 상태 알려줘", ()),
    ),
)
def test_catalog_vocabulary_binds_subtypes_but_not_declaration_lists(
    catalog_descriptors: tuple[dict[str, Any], ...],
    utterance: str,
    values: tuple[str, ...],
) -> None:
    stated = stated_catalog_values(utterance, catalog_descriptors)

    assert tuple(value for item in stated for value in item.values) == values


def test_typed_only_never_holds_a_read_on_a_catalog_value_found_among_the_words() -> None:
    from fdai.core.conversation.semantic_planning_frame_checks import (
        deterministic_pre_frame_outcome,
    )

    def outcome(typed_only: bool) -> Any:
        return deterministic_pre_frame_outcome(
            judgment=_manifest_list(),
            utterance="aks 목록을 보여줘",
            context=(),
            descriptors=tuple(_manifest().descriptors),
            manifest_digest=_manifest().manifest_digest,
            bound_incident=False,
            judgment_accepted=True,
            locale="ko",
            typed_only=typed_only,
        )

    held = outcome(False)
    assert held is not None and held.disposition is SemanticPlanningDisposition.CLARIFICATION
    # Only a typed reading decides what a read states, so the word-matching gate stays closed.
    assert outcome(True) is None
