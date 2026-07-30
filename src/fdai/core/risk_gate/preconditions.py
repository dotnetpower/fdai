"""Deterministic evidence production for ActionType preconditions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from fdai.shared.contracts.models import (
    Action,
    Event,
    OntologyActionType,
    PreconditionKind,
)


@dataclass(frozen=True, slots=True)
class PreconditionEvaluation:
    """One deterministic result for an indexed ActionType precondition."""

    condition_index: int
    kind: PreconditionKind
    satisfied: bool

    def __post_init__(self) -> None:
        if self.condition_index < 0:
            raise ValueError("condition_index MUST be >= 0")


@runtime_checkable
class PreconditionEvaluator(Protocol):
    """Produce bounded evidence without granting execution authority."""

    async def evaluate(
        self,
        *,
        event: Event,
        action: Action,
        action_type: OntologyActionType,
    ) -> tuple[PreconditionEvaluation, ...]: ...


class EventPreconditionEvaluator:
    """Evaluate conditions grounded in the event's resource snapshot."""

    async def evaluate(
        self,
        *,
        event: Event,
        action: Action,
        action_type: OntologyActionType,
    ) -> tuple[PreconditionEvaluation, ...]:
        del action
        resource = event.payload.get("resource")
        if not isinstance(resource, Mapping):
            return ()
        props = resource.get("props")
        if not isinstance(props, Mapping):
            return ()

        evaluations: list[PreconditionEvaluation] = []
        for index, precondition in enumerate(action_type.preconditions):
            if precondition.kind is PreconditionKind.RESOURCE_PROPERTY_EQUALS:
                property_name = precondition.property
                if property_name is None:
                    continue
                actual = props.get(property_name)
                expected = precondition.value
                evaluations.append(
                    PreconditionEvaluation(
                        condition_index=index,
                        kind=precondition.kind,
                        satisfied=(
                            property_name in props
                            and type(actual) is type(expected)
                            and actual == expected
                        ),
                    )
                )
            elif precondition.kind is PreconditionKind.RESOURCE_TAG_PRESENT:
                tag_name = precondition.tag
                tags = resource.get("tags")
                if not isinstance(tags, Mapping):
                    tags = props.get("tags")
                if tag_name is None or not isinstance(tags, Mapping):
                    continue
                evaluations.append(
                    PreconditionEvaluation(
                        condition_index=index,
                        kind=precondition.kind,
                        satisfied=tag_name in tags,
                    )
                )
        return tuple(evaluations)


__all__ = [
    "EventPreconditionEvaluator",
    "PreconditionEvaluation",
    "PreconditionEvaluator",
]
