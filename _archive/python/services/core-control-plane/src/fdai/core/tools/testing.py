"""Deterministic fakes for tool tests.

Colocated with production code (not under ``tests/``) so a fork's test
suite can import the same helpers via the public
``fdai.core.tools`` package. Mirrors the pattern established in
:mod:`fdai.core.prompts.testing` and
:mod:`fdai.core.quality_gate.testing`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from fdai.core.tools.executor import ToolProvider
from fdai.core.tools.types import ToolArtifact


class InMemoryToolProvider(ToolProvider):
    """Return canned answers keyed by ``(tool_id, arguments-tuple)``.

    Useful for property-based tests and any deterministic replay
    scenario. An unknown key raises :class:`KeyError` so a test that
    forgets to register a fixture surfaces the omission loudly.
    """

    def __init__(
        self,
        *,
        canned: Mapping[tuple[str, tuple[tuple[str, object], ...]], object] | None = None,
    ) -> None:
        self._canned: dict[tuple[str, tuple[tuple[str, object], ...]], object] = dict(canned or {})
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def prime(
        self,
        *,
        tool_id: str,
        arguments: Mapping[str, Any],
        response: object,
    ) -> None:
        """Register a canned response for a specific call."""

        self._canned[(tool_id, _key(arguments))] = response

    async def call(
        self,
        *,
        artifact: ToolArtifact,
        arguments: Mapping[str, Any],
    ) -> object:
        self.calls.append((artifact.id, dict(arguments)))
        key = (artifact.id, _key(arguments))
        if key not in self._canned:
            raise KeyError(
                f"no canned response primed for tool {artifact.id!r} with "
                f"arguments {dict(arguments)!r}"
            )
        return self._canned[key]


class NoOpToolProvider(ToolProvider):
    """Provider that refuses every call.

    The upstream default binding for any tool whose fork-specific
    provider is not yet wired. A fork that promotes a tool from
    ``shadow`` to ``enforce`` without also registering a real provider
    will hit this and fail fast (fail-closed) rather than silently
    returning ``None`` into the model prompt.
    """

    def __init__(self, *, reason: str = "provider not wired") -> None:
        self._reason: Final[str] = reason

    async def call(
        self,
        *,
        artifact: ToolArtifact,
        arguments: Mapping[str, Any],
    ) -> object:
        raise RuntimeError(f"NoOpToolProvider refuses tool call to {artifact.id!r}: {self._reason}")


def _key(arguments: Mapping[str, Any]) -> tuple[tuple[str, object], ...]:
    """Freeze an arguments mapping into a hashable canonical key.

    Sorted by key so ``{"a": 1, "b": 2}`` and ``{"b": 2, "a": 1}``
    hash identically. Nested containers are converted only if they
    are already hashable; anything else falls through as-is so the
    lookup fails loudly in :meth:`InMemoryToolProvider.call`.
    """

    return tuple(sorted(arguments.items()))


__all__ = [
    "InMemoryToolProvider",
    "NoOpToolProvider",
]
