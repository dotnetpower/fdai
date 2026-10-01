from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import fdai.agents.bragi as bragi_module
import pytest
from fdai.agents._framework.bragi_intent_training import (
    IntentTrainingEvaluationResult,
    IntentTrainingEvidence,
    ReviewedIntentTrainingPromotion,
)
from fdai.agents._framework.bragi_routing import route_semantic_judgment
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.bragi import Bragi
from fdai.agents.norns import Norns
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.agents.semantic_judgment_support import semantic_test_proposal

_PRINCIPAL_A = "sha256:" + "a" * 64
_PRINCIPAL_B = "sha256:" + "b" * 64
_PRINCIPAL_C = "sha256:" + "c" * 64
_INPUT_A = "sha256:" + "1" * 64
_INPUT_B = "sha256:" + "2" * 64
_INPUT_C = "sha256:" + "3" * 64
_REVIEWER = "sha256:" + "d" * 64


class _DeterministicEvaluator:
    def __init__(self, *, regress: bool = False) -> None:
        self.regress = regress
        self.calls: list[tuple[Mapping[str, Any], Mapping[str, Any], tuple[str, ...]]] = []

    def evaluate(
        self,
        *,
        baseline_revision: Mapping[str, Any],
        candidate_revision: Mapping[str, Any],
        holdout_cases: Sequence[IntentTrainingEvidence],
    ) -> Sequence[IntentTrainingEvaluationResult]:
        self.calls.append(
            (
                baseline_revision,
                candidate_revision,
                tuple(case.evidence_id for case in holdout_cases),
            )
        )
        results: list[IntentTrainingEvaluationResult] = []
        for case in holdout_cases:
            candidate_owner = (
                "Freyr" if self.regress and not case.targeted else case.corrected_owner
            )
            results.append(
                IntentTrainingEvaluationResult(
                    evidence_id=case.evidence_id,
                    baseline_owner=case.baseline_owner,
                    candidate_owner=candidate_owner,
                    expected_owner=case.corrected_owner,
                )
            )
        return tuple(results)


def _evidence(
    evidence_id: str,
    principal_scope_digest: str,
    input_digest: str,
    *,
    baseline_owner: str | None,
    corrected_owner: str = "Njord",
    corrected_intent: str = "cost_breakdown",
    targeted: bool,
) -> IntentTrainingEvidence:
    return IntentTrainingEvidence(
        evidence_id=evidence_id,
        source_kind="post_turn_review_correction",
        principal_scope_digest=principal_scope_digest,
        consent_ref=f"preference:{evidence_id}:share-with-learner",
        input_digest=input_digest,
        baseline_owner=baseline_owner,
        corrected_owner=corrected_owner,
        corrected_intent=corrected_intent,
        targeted=targeted,
        evidence_refs=(f"audit:{evidence_id}",),
    )


async def test_unbound_intent_training_is_visible_no_op_without_degrading_bragi() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    bragi = Bragi()
    bragi.bind_bus(bus)

    run = await bragi.run_intent_training(
        (
            _evidence(
                "target-1",
                _PRINCIPAL_A,
                _INPUT_A,
                baseline_owner=None,
                targeted=True,
            ),
        )
    )

    assert run.candidate_revision is None
    assert run.gate_passed is False
    assert run.published is True
    assert run.payload["kind"] == "bragi_intent_training_evidence"
    assert run.payload["stages"]["corpus_selection"]["status"] == "no_op"
    health = bragi.health()
    assert health["status"] == "ok"
    assert health["intent_training"]["status"] == "unavailable"
    assert health["intent_training"]["evidence_retention"] == {
        "evidence_state": "not_configured",
        "retained": False,
        "reason": "state_store_unbound",
    }
    assert health["intent_training"]["runtime_routing_authority"] is False
    (message,) = bus.messages_on("object.post-turn-review")
    assert message.payload["kind"] == "bragi_intent_training_evidence"


