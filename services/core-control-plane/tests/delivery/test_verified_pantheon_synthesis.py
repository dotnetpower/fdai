"""Verified composition over owned snapshots with no live model calls."""

from __future__ import annotations

import json

import pytest
from fdai.agents import DeliberationClaim, DeliberationRequest
from fdai.core.conversation.model_observation import (
    ConversationModelObservation,
    ConversationModelResponse,
)
from fdai.core.metering.budget import InMemoryBudgetLedger, ModelBudget
from fdai.core.metering.pricing import PricingTable
from fdai.core.metering.sink import InMemoryMeteringSink
from fdai.delivery.verified_pantheon_synthesis import (
    VerifiedPantheonSynthesisVerifier,
    VerifiedPantheonSynthesizer,
)


def _request() -> DeliberationRequest:
    return DeliberationRequest(
        question="Compare the owned state snapshots.",
        requester="Bragi",
        correlation_id="verified-synthesis-example",
        primary_agent="Njord",
        claims=tuple(
            DeliberationClaim(
                agent=agent,
                answer="Owned snapshot.",
                evidence_refs=(f"source:{agent}",),
                prompt_sha256="a" * 64,
                facts_json=json.dumps({"state": "held"}, separators=(",", ":")),
            )
            for agent in ("Njord", "Freyr")
        ),
        participant_prompts=(("Njord", "role one"), ("Freyr", "role two")),
        locale="ko",
    )


def _answer(*, state: str = "held", agents=("Njord", "Freyr")) -> dict[str, object]:
    parts = [*(f"{agent} {state}." for agent in agents), "agent owned projection only."]
    text = " ".join(parts)
    claims = []
    offset = 0
    for index, agent in enumerate(agents):
        ref = {"goal": f"g{index + 1}", "node": "owned_facts", "row": agent, "field": "state"}
        start = offset + parts[index].index(state)
        claims.append(
            {
                "id": f"c{index + 1}",
                "kind": "state",
                "span": {"start": offset, "end": offset + len(parts[index])},
                "refs": [ref],
                "rows": [agent],
                "proposition": {"subject": agent, "predicate": "state", "value": state},
                "literals": [
                    {
                        "span": {"start": offset, "end": offset + len(agent)},
                        "value": agent,
                        "ref": {**ref, "field": "id"},
                    },
                    {
                        "span": {"start": start, "end": start + len(state)},
                        "value": state,
                        "ref": ref,
                    },
                ],
            }
        )
        offset += len(parts[index]) + 1
    claims.append(
        {
            "id": f"c{len(agents) + 1}",
            "kind": "limitation",
            "span": {"start": offset, "end": len(text)},
            "limitation_codes": ["agent_owned_projection_only"],
        }
    )
    return {"text": text, "claims": claims}


class Model:
    def __init__(
        self,
        *,
        state: str = "held",
        reasons: dict[str, str | None] | None = None,
        agents=("Njord", "Freyr"),
    ):
        self.state = state
        self.agents = agents
        self.reasons = reasons or {f"c{index + 1}": None for index in range(len(agents) + 1)}
        self.calls = []

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        stage = kwargs["stage"]
        proposal = (
            _answer(state=self.state, agents=self.agents)
            if stage == "answer"
            else {
                "claims": [
                    {"claim_id": claim, "reason": reason} for claim, reason in self.reasons.items()
                ]
            }
        )
        return ConversationModelResponse(
            proposal,
            ConversationModelObservation(
                model="author" if stage == "answer" else "reviewer",
                usage={"prompt_tokens": 5, "completion_tokens": 7},
                trace_call={},
            ),
        )


def _components(model: Model):
    budget = ModelBudget(max_calls_per_correlation=2)
    ledger = InMemoryBudgetLedger(budget)
    pricing = PricingTable.from_mapping(
        {
            name: {
                "input_per_1k": "0.001",
                "output_per_1k": "0.002",
                "currency": "USD",
            }
            for name in ("author", "reviewer")
        }
    )
    return (
        VerifiedPantheonSynthesizer(
            model,
            "author prompt",
            "publisher-a:author",
            "family-a",
            "author",
            ledger,
            pricing,
            InMemoryMeteringSink(),
        ),
        VerifiedPantheonSynthesisVerifier(
            model,
            "review prompt",
            "publisher-a:author",
            "publisher-b:reviewer",
            "reviewer",
            ledger,
            pricing,
            InMemoryMeteringSink(),
            budget,
        ),
    )


