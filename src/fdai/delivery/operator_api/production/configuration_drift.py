"""Production composition for one immutable Azure configuration baseline."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from fdai.core.conversation import CreateScheduledTaskCommand, Principal, Role
from fdai.core.detection.configuration_drift import (
    ConfigurationBaselineRegistry,
    ConfigurationBaselineStatus,
    ConfigurationReviewCampaignService,
    RegisteredConfigurationBaseline,
)
from fdai.core.detection.configuration_drift_codec import baseline_from_dict
from fdai.core.detection.configuration_drift_service import ConfigurationDriftService
from fdai.core.scheduler.blueprints import AutomationBlueprintReviewService
from fdai.delivery.azure.configuration_drift import (
    AzureArgConfigurationObservationSource,
    AzureConfigurationObservationConfig,
)
from fdai.delivery.configuration_drift import JsonFileConfigurationBaselineSource
from fdai.delivery.configuration_drift_knowledge import (
    PinnedConfigurationBaselineKnowledgeSource,
    configuration_baseline_document,
)
from fdai.delivery.configuration_drift_report_store import (
    StateStoreConfigurationDriftReportStore,
)
from fdai.delivery.configuration_review_runtime import ConfigurationReviewRuntime
from fdai.delivery.configuration_review_store import (
    StateStoreConfigurationReviewCampaignStore,
)
from fdai.delivery.operator_api.application.conversation.capabilities.configuration_drift import (
    ConfigurationDriftChatTools,
)
from fdai.delivery.operator_api.production import env_contract as _env
from fdai.delivery.persistence import (
    PostgresAutomationBlueprintStore,
    PostgresAutomationBlueprintStoreConfig,
    PostgresScheduleStore,
    PostgresScheduleStoreConfig,
)
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

_MAX_BASELINE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ProductionConfigurationReview:
    runtime: ConfigurationReviewRuntime
    blueprints: AutomationBlueprintReviewService


class _BlueprintAuthorizer:
    def can_review(self, principal: Principal) -> bool:
        return principal.role in {Role.APPROVER, Role.OWNER}


class _StateStoreBlueprintAudit:
    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def append(self, event: Mapping[str, Any]) -> None:
        await self._store.append_audit_entry(event)


def build_production_configuration_drift_context(
    *,
    environ: Mapping[str, str],
    subscription_id: str,
    allowed_resource_groups: Sequence[str],
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
) -> ConfigurationDriftChatTools | None:
    """Build an optional exact-scope ARG-backed production drift context."""

    configured = {
        _env.CONFIGURATION_BASELINE_JSON_ENV: environ.get(
            _env.CONFIGURATION_BASELINE_JSON_ENV, ""
        ).strip(),
        _env.CONFIGURATION_BASELINE_DOCX_ENV: environ.get(
            _env.CONFIGURATION_BASELINE_DOCX_ENV, ""
        ).strip(),
        _env.CONFIGURATION_BASELINE_RESOURCE_GROUP_ENV: environ.get(
            _env.CONFIGURATION_BASELINE_RESOURCE_GROUP_ENV, ""
        ).strip(),
    }
    populated = {name for name, value in configured.items() if value}
    if not populated:
        return None
    if len(populated) != len(configured):
        missing = ", ".join(sorted(set(configured) - populated))
        raise ValueError(f"production configuration baseline binding is incomplete: {missing}")
    if not subscription_id.strip():
        raise ValueError("production configuration baseline requires an Azure reader subscription")

    resource_group = configured[_env.CONFIGURATION_BASELINE_RESOURCE_GROUP_ENV]
    if resource_group.casefold() not in {item.casefold() for item in allowed_resource_groups}:
        raise ValueError(
            "configuration baseline resource group is outside the Azure reader allowlist"
        )

    baseline_path = _absolute_file(configured[_env.CONFIGURATION_BASELINE_JSON_ENV])
    document_path = _absolute_file(configured[_env.CONFIGURATION_BASELINE_DOCX_ENV])
    if baseline_path.stat().st_size > _MAX_BASELINE_BYTES:
        raise ValueError("configuration baseline JSON exceeds the production size limit")
    raw = json.loads(baseline_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("configuration baseline JSON MUST be an object")
    baseline = baseline_from_dict(raw)
    baseline_source = JsonFileConfigurationBaselineSource(baseline_path)
    document = configuration_baseline_document(baseline, document_path=document_path)
    observation = AzureArgConfigurationObservationSource(
        identity=identity,
        http_client=http_client,
        config=AzureConfigurationObservationConfig(
            scope_ref=baseline.scope,
            subscription_scope=subscription_id,
            resource_group=resource_group,
        ),
    )
    return ConfigurationDriftChatTools(
        baseline_source=baseline_source,
        service=ConfigurationDriftService(
            baseline_source=baseline_source,
            observation_source=observation,
            expected_version=baseline.version,
            expected_sha256=baseline.sha256,
            expected_scope=baseline.scope,
            knowledge_source=PinnedConfigurationBaselineKnowledgeSource(document),
        ),
        document_name=document.source_ref,
        baseline_registry=ConfigurationBaselineRegistry(
            (RegisteredConfigurationBaseline(baseline, ConfigurationBaselineStatus.ACTIVE),)
        ),
    )


def build_production_configuration_review(
    *,
    context: ConfigurationDriftChatTools,
    state_store: StateStore,
    dsn: str,
    statement_timeout_ms: int,
    connect_timeout_s: int,
) -> ProductionConfigurationReview:
    """Build the evidence-run to independently reviewed schedule lifecycle."""

    blueprints = AutomationBlueprintReviewService(
        store=PostgresAutomationBlueprintStore(
            config=PostgresAutomationBlueprintStoreConfig(
                dsn=dsn,
                statement_timeout_ms=statement_timeout_ms,
                connect_timeout_s=connect_timeout_s,
            )
        ),
        authorizer=_BlueprintAuthorizer(),
        audit=_StateStoreBlueprintAudit(state_store),
        schedule_command=CreateScheduledTaskCommand(
            store=PostgresScheduleStore(
                config=PostgresScheduleStoreConfig(
                    dsn=dsn,
                    statement_timeout_ms=statement_timeout_ms,
                    connect_timeout_s=connect_timeout_s,
                )
            )
        ),
    )
    campaigns = ConfigurationReviewCampaignService(
        StateStoreConfigurationReviewCampaignStore(state_store),
        StateStoreConfigurationDriftReportStore(state_store),
    )
    return ProductionConfigurationReview(
        runtime=ConfigurationReviewRuntime(
            baseline_source=context.baseline_source,
            drift_service=context.service,
            campaigns=campaigns,
            blueprints=blueprints,
        ),
        blueprints=blueprints,
    )


def _absolute_file(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or not path.is_file():
        raise ValueError("production configuration baseline paths MUST be absolute files")
    return path


__all__ = [
    "ProductionConfigurationReview",
    "build_production_configuration_drift_context",
    "build_production_configuration_review",
]
