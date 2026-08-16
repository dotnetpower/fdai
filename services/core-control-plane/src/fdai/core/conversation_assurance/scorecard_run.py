"""Deterministic aggregation of frozen-corpus runs into one ChatOps scorecard.

The 50-item contract in
:mod:`fdai.core.conversation_assurance.quality_scorecard` fixes the score
schema. This module fixes how independently measured runs over the frozen
corpus reduce to one replayable qualification artifact.

Design invariants
-----------------
- **Worst run decides.** Each item's reported score is the minimum final score
  across every supplied run, so a single favourable run can never qualify an
  item.
- **Pinned thresholds.** The run set declares the contract digest it was
  measured against. A digest that no longer matches the installed contract is a
  hard error, so a change cannot edit thresholds and promote a failing
  implementation in one step.
- **Frozen corpus identity.** Every run MUST cite the same corpus version and
  digest. A mixed corpus is a hard error rather than a blended average.
- **Fail closed.** Too few runs, an unmet turn floor, an unmet locale floor, or
  a failing item leaves the scorecard unqualified with an explicit reason. No
  reason is ever inferred from an absent measurement.
- **Evidence only.** The artifact carries versions, digests, counts, and scores.
  It carries no answer text, principal, tenant, endpoint, or customer value.

See also
--------
- ``docs/roadmap/decisioning/conversation-assurance.md``
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from fdai.core.conversation_assurance.quality_scorecard import (
    ChatOpsQualityContract,
    QualityHardCap,
    QualityItemMeasurement,
    score_quality_item,
)

SCORECARD_SCHEMA_VERSION = 1
_MAX_IDENTIFIER = 128
_MAX_RUNS = 32


class ScorecardBlocker(StrEnum):
    """Deterministic reasons a scorecard cannot report qualification."""

    INSUFFICIENT_RUNS = "insufficient_runs"
    CORPUS_TURN_FLOOR_UNMET = "corpus_turn_floor_unmet"
    LOCALE_TURN_FLOOR_UNMET = "locale_turn_floor_unmet"
    ITEM_BELOW_MINIMUM = "item_below_minimum"


def _require_identifier(value: str, field: str) -> str:
    if not value.strip() or len(value) > _MAX_IDENTIFIER:
        raise ValueError(f"scorecard {field} MUST contain 1-{_MAX_IDENTIFIER} characters")
    return value


@dataclass(frozen=True, slots=True)
class QualityRunEvidence:
    """One complete independently executed run over the frozen corpus."""

    run_id: str
    english_turns: int
    korean_turns: int
    measurements: tuple[QualityItemMeasurement, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.run_id, "run_id")
        if self.english_turns < 0 or self.korean_turns < 0:
            raise ValueError("scorecard run turn counts MUST NOT be negative")
        measured_ids = tuple(measurement.item_id for measurement in self.measurements)
        if measured_ids != tuple(range(1, len(self.measurements) + 1)):
            raise ValueError("scorecard run MUST measure every contract item once in id order")

    @property
    def total_turns(self) -> int:
        return self.english_turns + self.korean_turns


@dataclass(frozen=True, slots=True)
class ScorecardProvenance:
    """Version-pinned identity of the measured configuration."""

    contract_digest: str
    corpus_version: str
    corpus_digest: str
    model_deployment_id: str
    evaluator_version: str
    generated_by: str

    def __post_init__(self) -> None:
        for field, value in (
            ("contract_digest", self.contract_digest),
            ("corpus_version", self.corpus_version),
            ("corpus_digest", self.corpus_digest),
            ("model_deployment_id", self.model_deployment_id),
            ("evaluator_version", self.evaluator_version),
            ("generated_by", self.generated_by),
        ):
            _require_identifier(value, field)

    def to_dict(self) -> dict[str, str]:
        return {
            "contract_digest": self.contract_digest,
            "corpus_version": self.corpus_version,
            "corpus_digest": self.corpus_digest,
            "model_deployment_id": self.model_deployment_id,
            "evaluator_version": self.evaluator_version,
            "generated_by": self.generated_by,
        }


@dataclass(frozen=True, slots=True)
class ScorecardItemResult:
    """One item's worst observed run score and its applied caps."""

    item_id: int
    name: str
    workstream: str
    minimum_score: float
    worst_run_id: str
    worst_score: float
    applied_caps: tuple[QualityHardCap, ...]
    passed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.item_id,
            "name": self.name,
            "workstream": self.workstream,
            "minimum_score": self.minimum_score,
            "worst_run_id": self.worst_run_id,
            "worst_score": self.worst_score,
            "applied_caps": [cap.value for cap in self.applied_caps],
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class QualityScorecard:
    """Replayable qualification artifact for one pinned configuration."""

    schema_version: int
    contract_version: str
    provenance: ScorecardProvenance
    run_ids: tuple[str, ...]
    minimum_english_turns: int
    minimum_korean_turns: int
    items: tuple[ScorecardItemResult, ...]
    blockers: tuple[ScorecardBlocker, ...]
    qualified: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "contract_version": self.contract_version,
            "provenance": self.provenance.to_dict(),
            "run_ids": list(self.run_ids),
            "minimum_english_turns": self.minimum_english_turns,
            "minimum_korean_turns": self.minimum_korean_turns,
            "items": [item.to_dict() for item in self.items],
            "blockers": [blocker.value for blocker in self.blockers],
            "qualified": self.qualified,
        }

    def to_json(self) -> str:
        """Render the stable canonical artifact text."""

        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )

    @property
    def content_digest(self) -> str:
        canonical = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


