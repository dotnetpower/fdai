"""Immutable observation accounting for one frozen causal investigation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class ObservationOutcome(StrEnum):
    SUPPORTED = "supported"
    REFUTED = "refuted"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class HypothesisObservation:
    """An actual observation, distinct from a candidate's predicted outcome."""

    hypothesis_id: str
    outcome: ObservationOutcome
    evidence_ref: str
    result_digest: str

    def __post_init__(self) -> None:
        for name, value in (
            ("hypothesis_id", self.hypothesis_id),
            ("evidence_ref", self.evidence_ref),
        ):
            if (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
                or len(value) > 512
            ):
                raise ValueError(f"hypothesis observation {name} MUST be exact bounded text")
        if not isinstance(self.outcome, ObservationOutcome):
            raise ValueError("hypothesis observation outcome MUST be typed")
        if (
            not isinstance(self.result_digest, str)
            or not self.result_digest.startswith("sha256:")
            or len(self.result_digest) != 71
            or any(char not in "0123456789abcdef" for char in self.result_digest[7:])
        ):
            raise ValueError("hypothesis observation result digest MUST be SHA-256")


def validate_history(history: tuple[HypothesisObservation, ...]) -> None:
    if (
        not isinstance(history, tuple)
        or len(history) > 32
        or any(not isinstance(item, HypothesisObservation) for item in history)
    ):
        raise ValueError("hypothesis observation history MUST be a bounded immutable tuple")
    ids = tuple(item.hypothesis_id for item in history)
    if ids != tuple(sorted(set(ids))):
        raise ValueError("hypothesis observation ids MUST be sorted and unique")


def history_material(history: tuple[HypothesisObservation, ...]) -> list[dict[str, str]]:
    return [
        {
            "hypothesis_id": item.hypothesis_id,
            "outcome": item.outcome.value,
            "evidence_ref": item.evidence_ref,
            "result_digest": item.result_digest,
        }
        for item in history
    ]


def history_from_mapping(value: object) -> tuple[HypothesisObservation, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > 32:
        raise ValueError("persisted hypothesis observations MUST be a bounded array")
    items: list[HypothesisObservation] = []
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) != {
            "hypothesis_id",
            "outcome",
            "evidence_ref",
            "result_digest",
        }:
            raise ValueError("persisted hypothesis observation has invalid fields")

        items.append(
            HypothesisObservation(
                _text(raw, "hypothesis_id"),
                ObservationOutcome(_text(raw, "outcome")),
                _text(raw, "evidence_ref"),
                _text(raw, "result_digest"),
            )
        )
    result = tuple(items)
    validate_history(result)
    return result


def _text(raw: Mapping[str, object], name: str) -> str:
    field = raw.get(name)
    if not isinstance(field, str):
        raise ValueError("persisted hypothesis observation fields MUST be text")
    return field


def validate_transition(
    prior: tuple[HypothesisObservation, ...],
    current: tuple[HypothesisObservation, ...],
    *,
    active_ids: tuple[str, ...],
    result_digest: str,
    evidence_refs: tuple[str, ...],
) -> HypothesisObservation | None:
    """A revision may add one current observation; it cannot erase or rewrite prior evidence."""

    validate_history(prior)
    validate_history(current)
    before = {item.hypothesis_id: item for item in prior}
    after = {item.hypothesis_id: item for item in current}
    if any(after.get(key) != item for key, item in before.items()):
        raise ValueError("hypothesis revision rewrote observation history")
    added = tuple(item for key, item in after.items() if key not in before)
    if not added and not prior and not current:
        return None
    if len(added) != 1:
        raise ValueError("hypothesis revision requires exactly one new observation")
    observation = added[0]
    if (
        observation.hypothesis_id not in active_ids
        or observation.result_digest != result_digest
        or observation.evidence_ref not in evidence_refs
    ):
        raise ValueError("hypothesis observation does not match the current verified execution")
    return observation