async def test_verified_snapshot_answer_uses_vclaim_and_independent_review() -> None:
    model = Model()
    author, reviewer = _components(model)
    request = _request()
    outcome = await author.synthesize(request)
    assert outcome is not None
    receipt = await reviewer.verify(request, outcome)
    assert receipt is not None and receipt.accepted
    assert receipt.request_sha256 == request.sha256
    assert [call["stage"] for call in model.calls] == ["answer", "verify"]
    assert all(call["payload"]["locale"] == "ko" for call in model.calls)


async def test_invented_state_is_rejected_before_independent_model_call() -> None:
    model = Model(state="healthy")
    author, reviewer = _components(model)
    request = _request()
    outcome = await author.synthesize(request)
    assert outcome is not None
    receipt = await reviewer.verify(request, outcome)
    assert receipt is not None and not receipt.accepted
    assert [call["stage"] for call in model.calls] == ["answer"]


@pytest.mark.parametrize("reasons", [{"c1": None}, {"c1": "not_entailed", "c2": None, "c3": None}])
async def test_missing_or_rejected_entailment_never_approves_the_answer(reasons) -> None:
    author, reviewer = _components(Model(reasons=reasons))
    request = _request()
    outcome = await author.synthesize(request)
    assert outcome is not None
    receipt = await reviewer.verify(request, outcome)
    assert receipt is None or not receipt.accepted


async def test_malformed_generation_retains_measured_cost() -> None:
    class BadModel(Model):
        async def complete(self, **kwargs):
            response = await super().complete(**kwargs)
            return ConversationModelResponse(
                {"text": "Invalid claim record."}, response.observation
            )

    author, _reviewer = _components(BadModel())
    request = _request()
    assert await author.synthesize(request) is None
    assert (await author.ledger.spend(request.correlation_id)).cost_microusd == 19


@pytest.mark.parametrize(
    ("state", "reasons", "review_bound", "incomplete", "expected", "calls"),
    [
        ("held", None, True, False, "completed", 2),
        ("healthy", None, True, False, "verification_rejected", 1),
        ("held", {"c1": "not_entailed", "c2": None}, True, False, "verification_rejected", 2),
        ("held", {"c1": None}, True, False, "verification_invalid", 2),
        ("held", None, False, False, "verification_unavailable", 0),
        ("held", None, True, True, "participant_evidence_incomplete", 0),
    ],
)
async def test_single_owned_answer_uses_existing_claim_review_and_budget(
    state, reasons, review_bound, incomplete, expected, calls
) -> None:
    from fdai.agents import (
        PANTHEON_SPECS,
        ConversationDeliberator,
        agent_state_evidence_ref,
        compose_owned_answer,
    )

    async def unused_responder(*_args):
        raise AssertionError("composition must not reread owned state")

    model = Model(state=state, reasons=reasons, agents=("Njord",))
    author, reviewer = _components(model)
    deliberator = ConversationDeliberator(
        specs=PANTHEON_SPECS,
        semantic_router=None,
        t2_synthesizer=author,
        synthesis_verifier=reviewer if review_bound else None,
        call_responder=unused_responder,
        escalation_budget=reviewer.budget,
        escalation_ledger=author.ledger,
        pricing=author.pricing,
        metering=author.metering,
    )
    facts = {"state": "held"}
    facts["evidence_refs"] = [agent_state_evidence_ref("Njord", facts)]
    values = {
        "question": "Explain the current owned state.",
        "correlation_id": "owned-answer-test",
        "primary_agent": "Njord",
        "answer": {
            "answer": "Unreviewed template.",
            "facts": facts,
            "prompt_composition": {"prompt_sha256": "a" * 64},
        },
        "contributors": [],
        "locale": "ko",
        "incomplete": incomplete,
    }
    result = await compose_owned_answer(deliberator, **values)
    assert result["authority"] == "presentation_only"
    assert result["t2_status"] == expected
    assert len(model.calls) == calls
    assert all(call["payload"]["purpose"] == "owned_answer" for call in model.calls)
    assert all(call["payload"]["locale"] == "ko" for call in model.calls)
    assert all("Unreviewed template." not in str(call["payload"]) for call in model.calls)
    if expected == "completed":
        assert result["conclusion"] == _answer(agents=("Njord",))["text"]
        assert result["synthesis_verification"]["evidence_refs"] == facts["evidence_refs"]
        assert (await author.ledger.spend(values["correlation_id"])).cost_microusd == 38
        repeated = await compose_owned_answer(deliberator, **values)
        assert repeated["t2_status"] == "budget_denied"
        assert len(model.calls) == 2
    else:
        assert result["status"] == "held"
        assert result["conclusion"] is None


