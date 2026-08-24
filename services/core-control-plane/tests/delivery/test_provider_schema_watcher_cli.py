"""Provider schema watcher environment and source-policy composition tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fdai.delivery.azure.provider_schema import AzureBicepProviderSchemaParser
from fdai.delivery.provider_schema_watcher import ProviderSchemaSourceKind
from fdai.delivery.provider_schema_watcher_cli import (
    ProviderSchemaNetworkPolicy,
    ProviderSchemaWatcherConfig,
    _build_sources,
)


def test_config_defaults_to_blocked_and_global_corpus_bounds(tmp_path: Path) -> None:
    config = ProviderSchemaWatcherConfig.from_env({}, repo_root=tmp_path)

    assert config.network_policy is ProviderSchemaNetworkPolicy.BLOCKED
    assert config.ledger_root == tmp_path / "provider-schema-catalog"
    assert config.state_store_dsn is None
    assert config.kafka_bootstrap_servers is None
    assert config.min_type_count == 3_000
    assert config.max_type_count == 10_000
    assert _build_sources(config, parser=AzureBicepProviderSchemaParser()) == ()


def test_config_accepts_durable_provider_schema_dsn(tmp_path: Path) -> None:
    config = ProviderSchemaWatcherConfig.from_env(
        {"FDAI_PROVIDER_SCHEMA_DSN": "postgresql://provider-schema"},
        repo_root=tmp_path,
    )

    assert config.state_store_dsn == "postgresql://provider-schema"


def test_config_accepts_authenticated_pantheon_transport(tmp_path: Path) -> None:
    config = ProviderSchemaWatcherConfig.from_env(
        {"KAFKA_BOOTSTRAP_SERVERS": "namespace.servicebus.windows.net:9093"},
        repo_root=tmp_path,
    )

    assert config.kafka_bootstrap_servers == "namespace.servicebus.windows.net:9093"


def test_config_rejects_partial_source_binding(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="configured together"):
        ProviderSchemaWatcherConfig.from_env(
            {"FDAI_PROVIDER_SCHEMA_PRIMARY_REPO": "https://example.com/repo.git"},
            repo_root=tmp_path,
        )


@pytest.mark.parametrize(
    ("policy", "allowed_kinds"),
    [
        (
            "public",
            {
                ProviderSchemaSourceKind.PRIMARY,
                ProviderSchemaSourceKind.MIRROR,
                ProviderSchemaSourceKind.OFFLINE,
            },
        ),
        ("mirror-only", {ProviderSchemaSourceKind.MIRROR, ProviderSchemaSourceKind.OFFLINE}),
        ("offline-only", {ProviderSchemaSourceKind.OFFLINE}),
        ("blocked", set()),
    ],
)
def test_network_policy_controls_source_calls_before_collection(
    tmp_path: Path,
    policy: str,
    allowed_kinds: set[ProviderSchemaSourceKind],
) -> None:
    config = ProviderSchemaWatcherConfig.from_env(
        {
            "FDAI_PROVIDER_SCHEMA_NETWORK_POLICY": policy,
            "FDAI_PROVIDER_SCHEMA_PRIMARY_REPO": "https://example.com/primary.git",
            "FDAI_PROVIDER_SCHEMA_PRIMARY_REF": "refs/heads/main",
            "FDAI_PROVIDER_SCHEMA_MIRROR_REPO": "https://example.com/mirror.git",
            "FDAI_PROVIDER_SCHEMA_MIRROR_REF": "refs/heads/main",
            "FDAI_PROVIDER_SCHEMA_OFFLINE_ROOT": str(tmp_path / "offline"),
            "FDAI_PROVIDER_SCHEMA_OFFLINE_REVISION": "a" * 40,
        },
        repo_root=tmp_path,
    )

    sources = _build_sources(config, parser=AzureBicepProviderSchemaParser())

    assert {source.kind for source in sources if source.allowed} == allowed_kinds