def build_quality_scorecard(
    runs: tuple[QualityRunEvidence, ...],
    *,
    contract: ChatOpsQualityContract,
    provenance: ScorecardProvenance,
) -> QualityScorecard:
    """Reduce independent runs to one worst-run scorecard.

    Raises:
        ValueError: when no run is supplied, run ids repeat, a run does not
            measure every contract item, or the declared contract digest does
            not match the installed contract.
    """

    if not runs:
        raise ValueError("scorecard MUST aggregate at least one run")
    if len(runs) > _MAX_RUNS:
        raise ValueError(f"scorecard MUST aggregate at most {_MAX_RUNS} runs")
    run_ids = tuple(run.run_id for run in runs)
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("scorecard run ids MUST be unique")
    if provenance.contract_digest != contract.content_digest:
        raise ValueError("scorecard contract digest does not match the installed contract")
    for run in runs:
        if len(run.measurements) != len(contract.items):
            raise ValueError("scorecard run MUST measure every contract item")

    items: list[ScorecardItemResult] = []
    for item in contract.items:
        scored_runs = tuple(
            (run.run_id, score_quality_item(run.measurements[item.item_id - 1], contract=contract))
            for run in runs
        )
        worst_run_id, worst = min(scored_runs, key=lambda entry: entry[1].final_score)
        items.append(
            ScorecardItemResult(
                item_id=item.item_id,
                name=item.name,
                workstream=item.workstream,
                minimum_score=item.minimum_score,
                worst_run_id=worst_run_id,
                worst_score=worst.final_score,
                applied_caps=worst.applied_caps,
                passed=worst.final_score >= item.minimum_score,
            )
        )

    blockers: list[ScorecardBlocker] = []
    if len(runs) < contract.minimum_runs:
        blockers.append(ScorecardBlocker.INSUFFICIENT_RUNS)
    if any(run.total_turns < contract.minimum_turns for run in runs):
        blockers.append(ScorecardBlocker.CORPUS_TURN_FLOOR_UNMET)
    if any(
        min(run.english_turns, run.korean_turns) < contract.minimum_turns_per_locale for run in runs
    ):
        blockers.append(ScorecardBlocker.LOCALE_TURN_FLOOR_UNMET)
    if any(not item.passed for item in items):
        blockers.append(ScorecardBlocker.ITEM_BELOW_MINIMUM)

    return QualityScorecard(
        schema_version=SCORECARD_SCHEMA_VERSION,
        contract_version=contract.version,
        provenance=provenance,
        run_ids=run_ids,
        minimum_english_turns=min(run.english_turns for run in runs),
        minimum_korean_turns=min(run.korean_turns for run in runs),
        items=tuple(items),
        blockers=tuple(blockers),
        qualified=not blockers,
    )


__all__ = [
    "SCORECARD_SCHEMA_VERSION",
    "QualityRunEvidence",
    "QualityScorecard",
    "ScorecardBlocker",
    "ScorecardItemResult",
    "ScorecardProvenance",
    "build_quality_scorecard",
]