async def test_bragi_ask_binds_verified_owned_answer_without_changing_role_views() -> None:
    from fdai.agents import Bragi, agent_state_evidence_ref

    from tests.agents.semantic_judgment_support import semantic_test_boundary

    model = Model(agents=("Njord",))
    author, reviewer = _components(model)
    bragi = Bragi(
        semantic_judgment=semantic_test_boundary(),
        t2_synthesizer=author,
        synthesis_verifier=reviewer,
        escalation_budget=reviewer.budget,
        escalation_ledger=author.ledger,
        pricing=author.pricing,
        metering=author.metering,
    )

    async def owned_responder(_question, _context):
        facts = {"state": "held"}
        facts["evidence_refs"] = [agent_state_evidence_ref("Njord", facts)]
        return {
            "answer": "Unreviewed owned data view.",
            "facts": facts,
            "prompt_composition": {"prompt_sha256": "a" * 64},
        }

    bragi.register_responder("Njord", owned_responder)
    for _ in range(2):
        turn = await bragi.ask(
            session_id="owned-view-session",
            user_id="operator-example",
            question="Njord, explain the current owned state.",
        )
        assert turn.answer["answer"] == _answer(agents=("Njord",))["text"]
        assert turn.answer["owned_answer_composition"]["status"] == "completed"
        assert (
            turn.answer["owned_answer_composition"]["escalation_budget"]["spent_for_correlation"]
            == 2
        )
        assert turn.answer["facts"]["state"] == "held"
    assert len(model.calls) == 4
    role = await bragi.ask(
        session_id="owned-view-session",
        user_id="operator-example",
        question="Njord, explain your role.",
    )
    assert role.answer["answer"] == "Unreviewed owned data view."
    assert "owned_answer_composition" not in role.answer
    assert len(model.calls) == 4


def test_default_factory_binds_without_model_or_identity_calls(monkeypatch) -> None:
    from pathlib import Path
    from types import SimpleNamespace

    import httpx
    from fdai.composition import pantheon_synthesis as factory
    from fdai.delivery.azure.llm.adaptive_answer import (
        AdaptiveModelTarget,
        AzureOpenAIAdaptiveModelConfig,
    )
    from fdai.delivery.azure.llm.request_target import ModelRequestTarget
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    config = AzureOpenAIAdaptiveModelConfig(
        primary=AdaptiveModelTarget(
            ModelRequestTarget("https://models.example.com", "author", api_version="2024-06-01"),
            "publisher-a",
            "family-a",
        ),
        reviewer=AdaptiveModelTarget(
            ModelRequestTarget("https://models.example.com", "reviewer", api_version="2024-06-01"),
            "publisher-b",
            "family-b",
        ),
    )
    monkeypatch.setattr(factory, "resolved_model_config", lambda *args, **kwargs: config)
    author, reviewer = _components(Model())
    client = httpx.AsyncClient()
    try:
        bound = factory.build_pantheon_synthesis(
            resolved=SimpleNamespace(),
            identity=SimpleNamespace(),
            http_client=client,
            endpoint=None,
            endpoint_resolver=None,
            catalog_root=Path(__file__).resolve().parents[4] / "rule-catalog",
            state_store=InMemoryStateStore(),
            pricing=author.pricing,
            metering=reviewer.metering,
        )
        assert bound is not None
        assert bound.budget.max_calls_per_correlation == 2
        assert bound.model_key == "author"
        assert bound.verifier.author_identity != bound.verifier.reviewer_identity
    finally:
        import asyncio

        asyncio.run(client.aclose())
