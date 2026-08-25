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
def topic_hydrator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "focused_hydrate_event_topic", _SCRIPTS / "hydrate_event_topic.py"
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
            {"endpoint": "https://models.example.com/", "deployment": "primary"},
            {"endpoint": "https://models.example.com", "deployment": "secondary"},
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
        web_search_requested=True,
        web_search_allowed_domains=["learn.example.com"],
    )

    assert selected["llm"] == {
        "endpoint": "https://models.example.com",
        "web_search_enabled": False,
        "web_search_allowed_domains": [],
        "web_search_max_results": 8,
        "web_search_timeout_seconds": 45,
        "resolved_models_digest": digest,
    }
    assert payload["environments"]["dev"]["core-control-plane"]["llm"] == {"endpoint": "stale"}


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


@pytest.mark.parametrize("service", ["core-control-plane", "operator-service"])
def test_hydrates_primary_event_topic_from_authoritative_platform_output(
    topic_hydrator: ModuleType,
    service: str,
) -> None:
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
        "narrator": {"endpoint": "https://models.example.com/", "deployment": "primary"},
        "web_search_candidates": [
            {"endpoint": "https://models.example.com", "deployment": "search"}
        ],
    }

    materialized = tfvars.materialize_core_llm(
        resolved_models,
        expected_digest=_digest(resolved_models),
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
                {"endpoint": "https://other.example.com", "deployment": "other"}
            ),
            "exactly one narrator endpoint",
        ),
        (
            lambda payload: payload["narrator_candidates"].append(
                {"endpoint": "http://models.example.com", "deployment": "other"}
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
        "narrator_candidates": [
            {"endpoint": "https://models.example.com", "deployment": "primary"}
        ],
    }
    mutation(resolved_models)

    with pytest.raises(tfvars.TfvarsError, match=error):
        tfvars.materialize_core_llm(resolved_models, expected_digest=_digest(resolved_models))


def test_rejects_resolved_models_digest_mismatch(tfvars: ModuleType) -> None:
    resolved_models = {
        "schema_version": "1.0.0",
        "capabilities": [],
        "narrator": {"endpoint": "https://models.example.com", "deployment": "primary"},
    }

    with pytest.raises(tfvars.TfvarsError, match="does not match the attested digest"):
        tfvars.materialize_core_llm(resolved_models, expected_digest="a" * 64)


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
                "narrator": {"endpoint": "https://models.example.com", "deployment": ""},
            },
            [],
            "deployment must be non-empty",
        ),
        (
            {
                "schema_version": "1.0.0",
                "capabilities": [],
                "narrator": {
                    "endpoint": "https://models.example.com:invalid",
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
                "narrator": {"endpoint": "https://models.example.com", "deployment": "primary"},
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
        "narrator": {"endpoint": "https://models.example.com", "deployment": "primary"},
    }
    service_tfvars = {"environments": {"dev": {"core-control-plane": {"name": "example"}}}}
    output = tmp_path / "service.tfvars.json"
    monkeypatch.setenv("RESOLVED_MODELS_JSON", json.dumps(resolved_models))
    monkeypatch.setenv("RESOLVED_MODELS_DIGEST", _digest(resolved_models))
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "false")
    monkeypatch.setenv("WEB_SEARCH_ALLOWED_DOMAINS_JSON", "[]")
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
    assert '"${resolved_model_args[@]}"' in _WORKFLOW
    assert "Core service tfvars has no LLM configuration" not in _WORKFLOW
