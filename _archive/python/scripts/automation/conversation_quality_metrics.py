"""Answer, presentation, and model-invariance metrics for FDAI conversation assurance."""

from __future__ import annotations

from typing import Any

from scripts.automation.presentation_quality_metrics import PRESENTATION_METRICS
from scripts.automation.semantic_intent_metrics import (
    COVERAGE_LIMITATIONS,
)
from scripts.automation.semantic_intent_metrics import (
    METRIC_GROUPS as SEMANTIC_METRIC_GROUPS,
)
from scripts.automation.semantic_intent_metrics import (
    OPERATING_DOMAINS as SEMANTIC_OPERATING_DOMAINS,
)
from scripts.automation.semantic_intent_metrics import (
    SCORING_POLICY as SEMANTIC_SCORING_POLICY,
)


def metric(
    name: str,
    definition: str,
    aggregation: str,
    target: float | int,
) -> dict[str, Any]:
    return {
        "name": name,
        "definition": definition,
        "aggregation": aggregation,
        "promotion_target": target,
    }


OPERATING_DOMAINS = SEMANTIC_OPERATING_DOMAINS

SCORECARD = {
    "id": "fdai-conversation-quality-assurance",
    "name": "FDAI Conversation Quality Assurance Scorecard",
    "acronym": "CQAS",
    "aggregation": "conjunctive",
    "pillars": {
        "question_understanding": [
            "intent",
            "target",
            "ambiguity",
            "discourse_and_action",
            "time_and_evidence",
            "locale_and_robustness",
            "authority",
        ],
        "answer_fidelity": ["answer_fidelity"],
        "presentation_quality": ["presentation_quality"],
        "model_invariance": ["model_invariance"],
    },
}

MODEL_CHANGE_POLICY = {
    "comparison_unit": "paired_case",
    "control": (
        "Use the same exact-source question cohort, ontology release, principal manifest, "
        "evidence snapshot, prompt catalog, locale, and runtime policy for baseline and challenger."
    ),
    "combined_change_rule": (
        "A model and prompt change evaluated together is a combined treatment, "
        "not model-only evidence."
    ),
    "promotion_rule": (
        "Every required metric and slice must meet its target; no aggregate score may compensate "
        "for a hard-zero violation, an unsupported slice, or a worst-slice regression."
    ),
    "reviewer_independence": (
        "The answer model cannot review itself; use at least two independent reviewer families "
        "after deterministic semantic, evidence, completeness, calibration, scope, "
        "and authority gates."
    ),
    "presentation_rule": (
        "Models propose meaning only. Deterministic presentation planning selects renderer-neutral "
        "blocks from verified evidence shape, and browser checks validate the rendered experience."
    ),
}

QUALITY_COVERAGE_LIMITATIONS = COVERAGE_LIMITATIONS + (
    "Golden answer oracles cover only reviewed Golden questions; candidate membership is not "
    "answer-fidelity evidence.",
    "No question-level presentation oracle or repository-owned paired model comparison exists yet, "
    "so those coverage slices remain zero rather than receiving inferred credit.",
    "Source-level presentation contract coverage is not browser scenario evidence.",
)

