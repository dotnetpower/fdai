"""Shared pytest fixtures.

Kept intentionally thin - most subsystem-specific fixtures colocate with their
Core service subsystem. Only truly cross-cutting things (composition helpers,
common valid instances) live here.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import pytest
from fdai.composition import Container, default_container
from fdai.shared.config import AppConfig


@pytest.fixture(autouse=True, scope="session")
def _shutdown_otel_at_session_end() -> Iterator[None]:
    """Flush the OTel tracer provider before pytest closes captured streams.

    Without this fixture, the BatchSpanProcessor's background thread races
    pytest's teardown of stdout and prints a scary (but harmless) traceback
    on session exit. The shutdown is idempotent - safe to run even when
    no test touched tracing.
    """
    yield
    from opentelemetry import trace

    provider = trace.get_tracer_provider()
    shutdown = getattr(provider, "shutdown", None)
    if callable(shutdown):
        shutdown()


@pytest.fixture()
def app_config() -> AppConfig:
    """A customer-agnostic :class:`AppConfig` for tests.

    Kept in code (not env) so the test suite is deterministic regardless of
    the shell environment. Real deployments load from env via
    :func:`fdai.composition.default_container_from_env`.
    """
    return AppConfig.model_validate(
        {
            "schema_version": "1.0.0",
            "azure": {
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "resource_group": "rg-fdai",
                "region": "krc",
            },
            "kafka": {
                "bootstrap_servers": "evhns-fdai.example.local:9093",
                "topic_events": "aw.change.events",
            },
            "postgres": {
                "host": "psql-fdai.example.local",
                "database": "fdai",
            },
            "rule_catalog": {"ref": "main"},
            "runtime": {"env": "dev"},
        }
    )


@pytest.fixture()
def container(app_config: AppConfig) -> Container:
    """Upstream default binding - same wiring an entry point receives."""
    return default_container(app_config)


@pytest.fixture()
def valid_event() -> dict[str, Any]:
    """A minimal, customer-agnostic event that passes the Event schema."""
    return {
        "schema_version": "1.0.0",
        "event_id": "00000000-0000-0000-0000-000000000001",
        "idempotency_key": "example-key-1",
        "source": "example_source",
        "event_type": "change_detected",
        "detected_at": "2026-07-05T08:00:00Z",
        "ingested_at": "2026-07-05T08:00:01Z",
        "mode": "shadow",
    }


@pytest.fixture()
def valid_action() -> dict[str, Any]:
    """A minimal Action carrying every safety-invariant field."""
    return {
        "schema_version": "1.0.0",
        "action_id": "00000000-0000-0000-0000-000000000002",
        "idempotency_key": "example-action-1",
        "event_id": "00000000-0000-0000-0000-000000000001",
        "action_type": "tag_missing_owner",
        "target_resource_ref": "resource:example/rg/example-resource",
        "operation": "tag",
        "params": {"owner": "unassigned"},
        "stop_condition": "provider_api_error_streak",
        "stop_conditions": [{"kind": "provider_api_error_streak", "count": 3}],
        "rollback_ref": {"kind": "pr_revert", "reference": "example-pr-1"},
        "blast_radius": {"scope": "resource", "count": 1, "rate_per_minute": 5},
        "mode": "shadow",
        "citing_rules": ["example.tag.owner-required"],
        "created_at": "2026-07-05T08:00:02Z",
    }


@pytest.fixture()
def valid_rule() -> dict[str, Any]:
    """A minimal Rule with grounded provenance."""
    return {
        "schema_version": "1.0.0",
        "id": "example.tag.owner-required",
        "version": "1.0.0",
        "source": "custom",
        "severity": "low",
        "category": "config_drift",
        "resource_type": "compute.vm",
        "check_logic": {
            "kind": "rego",
            "reference": "policies/example/tag-owner.rego",
        },
        "remediation": {
            "template_ref": "remediations/example-tag-owner",
            "cost_impact_monthly_usd": 0,
        },
        "remediates": "remediate.tag-add",
        "provenance": {
            "source_url": "https://example.com/rules/tag-owner",
            "resolved_ref": "0000000000000000000000000000000000000000",
            "content_hash": "sha256:example",
            "license": "MIT",
            "redistribution": "embeddable",
            "retrieved_at": "2026-07-05T00:00:00Z",
        },
    }


@pytest.fixture()
def valid_ontology_action_type() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "name": "remediate.tag-missing-owner",
        "version": "1.0.0",
        "operation": "tag",
        "interfaces": ["ControlPlane", "IdempotentByKey"],
        "rollback_contract": "pr_revert",
        "default_mode": "shadow",
        "promotion_gate": {
            "min_shadow_days": 14,
            "min_samples": 100,
            "min_accuracy": 0.95,
            "max_policy_escapes": 0,
        },
        "description": "Attach an owner tag when missing.",
    }


class InMemorySchemaRegistry:
    """Test-only :class:`~fdai.shared.contracts.registry.SchemaRegistry`.

    Kept inside the Core service test tree so ``core/`` cannot import it by
    accident.
    A permanent, package-level fake lands in ``shared/providers/testing/``
    once WI6 (Local Dev Preset) is implemented.
    """

    def __init__(self, schemas: Mapping[tuple[str, str], Mapping[str, Any]]) -> None:
        self._schemas: dict[tuple[str, str], Mapping[str, Any]] = dict(schemas)

    def get(
        self, name: str, version: str | None = None
    ) -> Mapping[str, Any]:  # pragma: no cover - trivial
        if version is None:
            versions = [v for (n, v) in self._schemas if n == name]
            if not versions:
                from fdai.shared.contracts.registry import SchemaNotFoundError

                raise SchemaNotFoundError(f"unknown schema name: {name!r}")
            version = max(versions)
        key = (name, version)
        if key not in self._schemas:
            from fdai.shared.contracts.registry import SchemaNotFoundError

            raise SchemaNotFoundError(f"unknown schema: {key}")
        return self._schemas[key]

    def names(self) -> list[str]:  # pragma: no cover - trivial
        return sorted({n for (n, _v) in self._schemas})
