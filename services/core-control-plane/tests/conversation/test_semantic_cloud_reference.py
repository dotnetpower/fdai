"""Source-grounded cloud conditions use the real planner without a live model or source fetch."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest
from fdai.core.conversation.semantic_cloud_reference import cloud_reference_constraints
from fdai.core.conversation.semantic_governed_document_planning import (
    apply_document_evidence_requirement,
    compile_governed_document_plan,
)
from fdai.core.ontology_platform import OntologyQueryPlanVerifier
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.governed_document_queries import (
    governed_document_function,
    governed_document_function_type,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release
from fdai_service_contracts.cloud_knowledge import Applicability
from fdai_service_contracts.ontology_query import QueryNodeKind
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal, SemanticTarget


def _helpers(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("_cloud_semantic_" + path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PLANNING = _helpers(Path(__file__).with_name("test_semantic_governed_document_planning.py"))
QUERY = _helpers(
    Path(__file__).parents[1] / "core/ontology_platform/test_governed_document_queries.py"
)


def _judgment(utterance: str, mode: str) -> SemanticJudgmentProposal:
    targets = []
    for kind, value in (
        ("cloud_provider", "azure"),
        ("cloud_resource_type", "Microsoft.ApiManagement/service"),
        ("cloud_generation", "classic"),
        ("cloud_sku", "Premium"),
    ):
        start = utterance.index(value)
        targets.append(
            SemanticTarget(
                kind=kind,
                value=value,
                source_start=start,
                source_end=start + len(value),
            )
        )
    return SemanticJudgmentProposal(
        primary_intent="query.governed_documents",
        targets=tuple(targets),
        requested_facets=(mode,),
        confidence=0.99,
        ambiguous=False,
        document_evidence_mode="explicit",
        action_subject="none",
    )


@pytest.mark.parametrize("korean", [False, True])
@pytest.mark.parametrize("mode", ["cloud_as_of", "cloud_current"])
def test_existing_typed_judgment_becomes_exact_applicability_query(korean: bool, mode: str) -> None:
    utterance = (
        "azure Microsoft.ApiManagement/service classic Premium 원본 문서로 설명해 주세요."
        if korean
        else "Explain azure Microsoft.ApiManagement/service classic Premium from source documents."
    )
    proposal = PLANNING._proposal()
    frame = PLANNING.build_semantic_frame(proposal, utterance=utterance, context=())
    _, frame = apply_document_evidence_requirement(
        proposal,
        frame,
        judgment=_judgment(utterance, mode),
        utterance=utterance,
        context=(),
    )
    plan = compile_governed_document_plan(
        frame=frame,
        utterance=utterance,
        manifest=PLANNING._manifest(),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
        purpose="operations-review",
    )
    assert plan is not None and not plan.execution_authority
    arguments = plan.nodes[0].arguments["arguments"]
    assert arguments["guidance_mode"] == mode.removeprefix("cloud_")
    target = Applicability.model_validate(arguments["applicability"])
    assert target.skus == ("Premium",) and target.service_generation == "classic"
    assert target.api_versions == () and target.regions == ()


def test_unspanned_target_or_fabricated_alias_never_becomes_a_filter() -> None:
    utterance = "azure Microsoft.ApiManagement/service classic Premium"
    judgment = _judgment(utterance, "cloud_as_of")
    for replacement in (
        {"source_start": 1},
        {"canonical_value": "other"},
        {"value": "invented"},
    ):
        altered = judgment.model_copy(
            update={
                "targets": (
                    judgment.targets[0].model_copy(update=replacement),
                    *judgment.targets[1:],
                )
            }
        )
        with pytest.raises(ValueError, match="current-turn"):
            cloud_reference_constraints(altered, utterance=utterance)


class _BoundReader(QUERY._Reader):
    async def search(self, *, target=None, **kwargs):
        self.target = target
        return await super().search(**kwargs)


async def _invoke(reader, arguments):
    declaration = governed_document_function_type()
    release = build_ontology_release(function_types=(declaration,))
    handler = governed_document_function(release, reader=reader)
    return await handler(
        arguments,
        FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
            principal_ref="synthetic-reader",
            principal_scope_digest=PLANNING.DIGEST,
        ),
    )


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("as_of", "cloud_applicability_required"),
        ("current", "cloud_source_observation_required"),
    ],
)
async def test_current_or_unqualified_guidance_is_terminal_without_a_read(mode, reason) -> None:
    reader = _BoundReader(QUERY._collection())
    result = await _invoke(
        reader,
        {
            "query": "reference",
            "evidence_mode": "explicit",
            "guidance_mode": mode,
        },
    )
    assert reader.calls == []
    assert result["complete"] is False and result["truncation_reason"] == reason
    assert result["rows"][0]["values"]["excerpt_count"] == 0


async def test_as_of_request_never_substitutes_an_ordinary_document_for_cloud_evidence() -> None:
    reader = _BoundReader(QUERY._collection(excerpts=(QUERY._excerpt(),)))
    target = Applicability(resource_type="network", service_generation="v1")
    result = await _invoke(
        reader,
        {
            "query": "reference",
            "evidence_mode": "explicit",
            "guidance_mode": "as_of",
            "applicability": target.model_dump(mode="json"),
        },
    )
    assert reader.target == target
    assert result["rows"][0]["values"]["excerpt_count"] == 0
    assert result["truncation_reason"] == "cloud_source_refresh_required"


@pytest.mark.parametrize("fresh", [False, True])
async def test_as_of_requires_fresh_matching_cloud_evidence(fresh: bool) -> None:
    reference = _helpers(Path(__file__).parents[1] / "core/knowledge/test_cloud_reference.py")
    source = reference._source(reference.NOW)
    excerpt = replace(
        QUERY._excerpt(),
        cloud_source=source,
        cloud_status="fresh" if fresh else "stale",
        applicability_verified=True,
    )
    reader = _BoundReader(QUERY._collection(excerpts=(excerpt,)))
    result = await _invoke(
        reader,
        {
            "query": "reference",
            "evidence_mode": "explicit",
            "guidance_mode": "as_of",
            "applicability": source.applicability.model_dump(mode="json"),
        },
    )
    assert result["rows"][0]["values"]["excerpt_count"] == int(fresh)
    if fresh:
        assert result["rows"][1]["values"]["current_guidance_eligible"] is True
