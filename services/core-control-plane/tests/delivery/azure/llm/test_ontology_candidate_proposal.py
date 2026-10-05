"""Single-attempt model proposals over complete frozen diagnostic inputs."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
import yaml
from fdai.core.ontology_platform import build_query_manifest
from fdai.core.prompts import PromptAssembler, estimate_chat_request_tokens
from fdai.core.prompts.registry import FileSystemPromptRegistry
from fdai.delivery.azure.llm import semantic_planning as planning_module
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.delivery.azure.llm.semantic_planning import (
    AzureOpenAISemanticPlanningModel,
    AzureOpenAISemanticPlanningModelConfig,
)
from fdai.delivery.azure.llm.semantic_planning_config import (
    candidate_proposal_binding,
    candidate_proposal_response_format,
    candidate_proposal_schema_digest,
    candidate_proposal_system_content,
    strict_candidate_proposal_schema,
)
from fdai.delivery.catalog_search.generation import build_ontology_semantic_generation
from fdai.delivery.catalog_search.ontology_candidate_proposal import (
    OntologyCandidateProposal,
    candidate_proposal_payload,
)
from fdai.rule_catalog.schema.object_type import load_object_type_from_mapping
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from pydantic import ValidationError

from tests.delivery.azure.llm.test_semantic_planning import (
    _config,
    _Identity,
    _target,
)
from tests.delivery.catalog_search.test_ontology_evaluation_assets import _ASSETS, _ROOT
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


def test_all_v2_calibration_cases_fit_diagnostic_request_budget() -> None:
    corpus = json.loads((_ASSETS / "instance-corpus.v1.json").read_text())
    calibration = json.loads((_ASSETS / "instance-calibration.v2.json").read_text())
    names = tuple(corpus["required_object_types"])
    registry = PackageResourceSchemaRegistry()
    declarations = tuple(
        load_object_type_from_mapping(
            yaml.safe_load(
                (_ROOT / f"rule-catalog/vocabulary/object-types/{name}.yaml").read_text()
            ),
            schema_registry=registry,
        )
        for name in names
    )
    resource_terms = {
        item.id: tuple(item.query_terms)
        for item in load_resource_type_registry_from_mapping(
            yaml.safe_load((_ROOT / "rule-catalog/vocabulary/resource-types.yaml").read_text())
        )
    }
    manifest = build_query_manifest(
        release=build_ontology_release(object_types=declarations),
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest="sha256:" + "a" * 64,
        object_types=declarations,
    )
    build = build_ontology_semantic_generation(
        manifest=manifest,
        embedding_space_id="budget-check",
        embedding_model_version="fixture-v1",
        embedding_dimension=384,
        runtime_objects=tuple(OntologyObjectRecord(**item) for item in corpus["objects"]),
        resource_type_query_terms=resource_terms,
    )
    config = _candidate_config()
    assert config.plan_prompt_manifest is not None
    budget = config.plan_prompt_manifest.request_token_budget
    assert isinstance(budget, int)

    estimates: list[int] = []
    for case in calibration["cases"]:
        payload = candidate_proposal_payload(
            query=case["query"],
            manifest=manifest,
            build=build,
            staged=type(
                "Staged",
                (),
                {"snapshot_digest": "sha256:" + "b" * 64},
            )(),
        )
        messages = [
            {
                "role": "system",
                "content": candidate_proposal_system_content(config.plan_system_prompt),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"untrusted_input": payload},
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            },
        ]
        estimates.append(
            estimate_chat_request_tokens(
                messages=messages,
                response_format=candidate_proposal_response_format(
                    manifest=manifest,
                    query=case["query"],
                    build=build,
                ),
                reserved_output_tokens=config.max_tokens,
            )
        )

    assert len(estimates) == 64
    assert max(estimates) <= budget


def _proposal() -> dict[str, object]:
    return {
        "status": "select",
        "reason": "conditions_proposed",
        "clauses": [{"object_type": "Resource"}],
        "clause_quotes": [_QUERY],
    }


def _provider_proposal() -> dict[str, object]:
    return {
        "status": "select",
        "reason": "conditions_proposed",
        "clauses": [
            {"object_type": "Resource", "predicates": [], "object_ids": None, "quote": _QUERY}
        ],
    }


def test_strict_candidate_schema_matches_pydantic_contract_surface() -> None:
    pydantic_schema = OntologyCandidateProposal.model_json_schema()
    strict_schema = strict_candidate_proposal_schema()

    assert strict_schema["additionalProperties"] is False
    assert set(strict_schema["required"]) == {"status", "reason", "clauses"}
    assert (
        strict_schema["properties"]["status"]["enum"]
        == pydantic_schema["properties"]["status"]["enum"]
    )
    assert (
        strict_schema["properties"]["reason"]["enum"]
        == pydantic_schema["properties"]["reason"]["enum"]
    )
    clause_schema = strict_schema["properties"]["clauses"]["items"]
    assert clause_schema["additionalProperties"] is False
    assert set(clause_schema["required"]) == {"object_type", "predicates", "object_ids", "quote"}
    assert clause_schema["properties"]["quote"]["type"] == "string"
    predicate_variants = clause_schema["properties"]["predicates"]["items"]["anyOf"]
    strict_operators = {
        value
        for variant in predicate_variants
        for value in variant["properties"]["operator"]["enum"]
    }
    assert strict_operators == set(pydantic_schema["$defs"]["ObjectPredicateOperator"]["enum"])

    for example in (
        {
            "status": "select",
            "reason": "conditions_proposed",
            "clauses": [{"object_type": "Resource", "predicates": [], "object_ids": None}],
            "clause_quotes": ["Resource"],
        },
        {
            "status": "select",
            "reason": "conditions_proposed",
            "clauses": [
                {
                    "object_type": "Resource",
                    "predicates": [
                        {"property": "id", "operator": "contains", "equals": "resource-0"}
                    ],
                    "object_ids": None,
                }
            ],
            "clause_quotes": ["resource-0"],
        },
        {
            "status": "select",
            "reason": "conditions_proposed",
            "clauses": [
                {
                    "object_type": "Resource",
                    "predicates": [{"property": "id", "operator": "in", "values": ["resource-0"]}],
                    "object_ids": ["resource-0"],
                }
            ],
            "clause_quotes": ["resource-0"],
        },
        {
            "status": "clarify",
            "reason": "unresolved_reference",
            "clauses": [],
            "clause_quotes": [],
        },
    ):
        OntologyCandidateProposal.model_validate(example)


def test_candidate_quote_schema_is_constant_and_uses_exact_validator_backstop() -> None:
    schema = strict_candidate_proposal_schema(query="Find alpha beta now.")
    clause = schema["properties"]["clauses"]["items"]
    assert clause["properties"]["quote"] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 16384,
    }
    assert strict_candidate_proposal_schema(query="different query") == schema


async def test_actual_adapter_proposal_reaches_secured_membership_without_embedding() -> None:
    harness = await _harness(typed_selection_available=True)
    requests: list[httpx.Request] = []

    async def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(_provider_proposal())},
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
        proposed = await model.propose_candidate_selection(
            query=_QUERY, manifest=harness.manifest, build=harness.build, staged=harness.staged
        )
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer test-token"
    body = json.loads(requests[0].content)
    assert requests[0].url.params["api-version"] == "2024-10-21"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == ("ontology_candidate_proposal")
    assert body["response_format"]["json_schema"]["strict"] is True
    schema = body["response_format"]["json_schema"]["schema"]
    quote_schema = schema["properties"]["clauses"]["items"]["anyOf"][0]["properties"]["quote"]
    assert quote_schema == {"type": "string", "minLength": 1, "maxLength": 16384}
    resource_clause = next(
        item
        for item in schema["properties"]["clauses"]["items"]["anyOf"]
        if item["properties"]["object_type"]["enum"] == ["Resource"]
    )
    resource_properties = {
        value
        for variant in resource_clause["properties"]["predicates"]["items"]["anyOf"]
        for value in variant["properties"]["property"]["enum"]
    }
    assert "id" in resource_properties
    assert "properties.purpose" not in resource_properties
    transmitted = json.loads(body["messages"][1]["content"])["untrusted_input"]
    resource_catalog = next(
        item
        for item in transmitted["allowed_predicate_properties"]
        if item["object_type"] == "Resource"
    )
    assert tuple(resource_catalog["properties"]) == tuple(sorted(resource_properties))
    assert len(transmitted["documents"]) == len(harness.build.documents)
    assert proposed.input_digest == transmitted["input_digest"]
    assert candidate_proposal_schema_digest(manifest=harness.manifest, query=_QUERY) == (
        candidate_proposal_schema_digest(manifest=harness.manifest, query=_QUERY + " extra")
    )
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


async def test_candidate_proposal_uses_model_family_token_fields_for_alias_deployment() -> None:
    harness = await _harness(typed_selection_available=True)
    requests: list[httpx.Request] = []
    config = replace(
        _candidate_config(),
        reasoning_effort="low",
        candidates=(
            ModelRequestTarget(
                endpoint="https://example.openai.azure.com",
                deployment="t1.judge",
                api_version="2024-06-01",
                model_family="gpt-5.4-mini",
            ),
        ),
    )

    async def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(_provider_proposal())},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        model = AzureOpenAISemanticPlanningModel(
            identity=_Identity(),
            http_client=http,
            config=config,
            owner_loop=asyncio.get_running_loop(),
        )
        await model.propose_candidate_selection(
            query=_QUERY, manifest=harness.manifest, build=harness.build, staged=harness.staged
        )

    body = json.loads(requests[0].content)
    assert requests[0].url.params["api-version"] == "2024-10-21"
    assert body["response_format"]["type"] == "json_schema"
    assert body["max_completion_tokens"] == 2048
    assert body["reasoning_effort"] == "low"
    assert "max_tokens" not in body
    assert "temperature" not in body


async def test_candidate_proposal_omits_reasoning_effort_for_legacy_targets() -> None:
    harness = await _harness(typed_selection_available=True)
    requests: list[httpx.Request] = []
    config = replace(_candidate_config(), reasoning_effort="low", candidates=(_target("legacy"),))

    async def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(_provider_proposal())},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        model = AzureOpenAISemanticPlanningModel(
            identity=_Identity(),
            http_client=http,
            config=config,
            owner_loop=asyncio.get_running_loop(),
        )
        await model.propose_candidate_selection(
            query=_QUERY, manifest=harness.manifest, build=harness.build, staged=harness.staged
        )

    body = json.loads(requests[0].content)
    assert "reasoning_effort" not in body


def test_candidate_proposal_digest_binds_reasoning_effort() -> None:
    config = replace(
        _candidate_config(),
        candidates=(
            ModelRequestTarget(
                endpoint="https://example.openai.azure.com",
                deployment="t1.judge",
                api_version="2024-06-01",
                model_family="gpt-5.4-mini",
            ),
        ),
    )
    low = replace(config, reasoning_effort="low")
    minimal = replace(config, reasoning_effort="minimal")

    assert candidate_proposal_binding(low).request_parameters_digest != (
        candidate_proposal_binding(minimal).request_parameters_digest
    )


async def test_candidate_proposal_accepts_exact_quote_with_contains_predicates() -> None:
    query = "Which business service handles invoice payments?"
    harness = await _harness(typed_selection_available=True)
    proposal = {
        "status": "select",
        "reason": "conditions_proposed",
        "clauses": [
            {
                "object_type": "Resource",
                "predicates": [
                    {
                        "property": "id",
                        "operator": "contains",
                        "equals": "resource-0",
                    }
                ],
                "object_ids": None,
                "quote": query,
            }
        ],
    }

    async def transport(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(proposal)}}]
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
            query=query, manifest=harness.manifest, build=harness.build, staged=harness.staged
        )

    assert proposed.selection is not None
    result = await harness.reader.search(
        query,
        staged=harness.staged,
        manifest=harness.manifest,
        gateway=harness.gateway,
        as_of=harness.clock.now,
        selection=proposed.selection,
    )
    assert result.authorized is not None
    assert tuple(item.id for item in result.authorized.objects) == ("resource-0",)


async def test_candidate_proposal_canonicalizes_duplicate_object_ids() -> None:
    harness = await _harness(typed_selection_available=True)
    proposal = {
        "status": "select",
        "reason": "conditions_proposed",
        "clauses": [
            {
                "object_type": "Resource",
                "predicates": [],
                "object_ids": ["resource-0", "resource-0", "resource-1"],
                "quote": _QUERY,
            }
        ],
    }

    async def transport(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(proposal)}}]
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

    assert proposed.proposal.clauses[0].object_ids == ("resource-0", "resource-1")


async def test_candidate_proposal_drops_invalid_quote_clauses_but_keeps_valid_ones() -> None:
    harness = await _harness(typed_selection_available=True)
    proposal = {
        "status": "select",
        "reason": "conditions_proposed",
        "clauses": [
            {
                "object_type": "Resource",
                "predicates": [],
                "object_ids": ["resource-0"],
                "quote": _QUERY,
            },
            {
                "object_type": "Resource",
                "predicates": [],
                "object_ids": ["resource-1"],
                "quote": "not present in query",
            },
        ],
    }

    async def transport(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(proposal)}}]
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

    assert proposed.quote_invalid_clauses == 1
    assert proposed.proposal.status == "select"
    assert proposed.proposal.clauses[0].object_ids == ("resource-0",)


@pytest.mark.parametrize("quote", ["not present in query", "Resource"])
async def test_candidate_proposal_all_invalid_quotes_become_abstention(quote: str) -> None:
    harness = await _harness(typed_selection_available=True)
    proposal = {
        "status": "select",
        "reason": "conditions_proposed",
        "clauses": [
            {
                "object_type": "Resource",
                "predicates": [],
                "object_ids": ["resource-0"],
                "quote": quote,
            }
        ],
    }

    async def transport(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(proposal)}}]
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
            query="Resource and Resource",
            manifest=harness.manifest,
            build=harness.build,
            staged=harness.staged,
        )

    assert proposed.quote_invalid_clauses == 1
    assert proposed.proposal.status == "clarify"
    assert proposed.selection is None


@pytest.mark.parametrize("failure", ["429", "503", "404", "timeout", "malformed", "length"])
async def test_provider_or_proposal_failure_never_retries_or_becomes_no_match(failure: str) -> None:
    harness, calls = await _harness(), 0

    async def transport(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure in {"429", "503", "404"}:
            return httpx.Response(int(failure))
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        proposal = _proposal()
        proposal = _provider_proposal()
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
                        "message": {"content": json.dumps(_provider_proposal())},
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
