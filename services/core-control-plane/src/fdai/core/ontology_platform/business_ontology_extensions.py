"""Business ontology extensions: CostAllocation, SLA, polymorphic interfaces, and Q&A."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from fdai.core.ontology_platform.interfaces import (
    CompiledInterfaceCatalog,
    compile_interfaces,
)
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog
from fdai.shared.contracts.models import (
    CeilingRole,
    LinkCardinality,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyInterfaceType,
    OntologyLinkType,
    OntologyObjectType,
    OntologyProvenance,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.contracts.models import (
    OntologyInterfaceImplementation as InterfaceImplementation,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyInstanceStore


def _sha256(seed: str) -> str:
    return f"sha256:{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"


def _prov(ref: str, digest_seed: str) -> OntologyProvenance:
    return OntologyProvenance(
        source_url="https://github.com/dotnetpower/fdai",
        resolved_ref=ref,
        content_hash=_sha256(digest_seed),
        license="MIT",
        retrieved_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


BILINGUAL_OBJECT_QUERY_TERMS: Mapping[str, tuple[str, ...]] = {
    "AccessGrant": ("access grant", "권한 부여", "액세스 승인"),
    "AccessGrantRequest": ("access grant request", "권한 요청", "액세스 요청"),
    "ActionOption": ("action option", "candidate option", "조치 옵션", "대안 옵션"),
    "ActionRun": ("action run", "execution run", "조치 실행", "실행 이력"),
    "ActionType": ("action type", "remediation action", "조치 유형", "액션 타입"),
    "Agent": ("agent", "pantheon agent", "에이전트", "판테온 에이전트"),
    "Approval": ("approval", "human approval", "승인", "인간 승인"),
    "ArchitectureConstraint": ("architecture constraint", "arb constraint", "아키텍처 제약"),
    "AuthorizationCapability": ("authorization capability", "인가 역량", "권한 기능"),
    "AuthorizationDecision": ("authorization decision", "인가 결정", "권한 판정"),
    "AuthorizationObservation": ("authorization observation", "권한 관측"),
    "AuthorizationPolicyAssignment": ("policy assignment", "정책 할당"),
    "AuthorizationRequirement": ("authorization requirement", "권한 요구사항"),
    "BenchmarkValidation": ("benchmark validation", "벤치마크 검증"),
    "BriefingRun": ("briefing run", "브리핑 실행", "보고서 생성"),
    "BriefingSubscription": ("briefing subscription", "브리핑 구독"),
    "Budget": ("budget", "service budget", "예산", "서비스 예산", "비용 한도"),
    "BusinessCapability": ("business capability", "비즈니스 역량", "사업 역량"),
    "BusinessService": ("business service", "business services", "비즈니스 서비스", "서비스"),
    "CapacityForecast": ("capacity forecast", "용량 예측"),
    "CapacityGraduationRecommendation": ("capacity graduation", "용량 졸업 권고"),
    "CausalHypothesis": ("causal hypothesis", "root cause hypothesis", "인과 가설", "원인 가설"),
    "Change": ("change", "deployment change", "변경", "배포 변경"),
    "ChangeSummary": ("change summary", "변경 요약"),
    "ChangeWindow": ("change window", "maintenance window", "변경 윈도우", "점검 시간"),
    "ConfigurationBaseline": ("configuration baseline", "구성 베이스라인"),
    "ConfigurationDriftCheck": ("configuration drift check", "드리프트 점검"),
    "ConfigurationDriftEvidence": ("configuration drift evidence", "드리프트 증거"),
    "ConfigurationDriftFinding": ("configuration drift finding", "구성 드리프트 발견"),
    "ControlObjective": ("control objective", "통제 목표", "제어 목표"),
    "Conversation": ("conversation", "대화", "세션 대화"),
    "ConversationPolicy": ("conversation policy", "대화 정책"),
    "CostAllocation": ("cost allocation", "shared cost split", "비용 배부", "공유 비용 배분"),
    "CostAnomaly": ("cost anomaly", "spend spike", "비용 이상", "비용 급증"),
    "CostObjective": ("cost objective", "unit cost target", "비용 목표", "단위 비용 목표"),
    "CostObservation": ("cost observation", "spend observation", "비용 관측", "지출 측정"),
    "Decision": ("decision", "verdict", "의사결정", "판결"),
    "DecisionCase": ("decision case", "의사결정 케이스", "결정 사례"),
    "DiagnosticEvidence": ("diagnostic evidence", "진단 증거"),
    "DiagnosticFinding": ("diagnostic finding", "진단 결과"),
    "DiagnosticMechanism": ("diagnostic mechanism", "진단 메커니즘"),
    "Environment": ("environment", "operating environment", "운영 환경", "배포 환경"),
    "EquivalenceValidationReceipt": ("equivalence receipt", "동치 검증 영수증"),
    "EvidenceArtifact": ("evidence artifact", "증거 아티팩트"),
    "EvidenceConflict": ("evidence conflict", "증거 충돌"),
    "ExecutionProfile": ("execution profile", "실행 프로파일"),
    "ExpectedEffect": ("expected effect", "predicted effect", "기대 효과", "예상 효과"),
    "Experiment": ("chaos experiment", "experiment", "카오스 실험", "실험"),
    "ExternalSlaContract": (
        "external sla",
        "sla contract",
        "외부 SLA",
        "SLA 계약",
        "에러 버짓 계약",
    ),
    "Finding": ("finding", "policy finding", "발견 사항", "정책 위반"),
    "Forecast": ("forecast", "prediction", "예측", "전망"),
    "Framework": ("compliance framework", "프레임워크", "규정 프레임워크"),
    "FrameworkControl": ("framework control", "프레임워크 통제항목"),
    "HandoffEscalation": ("handoff escalation", "에스컬레이션", "인수인계"),
    "ImpactEnvelope": ("impact envelope", "blast radius", "영향 범위", "폭발 반경"),
    "Incident": ("incident", "incidents", "인시던트", "장애"),
    "Issue": ("issue", "operational issue", "운영 이슈"),
    "Observation": ("observation", "metric sample", "관측치", "측정값"),
    "ObservedOutcome": ("observed outcome", "actual outcome", "관찰된 결과", "실제 효과"),
    "Ownership": ("ownership", "service owner", "소유권", "담당 조직"),
    "Pattern": ("operating pattern", "learned pattern", "운영 패턴", "학습 패턴"),
    "PolicyArtifact": ("policy artifact", "rego policy", "정책 아티팩트", "레고 정책"),
    "PostTurnReview": ("post turn review", "턴 사후 리뷰"),
    "Principal": ("principal", "actor identity", "주체", "인증 주체"),
    "Process": ("process", "workflow process", "프로세스", "워크플로 실행"),
    "Property": ("property", "resource property", "속성", "리소스 속성"),
    "ProspectiveLineage": ("prospective lineage", "사전 계보"),
    "ProviderPermissionSet": ("provider permission set", "프로바이더 권한 세트"),
    "PythonTask": ("python task", "파이썬 태스크"),
    "RecoveryObjective": ("recovery objective", "rto rpo", "복구 목표", "RTO RPO 목표"),
    "RecoveryPlan": ("recovery plan", "rollback plan", "복구 계획", "롤백 계획"),
    "Resource": ("resource", "resources", "리소스", "클라우드 리소스"),
    "ResourceClass": ("resource class", "리소스 클래스", "리소스 분류"),
    "ResourceType": ("resource type", "리소스 유형", "리소스 타입"),
    "ReviewCase": ("review case", "arb review", "아키텍처 리뷰 케이스"),
    "ReviewCheck": ("review check", "리뷰 체크"),
    "Rule": ("rule", "governance rule", "규칙", "거버넌스 규칙"),
    "RuleCandidate": ("rule candidate", "규칙 후보"),
    "RuleObjectiveBinding": ("rule objective binding", "규칙 목표 바인딩"),
    "SecurityEvent": ("security event", "보안 이벤트", "보안 신호"),
    "ServiceObjective": ("service objective", "slo", "서비스 목표", "SLO 목표"),
    "Signal": ("signal", "alert signal", "신호", "알림 신호"),
    "SignalType": ("signal type", "신호 유형"),
    "SizingRecommendation": ("sizing recommendation", "rightsizing", "적정 사이징 권고"),
    "Turn": ("conversation turn", "대화 턴"),
    "UserMemoryFact": ("user memory fact", "사용자 기억 사실"),
    "UserPreference": ("user preference", "사용자 선호도"),
    "VmTaskRun": ("vm task run", "가상머신 작업 실행"),
    "WorkflowBinding": ("workflow binding", "워크플로 바인딩"),
    "WorkflowDefinition": ("workflow definition", "워크플로 정의"),
    "Workload": ("workload", "workloads", "워크로드", "작업"),
}


def extended_business_object_types() -> tuple[OntologyObjectType, ...]:
    """Return the additive `CostAllocation` and `ExternalSlaContract` ObjectTypes."""

    s = PropertyDecl(type=PropertyType.STRING, required=True)
    n = PropertyDecl(type=PropertyType.NUMBER, required=True)
    dt = PropertyDecl(type=PropertyType.DATETIME, required=True)
    dt_opt = PropertyDecl(type=PropertyType.DATETIME, required=False)
    return (
        OntologyObjectType(
            schema_version="1.0.0",
            name="CostAllocation",
            version="1.0.0",
            key="id",
            description="Reviewed shared-resource cost split targeting a BusinessService.",
            query_terms=BILINGUAL_OBJECT_QUERY_TERMS["CostAllocation"],
            properties={
                "id": s,
                "source_resource_ref": s,
                "target_service_ref": s,
                "allocation_method": s,
                "allocation_ratio": n,
                "allocated_amount": n,
                "currency": s,
                "effective_from": dt,
                "effective_to": dt_opt,
                "source_ref": s,
            },
            provenance=_prov("object-type:CostAllocation@1.0.0", "CostAllocation@1.0.0"),
        ),
        OntologyObjectType(
            schema_version="1.0.0",
            name="ExternalSlaContract",
            version="1.0.0",
            key="id",
            description="Explicit external SLA commitment and error-budget burn ceiling.",
            query_terms=BILINGUAL_OBJECT_QUERY_TERMS["ExternalSlaContract"],
            properties={
                "id": s,
                "service_ref": s,
                "service_objective_ref": s,
                "contract_tier": s,
                "guaranteed_availability": n,
                "error_budget_burn_alert_threshold": n,
                "effective_from": dt,
                "effective_to": dt_opt,
                "source_ref": s,
            },
            provenance=_prov("object-type:ExternalSlaContract@1.0.0", "ExternalSlaContract@1.0.0"),
        ),
    )


def extended_business_link_types() -> tuple[OntologyLinkType, ...]:
    """Return additive LinkTypes for cost allocation and external SLA governance."""

    return (
        OntologyLinkType(
            schema_version="1.0.0",
            name="allocates_cost_to",
            version="1.0.0",
            from_type="CostAllocation",
            to_type="BusinessService",
            cardinality=LinkCardinality.MANY_TO_ONE,
            description="Bind a shared-resource cost allocation share to one BusinessService.",
            provenance=_prov("link-type:allocates_cost_to@1.0.0", "allocates_cost_to@1.0.0"),
        ),
        OntologyLinkType(
            schema_version="1.0.0",
            name="cost_allocation_sources_resource",
            version="1.0.0",
            from_type="CostAllocation",
            to_type="Resource",
            cardinality=LinkCardinality.MANY_TO_ONE,
            description="Identify the shared cloud Resource whose cost is allocated.",
            provenance=_prov(
                "link-type:cost_allocation_sources_resource@1.0.0",
                "cost_allocation_sources_resource@1.0.0",
            ),
        ),
        OntologyLinkType(
            schema_version="1.0.0",
            name="sla_governs_service_objective",
            version="1.0.0",
            from_type="ExternalSlaContract",
            to_type="ServiceObjective",
            cardinality=LinkCardinality.MANY_TO_ONE,
            description="Bind an external SLA contract to the internal ServiceObjective it bounds.",
            provenance=_prov(
                "link-type:sla_governs_service_objective@1.0.0",
                "sla_governs_service_objective@1.0.0",
            ),
        ),
    )


def enrich_object_types_with_bilingual_query_terms(
    object_types: Sequence[OntologyObjectType],
) -> tuple[OntologyObjectType, ...]:
    """Ensure every ObjectType carries reviewed English + Korean query_terms."""

    enriched: list[OntologyObjectType] = []
    for obj in object_types:
        terms = BILINGUAL_OBJECT_QUERY_TERMS.get(obj.name, ())
        merged = tuple(dict.fromkeys((*obj.query_terms, *terms)))
        if merged == obj.query_terms:
            enriched.append(obj)
        else:
            enriched.append(obj.model_copy(update={"query_terms": merged}))
    return tuple(enriched)


def build_expanded_interface_catalog(
    catalog: OntologyCatalog,
) -> CompiledInterfaceCatalog:
    """Compile all 7 interfaces across expanded polymorphic business ObjectTypes."""

    all_objects = (*catalog.object_types, *extended_business_object_types())
    relaxed_interfaces = tuple(
        OntologyInterfaceType(
            schema_version=iface.schema_version,
            name=iface.name,
            version=iface.version,
            description=iface.description,
            properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
            required_links=(),
            supported_actions=iface.supported_actions,
            extends=iface.extends,
            provenance=iface.provenance,
        )
        for iface in catalog.interface_types
    )
    by_iface: dict[str, tuple[str, ...]] = {
        "Identifiable": tuple(sorted(item.name for item in all_objects)),
        "Ownable": ("BusinessService", "ServiceObjective", "Workload"),
        "Operable": ("BusinessService", "Resource", "Workload"),
        "Observable": ("BusinessService", "Observation", "Resource", "Workload"),
        "Recoverable": ("BusinessService", "RecoveryObjective", "RecoveryPlan", "Workload"),
        "ObjectiveBound": (
            "BusinessService",
            "ExternalSlaContract",
            "RecoveryPlan",
            "ServiceObjective",
            "Workload",
        ),
        "CostBearing": (
            "Budget",
            "BusinessService",
            "CostAllocation",
            "CostObjective",
            "Resource",
            "Workload",
        ),
    }
    ifaces_by_object: dict[str, list[str]] = {}
    for iface_name, obj_names in by_iface.items():
        for obj_name in obj_names:
            ifaces_by_object.setdefault(obj_name, []).append(iface_name)
    expanded_impls = tuple(
        InterfaceImplementation(
            object_type=obj_name,
            interfaces=tuple(sorted(iface_list)),
        )
        for obj_name, iface_list in sorted(ifaces_by_object.items())
    )
    release = build_ontology_release(
        object_types=all_objects,
        link_types=(*catalog.link_types, *extended_business_link_types()),
        action_types=catalog.action_types,
        interface_types=relaxed_interfaces,
        function_types=catalog.function_types,
    )
    return compile_interfaces(
        interfaces=relaxed_interfaces,
        implementations=expanded_impls,
        object_types=all_objects,
        release=release,
    )


def extended_business_function_types() -> tuple[OntologyFunctionType, ...]:
    """Return 4 declarative business FunctionTypes for posture, burn, outcome, and what-if."""

    names = (
        "query.business_service_posture",
        "query.business_budget_burn",
        "query.decision_expected_vs_observed_outcome",
        "query.scenario_branch_what_if",
    )
    return tuple(
        OntologyFunctionType(
            name=name,
            version="1.0.0",
            kind=OntologyFunctionKind.QUERY,
            artifact_digest=_sha256(f"fn:{name}:1.0.0"),
            publisher="fdai",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            required_role=CeilingRole.READER,
        )
        for name in names
    )


@dataclass(frozen=True, slots=True)
class BusinessServiceClarificationResult:
    """Structured clarification offering candidate BusinessService identities and aliases."""

    resolved_service_id: str | None
    requires_clarification: bool
    candidate_services: tuple[tuple[str, str, tuple[str, ...]], ...]
    clarification_prompt: str | None


@dataclass(frozen=True, slots=True)
class ServiceBudgetBurnReport:
    """Evaluated service budget consumption including shared CostAllocation splits."""

    service_id: str
    budget_id: str
    currency: str
    budget_limit: Decimal
    direct_spend: Decimal
    allocated_shared_spend: Decimal
    total_spend: Decimal
    burn_ratio: float
    status: str


async def resolve_business_service_or_clarify(
    store: OntologyInstanceStore,
    *,
    utterance_target: str,
) -> BusinessServiceClarificationResult:
    """Resolve an exact service or return candidate-suggesting clarification (#10)."""

    normalized = utterance_target.strip().casefold()
    graph = await store.query_objects(
        object_types=("BusinessService",),
        limit=100,
        include_relationships=False,
    )
    candidates: list[tuple[str, str, tuple[str, ...]]] = []
    for obj in sorted(graph.objects, key=lambda item: item.id):
        name = str(obj.properties.get("name", obj.id))
        aliases = tuple(str(a) for a in obj.properties.get("aliases", ()))
        candidates.append((obj.id, name, aliases))
        if (
            obj.id.casefold() == normalized
            or name.casefold() == normalized
            or normalized in {a.casefold() for a in aliases}
        ):
            return BusinessServiceClarificationResult(
                resolved_service_id=obj.id,
                requires_clarification=False,
                candidate_services=(candidates[-1],),
                clarification_prompt=None,
            )
    options_text = ", ".join(f"{cid} ({cname})" for cid, cname, _ in candidates)
    return BusinessServiceClarificationResult(
        resolved_service_id=None,
        requires_clarification=True,
        candidate_services=tuple(candidates),
        clarification_prompt=f"Which BusinessService did you mean: {options_text}?",
    )


def evaluate_service_budget_burn(
    *,
    service_id: str,
    budget_id: str,
    budget_limit: Decimal,
    direct_spend: Decimal,
    allocated_shared_spend: Decimal,
    currency: str = "USD",
) -> ServiceBudgetBurnReport:
    """Compute service budget burn combining direct spend and CostAllocation splits (#2, #6)."""

    total = direct_spend + allocated_shared_spend
    ratio = round(float(total / budget_limit), 4) if budget_limit > 0 else 0.0
    status = "breached" if ratio > 1.0 else ("warning" if ratio >= 0.85 else "within_budget")
    return ServiceBudgetBurnReport(
        service_id=service_id,
        budget_id=budget_id,
        currency=currency,
        budget_limit=budget_limit,
        direct_spend=direct_spend,
        allocated_shared_spend=allocated_shared_spend,
        total_spend=total,
        burn_ratio=ratio,
        status=status,
    )
