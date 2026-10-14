"""Prompt quality and bounded conversational-deliberation contracts."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from decimal import Decimal
from inspect import signature

import pytest
from fdai.agents._framework.bragi_models import RoutingDecision
from fdai.agents._framework.charters import conversation_prompt_layers
from fdai.agents._framework.deliberation import (
    ConversationDeliberator,
    DeliberationClaim,
    DeliberationRequest,
    SynthesisOutcome,
    SynthesisVerification,
    T2ConversationSynthesizer,
    _claim,
)
from fdai.agents._framework.deliberation_evaluation import (
    evaluate_t1_answers,
    evaluation_signals,
)
from fdai.agents._framework.pantheon import PANTHEON_SPECS
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents._framework.semantic_routing import SemanticRouterConfig
from fdai.core.metering.budget import (
    InMemoryBudgetLedger,
    ModelBudget,
)
from fdai.core.metering.pricing import PricingTable
from fdai.core.metering.records import InvocationScope
from fdai.core.metering.sink import InMemoryMeteringSink
from fdai.core.metering.usage import TokenUsage
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

from tests.agents.semantic_judgment_support import (
    restart_action_type,
    semantic_test_boundary,
)

PromptCheck = tuple[str, Callable[[str], bool]]

_CRITIQUE_ROUNDS: tuple[tuple[str, tuple[PromptCheck, ...]], ...] = (
    (
        "identity",
        (
            ("canonical identity", lambda prompt: prompt.startswith("you are ")),
            ("fixed pantheon", lambda prompt: "fixed operational agents" in prompt),
        ),
    ),
    (
        "mandate",
        (
            ("positive mandate", lambda prompt: "mandate:" in prompt),
            ("owned scope", lambda prompt: "owned state" in prompt),
        ),
    ),
    (
        "authority",
        (
            ("role boundary", lambda prompt: "authority boundary:" in prompt),
            ("typed authority", lambda prompt: "typed pipeline remains authoritative" in prompt),
            ("read-only port", lambda prompt: "read-only" in prompt),
        ),
    ),
    (
        "grounding",
        (
            ("allowed tools", lambda prompt: "allowed tools" in prompt),
            ("evidence refs", lambda prompt: "evidence refs" in prompt),
            ("fact inference split", lambda prompt: "facts, inferences, and unknowns" in prompt),
        ),
    ),
    (
        "epistemics",
        (
            ("insufficient evidence", lambda prompt: "insufficient" in prompt),
            ("counterevidence", lambda prompt: "counterevidence" in prompt),
            ("calibrated uncertainty", lambda prompt: "uncertainty" in prompt),
        ),
    ),
    (
        "human_dialogue",
        (
            ("operator locale", lambda prompt: "operator's locale" in prompt),
            ("minimal clarification", lambda prompt: "minimum missing scope" in prompt),
        ),
    ),
    (
        "peer_protocol",
        (
            ("peer discussion", lambda prompt: "peer discussion" in prompt),
            ("requester attribution", lambda prompt: "requester" in prompt),
            ("correlation trace", lambda prompt: "correlation trace" in prompt),
        ),
    ),
    (
        "handoff",
        (
            ("owner named", lambda prompt: "to that owner by name" in prompt),
            ("llm-free routing", lambda prompt: "deterministic and needs no model" in prompt),
            ("owner source", lambda prompt: "from the peer set above" in prompt),
            ("no impersonation", lambda prompt: "never answer in the owner's name" in prompt),
        ),
    ),
    (
        "disagreement",
        (
            ("claim challenge", lambda prompt: "challenge peer claims" in prompt),
            ("no conflict averaging", lambda prompt: "never average conflicts" in prompt),
        ),
    ),
    (
        "tiers",
        (
            ("T1 selection", lambda prompt: "t1" in prompt),
            ("T2 synthesis", lambda prompt: "t2" in prompt),
        ),
    ),
    (
        "economy",
        (
            ("owned facts first", lambda prompt: "owned facts first" in prompt),
            ("model call is last", lambda prompt: "last resort" in prompt),
            ("declared budget", lambda prompt: "pre-declared budget" in prompt),
            ("state the bound", lambda prompt: "state the bound" in prompt),
        ),
    ),
    (
        "security_output",
        (
            ("untrusted content", lambda prompt: 'trusted="false"' in prompt),
            ("sensitive output", lambda prompt: "sensitive values" in prompt),
            ("bounded conclusion", lambda prompt: "bounded conclusion" in prompt),
        ),
    ),
)


def test_each_agent_prompt_passes_every_check_across_twelve_rounds() -> None:
    assert len(_CRITIQUE_ROUNDS) == 12
    assert sum(len(checks) for _, checks in _CRITIQUE_ROUNDS) >= 31

    failures: list[str] = []
    for spec in PANTHEON_SPECS:
        prompt = spec.conversation.system_prompt.casefold()
        for round_name, checks in _CRITIQUE_ROUNDS:
            for check_name, check in checks:
                if not check(prompt):
                    failures.append(f"{spec.name}:{round_name}:{check_name}")

    assert failures == []


def test_each_agent_prompt_carries_its_exact_role_and_budget_contract() -> None:
    for spec in PANTHEON_SPECS:
        assert spec.role_contract() in spec.conversation.system_prompt, spec.name


def test_each_agent_improves_monotonically_over_twelve_critique_rounds() -> None:
    for spec in PANTHEON_SPECS:
        mandate = spec.conversation.system_prompt.splitlines()[1].removeprefix("Mandate: ")
        layers = conversation_prompt_layers(spec.name, mandate)
        assert len(layers) == 12

        scores: list[int] = []
        for round_index in range(1, 13):
            snapshot = "\n".join(layers[:round_index]).casefold()
            results = [check(snapshot) for _, checks in _CRITIQUE_ROUNDS for _, check in checks]
            assert len(results) >= 31
            scores.append(sum(results))

        assert all(after > before for before, after in zip(scores, scores[1:], strict=False))
        assert scores[-1] == sum(len(checks) for _, checks in _CRITIQUE_ROUNDS)


class _CrossDomainEmbedding:
    dim = len(PANTHEON_SPECS)

    async def embed(self, text: str) -> Sequence[float]:
        vector = [0.0] * self.dim
        for index, spec in enumerate(PANTHEON_SPECS):
            if text.startswith(f"{spec.name}\n"):
                vector[index] = 1.0
                return vector
        vector[_agent_index("Njord")] = 1.0
        vector[_agent_index("Freyr")] = 0.8
        return vector


class _T2Synthesizer:
    def __init__(self, *, usage: TokenUsage | None = None, model_key: str = "") -> None:
        self.requests: list[object] = []
        self._usage = usage
        self._model_key = model_key

    async def synthesize(self, request: DeliberationRequest) -> SynthesisOutcome:
        self.requests.append(request)
        return SynthesisOutcome(
            conclusion=(
                "Capacity evidence outweighs the bounded cost objection; disagreement remains."
            ),
            model_identity="publisher-c:model-c",
            model_family="family-c",
            model_key=self._model_key,
            usage=self._usage,
        )


class _SynthesisVerifier:
    async def verify(
        self, request: DeliberationRequest, outcome: SynthesisOutcome
    ) -> SynthesisVerification:
        return SynthesisVerification(
            accepted=outcome.conclusion
            == "Capacity evidence outweighs the bounded cost objection; disagreement remains.",
            request_sha256=request.sha256,
            conclusion_sha256=hashlib.sha256(outcome.conclusion.encode()).hexdigest(),
            evidence_refs=tuple(
                sorted({ref for claim in request.claims for ref in claim.evidence_refs})
            ),
            verifier_identity="publisher-d:independent-reviewer",
        )


class _T2FailureSynthesizer:
    def __init__(self, outcome: str | None | Exception) -> None:
        self.outcome = outcome

    async def synthesize(self, request: DeliberationRequest) -> SynthesisOutcome | None:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        if self.outcome is None:
            return None
        return SynthesisOutcome(
            conclusion=self.outcome,
            model_identity="publisher-c:model-c",
            model_family="family-c",
        )


@pytest.mark.parametrize(
    ("model_identity", "model_family"),
    [("", "family-c"), ("publisher-c:model-c", "")],
)
def test_t2_synthesis_outcome_requires_exact_model_attribution(
    model_identity: str,
    model_family: str,
) -> None:
    with pytest.raises(ValueError, match="model identity and family"):
        SynthesisOutcome(
            conclusion="Bounded conclusion.",
            model_identity=model_identity,
            model_family=model_family,
        )


def _bind_t1_recommendations(
    runtime: PantheonRuntime,
    recommendations: tuple[str | None, str | None],
) -> PantheonRuntime:
    bragi = runtime.agents["Bragi"]
    recommendation_by_agent = dict(zip(("Njord", "Freyr"), recommendations, strict=True))

    async def responder(
        agent_name: str,
        _question: str,
        context: dict[str, object],
    ) -> tuple[dict[str, object], None]:
        recommendation = recommendation_by_agent[agent_name]
        facts: dict[str, object] = {
            "resource_id": "resource-example",
            "evidence_refs": [_agent_state_ref(agent_name)],
        }
        if recommendation is not None:
            facts["recommendation"] = recommendation
        return (
            {
                "primary_agent": agent_name,
                "answer": f"{agent_name} grounded evidence.",
                "facts": facts,
                "prompt_composition": {
                    "prompt_sha256": ("a" if agent_name == "Njord" else "b") * 64
                },
                "trace_ref": context.get("correlation_id", ""),
            },
            None,
        )

    bragi._deliberator._call_responder = responder  # noqa: SLF001
    return runtime


def _runtime(*, t2: T2ConversationSynthesizer | None = None) -> PantheonRuntime:
    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        conversation_semantic_judgment=semantic_test_boundary(),
        action_types=(restart_action_type(),),
        conversation_embedding_model=_CrossDomainEmbedding(),
        semantic_router_config=SemanticRouterConfig(
            cosine_threshold=0.6,
            margin_threshold=0.08,
        ),
        conversation_t2_synthesizer=t2,
        conversation_synthesis_verifier=_SynthesisVerifier(),
    )
    return (
        _bind_t1_recommendations(runtime, ("scale_down", "scale_up")) if t2 is not None else runtime
    )


def test_explicit_t1_discussion_holds_conflict_without_synthesis_calls() -> None:
    synthesizer = _T2Synthesizer()
    result = asyncio.run(
        _runtime(t2=synthesizer).deliberate(
            question="Compare cost and capacity.", requester="Forseti", allow_t2=False
        )
    )
    assert result["status"] == "held"
    assert result["conclusion"] is None
    assert result["t2_status"] == "disabled_by_request"
    assert synthesizer.requests == []


def test_t2_without_independent_verification_does_not_call_the_generator() -> None:
    synthesizer = _T2Synthesizer()
    runtime = _runtime(t2=synthesizer)
    runtime.agents["Bragi"]._deliberator._synthesis_verifier = None  # noqa: SLF001
    result = asyncio.run(
        runtime.deliberate(question="Compare cost and capacity.", requester="Forseti")
    )
    assert result["tier"] == "T1"
    assert result["status"] == "held"
    assert result["conclusion"] is None
    assert result["t2_status"] == "verification_unavailable"
    assert synthesizer.requests == []


def test_t2_rejects_unsupported_operational_conclusion() -> None:
    fabricated = "Independent observation proves 999 production resources are healthy."
    runtime = _runtime(t2=_T2FailureSynthesizer(fabricated))
    result = asyncio.run(
        runtime.deliberate(question="Compare cost and capacity.", requester="Forseti")
    )
    assert result["tier"] == "T1"
    assert result["status"] == "held"
    assert result["conclusion"] is None
    assert result["t2_status"] == "verification_rejected"
    assert result["conclusion"] != fabricated


@pytest.mark.parametrize(
    "changed_field, changed_value",
    [
        ("request_sha256", "c" * 64),
        ("conclusion_sha256", "d" * 64),
        ("evidence_refs", ("unrelated:evidence",)),
        ("verifier_identity", "publisher-c:model-c"),
        ("accepted", 1),
    ],
)
def test_t2_rejects_verification_receipt_substitution(
    changed_field: str,
    changed_value: object,
) -> None:
    class SubstitutingVerifier(_SynthesisVerifier):
        async def verify(
            self, request: DeliberationRequest, outcome: SynthesisOutcome
        ) -> SynthesisVerification:
            receipt = await super().verify(request, outcome)
            return replace(receipt, **{changed_field: changed_value})

    runtime = _runtime(t2=_T2Synthesizer())
    runtime.agents["Bragi"]._deliberator._synthesis_verifier = SubstitutingVerifier()  # noqa: SLF001
    result = asyncio.run(
        runtime.deliberate(question="Compare cost and capacity.", requester="Forseti")
    )
    assert result["tier"] == "T1"
    assert result["status"] == "held"
    assert result["conclusion"] is None
    assert result["t2_status"] == "verification_invalid"


@pytest.mark.parametrize(
    "failure, expected_status",
    [(TimeoutError(), "verification_timeout"), (RuntimeError(), "verification_error")],
)
def test_t2_verifier_failure_preserves_the_t1_evidence(
    failure: Exception,
    expected_status: str,
) -> None:
    class FailingVerifier(_SynthesisVerifier):
        async def verify(
            self, request: DeliberationRequest, outcome: SynthesisOutcome
        ) -> SynthesisVerification:
            raise failure

    runtime = _runtime(t2=_T2Synthesizer())
    runtime.agents["Bragi"]._deliberator._synthesis_verifier = FailingVerifier()  # noqa: SLF001
    result = asyncio.run(
        runtime.deliberate(question="Compare cost and capacity.", requester="Forseti")
    )
    assert result["tier"] == "T1"
    assert result["t2_status"] == expected_status
    assert result["status"] == "held"
    assert result["conclusion"] is None
    assert result["rounds"][0]["contributions"][0]["answer"]


def test_t2_generator_cannot_be_its_own_verifier() -> None:
    class SelfVerifyingSynthesizer(_T2Synthesizer, _SynthesisVerifier):
        pass

    synthesizer = SelfVerifyingSynthesizer()
    with pytest.raises(ValueError, match="independent verifier"):
        ConversationDeliberator(
            specs=PANTHEON_SPECS,
            semantic_router=None,
            t2_synthesizer=synthesizer,
            synthesis_verifier=synthesizer,
            call_responder=_runtime().agents["Bragi"]._call_responder,  # noqa: SLF001
        )


def test_explicit_operator_target_survives_a_different_semantic_owner() -> None:
    runtime = _runtime()
    turn = asyncio.run(
        runtime.ask(
            session_id="explicit-target-session",
            user_id="operator-example",
            question="Compare cost and capacity evidence.",
            target_agent="Saga",
            locale="ko",
        )
    )
    assert turn is not None
    assert turn.primary_agent == "Saga"
    assert turn.decision.method == "explicit_target"
    assert turn.answer["primary_agent"] == "Saga"
    assert "locale_ko" in turn.answer["prompt_composition"]["layers"]


def test_two_model_synthesis_reserves_both_calls_before_generation() -> None:
    class TwoModelSynthesizer(_T2Synthesizer):
        model_calls_per_synthesis = 2

    synthesizer = TwoModelSynthesizer()
    runtime = _runtime(t2=synthesizer)
    result = asyncio.run(
        runtime.deliberate(
            question="Compare cost and capacity.",
            requester="Forseti",
            locale="ko",
        )
    )
    assert result["t2_status"] == "budget_denied"
    assert synthesizer.requests == []


def test_new_verifier_preserves_the_llm_binding_constructor_prefix() -> None:
    from fdai.composition import LlmBindings

    assert list(signature(LlmBindings).parameters)[:13] == [
        "embedding_model",
        "cross_check_models",
        "critic_model",
        "judge_model",
        "debate_orchestrator",
        "rca_reasoner",
        "rubric_evaluator",
        "t2_proposer",
        "conversation_t2_synthesizer",
        "conversation_metering",
        "conversation_pricing",
        "conversation_t2_model_key",
        "conversation_semantic_judgment_factory",
    ]


def _agent_index(name: str) -> int:
    return next(index for index, spec in enumerate(PANTHEON_SPECS) if spec.name == name)


def _agent_state_ref(agent: str) -> str:
    digest = ("a" if agent == "Njord" else "b") * 64
    return f"agent-state:{agent}:sha256:{digest}"


def _test_claim(agent: str, digest_character: str) -> DeliberationClaim:
    return DeliberationClaim(
        agent=agent,
        answer=f"{agent} grounded evidence.",
        evidence_refs=(_agent_state_ref(agent),),
        prompt_sha256=digest_character * 64,
    )


def test_deliberation_requires_t1_instead_of_falling_back_to_t0() -> None:
    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
    )

    result = asyncio.run(
        runtime.deliberate(
            question="Compare cost and capacity evidence.",
            requester="Forseti",
            correlation_id="corr-no-t1",
        )
    )

    assert result["status"] == "abstain"
    assert result["reason"] == "semantic_unavailable"
    assert result["rounds"] == []


def test_t1_deliberation_collects_position_and_peer_critique() -> None:
    result = asyncio.run(
        _runtime().deliberate(
            question="Compare cost and capacity evidence.",
            requester="Forseti",
            correlation_id="corr-t1",
        )
    )

    assert result["status"] == "completed"
    assert result["tier"] == "T1"
    assert result["primary_agent"] == "Njord"
    assert result["participants"] == ["Njord", "Freyr"]
    assert [round_["phase"] for round_ in result["rounds"]] == ["position", "critique"]
    assert result["rounds"][0]["contributions"][0]["agent"] == "Njord"
    assert result["rounds"][1]["contributions"][0]["agent"] == "Freyr"
    assert result["trace_ref"] == "corr-t1"
    assert result["authority"] == "presentation_only"


@pytest.mark.parametrize(
    "peer_recommendation, expected_reason",
    [
        ("scale_down", "no_structured_conflict"),
        ("scale_up", "structured_conflict"),
        (None, "no_structured_conflict"),
    ],
)
def test_peer_critique_compares_the_exact_primary_and_owned_evidence(
    peer_recommendation: str | None,
    expected_reason: str,
) -> None:
    runtime = _bind_t1_recommendations(_runtime(), ("scale_down", peer_recommendation))
    result = asyncio.run(
        runtime.deliberate(
            question="Compare cost and capacity.",
            requester="Forseti",
            correlation_id="peer-review-example",
        )
    )
    contribution = result["rounds"][1]["contributions"][0]
    review = contribution["peer_review"]
    assert review["reason"] == expected_reason
    assert review["primary_agent"] == "Njord"
    assert review["reviewer"] == contribution["agent"] == "Freyr"
    assert review["primary_evidence_refs"] == [_agent_state_ref("Njord")]
    assert review["reviewer_evidence_refs"] == [_agent_state_ref("Freyr")]
    assert bool(review["conflicts"]) is (expected_reason == "structured_conflict")
    assert review["comparison_status"] == (
        "not_comparable"
        if peer_recommendation is None
        else "conflicting"
        if peer_recommendation != "scale_down"
        else "consistent"
    )


@pytest.mark.parametrize("failed_peers", [("Heimdall",), ("Freyr", "Heimdall")])
def test_deliberation_accounts_for_failed_peers_without_claiming_completion(
    failed_peers: tuple[str, ...],
) -> None:
    synthesizer = _T2Synthesizer()

    async def responder(
        agent: str, _question: str, _context: dict[str, object]
    ) -> tuple[dict[str, object] | None, str | None]:
        if agent in failed_peers:
            return None, "timeout"
        return {
            "answer": f"{agent} owned evidence.",
            "facts": {
                "resource_id": "resource-example",
                "recommendation": "scale_down" if agent == "Njord" else "scale_up",
                "evidence_refs": [_agent_state_ref(agent)],
            },
            "prompt_composition": {"prompt_sha256": "a" * 64},
        }, None

    deliberator = ConversationDeliberator(
        specs=PANTHEON_SPECS,
        semantic_router=None,
        t2_synthesizer=synthesizer,
        call_responder=responder,
    )
    result = asyncio.run(
        deliberator.deliberate(
            question="Compare cost, capacity, and observation evidence.",
            requester="Forseti",
            routing_decision=RoutingDecision(
                primary_agent="Njord",
                scores={},
                tie_break=None,
                contributors=("Freyr", "Heimdall"),
            ),
        )
    )

    assert result["status"] == ("partial" if len(failed_peers) == 1 else "abstain")
    assert result["requested_participants"] == ["Njord", "Freyr", "Heimdall"]
    assert len(result["participant_outcomes"]) == 3
    assert {
        outcome["agent"]
        for outcome in result["participant_outcomes"]
        if outcome["status"] == "abstained" and outcome["reason"] == "timeout"
    } == set(failed_peers)
    assert synthesizer.requests == []


def test_deliberation_claim_uses_the_effective_composed_prompt_digest() -> None:
    baseline_digest = "a" * 64
    composed_digest = "b" * 64

    claim = _claim(
        "Njord",
        {
            "answer": "Grounded cost evidence.",
            "facts": {"evidence_refs": ["cost-snapshot:one"]},
            "conversation_policy": {"prompt_sha256": baseline_digest},
            "prompt_composition": {
                "prompt_sha256": composed_digest,
                "layers": ["identity", "phase_position"],
            },
        },
    )

    assert claim is not None
    assert claim.prompt_sha256 == composed_digest


def test_deliberation_claim_preserves_immutable_owned_fact_values() -> None:
    facts = {"count": 7, "state": "held", "evidence_refs": [_agent_state_ref("Njord")]}
    claim = _claim(
        "Njord",
        {
            "answer": "Owned snapshot.",
            "facts": facts,
            "prompt_composition": {"prompt_sha256": "a" * 64},
        },
    )
    assert claim is not None
    facts["count"] = 999
    assert json.loads(claim.facts_json)["count"] == 7


@pytest.mark.parametrize("value", [float("nan"), object(), "x" * 16_385])
def test_deliberation_claim_holds_unserializable_or_oversized_owned_facts(value: object) -> None:
    assert (
        _claim(
            "Njord",
            {
                "answer": "Owned snapshot.",
                "facts": {"value": value, "evidence_refs": [_agent_state_ref("Njord")]},
                "prompt_composition": {"prompt_sha256": "a" * 64},
            },
        )
        is None
    )


def test_deliberation_claim_rejects_non_hex_prompt_digest() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        DeliberationClaim(
            agent="Njord",
            answer="Grounded cost evidence.",
            evidence_refs=("cost-snapshot:one",),
            prompt_sha256="z" * 64,
        )

    assert (
        _claim(
            "Njord",
            {
                "answer": "Grounded cost evidence.",
                "facts": {"evidence_refs": ["cost-snapshot:one"]},
                "prompt_composition": {"prompt_sha256": "z" * 64},
            },
        )
        is None
    )


def test_deliberation_claim_rejects_missing_evidence_refs() -> None:
    digest = "c" * 64

    with pytest.raises(ValueError, match="evidence_refs"):
        DeliberationClaim(
            agent="Njord",
            answer="Unsupported cost claim.",
            evidence_refs=(),
            prompt_sha256=digest,
        )

    assert (
        _claim(
            "Njord",
            {
                "answer": "Unsupported cost claim.",
                "facts": {},
                "prompt_composition": {"prompt_sha256": digest},
            },
        )
        is None
    )


def test_deliberation_request_rejects_primary_claim_owner_mismatch() -> None:
    claims = (_test_claim("Njord", "a"), _test_claim("Freyr", "b"))

    with pytest.raises(ValueError, match="primary_agent"):
        DeliberationRequest(
            question="Compare cost and capacity.",
            requester="Forseti",
            correlation_id="corr-primary-owner",
            primary_agent="Thor",
            claims=claims,
            participant_prompts=(("Njord", "Njord prompt"), ("Freyr", "Freyr prompt")),
        )


def test_deliberation_request_rejects_duplicate_claim_agents() -> None:
    claims = (_test_claim("Njord", "a"), _test_claim("Njord", "b"))

    with pytest.raises(ValueError, match="claim agents MUST be unique"):
        DeliberationRequest(
            question="Compare cost evidence.",
            requester="Forseti",
            correlation_id="corr-duplicate-claim-agent",
            primary_agent="Njord",
            claims=claims,
            participant_prompts=(("Njord", "Position prompt"), ("Njord", "Critique prompt")),
        )


def test_deliberation_request_rejects_prompt_claim_order_mismatch() -> None:
    claims = (_test_claim("Njord", "a"), _test_claim("Freyr", "b"))

    with pytest.raises(ValueError, match="prompts MUST align with claim agents"):
        DeliberationRequest(
            question="Compare cost and capacity.",
            requester="Forseti",
            correlation_id="corr-prompt-claim-order",
            primary_agent="Njord",
            claims=claims,
            participant_prompts=(("Freyr", "Freyr prompt"), ("Njord", "Njord prompt")),
        )


def test_t2_deliberation_synthesizes_without_raising_authority() -> None:
    synthesizer = _T2Synthesizer()
    result = asyncio.run(
        _runtime(t2=synthesizer).deliberate(
            question="Compare cost and capacity evidence.",
            requester="Forseti",
            correlation_id="corr-t2",
        )
    )

    assert result["status"] == "completed"
    assert result["tier"] == "T2"
    assert result["authority"] == "presentation_only"
    assert result["conclusion"].endswith("disagreement remains.")
    assert len(synthesizer.requests) == 1
    request = synthesizer.requests[0]
    assert isinstance(request, DeliberationRequest)
    assert len(request.participant_prompts) == 2
    assert all("Authority boundary:" in prompt for _, prompt in request.participant_prompts)
    baseline_digests = {
        spec.name: spec.conversation_policy()["prompt_sha256"] for spec in PANTHEON_SPECS
    }
    assert all(claim.prompt_sha256 != baseline_digests[claim.agent] for claim in request.claims)
    assert all(
        prompt
        == next(spec.conversation.system_prompt for spec in PANTHEON_SPECS if spec.name == agent)
        for agent, prompt in request.participant_prompts
    )
    assert "Authority boundary:" not in str(result)


def test_deliberation_reuses_verified_semantic_participant_selection() -> None:
    runtime = _bind_t1_recommendations(_runtime(), ("scale_down", "scale_up"))
    deliberator = runtime.agents["Bragi"]._deliberator  # noqa: SLF001
    assert isinstance(deliberator, ConversationDeliberator)

    result = asyncio.run(
        deliberator.deliberate(
            question="Compare cost and capacity evidence.",
            requester="Forseti",
            correlation_id="corr-semantic-route",
            routing_decision=RoutingDecision(
                primary_agent="Njord",
                scores={"Njord": 3.0, "Freyr": 3.0},
                tie_break="canonical_name",
                contributors=("Freyr",),
                method="semantic_judgment",
            ),
        )
    )

    assert result["status"] == "held"
    assert result["conclusion"] is None
    assert result["primary_agent"] == "Njord"
    assert result["participants"] == ["Njord", "Freyr"]
    assert result["routing_method"] == "semantic_judgment"
    assert result["t1_evaluation"]["reason"] == "structured_conflict"


def test_deliberation_supplements_peers_without_replacing_verified_primary() -> None:
    runtime = _bind_t1_recommendations(_runtime(), ("scale_down", "scale_up"))
    deliberator = runtime.agents["Bragi"]._deliberator  # noqa: SLF001
    assert isinstance(deliberator, ConversationDeliberator)

    result = asyncio.run(
        deliberator.deliberate(
            question="Compare cost and capacity evidence.",
            requester="Forseti",
            correlation_id="corr-direct-route",
            routing_decision=RoutingDecision(
                primary_agent="Freyr",
                scores={"Freyr": 3.0},
                tie_break=None,
                contributors=(),
                method="explicit",
            ),
        )
    )

    assert result["status"] == "held"
    assert result["conclusion"] is None
    assert result["primary_agent"] == "Freyr"
    assert result["participants"][0] == "Freyr"
    assert result["routing_method"] == "explicit"


def test_deliberation_deduplicates_reused_contributors() -> None:
    runtime = _bind_t1_recommendations(_runtime(), ("scale_down", "scale_up"))
    deliberator = runtime.agents["Bragi"]._deliberator  # noqa: SLF001
    assert isinstance(deliberator, ConversationDeliberator)

    result = asyncio.run(
        deliberator.deliberate(
            question="Compare cost and capacity evidence.",
            requester="Forseti",
            correlation_id="corr-duplicate-peer",
            routing_decision=RoutingDecision(
                primary_agent="Freyr",
                scores={"Freyr": 3.0, "Njord": 2.0},
                tie_break=None,
                contributors=("Njord", "Njord", "Freyr"),
                method="semantic_judgment",
            ),
        )
    )

    assert result["status"] == "held"
    assert result["conclusion"] is None
    assert result["participants"] == ["Freyr", "Njord"]


@pytest.mark.parametrize(
    ("recommendations", "reason", "signal_count"),
    (
        (("scale_up", "scale_up"), "no_structured_conflict", 2),
        ((None, None), "no_comparable_signals", 0),
    ),
)
def test_t1_answer_evaluation_skips_t2_when_not_required(
    recommendations: tuple[str | None, str | None],
    reason: str,
    signal_count: int,
) -> None:
    synthesizer = _T2Synthesizer()
    runtime = _bind_t1_recommendations(_runtime(t2=synthesizer), recommendations)

    result = asyncio.run(
        runtime.deliberate(
            question="Compare cost and capacity evidence.",
            requester="Forseti",
            correlation_id=f"corr-{reason}",
        )
    )

    assert result["tier"] == "T1"
    assert result["t2_status"] == "not_required"
    assert result["t1_evaluation"] == {
        "status": "not_required",
        "reason": reason,
        "signal_count": signal_count,
        "conflicts": [],
    }
    assert synthesizer.requests == []


def test_t1_answer_evaluation_keeps_identity_fields_in_separate_namespaces() -> None:
    left = _test_claim("Njord", "a")
    right = _test_claim("Freyr", "b")
    left = DeliberationClaim(
        agent=left.agent,
        answer=left.answer,
        evidence_refs=left.evidence_refs,
        prompt_sha256=left.prompt_sha256,
        evaluation_signals=evaluation_signals(
            {"resource_id": "same-text", "recommendation": "scale_down"}
        ),
    )
    right = DeliberationClaim(
        agent=right.agent,
        answer=right.answer,
        evidence_refs=right.evidence_refs,
        prompt_sha256=right.prompt_sha256,
        evaluation_signals=evaluation_signals({"id": "same-text", "recommendation": "scale_up"}),
    )

    evaluation = evaluate_t1_answers((left, right))

    assert evaluation.requires_t2 is False
    assert evaluation.reason == "no_structured_conflict"


def test_fixed_assurance_facts_control_t2_admission_without_prose_inference() -> None:
    synthesizer = _T2Synthesizer()
    runtime = _bind_t1_recommendations(
        _runtime(t2=synthesizer),
        ("scale_down", "scale_down"),
    )

    result = asyncio.run(
        runtime.deliberate(
            question="Compare the fixed cost and capacity scenario.",
            requester="Forseti",
            correlation_id="corr-fixed-scenario",
            fixed_assurance_scenario_id="conversation-assurance-census-v1",
            fixed_assurance_facts={
                "Njord": {
                    "scope_ref": "fixed-t2-scenario",
                    "status": "conflicting",
                },
                "Freyr": {
                    "scope_ref": "fixed-t2-scenario",
                    "status": "consistent",
                },
            },
        )
    )

    assert result["t1_evaluation"] == {
        "status": "escalation_required",
        "reason": "structured_conflict",
        "signal_count": 2,
        "conflicts": [
            {
                "field": "status",
                "left_agent": "Njord",
                "right_agent": "Freyr",
            }
        ],
    }
    assert result["t2_status"] == "completed"
    assert len(synthesizer.requests) == 1


def test_fixed_assurance_facts_reject_unknown_agent() -> None:
    with pytest.raises(ValueError, match="unknown agent"):
        asyncio.run(
            _runtime().deliberate(
                question="Compare the fixed cost and capacity scenario.",
                requester="Forseti",
                correlation_id="corr-invalid-scenario",
                fixed_assurance_scenario_id="conversation-assurance-census-v1",
                fixed_assurance_facts={
                    "Unknown": {
                        "scope_ref": "fixed-t2-scenario",
                        "status": "conflicting",
                    }
                },
            )
        )


@pytest.mark.parametrize(
    ("outcome", "expected_status"),
    (
        (None, "abstained"),
        (RuntimeError("provider unavailable"), "error"),
        ("x" * 4_001, "output_too_large"),
        ("password=supersecretvalue", "sensitive_output"),
    ),
)
def test_t2_failure_preserves_t1_discussion(
    outcome: str | None | Exception,
    expected_status: str,
) -> None:
    result = asyncio.run(
        _runtime(t2=_T2FailureSynthesizer(outcome)).deliberate(
            question="Compare cost and capacity evidence.",
            requester="Forseti",
            correlation_id="corr-t2-failure",
        )
    )

    assert result["status"] == "held"
    assert result["conclusion"] is None
    assert result["reason"] == "structured_conflict_unresolved"
    assert result["tier"] == "T1"
    assert result["t2_status"] == expected_status
    assert result["authority"] == "presentation_only"
    assert len(result["rounds"]) == 2


def test_deliberation_action_intent_requires_typed_pipeline() -> None:
    result = asyncio.run(
        _runtime().deliberate(
            question="restart vm-1 now",
            requester="Forseti",
            correlation_id="corr-action",
        )
    )

    assert result["status"] == "abstain"
    assert result["reason"] == "requires_typed_pipeline"
    assert result["requires_typed_pipeline"] is True


# ---------------------------------------------------------------------------
# Pre-declared escalation budget (cost-model.md: the cap is a ceiling)
# ---------------------------------------------------------------------------


def test_t2_synthesis_stops_at_the_declared_budget_instead_of_calling_again() -> None:
    synthesizer = _T2Synthesizer()
    runtime = _bind_t1_recommendations(
        PantheonRuntime.build(
            provider=InMemoryEventBus(),
            raw_event_topic="fdai.events",
            conversation_semantic_judgment=semantic_test_boundary(),
            conversation_embedding_model=_CrossDomainEmbedding(),
            semantic_router_config=SemanticRouterConfig(
                cosine_threshold=0.6, margin_threshold=0.08
            ),
            conversation_t2_synthesizer=synthesizer,
            conversation_synthesis_verifier=_SynthesisVerifier(),
            conversation_escalation_budget=ModelBudget(max_calls_per_correlation=1),
        ),
        ("scale_down", "scale_up"),
    )

    first = asyncio.run(
        runtime.deliberate(
            question="Compare the cost and capacity evidence for this resource.",
            requester="Forseti",
            correlation_id="corr-budget",
        )
    )
    second = asyncio.run(
        runtime.deliberate(
            question="Compare the cost and capacity evidence for this resource.",
            requester="Forseti",
            correlation_id="corr-budget",
        )
    )

    assert first["t2_status"] == "completed"
    assert second["t2_status"] == "budget_denied"
    # The ceiling holds: the provider was called once, not twice.
    assert len(synthesizer.requests) == 1
    # The bound is reportable, so the answer can say the deeper pass did
    # not run instead of implying it did.
    assert second["escalation_budget"] == {
        "spent_for_correlation": 1,
        "max_per_correlation": 1,
        "cost_microusd_for_correlation": 0,
        "max_cost_microusd_per_correlation": 50_000,
    }
    # Denying escalation degrades to the T1 result, never to an error.
    assert second["status"] == "held"
    assert second["conclusion"] is None
    assert second["tier"] == "T1"


def test_unattributed_participants_see_the_budget_that_gates_synthesis() -> None:
    runtime = _runtime(t2=_T2Synthesizer())
    contexts: list[dict[str, object]] = []

    async def capture(
        agent_name: str,
        _question: str,
        context: dict[str, object],
    ) -> tuple[dict[str, object], None]:
        contexts.append(dict(context))
        spec = next(spec for spec in PANTHEON_SPECS if spec.name == agent_name)
        composition = spec.conversation.compose_prompt().attribution()
        return (
            {
                "primary_agent": agent_name,
                "answer": f"{agent_name} evidence",
                "facts": {
                    "resource_id": "resource-example",
                    "recommendation": ("scale_down" if agent_name == "Njord" else "scale_up"),
                    "evidence_refs": [_agent_state_ref(agent_name)],
                },
                "conversation_policy": spec.conversation_policy(),
                "prompt_composition": composition,
            },
            None,
        )

    runtime.agents["Bragi"]._deliberator._call_responder = capture  # noqa: SLF001
    first = asyncio.run(
        runtime.deliberate(question="Compare cost and capacity.", requester="Forseti")
    )
    contexts.clear()
    second = asyncio.run(
        runtime.deliberate(question="Compare cost and capacity.", requester="Forseti")
    )

    assert first["t2_status"] == "completed"
    assert second["t2_status"] == "budget_denied"
    assert contexts
    assert all(context["escalation_available"] is False for context in contexts)
    assert all(context["escalation_spent"] == 1 for context in contexts)


def test_a_zero_budget_never_calls_the_model_at_all() -> None:
    synthesizer = _T2Synthesizer()
    runtime = _bind_t1_recommendations(
        PantheonRuntime.build(
            provider=InMemoryEventBus(),
            raw_event_topic="fdai.events",
            conversation_semantic_judgment=semantic_test_boundary(),
            conversation_embedding_model=_CrossDomainEmbedding(),
            semantic_router_config=SemanticRouterConfig(
                cosine_threshold=0.6, margin_threshold=0.08
            ),
            conversation_t2_synthesizer=synthesizer,
            conversation_synthesis_verifier=_SynthesisVerifier(),
            conversation_escalation_budget=ModelBudget(
                max_calls_per_correlation=0,
                max_calls_total=0,
            ),
        ),
        ("scale_down", "scale_up"),
    )

    result = asyncio.run(
        runtime.deliberate(
            question="Compare the cost and capacity evidence for this resource.",
            requester="Forseti",
            correlation_id="corr-zero",
        )
    )

    assert synthesizer.requests == []
    assert result["t2_status"] == "budget_denied"
    assert result["tier"] == "T1"


def test_escalation_budget_rejects_an_incoherent_ceiling() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ModelBudget(max_calls_per_correlation=-1)
    with pytest.raises(ValueError, match="fit the total call budget"):
        ModelBudget(max_calls_per_correlation=4, max_calls_total=2)


def test_a_denied_budget_reaches_the_agent_prompt_for_the_turn() -> None:
    """The agent is told the budget is spent, so it cannot imply a deeper pass."""
    from fdai.agents.odin import Odin

    odin = Odin()

    allowed = asyncio.run(odin.on_conversation_turn("portfolio status", {}))
    denied = asyncio.run(
        odin.on_conversation_turn("portfolio status", {"escalation_available": False})
    )

    assert "budget_denied" not in allowed["prompt_composition"]["layers"]
    assert "escalation=available" in allowed["prompt_composition"]["situation"]
    assert "budget_denied" in denied["prompt_composition"]["layers"]
    assert "escalation=denied" in denied["prompt_composition"]["situation"]


def test_a_total_budget_larger_than_the_ledger_is_rejected() -> None:
    """An evictable ledger would refund spent budget, so the ceiling would leak."""
    from fdai.core.metering.budget import MAX_TRACKED_CORRELATIONS

    with pytest.raises(ValueError, match="tracked correlations"):
        ModelBudget(
            max_calls_per_correlation=1,
            max_calls_total=MAX_TRACKED_CORRELATIONS + 1,
        )


def test_spent_budget_is_never_refunded_by_ledger_eviction() -> None:
    from fdai.core.metering.budget import MAX_TRACKED_CORRELATIONS, InMemoryBudgetLedger

    ledger = InMemoryBudgetLedger(
        ModelBudget(max_calls_per_correlation=1, max_calls_total=MAX_TRACKED_CORRELATIONS)
    )
    asyncio.run(ledger.charge("victim", calls=1, cost_microusd=0))

    # Fill the ledger with every other correlation the budget can pay for.
    async def fill() -> None:
        for index in range(MAX_TRACKED_CORRELATIONS - 1):
            await ledger.charge(f"c{index}", calls=1, cost_microusd=0)

    asyncio.run(fill())

    assert asyncio.run(ledger.allows("victim")) is False


def test_the_denied_turn_states_the_bound_it_was_told_to_state() -> None:
    """The economy layer says to state the bound, so the bound MUST be legible."""
    from fdai.agents._framework.conversation_prompt import ConversationSituation
    from fdai.agents.odin import Odin

    odin = Odin()
    envelope = asyncio.run(
        odin.on_conversation_turn(
            "portfolio status",
            {"escalation_available": False, "escalation_spent": 1, "escalation_limit": 1},
        )
    )
    composed = odin.spec.conversation.compose_prompt(
        ConversationSituation(escalation_available=False, escalation_spent=1, escalation_limit=1)
    )

    assert "budget_denied" in envelope["prompt_composition"]["layers"]
    # The instruction "state the bound" is satisfiable only if the bound is
    # in the prompt. Without the numbers it would be another ungroundable ask.
    assert "1 of 1 model call(s) already spent for this correlation" in composed.text


# ---------------------------------------------------------------------------
# The ceiling is money, measured against the shipped pricing table
# ---------------------------------------------------------------------------

_PRICING = PricingTable.from_mapping(
    {"gpt-test": {"input_per_1k": "1.00", "output_per_1k": "2.00", "currency": "USD"}}
)


def _priced_runtime(
    synthesizer: _T2Synthesizer,
    *,
    budget: ModelBudget,
    metering: InMemoryMeteringSink | None = None,
    pricing: PricingTable | None = None,
) -> PantheonRuntime:
    """Wire the runtime the way a composition root does.

    The ledger is charged where spend becomes known - the metering
    record - so the sink is wrapped rather than the deliberator being
    taught to account for money twice.
    """
    ledger = InMemoryBudgetLedger(budget)
    return _bind_t1_recommendations(
        PantheonRuntime.build(
            provider=InMemoryEventBus(),
            raw_event_topic="fdai.events",
            conversation_semantic_judgment=semantic_test_boundary(),
            conversation_embedding_model=_CrossDomainEmbedding(),
            semantic_router_config=SemanticRouterConfig(
                cosine_threshold=0.6, margin_threshold=0.08
            ),
            conversation_t2_synthesizer=synthesizer,
            conversation_synthesis_verifier=_SynthesisVerifier(),
            conversation_escalation_budget=budget,
            conversation_escalation_ledger=ledger,
            conversation_pricing=pricing if pricing is not None else _PRICING,
            # A plain sink on purpose: the deliberator wraps it with the
            # charging sink itself, so no composition root can forget to.
            conversation_metering=metering if metering is not None else InMemoryMeteringSink(),
            conversation_t2_model_key="gpt-test",
        ),
        ("scale_down", "scale_up"),
    )


def test_a_spent_cost_ceiling_denies_the_next_escalation() -> None:
    """Calls remain, money does not: the cost bound denies on its own."""
    synthesizer = _T2Synthesizer(model_key="gpt-test", usage=TokenUsage(1_000, 500))
    runtime = _priced_runtime(
        synthesizer,
        budget=ModelBudget(
            max_calls_per_correlation=8,
            max_calls_total=8,
            # One call prices well above this, so the money runs out first.
            max_cost_microusd_per_correlation=1_000,
            max_cost_microusd_total=1_000,
        ),
    )

    first = asyncio.run(
        runtime.deliberate(question="Compare cost and capacity.", requester="Forseti")
    )
    second = asyncio.run(
        runtime.deliberate(question="Compare cost and capacity.", requester="Forseti")
    )

    assert first["t2_status"] == "completed"
    assert second["t2_status"] == "budget_denied"
    assert len(synthesizer.requests) == 1
    # Calls were still available; the money is what stopped it.
    assert second["escalation_budget"]["spent_for_correlation"] < 8
    assert second["escalation_budget"]["cost_microusd_for_correlation"] >= 1_000


def test_a_measured_call_is_metered_for_replay() -> None:
    """A budget that cannot be audited is not evidence-governed."""
    sink = InMemoryMeteringSink()
    synthesizer = _T2Synthesizer(model_key="gpt-test", usage=TokenUsage(2_000, 1_000))
    runtime = _priced_runtime(synthesizer, budget=ModelBudget(), metering=sink)

    asyncio.run(
        runtime.deliberate(
            question="Compare cost and capacity.",
            requester="Forseti",
            correlation_id="corr-metered",
        )
    )
    recorded = asyncio.run(sink.invocations())

    assert len(recorded) == 1
    invocation = recorded[0]
    assert invocation.correlation_id == "corr-metered"
    assert invocation.usage_scope is InvocationScope.OPERATOR_CHAT
    assert invocation.tier == "T2"
    assert invocation.model_key == "gpt-test"
    # 2,000 prompt tokens at 1.00 + 1,000 completion tokens at 2.00 per 1k.
    assert invocation.cost == Decimal("4.000")
    assert invocation.currency == "USD"


def test_an_unpriced_model_still_hits_the_call_ceiling() -> None:
    """Pricing gaps MUST NOT become budget gaps."""
    synthesizer = _T2Synthesizer(model_key="unpriced", usage=TokenUsage(9_000, 9_000))
    runtime = _priced_runtime(
        synthesizer,
        budget=ModelBudget(max_calls_per_correlation=1, max_calls_total=1),
    )

    first = asyncio.run(
        runtime.deliberate(question="Compare cost and capacity.", requester="Forseti")
    )
    second = asyncio.run(
        runtime.deliberate(question="Compare cost and capacity.", requester="Forseti")
    )

    assert first["t2_status"] == "completed"
    assert second["t2_status"] == "budget_denied"
    assert len(synthesizer.requests) == 1


def test_an_estimate_is_charged_before_a_provider_can_fail() -> None:
    """A failing provider MUST NOT be retriable without limit."""
    runtime = _priced_runtime(
        _T2Synthesizer(model_key="gpt-test"),
        budget=ModelBudget(max_calls_per_correlation=1, max_calls_total=4),
    )
    runtime.agents["Bragi"]._deliberator._t2_synthesizer = _T2FailureSynthesizer(  # noqa: SLF001
        RuntimeError("provider down")
    )

    first = asyncio.run(
        runtime.deliberate(
            question="Compare cost and capacity.",
            requester="Forseti",
            correlation_id="corr-fail",
        )
    )
    second = asyncio.run(
        runtime.deliberate(
            question="Compare cost and capacity.",
            requester="Forseti",
            correlation_id="corr-fail",
        )
    )

    assert first["t2_status"] == "error"
    assert second["t2_status"] == "budget_denied"


def test_unattributed_rounds_do_not_share_one_budget() -> None:
    """An absent correlation id MUST NOT make every question spend the first one's budget."""
    synthesizer = _T2Synthesizer()
    runtime = _priced_runtime(synthesizer, budget=ModelBudget())

    statuses = [
        asyncio.run(runtime.deliberate(question=question, requester="Forseti"))["t2_status"]
        for question in (
            "Compare cost and capacity for the first scope.",
            "Compare cost and capacity for the second scope.",
            # The same question again is the same unit of work, so it is
            # the one round the ceiling denies.
            "Compare cost and capacity for the first scope.",
        )
    ]

    assert statuses == ["completed", "completed", "budget_denied"]
    assert len(synthesizer.requests) == 2


