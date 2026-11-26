"""Direct Azure OpenAI and APIM OpenAI-v1 request target tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.azure.llm.cross_check import (
    AzureOpenAICrossCheckModel,
    AzureOpenAICrossCheckModelConfig,
)
from fdai.delivery.azure.llm.embeddings import (
    AzureOpenAIEmbeddingModel,
    AzureOpenAIEmbeddingModelConfig,
)
from fdai.delivery.azure.llm.gateway_evidence import record_gateway_route_evidence
from fdai.delivery.azure.llm.latency_routed_cross_check import (
    InMemoryModelHealthTransitionSink,
)
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.rule_catalog.schema.model_endpoint import ModelApiStyle, ModelRouteKind
from fdai.shared.providers.workload_identity import IdentityToken


class _Identity:
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(
            token="test-token",
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=5),
            audience=audience,
        )


async def test_apim_openai_v1_embedding_uses_model_body_and_gateway_audience() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

    identity = _Identity()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = AzureOpenAIEmbeddingModel(
            identity=identity,
            http_client=client,
            config=AzureOpenAIEmbeddingModelConfig(
                endpoint="https://models.example.com",
                deployment="embedding-gpu",
                dim=2,
                api_style=ModelApiStyle.OPENAI_V1,
                auth_audience="api://fdai-model-gateway",
            ),
        )
        await model.embed("hello")

    assert requests[0].url.path == "/v1/embeddings"
    assert "api-version" not in requests[0].url.params
    assert json.loads(requests[0].content)["model"] == "embedding-gpu"
    assert identity.audiences == ["api://fdai-model-gateway"]


async def test_apim_openai_v1_cross_check_preserves_structured_output() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"action_type": "remediate.tag-add", "params": {}}
                            )
                        }
                    }
                ]
            },
        )

    identity = _Identity()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = AzureOpenAICrossCheckModel(
            identity=identity,
            http_client=client,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://models.example.com",
                deployment="qwen-instruct",
                system_prompt="test prompt",
                api_style=ModelApiStyle.OPENAI_V1,
                auth_audience="api://fdai-model-gateway",
            ),
        )
        from fdai.core.quality_gate.gate import QualityCandidate

        await model.propose(
            QualityCandidate(
                action_type="remediate.tag-add",
                target_resource_ref="resource:example/one",
                params={},
                cited_rule_ids=("rule.one",),
            )
        )

    body = json.loads(requests[0].content)
    assert requests[0].url.path == "/v1/chat/completions"
    assert body["model"] == "qwen-instruct"
    assert body["response_format"] == {"type": "json_object"}
    assert identity.audiences == ["api://fdai-model-gateway"]


async def test_apim_spillover_evidence_is_persisted_as_selected_transition() -> None:
    sink = InMemoryModelHealthTransitionSink()
    target = ModelRequestTarget(
        endpoint="https://models.example.com",
        deployment="primary-model",
        api_style=ModelApiStyle.OPENAI_V1,
        auth_audience="api://fdai-model-gateway",
        route_kind=ModelRouteKind.APIM_GATEWAY,
        binding_id="t2-primary-prod",
    )
    response = httpx.Response(
        200,
        headers={
            "x-fdai-model-backend": "primary-standard-spillover",
            "x-fdai-capacity-unit": "tpm",
            "x-fdai-spillover": "true",
        },
    )

    await record_gateway_route_evidence(
        response=response,
        target=target,
        model_role="t2.reasoner.primary",
        sink=sink,
    )

    transition = sink.transitions[0]
    assert transition.deployment == "primary-standard-spillover"
    assert transition.status == "selected"
    assert transition.reason == (
        "apim_route:capacity_unit=tpm:spillover=true:binding=t2-primary-prod"
    )


async def test_apim_response_without_route_evidence_fails_closed() -> None:
    target = ModelRequestTarget(
        endpoint="https://models.example.com",
        deployment="primary-model",
        api_style=ModelApiStyle.OPENAI_V1,
        auth_audience="api://fdai-model-gateway",
        route_kind=ModelRouteKind.APIM_GATEWAY,
        binding_id="t2-primary-prod",
    )

    with pytest.raises(RuntimeError, match="route evidence"):
        await record_gateway_route_evidence(
            response=httpx.Response(200),
            target=target,
            model_role="t2.reasoner.primary",
            sink=InMemoryModelHealthTransitionSink(),
        )
