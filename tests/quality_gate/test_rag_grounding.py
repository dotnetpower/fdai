"""Tests for :class:`RagGroundingSource` — the first non-fake grounding leg.

Covers:

- :class:`~aiopspilot.core.quality_gate.testing.HashedRuleEmbeddingIndex`
  determinism, zero-vector handling, cosine correctness, and construction
  guards.
- :meth:`~aiopspilot.core.quality_gate.rag_grounding.RagGroundingSource.supports`
  returning ``True`` for a topically-related citation, ``False`` for an
  off-topic citation, and the threshold cutoff around a specific pair.
- :class:`~aiopspilot.core.quality_gate.rag_grounding.RagGroundingSource`
  still satisfying the base :class:`GroundingSource` Protocol
  (``known_rule_ids`` + ``get``) so the gate's ID-exists-only branch
  keeps working.
- Composition with :class:`~aiopspilot.core.quality_gate.QualityGate`:
  an off-topic citation surfaces ``ungrounded_citation:<rule_id>`` in
  the decision reasons and drives the outcome to
  :attr:`QualityOutcome.ABSTAIN`; a topical citation still yields
  :attr:`QualityOutcome.ELIGIBLE`.
"""

from __future__ import annotations

from typing import Any

import pytest

from aiopspilot.core.quality_gate import (
    GroundingSource,
    QualityCandidate,
    QualityGate,
    QualityGateConfig,
    QualityOutcome,
    RagGroundingSource,
    RuleEmbeddingIndex,
)
from aiopspilot.core.quality_gate.testing import (
    HashedRuleEmbeddingIndex,
    MatchTypeCrossCheckModel,
    StaticVerifier,
)
from aiopspilot.shared.contracts.models import Rule

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rule(
    valid_rule: dict[str, Any],
    *,
    rule_id: str,
    check_logic_reference: str = "policies/example/tag-owner.rego",
    remediates: str = "remediate.tag-add",
) -> Rule:
    payload = dict(valid_rule)
    payload["id"] = rule_id
    payload["remediates"] = remediates
    payload["check_logic"] = dict(payload["check_logic"])
    payload["check_logic"]["reference"] = check_logic_reference
    return Rule.model_validate(payload)


def _candidate(
    *,
    action_type: str = "remediate.tag-add",
    params: dict[str, Any] | None = None,
    cited: tuple[str, ...] = ("rule.tag-owner",),
) -> QualityCandidate:
    return QualityCandidate(
        action_type=action_type,
        target_resource_ref="rid-1",
        params={"tag_name": "owner", "tag_value": "team-a"} if params is None else params,
        cited_rule_ids=cited,
        confidence_signals={"retrieval": 0.9, "verifier_margin": 0.9},
    )


# ---------------------------------------------------------------------------
# HashedRuleEmbeddingIndex
# ---------------------------------------------------------------------------


def test_hashed_index_encode_is_deterministic() -> None:
    index = HashedRuleEmbeddingIndex(dim=32)
    v1 = index.encode("remediate.tag-add owner team")
    v2 = index.encode("remediate.tag-add owner team")
    assert v1 == v2
    assert len(v1) == 32


def test_hashed_index_encode_preserves_token_multiplicity() -> None:
    """Same token appearing twice must double its bucket weight."""
    index = HashedRuleEmbeddingIndex(dim=64)
    v_once = index.encode("owner")
    v_twice = index.encode("owner owner")
    assert sum(v_twice) == pytest.approx(2 * sum(v_once))


def test_hashed_index_empty_text_returns_zero_vector() -> None:
    index = HashedRuleEmbeddingIndex(dim=16)
    vec = index.encode("")
    assert vec == tuple([0.0] * 16)


def test_hashed_index_cosine_identical_is_one() -> None:
    index = HashedRuleEmbeddingIndex(dim=32)
    vec = index.encode("remediate.tag-add owner")
    assert index.cosine(vec, vec) == pytest.approx(1.0)


def test_hashed_index_cosine_zero_norm_returns_zero() -> None:
    index = HashedRuleEmbeddingIndex(dim=8)
    zero = tuple([0.0] * 8)
    nonzero = index.encode("remediate")
    assert index.cosine(zero, nonzero) == 0.0
    assert index.cosine(nonzero, zero) == 0.0
    assert index.cosine(zero, zero) == 0.0