ADDITIONAL_METRIC_GROUPS: dict[str, tuple[dict[str, Any], ...]] = {
    "answer_fidelity": (
        metric(
            "required_goal_completion_recall",
            "Share of required answer goals completed without substituting another goal.",
            "recall",
            1.0,
        ),
        metric(
            "required_fact_recall",
            "Share of oracle-required facts supported in the answer.",
            "recall",
            1.0,
        ),
        metric(
            "forbidden_claim_rate",
            "Oracle-forbidden claims asserted by the answer.",
            "rate",
            0.0,
        ),
        metric(
            "unsupported_operational_claim_rate",
            "Operational claims without admitted authoritative evidence.",
            "rate",
            0.0,
        ),
        metric(
            "evidence_entailment_pass_rate",
            "Answers whose atomic operational claims are entailed by cited evidence.",
            "pass_rate",
            1.0,
        ),
        metric(
            "atomic_claim_support_precision",
            "Share of asserted atomic claims classified as supported.",
            "precision",
            1.0,
        ),
        metric(
            "claim_citation_coverage",
            "Share of evidence-requiring claims carrying a supporting evidence reference.",
            "coverage",
            1.0,
        ),
        metric(
            "citation_reference_integrity",
            "Citations resolving to evidence admitted for the exact turn and claim.",
            "validity",
            1.0,
        ),
        metric(
            "evidence_completeness_fidelity",
            "Answer completeness language matches the verified evidence completeness state.",
            "accuracy",
            1.0,
        ),
        metric(
            "required_limitation_recall",
            "Share of oracle-required evidence and capability limitations retained.",
            "recall",
            1.0,
        ),
        metric(
            "uncertainty_calibration_accuracy",
            "Unknown, partial, conflicting, and supported conclusions use the expected "
            "confidence posture.",
            "accuracy",
            1.0,
        ),
        metric(
            "scope_fidelity",
            "Answer claims stay within the authorized target, time, relationship, "
            "and result bounds.",
            "accuracy",
            1.0,
        ),
        metric(
            "temporal_answer_fidelity",
            "Answer preserves effective time, event time, recorded time, and requested "
            "comparison windows.",
            "accuracy",
            1.0,
        ),
        metric(
            "answer_locale_accuracy",
            "Answer language matches the resolved operator locale without changing typed meaning.",
            "accuracy",
            1.0,
        ),
        metric(
            "answer_clarity_minimum_score",
            "Lowest independent-review clarity score on the governed 0..4 scale.",
            "minimum_score",
            3,
        ),
        metric(
            "independent_review_pass_rate",
            "Answers passing complete independent reviewer criteria after deterministic gates.",
            "pass_rate",
            1.0,
        ),
    ),
    "presentation_quality": PRESENTATION_METRICS,
    "model_invariance": (
        metric(
            "paired_model_case_coverage",
            "Required cases evaluated for both baseline and challenger under identical controls.",
            "coverage",
            1.0,
        ),
        metric(
            "challenger_target_pass_rate",
            "Challenger cases meeting every applicable question, answer, and presentation target.",
            "pass_rate",
            1.0,
        ),
        metric(
            "regressed_metric_count",
            "Non-hard-zero metrics that pass baseline but miss target with the challenger.",
            "count",
            0,
        ),
        metric(
            "hard_zero_regression_count",
            "Hard-zero metrics with any challenger violation.",
            "count",
            0,
        ),
        metric(
            "worst_slice_regression_count",
            "Topic, locale, posture, evidence, or presentation slices below baseline or target.",
            "count",
            0,
        ),
        metric(
            "metamorphic_consistency_rate",
            "Meaning-preserving variations that retain equivalent typed and factual outcomes.",
            "pass_rate",
            1.0,
        ),
        metric(
            "repeated_run_consistency_rate",
            "Repeated controlled runs that retain equivalent rubric outcomes.",
            "pass_rate",
            1.0,
        ),
        metric(
            "reviewer_model_independence_violation_count",
            "Evaluations where the answer model reviews itself or reviewer families "
            "are not independent.",
            "count",
            0,
        ),
        metric(
            "model_operational_budget_pass_rate",
            "Cases meeting profile-owned latency and cost ceilings without lowering quality.",
            "pass_rate",
            1.0,
        ),
    ),
}

METRIC_GROUPS = SEMANTIC_METRIC_GROUPS | ADDITIONAL_METRIC_GROUPS
SCORING_POLICY = SEMANTIC_SCORING_POLICY | {
    "pillar_aggregation": (
        "conjunctive; report each pillar and worst slice, never one compensating weighted score"
    ),
    "answer_review_scale": "integer 0..4; every criterion >=3 to pass",
    "presentation_scoring": (
        "deterministic artifact checks plus exercised desktop, constrained-desktop, "
        "and mobile scenarios"
    ),
    "model_comparison": "paired baseline and challenger cases under MODEL_CHANGE_POLICY controls",
}

HARD_ZERO_METRICS = (
    "candidate_authority_violation_count",
    "execution_authority_violation_count",
    "executable_action_draft_count",
    "forbidden_action_false_positive_rate",
    "forbidden_claim_rate",
    "hard_zero_regression_count",
    "invented_capability_count",
    "invented_target_identity_count",
    "legacy_ordinary_language_route_count",
    "non_direct_action_false_positive_rate",
    "presentation_invented_value_count",
    "read_to_action_false_positive_rate",
    "regressed_metric_count",
    "reviewer_model_independence_violation_count",
    "schema_failure_success_fallback_count",
    "unsupported_operational_claim_rate",
    "unverified_operational_success_claim_rate",
    "worst_slice_regression_count",
)
