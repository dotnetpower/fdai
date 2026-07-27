"""Prompt quality and bounded conversational-deliberation contracts."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from decimal import Decimal

import pytest

from fdai.agents._framework.charters import conversation_prompt_layers
from fdai.agents._framework.deliberation import (
    DeliberationRequest,
    SynthesisOutcome,
    T2ConversationSynthesizer,
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
            model_key=self._model_key,
            usage=self._usage,
        )


class _T2FailureSynthesizer:
    def __init__(self, outcome: str | None | Exception) -> None:
        self.outcome = outcome

    async def synthesize(self, request: DeliberationRequest) -> SynthesisOutcome | None:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        if self.outcome is None:
            return None
        return SynthesisOutcome(conclusion=self.outcome)


def _runtime(*, t2: T2ConversationSynthesizer | None = None) -> PantheonRuntime:
    return PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        conversation_embedding_model=_CrossDomainEmbedding(),
        semantic_router_config=SemanticRouterConfig(
            cosine_threshold=0.6,
            margin_threshold=0.08,
        ),
        conversation_t2_synthesizer=t2,
    )


def _agent_index(name: str) -> int:
    return next(index for index, spec in enumerate(PANTHEON_SPECS) if spec.name == name)


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
    assert result["reason"] == "t1_unavailable"
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
    assert "Authority boundary:" not in str(result)


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

    assert result["status"] == "completed"
    assert result["tier"] == "T1"
    assert result["t2_status"] == expected_status
    assert result["authority"] == "presentation_only"
    assert len(result["rounds"]) == 2


def test_deliberation_action_intent_requires_typed_pipeline() -> None:
    result = asyncio.run(
        _runtime().deliberate(
            question="scale down vm-1 now",
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
    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        conversation_embedding_model=_CrossDomainEmbedding(),
        semantic_router_config=SemanticRouterConfig(cosine_threshold=0.6, margin_threshold=0.08),
        conversation_t2_synthesizer=synthesizer,
        conversation_escalation_budget=ModelBudget(max_calls_per_correlation=1),
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
    assert second["status"] == "completed"
    assert second["tier"] == "T1"


def test_a_zero_budget_never_calls_the_model_at_all() -> None:
    synthesizer = _T2Synthesizer()
    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        conversation_embedding_model=_CrossDomainEmbedding(),
        semantic_router_config=SemanticRouterConfig(cosine_threshold=0.6, margin_threshold=0.08),
        conversation_t2_synthesizer=synthesizer,
        conversation_escalation_budget=ModelBudget(
            max_calls_per_correlation=0,
            max_calls_total=0,
        ),
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
    return PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        conversation_embedding_model=_CrossDomainEmbedding(),
        semantic_router_config=SemanticRouterConfig(cosine_threshold=0.6, margin_threshold=0.08),
        conversation_t2_synthesizer=synthesizer,
        conversation_escalation_budget=budget,
        conversation_escalation_ledger=ledger,
        conversation_pricing=pricing if pricing is not None else _PRICING,
        # A plain sink on purpose: the deliberator wraps it with the
        # charging sink itself, so no composition root can forget to.
        conversation_metering=metering if metering is not None else InMemoryMeteringSink(),
        conversation_t2_model_key="gpt-test",
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

    await runtime.deliberate(
        question="Compare cost and capacity.",
        requester="Forseti",
        correlation_id="corr-krw",
    )

    invocation = (await sink.invocations())[0]
    assert invocation.currency == "KRW"
