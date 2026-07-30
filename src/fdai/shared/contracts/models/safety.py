"""Safety value objects shared by ontology declarations and runtime actions."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from ._base import _Base
from .enums import StopConditionKind


class ActionStopCondition(_Base):
    kind: StopConditionKind
    threshold: float | None = None
    window_seconds: Annotated[int, Field(ge=1)] | None = None
    seconds: Annotated[int, Field(ge=1)] | None = None
    count: Annotated[int, Field(ge=1)] | None = None


__all__ = ["ActionStopCondition"]