def test_hashed_index_cosine_rejects_length_mismatch() -> None:
    index = HashedRuleEmbeddingIndex(dim=8)
    with pytest.raises(ValueError, match="equal-length"):
        index.cosine((1.0, 0.0), (1.0, 0.0, 0.0))


def test_hashed_index_rejects_zero_dim() -> None:
    with pytest.raises(ValueError, match="dim MUST be >= 1"):
        HashedRuleEmbeddingIndex(dim=0)


def test_hashed_index_satisfies_protocol() -> None:
    """Runtime-checkable Protocol conformance."""
    index = HashedRuleEmbeddingIndex()
    assert isinstance(index, RuleEmbeddingIndex)


# ---------------------------------------------------------------------------
# RagGroundingSource — protocol methods
# ---------------------------------------------------------------------------


def test_rag_grounding_source_satisfies_grounding_protocol(valid_rule: dict[str, Any]) -> None:
    rule = _make_rule(valid_rule, rule_id="rule.tag-owner")
    grounding = RagGroundingSource(
        rules={"rule.tag-owner": rule},
        embedding_index=HashedRuleEmbeddingIndex(),
    )
    assert isinstance(grounding, GroundingSource)
    assert grounding.known_rule_ids() == {"rule.tag-owner"}
    assert grounding.get("rule.tag-owner") is rule
    assert grounding.get("unknown") is None


def test_rag_grounding_source_rejects_out_of_range_threshold(
    valid_rule: dict[str, Any],
) -> None:
    rule = _make_rule(valid_rule, rule_id="rule.a")
    index = HashedRuleEmbeddingIndex()
    with pytest.raises(ValueError, match=r"threshold MUST be in"):
        RagGroundingSource(rules={"rule.a": rule}, embedding_index=index, threshold=1.5)
    with pytest.raises(ValueError, match=r"threshold MUST be in"):
        RagGroundingSource(rules={"rule.a": rule}, embedding_index=index, threshold=-1.1)


# ---------------------------------------------------------------------------
# supports() — true / false / threshold
# ---------------------------------------------------------------------------


def test_supports_true_when_candidate_and_rule_share_intent(
    valid_rule: dict[str, Any],
) -> None:
    """Rule text 'policies/tag/owner.rego remediate.tag-add' vs
    candidate text 'remediate.tag-add tag_name=owner tag_value=team-a'
    share the tokens ``remediate``, ``tag``, ``add``, and ``owner`` — cosine
    similarity clears the default 0.5 threshold."""
    rule = _make_rule(
        valid_rule,
        rule_id="rule.tag-owner",
        check_logic_reference="policies/tag/owner.rego",
        remediates="remediate.tag-add",
    )
    grounding = RagGroundingSource(
        rules={"rule.tag-owner": rule},
        embedding_index=HashedRuleEmbeddingIndex(dim=64),
    )
    candidate = _candidate(action_type="remediate.tag-add", cited=("rule.tag-owner",))
    assert grounding.supports(candidate, "rule.tag-owner") is True


def test_supports_false_when_candidate_and_rule_diverge(valid_rule: dict[str, Any]) -> None:
    """Rule text about a firewall / network-restrict action has no
    tokens in common with a tagging candidate — similarity is well
    below the default threshold, so supports() denies the citation."""
    rule = _make_rule(
        valid_rule,
        rule_id="rule.firewall",
        check_logic_reference="policies/network/firewall.rego",
        remediates="remediate.restrict-network-access",
    )
    grounding = RagGroundingSource(
        rules={"rule.firewall": rule},
        embedding_index=HashedRuleEmbeddingIndex(dim=64),
    )
    candidate = _candidate(
        action_type="remediate.tag-add",
        params={"tag_name": "owner", "tag_value": "team-a"},
        cited=("rule.firewall",),
    )
    assert grounding.supports(candidate, "rule.firewall") is False


def test_supports_false_for_unknown_rule_id(valid_rule: dict[str, Any]) -> None:
    rule = _make_rule(valid_rule, rule_id="rule.a")
    grounding = RagGroundingSource(
        rules={"rule.a": rule},
        embedding_index=HashedRuleEmbeddingIndex(),
    )
    assert grounding.supports(_candidate(cited=()), "rule.nonexistent") is False


