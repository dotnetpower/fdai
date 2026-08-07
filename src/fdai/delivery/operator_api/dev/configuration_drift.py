"""Local composition for the integrity-pinned S13 configuration baseline."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from fdai.core.detection.configuration_drift import (
    ConfigurationBaselineRegistry,
    ConfigurationBaselineStatus,
    RegisteredConfigurationBaseline,
)
from fdai.core.detection.configuration_drift_codec import baseline_from_dict
from fdai.core.detection.configuration_drift_service import ConfigurationDriftService
from fdai.delivery.configuration_drift import (
    JsonFileConfigurationBaselineSource,
    JsonFileConfigurationObservationSource,
)
from fdai.delivery.configuration_drift_knowledge import (
    PinnedConfigurationBaselineKnowledgeSource,
    configuration_baseline_document,
)
from fdai.delivery.operator_api.application.conversation.capabilities.configuration_drift import (
    ConfigurationDriftChatTools,
)

_BASELINE_ENV = "FDAI_CONFIGURATION_BASELINE_JSON"
_DOCUMENT_ENV = "FDAI_CONFIGURATION_BASELINE_DOCX"
_OBSERVATION_ENV = "FDAI_CONFIGURATION_OBSERVATION_JSON"


def build_local_configuration_drift_context(
    *,
    environ: Mapping[str, str],
    repo_root: Path,
) -> ConfigurationDriftChatTools | None:
    """Build the optional local resolver from three all-or-none artifact paths."""

    configured = {
        _BASELINE_ENV: environ.get(_BASELINE_ENV, "").strip(),
        _DOCUMENT_ENV: environ.get(_DOCUMENT_ENV, "").strip(),
        _OBSERVATION_ENV: environ.get(_OBSERVATION_ENV, "").strip(),
    }
    populated = {name for name, value in configured.items() if value}
    if not populated:
        return None
    if len(populated) != len(configured):
        missing = ", ".join(sorted(set(configured) - populated))
        raise ValueError(f"configuration baseline binding is incomplete: {missing}")

    baseline_path = _path(repo_root, configured[_BASELINE_ENV])
    document_path = _path(repo_root, configured[_DOCUMENT_ENV])
    observation_path = _path(repo_root, configured[_OBSERVATION_ENV])
    raw = json.loads(baseline_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("configuration baseline JSON MUST be an object")
    baseline = baseline_from_dict(raw)
    baseline_source = JsonFileConfigurationBaselineSource(baseline_path)
    document = configuration_baseline_document(baseline, document_path=document_path)
    knowledge = PinnedConfigurationBaselineKnowledgeSource(document)
    service = ConfigurationDriftService(
        baseline_source=baseline_source,
        observation_source=JsonFileConfigurationObservationSource(
            observation_path,
            baseline.scope,
        ),
        expected_version=baseline.version,
        expected_sha256=baseline.sha256,
        expected_scope=baseline.scope,
        knowledge_source=knowledge,
    )
    return ConfigurationDriftChatTools(
        baseline_source=baseline_source,
        service=service,
        document_name=document.source_ref,
        baseline_registry=ConfigurationBaselineRegistry(
            (RegisteredConfigurationBaseline(baseline, ConfigurationBaselineStatus.ACTIVE),)
        ),
    )


def _path(repo_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo_root / path


__all__ = ["build_local_configuration_drift_context"]
