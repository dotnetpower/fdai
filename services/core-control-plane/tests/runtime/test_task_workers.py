from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fdai.core.metering.pricing import PricingTable
from fdai.core.task_worker.store import InMemoryTaskWorkerStore
from fdai.rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    ResolvedCapability,
    ResolvedModels,
)
from fdai.runtime import bootstrap_core, task_workers
from fdai.runtime.bootstrap_resources import RuntimeResources


def binding_arguments(dsn: str = "host=127.0.0.1 dbname=synthetic user=fdai_core") -> dict:
    return {
        "environment": {
            "FDAI_TASK_WORKERS_ENABLED": "1",
            "FDAI_STATE_STORE_DSN": dsn,
            "FDAI_LLM_ENDPOINT": "https://example.openai.azure.com",
            "FDAI_TASK_WORKER_READ_SCOPE_JSON": json.dumps(
                {"scope_ref": "scope:example", "resource_refs": ["resource:one"]}
            ),
        },
        "resolved_models": ResolvedModels(
            schema_version="1.0.0",
            region="example-region",
            subscription_id="00000000-0000-0000-0000-000000000000",
            deployer_object_id="00000000-0000-0000-0000-000000000000",
            mixed_model_mode="normal",
            capabilities=(
                ResolvedCapability(
                    name="t1.judge",
                    status=CapabilityStatus.RESOLVED,
                    publisher="OpenAI",
                    family="gpt-4.1-mini",
                    sku="GlobalStandard",
                    capacity_tpm=1000,
                    invocation="always",
                ),
            ),
        ),
        "held_capabilities": frozenset(),
        "identity": SimpleNamespace(
            get_token=AsyncMock(side_effect=AssertionError("no model probe"))
        ),
        "http_client": None,
        "pricing": PricingTable.from_mapping(
            {
                "gpt-4.1-mini": {
                    "input_per_1k": Decimal("0.001"),
                    "output_per_1k": Decimal("0.002"),
                },
            }
        ),
    }


class _Store(InMemoryTaskWorkerStore):
    instances: list = []
    fail: str | None = None

    def __init__(self, **kwargs):
        super().__init__()
        self.config = kwargs["config"]
        self.calls = []
        self.instances.append(self)

    async def open(self):
        self.calls.append("open")
        if self.fail == "open":
            raise RuntimeError("synthetic database unavailable")

    async def verify_inventory_source(self):
        self.calls.append("source")
        if self.fail == "source":
            raise RuntimeError("synthetic inventory schema unavailable")

    async def list_interrupted(self, *, limit=100):
        self.calls.append("recover")
        if self.fail == "recover":
            raise RuntimeError("synthetic recovery failure")
        return await super().list_interrupted(limit=limit)

    async def aclose(self):
        self.calls.append("close")


@pytest.mark.parametrize("enabled", ["", "0", "false", "off"])
async def test_disabled_workers_do_not_load_dependencies(enabled: str) -> None:
    result = await task_workers.build_task_worker_runtime_from_env(
        environment={"FDAI_TASK_WORKERS_ENABLED": enabled},
        resolved_models=None,
        held_capabilities=frozenset(),
        identity=None,
        http_client=None,
        pricing=None,
    )
    assert result is None


@pytest.mark.parametrize(
    "missing",
    [
        "FDAI_STATE_STORE_DSN",
        "FDAI_TASK_WORKER_READ_SCOPE_JSON",
        "resolved_models",
        "identity",
        "http_client",
        "pricing",
    ],
)
async def test_enabled_workers_fail_on_missing_required_dependencies(missing: str) -> None:
    args = binding_arguments()
    async with httpx.AsyncClient() as client:
        args["http_client"] = client
        if missing.startswith("FDAI_"):
            args["environment"].pop(missing)
        else:
            args[missing] = None
        with pytest.raises(RuntimeError, match="require"):
            await task_workers.build_task_worker_runtime_from_env(**args)


@pytest.mark.parametrize("held", ["t1.judge", "t1.narrator"])
async def test_model_holds_cannot_be_bypassed(held: str) -> None:
    args = binding_arguments()
    args["held_capabilities"] = frozenset({held})
    async with httpx.AsyncClient() as client:
        args["http_client"] = client
        with pytest.raises(RuntimeError, match="held|eligible"):
            await task_workers.build_task_worker_runtime_from_env(**args)
    args["identity"].get_token.assert_not_awaited()


