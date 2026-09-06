"""Availability result for semantic query runtime composition."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.core.conversation.semantic_runtime import SemanticConversationRuntime


@dataclass(frozen=True, slots=True)
class SemanticQueryRuntimeComposition:
    """Optional runtime plus one stable reason when composition is unavailable."""

    runtime: SemanticConversationRuntime | None
    unavailable_reason: str | None
    model_auth_audiences: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (self.runtime is None) != (self.unavailable_reason is not None):
            raise ValueError("semantic runtime composition availability is inconsistent")
        if self.runtime is not None and not self.model_auth_audiences:
            raise ValueError("available semantic runtime requires model auth audiences")
        if self.runtime is None and self.model_auth_audiences:
            raise ValueError("unavailable semantic runtime cannot expose model auth audiences")
