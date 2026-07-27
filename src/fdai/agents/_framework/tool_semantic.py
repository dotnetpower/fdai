"""T1 embedding fallback for tool selection, mirroring agent routing.

Lexical matching answers the questions that use the vocabulary a tool
declares. Real operators mostly do not: measured against fourteen
questions written the way they are actually asked, the lexical planner
selected the right tool three times. Embedding the same declarations
scored exactly the same three, because a declaration and a question sit
in different registers. Embedding each tool together with the way its
question is really asked - :mod:`fdai.agents._framework.tool_examples` -
put all fourteen in the top three.

The shape is deliberately the same as
:class:`~fdai.agents._framework.semantic_routing.SemanticAgentRouter`,
which already resolves ambiguous agent routing: T0 decides first and this
tier only runs when T0 found nothing, tool vectors are cached once, a
cosine floor and a margin keep an unsure match from selecting anything,
and a provider failure degrades silently to the T0 answer. A deployment
with no embedding model bound therefore behaves exactly as it did before
this tier existed.

Determinism is preserved, not traded away. The same question against the
same catalog and the same model yields the same vectors and therefore the
same plan, so a recorded turn still replays. That is why the tier is an
embedding rather than a generative model: a generation that reorders
tools between vendor versions cannot be replayed, and tool selection is
part of the evidence trail.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass

from fdai.agents._framework.base import AgentSpec, ConversationTool
from fdai.agents._framework.tool_planner import MAX_TOOL_PLANS, ConversationToolPlan
from fdai.core.tiers.t1_lightweight.tier import EmbeddingModel

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SemanticToolConfig:
    """Confidence a match needs before it may spend a read.

    Lower than the agent router's floor by design. Routing picks one
    owner out of fifteen and a wrong pick sends the whole question to the
    wrong place; a tool plan only adds supplementary evidence to an
    answer the owning agent produces anyway, so an unsure match costs a
    read rather than the answer.
    """

    cosine_threshold: float = 0.55
    margin_threshold: float = 0.0

    def __post_init__(self) -> None:
        if not 0 < self.cosine_threshold <= 1:
            raise ValueError("semantic tool cosine_threshold MUST be in (0, 1]")
        if not 0 <= self.margin_threshold < 1:
            raise ValueError("semantic tool margin_threshold MUST be in [0, 1)")


@dataclass(frozen=True, slots=True)
class _ToolVector:
    agent: str
    tool_id: str
    vector: tuple[float, ...]


class SemanticToolPlanner:
    """Select owned read tools by meaning when the vocabulary misses."""

    __slots__ = ("_config", "_embedding", "_lock", "_specs", "_vector_dim", "_vectors")

    def __init__(
        self,
        *,
        embedding_model: EmbeddingModel,
        specs: Sequence[AgentSpec],
        config: SemanticToolConfig | None = None,
    ) -> None:
        if not specs:
            raise ValueError("semantic tool planner requires agent specs")
        self._embedding = embedding_model
        self._specs = tuple(specs)
        self._config = config or SemanticToolConfig()
        self._vectors: tuple[_ToolVector, ...] | None = None
        self._vector_dim = 0
        self._lock = asyncio.Lock()

    async def plan(
        self,
        question: str,
        *,
        agents: Sequence[str] = (),
        limit: int = MAX_TOOL_PLANS,
    ) -> tuple[ConversationToolPlan, ...]:
        """Return the tools this question is about, best match first.

        Returns an empty tuple when the provider fails or nothing clears
        the floor. Both mean the same thing to the caller: no
        supplementary evidence for this turn, which is what happened
        before this tier existed.
        """
        if limit <= 0 or not question.strip():
            return ()
        try:
            vectors = await self._tool_vectors()
            query = _unit(await self._embedding.embed(question), expected_dim=self._embedding.dim)
        except asyncio.CancelledError:
            raise
        except Exception:
            return ()
        if query is None:
            return ()
        wanted = frozenset(agents)
        scored = sorted(
            (
                (_cosine(query, entry.vector), entry)
                for entry in vectors
                if not wanted or entry.agent in wanted
            ),
            # Score, then name: a tie MUST NOT resolve by catalog order,
            # or adding an unrelated tool would re-rank a recorded turn.
            key=lambda item: (-item[0], item[1].agent, item[1].tool_id),
        )
        if not scored:
            return ()
        best = scored[0][0]
        if best < self._config.cosine_threshold:
            return ()
        runner = scored[1][0] if len(scored) > 1 else -1.0
        if best - runner < self._config.margin_threshold:
            return ()
        return tuple(
            ConversationToolPlan(
                agent=entry.agent,
                tool_id=entry.tool_id,
                # Scaled to an integer so a plan reads the same whichever
                # tier produced it. The matched terms carry the tier.
                # Tier-local units: a scaled cosine, not a term count.
                score=max(1, int(round(score * 100))),
                matched_terms=(),
                tier="t1_semantic",
            )
            for score, entry in scored[: min(limit, MAX_TOOL_PLANS)]
            if score >= self._config.cosine_threshold
        )

    async def _tool_vectors(self) -> tuple[_ToolVector, ...]:
        """Return the cached tool vectors, building them out of band.

        The build embeds every declared tool once, which is one provider
        round trip each. Under a remote provider that is easily longer
        than the budget the asking question runs under, and a build that
        is cancelled with the question keeps nothing: every later
        question would restart it, cancel it again, and pay for the
        embeddings without ever completing the cache. The tier would be
        permanently off while permanently costing money.

        ``shield`` decouples the two. The question that triggered the
        build gives up on schedule and degrades to the lexical tier, but
        the build survives its cancellation and finishes in the
        background, so a later question finds the cache ready.
        """
        if self._vectors is not None and self._vector_dim == self._embedding.dim:
            return self._vectors
        if self._vectors is not None:
            # The provider was re-deployed on a different model. Cached
            # vectors and a fresh query no longer live in the same space,
            # and a dot product over the shorter of the two is not a
            # smaller cosine - it is a confident number with no meaning.
            # Drop the catalog and rebuild it rather than rank on it.
            _LOG.warning(
                "pantheon_tool_vector_dim_changed",
                extra={"cached_dim": self._vector_dim, "provider_dim": self._embedding.dim},
            )
            self._vectors = None
        return await asyncio.shield(self._build_vectors())

    async def _build_vectors(self) -> tuple[_ToolVector, ...]:
        async with self._lock:
            if self._vectors is not None:
                return self._vectors
            entries: list[_ToolVector] = []
            declared = 0
            for spec in self._specs:
                for tool in spec.conversation.tool_specs:
                    declared += 1
                    vector = _unit(
                        await self._embedding.embed(_tool_text(spec.name, tool)),
                        expected_dim=self._embedding.dim,
                    )
                    if vector is not None:
                        entries.append(
                            _ToolVector(agent=spec.name, tool_id=tool.tool_id, vector=vector)
                        )
            # All or nothing. Ranking is relative, so a catalog missing one
            # tool does not lose that tool - it sends its questions to
            # whichever tool is next closest, silently and permanently.
            # One provider hiccup would quietly rewire the read path, so
            # an incomplete build is refused, logged, and retried by the
            # next question rather than cached as if it were the catalog.
            if len(entries) != declared:
                _LOG.warning(
                    "pantheon_tool_vector_build_incomplete",
                    extra={"embedded": len(entries), "declared": declared},
                )
                return ()
            self._vectors = tuple(entries)
            self._vector_dim = self._embedding.dim
            return self._vectors


def _tool_text(agent: str, tool: ConversationTool) -> str:
    """Return the text a tool is retrieved by.

    Typed, not duck-typed: a misspelled attribute here would silently
    embed an empty string and quietly drop the tool out of reach, which
    is exactly the failure this module exists to avoid.
    """
    keys = " ".join(key.replace("_", " ") for key in tool.fact_keys)
    return " ".join((agent, tool.purpose, keys, *tool.examples)).strip()


def _unit(values: Sequence[float], *, expected_dim: int) -> tuple[float, ...] | None:
    if len(values) != expected_dim:
        return None
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0:
        return None
    return tuple(value / norm for value in values)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    """Dot product of two unit vectors, which is their cosine."""
    return sum(a * b for a, b in zip(left, right, strict=True))


__all__ = ["SemanticToolConfig", "SemanticToolPlanner"]
