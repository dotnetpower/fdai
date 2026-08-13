"""Agent-facing protocols for Rule semantic generation workers."""

from __future__ import annotations

from typing import Protocol

from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RuleGenerationBuildRequestEvent,
    RuleGenerationBuildResultEvent,
    RuleGenerationValidationResultEvent,
)


class RuleGenerationBuildHandler(Protocol):
    """Build and durably close one bounded generation result."""

    async def handle(
        self,
        request: RuleGenerationBuildRequestEvent,
    ) -> RuleGenerationBuildResultEvent: ...


class RuleGenerationValidationHandler(Protocol):
    """Independently validate one bounded staged-generation result."""

    async def handle(
        self,
        build_result: RuleGenerationBuildResultEvent,
    ) -> RuleGenerationValidationResultEvent: ...


__all__ = ["RuleGenerationBuildHandler", "RuleGenerationValidationHandler"]
