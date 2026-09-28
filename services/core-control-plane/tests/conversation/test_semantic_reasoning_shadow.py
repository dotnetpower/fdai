"""Shadow question-form path: quote binding, successive passes, and the Azure adapter."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fdai.core.conversation.semantic_reasoning_binding import GatewayAnchorResolver
from fdai.core.conversation.semantic_reasoning_concepts import ConceptShard
from fdai.core.conversation.semantic_reasoning_proposal import (
    locate_quote,
    question_form_proposal_schema,
    resolve_question_form,
)
from fdai.core.conversation.semantic_reasoning_shadow import ShadowBudget, run_reasoning_shadow
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.delivery.azure.llm.semantic_question_form import (
    AzureOpenAIQuestionFormConfig,
    AzureOpenAIQuestionFormModel,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.acl import ProjectionRequest

from tests.conversation.semantic_reasoning_support import (
    DEFAULT_LOOKBACK_SECONDS,
    NOW,
    PURPOSE,
    fixture_gateway,
    plan_verifier,
    production_manifest,
)

_UTTERANCE = "How many VMs depend on sql-app, and what depends on sql-app?"


def _quoted_form(**overrides: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "mentions": [
            {
                "id": "m1",
                "form": "name",
                "domain": "instance",
                "span": {"text": "sql-app", "occurrence": 1},
            },
            {
                "id": "m2",
                "form": "concept",
                "domain": "resource_type",
                "span": {"text": "VMs", "occurrence": 1},
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "count",
                "subject": "m1",
                "subject_scope": "anchor",
                "filters": [{"role": "type", "mention": "m2"}],
                "relation": {
                    "sense": "dependency",
                    "anchor_role": "dependency",
                    "result_role": "dependent",
                    "cue": {"text": "depend on", "occurrence": 1},
                },
                "cue": {"text": "How many", "occurrence": 1},
                "confidence": 0.9,
            }
        ],
    }
    form.update(overrides)
    return form


class _Model:
    def __init__(self, forms: list[dict[str, Any] | None], picks: dict[str, list[str]]) -> None:
        self.forms = forms
        self.picks = picks
        self.form_calls: list[dict[str, Any]] = []
        self.shards: list[ConceptShard] = []

    async def propose_form(self, **kwargs: Any) -> dict[str, Any] | None:
        self.form_calls.append(kwargs)
        return self.forms.pop(0) if self.forms else None

    async def choose_concepts(
        self, *, utterance: str, mentions: tuple[dict[str, Any], ...], shard: ConceptShard
    ) -> dict[str, Any]:
        self.shards.append(shard)
        present = {candidate.id for candidate in shard.candidates}
        return {
            "shard_digest": shard.digest,
            "choices": [
                {
                    "mention": item["mention"],
                    "candidate_ids": [
                        pick for pick in self.picks.get(item["mention"], []) if pick in present
                    ],
                }
                for item in mentions
            ],
        }


async def _run(model: _Model, **budget: Any) -> Any:
    return await run_reasoning_shadow(
        model=model,
        utterance=_UTTERANCE,
        context=(),
        locale="en",
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        budget=ShadowBudget(**budget) if budget else None,
        resolver=GatewayAnchorResolver(
            await fixture_gateway(),
            projection_request=ProjectionRequest(
                caller_role=CeilingRole.READER, declared_purposes=frozenset({PURPOSE})
            ),
            purpose=PURPOSE,
            as_of=NOW,
        ),
    )


def test_quotes_bind_to_the_named_verbatim_occurrence() -> None:
    second = _quoted_form()
    second["mentions"][0]["span"]["occurrence"] = 2

    first = resolve_question_form(_quoted_form(), utterance=_UTTERANCE)
    bound = resolve_question_form(second, utterance=_UTTERANCE)

    assert first.form is not None and bound.form is not None
    assert first.form.mentions[0].span.start == _UTTERANCE.index("sql-app")
    assert bound.form.mentions[0].span.start == _UTTERANCE.rindex("sql-app")
    assert locate_quote("sql-app", 3, _UTTERANCE) is None


@pytest.mark.parametrize(
    ("mutate", "reason"),
    (
        (
            lambda form: form["mentions"][0].update(span={"text": "SQL-APP", "occurrence": 1}),
            "quote_not_verbatim:span",
        ),
        (lambda form: form["goals"][0].update(cue={"start": 0, "end": 3}), "quote_invalid:cue"),
        (
            lambda form: form["goals"][0].update(operation="query.inventory"),
            "form_contract_invalid:goals.0.operation",
        ),
    ),
)
def test_unquotable_or_unclosed_proposals_fail_closed(mutate: Any, reason: str) -> None:
    form = _quoted_form()
    mutate(form)

    resolution = resolve_question_form(form, utterance=_UTTERANCE)

    assert resolution.form is None
    assert reason in resolution.reasons


def test_model_schema_asks_for_quotes_not_offsets() -> None:
    schema = question_form_proposal_schema()

    assert set(schema["$defs"]["SourceSpan"]["properties"]) == {"text", "occurrence"}
    assert "execution_authority" in schema["properties"]


async def test_shadow_turn_compiles_grounded_goals_and_records_digests_only() -> None:
    model = _Model([_quoted_form()], {"m2": ["value:compute.vm", "group:compute.vm"]})

    observation = await _run(model)
    summary = observation.summary()

    (only_pass,) = observation.passes
    assert only_pass.disposition == "admitted"
    assert [goal["status"] for goal in summary["passes"][0]["goals"]] == ["compiled"]
    assert observation.model_calls == 1 + len(model.shards)
    assert _UTTERANCE not in json.dumps(summary)
    assert observation.execution_authority is False


async def test_remaining_goals_run_bounded_successive_passes() -> None:
    first = _quoted_form(remaining_goals=True)
    second = _quoted_form()
    model = _Model([first, second, _quoted_form(remaining_goals=True)], {})

    observation = await _run(model, max_form_passes=2)

    assert [item.disposition for item in observation.passes] == ["admitted", "admitted"]
    assert model.form_calls[1]["pass_index"] == 1
    assert model.form_calls[1]["prior_goals"] == (
        {"level": "instance", "operation": "count", "subject_scope": "anchor"},
    )
    assert observation.continuation_pending is False


async def test_unfinished_continuation_is_reported_not_hidden() -> None:
    model = _Model([_quoted_form(remaining_goals=True)], {})

    observation = await _run(model, max_form_passes=1)

    assert observation.continuation_pending is True
    assert observation.notes == ("continuation_budget_exhausted",)


async def test_model_unavailability_and_invalid_forms_stop_without_fallback() -> None:
    unavailable = await _run(_Model([None], {}))
    invalid = await _run(_Model([{"goals": "not-a-list", "mentions": []}], {}))

    assert [item.disposition for item in unavailable.passes] == ["model_unavailable"]
    assert invalid.passes[0].disposition == "invalid"
    assert invalid.passes[0].compilation is None


class _Identity:
    async def get_token(self, audience: str) -> Any:
        assert audience == "https://example.com/.default"
        return SimpleNamespace(token="not-a-real-token")


def _adapter(handler: Any) -> AzureOpenAIQuestionFormModel:
    return AzureOpenAIQuestionFormModel(
        identity=_Identity(),  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        config=AzureOpenAIQuestionFormConfig(
            candidates=(
                ModelRequestTarget(
                    endpoint="https://example.com",
                    deployment="example-model",
                    api_version="2024-06-01",
                    auth_audience="https://example.com/.default",
                    binding_id="binding-form",
                ),
            ),
            form_system_prompt="Return the closed question form.",
            concept_system_prompt="Choose concepts.",
        ),
    )


async def test_adapter_sends_strict_schema_and_returns_the_json_object() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        captured["authorization"] = request.headers["Authorization"]
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(_quoted_form())}}]}
        )

    proposal = await _adapter(handler).propose_form(
        utterance=_UTTERANCE, context=(), locale="en", pass_index=0, prior_goals=()
    )

    assert proposal == _quoted_form()
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert captured["authorization"] == "Bearer not-a-real-token"
    assert json.loads(captured["messages"][1]["content"])["utterance"] == _UTTERANCE


async def test_adapter_returns_none_for_transport_or_malformed_output() -> None:
    def failing(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={})

    def malformed(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    arguments = {
        "utterance": _UTTERANCE,
        "context": (),
        "locale": "en",
        "pass_index": 0,
        "prior_goals": (),
    }

    assert await _adapter(failing).propose_form(**arguments) is None
    assert await _adapter(malformed).propose_form(**arguments) is None