def test_supports_threshold_gate_flips_the_decision(valid_rule: dict[str, Any]) -> None:
    """Two grounding sources over the same (candidate, rule) pair with
    different thresholds return opposite answers around the measured
    similarity. Proves the threshold is the sole gate — not a hidden
    boolean check inside the implementation."""
    rule = _make_rule(
        valid_rule,
        rule_id="rule.tag-owner",
        check_logic_reference="policies/tag/owner.rego",
        remediates="remediate.tag-add",
    )
    candidate = _candidate(action_type="remediate.tag-add", cited=("rule.tag-owner",))

    # Measure the actual similarity so the test proves the gate around
    # THIS observed value, not a magic number that could drift silently.
    index = HashedRuleEmbeddingIndex(dim=64)
    rule_text = f"{rule.check_logic.reference} {rule.remediates}"
    candidate_text = f"{candidate.action_type} " + " ".join(
        f"{k}={candidate.params[k]}" for k in sorted(candidate.params)
    )
    similarity = index.cosine(index.encode(candidate_text), index.encode(rule_text))
    assert 0.0 < similarity < 1.0  # sanity: neither degenerate nor identical

    below = RagGroundingSource(
        rules={"rule.tag-owner": rule},
        embedding_index=HashedRuleEmbeddingIndex(dim=64),
        threshold=similarity - 1e-6,
    )
    above = RagGroundingSource(
        rules={"rule.tag-owner": rule},
        embedding_index=HashedRuleEmbeddingIndex(dim=64),
        threshold=similarity + 1e-6,
    )
    assert below.supports(candidate, "rule.tag-owner") is True
    assert above.supports(candidate, "rule.tag-owner") is False


def test_candidate_text_stable_across_param_insertion_order(
    valid_rule: dict[str, Any],
) -> None:
    """Reordering ``params`` dict insertion MUST NOT change the
    similarity — otherwise identical candidates could flip between
    grounded and ungrounded across replays, breaking audit
    determinism."""
    rule = _make_rule(valid_rule, rule_id="rule.a")
    index = HashedRuleEmbeddingIndex(dim=64)
    grounding = RagGroundingSource(
        rules={"rule.a": rule},
        embedding_index=index,
        threshold=0.0,  # accept anything — we only check equality below
    )
    forward = QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="rid-1",
        params={"tag_name": "owner", "tag_value": "team-a"},
        cited_rule_ids=("rule.a",),
    )
    reversed_ = QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="rid-1",
        params={"tag_value": "team-a", "tag_name": "owner"},
        cited_rule_ids=("rule.a",),
    )
    # Both must yield the exact same supports() answer.
    assert grounding.supports(forward, "rule.a") is grounding.supports(reversed_, "rule.a")


def test_candidate_text_omits_params_digest_when_empty(valid_rule: dict[str, Any]) -> None:
    """Empty params must not degrade to a trailing space that would
    tokenize differently (defensive; splitters already strip empties)."""
    rule = _make_rule(valid_rule, rule_id="rule.a")
    grounding = RagGroundingSource(
        rules={"rule.a": rule},
        embedding_index=HashedRuleEmbeddingIndex(),
        threshold=0.0,
    )
    empty = QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="rid-1",
        params={},
        cited_rule_ids=("rule.a",),
    )
    # Just prove supports() runs and returns a bool (no exception, no NaN).
    assert isinstance(grounding.supports(empty, "rule.a"), bool)


# ---------------------------------------------------------------------------
# QualityGate composition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_emits_ungrounded_citation_when_supports_denies(
    valid_rule: dict[str, Any],
) -> None:
    """Off-topic citation → gate records ``ungrounded_citation:<id>`` +
    ``no_grounded_citation`` (since no other citations grounded) and
    routes to ABSTAIN."""
    rule = _make_rule(
        valid_rule,
        rule_id="rule.firewall",
        check_logic_reference="policies/network/firewall.rego",
        remediates="remediate.restrict-network-access",
    )
    grounding = RagGroundingSource(
        rules={"rule.firewall": rule},
        embedding_index=HashedRuleEmbeddingIndex(dim=64),
    )
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(),
            MatchTypeCrossCheckModel(model_id="fake-2"),
        ),
        grounding=grounding,
        config=QualityGateConfig(confidence_threshold=0.0),
    )
    candidate = _candidate(action_type="remediate.tag-add", cited=("rule.firewall",))
    decision = await gate.evaluate(candidate)
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert "ungrounded_citation:rule.firewall" in decision.reasons
    assert "no_grounded_citation" in decision.reasons
    assert decision.grounded_rule_ids == ()


