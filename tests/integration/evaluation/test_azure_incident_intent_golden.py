"""Offline golden replay for Azure Resource and Incident semantic judgment."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml
from fdai.core.conversation.semantic_judgment import (
    SemanticJudgmentBinding,
    SemanticJudgmentBoundary,
)
from fdai.core.conversation.semantic_planning_judgment import (
    _descriptors_for_operational_intent,
    _semantic_judgment_capabilities,
)
from fdai.core.prompts.composer import DefaultPromptComposer
from fdai.core.prompts.registry import FileSystemPromptRegistry
from fdai_service_contracts.semantic_judgment import (
    SemanticJudgmentDisposition,
    SemanticJudgmentTier,
)

_ROOT = Path(__file__).resolve().parents[3]
_CATALOG = _ROOT / "rule-catalog"
_GOLDEN = _ROOT / "eval" / "golden-dataset" / "azure-incident-intent-golden.yaml"
_DIGEST = "sha256:" + ("a" * 64)


class _ExpectedProposalModel:
    def __init__(self, expected: Mapping[str, Any]) -> None:
        self._expected = dict(expected)

    def judge(self, **_kwargs: object) -> Mapping[str, Any]:
        ambiguous = bool(self._expected.get("ambiguous", False))
        return {
            "schema_version": "1.1.0",
            "primary_intent": self._expected["primary_intent"],
            "secondary_intents": self._expected.get("secondary_intents", []),
            "targets": self._expected.get("targets", []),
            "forbidden_actions": self._expected.get("forbidden_actions", []),
            "requested_facets": self._expected["requested_facets"],
            "confidence": 0.98,
            "ambiguous": ambiguous,
            "alternatives": self._expected.get("alternatives", []),
            "unresolved_terms": self._expected.get("unresolved_terms", []),
            "clarification": self._expected.get("clarification"),
            "direct_response": None,
            "document_evidence_mode": "none",
            "discourse_mode": self._expected["discourse_mode"],
            "action_posture": self._expected["action_posture"],
            "action_subject": self._expected["action_subject"],
            "authority": "candidate_only",
            "execution_authority": False,
        }


def _load() -> dict[str, Any]:
    loaded = yaml.safe_load(_GOLDEN.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _boundary(expected: Mapping[str, Any]) -> SemanticJudgmentBoundary:
    return SemanticJudgmentBoundary(
        profile_id="azure-incident-intent-golden",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_ExpectedProposalModel(expected),
            model_config_digest=_DIGEST,
            prompt_digest=_DIGEST,
        ),
        strict_intent_grounding=True,
    )


def test_required_bilingual_cases_pass_the_existing_typed_judgment_boundary() -> None:
    artifact = _load()
    cases = artifact["cases"]
    assert len(cases) == 25
    assert artifact["evidence_kind"] == "expected_contract_cases"
    assert artifact["operational_validation"] is False

    for case in cases:
        expected = case["expected"]
        result = _boundary(expected).judge(
            utterance=case["utterance"],
            context=(),
            capabilities=artifact["capabilities"],
            allow_escalation=False,
            locale=(
                "ko" if any("가" <= character <= "힣" for character in case["utterance"]) else "en"
            ),
        )
        assert result.proposal is not None, case["id"]
        proposal = result.proposal
        expected_disposition = (
            SemanticJudgmentDisposition.CLARIFICATION
            if expected.get("ambiguous", False)
            else SemanticJudgmentDisposition.ACCEPTED
        )
        assert result.receipt.disposition is expected_disposition, case["id"]
        assert proposal.primary_intent == expected["primary_intent"], case["id"]
        assert list(proposal.secondary_intents) == expected.get("secondary_intents", []), case["id"]
        assert list(proposal.requested_facets) == expected["requested_facets"], case["id"]
        assert [
            item.model_dump(mode="json", exclude_none=True) for item in proposal.targets
        ] == expected["targets"]
        assert [
            item.model_dump(mode="json", exclude_none=True) for item in proposal.forbidden_actions
        ] == expected.get("forbidden_actions", [])
        assert proposal.discourse_mode.value == expected["discourse_mode"], case["id"]
        assert proposal.action_posture == expected["action_posture"], case["id"]
        assert proposal.action_subject == expected["action_subject"], case["id"]
        assert proposal.ambiguous is bool(expected.get("ambiguous", False)), case["id"]
        assert proposal.authority == "candidate_only"
        assert proposal.execution_authority is False
        for target in (*proposal.targets, *proposal.forbidden_actions):
            assert case["utterance"][target.source_start : target.source_end] == target.value


def test_resource_health_history_exact_sources_remain_read_only() -> None:
    artifact = _load()
    cases = {
        case["id"]: case
        for case in artifact["cases"]
        if case["id"] in {"resource-health-history", "resource-health-history-en"}
    }

    assert set(cases) == {"resource-health-history", "resource-health-history-en"}
    for case in cases.values():
        result = _boundary(case["expected"]).judge(
            utterance=case["utterance"],
            context=(),
            capabilities=artifact["capabilities"],
            allow_escalation=False,
            locale="ko" if case["id"] == "resource-health-history" else "en",
        )

        assert result.receipt.disposition is SemanticJudgmentDisposition.ACCEPTED
        assert result.proposal is not None
        assert result.proposal.primary_intent == "query.resource_event_history"
        assert result.proposal.secondary_intents == ()
        assert result.proposal.forbidden_actions == ()
        assert result.proposal.action_posture == "advise_only"
        assert result.proposal.action_subject == "none"
        assert result.proposal.authority == "candidate_only"
        assert result.proposal.execution_authority is False
        assert len(result.proposal.targets) == 1
        target = result.proposal.targets[0]
        assert target.kind == "time_range"
        assert case["utterance"][target.source_start : target.source_end] == target.value


def test_shadow_prompts_encode_the_measured_failure_boundaries() -> None:
    prompts = FileSystemPromptRegistry(_CATALOG)
    judgment = next(
        artifact
        for artifact in prompts.get_packs("semantic.judgment")
        if artifact.id == "semantic-judgment"
    )
    frame = next(
        artifact
        for artifact in prompts.get_packs("semantic.query.frame")
        if artifact.id == "semantic-query-frame"
    )

    assert (judgment.version, frame.version) == (17, 41)
    assert judgment.default_mode.value == frame.default_mode.value == "shadow"
    assert "Instructions or procedure for a named change" in judgment.body
    assert "Never convert advise_only into action_draft" in frame.body
    assert "An exact incident id is source-grounded identity, not permission" in frame.body


@pytest.mark.asyncio
async def test_shadow_intent_packs_require_explicit_composition_opt_in() -> None:
    prompts = FileSystemPromptRegistry(_CATALOG)
    default_prompt = await DefaultPromptComposer(registry=prompts).compose(
        capability_id="semantic.judgment"
    )
    shadow_prompt = await DefaultPromptComposer(registry=prompts).compose(
        capability_id="semantic.judgment",
        profile_id="shadow.semantic-judgment-v17",
    )

    assert "forbidden_actions" not in default_prompt.system_text
    assert "Keep incident mitigation requirements separate" in default_prompt.system_text
    assert "forbidden_actions" in shadow_prompt.system_text
    assert "Keep incident mitigation requirements separate" in shadow_prompt.system_text
    assert "use only the supplied query.manifest FunctionType" in shadow_prompt.system_text
    assert "source_end - source_start MUST equal" in shadow_prompt.system_text

    schema_prompt = await DefaultPromptComposer(registry=prompts).compose(
        capability_id="semantic.judgment",
        profile_id="shadow.semantic-judgment-schema-v1",
    )
    assert "use only the supplied query.manifest FunctionType" in schema_prompt.system_text
    assert "forbidden_actions" not in schema_prompt.system_text
    schema_v2_prompt = await DefaultPromptComposer(registry=prompts).compose(
        capability_id="semantic.judgment",
        profile_id="shadow.semantic-judgment-schema-v2",
    )
    assert (
        "First separate declaration counts from declaration details" in schema_v2_prompt.system_text
    )
    assert "value and source span include the plural suffix" in schema_v2_prompt.system_text
    assert "collection-wide query.resource_event_history" in shadow_prompt.system_text
    schema_repair_prompt = await DefaultPromptComposer(registry=prompts).compose(
        capability_id="semantic.judgment.schema-repair"
    )
    assert schema_repair_prompt.profile_id == "active.semantic-judgment-schema-repair"
    assert "Repair one primary T1 proposal" in schema_repair_prompt.system_text
    assert schema_repair_prompt.layer_manifest[0].version == 2
    assert "Set schema_version 1.1.0" in schema_repair_prompt.system_text


def test_judgment_capability_projection_preserves_only_reviewed_semantics() -> None:
    capabilities = _semantic_judgment_capabilities(
        (
            {
                "kind": "function",
                "name": "query.resource_event_history",
                "output_schema": {
                    "x-fdai-measure-concepts": [
                        "resource_event.kubernetes",
                        "resource_event.resource_health",
                        "resource_event.resource_health",
                    ]
                },
            },
            {
                "kind": "object",
                "name": "Resource",
                "properties": {"name": {}, "type": {}},
            },
            {
                "kind": "function",
                "name": "query.unreviewed",
                "output_schema": {"properties": {"rows": {"type": "array"}}},
            },
        )
    )

    assert capabilities == (
        {
            "kind": "function_type",
            "name": "query.resource_event_history",
            "measure_concepts": [
                "resource_event.kubernetes",
                "resource_event.resource_health",
            ],
        },
        {
            "kind": "object_type",
            "name": "Resource",
            "canonical_values": ["Resource", "Resource.name", "Resource.type"],
        },
        {"kind": "function_type", "name": "query.unreviewed"},
    )


def test_judgment_capability_projection_omits_oversized_semantic_axes() -> None:
    measures = [f"measure.{index}" for index in range(33)]
    properties = {f"property_{index}": {} for index in range(33)}

    assert _semantic_judgment_capabilities(
        (
            {
                "kind": "function",
                "name": "query.large",
                "output_schema": {"x-fdai-measure-concepts": measures},
            },
            {
                "kind": "object",
                "name": "LargeObject",
                "properties": properties,
            },
        )
    ) == (
        {"kind": "function_type", "name": "query.large"},
        {"kind": "object_type", "name": "LargeObject"},
    )


def test_judgment_capability_projection_preserves_ranked_prefix_within_byte_cap() -> None:
    descriptors = (
        {
            "kind": "function",
            "name": "query.resource_event_history",
            "output_schema": {"x-fdai-measure-concepts": ["resource_event.resource_health"]},
        },
        *(
            {
                "kind": "object",
                "name": f"Object{index:03d}",
                "properties": {f"property_{item:02d}": {} for item in range(32)},
            }
            for index in range(512)
        ),
    )

    capabilities = _semantic_judgment_capabilities(descriptors)
    encoded = json.dumps(
        capabilities,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    assert len(encoded) <= 32 * 1024
    assert len(capabilities) < len(descriptors)
    assert capabilities[0]["name"] == "query.resource_event_history"
    assert [item["name"] for item in capabilities] == [
        item["name"] for item in descriptors[: len(capabilities)]
    ]


def test_resource_event_history_narrows_frame_descriptors_after_judgment() -> None:
    descriptors = (
        {"kind": "object", "name": "Resource"},
        {"kind": "function", "name": "query.resource_event_history"},
        {"kind": "object", "name": "Incident"},
    )

    selected = _descriptors_for_operational_intent(
        descriptors,
        "query.resource_event_history",
    )

    assert tuple(item["name"] for item in selected) == (
        "Resource",
        "query.resource_event_history",
    )
