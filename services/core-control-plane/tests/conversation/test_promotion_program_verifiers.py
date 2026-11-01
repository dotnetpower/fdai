"""Focused verification tests for promotion-program verifiers and production-shadow expiry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.conversation.production_shadow_expiry_store import (
    PRODUCTION_SHADOW_KEY_PREFIX,
    ExpiringProductionShadowStore,
    SemanticProductionShadowRecord,
)
from fdai.core.conversation.promotion_program_verifiers import (
    MAX_SINGLE_SAMPLE_RESAMPLES,
    PLAN_CONSTRAINT_UNCOVERED,
    TERMINAL_CLARIFICATION_HOLD,
    AmbiguityVerdict,
    BlindReadingRoleSpec,
    CompiledPlanRoleBinding,
    SingleSampleFailureKind,
    ThirdFamilyAmbiguityInput,
    arbitrate_third_family_ambiguity,
    enforce_terminal_clarification_hold,
    evaluate_single_sample_variance_and_ambiguity,
    verify_plan_role_coverage,
)


class _FakeClock:
    def __init__(self, initial: datetime) -> None:
        self.current = initial

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **kwargs: float) -> datetime:
        self.current = self.current + timedelta(**kwargs)
        return self.current


def test_item27_plan_role_coverage_holds_list_only_or_partially_covered_plans() -> None:
    per_group_list_verdict = verify_plan_role_coverage(
        groupings=("resource_group",),
        measures=("count",),
        bound_groupings=("resource_group",),
        bound_measures=("count",),
        reads_only_filtered_list=True,
    )
    assert not per_group_list_verdict.covered
    assert per_group_list_verdict.hold_reason == PLAN_CONSTRAINT_UNCOVERED
    assert not per_group_list_verdict.release_allowed
    assert per_group_list_verdict.uncovered_roles == ("measures", "groupings")

    partial_restrictions_verdict = verify_plan_role_coverage(
        BlindReadingRoleSpec(
            hard_constraints=("type:virtual_machine",),
            location_restrictions=("koreacentral",),
            lifecycle_restrictions=("deallocated",),
            time_restrictions=("last_24h",),
            quantities=("top_5",),
            relations=("depends_on",),
        ),
        CompiledPlanRoleBinding(
            bound_predicates=("predicate:type:virtual_machine",),
            bound_measures=(),
            bound_groupings=(),
            bound_quantities=(),
            bound_paths=(),
            reads_only_filtered_list=False,
        ),
    )
    assert not partial_restrictions_verdict.covered
    assert partial_restrictions_verdict.hold_reason == PLAN_CONSTRAINT_UNCOVERED
    assert not partial_restrictions_verdict.release_allowed
    assert partial_restrictions_verdict.uncovered_roles == (
        "location_restrictions",
        "lifecycle_restrictions",
        "time_restrictions",
        "quantities",
        "relations",
    )


def test_item27_plan_role_coverage_releases_when_every_stated_role_is_bound() -> None:
    verdict = verify_plan_role_coverage(
        hard_constraints=("sku:standard_d4s_v5",),
        measures=("cpu_utilization",),
        groupings=("resource_group",),
        quantities=("top_3",),
        relations=("contains",),
        location_restrictions=("koreacentral",),
        lifecycle_restrictions=("running",),
        time_restrictions=("PT1H",),
        bound_predicates=(
            "hard:sku:standard_d4s_v5",
            "location:koreacentral",
            "status:running",
            "window:PT1H",
        ),
        bound_measures=("cpu_utilization",),
        bound_groupings=("resource_group",),
        bound_quantities=("top_3",),
        bound_paths=("contains",),
        reads_only_filtered_list=False,
    )
    assert verdict.covered
    assert verdict.hold_reason is None
    assert verdict.uncovered_roles == ()
    assert verdict.release_allowed


@pytest.mark.parametrize(
    ("is_clarification", "is_ambiguous", "has_released", "verdict"),
    [
        (True, False, False, None),
        (False, True, False, None),
        (True, False, True, None),
        (True, True, True, "multiple"),
        (False, True, True, "unclear"),
        (True, False, False, "one"),
    ],
)
def test_item28_clarification_or_ambiguous_judgment_blocks_frame_reinterpretation(
    is_clarification: bool,
    is_ambiguous: bool,
    has_released: bool,
    verdict: Any,
) -> None:
    decision = enforce_terminal_clarification_hold(
        is_clarification=is_clarification,
        is_ambiguous=is_ambiguous,
        clarification_prompt="Which incident or ordinal item did you mean?",
        has_released_reading=has_released,
        third_family_verdict=verdict,
    )
    assert decision.terminal_clarification
    assert not decision.allow_released_reading
    assert not decision.allow_frame_reinterpretation
    assert decision.disposition == "clarification"
    assert decision.hold_reason == TERMINAL_CLARIFICATION_HOLD
    assert decision.clarification_prompt == "Which incident or ordinal item did you mean?"


def test_item28_released_reading_answers_only_when_third_family_verdict_is_one() -> None:
    decision = enforce_terminal_clarification_hold(
        is_clarification=True,
        is_ambiguous=True,
        clarification_prompt="Clarify reading",
        has_released_reading=True,
        third_family_verdict="one",
    )
    assert not decision.terminal_clarification
    assert decision.allow_released_reading
    assert not decision.allow_frame_reinterpretation
    assert decision.disposition == "released_reading"
    assert decision.hold_reason is None


@pytest.mark.parametrize(
    "failure_kind",
    [
        SingleSampleFailureKind.COMPETING_READING,
        SingleSampleFailureKind.UNFAITHFUL_REVIEW,
        SingleSampleFailureKind.DROPPED_OPERAND_REPAIR,
    ],
)
def test_item29_single_resample_recovers_eligible_failures_and_caps_at_one(
    failure_kind: SingleSampleFailureKind,
) -> None:
    recovered = evaluate_single_sample_variance_and_ambiguity(
        first_sample_compilable=True,
        first_failure_kind=failure_kind,
        resamples_already_taken=0,
        second_sample_released=True,
    )
    assert recovered.should_resample
    assert recovered.resamples_taken == 1
    assert recovered.max_resamples == MAX_SINGLE_SAMPLE_RESAMPLES
    assert recovered.has_released_reading
    assert recovered.allow_released_reading
    assert recovered.disposition == "released_reading"

    exhausted = evaluate_single_sample_variance_and_ambiguity(
        first_sample_compilable=True,
        first_failure_kind=failure_kind,
        resamples_already_taken=1,
        second_sample_released=True,
    )
    assert not exhausted.should_resample
    assert exhausted.resamples_taken == 0
    assert not exhausted.has_released_reading
    assert exhausted.disposition == "held"


def test_item29_non_recoverable_schema_error_does_not_resample() -> None:
    evaluation = evaluate_single_sample_variance_and_ambiguity(
        first_sample_compilable=True,
        first_failure_kind=SingleSampleFailureKind.NON_RECOVERABLE_SCHEMA_ERROR,
        resamples_already_taken=0,
        second_sample_released=True,
    )
    assert not evaluation.should_resample
    assert evaluation.resamples_taken == 0
    assert not evaluation.has_released_reading
    assert evaluation.hold_reason == "non_recoverable_schema_error"


def test_item29_third_family_ambiguity_enforces_family_independence_and_masked_input() -> None:
    with pytest.raises(ValueError, match="distinct"):
        ThirdFamilyAmbiguityInput(
            primary_model_family="family-alpha",
            secondary_model_family="family-beta",
            reader_model_family="family-alpha",
            masked_utterance="why did [ENTITY_1] fail?",
            reading_candidates=("reading_cause", "reading_history"),
        )

    with pytest.raises(ValueError, match="masked_utterance"):
        ThirdFamilyAmbiguityInput(
            primary_model_family="family-alpha",
            secondary_model_family="family-beta",
            reader_model_family="family-gamma",
            masked_utterance="why did [ENTITY_1] fail?",
            reading_candidates=("reading_cause",),
            unmasked_utterance="why did prod-db-01 fail?",
        )

    with pytest.raises(ValueError, match="masked_utterance"):
        ThirdFamilyAmbiguityInput(
            primary_model_family="family-alpha",
            secondary_model_family="family-beta",
            reader_model_family="family-gamma",
            masked_utterance="why did [ENTITY_1] fail?",
            reading_candidates=("reading_cause",),
            raw_evidence_rows=({"resource_id": "prod-db-01"},),
        )

    valid_input = ThirdFamilyAmbiguityInput(
        primary_model_family="family-alpha",
        secondary_model_family="family-beta",
        reader_model_family="family-gamma",
        masked_utterance="why did [ENTITY_1] restart?",
        reading_candidates=("reading_cause", "reading_state"),
    )
    one_outcome = arbitrate_third_family_ambiguity(
        valid_input,
        selected_candidates=("reading_cause",),
    )
    assert one_outcome.verdict is AmbiguityVerdict.ONE
    assert one_outcome.selected_reading == "reading_cause"
    assert not one_outcome.clarification_preserved
    assert one_outcome.release_allowed

    multiple_outcome = arbitrate_third_family_ambiguity(
        valid_input,
        selected_candidates=("reading_cause", "reading_state"),
    )
    assert multiple_outcome.verdict is AmbiguityVerdict.MULTIPLE
    assert multiple_outcome.selected_reading is None
    assert multiple_outcome.clarification_preserved
    assert not multiple_outcome.release_allowed

    unclear_outcome = arbitrate_third_family_ambiguity(
        valid_input,
        selected_candidates=(),
    )
    assert unclear_outcome.verdict is AmbiguityVerdict.UNCLEAR
    assert unclear_outcome.clarification_preserved
    assert not unclear_outcome.release_allowed


def test_item30_expiring_shadow_store_enforces_read_expiry_and_isolates_cleanup() -> None:
    t0 = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    clock = _FakeClock(t0)
    shared_state: dict[str, Any] = {
        "authoritative:incident:inc-202611-0001": {
            "status": "open",
            "expires_at": (t0 - timedelta(days=1)).isoformat(),
        },
        "workflow:approval:wf-99": {"decision": "approved"},
    }
    store = ExpiringProductionShadowStore(clock=clock, backing_store=shared_state)

    with pytest.raises(ValueError, match="sha256 digest"):
        SemanticProductionShadowRecord(
            record_id="bad-content",
            record_digest="raw operator utterance",
            turn_digest="sha256:1111222233334444",
            disposition="linked",
            expires_at=t0 + timedelta(minutes=10),
        )

    with pytest.raises(ValueError, match="already expired"):
        store.record(
            SemanticProductionShadowRecord(
                record_id="expired-on-arrival",
                record_digest="sha256:aaaa1111bbbb2222",
                turn_digest="sha256:cccc3333dddd4444",
                disposition="linked",
                expires_at=t0,
            )
        )

    short_record = store.record(
        SemanticProductionShadowRecord(
            record_id="rec-short-1",
            record_digest="sha256:1111111122222222",
            turn_digest="sha256:3333333344444444",
            disposition="linked",
            expires_at=t0 + timedelta(minutes=5),
        )
    )
    second_short = store.record(
        SemanticProductionShadowRecord(
            record_id="rec-short-2",
            record_digest="sha256:5555555566666666",
            turn_digest="sha256:7777777788888888",
            disposition="form_absent",
            expires_at=t0 + timedelta(minutes=10),
        )
    )
    long_record = store.record(
        SemanticProductionShadowRecord(
            record_id="rec-long",
            record_digest="sha256:99999999aaaa0000",
            turn_digest="sha256:bbbbccccddddeeee",
            disposition="linked",
            expires_at=t0 + timedelta(hours=1),
        )
    )

    assert short_record.storage_key == f"{PRODUCTION_SHADOW_KEY_PREFIX}rec-short-1"
    assert store.get("rec-short-1") == short_record
    assert len(store.list_active()) == 3

    # Advance fake clock past the two short-lived records before cleanup runs.
    clock.advance(minutes=10)
    assert store.get("rec-short-1") is None
    assert store.get(second_short.storage_key) is None
    assert store.get("rec-long") == long_record
    assert store.list_active() == (long_record,)

    # Bounded cleanup deletes at most max_delete=1 expired shadow key and keeps authoritative keys.
    first_cleanup = store.cleanup_expired(max_delete=1)
    assert first_cleanup.scanned_shadow_keys == 3
    assert first_cleanup.deleted_count == 1
    assert first_cleanup.deleted_keys == (f"{PRODUCTION_SHADOW_KEY_PREFIX}rec-short-1",)
    assert first_cleanup.remaining_expired_count == 1
    assert first_cleanup.active_count == 1
    assert first_cleanup.skipped_non_shadow_keys == 2
    assert "authoritative:incident:inc-202611-0001" in shared_state
    assert "workflow:approval:wf-99" in shared_state

    second_cleanup = store.cleanup_expired(max_delete=5)
    assert second_cleanup.deleted_count == 1
    assert second_cleanup.deleted_keys == (f"{PRODUCTION_SHADOW_KEY_PREFIX}rec-short-2",)
    assert second_cleanup.remaining_expired_count == 0
    assert second_cleanup.active_count == 1
    assert "authoritative:incident:inc-202611-0001" in shared_state
    assert "workflow:approval:wf-99" in shared_state
