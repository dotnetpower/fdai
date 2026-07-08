"""Property tests for the mixed-model cross-check quorum arithmetic.

Design reference: [phase-2 § LLM Quality Gate](../../docs/roadmap/phases/phase-2-quality-and-t1.md)

> Mixed-model cross-check: run **two or more independent models**
> (distinct providers/weights, not two endpoints of one base model -
> correlated errors defeat the check). Agreement is on the normalized
> structured action; **with N >= 3 require a configured quorum**. Any
> disagreement **escalates to HIL**, never auto-resolves.

The unit tests in :mod:`tests.core.quality_gate.test_gate` cover
N=1,2 with simple agree/disagree fakes. This module adds the property
tests for the N >= 3 quorum arithmetic:

- Enough agreeing models (>= quorum) => :attr:`QualityOutcome.ELIGIBLE`.
- Fewer agreeing models (< quorum) => :attr:`QualityOutcome.DISAGREE`
  (never ``ELIGIBLE``, never silently degrades).
- Quorum equal to N: unanimity is required, one dissenter forces HIL.
- Quorum = 1 with N >= 2: still requires at least one agreement (proves
  the gate does not compute quorum "off by one").

Also cross-checks the composition-level invariant that the resolver
loader rejects a same-publisher primary/secondary pair, so a fork
cannot silently regress to the "two endpoints of one base model"
anti-pattern the design doc calls out.
"""

from __future__ import annotations

import pytest

from fdai.core.quality_gate import (
    QualityCandidate,
    QualityGate,
    QualityGateConfig,
    QualityOutcome,
)
from fdai.core.quality_gate.gate import CrossCheckModel
from fdai.core.quality_gate.testing import (
    InMemoryGroundingSource,
    MatchTypeCrossCheckModel,
    MismatchCrossCheckModel,
    StaticVerifier,
)
from fdai.shared.contracts.models import Rule


def _candidate(valid_rule: dict[str, object]) -> QualityCandidate:
    return QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="example/object-storage/one",
        params={"tag_name": "owner", "tag_value": "team-a"},
        cited_rule_ids=("rule.a",),
    )


def _grounding(valid_rule: dict[str, object]) -> InMemoryGroundingSource:
    payload = dict(valid_rule)
    payload["id"] = "rule.a"
    rule = Rule.model_validate(payload)
    return InMemoryGroundingSource({rule.id: rule})


def _models(agree_count: int, dissent_count: int) -> tuple[CrossCheckModel, ...]:
    agree = tuple(MatchTypeCrossCheckModel(model_id=f"fake-agree-{i}") for i in range(agree_count))
    dissent = tuple(
        MismatchCrossCheckModel(model_id=f"fake-dissent-{i}") for i in range(dissent_count)
    )
    return agree + dissent


# ---------------------------------------------------------------------------
# Quorum arithmetic — parametrized over N >= 3
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("total_models", "agree_count", "quorum", "expected_outcome"),
    [
        # N=3, quorum=2 — the canonical mixed-model config.
        (3, 3, 2, QualityOutcome.ELIGIBLE),  # unanimous agreement -> eligible
        (3, 2, 2, QualityOutcome.ELIGIBLE),  # exactly quorum agrees
        (3, 1, 2, QualityOutcome.DISAGREE),  # 1 agree < quorum -> disagree
        (3, 0, 2, QualityOutcome.DISAGREE),  # unanimous dissent -> disagree
        # N=4, quorum=3 — one dissenter forces HIL.
        (4, 4, 3, QualityOutcome.ELIGIBLE),
        (4, 3, 3, QualityOutcome.ELIGIBLE),
        (4, 2, 3, QualityOutcome.DISAGREE),
        # N=5, quorum=3 — majority quorum tolerates 2 dissenters.
        (5, 5, 3, QualityOutcome.ELIGIBLE),
        (5, 3, 3, QualityOutcome.ELIGIBLE),
        (5, 2, 3, QualityOutcome.DISAGREE),
        (5, 0, 3, QualityOutcome.DISAGREE),
        # N=5, quorum=5 — unanimity required.
        (5, 5, 5, QualityOutcome.ELIGIBLE),
        (5, 4, 5, QualityOutcome.DISAGREE),  # one dissenter breaks unanimity
        # N=3, quorum=1 — degenerate config (one-agree is enough).
        (3, 1, 1, QualityOutcome.ELIGIBLE),
        (3, 0, 1, QualityOutcome.DISAGREE),
    ],
)
@pytest.mark.asyncio
async def test_cross_check_quorum_arithmetic(
    valid_rule: dict[str, object],
    total_models: int,
    agree_count: int,
    quorum: int,
    expected_outcome: QualityOutcome,
) -> None:
    """Quorum arithmetic MUST NOT silently degrade under any (N, k) config.

    Any (agree_count < quorum) combination MUST NOT yield ELIGIBLE.
    Any (agree_count >= quorum) with clean verifier + grounding MUST
    yield ELIGIBLE.
    """
    assert agree_count + (total_models - agree_count) == total_models
    dissent_count = total_models - agree_count
    models = _models(agree_count, dissent_count)
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=models,
        grounding=_grounding(valid_rule),
        config=QualityGateConfig(
            confidence_threshold=0.0,
            require_grounding=False,
            require_cross_check_quorum=quorum,
        ),
    )
    decision = await gate.evaluate(_candidate(valid_rule))
    assert decision.outcome is expected_outcome, (
        f"(N={total_models}, agree={agree_count}, quorum={quorum}) -> "
        f"{decision.outcome} (expected {expected_outcome})"
    )
    # Invariant: an ELIGIBLE outcome REQUIRES at least ``quorum`` agreements.
    if decision.outcome is QualityOutcome.ELIGIBLE:
        assert agree_count >= quorum
    # Invariant: a DISAGREE outcome implies fewer than quorum agreed.
    if decision.outcome is QualityOutcome.DISAGREE:
        assert agree_count < quorum