@pytest.mark.asyncio
async def test_gate_eligible_when_supports_confirms(valid_rule: dict[str, Any]) -> None:
    """Topical citation → supports() True → the gate treats it as
    grounded and (with the other legs passing) yields ELIGIBLE."""
    rule = _make_rule(
        valid_rule,
        rule_id="rule.tag-owner",
        check_logic_reference="policies/tag/owner.rego",
        remediates="remediate.tag-add",
    )
    grounding = RagGroundingSource(
        rules={"rule.tag-owner": rule},
        embedding_index=HashedRuleEmbeddingIndex(dim=64),
    )
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(),
            MatchTypeCrossCheckModel(model_id="fake-2"),
        ),
        grounding=grounding,
        config=QualityGateConfig(confidence_threshold=0.0),
    )
    candidate = _candidate(action_type="remediate.tag-add", cited=("rule.tag-owner",))
    decision = await gate.evaluate(candidate)
    assert decision.outcome is QualityOutcome.ELIGIBLE
    assert decision.grounded_rule_ids == ("rule.tag-owner",)
    assert decision.reasons == ()


@pytest.mark.asyncio
async def test_gate_partial_grounding_still_abstains_with_mix_of_reasons(
    valid_rule: dict[str, Any],
) -> None:
    """Two citations: one topical (grounded), one off-topic (ungrounded).
    The gate records the ungrounded one but keeps the topical one in
    ``grounded_rule_ids`` — proves supports() is applied per-citation,
    not as an all-or-nothing gate."""
    tag_rule = _make_rule(
        valid_rule,
        rule_id="rule.tag-owner",
        check_logic_reference="policies/tag/owner.rego",
        remediates="remediate.tag-add",
    )
    firewall_rule = _make_rule(
        valid_rule,
        rule_id="rule.firewall",
        check_logic_reference="policies/network/firewall.rego",
        remediates="remediate.restrict-network-access",
    )
    grounding = RagGroundingSource(
        rules={"rule.tag-owner": tag_rule, "rule.firewall": firewall_rule},
        embedding_index=HashedRuleEmbeddingIndex(dim=64),
    )
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(),
            MatchTypeCrossCheckModel(model_id="fake-2"),
        ),
        grounding=grounding,
        config=QualityGateConfig(confidence_threshold=0.0),
    )
    candidate = _candidate(
        action_type="remediate.tag-add",
        cited=("rule.tag-owner", "rule.firewall"),
    )
    decision = await gate.evaluate(candidate)
    # Still ABSTAIN because the ungrounded citation is a recorded reason.
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert "ungrounded_citation:rule.firewall" in decision.reasons
    assert "no_grounded_citation" not in decision.reasons
    assert decision.grounded_rule_ids == ("rule.tag-owner",)


@pytest.mark.asyncio
async def test_gate_falls_back_to_id_only_when_grounding_source_has_no_supports(
    valid_rule: dict[str, Any],
) -> None:
    """A grounding source that does NOT expose ``supports`` still
    works — the gate's duck-typed check silently falls back to the
    ID-exists-only behavior (backward compat)."""
    from aiopspilot.core.quality_gate.testing import InMemoryGroundingSource

    rule = _make_rule(valid_rule, rule_id="rule.a")
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(),
            MatchTypeCrossCheckModel(model_id="fake-2"),
        ),
        grounding=InMemoryGroundingSource({"rule.a": rule}),
        config=QualityGateConfig(confidence_threshold=0.0),
    )
    # Even though the candidate topic diverges from the rule (an
    # ungrounded call in the RAG sense), the ID-only grounding source
    # accepts it. Proves we did not tighten the base Protocol.
    decision = await gate.evaluate(_candidate(action_type="remediate.unrelated", cited=("rule.a",)))
    assert decision.outcome is QualityOutcome.ELIGIBLE
    assert decision.grounded_rule_ids == ("rule.a",)
