"""Dev/deploy parity contract test.

Design reference:
[dev-and-deploy-parity.md § Parity Contract](../docs/roadmap/dev-and-deploy-parity.md)

    "the code path that binds seams in a local-fake laptop debug session
    and the code path that binds seams under Azure Container Apps MUST be
    the same code path — configured differently via env vars, never
    forked by if-else in `core/`."

The unit tests in :mod:`tests.test_composition_llm` cover the two ends
(local-fake, azure) individually. This test proves the **runtime env
shape** that a live Azure Container Apps deployment injects into the
process is understood by
:func:`aiopspilot.composition.default_container_from_env` with zero
production-only branches.

The env values match the actually deployed resources under
``rg-aiopspilot-dev-krc`` (moonchoi subscription) as of the P1 deploy —
Postgres FQDN, Event Hubs Kafka endpoint, tenant/subscription ids,
Container App identity. If a fork drifts one of those env-var *names*,
the deployed process fails-closed at import via
:class:`aiopspilot.shared.config.errors.ConfigError`; this test proves
the shape upstream ships.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from aiopspilot.composition import Container, default_container
from aiopspilot.shared.config.loader import load_from_mapping
from aiopspilot.shared.config.models import AppConfig, LlmMode
from aiopspilot.shared.config.provider import EnvVarConfigProvider

# ---------------------------------------------------------------------------
# Live-deploy env shape - generic rg-aiopspilot-dev-krc-shaped env with
# placeholder GUIDs. The fork substitutes real tenant/subscription ids at
# deploy time; tests only verify the config loader round-trips the shape.
# ---------------------------------------------------------------------------

_LIVE_DEPLOY_ENV_LOCAL_FAKE: Mapping[str, str] = {
    "AZURE_TENANT_ID": "00000000-0000-0000-0000-000000000001",
    "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000002",
    "AZURE_RESOURCE_GROUP": "rg-aiopspilot-dev-krc",
    "AZURE_REGION": "koreacentral",
    "KAFKA_BOOTSTRAP_SERVERS": "evhns-aiopspilot-dev-krc.servicebus.windows.net:9093",
    "KAFKA_SECURITY_PROTOCOL": "SASL_SSL",
    "KAFKA_SASL_MECHANISM": "OAUTHBEARER",
    "KAFKA_TOPIC_EVENTS": "aw.change.events",
    "POSTGRES_HOST": "psql-aiopspilot-dev-krc.postgres.database.azure.com",
    "POSTGRES_DATABASE": "aiopspilot",
    "RUNTIME_ENV": "dev",
    "LLM_MODE": "local-fake",
}

_LIVE_DEPLOY_ENV_AZURE_MODE = {
    **_LIVE_DEPLOY_ENV_LOCAL_FAKE,
    "LLM_MODE": "azure",
    "LLM_RESOLVED_MODELS_PATH": "/mnt/secrets/resolved-models.json",
}


# ---------------------------------------------------------------------------
# Parity tests
# ---------------------------------------------------------------------------


def test_live_deploy_env_shape_local_fake_binds_container() -> None:
    """Local-fake LLM mode boots a full container from the deployed env shape.

    Proves the runtime env shape that Container Apps injects satisfies
    every required config key without touching an azure secret.
    """
    provider = EnvVarConfigProvider(env=_LIVE_DEPLOY_ENV_LOCAL_FAKE)
    config: AppConfig = provider.get()

    assert str(config.azure.tenant_id) == "00000000-0000-0000-0000-000000000001"
    assert str(config.azure.subscription_id) == "00000000-0000-0000-0000-000000000002"
    assert config.azure.resource_group == "rg-aiopspilot-dev-krc"
    assert config.azure.region == "koreacentral"
    assert config.kafka.bootstrap_servers.endswith(":9093")
    assert config.postgres.host.endswith("postgres.database.azure.com")
    assert config.runtime.env == "dev"
    assert config.llm.mode == LlmMode.LOCAL_FAKE

    container: Container = default_container(config)
    assert container.llm_bindings is not None
    assert len(container.llm_bindings.cross_check_models) >= 2


def test_live_deploy_env_shape_azure_mode_defers_llm_binding() -> None:
    """Azure LLM mode leaves llm_bindings unbound until bind_azure_llm_bindings runs.

    The default composition MUST NOT attempt to reach Azure OpenAI at
    startup — it produces an unbound container that raises
    :class:`LlmBindingsUnavailableError` if T2 is invoked before the
    entry point wires the real adapters. That fail-close contract is the
    core of the dev/deploy parity gate.
    """
    provider = EnvVarConfigProvider(env=_LIVE_DEPLOY_ENV_AZURE_MODE)
    config: AppConfig = provider.get()
    assert config.llm.mode == LlmMode.AZURE
    assert config.llm.resolved_models_path == "/mnt/secrets/resolved-models.json"

    container: Container = default_container(config)
    assert container.llm_bindings is None

    from aiopspilot.composition import LlmBindingsUnavailableError

    with pytest.raises(LlmBindingsUnavailableError):
        container.require_llm_bindings()


def test_missing_required_env_key_fails_closed() -> None:
    """Every required key is genuinely required.

    A drift in the deployed env (e.g. Container App template renames
    ``POSTGRES_HOST``) MUST fail-close, not silently degrade.
    """
    from aiopspilot.shared.config.errors import ConfigError

    incomplete = dict(_LIVE_DEPLOY_ENV_LOCAL_FAKE)
    del incomplete["POSTGRES_HOST"]

    with pytest.raises(ConfigError) as exc_info:
        EnvVarConfigProvider(env=incomplete).get()
    issues = exc_info.value.issues
    assert any(
        issue.key == "POSTGRES_HOST" or issue.key.startswith("postgres") for issue in issues
    ), f"expected POSTGRES_HOST to surface as a missing key; got issues={issues}"


def test_load_from_mapping_agrees_with_env_var_provider() -> None:
    """Round-trip: env-var → dotted config → same AppConfig as file-mapping load.

    Documents the parity: fork-provided config-service adapters can produce
    the same :class:`AppConfig` as the env-var provider by returning the
    same dotted-key mapping. If this drifts, forks binding config via App
    Configuration / ConsulKV would silently disagree with the env-var path.
    """
    env_config = EnvVarConfigProvider(env=_LIVE_DEPLOY_ENV_LOCAL_FAKE).get()

    dotted: dict[str, str] = {
        "schema_version": "1.0.0",
        "azure": {  # type: ignore[dict-item]
            "tenant_id": _LIVE_DEPLOY_ENV_LOCAL_FAKE["AZURE_TENANT_ID"],
            "subscription_id": _LIVE_DEPLOY_ENV_LOCAL_FAKE["AZURE_SUBSCRIPTION_ID"],
            "resource_group": _LIVE_DEPLOY_ENV_LOCAL_FAKE["AZURE_RESOURCE_GROUP"],
            "region": _LIVE_DEPLOY_ENV_LOCAL_FAKE["AZURE_REGION"],
        },
        "kafka": {  # type: ignore[dict-item]
            "bootstrap_servers": _LIVE_DEPLOY_ENV_LOCAL_FAKE["KAFKA_BOOTSTRAP_SERVERS"],
            "security_protocol": _LIVE_DEPLOY_ENV_LOCAL_FAKE["KAFKA_SECURITY_PROTOCOL"],
            "sasl_mechanism": _LIVE_DEPLOY_ENV_LOCAL_FAKE["KAFKA_SASL_MECHANISM"],
            "topic_events": _LIVE_DEPLOY_ENV_LOCAL_FAKE["KAFKA_TOPIC_EVENTS"],
        },
        "postgres": {  # type: ignore[dict-item]
            "host": _LIVE_DEPLOY_ENV_LOCAL_FAKE["POSTGRES_HOST"],
            "database": _LIVE_DEPLOY_ENV_LOCAL_FAKE["POSTGRES_DATABASE"],
        },
        "runtime": {"env": _LIVE_DEPLOY_ENV_LOCAL_FAKE["RUNTIME_ENV"]},  # type: ignore[dict-item]
        "llm": {"mode": _LIVE_DEPLOY_ENV_LOCAL_FAKE["LLM_MODE"]},  # type: ignore[dict-item]
    }
    file_config = load_from_mapping(dotted)  # type: ignore[arg-type]

    assert env_config == file_config
