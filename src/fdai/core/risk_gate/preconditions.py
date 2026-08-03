"""Deterministic evidence production for ActionType preconditions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
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


@runtime_checkable
class OpenActionEvidenceProvider(Protocol):
    """Read whether another open action conflicts on the logical target."""

    async def has_conflict(
        self,
        *,
        target_ref: str,
        excluding_idempotency_key: str,
    ) -> bool: ...


@runtime_checkable
class ChangeWindowEvidenceProvider(Protocol):
    """Read whether an approved change window covers the target and time."""

    async def is_active(self, *, target_ref: str, at: datetime) -> bool: ...


@runtime_checkable
class AutomationHoldReader(Protocol):
    """Read whether incomplete recovery blocks ordinary target automation."""

    async def is_held(self, *, target_ref: str) -> bool: ...


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


class GovernedPreconditionEvaluator:
    """Combine event evidence with optional authoritative state providers."""

    def __init__(
        self,
        *,
        event_evaluator: EventPreconditionEvaluator | None = None,
        open_actions: OpenActionEvidenceProvider | None = None,
        change_windows: ChangeWindowEvidenceProvider | None = None,
    ) -> None:
        self._event_evaluator = event_evaluator or EventPreconditionEvaluator()
        self._open_actions = open_actions
        self._change_windows = change_windows

    async def evaluate(
        self,
        *,
        event: Event,
        action: Action,
        action_type: OntologyActionType,
    ) -> tuple[PreconditionEvaluation, ...]:
        evaluations = {
            item.condition_index: item
            for item in await self._event_evaluator.evaluate(
                event=event,
                action=action,
                action_type=action_type,
            )
        }
        for index, precondition in enumerate(action_type.preconditions):
            if (
                precondition.kind is PreconditionKind.NO_CONFLICTING_OPEN_ACTION_ON_RESOURCE
                and self._open_actions is not None
            ):
                conflict = await self._open_actions.has_conflict(
                    target_ref=action.target_resource_ref,
                    excluding_idempotency_key=action.idempotency_key,
                )
                evaluations[index] = PreconditionEvaluation(
                    condition_index=index,
                    kind=precondition.kind,
                    satisfied=not conflict,
                )
            elif (
                precondition.kind is PreconditionKind.MAINTENANCE_WINDOW_ACTIVE
                and self._change_windows is not None
            ):
                active = await self._change_windows.is_active(
                    target_ref=action.target_resource_ref,
                    at=event.detected_at,
                )
                evaluations[index] = PreconditionEvaluation(
                    condition_index=index,
                    kind=precondition.kind,
                    satisfied=active,
                )
        return tuple(evaluations[index] for index in sorted(evaluations))


__all__ = [
    "AutomationHoldReader",
    "EventPreconditionEvaluator",
    "ChangeWindowEvidenceProvider",
    "GovernedPreconditionEvaluator",
    "OpenActionEvidenceProvider",
    "PreconditionEvaluation",
    "PreconditionEvaluator",
]
