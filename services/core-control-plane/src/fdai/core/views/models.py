"""Declarative ViewSpec and rendered process-view value objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ViewAppliesTo:
    workflow_ref: str


@dataclass(frozen=True, slots=True)
class ViewRegion:
    id: str
    report_ref: str
    column_span: int = 12

    def __post_init__(self) -> None:
        if not 1 <= self.column_span <= 12:
            raise ValueError("ViewRegion.column_span MUST be in [1, 12]")


@dataclass(frozen=True, slots=True)
class ViewSpec:
    id: str
    version: str
    name: str
    description: str
    route: str
    applies_to: ViewAppliesTo
    regions: tuple[ViewRegion, ...]


__all__ = ["ViewAppliesTo", "ViewRegion", "ViewSpec"]
