"""Immutable decision-case values."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any

_ARGUMENT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True, slots=True)
class ActionArgumentProposal:
    """Digest-bound safe projection of one proposed action argument."""

    name: str
    value_digest: str
    redacted: bool
    safe_value_json: str

    def __post_init__(self) -> None:
        if _ARGUMENT_NAME.fullmatch(self.name) is None:
            raise ValueError("action argument proposal name is invalid")
        if not self.value_digest.startswith("sha256:") or len(self.value_digest) != 71:
            raise ValueError("action argument proposal digest MUST be SHA-256")
        _canonical_json(json.loads(self.safe_value_json))


@dataclass(frozen=True, slots=True)
class ActionArguments:
    """Canonical exact arguments plus typed redacted bindings."""

    arguments_json: str
    arguments_digest: str
    bindings: tuple[ActionArgumentProposal, ...]

    @classmethod
    def create(
        cls,
        arguments: Mapping[str, Any],
        *,
        redacted_names: frozenset[str] = frozenset(),
    ) -> ActionArguments:
        """Create deterministic bindings without retaining redacted safe values."""

        values = dict(arguments)
        names = tuple(sorted(values))
        if any(_ARGUMENT_NAME.fullmatch(name) is None for name in names):
            raise ValueError("action argument names MUST be canonical identifiers")
        if not redacted_names.issubset(names):
            raise ValueError("redacted action argument names MUST exist")
        arguments_json = _canonical_json(values)
        bindings = tuple(
            ActionArgumentProposal(
                name=name,
                value_digest=_content_digest(values[name]),
                redacted=name in redacted_names,
                safe_value_json=_canonical_json(
                    "<redacted>" if name in redacted_names else values[name]
                ),
            )
            for name in names
        )
        return cls(
            arguments_json=arguments_json,
            arguments_digest=_content_digest(values),
            bindings=bindings,
        )

    def __post_init__(self) -> None:
        values = self.values()
        if self.arguments_digest != _content_digest(values):
            raise ValueError("action arguments digest does not match canonical values")
        if tuple(binding.name for binding in self.bindings) != tuple(sorted(values)):
            raise ValueError("action argument bindings MUST be complete, sorted, and unique")
        for binding in self.bindings:
            value = values[binding.name]
            if binding.value_digest != _content_digest(value):
                raise ValueError("action argument binding digest does not match")
            expected_safe = _canonical_json("<redacted>" if binding.redacted else value)
            if binding.safe_value_json != expected_safe:
                raise ValueError("action argument safe projection does not match")

    def values(self) -> dict[str, Any]:
        decoded = json.loads(self.arguments_json)
        if not isinstance(decoded, dict) or _canonical_json(decoded) != self.arguments_json:
            raise ValueError("action arguments MUST be one canonical JSON object")
        return decoded

    def to_mapping(self) -> dict[str, object]:
        return {
            "digest": self.arguments_digest,
            "projection": {
                binding.name: json.loads(binding.safe_value_json) for binding in self.bindings
            },
            "bindings": [
                {
                    "name": binding.name,
                    "value_digest": binding.value_digest,
                    "redacted": binding.redacted,
                    "safe_value_json": binding.safe_value_json,
                }
                for binding in self.bindings
            ],
        }


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("action argument values MUST be canonical JSON") from exc


def _content_digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(_canonical_json(value).encode()).hexdigest()}"


@dataclass(frozen=True, slots=True)
class ObjectiveEffect:
    """Expected utility for one objective, normalized to [-1, 1]."""

    objective_id: str
    utility: float
    confidence: float
    metric: str
    expected_min: float
    expected_max: float
    observation_window_seconds: int

    def __post_init__(self) -> None:
        if not self.objective_id or not self.metric:
            raise ValueError("objective effect identities MUST be non-empty")
        numeric = (self.utility, self.confidence, self.expected_min, self.expected_max)
        if not all(isfinite(value) for value in numeric):
            raise ValueError("objective effect numeric values MUST be finite")
        if not -1.0 <= self.utility <= 1.0 or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("objective effect utility/confidence MUST be normalized")
        if self.expected_min > self.expected_max or self.observation_window_seconds < 1:
            raise ValueError("objective effect range/window is invalid")


@dataclass(frozen=True, slots=True)
class ActionOption:
    """One bounded action, hold, or no-op option considered in a case."""

    option_id: str
    action_type: str | None
    effects: tuple[ObjectiveEffect, ...]
    evidence_refs: tuple[str, ...]
    violated_constraint_ids: tuple[str, ...] = ()
    proposing_agents: tuple[str, ...] = ()
    logic_receipt_refs: tuple[str, ...] = ()
    simulation_receipt_refs: tuple[str, ...] = ()
    constraint_evaluation_refs: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    arguments: ActionArguments | None = None

    def __post_init__(self) -> None:
        if not self.option_id or not self.effects or not self.evidence_refs:
            raise ValueError("action option MUST have id, effects, and evidence")
        objective_ids = [effect.objective_id for effect in self.effects]
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("action option MUST contain one effect per objective")


@dataclass(frozen=True, slots=True)
class DecisionCase:
    """Immutable semantic input shared by judge, arbiter, approver, and audit."""

    case_id: str
    correlation_id: str
    context_snapshot_id: str
    created_at: datetime
    no_action_effects: tuple[ObjectiveEffect, ...]
    options: tuple[ActionOption, ...]
    protected_objective_ids: tuple[str, ...]
    active_constraint_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    process_id: str | None = None
    logic_release_digest: str | None = None

    def __post_init__(self) -> None:
        if not all((self.case_id, self.correlation_id, self.context_snapshot_id)):
            raise ValueError("decision case identities MUST be non-empty")
        if self.created_at.tzinfo is None:
            raise ValueError("decision case timestamp MUST be timezone-aware")
        if not self.no_action_effects or not self.options or not self.evidence_refs:
            raise ValueError("decision case MUST include baseline, options, and evidence")


@dataclass(frozen=True, slots=True)
class DecisionSelection:
    selected_option_id: str | None
    objective_scores: tuple[tuple[str, float], ...]
    margin: float
    requires_human_approval: bool
    reason: str


@dataclass(frozen=True, slots=True)
class DecisionClosure:
    case_id: str
    selected_option_id: str
    outcome_id: str
    effect_verified: bool
    guard_regression: bool
    reusable: bool
    reason: str
