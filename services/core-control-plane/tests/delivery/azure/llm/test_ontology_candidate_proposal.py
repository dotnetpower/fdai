"""Single-attempt model proposals over complete frozen diagnostic inputs."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fdai.core.prompts import PromptAssembler
from fdai.core.prompts.registry import FileSystemPromptRegistry
from fdai.delivery.azure.llm import semantic_planning as planning_module
from fdai.delivery.azure.llm.semantic_planning import (
    AzureOpenAISemanticPlanningModel,
    AzureOpenAISemanticPlanningModelConfig,
)
from fdai.delivery.catalog_search.ontology_candidate_proposal import (
    OntologyCandidateProposal,
    candidate_proposal_payload,
)
from pydantic import ValidationError

from tests.delivery.azure.llm.test_semantic_planning import (
    _config,
    _Identity,
    _target,
)
from tests.delivery.catalog_search.test_ontology_evaluation_runner import _harness

_QUERY = "Select all Resource objects."


def _candidate_config() -> AzureOpenAISemanticPlanningModelConfig:
    registry = FileSystemPromptRegistry(Path(__file__).parents[6] / "rule-catalog")
    selection = registry.resolve(
        "semantic.query.plan", profile_id="diagnostic.ontology-candidate-selection"
    )
    prompt = PromptAssembler(selection).complete
    return replace(
        _config(),
        plan_system_prompt=prompt.system_text,
        plan_prompt_manifest=prompt.replay_manifest(),
    )


def _proposal() -> dict[str, object]:
    return {
        "status": "select",
        "reason": "conditions_proposed",
        "clauses": [{"object_type": "Resource"}],
        "clause_quotes": [_QUERY],
    }


async def test_actual_adapter_proposal_reaches_secured_membership_without_embedding() -> None:
    harness = await _harness(typed_selection_available=True)
    requests: list[httpx.Request] = []

    async def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": json.dumps(_proposal())}}
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        model = AzureOpenAISemanticPlanningModel(
            identity=_Identity(),
            http_client=http,
            config=_candidate_config(),
            owner_loop=asyncio.get_running_loop(),
        )
        proposed = await model.propose_candidate_selection(
            query=_QUERY, manifest=harness.manifest, build=harness.build, staged=harness.staged
        )
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    transmitted = json.loads(body["messages"][1]["content"])["untrusted_input"]
    assert len(transmitted["documents"]) == len(harness.build.documents)
    assert proposed.input_digest == transmitted["input_digest"]
    assert proposed.selection is not None
    assert proposed.observation.prompt_replay_manifest is not None
    assert proposed.observation.prompt_replay_manifest.profile_id == (
        "diagnostic.ontology-candidate-selection"
    )
    result = await harness.reader.search(
        _QUERY,
        staged=harness.staged,
        manifest=harness.manifest,
        gateway=harness.gateway,
        as_of=harness.clock.now,
        selection=proposed.selection,
    )
    assert result.authorized is not None
    assert tuple(item.id for item in result.authorized.objects) == ("resource-0", "resource-1")
    assert result.score_kind == "predicate_membership"
    assert harness.embedder.calls == 0


@pytest.mark.parametrize("failure", ["429", "503", "timeout", "malformed", "length", "quote"])
async def test_provider_or_proposal_failure_never_retries_or_becomes_no_match(failure: str) -> None:
    harness, calls = await _harness(), 0

    async def transport(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure in {"429", "503"}:
            return httpx.Response(int(failure))
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        proposal = _proposal()
        if failure == "quote":
            proposal["clause_quotes"] = ["not present in the query"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length" if failure == "length" else "stop",
                        "message": {
                            "content": "not JSON"
                            if failure == "malformed"
                            else json.dumps(proposal)
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        model = AzureOpenAISemanticPlanningModel(
            identity=_Identity(),
            http_client=http,
            config=_candidate_config(),
            owner_loop=asyncio.get_running_loop(),
        )
        with pytest.raises(ValueError, match="unavailable|source span"):
            await model.propose_candidate_selection(
                query=_QUERY, manifest=harness.manifest, build=harness.build, staged=harness.staged
            )
    assert calls == 1


@pytest.mark.parametrize("invalid", ["fallback", "deadline", "missing-profile", "wrong-profile"])
async def test_unbounded_or_unbound_configuration_stops_before_dispatch(invalid: str) -> None:
    harness, calls = await _harness(), 0
    config = _candidate_config()
    if invalid == "fallback":
        config = replace(config, candidates=(_target("primary"), _target("secondary")))
    elif invalid == "deadline":
        config = replace(config, timeout_seconds=6)
    elif invalid == "missing-profile":
        config = replace(config, plan_prompt_manifest=None)
    else:
        assert config.plan_prompt_manifest is not None
        config = replace(
            config,
            plan_prompt_manifest=replace(config.plan_prompt_manifest, profile_id="active.test"),
        )

    async def transport(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("invalid configuration reached provider")

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        model = AzureOpenAISemanticPlanningModel(
            identity=_Identity(),
            http_client=http,
            config=config,
            owner_loop=asyncio.get_running_loop(),
        )
        with pytest.raises(ValueError, match="one bounded target"):
            await model.propose_candidate_selection(
                query=_QUERY, manifest=harness.manifest, build=harness.build, staged=harness.staged
            )
    assert calls == 0


async def test_context_rejects_a_modified_document_before_any_call() -> None:
    harness = await _harness()
    build = replace(
        harness.build,
        documents=(replace(harness.build.documents[0], text="{}"), *harness.build.documents[1:]),
    )
    with pytest.raises(ValueError, match="document digest mismatch"):
        candidate_proposal_payload(
            query=_QUERY, manifest=harness.manifest, build=build, staged=harness.staged
        )


def test_clarification_is_explicit_and_cannot_hide_executable_conditions() -> None:
    proposal = OntologyCandidateProposal(
        status="clarify", reason="unresolved_reference", clauses=(), clause_quotes=()
    )
    assert proposal.status == "clarify"
    with pytest.raises(ValidationError):
        OntologyCandidateProposal.model_validate({**_proposal(), "status": "clarify"})
    with pytest.raises(ValidationError):
        OntologyCandidateProposal.model_validate({**_proposal(), "clauses": []})


async def test_changed_minimized_input_holds_before_provider_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness, calls = await _harness(), 0
    prepare = planning_module.prepare_model_messages
    monkeypatch.setattr(
        planning_module,
        "prepare_model_messages",
        lambda messages: replace(
            prepare(messages),
            messages=(
                {"role": "system", "content": "sanitized system"},
                {"role": "user", "content": "sanitized input"},
            ),
        ),
    )

    async def transport(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("changed context reached provider")

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        model = AzureOpenAISemanticPlanningModel(
            identity=_Identity(),
            http_client=http,
            config=_candidate_config(),
            owner_loop=asyncio.get_running_loop(),
        )
        with pytest.raises(ValueError, match="model unavailable"):
            await model.propose_candidate_selection(
                query=_QUERY, manifest=harness.manifest, build=harness.build, staged=harness.staged
            )
    assert calls == 0


async def test_non_yielding_late_response_cannot_publish_a_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness, calls, offset = await _harness(), 0, 0.0
    loop = asyncio.get_running_loop()
    original_time = loop.time

    async def transport(request: httpx.Request) -> httpx.Response:
        nonlocal calls, offset
        calls += 1
        offset = 2.0
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(_proposal())},
                    }
                ]
            },
        )

    monkeypatch.setattr(loop, "time", lambda: original_time() + offset)
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        model = AzureOpenAISemanticPlanningModel(
            identity=_Identity(), http_client=http, config=_candidate_config(), owner_loop=loop
        )
        with pytest.raises(TimeoutError, match="deadline"):
            await model.propose_candidate_selection(
                query=_QUERY, manifest=harness.manifest, build=harness.build, staged=harness.staged
            )
    assert calls == 1


def test_diagnostic_profile_does_not_replace_the_active_plan_profile() -> None:
    registry = FileSystemPromptRegistry(Path(__file__).parents[6] / "rule-catalog")
    diagnostic = registry.resolve(
        "semantic.query.plan", profile_id="diagnostic.ontology-candidate-selection"
    )
    active = registry.resolve("semantic.query.plan")
    assert diagnostic.profile is not None and active.profile is not None
    assert diagnostic.profile.mode.value == "shadow"
    assert not diagnostic.profile.promotion_evidence
    assert active.profile.mode.value == "active"
    assert active.root.id != diagnostic.root.id


async def test_native_async_diagnostic_rejects_another_event_loop() -> None:
    harness, calls = await _harness(), 0

    async def transport(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("wrong loop reached provider")

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        model = AzureOpenAISemanticPlanningModel(
            identity=_Identity(),
            http_client=http,
            config=_candidate_config(),
            owner_loop=asyncio.get_running_loop(),
        )
        with pytest.raises(ValueError, match="owner loop"):
            await asyncio.to_thread(
                lambda: asyncio.run(
                    model.propose_candidate_selection(
                        query=_QUERY,
                        manifest=harness.manifest,
                        build=harness.build,
                        staged=harness.staged,
                    )
                )
            )
    assert calls == 0
