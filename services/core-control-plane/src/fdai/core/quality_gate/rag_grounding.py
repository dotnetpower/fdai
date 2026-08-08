"""RAG-backed :class:`GroundingSource` - the first non-fake grounding leg.

The T2 quality gate's grounding leg (see
[`docs/roadmap/phases/phase-2-quality-and-t1.md § LLM Quality Gate`])
must "validate each cited item exists in the rule catalog and actually
**supports the claim**". The in-memory grounding source in
:mod:`~fdai.core.quality_gate.testing` only satisfies half of
that: it answers "does this rule id exist?" but has no way to say
"does this rule actually justify the proposed action?" - so a T2
model could cite an authoritative but topically-unrelated rule and
still pass grounding.

:class:`RagGroundingSource` closes that gap. It holds a precomputed
embedding of every catalog rule (via an injected
:class:`RuleEmbeddingIndex` seam) and exposes a new
:meth:`RagGroundingSource.supports` method that computes cosine
similarity between the candidate's intent (its ``action_type`` + a
canonical digest of ``params``) and the cited rule's intent
(``check_logic.reference`` + ``remediates``). The gate treats a rule
id as "not grounding" when its similarity is below a configured
threshold, and emits a ``ungrounded_citation:<rule_id>`` reason so the
audit record captures which citation was fabricated / off-topic.

Design notes
------------

- ``core/`` stays CSP-neutral: the embedding index is a Protocol, not a
    hard-coded SDK call. A deployment adapter MAY back it with any
  embedding service by registering an implementation at the
  composition root; the upstream default is the deterministic
  :class:`~fdai.core.quality_gate.testing.HashedRuleEmbeddingIndex`.
- The Protocol :class:`~fdai.core.quality_gate.gate.GroundingSource`
  is **unchanged** - ``supports`` is an additive method the gate finds
  via duck-typing, so the older ID-exists-only implementations still
  work and older callers do not have to be updated in the same PR.
- Rule vectors are computed **once at construction** so per-candidate
  ``supports`` is a single ``encode`` call plus a cosine - bounded and
  synchronous, safe to run inside the gate's event loop.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from fdai.core.quality_gate.gate import QualityCandidate
from fdai.shared.contracts.models import Rule


@runtime_checkable
class RuleEmbeddingIndex(Protocol):
    """Embedding-index seam for :class:`RagGroundingSource`.

    Kept minimal so a fork can back it with any provider (local
    sentence-transformers, Azure OpenAI embeddings, a hosted vector DB)
    without leaking transport concerns into ``core/``. Both methods
    MUST be deterministic for the same input: reproducibility of the
    grounding decision is a safety property - a flaky ``encode`` would
    let the same candidate flip between eligible and ungrounded across
    replays.
    """

    def encode(self, text: str) -> tuple[float, ...]:
        """Return a fixed-dimension embedding of ``text``.

        The dimension is defined by the implementation but MUST be
        constant across calls on the same instance. An empty string
        MAY yield a zero vector.
        """

    def cosine(self, a: tuple[float, ...], b: tuple[float, ...]) -> float:
        """Return cosine similarity in [-1.0, 1.0].

        Zero-norm vectors (either side) MUST return ``0.0`` rather
        than raise, so a rule / candidate with degenerate text falls
        through to the threshold as "not similar".
        """


class HashedRuleEmbeddingIndex:
    """Deterministic token index for catalog grounding.

    This local index is intentionally lexical, not semantic. It provides a
    reproducible production baseline without a network call and rejects cited
    rules that share no intent tokens with the candidate. A deployment can
    replace it with a stronger implementation behind :class:`RuleEmbeddingIndex`.
    """

    _TOKEN_SPLIT_CHARS = " \t\n\r.,;:/_-()[]{}\"'"  # noqa: S105 - punctuation set

    def __init__(self, *, dim: int = 64) -> None:
        if dim < 1:
            raise ValueError("dim MUST be >= 1")
        self._dim = dim

    def encode(self, text: str) -> tuple[float, ...]:
        vector = [0.0] * self._dim
        for token in self._tokenize(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest, "big") % self._dim
            vector[bucket] += 1.0
        return tuple(vector)

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
        for char in cls._TOKEN_SPLIT_CHARS:
            normalized = normalized.replace(char, " ")
        return [token for token in normalized.split(" ") if token]


class RagGroundingSource:
    """Rule-catalog grounding backed by embedding similarity.

    Precomputes an embedding for every rule at construction so the
    per-candidate :meth:`supports` call reduces to one embedding of
    the candidate text plus a cosine. ``threshold`` is the minimum
    similarity required for a citation to be considered supporting;
    below it, the gate emits ``ungrounded_citation:<rule_id>``.

    Parameters
    ----------
    rules:
        Rule id -> :class:`Rule` mapping (same catalog the T0 engine
        and risk-gate load; passing a subset would let a partially-
        loaded fork silently ground actions the full catalog would
        reject).
    embedding_index:
        The injected embedding backend. Precomputation of rule
        vectors happens eagerly so a slow / remote backend at least
        pays that cost once at composition time, not per candidate.
    threshold:
        Cosine cutoff in ``[-1.0, 1.0]``. Below → treated as
        ungrounded. The default (``0.5``) is a conservative starting
        point; the value SHOULD be tuned against the frozen scenario
        set and pinned in configuration, not code.
    """

    def __init__(
        self,
        *,
        rules: Mapping[str, Rule],
        embedding_index: RuleEmbeddingIndex,
        threshold: float = 0.5,
    ) -> None:
        if not -1.0 <= threshold <= 1.0:
            raise ValueError("threshold MUST be in [-1.0, 1.0]")
        self._rules: dict[str, Rule] = dict(rules)
        self._index = embedding_index
        self._threshold = threshold
        self._rule_vectors: dict[str, tuple[float, ...]] = {
            rule_id: embedding_index.encode(self._rule_text(rule))
            for rule_id, rule in self._rules.items()
        }

    # -- GroundingSource contract -----------------------------------------

    def known_rule_ids(self) -> set[str]:
        return set(self._rules.keys())

    def get(self, rule_id: str) -> Rule | None:
        return self._rules.get(rule_id)

    # -- New: supports() --------------------------------------------------

    def supports(self, candidate: QualityCandidate, rule_id: str) -> bool:
        """Return True iff the cited rule is topically relevant to ``candidate``.

        Concretely: ``cosine(encode(candidate_text), encode(rule_text)) >=
        threshold`` where ``candidate_text`` composes the proposed
        ``action_type`` with a canonical digest of ``params`` and
        ``rule_text`` composes the rule's ``check_logic.reference`` with
        its ``remediates`` ontology dispatch. A rule id that is not in
        the loaded catalog returns ``False`` - the gate's "unknown"
        branch already surfaces that case, but defending here keeps the
        method usable outside the gate too.
        """
        rule_vec = self._rule_vectors.get(rule_id)
        if rule_vec is None:
            return False
        candidate_vec = self._index.encode(self._candidate_text(candidate))
        similarity = self._index.cosine(candidate_vec, rule_vec)
        return similarity >= self._threshold

    # -- Text composition -------------------------------------------------

    @staticmethod
    def _candidate_text(candidate: QualityCandidate) -> str:
        """Compose ``action_type`` with a canonical digest of ``params``.

        ``params`` is stringified as ``key=value`` pairs sorted by key
        so the digest is stable across dict-insertion order - an
        identical candidate MUST embed to an identical vector.
        """
        params_digest = " ".join(f"{k}={candidate.params[k]}" for k in sorted(candidate.params))
        if params_digest:
            return f"{candidate.action_type} {params_digest}"
        return candidate.action_type

    @staticmethod
    def _rule_text(rule: Rule) -> str:
        """Compose the rule's check-logic reference with its ``remediates``."""
        return f"{rule.check_logic.reference} {rule.remediates}"


__all__ = [
    "HashedRuleEmbeddingIndex",
    "RagGroundingSource",
    "RuleEmbeddingIndex",
]