async def test_a_metering_hiccup_never_costs_the_operator_the_answer() -> None:
    """Metering is a side-channel; the model already answered.

    A durable metering store that is briefly unavailable must not turn a
    completed T2 synthesis into a failed turn.
    """

    class _BrokenSink:
        async def record(self, invocation: object) -> None:
            raise RuntimeError("metering store down")

    runtime = _priced_runtime(
        _T2Synthesizer(model_key="gpt-test", usage=TokenUsage(10, 5)),
        budget=ModelBudget(),
        metering=_BrokenSink(),  # type: ignore[arg-type]
    )

    result = await runtime.deliberate(
        question="Compare cost and capacity.",
        requester="Forseti",
        correlation_id="corr-broken-sink",
    )

    assert result["t2_status"] == "completed"
    assert result["t2_model_family"] == "family-c"
    assert "metering_receipt_digest" not in result


async def test_a_failed_metering_write_still_charges_the_money_it_spent() -> None:
    """A ceiling that only counts what it could persist is not a ceiling."""
    from datetime import UTC, datetime

    from fdai.core.metering.budget import BudgetChargingMeteringSink, InMemoryBudgetLedger
    from fdai.core.metering.records import InvocationMode, InvocationScope, LlmInvocation

    class _BrokenSink:
        async def record(self, invocation: object) -> None:
            raise RuntimeError("metering store down")

    ledger = InMemoryBudgetLedger(ModelBudget())
    sink = BudgetChargingMeteringSink(_BrokenSink(), ledger)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError):
        await sink.record(
            LlmInvocation(
                occurred_at=datetime.now(UTC),
                correlation_id="corr-1",
                capability_id="t2.conversation.synthesis",
                model_key="gpt-test",
                tier="T2",
                mode=InvocationMode.SHADOW,
                usage=TokenUsage(1_000, 500),
                usage_scope=InvocationScope.OPERATOR_CHAT,
                cost=Decimal("0.25"),
                currency="USD",
            )
        )

    assert (await ledger.spend("corr-1")).cost_microusd == 250_000


