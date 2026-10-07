"""One-shot governed WAF and CAF shadow assessment from the private runner."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from fdai.core.framework_assessment import (
    FrameworkApplicabilityDecision,
    FrameworkApplicabilityStatus,
    FrameworkAssessmentProfile,
    FrameworkAssessmentRequest,
    FrameworkAssessmentResult,
    FrameworkAssessmentRuntime,
    FrameworkEvidenceReceipt,
    FrameworkOwnerBinding,
    FrameworkRuleActivationPin,
    FrameworkSatisfactionStatus,
)
from fdai.core.rule_activation.ledger import StateStoreRuleActivationLedger
from fdai.delivery.framework_rule_evidence_source import (
    WorkloadRuleEvidence,
    WorkloadRuleEvidenceStatus,
    load_workload_rule_evidence,
)
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_wara_scope import (
    PostgresWaraScopeSource,
    PostgresWaraScopeSourceConfig,
    WaraResolvedScope,
)
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.schema.framework_assessment import (
    FrameworkAssessmentCatalog,
    FrameworkEvidenceRole,
    FrameworkProcessPhase,
    FrameworkScopeKind,
    canonical_digest,
    load_framework_assessment_catalog,
)

_LOGGER = logging.getLogger("fdai.framework_assessment")
_REPO_ROOT = repo_asset_root()
_CATALOG_ROOT = _REPO_ROOT / "rule-catalog/framework-assessments/generated"


class FrameworkAssessmentJobConfigurationError(ValueError):
    """Required live shadow bindings are absent or malformed."""


@dataclass(frozen=True, slots=True)
class FrameworkAssessmentJobSettings:
    """Validated private-runner inputs without repository-owned tenant values."""

    dsn: str
    workload_id: str
    inventory_freshness_seconds: int
    maximum_resources: int
    tenant_id: str
    subscription_id: str
    hierarchy_path: Path
    reviewer_identity: str

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.dsn,
                self.workload_id,
                self.tenant_id,
                self.subscription_id,
                self.reviewer_identity,
            )
        ):
            raise FrameworkAssessmentJobConfigurationError(
                "framework live context and reviewer identity MUST be non-empty"
            )
        if not 1 <= self.inventory_freshness_seconds <= 604_800:
            raise FrameworkAssessmentJobConfigurationError(
                "framework inventory freshness MUST be in [1, 604800]"
            )
        if not 1 <= self.maximum_resources <= 1_000:
            raise FrameworkAssessmentJobConfigurationError(
                "framework maximum resources MUST be in [1, 1000]"
            )
        if not self.hierarchy_path.is_file():
            raise FrameworkAssessmentJobConfigurationError(
                "framework hierarchy evidence file is unavailable"
            )

    @classmethod
    def from_environ(
        cls,
        environ: Mapping[str, str],
    ) -> FrameworkAssessmentJobSettings:
        hierarchy_path = Path(_required(environ, "FDAI_CAF_HIERARCHY_EVIDENCE_PATH"))
        workload_ids = _json_string_array(_required(environ, "FDAI_WARA_WORKLOAD_IDS_JSON"))
        if len(workload_ids) != 1:
            raise FrameworkAssessmentJobConfigurationError(
                "framework assessment requires exactly one workload"
            )
        return cls(
            dsn=_required(environ, "FDAI_FRAMEWORK_ASSESSMENT_DSN").replace(
                "postgresql+psycopg://",
                "postgresql://",
                1,
            ),
            workload_id=workload_ids[0],
            inventory_freshness_seconds=_bounded_integer(
                environ.get("FDAI_WARA_INVENTORY_FRESHNESS_SECONDS", ""),
                default=86_400,
                minimum=1,
                maximum=604_800,
            ),
            maximum_resources=_bounded_integer(
                environ.get("FDAI_WARA_MAX_RESOURCES", ""),
                default=1_000,
                minimum=1,
                maximum=1_000,
            ),
            tenant_id=_required(environ, "AZURE_TENANT_ID"),
            subscription_id=_required(environ, "AZURE_SUBSCRIPTION_ID"),
            hierarchy_path=hierarchy_path,
            reviewer_identity=_required(
                environ,
                "FDAI_FRAMEWORK_ASSESSMENT_REVIEWER",
            ),
        )


@dataclass(frozen=True, slots=True)
class FrameworkAssessmentTickReport:
    """Sanitized durable evidence summary for one WAF and CAF pass."""

    source_revision: str
    waf_result_digest: str
    caf_result_digest: str
    workload_resource_count: int
    waf_counts: Mapping[str, int]
    caf_counts: Mapping[str, int]
    rule_evidence_status: str = WorkloadRuleEvidenceStatus.NO_ACTIVATION.value
    rule_receipt_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "status": "completed",
            "mode": "shadow",
            "execution_authority": False,
            "publication_status": "not_requested_validation_only",
            "source_revision": self.source_revision,
            "waf_result_digest": self.waf_result_digest,
            "caf_result_digest": self.caf_result_digest,
            "workload_resource_count": self.workload_resource_count,
            "waf_counts": dict(sorted(self.waf_counts.items())),
            "caf_counts": dict(sorted(self.caf_counts.items())),
            "rule_evidence_status": self.rule_evidence_status,
            "rule_receipt_count": self.rule_receipt_count,
        }


class FrameworkAssessmentWriter(Protocol):
    async def assess(
        self,
        request: FrameworkAssessmentRequest,
    ) -> FrameworkAssessmentResult: ...


class _AuditOnlyFrameworkAssessmentService:
    """Persist a live validation receipt without claiming event publication."""

    def __init__(
        self,
        runtime: FrameworkAssessmentRuntime,
        state_store: PostgresStateStore,
    ) -> None:
        self._runtime = runtime
        self._state_store = state_store

    async def assess(
        self,
        request: FrameworkAssessmentRequest,
    ) -> FrameworkAssessmentResult:
        result = self._runtime.assess(request)
        await self._state_store.append_audit_entry(
            {
                "type": "framework_live_shadow_validation",
                "assessment_id": result.assessment_id,
                "framework_id": result.framework_id,
                "profile_digest": result.profile_digest,
                "scope_digest": result.scope_digest,
                "result_digest": result.result_digest,
                "execution_authority": False,
                "publication_status": "not_requested_validation_only",
                "recorded_at": result.recorded_at.isoformat(),
            }
        )
        return result


def _load_catalog(framework_id: str) -> FrameworkAssessmentCatalog:
    return load_framework_assessment_catalog(_CATALOG_ROOT / f"{framework_id}.json")


def _profile(
    catalog: FrameworkAssessmentCatalog,
    *,
    scope_digest: str,
    ontology_release: str,
    reviewer_identity: str,
    reviewed_at: datetime,
    inventory_generation: str | None = None,
    hierarchy_generation: str | None = None,
    rule_activation: FrameworkRuleActivationPin | None = None,
) -> FrameworkAssessmentProfile:
    decisions = tuple(
        FrameworkApplicabilityDecision(
            control_id=control.control_id,
            status=FrameworkApplicabilityStatus.APPLICABLE,
            requested_by=reviewer_identity,
            owner_slot=control.owner_slot,
            cadence_days=control.cadence_days,
        )
        for control in catalog.controls
    )
    owners = tuple(
        FrameworkOwnerBinding(
            control_id=control.control_id,
            owner_slot=control.owner_slot,
            owner_identity=reviewer_identity,
        )
        for control in catalog.controls
    )
    return FrameworkAssessmentProfile.create(
        profile_id=f"{catalog.framework_id}-live-shadow",
        framework_id=catalog.framework_id,
        framework_version=catalog.framework_version,
        catalog_digest=catalog.catalog_digest,
        scope_kind=catalog.framework_scope,
        scope_digest=scope_digest,
        ontology_release=ontology_release,
        applicability=decisions,
        owners=owners,
        reviewed_by=reviewer_identity,
        reviewed_at=reviewed_at,
        inventory_generation=inventory_generation,
        hierarchy_generation=hierarchy_generation,
        operating_model=(
            "deployment-platform-operating-model"
            if catalog.framework_scope is FrameworkScopeKind.CLOUD_ESTATE
            else None
        ),
        environment_classes=(
            ("development",) if catalog.framework_scope is FrameworkScopeKind.CLOUD_ESTATE else ()
        ),
        regulatory_context=(),
        rule_activation=rule_activation,
    )


def _waf_scope_digest(scope: WaraResolvedScope) -> str:
    return canonical_digest(
        {
            "workload_id": scope.workload_id,
            "resources": [
                {
                    "resource_id": item.provider_resource_id,
                    "provider_resource_type": item.provider_resource_type.casefold(),
                }
                for item in scope.resources
            ],
        }
    )


def _load_hierarchy_generation(path: Path) -> tuple[str, bool]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FrameworkAssessmentJobConfigurationError(
            "CAF hierarchy evidence MUST be valid JSON"
        ) from error
    if not isinstance(raw, dict) or not raw:
        raise FrameworkAssessmentJobConfigurationError(
            "CAF hierarchy evidence MUST be a non-empty JSON object"
        )
    data = raw.get("data")
    count = raw.get("count")
    total_records = raw.get("totalRecords")
    complete = (
        isinstance(data, list)
        and len(data) == 1
        and count == 1
        and total_records == 1
        and raw.get("resultTruncated") is False
        and not raw.get("$skipToken")
    )
    return canonical_digest(raw), complete


def _caf_hierarchy_evidence(
    catalog: FrameworkAssessmentCatalog,
    *,
    scope_digest: str,
    hierarchy_generation: str,
    hierarchy_complete: bool,
    observed_at: datetime,
) -> tuple[FrameworkEvidenceReceipt, ...]:
    target_ref = "estate-hierarchy-observation"
    receipts: list[FrameworkEvidenceReceipt] = []
    for control in catalog.controls:
        for requirement in control.evidence:
            if requirement.source_ref != target_ref:
                continue
            if requirement.authoritative_producer is None:
                raise FrameworkAssessmentJobConfigurationError(
                    "CAF hierarchy evidence producer is blocked"
                )
            receipts.append(
                FrameworkEvidenceReceipt(
                    framework_id=catalog.framework_id,
                    control_id=control.control_id,
                    requirement_id=requirement.requirement_id,
                    evidence_ref=f"evidence://azure-hierarchy/{control.control_id}",
                    evidence_kind=requirement.kind.value,
                    producer=requirement.authoritative_producer,
                    source_identity="azure-management-read",
                    scope_digest=scope_digest,
                    observed_at=observed_at,
                    recorded_at=observed_at,
                    evidence_digest=hierarchy_generation,
                    freshness_ceiling_seconds=requirement.freshness_ceiling_seconds,
                    complete=hierarchy_complete,
                    truncated=not hierarchy_complete,
                    conflicting=False,
                    synthetic=False,
                    provider_error=(
                        None if hierarchy_complete else "hierarchy_observation_incomplete"
                    ),
                    outcome=(
                        FrameworkSatisfactionStatus.SATISFIED
                        if hierarchy_complete
                        else FrameworkSatisfactionStatus.UNKNOWN
                    ),
                    evidence_role=FrameworkEvidenceRole.DECISIVE,
                    process_phase=FrameworkProcessPhase.NONE,
                    hierarchy_generation=hierarchy_generation,
                )
            )
    if len(receipts) != 2:
        raise FrameworkAssessmentJobConfigurationError(
            "CAF hierarchy evidence MUST resolve exactly two reviewed requirements"
        )
    return tuple(
        sorted(
            receipts,
            key=lambda item: (item.control_id, item.requirement_id, item.evidence_ref),
        )
    )


async def execute_framework_assessment_tick(
    *,
    settings: FrameworkAssessmentJobSettings,
    scope: WaraResolvedScope,
    waf_service: FrameworkAssessmentWriter,
    caf_service: FrameworkAssessmentWriter,
    waf_catalog: FrameworkAssessmentCatalog,
    caf_catalog: FrameworkAssessmentCatalog,
    now: datetime,
    source_revision: str,
    rule_evidence: WorkloadRuleEvidence | None = None,
) -> FrameworkAssessmentTickReport:
    """Publish one exact-scope WAF result and one exact-estate CAF result.

    ``rule_evidence`` pins the Rule activation on the WAF profile and supplies one T0 Rule
    receipt per Rule requirement. Without it, Rule requirements stay ``unknown``.
    """

    if now.tzinfo is None:
        raise ValueError("framework assessment tick time MUST be timezone-aware")
    hierarchy_generation, hierarchy_complete = _load_hierarchy_generation(settings.hierarchy_path)
    waf_scope_digest = _waf_scope_digest(scope)
    caf_scope_digest = canonical_digest(
        {
            "tenant_id": settings.tenant_id,
            "subscription_id": settings.subscription_id,
        }
    )
    waf_profile = _profile(
        waf_catalog,
        scope_digest=waf_scope_digest,
        ontology_release=scope.ontology_release,
        reviewer_identity=settings.reviewer_identity,
        reviewed_at=now,
        inventory_generation=scope.inventory_generation,
        rule_activation=rule_evidence.pin if rule_evidence is not None else None,
    )
    caf_profile = _profile(
        caf_catalog,
        scope_digest=caf_scope_digest,
        ontology_release=scope.ontology_release,
        reviewer_identity=settings.reviewer_identity,
        reviewed_at=now,
        hierarchy_generation=hierarchy_generation,
    )
    waf_result = await waf_service.assess(
        FrameworkAssessmentRequest(
            assessment_id=_assessment_id(
                "waf",
                source_revision=source_revision,
                profile_digest=waf_profile.profile_digest,
            ),
            profile=waf_profile,
            evaluated_at=now,
            recorded_at=now,
            evidence=rule_evidence.receipts if rule_evidence is not None else (),
        )
    )
    caf_result = await caf_service.assess(
        FrameworkAssessmentRequest(
            assessment_id=_assessment_id(
                "caf",
                source_revision=source_revision,
                profile_digest=caf_profile.profile_digest,
            ),
            profile=caf_profile,
            evaluated_at=now,
            recorded_at=now,
            evidence=_caf_hierarchy_evidence(
                caf_catalog,
                scope_digest=caf_scope_digest,
                hierarchy_generation=hierarchy_generation,
                hierarchy_complete=hierarchy_complete,
                observed_at=now,
            ),
        )
    )
    return FrameworkAssessmentTickReport(
        source_revision=source_revision,
        waf_result_digest=waf_result.result_digest,
        caf_result_digest=caf_result.result_digest,
        workload_resource_count=len(scope.resources),
        waf_counts=waf_result.aggregate_counts,
        caf_counts=caf_result.aggregate_counts,
        rule_evidence_status=(
            rule_evidence.status.value
            if rule_evidence is not None
            else WorkloadRuleEvidenceStatus.NO_ACTIVATION.value
        ),
        rule_receipt_count=len(rule_evidence.receipts) if rule_evidence is not None else 0,
    )


def _assessment_id(
    framework: str,
    *,
    source_revision: str,
    profile_digest: str,
) -> str:
    digest = canonical_digest(
        {
            "framework": framework,
            "profile_digest": profile_digest,
            "source_revision": source_revision,
        }
    ).removeprefix("sha256:")[:24]
    return f"framework-assessment:{framework}:{digest}"


async def run_once(
    environ: Mapping[str, str] | None = None,
) -> FrameworkAssessmentTickReport:
    """Compose private PostgreSQL evidence for one live shadow validation pass."""

    environment = os.environ if environ is None else environ
    settings = FrameworkAssessmentJobSettings.from_environ(environment)
    source_revision = _required(environment, "FDAI_SOURCE_REVISION")
    now = datetime.now(tz=UTC)
    scope = await PostgresWaraScopeSource(
        config=PostgresWaraScopeSourceConfig(
            dsn=settings.dsn,
            freshness_budget_seconds=settings.inventory_freshness_seconds,
            maximum_resources=settings.maximum_resources,
        )
    ).resolve(settings.workload_id, now=now)
    waf_catalog = _load_catalog("azure-waf")
    caf_catalog = _load_catalog("azure-caf")
    state_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=settings.dsn))
    rule_evidence = await load_workload_rule_evidence(
        state_store=state_store,
        activation=await StateStoreRuleActivationLedger(store=state_store).current_generation(),
        scope=scope,
        catalog=waf_catalog,
        profile_scope_digest=_waf_scope_digest(scope),
        evaluated_at=now,
        source_identity="forseti-baseline-evaluation",
    )
    return await execute_framework_assessment_tick(
        settings=settings,
        scope=scope,
        waf_service=_AuditOnlyFrameworkAssessmentService(
            FrameworkAssessmentRuntime(waf_catalog),
            state_store,
        ),
        caf_service=_AuditOnlyFrameworkAssessmentService(
            FrameworkAssessmentRuntime(caf_catalog),
            state_store,
        ),
        waf_catalog=waf_catalog,
        caf_catalog=caf_catalog,
        now=now,
        source_revision=source_revision,
        rule_evidence=rule_evidence,
    )


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise FrameworkAssessmentJobConfigurationError(f"{name} is required")
    return value


def _json_string_array(raw: str) -> tuple[str, ...]:
    try:
        value: object = json.loads(raw)
    except json.JSONDecodeError as error:
        raise FrameworkAssessmentJobConfigurationError(
            "FDAI_WARA_WORKLOAD_IDS_JSON MUST be a JSON string array"
        ) from error
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise FrameworkAssessmentJobConfigurationError(
            "FDAI_WARA_WORKLOAD_IDS_JSON MUST be a JSON string array"
        )
    normalized = tuple(sorted(item.strip() for item in value))
    if len(normalized) != len(set(normalized)):
        raise FrameworkAssessmentJobConfigurationError(
            "FDAI_WARA_WORKLOAD_IDS_JSON MUST contain unique values"
        )
    return normalized


def _bounded_integer(
    raw: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise FrameworkAssessmentJobConfigurationError(
            "framework assessment bound MUST be an integer"
        ) from error
    if not minimum <= value <= maximum:
        raise FrameworkAssessmentJobConfigurationError(
            f"framework assessment bound MUST be in [{minimum}, {maximum}]"
        )
    return value


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    try:
        report = asyncio.run(run_once())
    except Exception:
        _LOGGER.exception("framework_assessment_failed")
        return 1
    print(json.dumps(report.to_dict(), separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
