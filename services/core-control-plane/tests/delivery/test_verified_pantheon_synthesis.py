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


def _answer(*, state: str = "held") -> dict[str, object]:
    parts = [f"Njord {state}.", f"Freyr {state}.", "agent owned projection only."]
    text = " ".join(parts)
    claims = []
    offset = 0
    for index, agent in enumerate(("Njord", "Freyr")):
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
            "id": "c3",
            "kind": "limitation",
            "span": {"start": offset, "end": len(text)},
            "limitation_codes": ["agent_owned_projection_only"],
        }
    )
    return {"text": text, "claims": claims}


class Model:
    def __init__(self, *, state: str = "held", reasons: dict[str, str | None] | None = None):
        self.state = state
        self.reasons = reasons or {"c1": None, "c2": None, "c3": None}
        self.calls = []

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        stage = kwargs["stage"]
        proposal = (
            _answer(state=self.state)
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