async def test_a_failed_provider_still_reports_the_bound_it_spent() -> None:
    """The call is charged before it is made, so the bound moved."""

    class _ErroringSynthesizer:
        async def synthesize(self, request: object) -> None:
            raise RuntimeError("provider 500")

    runtime = _priced_runtime(
        _ErroringSynthesizer(),  # type: ignore[arg-type]
        budget=ModelBudget(max_calls_per_correlation=2),
    )

    result = await runtime.deliberate(
        question="Compare cost and capacity.",
        requester="Forseti",
        correlation_id="corr-provider-error",
    )

    assert result["t2_status"] == "error"
    assert result["escalation_budget"]["spent_for_correlation"] == 1


async def test_a_recorded_call_states_the_currency_its_price_was_set_in() -> None:
    """A fork may price in its own currency; the record must say so.

    Stamping USD on a KRW price puts a number in the audit trail that
    means something else, and every rollup built on it inherits the lie.
    """
    from fdai.core.metering.pricing import PricingTable

    sink = InMemoryMeteringSink()
    runtime = _priced_runtime(
        _T2Synthesizer(model_key="gpt-test", usage=TokenUsage(1_000, 500)),
        budget=ModelBudget(),
        metering=sink,
        pricing=PricingTable.from_mapping(
            {"gpt-test": {"input_per_1k": "1500", "output_per_1k": "3000", "currency": "KRW"}}
        ),
    )

    result = await runtime.deliberate(
        question="Compare cost and capacity.",
        requester="Forseti",
        correlation_id="corr-krw",
    )

    invocation = (await sink.invocations())[0]
    assert invocation.currency == "KRW"
    assert result["t2_model_family"] == "family-c"
    assert len(result["metering_receipt_digest"]) == 64
