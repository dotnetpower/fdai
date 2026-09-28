"""Shadow question-form path: quote binding, successive passes, and the Azure adapter."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fdai.core.conversation.adaptive_call_scope import bind_adaptive_model_budget
from fdai.core.conversation.adaptive_models import AdaptivePolicy
from fdai.core.conversation.adaptive_service import _Budget
from fdai.core.conversation.semantic_reasoning_binding import GatewayAnchorResolver
from fdai.core.conversation.semantic_reasoning_concepts import ConceptShard
from fdai.core.conversation.semantic_reasoning_handles import HandleScope, ResultSetHandle
from fdai.core.conversation.semantic_reasoning_proposal import (
    FormInputHeldError,
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
    def __init__(
        self,
        forms: list[dict[str, Any] | None],
        picks: dict[str, list[str]],
        extraction: dict[str, Any] | None = None,
        second_picks: dict[str, list[str]] | None = None,
    ) -> None:
        self.forms = forms
        self.picks = picks
        self.second_picks = picks if second_picks is None else second_picks
        self.extraction = extraction
        self.form_calls: list[dict[str, Any]] = []
        self.review_calls: list[dict[str, Any]] = []
        self.shards: list[ConceptShard] = []

    async def extract_constraints(self, **kwargs: Any) -> dict[str, Any] | None:
        """Return the configured extraction, or only the request words, which bind nothing."""

        self.review_calls.append(kwargs)
        if self.extraction is not None:
            return self.extraction
        first = kwargs["utterance"].split()[0]
        return {"constraints": [{"quote": {"text": first, "occurrence": 1}, "role": "asks"}]}

    async def propose_form(self, **kwargs: Any) -> dict[str, Any] | None:
        self.form_calls.append(kwargs)
        return self.forms.pop(0) if self.forms else None

    async def choose_concepts(
        self,
        *,
        utterance: str,
        mentions: tuple[dict[str, Any], ...],
        shard: ConceptShard,
        second: bool = False,
    ) -> dict[str, Any]:
        """Answer as the primary chooser, or as the blind second chooser when asked."""

        self.shards.append(shard)
        picks = self.second_picks if second else self.picks
        present = {candidate.id for candidate in shard.candidates}
        return {
            "shard_digest": shard.digest,
            "choices": [
                {
                    "mention": item["mention"],
                    "candidate_ids": [
                        pick for pick in picks.get(item["mention"], []) if pick in present
                    ],
                }
                for item in mentions
            ],
        }


async def _run(model: _Model, *, account_spans: bool = False, **budget: Any) -> Any:
    """Run the shadow over the fixture; word accounting is off unless a test checks it."""

    return await run_reasoning_shadow(
        model=model,
        account_spans=account_spans,
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
    assert len(model.review_calls) == 1
    assert observation.review == "faithful" and observation.released is True
    assert observation.model_calls == 1 + len(model.shards) + len(model.review_calls)
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
    assert invalid.passes[0].goals == ()
    assert invalid.compilations == ()


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


async def test_provider_exceptions_are_contained_as_shadow_errors() -> None:
    class _Broken(_Model):
        async def propose_form(self, **kwargs: Any) -> dict[str, Any] | None:
            raise RuntimeError("provider exploded")

    observation = await _run(_Broken([], {}))

    assert [item.disposition for item in observation.passes] == ["shadow_error"]
    assert observation.passes[0].reasons == ("shadow_error:RuntimeError",)


def _two_candidate_adapter(handler: Any) -> AzureOpenAIQuestionFormModel:
    target = {
        "api_version": "2024-06-01",
        "auth_audience": "https://example.com/.default",
    }
    return AzureOpenAIQuestionFormModel(
        identity=_Identity(),  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        config=AzureOpenAIQuestionFormConfig(
            candidates=(
                ModelRequestTarget(
                    endpoint="https://example.com",
                    deployment="model-a",
                    binding_id="binding-a",
                    **target,
                ),
                ModelRequestTarget(
                    endpoint="https://example.com",
                    deployment="model-b",
                    binding_id="binding-b",
                    **target,
                ),
            ),
            form_system_prompt="Return the closed question form.",
            concept_system_prompt="Choose concepts.",
        ),
    )


async def test_a_secret_in_the_utterance_is_never_sent_for_verbatim_quoting() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    token = "Bearer " + "eyJhbGciOiJIUzI1NiJ9." + "eyJzdWIiOiIxIn0." + "c2lnbmF0dXJl"
    with pytest.raises(FormInputHeldError) as held:
        await _adapter(handler).propose_form(
            utterance=f"Use {token} and list VMs",
            context=(),
            locale="en",
            pass_index=0,
            prior_goals=(),
        )

    assert held.value.reason == "input_redacted"
    assert requests == []


async def test_a_bounded_read_ends_after_one_failed_provider_attempt() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(429)

    budget = _Budget(AdaptivePolicy())
    adapter = _two_candidate_adapter(handler)
    async with bind_adaptive_model_budget(budget):
        result = await adapter.propose_form(
            utterance=_UTTERANCE, context=(), locale="en", pass_index=0, prior_goals=()
        )

    assert result is None
    assert len(requests) == 1


async def test_successful_calls_record_measured_usage_in_the_turn_budget() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(_quoted_form())}}],
                "usage": {"total_tokens": 321},
            },
        )

    budget = _Budget(AdaptivePolicy())
    async with bind_adaptive_model_budget(budget, reserved_calls=1):
        result = await _adapter(handler).propose_form(
            utterance=_UTTERANCE, context=(), locale="en", pass_index=0, prior_goals=()
        )

    assert result == _quoted_form()
    assert len(budget.observations) == 1


async def test_observations_never_carry_utterance_text() -> None:
    utterance = "Which resources have zebra-secret-7 in their name?"
    form = {
        "mentions": [
            {
                "id": "m1",
                "form": "value",
                "domain": "instance",
                "span": {"text": "zebra-secret-7", "occurrence": 1},
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject_scope": "collection",
                "filters": [
                    {
                        "role": "name_fragment",
                        "mention": "m1",
                        "cue": {"text": "have zebra-secret-7 in their name", "occurrence": 1},
                    }
                ],
                "cue": {"text": "Which resources", "occurrence": 1},
                "confidence": 0.9,
            }
        ],
    }
    observation = await run_reasoning_shadow(
        model=_Model([form], {}),
        utterance=utterance,
        context=(),
        locale="en",
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
    )

    assert observation.passes[0].goals[0].status == "compiled"
    assert "zebra-secret-7" not in repr(observation)
    assert "zebra-secret-7" not in json.dumps(observation.summary())


async def test_a_failed_continuation_pass_keeps_the_continuation_visible() -> None:
    model = _Model([_quoted_form(remaining_goals=True), None], {})

    observation = await _run(model, max_form_passes=2)

    assert observation.continuation_pending is True
    assert observation.notes == ("continuation_failed",)


_FOLLOW_UP = "Among them, which ones depend on sql-app?"


def _follow_up_form() -> dict[str, Any]:
    return {
        "mentions": [
            {
                "id": "m1",
                "form": "anaphor",
                "domain": "instance",
                "span": {"text": "them", "occurrence": 1},
            },
            {
                "id": "m2",
                "form": "name",
                "domain": "instance",
                "span": {"text": "sql-app", "occurrence": 1},
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "traverse",
                "subject": "m1",
                "subject_scope": "prior_result",
                "relation": {
                    "sense": "dependency",
                    "anchor": "m2",
                    "anchor_role": "dependency",
                    "result_role": "dependent",
                    "cue": {"text": "depend on", "occurrence": 1},
                },
                "cue": {"text": "which ones", "occurrence": 1},
                "confidence": 0.9,
            }
        ],
    }


async def _follow_up(scope: HandleScope, handles: tuple[ResultSetHandle, ...]) -> Any:
    return await run_reasoning_shadow(
        model=_Model([_follow_up_form()], {}),
        account_spans=False,
        utterance=_FOLLOW_UP,
        context=(),
        locale="en",
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        resolver=GatewayAnchorResolver(
            await fixture_gateway(),
            projection_request=ProjectionRequest(
                caller_role=CeilingRole.READER, declared_purposes=frozenset({PURPOSE})
            ),
            purpose=PURPOSE,
            as_of=NOW,
        ),
        retain_compilations=True,
        handles=handles,
        handle_scope=scope,
    )


def _follow_up_scope(manifest_digest: str | None = None) -> HandleScope:
    return HandleScope(
        conversation_id="conversation-a",
        principal_id="principal-a",
        purpose=PURPOSE,
        manifest_digest=manifest_digest or production_manifest().manifest_digest,
        now=NOW,
    )


def _shown(scope: HandleScope) -> ResultSetHandle:
    return ResultSetHandle(
        handle_id="handle-a",
        conversation_id=scope.conversation_id,
        principal_id=scope.principal_id,
        purpose=scope.purpose,
        manifest_digest=scope.manifest_digest,
        expires_at=NOW + timedelta(minutes=30),
        object_type="Resource",
        row_ids=("aks-1", "kv-1", "vm-2"),
    )


async def test_a_follow_up_compiles_over_the_rows_the_operator_saw() -> None:
    scope = _follow_up_scope()

    observation = await _follow_up(scope, (_shown(scope),))

    (only_pass,) = observation.passes
    assert [goal.status for goal in only_pass.goals] == ["compiled"]
    assert only_pass.reference_digest is not None
    assert observation.summary()["passes"][0]["reference_digest"] == only_pass.reference_digest
    assert "aks-1" not in json.dumps(observation.summary())


async def test_a_follow_up_without_a_handle_clarifies_instead_of_guessing() -> None:
    observation = await _follow_up(_follow_up_scope(), ())

    (only_pass,) = observation.passes
    assert [goal.reasons for goal in only_pass.goals] == [("prior_result_unavailable",)]


async def test_a_handle_scope_from_another_manifest_is_a_caller_error() -> None:
    with pytest.raises(ValueError, match="handle scope"):
        await _follow_up(_follow_up_scope("another-manifest"), ())


async def test_concepts_bind_only_where_two_blind_choosers_agree() -> None:
    vms = {"m2": ["value:compute.vm", "group:compute.vm"]}
    agreeing = _Model([_quoted_form()], vms)
    differing = _Model([_quoted_form()], vms, second_picks={"m2": ["group:network.subnet"]})

    agreed = await _run(agreeing)
    disagreed = await _run(differing)

    assert [goal.status for goal in agreed.passes[0].goals] == ["compiled"]
    (goal,) = disagreed.passes[0].goals
    assert goal.status == "clarify"
    assert goal.reasons == ("concept_disagreement:resource_type",)


async def test_cancelling_the_shadow_never_leaves_the_extraction_running() -> None:
    started = asyncio.Event()
    extraction_cancelled = asyncio.Event()

    class _Stuck(_Model):
        async def propose_form(self, **kwargs: Any) -> dict[str, Any] | None:
            started.set()
            await asyncio.Event().wait()
            return None

        async def extract_constraints(self, **kwargs: Any) -> dict[str, Any] | None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                extraction_cancelled.set()
                raise
            return None

    task = asyncio.create_task(_run(_Stuck([], {})))
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert extraction_cancelled.is_set()
