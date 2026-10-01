"""Deterministic, authority-free state transitions for Norns learners."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from fdai_service_contracts.ontology_query import content_digest

from fdai.agents._framework.action_semantics import outcome_result
from fdai.agents._framework.adapters import canonical_json_digest
from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.norns_constants import _MAX_TRACKED
from fdai.core.operational_learning import (
    OperatingPatternCompiler,
    PatternCase,
    ShadowDwellEvidence,
    ShadowDwellEvidenceError,
    ShadowDwellLedger,
    ShadowDwellObservation,
)
from fdai.shared.providers.state_store import StateStore

_ADVERSE_RESULTS = frozenset({"rollback", "failure", "reverted"})
_SUCCESS_RESULTS = frozenset({"success", "applied", "ok"})
_SHADOW_INSTANT_KEYS = ("observed_at", "occurred_at", "recorded_at", "timestamp")


class NornsLearningState(Protocol):
    """Minimum Norns-owned state required by deterministic learners."""

    _approval_counts: BoundedLruDict[str, dict[str, int]]
    _approval_proposed: BoundedLruSet[str]
    _counted_approvals: BoundedLruSet[str]
    _counted_correlations: BoundedLruSet[str]
    _counted_shadow_outcomes: BoundedLruSet[str]
    _fingerprint_counter: BoundedLruDict[str, int]
    _min_outcome_samples: int
    _outcome_proposed: BoundedLruSet[str]
    _outcomes: BoundedLruDict[str, dict[str, int]]
    _override_counter: BoundedLruDict[str, int]
    _override_proposed: BoundedLruSet[str]
    _override_retire_threshold: int
    _promotion_threshold: int
    _proposed: BoundedLruSet[str]
    _rejection_revise_threshold: int
    _rollback_alarm_rate: float
    _shadow_dwell: ShadowDwellLedger
    pending_candidates: list[dict[str, Any]]
    _operating_pattern_compiler: OperatingPatternCompiler
    _operational_case_max_age: timedelta
    _clock: Callable[[], datetime]
    _operating_pattern_ids: BoundedLruSet[str]
    _pattern_publications: dict[str, dict[str, Any]]

    def _append_candidate(self, candidate: dict[str, Any]) -> None: ...

    def _ensure_pending_capacity(self) -> None: ...

    def _mark_learning_dirty(self, bucket: str, item_key: str) -> None: ...

    def record_behavior(self, name: str, amount: int = 1) -> None: ...


def observe_operational_case_cohort(
    state: NornsLearningState, payload: Mapping[str, Any]
) -> str | None:
    """Compile an inert candidate and return the identity whose publication must finish."""
    if payload.get("producer_principal") != "Muninn":
        state.record_behavior("operational_case_cohort_invalid_producer")
        return None
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not 1 <= len(raw_cases) <= 100:
        state.record_behavior("operational_case_cohort_invalid_payload")
        return None
    try:
        cases = tuple(
            PatternCase.from_mapping(item) for item in raw_cases if isinstance(item, dict)
        )
    except ValueError:
        state.record_behavior("operational_case_cohort_invalid_payload")
        return None
    fingerprint = str(payload.get("failure_fingerprint") or "")
    if (
        len(cases) != len(raw_cases)
        or not fingerprint
        or any(case.failure_fingerprint != fingerprint for case in cases)
    ):
        state.record_behavior("operational_case_cohort_invalid_payload")
        return None
    candidate = state._operating_pattern_compiler.compile(
        cases, reviewed_at=state._clock(), max_case_age=state._operational_case_max_age
    )
    if candidate is None:
        state.record_behavior("operational_case_cohort_held")
        return None
    if candidate.pattern_id in state._operating_pattern_ids:
        state.record_behavior("operational_case_cohort_duplicate")
        return candidate.pattern_id
    state._ensure_pending_capacity()
    scope, purpose, cohort_key = (
        payload.get("access_scope_digest"),
        payload.get("purpose"),
        payload.get("correlation_id"),
    )
    if isinstance(scope, str) and isinstance(purpose, str) and isinstance(cohort_key, str):
        state._pattern_publications[candidate.pattern_id] = {
            "producer_principal": "Norns",
            "schema_version": "1.0.0",
            "kind": "operational_pattern",
            "pattern_id": candidate.pattern_id,
            "cohort_key": cohort_key,
            "cohort_snapshot_ref": payload.get("cohort_snapshot_ref"),
            "access_scope_digest": scope,
            "purpose": purpose,
            "correlation_id": cohort_key,
            "idempotency_key": f"operating-pattern:{candidate.pattern_id}",
        }
    state._operating_pattern_ids.add(candidate.pattern_id)
    proposal = candidate.to_rule_candidate_mapping()
    if isinstance(scope, str) and isinstance(purpose, str):
        proposal["case_scope"] = {"access_scope_digest": scope, "purpose": purpose}
    state._append_candidate(proposal)
    state.record_behavior("operational_case_candidate_created")
    return candidate.pattern_id


def observe_fingerprint(state: NornsLearningState, payload: Mapping[str, Any]) -> None:
    """Propose one inert candidate after a fingerprint repeats enough times."""
    fingerprint = str(payload.get("fingerprint", ""))
    if not fingerprint:
        state.record_behavior("fingerprint:invalid")
        return
    count = (state._fingerprint_counter.get(fingerprint) or 0) + 1
    apply_fingerprint_count(state, fingerprint, count, propose=True)


def apply_fingerprint_count(
    state: NornsLearningState,
    fingerprint: str,
    count: int,
    *,
    propose: bool,
) -> None:
    """Project a validated count and optionally materialize its inert candidate."""
    state._fingerprint_counter.set(fingerprint, count)
    if not propose or count < state._promotion_threshold or fingerprint in state._proposed:
        return
    state._append_candidate(
        {
            "source_signal": "handoff_fingerprint",
            "evidence": {"fingerprint": fingerprint, "occurrence_count": count},
            "proposed_by": "Norns",
            "proposal_kind": "new",
        }
    )
    state._proposed.add(fingerprint)


def observe_outcome(state: NornsLearningState, payload: Mapping[str, Any]) -> None:
    """Propose a safer threshold after measured rollback evidence clears its floor."""
    if payload.get("producer_principal") != "Saga":
        state.record_behavior("audit_outcome:invalid_producer")
        return
    target = str(payload.get("action_type") or payload.get("rule_id") or "")
    if payload.get("shadow_mode"):
        retain_shadow_dwell(state, target, payload)
        return
    if payload.get("non_learnable") is True:
        state.record_behavior("audit_outcome:non_learnable")
        return
    result = str(payload.get("result", "")).lower()
    if not result:
        result = outcome_result(str(payload.get("state", ""))) or ""
    if not target:
        state.record_behavior("audit_outcome:invalid_target")
        return
    if result in _ADVERSE_RESULTS:
        bucket = "rollback"
    elif result in _SUCCESS_RESULTS:
        bucket = "success"
    else:
        state.record_behavior("audit_outcome:ignored_result")
        return
    correlation_id = str(payload.get("correlation_id", ""))
    if correlation_id:
        outcome_key = f"{correlation_id}:{target}"
        if outcome_key in state._counted_correlations:
            return
        state._counted_correlations.add(outcome_key)
        state._mark_learning_dirty("counted_correlations", outcome_key)
    counts = state._outcomes.get(target)
    if counts is None:
        counts = {"success": 0, "rollback": 0}
    counts[bucket] += 1
    state._outcomes.set(target, counts)
    state._mark_learning_dirty("outcomes", target)
    total = counts["success"] + counts["rollback"]
    if total < state._min_outcome_samples or target in state._outcome_proposed:
        return
    rollback_rate = counts["rollback"] / total
    if rollback_rate <= state._rollback_alarm_rate:
        return
    state._outcome_proposed.add(target)
    state._mark_learning_dirty("outcome_proposed", target)
    state._append_candidate(
        {
            "source_signal": "audit_outcome",
            "evidence": {
                "target": target,
                "sample_size": total,
                "rollback_rate": round(rollback_rate, 4),
                "alarm_rate": state._rollback_alarm_rate,
            },
            "proposed_by": "Norns",
            "proposal_kind": "threshold_adjustment",
            "suggested_change": "raise_confidence_threshold",
            "target_rule_id": target,
        }
    )


def retain_shadow_dwell(
    state: NornsLearningState,
    target: str,
    payload: Mapping[str, Any],
) -> None:
    """Retain one valid, deduplicated judge-and-log-only observation."""
    if not target:
        state.record_behavior("shadow_dwell_observation_invalid")
        return
    correlation_id = str(payload.get("correlation_id", ""))
    observation_id = str(payload.get("shadow_observation_id") or correlation_id)
    review_update = payload.get("shadow_review_update", False)
    if not isinstance(review_update, bool):
        state.record_behavior("shadow_dwell_observation_invalid")
        return
    if review_update:
        reviewed = payload.get("operator_reviewed")
        agreed = payload.get("operator_agreed")
        escape = payload.get("policy_escape")
        if reviewed is not True or not isinstance(agreed, bool) or not isinstance(escape, bool):
            state.record_behavior("shadow_dwell_review_invalid")
            return
        try:
            applied = state._shadow_dwell.apply_review(
                target=target,
                observation_id=observation_id,
                agreed=agreed,
            )
        except ShadowDwellEvidenceError:
            state.record_behavior("shadow_dwell_review_invalid")
            return
        state.record_behavior(
            "shadow_dwell_review_applied" if applied else "shadow_dwell_review_unmatched"
        )
        return
    instant = _shadow_observed_at(payload)
    if instant is None:
        state.record_behavior("shadow_dwell_observation_untimed")
        return
    reviewed = payload.get("operator_reviewed", False)
    agreed = payload.get("operator_agreed", False)
    escape = payload.get("policy_escape", False)
    if not all(isinstance(flag, bool) for flag in (reviewed, agreed, escape)):
        state.record_behavior("shadow_dwell_observation_invalid")
        return
    if correlation_id:
        dwell_key = f"shadow:{correlation_id}:{target}"
        if dwell_key in state._counted_shadow_outcomes:
            return
        state._counted_shadow_outcomes.add(dwell_key)
    try:
        observation = ShadowDwellObservation(
            target=target,
            observed_at=instant,
            reviewed=reviewed,
            agreed=agreed and reviewed,
            policy_escape=escape,
        )
    except ShadowDwellEvidenceError:
        state.record_behavior("shadow_dwell_observation_invalid")
        return
    state._shadow_dwell.record(
        observation,
        observation_id=observation_id if observation_id else None,
    )
    state.record_behavior("shadow_dwell_observation_retained")


def shadow_dwell_evidence(
    state: NornsLearningState,
    target: str,
) -> ShadowDwellEvidence | None:
    """Return retained dwell evidence without changing candidate authority."""
    return state._shadow_dwell.evidence_for(target)


def observe_approval(state: NornsLearningState, payload: Mapping[str, Any]) -> None:
    """Propose an inert revision after recurring human rejections."""
    if payload.get("producer_principal") != "Var":
        state.record_behavior("approval:invalid_producer")
        return
    action_type = str(payload.get("action_type") or "")
    decision = str(payload.get("state", "")).strip().lower()
    if not action_type or decision not in ("approved", "rejected"):
        state.record_behavior("approval:invalid")
        return
    correlation_id = str(payload.get("correlation_id", ""))
    if correlation_id:
        if correlation_id in state._counted_approvals:
            return
        state._counted_approvals.add(correlation_id)
        state._mark_learning_dirty("counted_approvals", correlation_id)
    counts = state._approval_counts.get(action_type)
    if counts is None:
        counts = {"approved": 0, "rejected": 0}
    counts[decision] += 1
    state._approval_counts.set(action_type, counts)
    state._mark_learning_dirty("approval_counts", action_type)
    if decision != "rejected" or action_type in state._approval_proposed:
        return
    if counts["rejected"] < state._rejection_revise_threshold:
        return
    state._approval_proposed.add(action_type)
    state._mark_learning_dirty("approval_proposed", action_type)
    state._append_candidate(
        {
            "source_signal": "recurring_hil_rejection",
            "evidence": {
                "action_type": action_type,
                "rejection_count": counts["rejected"],
                "sample_size": counts["approved"] + counts["rejected"],
            },
            "proposed_by": "Norns",
            "proposal_kind": "revision",
            "target_rule_id": action_type,
        }
    )


def observe_override(state: NornsLearningState, payload: Mapping[str, Any]) -> None:
    """Propose an inert revision or retirement after recurring overrides."""
    state._ensure_pending_capacity()
    rule_id = str(payload.get("rule_id") or payload.get("target_rule_id") or "")
    event = str(payload.get("event", "create")).lower()
    if not rule_id or event not in ("create", "modify"):
        return
    count = (state._override_counter.get(rule_id) or 0) + 1
    state._override_counter.set(rule_id, count)
    if count < state._override_retire_threshold or rule_id in state._override_proposed:
        return
    state._override_proposed.add(rule_id)
    mode = str(payload.get("mode", ""))
    kind = "retirement" if mode == "disabled" else "revision"
    state._append_candidate(
        {
            "source_signal": "recurring_override",
            "evidence": {
                "rule_id": rule_id,
                "override_count": count,
                "latest_mode": mode,
            },
            "proposed_by": "Norns",
            "proposal_kind": kind,
            "target_rule_id": rule_id,
        }
    )


def _shadow_observed_at(payload: Mapping[str, Any]) -> datetime | None:
    for key in _SHADOW_INSTANT_KEYS:
        value = payload.get(key)
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else None
        if isinstance(value, str) and len(value) <= 64:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                continue
            if parsed.tzinfo is not None:
                return parsed
    return None


__all__ = [
    "NornsLearningState",
    "observe_approval",
    "observe_fingerprint",
    "observe_outcome",
    "observe_override",
    "retain_shadow_dwell",
    "shadow_dwell_evidence",
]


_LEARNING_STATE_KEY = "pantheon/norns/learning-state"
_LEARNING_STATE_PREFIX = "pantheon/norns/learning-state-deltas"
_LEARNING_STATE_PAGE = 128
_LEARNING_BUCKETS = (
    "outcomes",
    "outcome_proposed",
    "counted_correlations",
    "approval_counts",
    "approval_proposed",
    "counted_approvals",
    "forecast_error_counts",
    "forecast_error_proposed",
    "counted_case_revisions",
    "post_turn_hint_proposed",
)


class NornsCapacityError(RuntimeError):
    """Pending proposals are saturated; the caller must retry or dead-letter."""


class NornsLearningStateMixin:
    """Persist deterministic learner counters and idempotency fences."""

    _learning_state_store: StateStore | None
    _learning_state_recovered: bool
    _learning_dirty: dict[str, set[str]]
    _outcomes: BoundedLruDict[str, dict[str, int]]
    _outcome_proposed: BoundedLruSet[str]
    _counted_correlations: BoundedLruSet[str]
    _approval_counts: BoundedLruDict[str, dict[str, int]]
    _approval_proposed: BoundedLruSet[str]
    _counted_approvals: BoundedLruSet[str]
    _forecast_error_counts: BoundedLruDict[str, int]
    _forecast_error_proposed: BoundedLruSet[str]
    _counted_case_revisions: BoundedLruSet[str]
    _post_turn_hint_proposed: BoundedLruSet[str]
    pending_candidates: list[dict[str, Any]]
    _max_pending_candidates: int
    _candidate_terminal_counts: dict[str, int]
    _candidate_terminal_ids: BoundedLruSet[str]
    _pattern_validation_counts: dict[str, int]

    if TYPE_CHECKING:

        def record_behavior(self, name: str, amount: int = 1) -> None: ...

        def _index_pending_candidate(self, candidate: dict[str, Any]) -> None: ...

    async def recover_learning_state(self) -> int:
        """Restore durable learner counters and idempotency fences once."""
        if self._learning_state_recovered:
            return 0
        self._learning_state_recovered = True
        store = self._learning_state_store
        if store is None:
            return 0
        row = await store.read_state(_LEARNING_STATE_KEY)
        restored = 0
        if row is not None:
            self._load_learning_state(row)
            restored += 1
        for bucket in _LEARNING_BUCKETS:
            offset = 0
            while True:
                rows, _total = await store.read_state_page(
                    f"{_LEARNING_STATE_PREFIX}/{bucket}/",
                    limit=_LEARNING_STATE_PAGE,
                    offset=offset,
                )
                if not rows:
                    break
                for delta in rows:
                    self._load_learning_delta(delta)
                    restored += 1
                offset += len(rows)
        return 1 if restored else 0

    async def _ensure_learning_state(self) -> None:
        await self.recover_learning_state()

    async def _persist_learning_state(self) -> None:
        store = self._learning_state_store
        if store is None:
            return
        dirty = self._learning_dirty
        if not dirty:
            return
        self._learning_dirty = {}
        for bucket, keys in dirty.items():
            for item_key in keys:
                await self._persist_learning_delta(store, bucket, item_key)
            await store.delete_states_beyond(
                f"{_LEARNING_STATE_PREFIX}/{bucket}/",
                retain_newest=_MAX_TRACKED,
            )

    async def _persist_learning_delta(
        self,
        store: StateStore,
        bucket: str,
        item_key: str,
    ) -> None:
        value = self._learning_value(bucket, item_key)
        if value is None:
            return
        state_key = (
            f"{_LEARNING_STATE_PREFIX}/{bucket}/{hashlib.sha256(item_key.encode()).hexdigest()}"
        )
        current = await store.read_state(state_key)
        revision = int(current.get("revision", 0)) if current is not None else 0
        record = {
            "kind": "norns_learning_state_delta",
            "revision": revision + 1,
            "bucket": bucket,
            "item_key": item_key,
            "value": value,
        }
        audit = {
            "kind": "norns_learning_state_delta",
            "principal": "Norns",
            "bucket": bucket,
            "item_key_digest": hashlib.sha256(item_key.encode()).hexdigest(),
            "revision": revision + 1,
            "grants_authority": False,
        }
        if current is None:
            if await store.write_state_with_audit_if_absent(state_key, record, audit):
                return
            current = await store.read_state(state_key)
            revision = int(current.get("revision", 0)) if current is not None else 0
            record["revision"] = revision + 1
            audit["revision"] = revision + 1
        if not await store.compare_and_set_state_with_audit(
            state_key,
            record,
            expected_revision=revision,
            audit_entry=audit,
        ):
            self.record_behavior("learning_state:cas_conflict")
            raise RuntimeError("Norns learning state delta CAS did not converge")

    def _load_learning_state(self, row: Mapping[str, Any]) -> None:
        self._restore_counter_dict(self._outcomes, row.get("outcomes"), nested=True)
        self._restore_set(self._outcome_proposed, row.get("outcome_proposed"))
        self._restore_set(self._counted_correlations, row.get("counted_correlations"))
        self._restore_counter_dict(self._approval_counts, row.get("approval_counts"), nested=True)
        self._restore_set(self._approval_proposed, row.get("approval_proposed"))
        self._restore_set(self._counted_approvals, row.get("counted_approvals"))
        self._restore_counter_dict(
            self._forecast_error_counts,
            row.get("forecast_error_counts"),
            nested=False,
        )
        self._restore_set(self._forecast_error_proposed, row.get("forecast_error_proposed"))
        self._restore_set(self._counted_case_revisions, row.get("counted_case_revisions"))
        self._restore_set(self._post_turn_hint_proposed, row.get("post_turn_hint_proposed"))

    def _load_learning_delta(self, row: Mapping[str, Any]) -> None:
        if row.get("kind") != "norns_learning_state_delta":
            raise ValueError("Norns durable learner delta kind is invalid")
        bucket = str(row.get("bucket") or "")
        item_key = str(row.get("item_key") or "")
        if bucket not in _LEARNING_BUCKETS or not item_key:
            raise ValueError("Norns durable learner delta identity is invalid")
        value = row.get("value")
        if bucket == "outcomes":
            if not isinstance(value, Mapping):
                raise ValueError("Norns durable outcome delta is invalid")
            self._outcomes.set(item_key, {str(name): int(count) for name, count in value.items()})
        elif bucket == "approval_counts":
            if not isinstance(value, Mapping):
                raise ValueError("Norns durable approval delta is invalid")
            self._approval_counts.set(
                item_key, {str(name): int(count) for name, count in value.items()}
            )
        elif bucket == "forecast_error_counts":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError("Norns durable forecast delta is invalid")
            self._forecast_error_counts.set(item_key, int(value))
        elif isinstance(value, bool) and value:
            self._learning_set(bucket).add(item_key)
        else:
            raise ValueError("Norns durable learner set delta is invalid")

    def _learning_value(self, bucket: str, item_key: str) -> object | None:
        if bucket == "outcomes":
            return self._outcomes.get(item_key)
        if bucket == "approval_counts":
            return self._approval_counts.get(item_key)
        if bucket == "forecast_error_counts":
            return self._forecast_error_counts.get(item_key)
        return True if item_key in self._learning_set(bucket) else None

    def _learning_set(self, bucket: str) -> BoundedLruSet[str]:
        return {
            "outcome_proposed": self._outcome_proposed,
            "counted_correlations": self._counted_correlations,
            "approval_proposed": self._approval_proposed,
            "counted_approvals": self._counted_approvals,
            "forecast_error_proposed": self._forecast_error_proposed,
            "counted_case_revisions": self._counted_case_revisions,
            "post_turn_hint_proposed": self._post_turn_hint_proposed,
        }[bucket]

    def _mark_learning_dirty(self, bucket: str, item_key: str) -> None:
        if bucket not in _LEARNING_BUCKETS or not item_key:
            return
        self._learning_dirty.setdefault(bucket, set()).add(item_key)

    @staticmethod
    def _restore_set(target: BoundedLruSet[str], values: object) -> None:
        if values is None:
            return
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise ValueError("Norns durable learner set is invalid")
        for item in values:
            target.add(item)

    @staticmethod
    def _restore_counter_dict(
        target: BoundedLruDict[str, Any],
        values: object,
        *,
        nested: bool,
    ) -> None:
        if values is None:
            return
        if not isinstance(values, Mapping):
            raise ValueError("Norns durable learner counter is invalid")
        for key, value in values.items():
            if not isinstance(key, str):
                raise ValueError("Norns durable learner counter key is invalid")
            if nested:
                if not isinstance(value, Mapping):
                    raise ValueError("Norns durable nested learner counter is invalid")
                target.set(key, {str(name): int(count) for name, count in value.items()})
            else:
                target.set(key, int(value))

    def _append_candidate(self, candidate: dict[str, Any]) -> None:
        self._ensure_pending_capacity()
        self.pending_candidates.append(candidate)
        self._index_pending_candidate(candidate)

    def _ensure_pending_capacity(self) -> None:
        if len(self.pending_candidates) >= self._max_pending_candidates:
            raise NornsCapacityError("Norns pending candidate capacity exhausted")

    def _record_candidate_terminal(self, candidate: Mapping[str, Any], outcome: str) -> None:
        if outcome not in self._candidate_terminal_counts:
            return
        try:
            identity = canonical_json_digest(candidate)
        except (TypeError, ValueError):
            identity = content_digest({"candidate_identity": "non_json", "outcome": outcome})
        if identity in self._candidate_terminal_ids:
            return
        self._candidate_terminal_ids.add(identity)
        self._candidate_terminal_counts[outcome] += 1

    def observe_pattern_validation(self, *, valid: bool) -> None:
        """Record a bounded pattern validation outcome for KPI reporting."""

        key = "valid" if valid else "false"
        self._pattern_validation_counts[key] += 1
        self.record_behavior(f"pattern_validation:{key}")
