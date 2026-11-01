"""Azure observation adapters for WAF and CAF assessment evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from fdai.core.framework_assessment.models import (
    FrameworkEvidenceReceipt,
    FrameworkSatisfactionStatus,
)
from fdai.rule_catalog.schema.framework_assessment import (
    FrameworkAssessmentCatalog,
    FrameworkEvidenceRole,
    FrameworkProcessPhase,
    FrameworkScopeKind,
    canonical_digest,
)
from fdai.shared.providers.framework_assessment import (
    FrameworkObservationRequest,
    FrameworkProviderObservation,
)


class WafExternalSource(StrEnum):
    WELL_ARCHITECTED_REVIEW = "well_architected_review"
    AZURE_ADVISOR = "azure_advisor"
    DEFENDER_SECURE_SCORE = "defender_secure_score"


class AzureAdvisorPillar(StrEnum):
    RELIABILITY = "reliability"
    SECURITY = "security"
    PERFORMANCE_EFFICIENCY = "performance-efficiency"
    COST_OPTIMIZATION = "cost-optimization"
    OPERATIONAL_EXCELLENCE = "operational-excellence"


class AzureAdvisorImpact(StrEnum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


_ADVISOR_CATEGORY_TO_PILLAR: dict[str, AzureAdvisorPillar] = {
    "highavailability": AzureAdvisorPillar.RELIABILITY,
    "reliability": AzureAdvisorPillar.RELIABILITY,
    "security": AzureAdvisorPillar.SECURITY,
    "performance": AzureAdvisorPillar.PERFORMANCE_EFFICIENCY,
    "performanceefficiency": AzureAdvisorPillar.PERFORMANCE_EFFICIENCY,
    "performance-efficiency": AzureAdvisorPillar.PERFORMANCE_EFFICIENCY,
    "cost": AzureAdvisorPillar.COST_OPTIMIZATION,
    "costoptimization": AzureAdvisorPillar.COST_OPTIMIZATION,
    "cost-optimization": AzureAdvisorPillar.COST_OPTIMIZATION,
    "operationalexcellence": AzureAdvisorPillar.OPERATIONAL_EXCELLENCE,
    "operational-excellence": AzureAdvisorPillar.OPERATIONAL_EXCELLENCE,
}

_ADVISOR_IMPACT_ALIASES: dict[str, AzureAdvisorImpact] = {
    "high": AzureAdvisorImpact.HIGH,
    "medium": AzureAdvisorImpact.MEDIUM,
    "low": AzureAdvisorImpact.LOW,
}


@dataclass(frozen=True, slots=True)
class AzureAdvisorRecommendation:
    """Normalized Azure Advisor recommendation from ARG AdvisorResources or Advisor REST API."""

    recommendation_id: str
    recommendation_type_id: str
    category: str
    waf_pillar: AzureAdvisorPillar
    impact: AzureAdvisorImpact
    impacted_field: str
    impacted_value: str
    problem: str
    solution: str
    last_updated: datetime | None = None
    extended_properties: Mapping[str, str] = ()  # type: ignore[assignment]

    def __post_init__(self) -> None:
        for label, value in (
            ("advisor recommendation_id", self.recommendation_id),
            ("advisor recommendation_type_id", self.recommendation_type_id),
            ("advisor category", self.category),
            ("advisor impacted_field", self.impacted_field),
            ("advisor impacted_value", self.impacted_value),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} MUST be a non-empty string")
        if not isinstance(self.waf_pillar, AzureAdvisorPillar):
            raise ValueError("advisor waf_pillar MUST be an AzureAdvisorPillar")
        if not isinstance(self.impact, AzureAdvisorImpact):
            raise ValueError("advisor impact MUST be an AzureAdvisorImpact")
        if self.last_updated is not None and (
            not isinstance(self.last_updated, datetime) or self.last_updated.tzinfo is None
        ):
            raise ValueError("advisor last_updated MUST be timezone-aware when provided")
        if isinstance(self.extended_properties, Mapping):
            normalized_ext = {
                str(k).strip(): str(v).strip()
                for k, v in sorted(self.extended_properties.items(), key=lambda item: str(item[0]))
                if str(k).strip()
            }
        else:
            normalized_ext = {}
        object.__setattr__(self, "extended_properties", normalized_ext)

    def to_dict(self) -> dict[str, object]:
        return {
            "recommendation_id": self.recommendation_id,
            "recommendation_type_id": self.recommendation_type_id,
            "category": self.category,
            "waf_pillar": self.waf_pillar.value,
            "impact": self.impact.value,
            "impacted_field": self.impacted_field,
            "impacted_value": self.impacted_value,
            "problem": self.problem,
            "solution": self.solution,
            "last_updated": (
                self.last_updated.astimezone(UTC).isoformat()
                if self.last_updated is not None
                else None
            ),
            "extended_properties": dict(self.extended_properties),
        }


def _parse_iso_datetime(raw: object) -> datetime | None:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo is not None else raw.replace(tzinfo=UTC)
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = raw.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def normalize_azure_advisor_recommendation(
    row: Mapping[str, object],
) -> AzureAdvisorRecommendation:
    """Normalize an ARG AdvisorResources row or Microsoft.Advisor/recommendations REST object."""
    if not isinstance(row, Mapping):
        raise ValueError("advisor recommendation row MUST be a mapping")
    raw_type = str(row.get("type") or "microsoft.advisor/recommendations").strip().lower()
    if raw_type and raw_type != "microsoft.advisor/recommendations":
        raise ValueError(f"unsupported advisor resource type: {raw_type}")
    props_obj = row.get("properties")
    props: Mapping[str, object] = props_obj if isinstance(props_obj, Mapping) else row

    recommendation_id = str(row.get("id") or props.get("id") or "").strip().lower()
    recommendation_type_id = str(
        props.get("recommendationTypeId")
        or row.get("recommendationTypeId")
        or row.get("name")
        or ""
    ).strip()
    category = str(props.get("category") or row.get("category") or "").strip()
    pillar_key = category.lower().replace("_", "").replace(" ", "")
    pillar = _ADVISOR_CATEGORY_TO_PILLAR.get(pillar_key) or _ADVISOR_CATEGORY_TO_PILLAR.get(
        category.lower()
    )
    if pillar is None:
        raise ValueError(f"unsupported Azure Advisor category: {category!r}")

    impact_raw = str(props.get("impact") or row.get("impact") or "Medium").strip()
    impact = _ADVISOR_IMPACT_ALIASES.get(impact_raw.lower())
    if impact is None:
        raise ValueError(f"unsupported Azure Advisor impact: {impact_raw!r}")

    impacted_field = str(
        props.get("impactedField")
        or row.get("impactedField")
        or "Microsoft.Resources/subscriptions"
    ).strip()
    impacted_value = str(
        props.get("impactedValue")
        or row.get("impactedValue")
        or row.get("subscriptionId")
        or recommendation_id
    ).strip()

    short_desc_obj = props.get("shortDescription") or row.get("shortDescription")
    short_desc = short_desc_obj if isinstance(short_desc_obj, Mapping) else {}
    problem = str(
        short_desc.get("problem") or props.get("problem") or row.get("problem") or ""
    ).strip()
    solution = str(
        short_desc.get("solution") or props.get("solution") or row.get("solution") or ""
    ).strip()
    last_updated = _parse_iso_datetime(props.get("lastUpdated") or row.get("lastUpdated"))

    ext_obj = props.get("extendedProperties") or row.get("extendedProperties")
    ext_props: dict[str, str] = {}
    if isinstance(ext_obj, Mapping):
        for k, v in ext_obj.items():
            if v is not None and str(k).strip():
                ext_props[str(k).strip()] = str(v).strip()

    return AzureAdvisorRecommendation(
        recommendation_id=recommendation_id,
        recommendation_type_id=recommendation_type_id,
        category=category,
        waf_pillar=pillar,
        impact=impact,
        impacted_field=impacted_field,
        impacted_value=impacted_value,
        problem=problem,
        solution=solution,
        last_updated=last_updated,
        extended_properties=ext_props,
    )


@dataclass(frozen=True, slots=True)
class WafExternalAssessmentArtifact:
    source: WafExternalSource
    source_identity: str
    scope_digest: str
    control_ids: tuple[str, ...]
    observed_at: datetime
    recorded_at: datetime
    evidence_digest: str
    inventory_generation: str
    complete: bool
    truncated: bool
    conflicting: bool
    synthetic: bool
    provider_error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, WafExternalSource):
            raise ValueError("WAF external artifact source MUST be a WafExternalSource")
        if not self.source_identity.strip() or not self.inventory_generation.strip():
            raise ValueError("WAF external artifact requires source and inventory identities")
        if not self.control_ids or self.control_ids != tuple(sorted(set(self.control_ids))):
            raise ValueError(
                "WAF external artifact controls MUST be non-empty, unique, and ordered"
            )
        if self.observed_at.tzinfo is None or self.recorded_at.tzinfo is None:
            raise ValueError("WAF external artifact timestamps MUST be timezone-aware")
        if self.recorded_at < self.observed_at:
            raise ValueError("WAF external artifact recorded_at MUST follow observed_at")
        for flag_name, flag_val in (
            ("complete", self.complete),
            ("truncated", self.truncated),
            ("conflicting", self.conflicting),
            ("synthetic", self.synthetic),
        ):
            if type(flag_val) is not bool:
                raise ValueError(f"WAF external artifact {flag_name} MUST be a boolean")
        if self.provider_error is not None and not self.provider_error.strip():
            raise ValueError("WAF external artifact provider_error MUST be non-empty when set")


def build_azure_advisor_supporting_artifact(
    catalog: FrameworkAssessmentCatalog,
    recommendations: Sequence[Mapping[str, object] | AzureAdvisorRecommendation],
    *,
    source_identity: str = "azure-advisor",
    scope_digest: str,
    inventory_generation: str,
    observed_at: datetime,
    recorded_at: datetime,
    complete: bool = True,
    truncated: bool = False,
    conflicting: bool = False,
    synthetic: bool = False,
    provider_error: str | None = None,
) -> WafExternalAssessmentArtifact:
    """Build a supporting-only WAF external artifact from Azure Advisor rows."""
    if catalog.framework_scope is not FrameworkScopeKind.WORKLOAD:
        raise ValueError("Azure Advisor supporting artifact requires a workload WAF catalog")
    normalized_recs = tuple(
        item
        if isinstance(item, AzureAdvisorRecommendation)
        else normalize_azure_advisor_recommendation(item)
        for item in recommendations
    )
    pillars = {rec.waf_pillar.value for rec in normalized_recs}
    matched_controls = tuple(
        sorted(
            {
                control.control_id
                for control in catalog.controls
                if not pillars or control.area in pillars
            }
        )
    )
    if not matched_controls:
        matched_controls = tuple(sorted({control.control_id for control in catalog.controls[:1]}))
    digest_payload = {
        "source": WafExternalSource.AZURE_ADVISOR.value,
        "source_identity": source_identity.strip(),
        "scope_digest": scope_digest,
        "inventory_generation": inventory_generation,
        "recommendations": [
            rec.to_dict()
            for rec in sorted(
                normalized_recs,
                key=lambda item: (item.recommendation_id, item.recommendation_type_id),
            )
        ],
    }
    return WafExternalAssessmentArtifact(
        source=WafExternalSource.AZURE_ADVISOR,
        source_identity=source_identity.strip(),
        scope_digest=scope_digest,
        control_ids=matched_controls,
        observed_at=observed_at,
        recorded_at=recorded_at,
        evidence_digest=canonical_digest(digest_payload),
        inventory_generation=inventory_generation,
        complete=complete,
        truncated=truncated,
        conflicting=conflicting,
        synthetic=synthetic,
        provider_error=provider_error,
    )


class AzureFrameworkEvidenceAdapter:
    """Convert exact Azure observations into catalog-bound decisive receipts."""

    def __init__(self, catalog: FrameworkAssessmentCatalog) -> None:
        self._catalog = catalog

    def to_receipts(
        self,
        request: FrameworkObservationRequest,
        observations: tuple[FrameworkProviderObservation, ...],
    ) -> tuple[FrameworkEvidenceReceipt, ...]:
        if (
            request.framework_id != self._catalog.framework_id
            or request.catalog_digest != self._catalog.catalog_digest
        ):
            raise ValueError("Azure framework observation request does not match the catalog")
        if len(observations) > request.maximum_observations:
            raise ValueError("Azure framework observations exceed the request bound")
        control_by_id = {item.control_id: item for item in self._catalog.controls}
        receipts: list[FrameworkEvidenceReceipt] = []
        for observation in observations:
            control = control_by_id.get(observation.control_id)
            if control is None or observation.control_id not in request.control_ids:
                raise ValueError("Azure framework observation references an out-of-scope control")
            matches = tuple(
                item
                for item in control.evidence
                if item.source_ref == observation.requirement_ref
                and item.kind.value == observation.evidence_kind
            )
            if len(matches) != 1:
                raise ValueError(
                    "Azure framework observation does not resolve one evidence contract"
                )
            requirement = matches[0]
            if observation.producer != requirement.authoritative_producer:
                raise ValueError("Azure framework observation producer is not authoritative")
            receipts.append(
                FrameworkEvidenceReceipt(
                    framework_id=self._catalog.framework_id,
                    control_id=observation.control_id,
                    requirement_id=requirement.requirement_id,
                    evidence_ref=observation.evidence_ref,
                    evidence_kind=observation.evidence_kind,
                    producer=observation.producer,
                    source_identity=observation.source_identity,
                    scope_digest=request.scope_digest,
                    observed_at=observation.observed_at,
                    recorded_at=observation.recorded_at,
                    evidence_digest=observation.evidence_digest,
                    freshness_ceiling_seconds=requirement.freshness_ceiling_seconds,
                    complete=observation.complete,
                    truncated=observation.truncated,
                    conflicting=observation.conflicting,
                    synthetic=observation.synthetic,
                    provider_error=observation.provider_error,
                    outcome=FrameworkSatisfactionStatus(observation.outcome.value),
                    evidence_role=requirement.evidence_role,
                    process_phase=requirement.process_phase,
                    inventory_generation=request.inventory_generation,
                    hierarchy_generation=request.hierarchy_generation,
                )
            )
        keys = tuple((item.control_id, item.requirement_id, item.evidence_ref) for item in receipts)
        if len(keys) != len(set(keys)):
            raise ValueError("Azure framework observations contain duplicate evidence")
        return tuple(sorted(receipts, key=lambda item: (item.control_id, item.requirement_id)))


class AzureWafSupportingEvidenceAdapter:
    """Preserve external WAF limitations without granting satisfaction authority."""

    def __init__(self, catalog: FrameworkAssessmentCatalog) -> None:
        if catalog.framework_id != "azure-waf":
            raise ValueError("external WAF evidence requires the azure-waf catalog")
        self._control_ids = {item.control_id for item in catalog.controls}

    def to_receipts(
        self,
        artifact: WafExternalAssessmentArtifact,
    ) -> tuple[FrameworkEvidenceReceipt, ...]:
        if not set(artifact.control_ids).issubset(self._control_ids):
            raise ValueError("external WAF artifact references an unknown control")
        limitations: list[str] = ["supporting_evidence_only"]
        if not artifact.complete:
            limitations.append("evidence_incomplete")
        if artifact.truncated:
            limitations.append("evidence_truncated")
        if artifact.conflicting:
            limitations.append("evidence_conflicting")
        if artifact.synthetic:
            limitations.append("synthetic_evidence")
        if artifact.provider_error is not None:
            limitations.append("provider_error")
        ordered_limitations = tuple(sorted(set(limitations)))
        return tuple(
            FrameworkEvidenceReceipt(
                framework_id="azure-waf",
                control_id=control_id,
                requirement_id=f"supporting:{artifact.source.value}",
                evidence_ref=f"evidence://supporting/{artifact.source.value}/{control_id}",
                evidence_kind=artifact.source.value,
                producer=f"azure-{artifact.source.value.replace('_', '-')}",
                source_identity=artifact.source_identity,
                scope_digest=artifact.scope_digest,
                observed_at=artifact.observed_at,
                recorded_at=artifact.recorded_at,
                evidence_digest=artifact.evidence_digest,
                freshness_ceiling_seconds=86_400,
                complete=artifact.complete,
                truncated=artifact.truncated,
                conflicting=artifact.conflicting,
                synthetic=artifact.synthetic,
                provider_error=artifact.provider_error,
                outcome=FrameworkSatisfactionStatus.UNKNOWN,
                evidence_role=FrameworkEvidenceRole.SUPPORTING_ONLY,
                process_phase=FrameworkProcessPhase.NONE,
                inventory_generation=artifact.inventory_generation,
                limitations=ordered_limitations,
            )
            for control_id in artifact.control_ids
        )


__all__ = [
    "AzureAdvisorImpact",
    "AzureAdvisorPillar",
    "AzureAdvisorRecommendation",
    "AzureFrameworkEvidenceAdapter",
    "AzureWafSupportingEvidenceAdapter",
    "WafExternalAssessmentArtifact",
    "WafExternalSource",
    "build_azure_advisor_supporting_artifact",
    "normalize_azure_advisor_recommendation",
]