# ---------------------------------------------------------------------------
# Resolver invariant — same-publisher primary/secondary is a resolve-time deny
# ---------------------------------------------------------------------------


def test_resolver_denies_same_publisher_primary_and_secondary() -> None:
    """Resolve MUST refuse a same-publisher (correlated-error) pair.

    The design doc calls this out explicitly:

        "run two or more independent models (distinct providers/weights,
        not two endpoints of one base model - correlated errors defeat
        the check)."

    The invariant is enforced at :func:`resolve` time. A fork that
    accidentally lists only one publisher in its ``llm-registry.yaml``
    preferences gets a hard failure instead of silently forming a
    correlated pair.
    """
    from fdai.rule_catalog.schema.llm_resolver import (
        CapabilityStatus,
        ResolvedCapability,
        ResolverError,
        _enforce_mixed_model_invariant,
    )

    entries = [
        ResolvedCapability(
            name="t2.reasoner.primary",
            status=CapabilityStatus.RESOLVED,
            publisher="OpenAI",
            family="gpt-4o",
            sku=None,
            capacity_tpm=100_000,
            invocation="chat",
        ),
        ResolvedCapability(
            name="t2.reasoner.secondary",
            status=CapabilityStatus.RESOLVED,
            publisher="OpenAI",  # same publisher — the anti-pattern.
            family="gpt-4o-mini",
            sku=None,
            capacity_tpm=100_000,
            invocation="chat",
        ),
    ]
    with pytest.raises(ResolverError, match="mixed_model_invariant_violated"):
        _enforce_mixed_model_invariant(entries)


def test_resolver_accepts_distinct_publisher_pair() -> None:
    """Two distinct publishers pass the invariant."""
    from fdai.rule_catalog.schema.llm_resolver import (
        CapabilityStatus,
        ResolvedCapability,
        _enforce_mixed_model_invariant,
    )

    entries = [
        ResolvedCapability(
            name="t2.reasoner.primary",
            status=CapabilityStatus.RESOLVED,
            publisher="OpenAI",
            family="gpt-4o",
            sku=None,
            capacity_tpm=100_000,
            invocation="chat",
        ),
        ResolvedCapability(
            name="t2.reasoner.secondary",
            status=CapabilityStatus.RESOLVED,
            publisher="Anthropic",
            family="claude-sonnet",
            sku=None,
            capacity_tpm=100_000,
            invocation="chat",
        ),
    ]
    _enforce_mixed_model_invariant(entries)  # MUST NOT raise.


def test_resolver_permits_same_publisher_when_one_is_hil_only() -> None:
    """A hil-only capability disables the affected reasoner entirely.

    In that case the mixed-model invariant is not applicable — T2 for
    that capability already cannot auto-execute. The resolver MUST NOT
    raise in this case.
    """
    from fdai.rule_catalog.schema.llm_resolver import (
        CapabilityStatus,
        ResolvedCapability,
        _enforce_mixed_model_invariant,
    )

    entries = [
        ResolvedCapability(
            name="t2.reasoner.primary",
            status=CapabilityStatus.RESOLVED,
            publisher="OpenAI",
            family="gpt-4o",
            sku=None,
            capacity_tpm=100_000,
            invocation="chat",
        ),
        ResolvedCapability(
            name="t2.reasoner.secondary",
            status=CapabilityStatus.HIL_ONLY,
            publisher="OpenAI",
            family="gpt-4o-mini",
            sku=None,
            capacity_tpm=0,
            invocation="chat",
        ),
    ]
    _enforce_mixed_model_invariant(entries)  # MUST NOT raise.


@pytest.mark.asyncio
async def test_model_votes_provenance_is_captured(
    valid_rule: dict[str, object],
) -> None:
    """The decision records each model's vote so a T2 judgment is
    reconstructable from the audit (reproducibility)."""
    models = _models(agree_count=2, dissent_count=1)
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=models,
        grounding=_grounding(valid_rule),
        config=QualityGateConfig(
            confidence_threshold=0.0,
            require_grounding=False,
            require_cross_check_quorum=2,
        ),
    )
    decision = await gate.evaluate(_candidate(valid_rule))
    assert len(decision.model_votes) == 3
    assert sum(1 for v in decision.model_votes if v.agreed) == 2
    assert all(v.model_id for v in decision.model_votes)  # ids captured
    assert any(
        v.proposed_action_type == "remediate.tag-add" for v in decision.model_votes
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_rule() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "id": "rule.a",
        "version": "1.0.0",
        "source": "custom",
        "severity": "low",
        "category": "config_drift",
        "resource_type": "object-storage",
        "check_logic": {
            "kind": "rego",
            "reference": "policies/example/tag-owner.rego",
        },
        "remediation": {
            "template_ref": "remediation/example/tag_owner.tftpl",
            "cost_impact_monthly_usd": 0,
        },
        "remediates": "remediate.tag-add",
        "parameters": {"tag_name": "owner", "tag_value": "unassigned"},
        "provenance": {
            "source_url": "https://example.com/rules/a",
            "resolved_ref": "0" * 40,
            "content_hash": "sha256:" + "0" * 64,
            "license": "MIT",
            "redistribution": "embeddable",
            "retrieved_at": "2026-07-05T00:00:00Z",
        },
    }
