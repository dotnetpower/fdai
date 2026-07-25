"""T1 embedding fallback for ambiguous conversational agent routing."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from dataclasses import dataclass

from fdai.agents._framework.base import AgentSpec
from fdai.agents._framework.bragi_models import RoutingDecision
from fdai.core.tiers.t1_lightweight.tier import EmbeddingModel


@dataclass(frozen=True, slots=True)
class SemanticRouterConfig:
    cosine_threshold: float = 0.65
    margin_threshold: float = 0.08

    def __post_init__(self) -> None:
        if not 0 < self.cosine_threshold <= 1:
            raise ValueError("semantic cosine_threshold MUST be in (0, 1]")
        if not 0 <= self.margin_threshold < 1:
            raise ValueError("semantic margin_threshold MUST be in [0, 1)")


class SemanticAgentRouter:
    """Cache frozen agent-domain vectors and route only T0 abstentions or ties."""

    def __init__(
        self,
        *,
        embedding_model: EmbeddingModel,
        specs: Sequence[AgentSpec],
        config: SemanticRouterConfig | None = None,
    ) -> None:
        if not specs:
            raise ValueError("semantic router requires agent specs")
        self._embedding = embedding_model
        self._specs = tuple(specs)
        self.config = config or SemanticRouterConfig()
        self._vectors: dict[str, tuple[float, ...]] | None = None
        self._lock = asyncio.Lock()

    async def route(
        self,
        question: str,
        *,
        t0: RoutingDecision,
        max_contributors: int,
    ) -> RoutingDecision:
        if t0.primary_agent is not None and t0.tie_break != "layer_precedence":
            return t0
        try:
            vectors = await self._domain_vectors()
            query = _validated_vector(
                await self._embedding.embed(question),
                expected_dim=self._embedding.dim,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return _with_semantic_status(t0, provider_status="error")

        scored = sorted(
            ((name, _cosine(query, vector)) for name, vector in vectors.items()),
            key=lambda item: (-item[1], item[0]),
        )
        winner, score = scored[0]
        runner_score = scored[1][1] if len(scored) > 1 else -1.0
        margin = score - runner_score
        if score < self.config.cosine_threshold or margin < self.config.margin_threshold:
            return _with_semantic_status(
                t0,
                provider_status="ok",
                semantic_score=score,
                semantic_margin=margin,
            )
        contributors = tuple(
            name
            for name, candidate_score in scored[1:]
            if candidate_score >= self.config.cosine_threshold
        )[:max_contributors]
        return RoutingDecision(
            primary_agent=winner,
            scores={name: value for name, value in scored},
            tie_break="t1_semantic",
            contributors=contributors,
            method="t1_semantic",
            semantic_score=score,
            semantic_margin=margin,
            provider_status="ok",
        )

    async def _domain_vectors(self) -> dict[str, tuple[float, ...]]:
        if self._vectors is not None:
            return self._vectors
        async with self._lock:
            if self._vectors is not None:
                return self._vectors
            vectors: dict[str, tuple[float, ...]] = {}
            for spec in self._specs:
                charter = spec.conversation
                text = "\n".join(
                    (
                        spec.name,
                        *spec.question_domains,
                        *charter.routing_examples,
                    )
                )
                vectors[spec.name] = _validated_vector(
                    await self._embedding.embed(text),
                    expected_dim=self._embedding.dim,
                )
            self._vectors = vectors
            return vectors


def _with_semantic_status(
    decision: RoutingDecision,
    *,
    provider_status: str,
    semantic_score: float | None = None,
    semantic_margin: float | None = None,
) -> RoutingDecision:
    return RoutingDecision(
        primary_agent=decision.primary_agent,
        scores=dict(decision.scores),
        tie_break=decision.tie_break,
        contributors=decision.contributors,
        method=decision.method,
        semantic_score=semantic_score,
        semantic_margin=semantic_margin,
        provider_status=provider_status,
    )


def _validated_vector(value: Sequence[float], *, expected_dim: int) -> tuple[float, ...]:
    vector = tuple(float(item) for item in value)
    if len(vector) != expected_dim or not vector:
        raise ValueError("embedding vector dimension mismatch")
    if any(not math.isfinite(item) for item in vector):
        raise ValueError("embedding vector contains a non-finite value")
    return vector


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    left_norm = math.sqrt(sum(item * item for item in left))
    right_norm = math.sqrt(sum(item * item for item in right))
    if left_norm == 0 or right_norm == 0:
        return -1.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


__all__ = ["SemanticAgentRouter", "SemanticRouterConfig"]
