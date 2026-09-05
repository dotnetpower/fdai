"""Focused tests for protected service tfvars model materialization."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts" / "deployment" / "service"
_WORKFLOW = (
    Path(__file__).resolve().parents[3] / ".github" / "workflows" / "service-deploy.yml"
).read_text(encoding="utf-8")
_PRIMARY_ENDPOINT = "https://oai-fdai.openai.azure.com"
_MODEL_ENDPOINTS = {"azure-openai:oai-fdai": _PRIMARY_ENDPOINT}
sys.path.insert(0, str(_SCRIPTS))


@pytest.fixture(scope="module")
def tfvars() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "focused_materialize_tfvars", _SCRIPTS / "materialize_tfvars.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def host_hydrator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "focused_hydrate_database_host", _SCRIPTS / "hydrate_database_host.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def console_hydrator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "focused_hydrate_console_origin", _SCRIPTS / "hydrate_console_origin.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def topic_hydrator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "focused_hydrate_event_topic", _SCRIPTS / "hydrate_event_topic.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def observation_hydrator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "focused_hydrate_observation_context",
        _SCRIPTS / "hydrate_observation_context.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(canonical).hexdigest()


def test_derives_core_llm_from_attested_resolved_models(tfvars: ModuleType) -> None:
    resolved_models = {
        "schema_version": "1.0.0",
        "capabilities": [],
        "narrator_candidates": [
            {"endpoint": f"{_PRIMARY_ENDPOINT}/", "deployment": "primary"},
            {"endpoint": _PRIMARY_ENDPOINT, "deployment": "secondary"},
        ],
    }
    digest = _digest(resolved_models)
    payload = {
        "environments": {
            "dev": {"core-control-plane": {"name": "example", "llm": {"endpoint": "stale"}}}
        }
    }

    selected = tfvars.select_tfvars(
        payload,
        service="core-control-plane",
        environment="dev",
        resolved_models=resolved_models,
        resolved_models_digest=digest,
        model_endpoints=_MODEL_ENDPOINTS,
        web_search_requested=True,
        web_search_allowed_domains=["learn.example.com"],
    )

    assert selected["llm"] == {
        "endpoint": _PRIMARY_ENDPOINT,
        "model_endpoints": _MODEL_ENDPOINTS,
        "web_search_enabled": False,
        "web_search_allowed_domains": [],
        "web_search_max_results": 8,
        "web_search_timeout_seconds": 45,
        "resolved_models_digest": digest,
    }
    assert payload["environments"]["dev"]["core-control-plane"]["llm"] == {"endpoint": "stale"}


def test_derives_foundry_endpoint_from_authoritative_platform_map(tfvars: ModuleType) -> None:
    foundry_ref = "azure-foundry:aif-fdai-models"
    foundry_endpoint = "https://aif-fdai-models.services.ai.azure.com"
    resolved_models = {
        "schema_version": "1.0.0",
        "capabilities": [],
        "narrator": {"endpoint": _PRIMARY_ENDPOINT, "deployment": "primary"},
        "endpoint_bindings": [{"endpoint_ref": foundry_ref}],
    }

    materialized = tfvars.materialize_core_llm(
        resolved_models,
        expected_digest=_digest(resolved_models),
        model_endpoints={
            **_MODEL_ENDPOINTS,
            foundry_ref: f"{foundry_endpoint}/",
        },
    )

    assert materialized["model_endpoints"] == {
        foundry_ref: foundry_endpoint,
        **_MODEL_ENDPOINTS,
    }


def test_rejects_missing_foundry_endpoint_for_sealed_binding(tfvars: ModuleType) -> None:
    resolved_models = {
        "schema_version": "1.0.0",
        "capabilities": [],
        "narrator": {"endpoint": _PRIMARY_ENDPOINT, "deployment": "primary"},
        "endpoint_bindings": [{"endpoint_ref": "azure-foundry:aif-fdai-models"}],
    }

    with pytest.raises(tfvars.TfvarsError, match="do not cover a Foundry binding"):
        tfvars.materialize_core_llm(
            resolved_models,
            expected_digest=_digest(resolved_models),
            model_endpoints=_MODEL_ENDPOINTS,
        )


@pytest.mark.parametrize(
    "model_endpoints",
    [
        {},
        {"azure-openai:wrong": _PRIMARY_ENDPOINT},
        {"azure-foundry:aif-fdai": _PRIMARY_ENDPOINT},
        {"unknown:oai-fdai": _PRIMARY_ENDPOINT},
    ],
)
def test_rejects_malformed_or_mismatched_platform_model_endpoints(
    tfvars: ModuleType,
    model_endpoints: dict[str, str],
) -> None:
    resolved_models = {
        "schema_version": "1.0.0",
        "capabilities": [],
        "narrator": {"endpoint": _PRIMARY_ENDPOINT, "deployment": "primary"},
    }

    with pytest.raises(tfvars.TfvarsError, match="platform model endpoint"):
        tfvars.materialize_core_llm(
            resolved_models,
            expected_digest=_digest(resolved_models),
            model_endpoints=model_endpoints,
        )


def test_hydrates_database_host_from_authoritative_platform_output(
    host_hydrator: ModuleType,
) -> None:
    payload = {
        "environments": {
            "dev": {
                "core-control-plane": {
                    "name": "example",
                    "database": {
                        "dsn_secret_id": "https://vault.example.com/secrets/core-dsn",
                        "role": "core_runtime",
                    },
                }
            }
        }
    }

    hydrated = host_hydrator.hydrate_database_host(
        payload,
        service="core-control-plane",
        environment="dev",
        database_host="postgres.example.com.",
    )

    assert hydrated["environments"]["dev"]["core-control-plane"]["database"] == {
        "dsn_secret_id": "https://vault.example.com/secrets/core-dsn",
        "host": "postgres.example.com",
        "role": "core_runtime",
    }
    assert "host" not in payload["environments"]["dev"]["core-control-plane"]["database"]


@pytest.mark.parametrize(
    "database_host",
    [
        "",
        "-postgres.example.com",
        "postgres..example.com",
        "postgres.example.com:5432",
        "호스트.example.com",
    ],
)
def test_rejects_invalid_authoritative_database_host(
    host_hydrator: ModuleType,
    database_host: str,
) -> None:
    payload = {
        "environments": {
            "dev": {
                "core-control-plane": {
                    "name": "example",
                    "database": {"dsn_secret_id": "secret", "role": "core_runtime"},
                }
            }
        }
    }

    with pytest.raises(host_hydrator.DatabaseHostError, match="valid DNS hostname"):
        host_hydrator.hydrate_database_host(
            payload,
            service="core-control-plane",
            environment="dev",
            database_host=database_host,
        )


def test_hydrates_operator_console_origin_from_platform_output(
    console_hydrator: ModuleType,
) -> None:
    payload = {
        "environments": {
            "dev": {
                "operator-service": {
                    "name": "example",
                    "cors_allow_origins": "",
                }
            }
        }
    }

    hydrated = console_hydrator.hydrate_console_origin(
        payload,
        service="operator-service",
        environment="dev",
        console_hostname="example.azurestaticapps.net.",
    )

    assert (
        hydrated["environments"]["dev"]["operator-service"]["cors_allow_origins"]
        == "https://example.azurestaticapps.net"
    )
    assert payload["environments"]["dev"]["operator-service"]["cors_allow_origins"] == ""


@pytest.mark.parametrize(
    "console_hostname",
    [
        "",
        "https://example.azurestaticapps.net",
        "example.com",
        "example..azurestaticapps.net",
    ],
)
def test_rejects_invalid_authoritative_console_hostname(
    console_hydrator: ModuleType,
    console_hostname: str,
) -> None:
    payload = {
        "environments": {
            "dev": {
                "operator-service": {
                    "name": "example",
                    "cors_allow_origins": "",
                }
            }
        }
    }

    with pytest.raises(console_hydrator.ConsoleOriginError, match="Console hostname"):
        console_hydrator.hydrate_console_origin(
            payload,
            service="operator-service",
            environment="dev",
            console_hostname=console_hostname,
        )


def test_hydrates_primary_event_topic_from_authoritative_platform_output(
    topic_hydrator: ModuleType,
) -> None:
    service = "core-control-plane"
    payload = {
        "environments": {
            "dev": {
                service: {
                    "name": "example",
                    "event_topics": {"events": "aw.change.events", "other": "preserved"},
                }
            }
        }
    }

    hydrated = topic_hydrator.hydrate_event_topic(
        payload,
        service=service,
        environment="dev",
        event_topic="fdai.change.events",
        pipeline_stage_topic="fdai.pipeline.stages",
        pantheon_object_topic="fdai.pantheon.objects",
    )

    assert hydrated["environments"]["dev"][service]["event_topics"] == {
        "events": "fdai.change.events",
        "other": "preserved",
    }
    assert payload["environments"]["dev"][service]["event_topics"]["events"] == ("aw.change.events")


def test_hydrates_operator_logical_topics_from_authoritative_contract(
    topic_hydrator: ModuleType,
) -> None:
    original = {
        "events": "aw.change.events",
        "semantic_requests": "legacy.semantic.requests",
        "semantic_projections": "legacy.semantic.projections",
        "semantic_physical": "aw.pantheon.objects",
        "read_investigation_requests": "legacy.read.requests",
        "incident_intervention_requests": "legacy.incident.requests",
        "read_investigation_completions": "legacy.read.completions",
        "hil_decisions": "operator.hil-decisions",
        "notification_receipts": "legacy.notification.receipts",
    }
    payload = {
        "environments": {
            "dev": {
                "operator-service": {
                    "name": "example",
                    "event_topics": dict(original),
                }
            }
        }
    }

    hydrated = topic_hydrator.hydrate_event_topic(
        payload,
        service="operator-service",
        environment="dev",
        event_topic="fdai.change.events",
        pipeline_stage_topic="fdai.pipeline.stages",
        pantheon_object_topic="fdai.pantheon.objects",
    )

    assert hydrated["environments"]["dev"]["operator-service"]["event_topics"] == {
        "events": "fdai.change.events",
        "semantic_requests": "operator.semantic-turn.requests",
        "semantic_projections": "core.semantic-turn.projections",
        "semantic_physical": "fdai.pantheon.objects",
        "read_investigation_requests": "operator.read-investigation.requests",
        "incident_intervention_requests": "operator.incident-intervention.requests",
        "read_investigation_completions": "core.read-investigation.completions",
        "hil_decisions": "fdai.hil.decisions",
        "notification_receipts": "fdai.notifications.delivery-receipts",
    }
    assert payload["environments"]["dev"]["operator-service"]["event_topics"] == original


def test_hydrates_missing_operator_logical_topics(
    topic_hydrator: ModuleType,
) -> None:
    payload = {
        "environments": {
            "dev": {
                "operator-service": {
                    "name": "example",
                    "event_topics": {"events": "aw.change.events"},
                }
            }
        }
    }

    hydrated = topic_hydrator.hydrate_event_topic(
        payload,
        service="operator-service",
        environment="dev",
        event_topic="fdai.change.events",
        pipeline_stage_topic="fdai.pipeline.stages",
        pantheon_object_topic="fdai.pantheon.objects",
    )

    assert (
        hydrated["environments"]["dev"]["operator-service"]["event_topics"][
            "read_investigation_requests"
        ]
        == "operator.read-investigation.requests"
    )
    assert (
        hydrated["environments"]["dev"]["operator-service"]["event_topics"]["notification_receipts"]
        == "fdai.notifications.delivery-receipts"
    )
    assert payload["environments"]["dev"]["operator-service"]["event_topics"] == {
        "events": "aw.change.events"
    }


def test_hydrates_core_observation_context_from_platform_output(
    observation_hydrator: ModuleType,
) -> None:
    payload = {
        "environments": {
            "dev": {
                "core-control-plane": {
                    "name": "example",
                    "observation_context": {"enabled": False},
                }
            }
        }
    }
    binding = {
        "signing_seed_secret_id": "https://vault.example.com/secrets/ohl-seed",
        "executor_credential_lineage": "azure-managed-identity:executor",
        "source_credential_lineage": "azure-managed-identity:inventory",
    }

    hydrated = observation_hydrator.hydrate_observation_context(
        payload,
        service="core-control-plane",
        environment="dev",
        binding=binding,
    )

    assert hydrated["environments"]["dev"]["core-control-plane"]["observation_context"] == {
        "enabled": True,
        **binding,
    }
    assert payload["environments"]["dev"]["core-control-plane"]["observation_context"] == {
        "enabled": False
    }


def test_absent_platform_observation_binding_removes_stale_core_input(
    observation_hydrator: ModuleType,
) -> None:
    payload = {
        "environments": {
            "dev": {
                "core-control-plane": {
                    "name": "example",
                    "observation_context": {"enabled": True},
                }
            }
        }
    }

    hydrated = observation_hydrator.hydrate_observation_context(
        payload,
        service="core-control-plane",
        environment="dev",
        binding=None,
    )

    assert "observation_context" not in hydrated["environments"]["dev"]["core-control-plane"]


@pytest.mark.parametrize(
    "binding",
    [
        {},
        {"signing_seed_secret_id": "secret"},
        {
            "signing_seed_secret_id": "secret",
            "executor_credential_lineage": "",
            "source_credential_lineage": "source",
        },
        {
            "signing_seed_secret_id": "secret",
            "executor_credential_lineage": " Same ",
            "source_credential_lineage": "same",
        },
    ],
)
def test_rejects_invalid_platform_observation_binding(
    observation_hydrator: ModuleType,
    binding: object,
) -> None:
    payload = {"environments": {"dev": {"core-control-plane": {"name": "example"}}}}

    with pytest.raises(observation_hydrator.ObservationContextError):
        observation_hydrator.hydrate_observation_context(
            payload,
            service="core-control-plane",
            environment="dev",
            binding=binding,
        )


def test_preserves_service_without_primary_event_topic(topic_hydrator: ModuleType) -> None:
    payload = {
        "environments": {"dev": {"isolated-executor": {"name": "example", "event_topics": {}}}}
    }

    hydrated = topic_hydrator.hydrate_event_topic(
        payload,
        service="isolated-executor",
        environment="dev",
        event_topic="fdai.change.events",
        pipeline_stage_topic="fdai.pipeline.stages",
        pantheon_object_topic="fdai.pantheon.objects",
    )

    assert hydrated == payload
    assert hydrated is not payload


@pytest.mark.parametrize(
    "event_topic",
    ["", "aw.change.events", "fdai.change.events.dlq", "fdai.Change.events"],
)
def test_rejects_noncanonical_authoritative_event_topic(
    topic_hydrator: ModuleType,
    event_topic: str,
) -> None:
    payload = {
        "environments": {
            "dev": {
                "core-control-plane": {
                    "name": "example",
                    "event_topics": {"events": "fdai.change.events"},
                }
            }
        }
    }

    with pytest.raises(topic_hydrator.EventTopicError, match="canonical"):
        topic_hydrator.hydrate_event_topic(
            payload,
            service="core-control-plane",
            environment="dev",
            event_topic=event_topic,
            pipeline_stage_topic="fdai.pipeline.stages",
            pantheon_object_topic="fdai.pantheon.objects",
        )


@pytest.mark.parametrize(
    ("service", "event_topics", "expected"),
    [
        (
            "document-ingestion-api",
            {"pipeline_stages": "aw.pipeline.stages"},
            {"pipeline_stages": "fdai.pipeline.stages"},
        ),
        (
            "document-processing-worker",
            {
                "pipeline_stages": "aw.pipeline.stages",
                "pantheon_objects": "aw.pantheon.objects",
            },
            {
                "pipeline_stages": "fdai.pipeline.stages",
                "pantheon_objects": "fdai.pantheon.objects",
            },
        ),
    ],
)
def test_hydrates_document_topics_from_authoritative_platform_output(
    topic_hydrator: ModuleType,
    service: str,
    event_topics: dict[str, str],
    expected: dict[str, str],
) -> None:
    payload = {
        "environments": {"dev": {service: {"name": "example", "event_topics": event_topics}}}
    }

    hydrated = topic_hydrator.hydrate_event_topic(
        payload,
        service=service,
        environment="dev",
        event_topic="fdai.change.events",
        pipeline_stage_topic="fdai.pipeline.stages",
        pantheon_object_topic="fdai.pantheon.objects",
    )

    assert hydrated["environments"]["dev"][service]["event_topics"] == expected
    assert payload["environments"]["dev"][service]["event_topics"] == event_topics


def test_enables_web_search_only_with_attested_candidate_and_policy(tfvars: ModuleType) -> None:
    resolved_models = {
        "schema_version": "1.0.0",
        "capabilities": [],
        "narrator": {"endpoint": f"{_PRIMARY_ENDPOINT}/", "deployment": "primary"},
        "web_search_candidates": [{"endpoint": _PRIMARY_ENDPOINT, "deployment": "search"}],
    }

    materialized = tfvars.materialize_core_llm(
        resolved_models,
        expected_digest=_digest(resolved_models),
        model_endpoints=_MODEL_ENDPOINTS,
        web_search_requested=True,
        web_search_allowed_domains=[" Learn.Example.COM. "],
    )

    assert materialized["web_search_enabled"] is True
    assert materialized["web_search_allowed_domains"] == ["learn.example.com"]


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda payload: payload.pop("narrator_candidates"), "exactly one narrator endpoint"),
        (
            lambda payload: payload["narrator_candidates"].append(
                {
                    "endpoint": "https://oai-other.openai.azure.com",
                    "deployment": "other",
                }
            ),
            "exactly one narrator endpoint",
        ),
        (
            lambda payload: payload["narrator_candidates"].append(
                {"endpoint": "http://oai-fdai.openai.azure.com", "deployment": "other"}
            ),
            "must be an HTTPS origin",
        ),
    ],
)
def test_rejects_missing_or_ambiguous_core_model_endpoint(
    tfvars: ModuleType,
    mutation: Callable[[dict[str, Any]], object],
    error: str,
) -> None:
    resolved_models = {
        "schema_version": "1.0.0",
        "capabilities": [],
        "narrator_candidates": [{"endpoint": _PRIMARY_ENDPOINT, "deployment": "primary"}],
    }
    mutation(resolved_models)

    with pytest.raises(tfvars.TfvarsError, match=error):
        tfvars.materialize_core_llm(
            resolved_models,
            expected_digest=_digest(resolved_models),
            model_endpoints=_MODEL_ENDPOINTS,
        )


def test_rejects_resolved_models_digest_mismatch(tfvars: ModuleType) -> None:
    resolved_models = {
        "schema_version": "1.0.0",
        "capabilities": [],
        "narrator": {"endpoint": _PRIMARY_ENDPOINT, "deployment": "primary"},
    }

    with pytest.raises(tfvars.TfvarsError, match="does not match the attested digest"):
        tfvars.materialize_core_llm(
            resolved_models,
            expected_digest="a" * 64,
            model_endpoints=_MODEL_ENDPOINTS,
        )


@pytest.mark.parametrize(
    ("resolved_models", "domains", "error"),
    [
        (
            {"schema_version": "2.0.0", "capabilities": []},
            [],
            "schema_version is unsupported",
        ),
        (
            {
                "schema_version": "1.0.0",
                "capabilities": [],
                "narrator": {"endpoint": _PRIMARY_ENDPOINT, "deployment": ""},
            },
            [],
            "deployment must be non-empty",
        ),
        (
            {
                "schema_version": "1.0.0",
                "capabilities": [],
                "narrator": {
                    "endpoint": "https://oai-fdai.openai.azure.com:invalid",
                    "deployment": "primary",
                },
            },
            [],
            "must be an HTTPS origin",
        ),
        (
            {
                "schema_version": "1.0.0",
                "capabilities": [],
                "narrator": {"endpoint": _PRIMARY_ENDPOINT, "deployment": "primary"},
            },
            ["example.com", "EXAMPLE.COM."],
            "100 unique hosts or fewer",
        ),
    ],
)
def test_rejects_malformed_model_binding_inputs(
    tfvars: ModuleType,
    resolved_models: dict[str, Any],
    domains: list[str],
    error: str,
) -> None:
    with pytest.raises(tfvars.TfvarsError, match=error):
        tfvars.materialize_core_llm(
            resolved_models,
            expected_digest=_digest(resolved_models),
            model_endpoints=_MODEL_ENDPOINTS,
            web_search_allowed_domains=domains,
        )


def test_cli_materializes_model_binding_with_owner_only_permissions(
    tfvars: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved_models = {
        "schema_version": "1.0.0",
        "capabilities": [],
        "narrator": {"endpoint": _PRIMARY_ENDPOINT, "deployment": "primary"},
    }
    service_tfvars = {"environments": {"dev": {"core-control-plane": {"name": "example"}}}}
    output = tmp_path / "service.tfvars.json"
    monkeypatch.setenv("RESOLVED_MODELS_JSON", json.dumps(resolved_models))
    monkeypatch.setenv("RESOLVED_MODELS_DIGEST", _digest(resolved_models))
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "false")
    monkeypatch.setenv("WEB_SEARCH_ALLOWED_DOMAINS_JSON", "[]")
    monkeypatch.setenv("MODEL_ENDPOINTS_JSON", json.dumps(_MODEL_ENDPOINTS))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(service_tfvars)))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "materialize_tfvars.py",
            "--service",
            "core-control-plane",
            "--environment",
            "dev",
            "--model-binding-transition",
            "--output",
            str(output),
        ],
    )

    result = tfvars.main()

    assert result == 0
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["llm"]["resolved_models_digest"] == _digest(resolved_models)
    assert output.stat().st_mode & 0o777 == 0o600


def test_workflow_delegates_core_model_binding_materialization() -> None:
    assert "RESOLVED_MODELS_JSON: ${{ vars.RESOLVED_MODELS_JSON }}" in _WORKFLOW
    assert "WEB_SEARCH_ENABLED: ${{ vars.OPERATOR_API_WEB_SEARCH_ENABLED == 'true' }}" in _WORKFLOW
    assert "WEB_SEARCH_ALLOWED_DOMAINS_JSON:" in _WORKFLOW
    assert '[[ "$SERVICE" == "core-control-plane" ]]' in _WORKFLOW
    assert "resolved_model_args+=(--model-binding-transition)" in _WORKFLOW
    assert "output -json llm_model_endpoints" in _WORKFLOW
    assert 'MODEL_ENDPOINTS_JSON="$model_endpoints_json"' in _WORKFLOW
    assert '"${resolved_model_args[@]}"' in _WORKFLOW
    assert "Core service tfvars has no LLM configuration" not in _WORKFLOW
    assert "output -json ohl_observation_context_binding" in _WORKFLOW
    assert "hydrate_observation_context.py" in _WORKFLOW
