"""In-memory fakes for the quality gate seams — used by tests + local dev."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from typing import Any

from aiopspilot.core.quality_gate.gate import (
    CrossCheckModel,
    GroundingSource,
    QualityCandidate,
    VerifierPolicy,
)
from aiopspilot.core.quality_gate.rag_grounding import RuleEmbeddingIndex
from aiopspilot.shared.contracts.models import Rule


class StaticVerifier(VerifierPolicy):
    """Deterministic verifier that returns a preconfigured outcome."""

    def __init__(self, *, outcome: bool | None) -> None:
        self._outcome = outcome

    def verify(self, candidate: QualityCandidate) -> bool | None:
        del candidate
        return self._outcome


class MatchTypeCrossCheckModel(CrossCheckModel):
    """A cross-check model that always agrees on the candidate's action_type."""

    def __init__(self, *, model_id: str = "fake-agree") -> None:
        self._id = model_id

    async def propose(self, candidate: QualityCandidate) -> tuple[str, Mapping[str, Any]]:
        return candidate.action_type, dict(candidate.params)


class MismatchCrossCheckModel(CrossCheckModel):
    """A cross-check model that always disagrees on the action_type."""

    def __init__(self, *, model_id: str = "fake-disagree") -> None:
        self._id = model_id

    async def propose(self, candidate: QualityCandidate) -> tuple[str, Mapping[str, Any]]:
        return f"{candidate.action_type}::other", {}


class InMemoryGroundingSource(GroundingSource):
    """A grounding source backed by an in-process rule map."""

    def __init__(self, rules: Mapping[str, Rule]) -> None:
        self._rules = dict(rules)

    def known_rule_ids(self) -> set[str]:
        return set(self._rules.keys())

    def get(self, rule_id: str) -> Rule | None:
        return self._rules.get(rule_id)


class HashedRuleEmbeddingIndex(RuleEmbeddingIndex):
    """Deterministic bag-of-tokens :class:`RuleEmbeddingIndex` fake.

    Tokenizes ``text`` on whitespace + common punctuation, lower-cases,
    then increments the bucket ``blake2b(token) mod dim`` for each
    token. The result is a fixed-``dim``-length vector that:

    - depends only on the input tokens (no per-process randomness — we
      cannot use built-in :func:`hash`, which is salt-randomized under
      ``PYTHONHASHSEED=random``);
    - preserves the token multiplicity, so shared vocabulary drives
      cosine similarity toward 1.0;
    - collapses to the zero vector on empty input, which
      :meth:`cosine` returns as ``0.0``.

    This is a **test fake**: a fork that wants meaningful semantic
    similarity in production replaces it with a real embedding
    provider behind the same :class:`RuleEmbeddingIndex` Protocol.
    """

    _TOKEN_SPLIT_CHARS = " \t\n\r.,;:/_-()[]{}\"'"  # noqa: S105 — punctuation set, not a secret

    def __init__(self, *, dim: int = 64) -> None:
        if dim < 1:
            raise ValueError("dim MUST be >= 1")
        self._dim = dim

    def encode(self, text: str) -> tuple[float, ...]:
        vec = [0.0] * self._dim
        for token in self._tokenize(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest, "big") % self._dim
            vec[bucket] += 1.0
        return tuple(vec)

    def cosine(self, a: tuple[float, ...], b: tuple[float, ...]) -> float:
        if len(a) != len(b):
            raise ValueError("cosine requires equal-length vectors")
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    @classmethod
    def _tokenize(cls, text: str) -> list[str]:
        normalized = text.lower()
        for ch in cls._TOKEN_SPLIT_CHARS:
            normalized = normalized.replace(ch, " ")
        return [token for token in normalized.split(" ") if token]


__all__ = [
    "HashedRuleEmbeddingIndex",
    "InMemoryGroundingSource",
    "MatchTypeCrossCheckModel",
    "MismatchCrossCheckModel",
    "StaticVerifier",
]
