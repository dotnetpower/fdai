"""Adapter -> MeteringEmitter integration: cross-check + RCA emit usage.

Verifies the two T2 adapters parse the response ``usage`` and record one
:class:`~fdai.core.metering.records.LlmInvocation` per call, attributed
to the active correlation id, with cost from the injected pricing table.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from fdai.core.metering.emitter import MeteringEmitter
from fdai.core.metering.pricing import PricingTable
from fdai.core.metering.records import InvocationMode
from fdai.core.metering.sink import InMemoryMeteringSink
from fdai.core.metering.usage import TokenUsage
from fdai.core.quality_gate.gate import QualityCandidate
from fdai.core.rca import Citation, CitationKind
from fdai.delivery.azure.llm.cross_check import (
    AzureOpenAICrossCheckModel,
    AzureOpenAICrossCheckModelConfig,
)
from fdai.delivery.azure.llm.rca_model import AzureOpenAIRcaModel, AzureOpenAIRcaModelConfig
from fdai.shared.providers.workload_identity import IdentityToken, WorkloadIdentity
from fdai.shared.telemetry.correlation import with_correlation

_PRICING = PricingTable.from_mapping({"gpt-4o": {"input_per_1k": "2.50", "output_per_1k": "10.00"}})


class _StaticIdentity(WorkloadIdentity):
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token",  # noqa: S106 - fake in-memory token, not a secret
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
            audience=audience,
        )


def _emitter(sink: InMemoryMeteringSink) -> MeteringEmitter:
    return MeteringEmitter(
        sink=sink,
        capability_id="t2.reasoner.primary",
        model_key="gpt-4o",
        tier="T2",
        pricing=_PRICING,
        mode=InvocationMode.ENFORCE,
    )


def _candidate() -> QualityCandidate:
    return QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="resource:example/rg/x",
        params={"tag_name": "owner"},
        cited_rule_ids=("object-storage.owner-tag.required",),
    )


async def test_cross_check_records_usage_and_cost() -> None:
    sink = InMemoryMeteringSink()

    async def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {"action_type": "remediate.tag-add", "params": {"foo": "bar"}}
                            ),
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt="unit-test system prompt",
            ),
            metering=_emitter(sink),
        )
        with with_correlation("evt-cc"):
            await adapter.propose(_candidate())

    (record,) = await sink.invocations()
    assert record.correlation_id == "evt-cc"
    assert record.usage.total_tokens == 1500
    assert record.cost == Decimal("7.50")


async def test_rca_records_usage_and_cost() -> None:
    sink = InMemoryMeteringSink()

    async def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "cause": "runaway writer",
                                    "confidence": 0.9,
                                    "citations": ["object-storage.owner-tag.required"],
                                }
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 400, "completion_tokens": 100},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        adapter = AzureOpenAIRcaModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAIRcaModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt="unit-test system prompt",
            ),
            metering=_emitter(sink),
        )
        with with_correlation("evt-rca"):
            await adapter.propose_cause(
                incident_summary="disk near full",
                candidate_citations=(
                    Citation(kind=CitationKind.RULE, ref="object-storage.owner-tag.required"),
                ),
            )

    (record,) = await sink.invocations()
    assert record.correlation_id == "evt-rca"
    assert record.usage == TokenUsage(prompt_tokens=400, completion_tokens=100)
    # 400/1000*2.50 + 100/1000*10.00 = 1.00 + 1.00 = 2.00
    assert record.cost == Decimal("2.00")


async def test_no_metering_wired_is_a_noop() -> None:
    async def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps({"action_type": "n", "params": {}})}}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt="unit-test system prompt",
            ),
        )
        action_type, _ = await adapter.propose(_candidate())
    assert action_type == "n"


async def test_cross_check_records_usage_even_when_final_answer_is_malformed() -> None:
    # H7: tokens are recorded on the failure path too (malformed answer
    # routes to HIL), so spend is not under-reported.
    import pytest

    sink = InMemoryMeteringSink()

    async def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                # Missing "action_type" -> _parse_final_answer raises.
                "choices": [{"message": {"content": json.dumps({"params": {}})}}],
                "usage": {"prompt_tokens": 900, "completion_tokens": 100},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt="unit-test system prompt",
            ),
            metering=_emitter(sink),
        )
        with with_correlation("evt-fail"), pytest.raises(RuntimeError):
            await adapter.propose(_candidate())

    (record,) = await sink.invocations()
    assert record.correlation_id == "evt-fail"
    assert record.usage.total_tokens == 1000


async def test_embeddings_records_usage() -> None:
    # H5: T1 embedding spend is metered like the T2 reasoners.
    from fdai.delivery.azure.llm.embeddings import (
        AzureOpenAIEmbeddingModel,
        AzureOpenAIEmbeddingModelConfig,
    )

    sink = InMemoryMeteringSink()

    async def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [{"embedding": [0.1] * 8, "index": 0}],
                "usage": {"prompt_tokens": 42, "total_tokens": 42},
            },
        )

    emitter = MeteringEmitter(
        sink=sink,
        capability_id="t1.embedding",
        model_key="text-embedding-3-small",
        tier="T1",
        pricing=PricingTable.from_mapping(
            {"text-embedding-3-small": {"input_per_1k": "0.02", "output_per_1k": "0"}}
        ),
        mode=InvocationMode.ENFORCE,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        adapter = AzureOpenAIEmbeddingModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAIEmbeddingModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t1-embedding",
                dim=8,
            ),
            metering=emitter,
        )
        with with_correlation("evt-embed"):
            await adapter.embed("hello")

    (record,) = await sink.invocations()
    assert record.tier == "T1"
    assert record.usage == TokenUsage(prompt_tokens=42, completion_tokens=0)
    # 42/1000 * 0.02 = 0.00084
    assert record.cost == Decimal("0.00084")
