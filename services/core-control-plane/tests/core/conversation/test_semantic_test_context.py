from copy import deepcopy

import pytest
from fdai.core.conversation.semantic_judgment import SemanticJudgmentResult
from fdai.core.conversation.semantic_test_context import (
    test_context_request_from_judgment as compile_request,
)
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.semantic_judgment import (
    SemanticJudgmentProposal,
    SemanticJudgmentReceipt,
)


def _judgment(*, changes=None, prefix="Propose test context:"):
    values = {
        "target_ref": "resource-example",
        "signal_code": "cpu_percent",
        "expected_min": "60",
        "expected_max": "90",
        "effective_from": "2026-09-15T10:00:00+00:00",
        "effective_to": "2026-09-15T11:00:00+00:00",
    }
    utterance = prefix
    targets = []
    for kind, value in values.items():
        start = len(utterance) + 1
        utterance += " " + value
        targets.append(
            {"kind": kind, "value": value, "source_start": start, "source_end": len(utterance)}
        )
    raw = {
        "primary_intent": "create.test_context",
        "confidence": 0.95,
        "ambiguous": False,
        "action_subject": "Change",
        "action_posture": "draft_only",
        "targets": targets,
    }
    raw.update(changes or {})
    proposal = SemanticJudgmentProposal.model_validate(raw)
    body = {
        "schema_version": "1.0.0",
        "input_digest": content_digest({"utterance": utterance}),
        "context_digest": "sha256:" + "a" * 64,
        "capability_digest": "sha256:" + "b" * 64,
        "proposal_digest": content_digest(proposal.model_dump(mode="json")),
        "profile_id": "example",
        "profile_version": "1.0.0",
        "tier": "t1",
        "model_config_digest": "sha256:" + "c" * 64,
        "prompt_digest": "sha256:" + "d" * 64,
        "disposition": "accepted",
        "confidence": 0.95,
        "ambiguous": proposal.ambiguous,
        "latency_ms": 1,
        "reason_code": "accepted",
        "execution_authority": False,
    }
    receipt = SemanticJudgmentReceipt.model_validate(
        {**body, "receipt_digest": content_digest(body)}
    )
    return utterance, SemanticJudgmentResult(proposal=proposal, receipt=receipt)


def _compile(utterance, judgment):
    return compile_request(
        judgment=judgment,
        utterance=utterance,
        access_scope_digest="a" * 64,
        policy_revision="policy:example",
        source_ref="turn:example",
    )


@pytest.mark.parametrize("prefix", ["Propose test context:", "테스트 컨텍스트를 제안합니다:"])
def test_compiles_source_grounded_proposal_without_identity_or_review(prefix):
    utterance, judgment = _judgment(prefix=prefix)
    request = _compile(utterance, judgment)
    assert request.operation == "propose" and request.expected_revision == 0
    assert request.expected_min == 60 and request.expected_max == 90
    assert request.semantic_receipt == judgment.receipt.receipt_digest
    assert "actor_id" not in request.model_dump()
    assert request == _compile(utterance, judgment)


def test_actual_semantic_boundary_accepts_only_source_grounded_context_meaning():
    from fdai.core.conversation.semantic_judgment import (
        SemanticJudgmentBinding,
        SemanticJudgmentBoundary,
    )
    from fdai.core.conversation.semantic_test_context import test_context_capability
    from fdai_service_contracts.semantic_judgment import SemanticJudgmentTier

    utterance, fixture = _judgment()

    class _Model:
        def judge(self, **_kwargs):
            return fixture.proposal.model_dump(mode="json")

    boundary = SemanticJudgmentBoundary(
        profile_id="example",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_Model(),
            model_config_digest="sha256:" + "a" * 64,
            prompt_digest="sha256:" + "b" * 64,
        ),
    )
    judged = boundary.judge(
        utterance=utterance,
        context=(),
        capabilities=(test_context_capability(),),
        allow_escalation=False,
    )
    assert judged.accepted, judged.receipt.reason_code
    assert _compile(utterance, judged).target_ref == "resource-example"


