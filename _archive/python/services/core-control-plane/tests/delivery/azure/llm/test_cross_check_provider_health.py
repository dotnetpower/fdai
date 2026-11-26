"""Actual cross-check invocations produce scoped API evidence without extra calls."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fdai.core.prompts import ComposedPrompt, LayerRef, PromptLayer
from fdai.core.prompts.types import PromptMode
from fdai.core.quality_gate.gate import QualityCandidate
from fdai.delivery.azure.llm import cross_check as module
from fdai.delivery.azure.llm.cross_check import (
    AzureOpenAICrossCheckModel,
    AzureOpenAICrossCheckModelConfig,
)
from fdai.delivery.azure.llm.latency_routed_cross_check import LatencyRoutedCrossCheckModel
from fdai.delivery.azure.llm.provider_observations import ProviderInvocationObservations
from fdai.shared.providers.local.identity import LocalWorkloadIdentity
from fdai.shared.providers.self_health import SelfHealthExporterUnavailableError
from fdai_service_contracts.model_provider_health import (
    ModelProviderHealth,
    ModelProviderObservationV1,
)

NOW = datetime(2026, 10, 19, tzinfo=UTC)
CONFIG = AzureOpenAICrossCheckModelConfig(
    endpoint="https://example.openai.azure.com",
    deployment="example-reasoner",
    system_prompt="Synthetic cross-check test.",
)
CANDIDATE = QualityCandidate(
    action_type="remediate.tag-add",
    target_resource_ref="resource:example",
    params={"tag_name": "owner"},
    cited_rule_ids=("example.rule",),
)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    clock = SimpleNamespace(now=NOW)
    factory = ProviderInvocationObservations
    monkeypatch.setattr(
        module,
        "ProviderInvocationObservations",
        lambda **kw: factory(clock=lambda: clock.now, **kw),
    )
    return clock


def _body(content=None):
    return {
        "choices": [
            {
                "message": {
                    "content": content
                    if content is not None
                    else json.dumps({"action_type": "remediate.tag-add", "params": {"safe": True}})
                }
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
    }


def _model(client, *, role="t2.reasoner.primary", config=CONFIG, **kwargs):
    return AzureOpenAICrossCheckModel(
        identity=kwargs.pop("identity", LocalWorkloadIdentity()),
        http_client=client,
        config=config,
        observation_role=role,
        **kwargs,
    )


def _source(model):
    return model.model_provider_observations(maximum_age_seconds=120)


async def _unavailable(source, reason, *, now=NOW):
    with pytest.raises(SelfHealthExporterUnavailableError) as caught:
        await source.observe(now=now)
    assert caught.value.reason == reason


async def test_binding_is_explicit_and_unobserved_source_never_probes():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: pytest.fail("observation must not call provider"))
    ) as client:
        model = _model(client)
        await _unavailable(_source(model), "source_missing")
        with pytest.raises(SelfHealthExporterUnavailableError) as caught:
            _source(_model(client, role=None))
        assert caught.value.reason == "source_missing"
        with pytest.raises(ValueError):
            _model(client, role="not a role")


async def test_normal_call_is_observed_without_composer_or_recollection_refresh(clock):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=_body())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = _model(client)
        assert await model.propose(CANDIDATE) == ("remediate.tag-add", {"safe": True})
        source = _source(model)
        sample = await source.observe(now=NOW)
        assert sample.value == Decimal(1)
        assert sample.role == "t2.reasoner.primary"
        assert sample.observed_at == NOW
        assert "example" not in repr(sample)
        clock.now += timedelta(seconds=119)
        assert await source.observe(now=NOW + timedelta(seconds=120)) == sample
        await _unavailable(source, "source_stale", now=NOW + timedelta(seconds=121))
        await _unavailable(source, "source_from_future", now=NOW - timedelta(seconds=1))
        assert len(calls) == 1
        replica = _model(client)
        replacement = _model(client, config=replace(CONFIG, deployment="replacement"))
        await _unavailable(_source(replica), "source_missing")
        await _unavailable(_source(replacement), "source_missing")
        assert _source(replica).exporter_id != source.exporter_id
        assert _source(replacement).binding_digest != source.binding_digest
    await _unavailable(source, "source_unreachable")


@pytest.mark.parametrize("failure", [401, 429, 503, "timeout"])
async def test_http_failure_is_known_without_retry(failure):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return httpx.Response(failure, json={"error": "synthetic provider detail"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = _model(client)
        with pytest.raises(httpx.HTTPError):
            await model.propose(CANDIDATE)
        assert (await _source(model).observe(now=NOW)).value == Decimal(0)
        assert len(calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        None,
        {"choices": []},
        {"choices": [{"message": []}]},
        _body("not json"),
        _body("[]"),
        _body("{}"),
        _body('{"action_type":"example","params":[]}'),
        _body('{"action_type":"example","params":{"value":NaN}}'),
        _body('{"action_type":"example","params":{"nested":[Infinity]}}'),
    ],
)
async def test_malformed_provider_envelope_and_final_json_are_known_failures(payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=json.dumps(payload).encode())
        )
    ) as client:
        model = _model(client)
        with pytest.raises(RuntimeError):
            await model.propose(CANDIDATE)
        assert (await _source(model).observe(now=NOW)).value == Decimal(0)


async def test_non_json_http_body_is_failed_and_original_exception_survives():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"not json"))
    ) as client:
        model = _model(client)
        with pytest.raises(ValueError):
            await model.propose(CANDIDATE)
        assert (await _source(model).observe(now=NOW)).value == Decimal(0)


@pytest.mark.parametrize("status", [200, 503])
async def test_cancellation_during_final_bookkeeping_keeps_whole_invocation_unknown(status):
    entered = asyncio.Event()

    class Metering:
        async def emit_safe(self, usage):
            entered.set()
            await asyncio.Event().wait()

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, json=_body()))
    ) as client:
        model = _model(client, metering=Metering())
        task = asyncio.create_task(model.propose(CANDIDATE))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await _unavailable(_source(model), "source_incomplete")


async def test_identity_failure_invalidates_previous_success_without_provider_call():
    class Identity(LocalWorkloadIdentity):
        fail = False

        async def get_token(self, audience):
            if self.fail:
                raise RuntimeError("identity unavailable")
            return await super().get_token(audience)

    identity = Identity()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=_body())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = _model(client, identity=identity)
        await model.propose(CANDIDATE)
        identity.fail = True
        with pytest.raises(RuntimeError, match="identity unavailable"):
            await model.propose(CANDIDATE)
        await _unavailable(_source(model), "source_incomplete")
        assert len(calls) == 1


@pytest.mark.parametrize("stage", ["prompt", "budget", "gateway", "metering", "tool"])
async def test_local_pipeline_failure_is_unknown_not_provider_failure(monkeypatch, stage):
    class Composer:
        async def compose(self, **kwargs):
            if stage == "prompt":
                raise RuntimeError("synthetic prompt failure")
            return ComposedPrompt(
                system_text="bounded",
                layer_manifest=(LayerRef("base", 1, PromptLayer.BASE, 7),),
                token_estimate=7,
                profile_id="active.test",
                profile_version=1,
                profile_digest="sha256:" + "a" * 64,
                system_token_budget=128,
                request_token_budget=513,
                reserved_output_tokens=512,
            )

    class Metering:
        async def emit_safe(self, usage):
            raise RuntimeError("synthetic local metering failure")

    class Registry:
        def artifacts(self):
            return (
                SimpleNamespace(
                    id="example.read",
                    default_mode=PromptMode.ENFORCE,
                    description="Synthetic read",
                    input_schema={"type": "object"},
                ),
            )

    class Executor:
        async def dispatch(self, **kwargs):
            raise RuntimeError("synthetic local tool failure")

    async def gateway(**kwargs):
        raise RuntimeError("synthetic local gateway observation failure")

    calls = []
    payload = _body()
    if stage == "tool":
        payload["choices"][0]["message"] = {
            "tool_calls": [{"id": "call", "function": {"name": "example_read", "arguments": "{}"}}]
        }

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload)

    kwargs = {}
    if stage in {"prompt", "budget"}:
        kwargs.update(prompt_composer=Composer(), capability_id="t2.reasoner.primary")
    elif stage == "metering":
        kwargs["metering"] = Metering()
    elif stage == "tool":
        kwargs.update(tool_registry=Registry(), tool_executor=Executor())
    else:
        monkeypatch.setattr(module, "record_gateway_route_evidence", gateway)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = _model(client, **kwargs)
        expected = {
            "prompt": "synthetic prompt failure",
            "budget": "profile budget",
            "gateway": "synthetic local gateway",
            "metering": "synthetic local metering",
            "tool": "synthetic local tool",
        }
        with pytest.raises(RuntimeError, match=expected[stage]):
            await model.propose(CANDIDATE)
        await _unavailable(_source(model), "source_incomplete")
        assert len(calls) == int(stage not in {"prompt", "budget"})


@pytest.mark.parametrize("cancel", [False, True])
async def test_overlapping_invocations_require_complete_settlement(cancel):
    entered = [asyncio.Event(), asyncio.Event()]
    release = [asyncio.Event(), asyncio.Event()]
    calls = 0

    async def handler(request):
        nonlocal calls
        index = calls
        calls += 1
        entered[index].set()
        await release[index].wait()
        return httpx.Response(503 if index == 0 else 200, json=_body())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = _model(client)
        first = asyncio.create_task(model.propose(CANDIDATE))
        second = asyncio.create_task(model.propose(CANDIDATE))
        await asyncio.gather(*(event.wait() for event in entered))
        await _unavailable(_source(model), "source_incomplete")
        if cancel:
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        else:
            release[0].set()
            with pytest.raises(httpx.HTTPStatusError):
                await first
        await _unavailable(_source(model), "source_incomplete")
        release[1].set()
        await second
        if cancel:
            await _unavailable(_source(model), "source_incomplete")
        else:
            assert (await _source(model).observe(now=NOW)).value == Decimal(0)
        assert calls == 2


async def test_pool_requires_every_member_and_keeps_oldest_original_observation(clock):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=_body())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = _model(client)
        second = _model(client, config=replace(CONFIG, deployment="second"))
        pool = LatencyRoutedCrossCheckModel(candidates=[("first", first), ("second", second)])
        source = _source(pool)
        await _unavailable(source, "source_missing")
        await pool.propose(CANDIDATE)
        await _unavailable(source, "source_missing")
        clock.now += timedelta(seconds=60)
        await pool.propose(CANDIDATE)
        sample = await source.observe(now=clock.now)
        assert sample.health is ModelProviderHealth.HEALTHY
        assert sample.observed_at == NOW
        assert sample.binding_digest not in {
            _source(first).binding_digest,
            _source(second).binding_digest,
        }
        await _unavailable(source, "source_stale", now=NOW + timedelta(seconds=121))
        assert len(calls) == 2
        reversed_pool = LatencyRoutedCrossCheckModel(
            candidates=[("second", second), ("first", first)]
        )
        assert _source(reversed_pool).binding_digest != source.binding_digest


async def test_known_failed_sibling_cannot_be_hidden_by_selected_healthy_member():
    fail_second = False
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            503 if fail_second and "/second/" in request.url.path else 200, json=_body()
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = _model(client)
        second = _model(client, config=replace(CONFIG, deployment="second"))
        pool = LatencyRoutedCrossCheckModel(candidates=[("first", first), ("second", second)])
        await first.propose(CANDIDATE)
        await second.propose(CANDIDATE)
        fail_second = True
        with pytest.raises(httpx.HTTPStatusError):
            await second.propose(CANDIDATE)
        assert (await _source(pool).observe(now=NOW)).health is ModelProviderHealth.UNHEALTHY
        assert (await _source(first).observe(now=NOW)).health is ModelProviderHealth.HEALTHY
        assert len(calls) == 3


@pytest.mark.parametrize("kind", ["missing", "unbound", "wrong-role"])
async def test_pool_cannot_skip_unsupported_or_wrong_role_members(kind):
    async with httpx.AsyncClient() as client:
        first = _model(client)
        other = (
            SimpleNamespace(propose=first.propose)
            if kind == "missing"
            else _model(client, role=None if kind == "unbound" else "t2.reasoner.secondary")
        )
        pool = LatencyRoutedCrossCheckModel(candidates=[("first", first), ("other", other)])
        with pytest.raises(SelfHealthExporterUnavailableError) as caught:
            _source(pool)
        assert (
            caught.value.reason
            == {
                "missing": "source_incomplete",
                "unbound": "source_missing",
                "wrong-role": "source_malformed",
            }[kind]
        )


@pytest.mark.parametrize("kind", ["future", "member-expired", "binding", "role", "unknown"])
async def test_pool_checks_each_external_member_before_compressing_timestamps(kind):
    class ExternalSource:
        role = "t2.reasoner.primary"
        binding_digest = "sha256:" + "a" * 64

        async def observe(self, *, now):
            return ModelProviderObservationV1(
                role="t2.reasoner.secondary" if kind == "role" else self.role,
                binding_digest="sha256:" + "b" * 64 if kind == "binding" else self.binding_digest,
                source="synthetic:external",
                health=ModelProviderHealth.UNKNOWN
                if kind == "unknown"
                else ModelProviderHealth.HEALTHY,
                value=None if kind == "unknown" else Decimal(1),
                observed_at=now
                + timedelta(
                    seconds=1 if kind == "future" else -2 if kind == "member-expired" else 0
                ),
                fresh=kind != "unknown",
                maximum_age_seconds=1 if kind == "member-expired" else 120,
                reason="synthetic",
            )

    class External:
        def model_provider_observations(self, *, maximum_age_seconds):
            return ExternalSource()

        async def propose(self, candidate):
            raise AssertionError("health must never probe")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=_body()))
    ) as client:
        first = _model(client)
        await first.propose(CANDIDATE)
        pool = LatencyRoutedCrossCheckModel(candidates=[("first", first), ("external", External())])
        await _unavailable(
            _source(pool),
            {
                "future": "source_from_future",
                "member-expired": "source_stale",
                "binding": "source_malformed",
                "role": "source_malformed",
                "unknown": "source_incomplete",
            }[kind],
        )
