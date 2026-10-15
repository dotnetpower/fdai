from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

import fdai.agents.bragi as bragi_module
import pytest
from fdai.agents._framework.bragi_intent_training import (
    IntentTrainingEvaluationResult,
    IntentTrainingEvidence,
    ReviewedIntentTrainingPromotion,
    evaluate_training_contract,
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


@pytest.mark.parametrize("substitution", ["duplicate", "baseline", "expected"])
def test_training_evaluator_cannot_replace_the_frozen_case_identity(substitution: str) -> None:
    class SubstitutingEvaluator(_DeterministicEvaluator):
        def evaluate(
            self,
            *,
            baseline_revision: Mapping[str, Any],
            candidate_revision: Mapping[str, Any],
            holdout_cases: Sequence[IntentTrainingEvidence],
        ) -> Sequence[IntentTrainingEvaluationResult]:
            results = list(
                super().evaluate(
                    baseline_revision=baseline_revision,
                    candidate_revision=candidate_revision,
                    holdout_cases=holdout_cases,
                )
            )
            if substitution == "duplicate":
                return (*results, results[0])
            original = results[0]
            results[0] = IntentTrainingEvaluationResult(
                evidence_id=original.evidence_id,
                baseline_owner="Freyr" if substitution == "baseline" else original.baseline_owner,
                candidate_owner=original.candidate_owner,
                expected_owner="Freyr" if substitution == "expected" else original.expected_owner,
            )
            return tuple(results)

    corpus = (
        _evidence("holdout", _PRINCIPAL_A, _INPUT_A, baseline_owner="Njord", targeted=False),
        _evidence("target", _PRINCIPAL_B, _INPUT_B, baseline_owner=None, targeted=True),
    )
    with pytest.raises(ValueError):
        evaluate_training_contract(corpus, evaluator=SubstitutingEvaluator())


@pytest.mark.parametrize("changed", ["baseline", "candidate", "nested_candidate", "support_type"])
async def test_training_evaluator_cannot_mutate_frozen_revisions(changed: str) -> None:
    class MutatingEvaluator(_DeterministicEvaluator):
        def evaluate(
            self,
            *,
            baseline_revision: Mapping[str, Any],
            candidate_revision: Mapping[str, Any],
            holdout_cases: Sequence[IntentTrainingEvidence],
        ) -> Sequence[IntentTrainingEvaluationResult]:
            results = super().evaluate(
                baseline_revision=baseline_revision,
                candidate_revision=candidate_revision,
                holdout_cases=holdout_cases,
            )
            assert isinstance(baseline_revision, dict)
            assert isinstance(candidate_revision, dict)
            if changed == "baseline":
                baseline_revision["revision"] = "substituted"
            elif changed == "candidate":
                candidate_revision["candidate_digest"] = "sha256:" + "0" * 64
            elif changed == "nested_candidate":
                candidate_revision["calibration_entries"][0]["owner"] = "Freyr"
            else:
                candidate_revision["calibration_entries"][0]["support_count"] = True
            return results

    state = InMemoryStateStore()
    bus = InMemoryBus(registry=load_pantheon())
    bragi = Bragi(state_store=state)
    bragi.bind_bus(bus)
    bragi.register_intent_training_evaluator(MutatingEvaluator())
    corpus = (
        _evidence("holdout", _PRINCIPAL_A, _INPUT_A, baseline_owner="Njord", targeted=False),
        _evidence("target", _PRINCIPAL_B, _INPUT_B, baseline_owner=None, targeted=True),
    )
    review = ReviewedIntentTrainingPromotion("review-1", _REVIEWER, "approval:review-1")
    with pytest.raises(ValueError, match="preserve the frozen revisions"):
        await bragi.run_intent_training(corpus, reviewed_promotion=review)
    assert not bus.messages_on("object.post-turn-review")
    assert not await state.read_states("pantheon/bragi/intent-training/", limit=20)
    assert not state.audit_entries


def test_training_evaluator_retained_reference_cannot_change_returned_candidate() -> None:
    evaluator = _DeterministicEvaluator()
    corpus = (
        _evidence("holdout", _PRINCIPAL_A, _INPUT_A, baseline_owner="Njord", targeted=False),
        _evidence("target", _PRINCIPAL_B, _INPUT_B, baseline_owner=None, targeted=True),
    )
    _, candidate, passed = evaluate_training_contract(corpus, evaluator=evaluator)
    assert passed and candidate is not None
    evaluation_candidate = evaluator.calls[0][1]
    assert isinstance(evaluation_candidate, dict)
    evaluation_candidate["calibration_entries"][0]["owner"] = "Freyr"
    assert candidate["calibration_entries"][0]["owner"] == "Njord"


def test_training_candidate_cannot_share_an_input_with_the_holdout() -> None:
    evaluator = _DeterministicEvaluator()
    corpus = (
        _evidence("holdout", _PRINCIPAL_A, _INPUT_A, baseline_owner="Njord", targeted=False),
        _evidence("target", _PRINCIPAL_B, _INPUT_A, baseline_owner=None, targeted=True),
    )
    with pytest.raises(ValueError, match="independent input digests"):
        evaluate_training_contract(corpus, evaluator=evaluator)
    assert not evaluator.calls


@pytest.mark.parametrize("changed", ["input", "correction", "consent", "review", "evaluation"])
def test_training_identity_binds_the_complete_evidence_snapshot(changed: str) -> None:
    corpus = (
        _evidence("holdout", _PRINCIPAL_A, _INPUT_A, baseline_owner="Njord", targeted=False),
        _evidence("target", _PRINCIPAL_B, _INPUT_B, baseline_owner=None, targeted=True),
    )
    first, _, _ = evaluate_training_contract(corpus, evaluator=_DeterministicEvaluator())
    changed_corpus = corpus
    review = None
    if changed == "input":
        changed_corpus = (corpus[0], replace(corpus[1], input_digest=_INPUT_C))
    elif changed == "correction":
        changed_corpus = (
            corpus[0],
            replace(corpus[1], corrected_owner="Freyr", corrected_intent="sizing_recommendation"),
        )
    elif changed == "consent":
        changed_corpus = (corpus[0], replace(corpus[1], consent_ref="preference:renewed-consent"))
    elif changed == "review":
        review = ReviewedIntentTrainingPromotion("review-1", _REVIEWER, "approval:review-1")
    second, _, _ = evaluate_training_contract(
        changed_corpus,
        evaluator=_DeterministicEvaluator(regress=changed == "evaluation"),
        reviewed_promotion=review,
    )
    assert second["id"] != first["id"]
    assert second["correlation_id"] == second["id"]
    assert second["idempotency_key"] != first["idempotency_key"]
    assert second["authority"]["routes_runtime_traffic"] is False
    assert second["authority"]["grants_action_authority"] is False
    replay, _, _ = evaluate_training_contract(
        tuple(reversed(changed_corpus)),
        evaluator=_DeterministicEvaluator(regress=changed == "evaluation"),
        reviewed_promotion=review,
    )
    assert replay == second


async def test_training_review_snapshot_has_distinct_immutable_stage_records() -> None:
    state = InMemoryStateStore()
    bus = InMemoryBus(registry=load_pantheon())
    bragi = Bragi(state_store=state)
    bragi.bind_bus(bus)
    bragi.register_intent_training_evaluator(_DeterministicEvaluator())
    corpus = (
        _evidence("holdout", _PRINCIPAL_A, _INPUT_A, baseline_owner="Njord", targeted=False),
        _evidence("target", _PRINCIPAL_B, _INPUT_B, baseline_owner=None, targeted=True),
    )
    first = await bragi.run_intent_training(corpus)
    review = ReviewedIntentTrainingPromotion("review-1", _REVIEWER, "approval:review-1")
    second = await bragi.run_intent_training(corpus, reviewed_promotion=review)
    replay = await bragi.run_intent_training(corpus, reviewed_promotion=review)
    rows = await state.read_states("pantheon/bragi/intent-training/", limit=20)
    assert len(rows) == len(state.audit_entries) == 8
    assert {row["run_id"] for row in rows} == {first.run_id, second.run_id}
    promotion_rows = [row for row in rows if row["stage"] == "promotion_decision"]
    assert {row["stage_status"] for row in promotion_rows} == {"held", "shadow_ready"}
    assert replay.run_id == second.run_id
    messages = bus.messages_on("object.post-turn-review")
    assert len(messages) == 3
    assert messages[0].payload["idempotency_key"] != messages[1].payload["idempotency_key"]
    assert messages[1].payload == messages[2].payload
    assert all(row["routes_runtime_traffic"] is False for row in rows)
    assert all(row["grants_action_authority"] is False for row in rows)


async def test_intent_training_gate_promotes_shadow_only_and_norns_records_new_kind() -> None:
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
    assert run.candidate_revision["calibration_entries"][0]["support_count"] == 1
    assert run.candidate_revision["calibration_entries"][0]["lineage_digests"] == (_INPUT_B,)
    assert _INPUT_A not in str(run.candidate_revision)
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
    assert norns.behavior_snapshot()["post_turn_review:intent_training_evidence_observed"] == 1


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
