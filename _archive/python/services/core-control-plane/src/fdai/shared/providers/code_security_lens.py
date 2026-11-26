"""Seam for the off-path code-security LLM lens lane.

A lens model reviews one bounded code excerpt for one weakness family and returns candidate
lines. Its output is untrusted: core re-validates every candidate for grounding, CWE, and quorum
across distinct model families, and kept candidates stay inert hypotheses. Adapters are
tool-free, schema-constrained, and byte-bounded; they live under ``delivery/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class LensModelError(RuntimeError):
    """Raised for a provider, transport, budget, or response-shape failure; the call is skipped."""


@dataclass(frozen=True, slots=True)
class LensModelIdentity:
    family: str
    deployment: str


@dataclass(frozen=True, slots=True)
class LensRequest:
    lens_id: str
    focus: str
    cwe: tuple[int, ...]
    language: str
    path: str
    first_line: int
    last_line: int
    numbered_excerpt: str
    max_findings: int


@dataclass(frozen=True, slots=True)
class LensFinding:
    line: int
    cwe: int
    confidence: str
    explanation: str


@dataclass(frozen=True, slots=True)
class LensResponse:
    findings: tuple[LensFinding, ...]
    model: LensModelIdentity
    prompt_tokens: int = 0
    completion_tokens: int = 0


@runtime_checkable
class CodeSecurityLensModel(Protocol):
    @property
    def identity(self) -> LensModelIdentity: ...

    async def review(self, request: LensRequest) -> LensResponse:
        """Return candidate lines for one excerpt, or raise :class:`LensModelError`."""
        ...


__all__ = [
    "CodeSecurityLensModel",
    "LensFinding",
    "LensModelError",
    "LensModelIdentity",
    "LensRequest",
    "LensResponse",
]
