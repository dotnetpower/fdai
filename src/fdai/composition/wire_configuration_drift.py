"""Composition binding for deterministic read-only configuration drift checks."""

from __future__ import annotations

from fdai.core.detection.configuration_drift_service import (
    ConfigurationBaselineSource,
    ConfigurationDriftService,
    ConfigurationObservationSource,
)
from fdai.delivery.configuration_drift import build_configuration_drift_bundle
from fdai.shared.providers.knowledge import KnowledgeSource

from ._helpers import Container
from .wire_capabilities import install_capability_bundle


def bind_configuration_drift(
    container: Container,
    *,
    baseline_source: ConfigurationBaselineSource,
    observation_source: ConfigurationObservationSource,
    expected_version: str,
    expected_sha256: str,
    expected_scope: str,
    knowledge_source: KnowledgeSource | None = None,
) -> Container:
    """Return a new container with one server-pinned read-only drift capability."""

    service = ConfigurationDriftService(
        baseline_source=baseline_source,
        observation_source=observation_source,
        expected_version=expected_version,
        expected_sha256=expected_sha256,
        expected_scope=expected_scope,
        knowledge_source=knowledge_source,
    )
    return install_capability_bundle(
        container,
        build_configuration_drift_bundle(service),
    )


__all__ = ["bind_configuration_drift"]
