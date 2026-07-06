"""Phase-4 measurement runners — unit tests.

Covers the two scheduled runners wired in
:mod:`aiopspilot.core.measurement.runners`:

- :class:`AutomatedBaselineRunner` — regression triggers a demote via
  :class:`ActionPromotionRegistry`, PASS outcomes do not, and the
  scheduler NEVER auto-promotes.
- :class:`PatternGrowthIntakeRunner` — accepted intake pushes a pattern
  into the writer, rejected outcomes do not, and every ingested pattern
  is stripped down to shadow-mode (``success_rate == 0.0``,
  ``reuse_count == 0``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import pytest

from aiopspilot.core.measurement.pattern_growth import (
    IntakeOutcome,
    OutcomeRecord,
)
from aiopspilot.core.measurement.regression import (
    GuardKind,
    GuardMetric,
    MeasurementSample,
    RegressionDetector,
    RegressionOutcome,
    SuccessMetric,
)
from aiopspilot.core.measurement.runners import (
    AutomatedBaselineRunner,
    OutcomeSource,
    PatternBuilder,
    PatternGrowthIntakeRunner,
    ScenarioReplayer,
)
from aiopspilot.core.risk_gate.gate import (
    ActionModeRecord,
    ActionPromotionRegistry,
    PromotionMetrics,
)
from aiopspilot.core.tiers.t1_lightweight.testing import InMemoryPatternLibrary
from aiopspilot.core.tiers.t1_lightweight.tier import LearnedAction
from aiopspilot.rule_catalog.schema.action_type import load_action_type_catalog
from aiopspilot.shared.contracts.models import Mode, OntologyActionType
from aiopspilot.shared.contracts.registry import PackageResourceSchemaRegistry
from aiopspilot.shared.providers.testing.state_store import InMemoryStateStore

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ACTION_TYPES_ROOT = _REPO_ROOT / "rule-catalog" / "action-types"


@lru_cache(maxsize=1)
def _shipped_action_types() -> dict[str, OntologyActionType]:
    registry = PackageResourceSchemaRegistry()
    return {
        at.name: at for at in load_action_type_catalog(_ACTION_TYPES_ROOT, schema_registry=registry)
    }


def _load_action_type(name: str) -> OntologyActionType:
    return _shipped_action_types()[name]


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FixedReplayer(ScenarioReplayer):
    """Static :class:`ScenarioReplayer` yielding a preset sample list."""

    def __init__(
        self,
        *,
        version: str,
        samples: Sequence[MeasurementSample],
        raises: Exception | None = None,
    ) -> None:
        self.scenario_set_version = version
        self._samples = tuple(samples)
        self._raises = raises

    async def replay(self) -> Sequence[MeasurementSample]:
        if self._raises is not None:
            raise self._raises
        return self._samples


class _ScriptedOutcomeSource(OutcomeSource):
    """OutcomeSource that yields a preset list once."""

    def __init__(self, records: Sequence[OutcomeRecord]) -> None:
        self._records = tuple(records)

    def outcomes(self) -> AsyncIterator[OutcomeRecord]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[OutcomeRecord]:
        for record in self._records:
            yield record


class _ScriptedBuilder(PatternBuilder):
    """PatternBuilder that returns preset (vector, action) pairs or None."""

    def __init__(
        self,
        *,
        results: dict[str, tuple[Sequence[float], LearnedAction] | None],
    ) -> None:
        self._results = dict(results)
        self.calls: list[str] = []

    async def build(self, record: OutcomeRecord) -> tuple[Sequence[float], LearnedAction] | None:
        self.calls.append(record.action_id)
        return self._results.get(record.action_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pass_sample(action_type: str) -> MeasurementSample:
    return MeasurementSample(
        action_type_id=action_type,
        scenario_set_version="v2026.07",
        guard_metrics=(GuardMetric(GuardKind.ROLLBACK_RATE, ceiling=0.05, observed=0.01),),
        success_metrics=(SuccessMetric(name="auto_share", lower_ci=0.4, observed=0.55),),
    )


def _breach_sample(action_type: str) -> MeasurementSample:
    return MeasurementSample(
        action_type_id=action_type,
        scenario_set_version="v2026.07",
        guard_metrics=(GuardMetric(GuardKind.POLICY_VIOLATION_ESCAPE, ceiling=0.0, observed=1.0),),
    )


def _drop_sample(action_type: str) -> MeasurementSample:
    return MeasurementSample(
        action_type_id=action_type,
        scenario_set_version="v2026.07",
        success_metrics=(SuccessMetric(name="auto_share", lower_ci=0.5, observed=0.3),),
    )


def _pattern_metrics(action_type_name: str) -> PromotionMetrics:
    """Metrics that would clear the promotion gate for the shipped ActionType."""
    return PromotionMetrics(
        action_type=action_type_name,
        shadow_days=999,
        samples=10_000,
        accuracy=1.0,
        policy_escapes=0,
    )


def _outcome(
    *,
    action_id: str,
    action_type_id: str = "remediate.tag-add",
    was_auto: bool = True,
    was_verified: bool = True,
    was_rolled_back: bool = False,
) -> OutcomeRecord:
    return OutcomeRecord(
        action_id=action_id,
        action_type_id=action_type_id,
        observed_at=datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC),
        was_auto=was_auto,
        was_verified=was_verified,
        was_rolled_back=was_rolled_back,
    )


def _learned_action(
    *,
    signature: str,
    success_rate: float = 0.99,
    reuse_count: int = 42,
) -> LearnedAction:
    return LearnedAction(
        signature=signature,
        rule_id="rg.tagging.owner-required",
        action_type="remediate.tag-add",
        params={"tag": "owner"},
        incident_id=f"incident-{signature}",
        success_rate=success_rate,
        reuse_count=reuse_count,
    )


# ---------------------------------------------------------------------------
# AutomatedBaselineRunner
# ---------------------------------------------------------------------------


async def test_baseline_pass_writes_pass_audit_and_does_not_demote() -> None:
    registry = ActionPromotionRegistry()
    audit = InMemoryStateStore()
    runner = AutomatedBaselineRunner(
        replayer=_FixedReplayer(
            version="v2026.07",
            samples=(_pass_sample("remediate.tag-add"),),
        ),
        detector=RegressionDetector(),
        registry=registry,
        audit_store=audit,
    )

    report = await runner.run_once()

    assert not report.had_regression
    assert report.sample_count == 1
    assert report.demoted_action_types == ()
    # Registry untouched → mode_of returns SHADOW as the default.
    assert registry.record("remediate.tag-add") is None
    # Exactly one audit entry — the aggregate run record. PASS never
    # writes a per-sample entry (audit trail is only "regression events").
    entries = list(audit.audit_entries)
    assert len(entries) == 1
    run = entries[0]["entry"]
    assert run["action_kind"] == "measurement.regression.run"
    assert run["outcome"] == "pass"
    assert run["regression_count"] == 0


async def test_baseline_guard_breach_demotes_and_audits() -> None:
    tag_add = _load_action_type("remediate.tag-add")
    # Promote FIRST so the demote transitions ENFORCE → SHADOW and stamps
    # demoted_at (the interesting audited transition).
    registry = ActionPromotionRegistry()
    promoted = registry.consider_promotion(
        action_type=tag_add,
        metrics=_pattern_metrics(tag_add.name),
    )
    assert promoted.mode is Mode.ENFORCE

    audit = InMemoryStateStore()
    runner = AutomatedBaselineRunner(
        replayer=_FixedReplayer(
            version="v2026.07",
            samples=(_breach_sample(tag_add.name),),
        ),
        detector=RegressionDetector(),
        registry=registry,
        audit_store=audit,
    )

    report = await runner.run_once()

    assert report.had_regression
    assert report.sample_count == 1
    assert report.demoted_action_types == (tag_add.name,)
    assert len(report.regressions) == 1
    assert report.regressions[0].outcome is RegressionOutcome.GUARD_BREACH

    # Registry now records SHADOW with demoted_at stamped.
    record = registry.record(tag_add.name)
    assert record is not None
    assert record.mode is Mode.SHADOW
    assert record.demoted_at is not None

    # Two audits: one per-sample regression entry + one aggregate run entry.
    entries = [e["entry"] for e in audit.audit_entries]
    assert [e["action_kind"] for e in entries] == [
        "measurement.regression.demote",
        "measurement.regression.run",
    ]
    demote_entry = entries[0]
    assert demote_entry["action_type_id"] == tag_add.name
    assert demote_entry["outcome"] == RegressionOutcome.GUARD_BREACH.value
    assert demote_entry["effective_mode"] == Mode.SHADOW.value
    assert any("policy_violation_escape" in r for r in demote_entry["reasons"])

    run_entry = entries[1]
    assert run_entry["outcome"] == "regression"
    assert run_entry["demoted_action_types"] == [tag_add.name]


async def test_baseline_success_drop_also_triggers_demote() -> None:
    registry = ActionPromotionRegistry()
    audit = InMemoryStateStore()
    runner = AutomatedBaselineRunner(
        replayer=_FixedReplayer(
            version="v2026.07",
            samples=(_drop_sample("remediate.tag-add"),),
        ),
        detector=RegressionDetector(),
        registry=registry,
        audit_store=audit,
    )

    report = await runner.run_once()
    assert report.had_regression
    assert report.regressions[0].outcome is RegressionOutcome.SUCCESS_DROP
    assert report.demoted_action_types == ("remediate.tag-add",)


async def test_baseline_never_promotes() -> None:
    """The runner is a one-way street to shadow — no PASS sample ever calls promote."""
    registry = ActionPromotionRegistry()
    audit = InMemoryStateStore()

    # Sentinel: monkey-patch consider_promotion so any accidental call raises.
    def _forbidden(**_: object) -> ActionModeRecord:
        raise AssertionError("AutomatedBaselineRunner MUST NOT auto-promote")

    registry.consider_promotion = _forbidden  # type: ignore[method-assign]

    runner = AutomatedBaselineRunner(
        replayer=_FixedReplayer(
            version="v2026.07",
            samples=(
                _pass_sample("remediate.tag-add"),
                _breach_sample("remediate.disable-public-access"),
            ),
        ),
        detector=RegressionDetector(),
        registry=registry,
        audit_store=audit,
    )

    report = await runner.run_once()
    # PASS ActionType stays unrecorded; breach ActionType is demoted.
    assert registry.record("remediate.tag-add") is None
    record = registry.record("remediate.disable-public-access")
    assert record is not None
    assert record.mode is Mode.SHADOW
    assert report.demoted_action_types == ("remediate.disable-public-access",)


async def test_baseline_multiple_samples_partitioned_correctly() -> None:
    registry = ActionPromotionRegistry()
    audit = InMemoryStateStore()
    runner = AutomatedBaselineRunner(
        replayer=_FixedReplayer(
            version="v2026.07",
            samples=(
                _pass_sample("remediate.tag-add"),
                _breach_sample("remediate.disable-public-access"),
                _drop_sample("remediate.enable-encryption"),
            ),
        ),
        detector=RegressionDetector(),
        registry=registry,
        audit_store=audit,
    )

    report = await runner.run_once()
    assert report.sample_count == 3
    assert set(report.demoted_action_types) == {
        "remediate.disable-public-access",
        "remediate.enable-encryption",
    }
    # 2 per-sample regression audits + 1 aggregate.
    kinds = [e["entry"]["action_kind"] for e in audit.audit_entries]
    assert kinds.count("measurement.regression.demote") == 2
    assert kinds.count("measurement.regression.run") == 1


async def test_baseline_replayer_failure_aborts_without_registry_mutation() -> None:
    class _BoomError(RuntimeError):
        pass

    registry = ActionPromotionRegistry()
    audit = InMemoryStateStore()
    runner = AutomatedBaselineRunner(
        replayer=_FixedReplayer(
            version="v2026.07",
            samples=(),
            raises=_BoomError("scenario source unavailable"),
        ),
        detector=RegressionDetector(),
        registry=registry,
        audit_store=audit,
    )

    report = await runner.run_once()
    assert report.aborted_reason is not None
    assert "scenario_replay_failed" in report.aborted_reason
    assert report.sample_count == 0
    assert report.demoted_action_types == ()

    # Exactly one abort audit entry; no registry mutation.
    entries = [e["entry"] for e in audit.audit_entries]
    assert len(entries) == 1
    assert entries[0]["action_kind"] == "measurement.regression.run"
    assert entries[0]["outcome"] == "aborted"


# ---------------------------------------------------------------------------
# PatternGrowthIntakeRunner
# ---------------------------------------------------------------------------


async def test_growth_accepted_intake_pushes_shadow_pattern() -> None:
    library = InMemoryPatternLibrary()
    audit = InMemoryStateStore()
    action = _learned_action(signature="pattern-alpha", success_rate=0.95, reuse_count=17)
    builder = _ScriptedBuilder(
        results={"action-1": ([0.5, 0.5], action)},
    )
    outcomes = _ScriptedOutcomeSource((_outcome(action_id="action-1"),))
    runner = PatternGrowthIntakeRunner(
        outcome_source=outcomes,
        pattern_builder=builder,
        writer=library,
        audit_store=audit,
    )

    report = await runner.run_once()
    assert report.total_outcomes == 1
    assert report.accepted_count == 1
    assert report.rejected_count == 0
    assert report.ingested_signatures == ("pattern-alpha",)
    assert builder.calls == ["action-1"]

    # Shadow-first invariant: even though the builder returned
    # success_rate=0.95 and reuse_count=17, the persisted pattern must
    # carry the shadow defaults.
    assert len(library) == 1
    matches = await library.search([0.5, 0.5], k=1)
    top = matches[0].action
    assert top.signature == "pattern-alpha"
    assert top.success_rate == 0.0
    assert top.reuse_count == 0

    # Intake audit entry confirms shadow-mode ingestion.
    entry = list(audit.audit_entries)[0]["entry"]
    assert entry["action_kind"] == "measurement.pattern_growth.intake"
    assert entry["mode"] == Mode.SHADOW.value
    assert entry["intake_outcome"] == IntakeOutcome.ACCEPTED.value
    assert entry["ingested"] is True
    assert entry["signature"] == "pattern-alpha"


async def test_growth_rejects_rolled_back_outcomes() -> None:
    library = InMemoryPatternLibrary()
    audit = InMemoryStateStore()
    builder = _ScriptedBuilder(results={})
    outcomes = _ScriptedOutcomeSource((_outcome(action_id="rolled-back", was_rolled_back=True),))
    runner = PatternGrowthIntakeRunner(
        outcome_source=outcomes,
        pattern_builder=builder,
        writer=library,
        audit_store=audit,
    )

    report = await runner.run_once()
    assert report.rejected_count == 1
    assert report.accepted_count == 0
    assert len(library) == 0
    # Builder is NEVER called for a rejected outcome.
    assert builder.calls == []

    entry = list(audit.audit_entries)[0]["entry"]
    assert entry["intake_outcome"] == IntakeOutcome.REJECTED_ROLLED_BACK.value
    assert entry["ingested"] is False


async def test_growth_rejects_hil_outcomes() -> None:
    library = InMemoryPatternLibrary()
    audit = InMemoryStateStore()
    builder = _ScriptedBuilder(results={})
    outcomes = _ScriptedOutcomeSource((_outcome(action_id="hil-approved", was_auto=False),))
    runner = PatternGrowthIntakeRunner(
        outcome_source=outcomes,
        pattern_builder=builder,
        writer=library,
        audit_store=audit,
    )

    report = await runner.run_once()
    assert report.rejected_count == 1
    assert report.ingested_signatures == ()
    entry = list(audit.audit_entries)[0]["entry"]
    assert entry["intake_outcome"] == IntakeOutcome.REJECTED_NOT_AUTO.value


async def test_growth_rejects_unverified_outcomes() -> None:
    library = InMemoryPatternLibrary()
    audit = InMemoryStateStore()
    outcomes = _ScriptedOutcomeSource((_outcome(action_id="not-verified", was_verified=False),))
    runner = PatternGrowthIntakeRunner(
        outcome_source=outcomes,
        pattern_builder=_ScriptedBuilder(results={}),
        writer=library,
        audit_store=audit,
    )

    report = await runner.run_once()
    assert report.rejected_count == 1
    entry = list(audit.audit_entries)[0]["entry"]
    assert entry["intake_outcome"] == IntakeOutcome.REJECTED_NOT_VERIFIED.value


async def test_growth_missing_pattern_build_records_skip_but_continues() -> None:
    library = InMemoryPatternLibrary()
    audit = InMemoryStateStore()
    action = _learned_action(signature="pattern-beta")
    builder = _ScriptedBuilder(
        results={
            "action-1": None,  # builder cannot rebuild — skip
            "action-2": ([0.1, 0.9], action),
        },
    )
    outcomes = _ScriptedOutcomeSource(
        (
            _outcome(action_id="action-1"),
            _outcome(action_id="action-2"),
        )
    )
    runner = PatternGrowthIntakeRunner(
        outcome_source=outcomes,
        pattern_builder=builder,
        writer=library,
        audit_store=audit,
    )

    report = await runner.run_once()
    assert report.total_outcomes == 2
    assert report.accepted_count == 1
    assert report.build_failures == 1
    assert report.ingested_signatures == ("pattern-beta",)
    # Builder called for BOTH accepted outcomes (skip is post-accept).
    assert builder.calls == ["action-1", "action-2"]

    entries = [e["entry"] for e in audit.audit_entries]
    assert len(entries) == 2
    # First outcome — accepted intake, but builder returned None → not ingested.
    assert entries[0]["intake_outcome"] == IntakeOutcome.ACCEPTED.value
    assert entries[0]["ingested"] is False
    assert entries[0]["reason"] == "pattern_builder_returned_none"
    # Second outcome — accepted + ingested.
    assert entries[1]["intake_outcome"] == IntakeOutcome.ACCEPTED.value
    assert entries[1]["ingested"] is True


async def test_growth_never_upserts_non_shadow_pattern() -> None:
    """Shadow-first invariant: no matter what the builder returns, the persisted
    pattern MUST carry ``success_rate == 0.0`` and ``reuse_count == 0``."""

    class _RecordingLibrary(InMemoryPatternLibrary):
        def __init__(self) -> None:
            super().__init__()
            self.upsert_calls: list[LearnedAction] = []

        async def upsert_pattern(self, *, vector: Sequence[float], action: LearnedAction) -> None:
            self.upsert_calls.append(action)
            await super().upsert_pattern(vector=vector, action=action)

    library = _RecordingLibrary()
    # Builder deliberately returns "already promoted" values.
    hot = _learned_action(signature="hot-pattern", success_rate=1.0, reuse_count=999)
    builder = _ScriptedBuilder(results={"a": ([1.0], hot)})
    outcomes = _ScriptedOutcomeSource((_outcome(action_id="a"),))
    audit = InMemoryStateStore()
    runner = PatternGrowthIntakeRunner(
        outcome_source=outcomes,
        pattern_builder=builder,
        writer=library,
        audit_store=audit,
    )

    await runner.run_once()

    assert len(library.upsert_calls) == 1
    persisted = library.upsert_calls[0]
    assert persisted.success_rate == 0.0
    assert persisted.reuse_count == 0
    # But the rest of the LearnedAction survives.
    assert persisted.signature == "hot-pattern"
    assert persisted.rule_id == hot.rule_id
    assert persisted.action_type == hot.action_type
    # And the runner did not mutate the builder's original dataclass —
    # frozen replace() gives us a fresh instance.
    assert hot.success_rate == 1.0
    assert hot.reuse_count == 999
    # Confirm dataclasses.replace was used implicitly by producing a new
    # instance, not the same one.
    assert persisted is not hot
    _ = replace  # keep import referenced when the test suite is trimmed


async def test_growth_upsert_dedupes_by_signature() -> None:
    """Two intakes of the same signature MUST NOT create duplicate library rows."""
    library = InMemoryPatternLibrary()
    audit = InMemoryStateStore()
    action = _learned_action(signature="dupe")
    builder = _ScriptedBuilder(
        results={
            "action-1": ([0.7, 0.3], action),
            "action-2": ([0.7, 0.3], action),
        }
    )
    outcomes = _ScriptedOutcomeSource(
        (
            _outcome(action_id="action-1"),
            _outcome(action_id="action-2"),
        )
    )
    runner = PatternGrowthIntakeRunner(
        outcome_source=outcomes,
        pattern_builder=builder,
        writer=library,
        audit_store=audit,
    )

    report = await runner.run_once()
    assert report.accepted_count == 2
    # Only one persisted row — the second upsert updates in place.
    assert len(library) == 1


async def test_growth_empty_stream_is_a_no_op() -> None:
    library = InMemoryPatternLibrary()
    audit = InMemoryStateStore()
    runner = PatternGrowthIntakeRunner(
        outcome_source=_ScriptedOutcomeSource(()),
        pattern_builder=_ScriptedBuilder(results={}),
        writer=library,
        audit_store=audit,
    )

    report = await runner.run_once()
    assert report.total_outcomes == 0
    assert report.accepted_count == 0
    assert report.rejected_count == 0
    assert len(library) == 0
    assert list(audit.audit_entries) == []


# ---------------------------------------------------------------------------
# demote() extension on ActionPromotionRegistry
# ---------------------------------------------------------------------------


def test_registry_demote_of_new_action_type_creates_shadow_record() -> None:
    registry = ActionPromotionRegistry()
    record = registry.demote("remediate.tag-add")
    assert record.mode is Mode.SHADOW
    assert record.demoted_at is None  # nothing was previously enforced
    assert registry.record("remediate.tag-add") is record


def test_registry_demote_from_enforce_stamps_demoted_at() -> None:
    at = _load_action_type("remediate.tag-add")
    registry = ActionPromotionRegistry()
    registry.consider_promotion(action_type=at, metrics=_pattern_metrics(at.name))
    assert registry.record(at.name) is not None
    assert registry.record(at.name).mode is Mode.ENFORCE  # type: ignore[union-attr]

    demoted = registry.demote(at.name)
    assert demoted.mode is Mode.SHADOW
    assert demoted.demoted_at is not None


def test_registry_demote_idempotent_on_shadow() -> None:
    registry = ActionPromotionRegistry()
    first = registry.demote("remediate.tag-add")
    second = registry.demote("remediate.tag-add")
    # Both are shadow; the second demote does not re-stamp demoted_at
    # (there was no ENFORCE → SHADOW transition to record).
    assert first.mode is Mode.SHADOW
    assert second.mode is Mode.SHADOW
    assert first.demoted_at is None
    assert second.demoted_at is None


def test_registry_demote_rejects_empty_name() -> None:
    registry = ActionPromotionRegistry()
    with pytest.raises(ValueError, match="MUST NOT be empty"):
        registry.demote("")
