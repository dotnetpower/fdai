"""Deterministic prompt-composer fakes for tests.

Colocated with production code (not under ``tests/``) so a fork's test
suite can import the same helpers via the public
``aiopspilot.core.prompts`` package. Mirrors the pattern established in
:mod:`aiopspilot.core.quality_gate.testing` and
:mod:`aiopspilot.core.tiers.t1_lightweight.testing`.
"""

from __future__ import annotations

from typing import Final

from aiopspilot.core.operator_memory import OperatorScope
from aiopspilot.core.prompts.composer import PromptComposer
from aiopspilot.core.prompts.types import (
    ComposedPrompt,
    LayerRef,
    PromptLayer,
)


class StaticPromptComposer(PromptComposer):
    """A composer that returns the same canned :class:`ComposedPrompt`.

    Useful when a test cares about how a downstream adapter behaves
    given some system prompt but not about how the prompt was
    assembled. The composer records every call's ``(capability_id,
    scope)`` pair so a test can assert wiring without inspecting the
    :class:`ComposedPrompt` itself.
    """

    def __init__(
        self,
        system_text: str,
        *,
        layer_id: str = "test-base",
        layer_version: int = 1,
    ) -> None:
        self._system_text: Final[str] = system_text
        self._manifest: Final[tuple[LayerRef, ...]] = (
            LayerRef(
                id=layer_id,
                version=layer_version,
                layer=PromptLayer.BASE,
                token_estimate=max(1, len(system_text) // 4),
            ),
        )
        self._token_estimate: Final[int] = max(1, len(system_text) // 4)
        self.calls: list[tuple[str, OperatorScope | None]] = []

    async def compose(
        self,
        *,
        capability_id: str,
        scope: OperatorScope | None = None,
    ) -> ComposedPrompt:
        self.calls.append((capability_id, scope))
        return ComposedPrompt(
            system_text=self._system_text,
            layer_manifest=self._manifest,
            token_estimate=self._token_estimate,
        )


__all__ = ["StaticPromptComposer"]
