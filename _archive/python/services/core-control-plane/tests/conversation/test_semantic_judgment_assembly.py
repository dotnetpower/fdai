"""Route-selected judgment prompt assembly and its complete-prompt coverage guard."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fdai.core.conversation.conversation_preflight import (
    ConversationPreflightProposal,
    ConversationPreflightResult,
)
from fdai.core.conversation.model_observation import ConversationModelObservation
from fdai.core.conversation.semantic_judgment_assembly import (
    judge_with_prompt_assembly,
    judgment_assembly_keys,
    judgment_result_keys,
    model_arguments,
)
from fdai.core.prompts import (
    PromptArtifactRef,
    PromptAssembler,
    PromptLayer,
    PromptProfile,
    PromptProfileMode,
    PromptSelection,
)
from fdai.core.prompts.types import PromptArtifact, PromptMode
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal


def _preflight(*, topics: tuple[str, ...], confidence: float = 0.9) -> ConversationPreflightResult:
    return ConversationPreflightResult(
        proposal=ConversationPreflightProposal.model_validate(
            {
                "social_act": "none",
                "operational_signal": "explicit",
                "context_dependency": "none",
                "confidence": confidence,
                "request_topics": list(topics),
            }
        )
    )


def _proposal(intent: str, **extra: Any) -> SemanticJudgmentProposal:
    return SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": intent,
            "confidence": 0.9,
            "ambiguous": False,
            "action_subject": "none",
            **extra,
        }
    )


def _assembler() -> PromptAssembler:
    def artifact(artifact_id: str, layer: PromptLayer = PromptLayer.PACK) -> PromptArtifact:
        return PromptArtifact(
            id=artifact_id,
            version=1,
            layer=layer,
            body=artifact_id.upper(),
            applies_to=("semantic.judgment",),
            token_budget=None,
            default_mode=PromptMode.SHADOW,
            provenance_source="test",
        )

    refs = (
        PromptArtifactRef(
            "inventory",
            1,
            PromptLayer.PACK,
            when_any=("topic:resource_inventory",),
            covers=("intent:query.contextual_resources",),
        ),
        PromptArtifactRef(
            "ontology",
            1,
            PromptLayer.PACK,
            when_any=("topic:ontology_schema",),
            covers=("intent:query.manifest",),
        ),
    )
    profile = PromptProfile(
        id="test.dynamic",
        version=1,
        capability_id="semantic.judgment",
        mode=PromptProfileMode.SHADOW,
        root=PromptArtifactRef("root", 1, PromptLayer.BASE),
        packs=refs,
        system_token_budget=4096,
        request_token_budget=8192,
        reserved_output_tokens=16,
        promotion_evidence=(),
        provenance_source="test",
    )
    return PromptAssembler(
        PromptSelection(
            root=artifact("root", PromptLayer.BASE),
            packs=(artifact("inventory"), artifact("ontology")),
            profile=profile,
        )
    )


@dataclass(frozen=True)
class _Result:
    proposal: SemanticJudgmentProposal | None
    observations: tuple[ConversationModelObservation, ...] = ()


@dataclass
class _Boundary:
    intents: list[str]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def judge(self, **arguments: Any) -> _Result:
        self.calls.append(arguments)
        keys = arguments.get("prompt_assembly_keys")
        composed = _assembler().assemble(keys)
        observation = ConversationModelObservation(
            model="test",
            usage=None,
            trace_call={"kind": "semantic-judgment"},
            prompt_replay_manifest=composed.replay_manifest(),
        )
        return _Result(_proposal(self.intents[len(self.calls) - 1]), (observation,))


def test_route_keys_require_one_confident_validated_topic_route() -> None:
    assert judgment_assembly_keys(None) is None
    assert judgment_assembly_keys(ConversationPreflightResult(proposal=None)) is None
    assert judgment_assembly_keys(_preflight(topics=())) is None
    assert judgment_assembly_keys(_preflight(topics=("ontology_schema",), confidence=0.5)) is None
    assert judgment_assembly_keys(_preflight(topics=("resource_inventory", "change_activity"))) == (
        "topic:change_activity",
        "topic:resource_inventory",
    )


def test_model_arguments_only_reach_a_primary_model_that_declares_support() -> None:
    class Supported:
        supports_prompt_assembly = True

    keys = ("topic:resource_inventory",)

    assert model_arguments(True, Supported(), keys) == {"prompt_assembly_keys": keys}
    assert model_arguments(False, Supported(), keys) == {}
    assert model_arguments(True, object(), keys) == {}
    assert model_arguments(True, Supported(), None) == {}


def test_result_keys_name_intents_posture_and_document_mode() -> None:
    proposal = _proposal(
        "query.governed_documents",
        secondary_intents=["query.manifest"],
        document_evidence_mode="explicit",
    )

    assert judgment_result_keys(proposal) == (
        "document:explicit",
        "intent:query.governed_documents",
        "intent:query.manifest",
        "posture:advise_only",
    )


def test_unrouted_turn_uses_one_complete_judgment() -> None:
    boundary = _Boundary(["query.manifest"])

    result = judge_with_prompt_assembly(boundary, preflight=None, utterance="u")

    assert len(boundary.calls) == 1
    assert "prompt_assembly_keys" not in boundary.calls[0]
    assert result.proposal is not None


def test_covered_route_result_is_accepted_without_fallback() -> None:
    boundary = _Boundary(["query.manifest"])

    result = judge_with_prompt_assembly(
        boundary, preflight=_preflight(topics=("ontology_schema",)), utterance="u"
    )

    assert [call.get("prompt_assembly_keys") for call in boundary.calls] == [
        ("topic:ontology_schema",)
    ]
    assert result.proposal is not None
    assert result.proposal.primary_intent == "query.manifest"


def test_uncovered_route_result_is_replaced_by_one_complete_judgment() -> None:
    boundary = _Boundary(["query.manifest", "query.manifest"])

    result = judge_with_prompt_assembly(
        boundary, preflight=_preflight(topics=("resource_inventory",)), utterance="u"
    )

    assert [call.get("prompt_assembly_keys") for call in boundary.calls] == [
        ("topic:resource_inventory",),
        None,
    ]
    assert len(result.observations) == 2
    first, second = (
        observation.prompt_replay_manifest.assembly
        for observation in result.observations
        if observation.prompt_replay_manifest is not None
    )
    assert first is not None and first.mode.value == "selected"
    assert second is not None and second.mode.value == "complete"


def test_ungoverned_result_keys_do_not_trigger_fallback() -> None:
    boundary = _Boundary(["explanation"])

    judge_with_prompt_assembly(
        boundary, preflight=_preflight(topics=("resource_inventory",)), utterance="u"
    )

    assert len(boundary.calls) == 1