@pytest.mark.parametrize(
    "mutation", ["input", "missing", "repeated", "substituted", "intent", "ambiguous"]
)
def test_rejects_unbound_or_ambiguous_proposals(mutation):
    utterance, judgment = _judgment()
    targets = deepcopy(judgment.proposal.model_dump(mode="json")["targets"])
    changes = {}
    if mutation == "input":
        utterance += " changed"
    elif mutation == "missing":
        changes["targets"] = targets[:-1]
    elif mutation == "repeated":
        changes["targets"] = targets + [targets[0]]
    elif mutation == "substituted":
        targets[0]["value"] = "other-resource"
        changes["targets"] = targets
    elif mutation == "intent":
        changes["primary_intent"] = "review.test_context"
    else:
        changes.update(ambiguous=True, unresolved_terms=["time"], clarification="Which time?")
    if changes:
        utterance, judgment = _judgment(changes=changes)
    with pytest.raises(ValueError):
        _compile(utterance, judgment)


@pytest.mark.parametrize("missing", [False, True])
def test_real_planner_returns_context_draft_or_clarification_without_action_planning(missing):
    from fdai.core.conversation.session import Principal, Role
    from tests.conversation.test_semantic_planning import (
        _fixture,
        _frame,
        _JudgmentBoundary,
        _Model,
        _service,
    )

    utterance, judgment = _judgment(changes={"targets": []} if missing else None)

    class _ContextBoundary(_JudgmentBoundary):
        def judge(self, **kwargs):
            assert any(item["name"] == "create.test_context" for item in kwargs["capabilities"])
            return judgment

    manifest, _definition = _fixture()
    model = _Model(frame=_frame(), plan=None)
    planner = _service(model, manifest, semantic_judgment=_ContextBoundary(judgment.proposal))
    result = planner.plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal("operator-one", Role.READER),
        purpose="operations-review",
    )
    if missing:
        assert result.disposition.value == "clarification" and result.test_context_draft is None
    else:
        assert result.disposition.value == "action_draft"
        assert result.test_context_draft.execution_authority is False
    assert model.frame_calls == model.plan_calls == 0


async def test_core_projection_and_operator_presentation_preserve_inert_context_draft():
    from dataclasses import replace
    from unittest.mock import AsyncMock

    from fdai.core.conversation.semantic_planning_models import (
        SemanticPlanningDisposition,
        SemanticPlanningOutcome,
    )
    from fdai.core.conversation.semantic_test_context import test_context_draft_from_judgment
    from fdai_operator_service.families.conversation.semantic_turn_presentation import (
        semantic_done_event_data,
    )
    from fdai_operator_service.families.conversation.semantic_turn_runtime import (
        SemanticTurnProjectionConsumer,
    )
    from tests.test_semantic_turn_processor import (
        _processor,
        _projection,
        _request,
        _Runtime,
        _runtime_result,
    )

    utterance, judgment = _judgment()
    draft = test_context_draft_from_judgment(
        judgment=judgment, utterance=utterance, source_ref="turn:example"
    )
    result = _runtime_result("action_draft")
    result = replace(
        result,
        planning=SemanticPlanningOutcome(
            disposition=SemanticPlanningDisposition.ACTION_DRAFT,
            reason="test_context_proposal_requires_scope_and_review",
            test_context_draft=draft,
        ),
    )
    processor = _processor(_Runtime(result))
    request = _request()
    encoded = await processor.process(request)
    assert await processor.process(request) == encoded
    projection = _projection(encoded)
    assert projection["payload"]["test_context_draft"] == draft.model_dump(mode="json")
    store = AsyncMock()
    consumer = SemanticTurnProjectionConsumer(store)
    await consumer.consume(projection)
    store.project_semantic_turn_result.assert_awaited_once()
    done = semantic_done_event_data(projection)
    assert done["test_context_draft"]["execution_authority"] is False
    assert done["status"] == "action_draft"
    malicious = deepcopy(projection)
    malicious["payload"]["test_context_draft"]["execution_authority"] = True
    with pytest.raises(ValueError):
        await consumer.consume(malicious)
    assert store.project_semantic_turn_result.await_count == 1
