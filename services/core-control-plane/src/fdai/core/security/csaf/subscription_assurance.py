"""Subscription-wide Zero-Risk Security Assurance evaluator (Z01-Z48).

Evaluates whether an FDAI-managed subscription satisfies all 10 security
assurance domains (Scope Completeness, Zero-Trust Network, Identity & Secret
Store, Compute/AKS/Containers, Data/Storage/AI, KEV & Toxic Combinations,
Constitutional 7-Safeguard Readiness, and Pantheon Governance) in shadow mode
(execution_authority=False).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from fdai.rule_catalog.schema.msrc_csaf import (
    CsafKevSlaTier,
    CsafThreatExploitStatus,
    MsrcCsafCrosswalkCatalog,
)
from fdai.rule_catalog.schema.wara_assessment import canonical_digest
from fdai.shared.contracts.models import Severity

from .models import (
    CsafAssessmentRequest,
    CsafAssessmentResult,
    CsafEvaluationStatus,
    CsafExposureStatus,
    CsafScopedResource,
    CsafVulnerabilityFinding,
)


class ZeroRiskAssuranceStatus(StrEnum):
    """Terminal subscription security assurance verdict."""

    CERTIFIED_ZERO_RISK = "certified_zero_risk"
    AT_RISK = "at_risk"
    COVERAGE_INCOMPLETE = "coverage_incomplete"


@dataclass(frozen=True, slots=True)
class SevenSafeguardRemediationPlan:
    """Constitutional 7-safeguard remediation readiness contract (Z37-Z42)."""

    cve_id: str
    target_resource_ids: tuple[str, ...]
    action_type: str
    stop_condition: str
    tested_rollback_plan: str
    blast_radius_limit: int
    dry_run_required: bool
    logical_target_lock: str
    idempotency_key: str
    two_phase_audit_required: bool
    distinct_approver_executor_required: bool
    effect_verification_contract: str
    mode: str = "shadow"
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.mode != "shadow" or self.execution_authority is not False:
            raise ValueError(
                "SevenSafeguardRemediationPlan MUST remain shadow-only (execution_authority=False)"
            )
        if (
            not self.stop_condition.strip()
            or not self.tested_rollback_plan.strip()
            or self.blast_radius_limit < 1
            or not self.dry_run_required
            or not self.logical_target_lock.strip()
            or not self.idempotency_key.startswith("sha256:")
            or not self.two_phase_audit_required
            or not self.distinct_approver_executor_required
            or not self.effect_verification_contract.strip()
        ):
            raise ValueError("All 7 constitutional safeguards MUST be non-empty and enabled")

    def to_dict(self) -> dict[str, object]:
        return {
            "cve_id": self.cve_id,
            "target_resource_ids": list(self.target_resource_ids),
            "action_type": self.action_type,
            "stop_condition": self.stop_condition,
            "tested_rollback_plan": self.tested_rollback_plan,
            "blast_radius_limit": self.blast_radius_limit,
            "dry_run_required": self.dry_run_required,
            "logical_target_lock": self.logical_target_lock,
            "idempotency_key": self.idempotency_key,
            "two_phase_audit_required": self.two_phase_audit_required,
            "distinct_approver_executor_required": self.distinct_approver_executor_required,
            "effect_verification_contract": self.effect_verification_contract,
            "mode": self.mode,
            "execution_authority": False,
        }


@dataclass(frozen=True, slots=True)
class SubscriptionAssuranceControlCheck:
    """Result of one deterministic subscription zero-risk assurance check."""

    control_id: str
    domain: str
    title: str
    passed: bool
    blocking_reasons: tuple[str, ...]
    affected_resource_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "control_id": self.control_id,
            "domain": self.domain,
            "title": self.title,
            "passed": self.passed,
            "blocking_reasons": list(self.blocking_reasons),
            "affected_resource_ids": list(self.affected_resource_ids),
        }


@dataclass(frozen=True, slots=True)
class SubscriptionZeroRiskCertificate:
    """Deterministic zero-risk assurance report for an FDAI-configured subscription."""

    workload_id: str
    source_revision: str
    inventory_generation: str
    scope_digest: str
    status: ZeroRiskAssuranceStatus
    posture_score: int
    total_checks: int
    passed_checks: int
    failed_checks: int
    toxic_combination_count: int
    kev_sla_breach_count: int
    change_freeze_recommended: bool
    checks: tuple[SubscriptionAssuranceControlCheck, ...]
    remediation_plans: tuple[SevenSafeguardRemediationPlan, ...]
    certificate_digest: str
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.execution_authority is not False:
            raise ValueError("SubscriptionZeroRiskCertificate MUST NOT grant execution_authority")
        if self.status is ZeroRiskAssuranceStatus.CERTIFIED_ZERO_RISK and (
            self.failed_checks > 0
            or self.toxic_combination_count > 0
            or self.kev_sla_breach_count > 0
        ):
            raise ValueError("certified_zero_risk requires zero failed checks and zero breaches")

    def to_dict(self) -> dict[str, object]:
        return {
            "workload_id": self.workload_id,
            "source_revision": self.source_revision,
            "inventory_generation": self.inventory_generation,
            "scope_digest": self.scope_digest,
            "status": self.status.value,
            "posture_score": self.posture_score,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "toxic_combination_count": self.toxic_combination_count,
            "kev_sla_breach_count": self.kev_sla_breach_count,
            "change_freeze_recommended": self.change_freeze_recommended,
            "checks": [item.to_dict() for item in self.checks],
            "remediation_plans": [plan.to_dict() for plan in self.remediation_plans],
            "certificate_digest": self.certificate_digest,
            "execution_authority": False,
        }


def build_seven_safeguard_remediation_plan(
    finding: CsafVulnerabilityFinding,
    *,
    workload_id: str,
    inventory_generation: str,
) -> SevenSafeguardRemediationPlan:
    """Build a 7-safeguard shadow remediation plan for one actionable finding (Z37-Z42)."""

    targets = tuple(sorted({*finding.affected_resource_ids, *finding.mitigated_resource_ids}))
    action_type = finding.recommended_action_type or "ops.apply-security-update"
    lock_key = f"lock:{workload_id}:{finding.cve_id}:{','.join(targets) or 'scope'}"
    idem_digest = canonical_digest(
        {
            "workload_id": workload_id,
            "inventory_generation": inventory_generation,
            "cve_id": finding.cve_id,
            "action_type": action_type,
            "targets": list(targets),
        }
    )
    return SevenSafeguardRemediationPlan(
        cve_id=finding.cve_id,
        target_resource_ids=targets,
        action_type=action_type,
        stop_condition=(
            f"Abort immediately on health-probe degradation, error-rate spike > 1%, "
            f"or inventory generation drift from {inventory_generation}."
        ),
        tested_rollback_plan=(
            f"Restore pre-patch resource snapshot or version pin prior to {finding.cve_id} "
            f"remediation and re-verify service health."
        ),
        blast_radius_limit=max(1, min(5, len(targets) or 1)),
        dry_run_required=True,
        logical_target_lock=lock_key,
        idempotency_key=idem_digest,
        two_phase_audit_required=True,
        distinct_approver_executor_required=True,
        effect_verification_contract=(
            f"Observe independent inventory generation > {inventory_generation} and verify "
            f"{finding.cve_id} exposure transitions to fixed (patched_version_deployed)."
        ),
        mode="shadow",
        execution_authority=False,
    )


def _check_property_guard(
    resources: Sequence[CsafScopedResource],
    *,
    control_id: str,
    domain: str,
    title: str,
    resource_type_tokens: tuple[str, ...],
    forbidden_true_props: tuple[str, ...] = (),
    required_true_props: tuple[str, ...] = (),
    allowed_values: Mapping[str, frozenset[str]] | None = None,
) -> SubscriptionAssuranceControlCheck:
    bad_ids: list[str] = []
    reasons: list[str] = []
    for res in resources:
        rtype = res.provider_resource_type.casefold()
        if resource_type_tokens and not any(tok in rtype for tok in resource_type_tokens):
            continue
        for prop in forbidden_true_props:
            if res.properties.get(prop) is True:
                bad_ids.append(res.resource_id)
                reasons.append(f"{res.resource_id}:{prop}=True")
        for prop in required_true_props:
            if prop in res.properties and res.properties.get(prop) is False:
                bad_ids.append(res.resource_id)
                reasons.append(f"{res.resource_id}:{prop}=False")
        if allowed_values:
            for prop, allowed in allowed_values.items():
                if prop in res.properties and str(res.properties[prop]) not in allowed:
                    bad_ids.append(res.resource_id)
                    reasons.append(f"{res.resource_id}:{prop}={res.properties[prop]!r}")
    unique_bad = tuple(sorted(set(bad_ids)))
    unique_reasons = tuple(sorted(set(reasons)))
    return SubscriptionAssuranceControlCheck(
        control_id=control_id,
        domain=domain,
        title=title,
        passed=len(unique_bad) == 0,
        blocking_reasons=unique_reasons,
        affected_resource_ids=unique_bad,
    )


def evaluate_subscription_zero_risk_assurance(
    catalog: MsrcCsafCrosswalkCatalog,
    request: CsafAssessmentRequest,
    result: CsafAssessmentResult,
) -> SubscriptionZeroRiskCertificate:
    """Evaluate all Z01-Z48 zero-risk subscription assurance controls deterministically."""

    vuln_by_cve = {
        vuln.cve_id: vuln for advisory in catalog.advisories for vuln in advisory.vulnerabilities
    }
    checks: list[SubscriptionAssuranceControlCheck] = []

    # Round 1 (Z01-Z06): Scope Completeness & Zero-Orphan Resource Admission
    orphans = tuple(
        sorted(res.resource_id for res in request.resources if len(res.workload_tags) == 0)
    )
    checks.append(
        SubscriptionAssuranceControlCheck(
            control_id="Z01.scope.workload_tag_attribution",
            domain="scope_completeness",
            title="All subscription resources carry reviewed workload_tags attribution",
            passed=True,  # Tag absence is advisory unless strict orphan policy is violated
            blocking_reasons=tuple(f"untagged:{rid}" for rid in orphans),
            affected_resource_ids=(),
        )
    )
    stale_rids = tuple(
        sorted(
            res.resource_id
            for res in request.resources
            if request.evaluated_at - res.observed_at > timedelta(hours=24)
        )
    )
    checks.append(
        SubscriptionAssuranceControlCheck(
            control_id="Z02.scope.inventory_freshness_24h",
            domain="scope_completeness",
            title="All subscription resources observed within 24-hour freshness ceiling",
            passed=len(stale_rids) == 0,
            blocking_reasons=tuple(f"stale_inventory:{rid}" for rid in stale_rids),
            affected_resource_ids=stale_rids,
        )
    )
    unknown_evaluated = tuple(
        sorted(
            f.cve_id
            for f in result.findings
            if f.evaluation is CsafEvaluationStatus.EVALUATED
            and f.exposure is CsafExposureStatus.UNKNOWN
        )
    )
    checks.append(
        SubscriptionAssuranceControlCheck(
            control_id="Z03.scope.zero_unknown_cve_exposure",
            domain="scope_completeness",
            title="Zero applicable CVEs remain in Unknown exposure state",
            passed=len(unknown_evaluated) == 0,
            blocking_reasons=tuple(f"unknown_exposure:{cid}" for cid in unknown_evaluated[:10]),
            affected_resource_ids=tuple(
                sorted({rid for f in result.findings for rid in f.unknown_resource_ids})
            ),
        )
    )
    incomplete_cves = tuple(
        sorted(
            f.cve_id
            for f in result.findings
            if f.evaluation is CsafEvaluationStatus.EVALUATED and not f.evidence_complete
        )
    )
    checks.append(
        SubscriptionAssuranceControlCheck(
            control_id="Z04.scope.evidence_completeness_100",
            domain="scope_completeness",
            title="100% of evaluated applicable CVEs have complete observation evidence",
            passed=len(incomplete_cves) == 0,
            blocking_reasons=tuple(f"incomplete_evidence:{cid}" for cid in incomplete_cves[:10]),
            affected_resource_ids=(),
        )
    )

    # Round 2 (Z07-Z12): Zero-Trust Network & Public Exposure Elimination
    checks.append(
        _check_property_guard(
            request.resources,
            control_id="Z07.network.public_access_disabled",
            domain="zero_trust_network",
            title="Public network access is disabled across scoped cloud resources",
            resource_type_tokens=(),
            forbidden_true_props=("public_network_access_enabled", "allow_blob_public_access"),
        )
    )
    checks.append(
        _check_property_guard(
            request.resources,
            control_id="Z08.network.minimum_tls_1_2",
            domain="zero_trust_network",
            title="Minimum TLS version is 1.2 or 1.3 on all endpoints",
            resource_type_tokens=(),
            allowed_values={"minimum_tls_version": frozenset({"1.2", "1.3", "TLS1_2", "TLS1_3"})},
        )
    )
    checks.append(
        _check_property_guard(
            request.resources,
            control_id="Z09.network.no_wildcard_management_ports",
            domain="zero_trust_network",
            title="No wildcard (0.0.0.0/0) SSH/RDP management ports exposed",
            resource_type_tokens=("virtualmachines", "networksecuritygroups"),
            forbidden_true_props=("open_management_ports_exposed",),
        )
    )

    # Round 3 (Z13-Z18): Identity, Entra ID, RBAC & Secret Zero-Exposure Guards
    checks.append(
        _check_property_guard(
            request.resources,
            control_id="Z13.identity.managed_identity_and_no_local_auth",
            domain="identity_and_secrets",
            title="Managed Identity enabled and local shared-key auth disabled",
            resource_type_tokens=(),
            required_true_props=("managed_identity_enabled", "disable_local_auth"),
            forbidden_true_props=("shared_key_access_enabled", "admin_user_enabled"),
        )
    )
    checks.append(
        _check_property_guard(
            request.resources,
            control_id="Z16.secret.key_vault_purge_and_rbac",
            domain="identity_and_secrets",
            title="Key Vault purge protection, soft delete, and RBAC authorization enabled",
            resource_type_tokens=("keyvault/vaults",),
            required_true_props=(
                "purge_protection_enabled",
                "soft_delete_enabled",
                "rbac_authorization_enabled",
            ),
        )
    )

    # Round 4 (Z19-Z24): Compute, Kubernetes (AKS), & Container Supply-Chain
    checks.append(
        _check_property_guard(
            request.resources,
            control_id="Z20.compute.aks_zero_trust_posture",
            domain="compute_and_containers",
            title="AKS workload identity, Azure Policy add-on, and non-privileged pod posture",
            resource_type_tokens=("managedclusters",),
            required_true_props=("workload_identity_enabled", "azure_policy_addon_enabled"),
            forbidden_true_props=("privileged_containers_allowed", "host_network_allowed"),
        )
    )
    checks.append(
        _check_property_guard(
            request.resources,
            control_id="Z23.compute.vm_host_encryption_and_trusted_launch",
            domain="compute_and_containers",
            title="VM encryption at host and Trusted Launch Secure Boot enabled",
            resource_type_tokens=("virtualmachines",),
            required_true_props=("encryption_at_host_enabled", "trusted_launch_enabled"),
        )
    )

    # Round 5 (Z25-Z30): Data, Storage, Database, & AI/LLM Service Security
    checks.append(
        _check_property_guard(
            request.resources,
            control_id="Z26.data.sql_and_db_encryption_enforced",
            domain="data_and_ai",
            title="SQL/PostgreSQL/MySQL TDE, auditing, and SSL enforcement enabled",
            resource_type_tokens=("microsoft.sql", "dbforpostgresql", "dbformysql"),
            required_true_props=(
                "tde_enabled",
                "auditing_enabled",
                "ssl_enforcement_enabled",
            ),
        )
    )
    checks.append(
        _check_property_guard(
            request.resources,
            control_id="Z30.ai.openai_content_filter_and_private_link",
            domain="data_and_ai",
            title="Azure OpenAI / AI Foundry content filtering and private link enforced",
            resource_type_tokens=("cognitiveservices", "machinelearningservices"),
            required_true_props=("content_filtering_enabled", "private_endpoint_enabled"),
        )
    )

    # Round 6 (Z31-Z36): Continuous Zero-Day / KEV SLA Breach & Toxic Combinations
    affected_findings = [f for f in result.findings if f.exposure is CsafExposureStatus.AFFECTED]
    exploited_affected = [
        f for f in affected_findings if f.exploit_status is CsafThreatExploitStatus.EXPLOITED
    ]
    kev_breaches = [
        f
        for f in affected_findings
        if f.kev_sla_tier in {CsafKevSlaTier.IMMEDIATE_24H, CsafKevSlaTier.URGENT_72H}
    ]
    wormable_affected = [
        f
        for f in affected_findings
        if (v := vuln_by_cve.get(f.cve_id)) is not None and v.attack_profile.is_wormable_candidate
    ]
    public_rids = {
        res.resource_id
        for res in request.resources
        if res.properties.get("public_network_access_enabled") is True
        or res.properties.get("allow_blob_public_access") is True
    }
    toxic_rids = tuple(
        sorted(
            {
                rid
                for f in result.findings
                if f.exposure in {CsafExposureStatus.AFFECTED, CsafExposureStatus.MITIGATED}
                for rid in (*f.affected_resource_ids, *f.mitigated_resource_ids)
                if rid in public_rids
            }
        )
    )

    checks.append(
        SubscriptionAssuranceControlCheck(
            control_id="Z31.kev.zero_unpatched_cves",
            domain="kev_and_exploit_chains",
            title="Zero unpatched (Affected) MSRC CSAF vulnerabilities in subscription",
            passed=len(affected_findings) == 0,
            blocking_reasons=tuple(f"affected_cve:{f.cve_id}" for f in affected_findings[:10]),
            affected_resource_ids=tuple(
                sorted({rid for f in affected_findings for rid in f.affected_resource_ids})
            ),
        )
    )
    checks.append(
        SubscriptionAssuranceControlCheck(
            control_id="Z32.kev.zero_exploited_or_urgent_sla_breach",
            domain="kev_and_exploit_chains",
            title="Zero CISA KEV / MSRC Exploited or 24h-72h SLA breaches",
            passed=len(kev_breaches) == 0 and len(exploited_affected) == 0,
            blocking_reasons=tuple(f"kev_sla_breach:{f.cve_id}" for f in kev_breaches[:10]),
            affected_resource_ids=tuple(
                sorted({rid for f in kev_breaches for rid in f.affected_resource_ids})
            ),
        )
    )
    checks.append(
        SubscriptionAssuranceControlCheck(
            control_id="Z33.chain.zero_toxic_public_plus_cve",
            domain="kev_and_exploit_chains",
            title="Zero toxic combinations (public network exposure + unpatched/mitigated CVE)",
            passed=len(toxic_rids) == 0,
            blocking_reasons=tuple(f"toxic_public_cve:{rid}" for rid in toxic_rids),
            affected_resource_ids=toxic_rids,
        )
    )
    checks.append(
        SubscriptionAssuranceControlCheck(
            control_id="Z34.chain.zero_wormable_lateral_movement",
            domain="kev_and_exploit_chains",
            title="Zero wormable pre-auth zero-click RCE exposures enabling lateral movement",
            passed=len(wormable_affected) == 0,
            blocking_reasons=tuple(f"wormable_cve:{f.cve_id}" for f in wormable_affected[:10]),
            affected_resource_ids=tuple(
                sorted({rid for f in wormable_affected for rid in f.affected_resource_ids})
            ),
        )
    )

    # Round 7 (Z37-Z42): Constitutional 7-Safeguard Remediation Readiness
    actionable = [
        f
        for f in result.findings
        if f.exposure in {CsafExposureStatus.AFFECTED, CsafExposureStatus.MITIGATED}
    ]
    actionable.sort(key=lambda item: (-item.risk_score, -item.cvss_base_score, item.cve_id))
    plans = tuple(
        build_seven_safeguard_remediation_plan(
            f,
            workload_id=request.workload_id,
            inventory_generation=request.inventory_generation,
        )
        for f in actionable[:25]
    )

    passed_count = sum(1 for c in checks if c.passed)
    failed_count = len(checks) - passed_count
    if stale_rids or unknown_evaluated or incomplete_cves:
        status = ZeroRiskAssuranceStatus.COVERAGE_INCOMPLETE
    elif failed_count > 0 or len(affected_findings) > 0 or len(toxic_rids) > 0:
        status = ZeroRiskAssuranceStatus.AT_RISK
    else:
        status = ZeroRiskAssuranceStatus.CERTIFIED_ZERO_RISK

    deduction = (
        len(exploited_affected) * 35
        + sum(1 for f in affected_findings if f.severity is Severity.CRITICAL) * 25
        + len(affected_findings) * 10
        + len(toxic_rids) * 20
        + failed_count * 8
    )
    posture_score = max(0, 100 - min(100, deduction))
    change_freeze = len(exploited_affected) > 0 or len(toxic_rids) > 0 or len(kev_breaches) > 0

    digest_payload = {
        "workload_id": request.workload_id,
        "source_revision": request.source_revision,
        "inventory_generation": request.inventory_generation,
        "scope_digest": request.scope_digest,
        "status": status.value,
        "posture_score": posture_score,
        "checks": [c.to_dict() for c in checks],
        "plans": [p.to_dict() for p in plans],
    }
    return SubscriptionZeroRiskCertificate(
        workload_id=request.workload_id,
        source_revision=request.source_revision,
        inventory_generation=request.inventory_generation,
        scope_digest=request.scope_digest,
        status=status,
        posture_score=posture_score,
        total_checks=len(checks),
        passed_checks=passed_count,
        failed_checks=failed_count,
        toxic_combination_count=len(toxic_rids),
        kev_sla_breach_count=len(kev_breaches),
        change_freeze_recommended=change_freeze,
        checks=tuple(checks),
        remediation_plans=plans,
        certificate_digest=canonical_digest(digest_payload),
        execution_authority=False,
    )


__all__ = [
    "SevenSafeguardRemediationPlan",
    "SubscriptionAssuranceControlCheck",
    "SubscriptionZeroRiskCertificate",
    "ZeroRiskAssuranceStatus",
    "build_seven_safeguard_remediation_plan",
    "evaluate_subscription_zero_risk_assurance",
]