@pytest.mark.parametrize("failure", [None, "open", "source", "recover"])
async def test_production_construction_recovers_before_exposure_and_cleans_failed_startup(
    monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    monkeypatch.setattr(task_workers, "PostgresTaskWorkerRuntimeStore", _Store)
    monkeypatch.setattr(_Store, "fail", failure)
    args = binding_arguments()
    transport = httpx.MockTransport(lambda request: pytest.fail("no HTTP at startup"))
    async with httpx.AsyncClient(transport=transport) as client:
        args["http_client"] = client
        if failure:
            with pytest.raises(RuntimeError, match="synthetic"):
                await task_workers.build_task_worker_runtime_from_env(**args)
            assert _Store.instances[-1].calls[-1] == "close"
        else:
            binding = await task_workers.build_task_worker_runtime_from_env(**args)
            assert binding is not None
            assert binding.store.calls == ["open", "source", "recover"]
            assert {tool.name for tool in binding.runtime._tools} == {
                "resolve_resource",
                "get_resource_state",
                "query_resource_activity",
                "query_resource_health",
                "query_guest_shutdown_events",
                "query_network_security",
                "query_network_peerings",
            }
            assert binding.runtime._executor._require_prepared is True
            await binding.aclose()
            assert binding.store.calls[-1] == "close"
    args["identity"].get_token.assert_not_awaited()


async def test_actual_core_assembly_calls_the_production_worker_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReachedWorkerBoundaryError(RuntimeError):
        pass

    build = AsyncMock(side_effect=ReachedWorkerBoundaryError)
    monkeypatch.setattr(task_workers, "build_task_worker_runtime_from_env", build)
    monkeypatch.setattr(
        bootstrap_core,
        "build_messaging_runtime",
        lambda **kwargs: SimpleNamespace(diagnostic_bus=None),
    )
    args = binding_arguments()
    container = SimpleNamespace(
        config=SimpleNamespace(kafka=object()),
        resolved_models=args["resolved_models"],
        held_model_capabilities=frozenset(),
        llm_bindings=SimpleNamespace(conversation_pricing=args["pricing"]),
    )
    plan = SimpleNamespace(requires_channel_http_client=False, github_change_feed_enabled=False)
    async with httpx.AsyncClient() as client:
        resources = RuntimeResources(http_client=client)
        with pytest.raises(ReachedWorkerBoundaryError):
            await bootstrap_core.build_core_runtime(
                container=container,
                plan=plan,
                resources=resources,
                identity=args["identity"],
                environment=args["environment"],
                license_authority=object(),
                state_store=InMemoryTaskWorkerStore(),
            )
        build.assert_awaited_once_with(
            environment=args["environment"],
            resolved_models=args["resolved_models"],
            held_capabilities=frozenset(),
            identity=args["identity"],
            http_client=client,
            pricing=args["pricing"],
        )


async def test_binding_releases_its_store_and_reports_a_failed_drain() -> None:
    runtime = SimpleNamespace(aclose=AsyncMock(side_effect=RuntimeError("synthetic drain failure")))
    store = SimpleNamespace(aclose=AsyncMock())
    binding = task_workers.TaskWorkerRuntimeBinding(runtime=runtime, store=store)
    with pytest.raises(RuntimeError, match="drain failure"):
        await binding.aclose()
    runtime.aclose.assert_awaited_once_with()
    store.aclose.assert_awaited_once_with()


async def test_core_binding_attaches_the_exact_factory_result_to_cleanup_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = object()
    build = AsyncMock(return_value=binding)
    monkeypatch.setattr(task_workers, "build_task_worker_runtime_from_env", build)
    args = binding_arguments()
    container = SimpleNamespace(
        resolved_models=args["resolved_models"],
        held_model_capabilities=frozenset(),
        llm_bindings=SimpleNamespace(conversation_pricing=args["pricing"]),
    )
    async with httpx.AsyncClient() as client:
        resources = RuntimeResources(http_client=client)
        await task_workers.bind_task_workers(
            container, resources, args["identity"], args["environment"]
        )
        assert resources.task_workers is binding
        build.assert_awaited_once_with(
            environment=args["environment"],
            resolved_models=args["resolved_models"],
            held_capabilities=frozenset(),
            identity=args["identity"],
            http_client=client,
            pricing=args["pricing"],
        )
