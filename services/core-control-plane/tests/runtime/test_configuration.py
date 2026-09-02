"""Runtime model endpoint reference resolution tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fdai.composition import default_container
from fdai.core.detection.configuration_drift import (
    ConfigurationResource,
    FrozenConfigurationBaseline,
)
from fdai.runtime.configuration import (
    _attach_runtime_configuration_drift,
    _catalog_root_candidates,
    _direct_model_endpoint_resolver,
    _json_string_tuple,
    _model_endpoint_resolver,
)
from fdai.shared.config.models import AppConfig
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity


def test_catalog_candidates_prefer_complete_container_payload() -> None:
    candidates = _catalog_root_candidates(
        Path("/app/.venv/lib/python3.13/site-packages/fdai/runtime/configuration.py"),
        Path("/app"),
    )

    assert candidates[0] == Path("/app/rule-catalog")
    assert candidates.index(Path("/app/rule-catalog")) < candidates.index(
        Path("/app/.venv/rule-catalog")
    )


def test_bootstrap_binds_symptom_index_to_resolved_catalog() -> None:
    bootstrap = Path("services/core-control-plane/src/fdai/runtime/bootstrap_core.py").read_text(
        encoding="utf-8"
    )

    assert 'build_from_promoted(_resolve_catalog_root() / "chaos-scenarios")' in bootstrap


def test_semantic_bootstrap_uses_account_qualified_endpoint_map() -> None:
    bootstrap = Path(
        "services/core-control-plane/src/fdai/runtime/bootstrap_semantics.py"
    ).read_text(encoding="utf-8")

    assert "_model_endpoint_resolver(" in bootstrap
    assert 'environment.get("FDAI_MODEL_ENDPOINTS_JSON")' in bootstrap
    assert "_direct_model_endpoint_resolver(" not in bootstrap


def test_runtime_bootstrap_attaches_knowledge_after_llm_finalization() -> None:
    bootstrap = Path("services/core-control-plane/src/fdai/runtime/bootstrap.py").read_text(
        encoding="utf-8"
    )

    finalize = bootstrap.index("container = await _finalize_llm_bindings(")
    knowledge = bootstrap.index("container = _attach_runtime_knowledge_source(container)")
    assert knowledge > finalize
    assert "if container.llm_bindings is not None:" in bootstrap[finalize:knowledge]


def test_runtime_bootstrap_reuses_one_settings_snapshot_for_llm_and_core() -> None:
    bootstrap = Path("services/core-control-plane/src/fdai/runtime/bootstrap.py").read_text(
        encoding="utf-8"
    )

    llm_call = bootstrap[
        bootstrap.index("container = await _finalize_llm_bindings(") : bootstrap.index(
            "bindings: LlmBindings"
        )
    ]
    core_call = bootstrap[
        bootstrap.index("core_runtime = await build_core_runtime(") : bootstrap.index(
            "elif pantheon_start_enabled"
        )
    ]
    drift_call = bootstrap[
        bootstrap.index("container = _attach_runtime_configuration_drift(") : bootstrap.index(
            "core_runtime: CoreRuntime"
        )
    ]

    assert "runtime_values=runtime_values" in llm_call
    assert "runtime_values_snapshot=runtime_values" in core_call
    assert "runtime_values_snapshot" not in drift_call


def test_direct_model_endpoint_resolver_accepts_only_matching_account_ref() -> None:
    endpoint = "https://oai-example.openai.azure.com/"
    resolve = _direct_model_endpoint_resolver(endpoint)

    assert resolve("azure-openai:oai-example") == endpoint
    with pytest.raises(ValueError, match="does not match"):
        resolve("azure-openai:other")


def test_model_endpoint_resolver_accepts_exact_foundry_account_map() -> None:
    primary = "https://oai-example.openai.azure.com/"
    foundry = "https://aif-example.services.ai.azure.com/"
    resolve = _model_endpoint_resolver(
        primary,
        '{"azure-foundry:aif-example":"https://aif-example.services.ai.azure.com/"}',
    )

    assert resolve("azure-openai:oai-example") == primary
    assert resolve("azure-foundry:aif-example") == foundry


@pytest.mark.parametrize(
    "mapping",
    [
        "not-json",
        "{}",
        '{"azure-foundry:wrong":"https://aif-example.services.ai.azure.com/"}',
        '{"azure-openai:aif-example":"https://aif-example.services.ai.azure.com/"}',
    ],
)
def test_model_endpoint_resolver_rejects_invalid_maps(mapping: str) -> None:
    with pytest.raises(ValueError):
        _model_endpoint_resolver(
            "https://oai-example.openai.azure.com/",
            mapping,
        )


@pytest.mark.parametrize(
    "endpoint",
    (
        "http://oai-example.openai.azure.com",
        "https://models.example.com",
        "https://user@example.openai.azure.com",
        "https://oai-example.openai.azure.com/openai?api-version=1",
    ),
)
def test_direct_model_endpoint_resolver_rejects_invalid_endpoint(endpoint: str) -> None:
    with pytest.raises(ValueError, match="Azure OpenAI|identify|origin"):
        _direct_model_endpoint_resolver(endpoint)


def _container():  # type: ignore[no-untyped-def]
    return default_container(
        AppConfig.model_validate(
            {
                "schema_version": "1.0.0",
                "azure": {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "subscription_id": "00000000-0000-0000-0000-000000000000",
                    "region": "koreacentral",
                },
                "kafka": {
                    "bootstrap_servers": "events.example.com:9093",
                    "topic_events": "fdai.events",
                },
                "postgres": {"host": "postgres.example.com", "database": "fdai"},
                "runtime": {"env": "dev"},
                "llm": {"mode": "local-fake"},
            }
        )
    )


def _drift_environment(
    baseline_path: Path,
    baseline: FrozenConfigurationBaseline,
) -> dict[str, str]:
    return {
        "FDAI_CONFIGURATION_DRIFT_ENABLED": "1",
        "FDAI_CONFIGURATION_BASELINE_PATH": str(baseline_path),
        "FDAI_CONFIGURATION_BASELINE_VERSION": baseline.version,
        "FDAI_CONFIGURATION_BASELINE_SHA256": baseline.sha256,
        "FDAI_CONFIGURATION_SCOPE": baseline.scope,
        "FDAI_CONFIGURATION_SUBSCRIPTIONS_JSON": ('["00000000-0000-0000-0000-000000000001"]'),
        "FDAI_CONFIGURATION_ATTRIBUTE_PATHS_JSON": (
            '["properties.publicNetworkAccess","sku.name"]'
        ),
    }


async def test_runtime_binds_azure_configuration_drift_when_complete(tmp_path: Path) -> None:
    baseline = FrozenConfigurationBaseline(
        version="example-v1",
        created_at=datetime(2026, 8, 28, tzinfo=UTC),
        scope="scope:example-platform",
        source="reviewed snapshot",
        document_sha256="a" * 64,
        resources=(
            ConfigurationResource(
                local_name="widget#0000000000000000",
                resource_type="example/widgets",
                region="koreacentral",
                attributes={"properties.publicNetworkAccess": "Disabled"},
            ),
        ),
    )
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(baseline.to_dict()),
        encoding="utf-8",
    )
    identity = StaticWorkloadIdentity(
        audience="https://management.azure.com/.default",
        token="test-token",  # noqa: S106 - inert test credential
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    ) as client:
        original = _container()
        bound = _attach_runtime_configuration_drift(
            original,
            http_client=client,
            identity=identity,
            environment=_drift_environment(baseline_path, baseline),
        )
        assert "configuration.drift.read" not in original.capability_runtime.bound_capability_ids()
        assert "configuration.drift.read" in bound.capability_runtime.bound_capability_ids()


async def test_runtime_configuration_drift_fails_closed_on_partial_config() -> None:
    identity = StaticWorkloadIdentity(
        audience="https://management.azure.com/.default",
        token="test-token",  # noqa: S106 - inert test credential
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="BASELINE_PATH"):
            _attach_runtime_configuration_drift(
                _container(),
                http_client=client,
                identity=identity,
                environment={"FDAI_CONFIGURATION_DRIFT_ENABLED": "true"},
            )


@pytest.mark.parametrize(
    ("value", "message"),
    (
        ("not-json", "JSON array"),
        ("[]", "contain 1-4"),
        ('["a",3]', "contain 1-4"),
        ('["  "]', "contain 1-4"),
        ('["b","a"]', "unique ordered"),
        ('["a","a"]', "unique ordered"),
    ),
)
def test_runtime_configuration_string_lists_fail_closed(
    value: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _json_string_tuple({"EXAMPLE_JSON": value}, "EXAMPLE_JSON", maximum=4)
