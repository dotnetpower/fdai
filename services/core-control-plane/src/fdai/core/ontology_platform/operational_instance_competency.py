"""Evaluate typed operational-instance competency without answer text matching."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from fdai.core.conversation.question_golden import GoldenQuestionCase
from fdai.core.ontology_platform.archive_retention import ArchiveHistoryStatus
from fdai.core.ontology_platform.graph_evidence_refresh import (
    GraphEvidenceRefreshDecision,
    GraphEvidenceRefreshOutcome,
)


@dataclass(frozen=True, order=True, slots=True)
class OperationalInstancePathStep:
    """Describe one stored-direction instance edge selected by a query."""

    from_id: str
    link_type: str
    to_id: str

    def __post_init__(self) -> None:
        for name, value in (
            ("from_id", self.from_id),
            ("link_type", self.link_type),
            ("to_id", self.to_id),
        ):
            if not value or len(value) > 512:
                raise ValueError(f"operational competency {name} MUST be bounded")


@dataclass(frozen=True, slots=True)
class OperationalInstanceExpectation:
    """Bind one golden logical case to exact runtime selection expectations."""

    semantic_pair_id: str
    instance_ids: tuple[str, ...]
    path_steps: tuple[OperationalInstancePathStep, ...]
    functions: tuple[str, ...]
    refresh_outcome: GraphEvidenceRefreshOutcome
    archive_status: ArchiveHistoryStatus

    def __post_init__(self) -> None:
        _ordered_unique(self.instance_ids, "instance ids")
        _ordered_unique(self.functions, "functions")
        if self.path_steps != tuple(sorted(set(self.path_steps))):
            raise ValueError("operational competency path steps MUST be ordered and unique")


@dataclass(frozen=True, slots=True)
class OperationalInstanceObservation:
    """Carry typed query selection and evidence disposition only."""

    semantic_pair_id: str
    instance_ids: tuple[str, ...]
    path_steps: tuple[OperationalInstancePathStep, ...]
    functions: tuple[str, ...]
    refresh_decision: GraphEvidenceRefreshDecision
    archive_status: ArchiveHistoryStatus
    execution_authority: bool

    def __post_init__(self) -> None:
        _ordered_unique(self.instance_ids, "observed instance ids")
        _ordered_unique(self.functions, "observed functions")
        if self.path_steps != tuple(sorted(set(self.path_steps))):
            raise ValueError("observed competency path steps MUST be ordered and unique")


@dataclass(frozen=True, slots=True)
class OperationalInstanceCompetencyReceipt:
    """Record exact typed competency axes and a total pass decision."""

    semantic_pair_id: str
    instances_exact: bool
    paths_exact: bool
    functions_exact: bool
    refresh_outcome_exact: bool
    archive_status_exact: bool
    authority_safe: bool
    passed: bool
    digest: str


def evaluate_operational_instance_competency(
    golden_case: GoldenQuestionCase,
    expectation: OperationalInstanceExpectation,
    observation: OperationalInstanceObservation,
) -> OperationalInstanceCompetencyReceipt:
    """Compare typed selections and reject case or ontology substitutions."""

    logical_expectation_id, separator, _variation = golden_case.semantic_pair_id.rpartition(".")
    if not separator or logical_expectation_id != expectation.semantic_pair_id:
        raise ValueError("operational competency expectation binds another golden case")
    if observation.semantic_pair_id != expectation.semantic_pair_id:
        raise ValueError("operational competency observation binds another golden case")
    required_functions = set(golden_case.required_function_types) | set(
        golden_case.required_capabilities
    )
    if not set(expectation.functions) <= required_functions:
        raise ValueError("operational competency function is absent from the golden oracle")
    required_links = set(golden_case.required_link_types)
    if not {item.link_type for item in expectation.path_steps} <= required_links:
        raise ValueError("operational competency path is absent from the golden oracle")
    axes = {
        "instances_exact": observation.instance_ids == expectation.instance_ids,
        "paths_exact": observation.path_steps == expectation.path_steps,
        "functions_exact": observation.functions == expectation.functions,
        "refresh_outcome_exact": (
            observation.refresh_decision.outcome is expectation.refresh_outcome
        ),
        "archive_status_exact": observation.archive_status is expectation.archive_status,
        "authority_safe": (
            not observation.execution_authority
            and not observation.refresh_decision.execution_authority
            and not observation.refresh_decision.mutation_authority
        ),
    }
    passed = all(axes.values())
    body = {
        "semantic_pair_id": expectation.semantic_pair_id,
        **axes,
        "passed": passed,
        "refresh_decision_digest": observation.refresh_decision.digest,
    }
    return OperationalInstanceCompetencyReceipt(
        semantic_pair_id=expectation.semantic_pair_id,
        **axes,
        passed=passed,
        digest="sha256:"
        + hashlib.sha256(
            json.dumps(
                body,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest(),
    )


def _ordered_unique(values: tuple[str, ...], name: str) -> None:
    if values != tuple(sorted(set(values))):
        raise ValueError(f"operational competency {name} MUST be ordered and unique")
    if any(not value or len(value) > 512 for value in values):
        raise ValueError(f"operational competency {name} MUST be bounded")


__all__ = [
    "OperationalInstanceCompetencyReceipt",
    "OperationalInstanceExpectation",
    "OperationalInstanceObservation",
    "OperationalInstancePathStep",
    "evaluate_operational_instance_competency",
]