async def test_intent_training_gate_promotes_shadow_only_and_norns_ignores_new_kind() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    bragi = Bragi()
    bragi.bind_bus(bus)
    norns = Norns()
    bus.subscribe("object.post-turn-review", "Norns", norns.on_typed_message)
    evaluator = _DeterministicEvaluator()
    bragi.register_intent_training_evaluator(evaluator)
    before = route_semantic_judgment(
        semantic_test_proposal("question without an owned domain"),
        max_contributors=2,
    )

    run = await bragi.run_intent_training(
        (
            _evidence(
                "holdout-1",
                _PRINCIPAL_A,
                _INPUT_A,
                baseline_owner="Njord",
                targeted=False,
            ),
            _evidence(
                "target-1",
                _PRINCIPAL_B,
                _INPUT_B,
                baseline_owner=None,
                targeted=True,
            ),
        ),
        reviewed_promotion=ReviewedIntentTrainingPromotion(
            review_id="review-intent-training-1",
            reviewer_principal_digest=_REVIEWER,
            approval_ref="approval:bragi-intent-training:1",
        ),
    )
    after = route_semantic_judgment(
        semantic_test_proposal("question without an owned domain"),
        max_contributors=2,
    )

    assert run.gate_passed is True
    assert run.candidate_revision is not None
    assert run.candidate_revision["runtime_routing_authority_changed"] is False
    assert run.payload["stages"]["corpus_selection"]["selection_rules"] == {
        "sources": [
            "human_resolved_abstention",
            "norns_semantic_feedback",
            "post_turn_review_correction",
        ],
        "consent_required": True,
        "principal_scope": "sha256_digest_only",
        "raw_bodies_allowed": False,
        "lineage": "digest_only",
    }
    assert run.payload["stages"]["regression_gate"]["status"] == "passed"
    assert run.payload["stages"]["promotion_decision"]["status"] == "shadow_ready"
    assert run.payload["stages"]["promotion_decision"]["activation_authority"] is False
    assert before == after
    assert evaluator.calls[0][0]["revision"] == "runtime-current"
    assert norns.behavior_snapshot().get("post_turn_review_completed") is None
    assert norns.behavior_snapshot().get("post_turn_review_unavailable") is None


async def test_intent_training_retains_each_stage_with_audit_idempotently() -> None:
    state = InMemoryStateStore()
    bragi = Bragi(state_store=state)
    bragi.register_intent_training_evaluator(_DeterministicEvaluator())
    corpus = (
        _evidence(
            "holdout-1",
            _PRINCIPAL_A,
            _INPUT_A,
            baseline_owner="Njord",
            targeted=False,
        ),
        _evidence(
            "target-1",
            _PRINCIPAL_B,
            _INPUT_B,
            baseline_owner=None,
            targeted=True,
        ),
    )
    promotion = ReviewedIntentTrainingPromotion(
        review_id="review-intent-training-1",
        reviewer_principal_digest=_REVIEWER,
        approval_ref="approval:bragi-intent-training:1",
    )

    first = await bragi.run_intent_training(corpus, reviewed_promotion=promotion)
    replay = await bragi.run_intent_training(corpus, reviewed_promotion=promotion)

    assert first.payload["corpus_digest"].startswith("sha256:")
    assert first.payload["candidate_digest"].startswith("sha256:")
    assert replay.payload["corpus_digest"] == first.payload["corpus_digest"]
    assert replay.payload["candidate_digest"] == first.payload["candidate_digest"]
    rows = await state.read_states("pantheon/bragi/intent-training/", limit=20)
    audit_entries = tuple(state.audit_entries)
    assert len(rows) == 4
    assert len(audit_entries) == 4
    assert {row["stage"] for row in rows} == {
        "corpus_selection",
        "candidate_construction",
        "regression_gate",
        "promotion_decision",
    }
    assert all(row["grants_action_authority"] is False for row in rows)
    assert {entry["entry"]["stage"] for entry in audit_entries} == {
        "corpus_selection",
        "candidate_construction",
        "regression_gate",
        "promotion_decision",
    }
    assert bragi.health()["intent_training"]["evidence_retention"]["retained"] is True


