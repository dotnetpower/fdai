"""Forseti-owned baseline worker: discover, claim, evaluate, and account one inventory generation.

The worker reads the active promoted inventory through a read-only provider, takes an atomic claim
per inventory observation and Rule activation generation, evaluates every pair with the same T0
engine decisions use, and records a version 2 coverage record whose denominator comes from T0
dispatch rather than from the outcomes it wrote. It writes Forseti-attributed entries through the
append-only audit store and never calls another agent. Nothing here grants execution authority.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from fdai_service_contracts.baseline_evaluation import (
    BaselineEvaluationCoverage,
    BaselineEvaluationCoverageLimitation,
    baseline_evaluation_coverage_digest,
)
from fdai_service_contracts.rule_activation import RuleActivationGeneration

from fdai.agents._framework.forseti_baseline_evaluation import (
    BaselineEvaluationAuditReference,
    baseline_inventory_observation_digest,
    evaluate_baseline_records,
)
from fdai.core.framework_rule_evidence import (
    INVENTORY_OBSERVATION_SIGNAL,
    ScopedRuleCoverage,
    WorkloadRuleResource,
    build_scoped_coverage,
    canonical_sha256,
    expected_rule_pairs,
)
from fdai.core.rule_activation.generation import rule_digest
from fdai.core.tiers.t0_deterministic import RuleGenerationSnapshot
from fdai.shared.contracts.models import Rule
from fdai.shared.providers.inventory import (
    PromotedInventoryGeneration,
    PromotedInventoryGenerationLimitError,
    PromotedInventoryGenerationReader,
    PromotedInventoryGenerationUnavailableError,
)
from fdai.shared.providers.state_store import StateStore

BASELINE_EVALUATION_CLAIM_PREFIX = "baseline-evaluation:claims:"
BASELINE_EVALUATION_COVERAGE_PREFIX = "baseline-evaluation:coverage:"
BASELINE_EVALUATION_STATUS_KEY = "baseline-evaluation:status:latest"
BASELINE_EVALUATION_LATEST_COVERAGE_KEY = "baseline-evaluation:latest:coverage"

_LOG = logging.getLogger("fdai.agents.forseti.baseline")

ActivationSource = Callable[[], Awaitable[RuleActivationGeneration | None]]
RuleSnapshotSource = Callable[[], Awaitable[RuleGenerationSnapshot]]


class BaselineWorkerResult(StrEnum):
    """Terminal result of one bounded worker run."""

    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    ALREADY_COMPLETED = "already_completed"
    UNCHANGED = "unchanged"
    CLAIMED_ELSEWHERE = "claimed_elsewhere"
    NO_GENERATION = "no_generation"
    ACTIVATION_UNAVAILABLE = "activation_unavailable"
    ACTIVATION_DRIFT = "activation_drift"
    GENERATION_TOO_LARGE = "generation_too_large"
    GENERATION_UNAVAILABLE = "generation_unavailable"
    DEADLINE_EXCEEDED = "deadline_exceeded"


@dataclass(frozen=True, slots=True)
class BaselineWorkerLimits:
    """Bounds that keep one run predictable."""

    max_resources: int = 20_000
    deadline_seconds: float = 600.0
    claim_lease_seconds: float = 900.0

    def __post_init__(self) -> None:
        if self.max_resources < 1 or self.deadline_seconds <= 0:
            raise ValueError("baseline worker limits MUST be positive")
        if self.claim_lease_seconds <= self.deadline_seconds:
            raise ValueError("baseline worker claim lease MUST outlast the run deadline")


def baseline_claim_key(*, inventory_observation_digest: str, activation_digest: str) -> str:
    """Return the claim key for one inventory observation and activation generation pair."""

    material = f"{inventory_observation_digest}|{canonical_sha256(activation_digest)}"
    return BASELINE_EVALUATION_CLAIM_PREFIX + hashlib.sha256(material.encode()).hexdigest()


def baseline_coverage_key(*, inventory_observation_digest: str, activation_digest: str) -> str:
    """Return the stable coverage key for one inventory observation and activation pair."""

    material = f"{inventory_observation_digest}|{canonical_sha256(activation_digest)}"
    return BASELINE_EVALUATION_COVERAGE_PREFIX + hashlib.sha256(material.encode()).hexdigest()


class ForsetiBaselineWorker:
    """Run at most one bounded baseline evaluation per call."""

    def __init__(
        self,
        *,
        state_store: StateStore,
        reader: PromotedInventoryGenerationReader,
        activation_source: ActivationSource,
        rule_snapshot_source: RuleSnapshotSource,
        owner: str,
        clock: Callable[[], datetime] | None = None,
        limits: BaselineWorkerLimits | None = None,
    ) -> None:
        if not owner.strip():
            raise ValueError("baseline worker owner MUST be non-empty")
        self._store = state_store
        self._reader = reader
        self._activation_source = activation_source
        self._rule_snapshot_source = rule_snapshot_source
        self._owner = owner
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._limits = limits or BaselineWorkerLimits()
        self._settled: tuple[str, str] | None = None
        self._observed_generation: str | None = None

    async def run_once(self) -> BaselineWorkerResult:
        """Run one bounded evaluation and record its terminal result as Forseti status."""

        activation = await self._activation_source()
        result = await self._run(activation)
        await self._record_status(result, activation)
        return result

    async def _run(self, activation: RuleActivationGeneration | None) -> BaselineWorkerResult:
        if activation is None:
            return BaselineWorkerResult.ACTIVATION_UNAVAILABLE
        snapshot = await self._rule_snapshot_source()
        if not _snapshot_matches(snapshot, activation):
            return BaselineWorkerResult.ACTIVATION_DRIFT
        try:
            generation_id = await self._reader.active_generation_id()
            if generation_id is None:
                return BaselineWorkerResult.NO_GENERATION
            if self._settled == (generation_id, activation.generation_digest):
                return BaselineWorkerResult.UNCHANGED
            generation = await self._reader.load_active_generation(
                max_resources=self._limits.max_resources
            )
        except PromotedInventoryGenerationLimitError:
            return BaselineWorkerResult.GENERATION_TOO_LARGE
        except PromotedInventoryGenerationUnavailableError:
            return BaselineWorkerResult.GENERATION_UNAVAILABLE
        if generation is None:
            return BaselineWorkerResult.NO_GENERATION
        if not generation.complete or generation.recorded_at is None:
            return BaselineWorkerResult.GENERATION_UNAVAILABLE
        self._observed_generation = generation.generation
        result = await self._run_generation(generation, snapshot, activation)
        if result in _SETTLED_RESULTS:
            self._settled = (generation.generation, activation.generation_digest)
        return result

    async def _run_generation(
        self,
        generation: PromotedInventoryGeneration,
        snapshot: RuleGenerationSnapshot,
        activation: RuleActivationGeneration,
    ) -> BaselineWorkerResult:

        observation_digest = baseline_inventory_observation_digest(generation)
        claim_key = baseline_claim_key(
            inventory_observation_digest=observation_digest,
            activation_digest=activation.generation_digest,
        )
        claim, refused = await self._claim(claim_key, observation_digest, activation)
        if claim is None:
            return refused or BaselineWorkerResult.CLAIMED_ELSEWHERE
        try:
            async with asyncio.timeout(self._limits.deadline_seconds):
                coverage = await self._evaluate(
                    generation=generation,
                    snapshot=snapshot,
                    activation=activation,
                    claim=claim,
                    observation_digest=observation_digest,
                )
        except TimeoutError:
            _LOG.warning("forseti_baseline_deadline_exceeded", extra={"claim": claim_key})
            return BaselineWorkerResult.DEADLINE_EXCEEDED
        await self._complete_claim(claim_key, claim, coverage)
        return (
            BaselineWorkerResult.COMPLETED if coverage.complete else BaselineWorkerResult.INCOMPLETE
        )

    async def _record_status(
        self,
        result: BaselineWorkerResult,
        activation: RuleActivationGeneration | None,
    ) -> None:
        if result is BaselineWorkerResult.UNCHANGED:
            return
        await self._store.write_state(
            BASELINE_EVALUATION_STATUS_KEY,
            {
                "schema_version": "1.0.0",
                "result": result.value,
                "recorded_at": self._clock().isoformat(),
                "rule_activation_generation_id": (
                    activation.generation_id if activation is not None else None
                ),
                "inventory_generation": self._observed_generation,
                "owner_agent": "Forseti",
                "execution_authority": False,
            },
        )

    async def _claim(
        self,
        key: str,
        observation_digest: str,
        activation: RuleActivationGeneration,
    ) -> tuple[dict[str, Any] | None, BaselineWorkerResult | None]:
        now = self._clock()
        record: dict[str, Any] = {
            "schema_version": "1.0.0",
            "status": "claimed",
            "revision": 1,
            "owner": self._owner,
            "evaluated_at": now.isoformat(),
            "lease_expires_at": (
                now + timedelta(seconds=self._limits.claim_lease_seconds)
            ).isoformat(),
            "inventory_observation_digest": observation_digest,
            "rule_activation_generation_id": activation.generation_id,
            "rule_activation_generation_digest": canonical_sha256(activation.generation_digest),
            "resumed": False,
            "execution_authority": False,
        }
        if await self._store.write_state_if_absent(key, record):
            return record, None
        existing = await self._store.read_state(key)
        if not isinstance(existing, Mapping):
            return None, BaselineWorkerResult.CLAIMED_ELSEWHERE
        if existing.get("status") == "completed":
            return None, BaselineWorkerResult.ALREADY_COMPLETED
        lease = _parse_time(existing.get("lease_expires_at"))
        if existing.get("status") != "claimed" or lease is None or lease > now:
            return None, BaselineWorkerResult.CLAIMED_ELSEWHERE
        revision = int(existing.get("revision", 1))
        # A stale claim keeps its evaluation time so re-run outcomes have identical digests.
        takeover = {
            **dict(existing),
            "revision": revision + 1,
            "owner": self._owner,
            "lease_expires_at": (
                now + timedelta(seconds=self._limits.claim_lease_seconds)
            ).isoformat(),
            "resumed": True,
        }
        if await self._store.compare_and_set_state(key, takeover, expected_revision=revision):
            return takeover, None
        return None, BaselineWorkerResult.CLAIMED_ELSEWHERE

    async def _evaluate(
        self,
        *,
        generation: PromotedInventoryGeneration,
        snapshot: RuleGenerationSnapshot,
        activation: RuleActivationGeneration,
        claim: Mapping[str, Any],
        observation_digest: str,
    ) -> BaselineEvaluationCoverage:
        evaluated_at = _parse_time(claim.get("evaluated_at"))
        if evaluated_at is None:
            raise ValueError("baseline claim evaluation time is malformed")
        evaluated_catalog = _rules_catalog_digest(snapshot.rules)
        intent = {
            "kind": "baseline_evaluation.started",
            "inventory_generation": generation.generation,
            "inventory_observation_digest": observation_digest,
            "rule_activation_generation_digest": canonical_sha256(activation.generation_digest),
            "evaluated_rule_catalog_digest": evaluated_catalog,
            "evaluated_at": evaluated_at.isoformat(),
        }
        reference = await self._append_audit(
            "baseline_evaluation.resumed" if claim.get("resumed") else intent["kind"],
            intent,
        )

        async def fixed_binder(_record: Mapping[str, Any]) -> BaselineEvaluationAuditReference:
            return reference

        completion, outcomes = await evaluate_baseline_records(
            observation=generation,
            engine=snapshot.engine,
            rules=snapshot.rules,
            catalog_revision=evaluated_catalog,
            audit_binder=fixed_binder,
            state_store=self._store,
            evaluated_at=evaluated_at,
        )
        if generation.recorded_at is None:
            raise ValueError("baseline inventory generation has no recorded time")
        workload = tuple(
            WorkloadRuleResource(resource_id=item.resource_id, resource_type=item.type)
            for item in generation.resources
        )
        expected = expected_rule_pairs(resources=workload, index=snapshot.engine.index)
        scoped = build_scoped_coverage(
            scope_digest=observation_digest,
            resources=workload,
            expected_pairs=expected,
            outcomes=outcomes,
            activation=activation,
            requested_rule_ids=(),
            inventory_generation=generation.generation,
            inventory_observed_at=generation.recorded_at,
            recorded_at=max(self._clock(), generation.recorded_at),
        )
        values = _coverage_values(
            scoped=scoped,
            expected_pair_set_digest=_expected_pair_set_digest(expected),
            generation_id=completion.generation_id,
            generation_digest=completion.generation_digest,
            observation_digest=observation_digest,
            activation=activation,
            evaluated_catalog=evaluated_catalog,
            outcome_set_digest=completion.outcome_set_digest,
            completed_at=evaluated_at,
        )
        coverage_audit = await self._append_audit(
            "baseline_evaluation.coverage",
            {key: value for key, value in values.items() if key != "completed_at"},
        )
        values["audit_ref"] = coverage_audit.ref
        values["audit_digest"] = coverage_audit.digest
        values["coverage_digest"] = baseline_evaluation_coverage_digest(**values)
        coverage = BaselineEvaluationCoverage.model_validate(values)
        record = coverage.model_dump(mode="json")
        await self._store.write_state(
            baseline_coverage_key(
                inventory_observation_digest=observation_digest,
                activation_digest=activation.generation_digest,
            ),
            record,
        )
        await self._publish_latest(coverage, record)
        return coverage

    async def _publish_latest(
        self,
        coverage: BaselineEvaluationCoverage,
        record: Mapping[str, Any],
    ) -> None:
        current = await self._store.read_state(BASELINE_EVALUATION_LATEST_COVERAGE_KEY)
        current_at = _parse_time(current.get("completed_at")) if current else None
        # A resumed run for an older generation never replaces a newer latest pointer.
        if current_at is not None and current_at > coverage.completed_at:
            return
        await self._store.write_state(BASELINE_EVALUATION_LATEST_COVERAGE_KEY, dict(record))

    async def _append_audit(
        self, kind: str, body: Mapping[str, Any]
    ) -> BaselineEvaluationAuditReference:
        payload = {
            "schema_version": "1.0.0",
            "kind": kind,
            "record": _json_ready(body),
            "owner_agent": "Forseti",
            "execution_authority": False,
        }
        digest = "sha256:" + hashlib.sha256(_canonical(payload).encode()).hexdigest()
        reference = BaselineEvaluationAuditReference(ref="audit:" + digest[7:39], digest=digest)
        await self._store.append_audit_entry(
            {
                "action_kind": kind,
                "producer_principal": "Forseti",
                "audit_ref": reference.ref,
                "audit_digest": reference.digest,
                "payload": payload,
                "execution_authority": False,
            }
        )
        return reference

    async def _complete_claim(
        self,
        key: str,
        claim: Mapping[str, Any],
        coverage: BaselineEvaluationCoverage,
    ) -> None:
        revision = int(claim.get("revision", 1))
        completed = {
            **dict(claim),
            "status": "completed",
            "revision": revision + 1,
            "coverage_digest": coverage.coverage_digest,
            "complete": coverage.complete,
        }
        if not await self._store.compare_and_set_state(key, completed, expected_revision=revision):
            _LOG.warning("forseti_baseline_claim_lost", extra={"claim": key})


class ForsetiBaselineScheduler:
    """Start at most one worker run per interval from Forseti's maintenance tick."""

    def __init__(
        self,
        worker: ForsetiBaselineWorker,
        *,
        interval_seconds: float = 300.0,
        clock: Callable[[], datetime] | None = None,
        on_result: Callable[[str], None] | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("baseline scheduler interval MUST be positive")
        self._worker = worker
        self._interval = timedelta(seconds=interval_seconds)
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._on_result = on_result
        self._task: asyncio.Task[BaselineWorkerResult] | None = None
        self._next_run: datetime | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def tick(self) -> bool:
        """Schedule one run when due; return whether a run started. Never blocks the tick."""

        now = self._clock()
        if self.running or (self._next_run is not None and now < self._next_run):
            return False
        self._next_run = now + self._interval
        self._task = asyncio.create_task(
            self._worker.run_once(),
            name="forseti-baseline-evaluation",
        )
        self._task.add_done_callback(self._observe)
        return True

    def _observe(self, task: asyncio.Task[BaselineWorkerResult]) -> None:
        if task.cancelled():
            result = "cancelled"
        elif task.exception() is not None:
            _LOG.error(
                "forseti_baseline_evaluation_failed",
                exc_info=task.exception(),
            )
            result = "failed"
        else:
            result = task.result().value
        if self._on_result is not None:
            self._on_result(result)


_SETTLED_RESULTS = frozenset(
    {
        BaselineWorkerResult.COMPLETED,
        BaselineWorkerResult.INCOMPLETE,
        BaselineWorkerResult.ALREADY_COMPLETED,
    }
)


def _snapshot_matches(
    snapshot: RuleGenerationSnapshot,
    activation: RuleActivationGeneration,
) -> bool:
    if snapshot.generation_digest is None:
        return False
    if canonical_sha256(snapshot.generation_digest) != canonical_sha256(
        activation.generation_digest
    ):
        return False
    members = {member.rule_id: member.rule_digest for member in activation.members}
    evaluated = {rule.id: rule_digest(rule) for rule in snapshot.rules}
    return members == evaluated


def _rules_catalog_digest(rules: tuple[Rule, ...]) -> str:
    material = [rule.model_dump(mode="json") for rule in sorted(rules, key=lambda rule: rule.id)]
    return "sha256:" + hashlib.sha256(_canonical(material).encode()).hexdigest()


def _expected_pair_set_digest(pairs: tuple[Any, ...]) -> str:
    material = [[pair.resource_id, pair.rule_id, pair.evaluated_rule_digest] for pair in pairs]
    return "sha256:" + hashlib.sha256(_canonical(material).encode()).hexdigest()


def _coverage_values(
    *,
    scoped: ScopedRuleCoverage,
    expected_pair_set_digest: str,
    generation_id: str,
    generation_digest: str,
    observation_digest: str,
    activation: RuleActivationGeneration,
    evaluated_catalog: str,
    outcome_set_digest: str,
    completed_at: datetime,
) -> dict[str, Any]:
    totals = {
        "expected": sum(rule.eligible_count for rule in scoped.rules),
        "compliant": sum(rule.compliant_count for rule in scoped.rules),
        "violated": sum(rule.violated_count for rule in scoped.rules),
        "abstained": sum(rule.abstained_count for rule in scoped.rules),
        "missing": sum(rule.missing_count for rule in scoped.rules),
        "duplicate": sum(rule.duplicate_count for rule in scoped.rules),
        "conflicting": sum(rule.conflicting_count for rule in scoped.rules),
        "unexpected": sum(rule.unexpected_count for rule in scoped.rules)
        + scoped.unattributed_unexpected_count,
        "revision": sum(rule.revision_mismatch_count for rule in scoped.rules),
    }
    covered = totals["compliant"] + totals["violated"] + totals["abstained"]
    counts = {
        BaselineEvaluationCoverageLimitation.PAIR_MISSING: totals["missing"],
        BaselineEvaluationCoverageLimitation.DUPLICATE_PAIR: totals["duplicate"],
        BaselineEvaluationCoverageLimitation.CONFLICTING_PAIR: totals["conflicting"],
        BaselineEvaluationCoverageLimitation.UNEXPECTED_PAIR: totals["unexpected"],
        BaselineEvaluationCoverageLimitation.RULE_REVISION_DRIFT: totals["revision"],
    }
    limitations = tuple(
        limitation
        for limitation, count in sorted(counts.items(), key=lambda item: item[0].value)
        if count
    )
    return {
        "generation_id": generation_id,
        "generation_digest": generation_digest,
        "inventory_observation_digest": observation_digest,
        "rule_activation_generation_id": activation.generation_id,
        "rule_activation_generation_digest": canonical_sha256(activation.generation_digest),
        "rule_catalog_digest": canonical_sha256(activation.catalog_digest),
        "evaluated_rule_catalog_digest": evaluated_catalog,
        "dispatch_signal": INVENTORY_OBSERVATION_SIGNAL,
        "expected_pair_set_digest": expected_pair_set_digest,
        "expected_pair_count": totals["expected"],
        "covered_pair_count": covered,
        "compliant_count": totals["compliant"],
        "violated_count": totals["violated"],
        "abstained_count": totals["abstained"],
        "missing_pair_count": totals["missing"],
        "duplicate_pair_count": totals["duplicate"],
        "conflicting_pair_count": totals["conflicting"],
        "unexpected_pair_count": totals["unexpected"],
        "revision_mismatch_count": totals["revision"],
        "outcome_set_digest": outcome_set_digest,
        "complete": not limitations and covered == totals["expected"],
        "limitations": limitations,
        "completed_at": completed_at,
        "projection_authority": False,
        "execution_authority": False,
    }


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _json_ready(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _canonical(value: object) -> str:
    return json.dumps(_json_ready(value), sort_keys=True, separators=(",", ":"))


__all__ = [
    "BASELINE_EVALUATION_CLAIM_PREFIX",
    "BASELINE_EVALUATION_COVERAGE_PREFIX",
    "BASELINE_EVALUATION_LATEST_COVERAGE_KEY",
    "BASELINE_EVALUATION_STATUS_KEY",
    "BaselineWorkerLimits",
    "BaselineWorkerResult",
    "ForsetiBaselineScheduler",
    "ForsetiBaselineWorker",
    "baseline_claim_key",
    "baseline_coverage_key",
]
