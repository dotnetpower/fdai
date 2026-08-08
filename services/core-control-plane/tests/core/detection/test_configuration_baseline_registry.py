from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.detection.configuration_drift import (
    ConfigurationBaselineNotFoundError,
    ConfigurationBaselineRegistry,
    ConfigurationBaselineStatus,
    ConfigurationResource,
    FrozenConfigurationBaseline,
    RegisteredConfigurationBaseline,
    RegistryConfigurationBaselineSource,
)

_NOW = datetime(2026, 8, 4, tzinfo=UTC)


def _baseline(version: str, *, scope: str = "example-scope") -> FrozenConfigurationBaseline:
    return FrozenConfigurationBaseline(
        version=version,
        created_at=_NOW,
        scope=scope,
        source="reviewed inventory snapshot",
        document_sha256=version[0] * 64,
        resources=(
            ConfigurationResource(
                local_name="service-a",
                resource_type="example/service",
                region="example-region",
            ),
        ),
    )


def _record(
    version: str,
    status: ConfigurationBaselineStatus,
    *,
    scope: str = "example-scope",
) -> RegisteredConfigurationBaseline:
    return RegisteredConfigurationBaseline(_baseline(version, scope=scope), status)


async def test_registry_exposes_active_and_pinned_versions() -> None:
    registry = ConfigurationBaselineRegistry(
        (
            _record("a-v1", ConfigurationBaselineStatus.SUPERSEDED),
            _record("b-v2", ConfigurationBaselineStatus.ACTIVE),
            _record("c-v3", ConfigurationBaselineStatus.CANDIDATE),
        ),
    )

    active = await RegistryConfigurationBaselineSource(registry, "example-scope").load()
    pinned = await RegistryConfigurationBaselineSource(
        registry,
        "example-scope",
        "a-v1",
    ).load()

    assert active.version == "b-v2"
    assert pinned.version == "a-v1"
    assert [record.baseline.version for record in registry.list(scope="example-scope")] == [
        "a-v1",
        "b-v2",
        "c-v3",
    ]


def test_registry_rejects_duplicate_keys_and_multiple_active_versions() -> None:
    duplicate = _record("a-v1", ConfigurationBaselineStatus.CANDIDATE)
    with pytest.raises(ValueError, match="keys MUST be unique"):
        ConfigurationBaselineRegistry((duplicate, duplicate))

    with pytest.raises(ValueError, match="one active version"):
        ConfigurationBaselineRegistry(
            (
                _record("a-v1", ConfigurationBaselineStatus.ACTIVE),
                _record("b-v2", ConfigurationBaselineStatus.ACTIVE),
            ),
        )


async def test_registry_fails_closed_when_scope_has_no_active_version() -> None:
    registry = ConfigurationBaselineRegistry(
        (_record("a-v1", ConfigurationBaselineStatus.CANDIDATE),),
    )

    with pytest.raises(ConfigurationBaselineNotFoundError):
        await RegistryConfigurationBaselineSource(registry, "example-scope").load()


def test_registry_keeps_scopes_independent() -> None:
    registry = ConfigurationBaselineRegistry(
        (
            _record("a-v1", ConfigurationBaselineStatus.ACTIVE),
            _record(
                "b-v1",
                ConfigurationBaselineStatus.ACTIVE,
                scope="another-scope",
            ),
        ),
    )

    assert registry.active(scope="example-scope").baseline.version == "a-v1"
    assert registry.active(scope="another-scope").baseline.version == "b-v1"