async def test_intent_training_retention_stays_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bragi_module, "_INTENT_TRAINING_EVIDENCE_RETENTION", 4)
    state = InMemoryStateStore()
    bragi = Bragi(state_store=state)
    bragi.register_intent_training_evaluator(_DeterministicEvaluator())

    for index in range(3):
        await bragi.run_intent_training(
            (
                _evidence(
                    f"holdout-{index}",
                    "sha256:" + f"{index + 10:064x}",
                    "sha256:" + f"{index + 20:064x}",
                    baseline_owner="Njord",
                    targeted=False,
                ),
                _evidence(
                    f"target-{index}",
                    "sha256:" + f"{index + 30:064x}",
                    "sha256:" + f"{index + 40:064x}",
                    baseline_owner=None,
                    targeted=True,
                ),
            ),
            reviewed_promotion=ReviewedIntentTrainingPromotion(
                review_id=f"review-intent-training-{index}",
                reviewer_principal_digest=_REVIEWER,
                approval_ref=f"approval:bragi-intent-training:{index}",
            ),
        )

    rows = await state.read_states("pantheon/bragi/intent-training/", limit=20)
    assert len(rows) == 4
    assert len(tuple(state.audit_entries)) == 12
    assert bragi.health()["intent_training"]["evidence_retention"]["retention_limit"] == 4


async def test_intent_training_gate_blocks_regression_and_requires_explicit_review() -> None:
    bragi = Bragi()
    bragi.register_intent_training_evaluator(_DeterministicEvaluator(regress=True))

    run = await bragi.run_intent_training(
        (
            _evidence(
                "holdout-1",
                _PRINCIPAL_A,
                _INPUT_A,
                baseline_owner="Njord",
                targeted=False,
            ),
            _evidence(
                "target-1",
                _PRINCIPAL_B,
                _INPUT_B,
                baseline_owner=None,
                targeted=True,
            ),
        )
    )

    assert run.published is False
    assert run.gate_passed is False
    assert run.payload["stages"]["regression_gate"]["status"] == "failed"
    assert run.payload["stages"]["regression_gate"]["regression_case_ids"] == ["holdout-1"]
    assert run.payload["stages"]["promotion_decision"] == {
        "status": "held",
        "reason": "regression_gate_failed",
        "shadow_only": True,
        "runtime_routing_authority_changed": False,
    }


def test_intent_training_corpus_is_bounded_consent_filtered_and_digest_only() -> None:
    with pytest.raises(ValueError, match="consent_ref"):
        IntentTrainingEvidence(
            evidence_id="target-1",
            source_kind="post_turn_review_correction",
            principal_scope_digest=_PRINCIPAL_A,
            consent_ref="",
            input_digest=_INPUT_A,
            baseline_owner=None,
            corrected_owner="Njord",
            corrected_intent="cost_breakdown",
            targeted=True,
        )
    with pytest.raises(ValueError, match="sha256"):
        IntentTrainingEvidence(
            evidence_id="target-1",
            source_kind="post_turn_review_correction",
            principal_scope_digest="operator-raw",
            consent_ref="preference:target-1",
            input_digest=_INPUT_A,
            baseline_owner=None,
            corrected_owner="Njord",
            corrected_intent="cost_breakdown",
            targeted=True,
        )
    with pytest.raises(ValueError, match="owner's declared routing signal"):
        _evidence(
            "bad-owner-signal",
            _PRINCIPAL_C,
            _INPUT_C,
            baseline_owner=None,
            corrected_owner="Njord",
            corrected_intent="capacity_status",
            targeted=True,
        )
