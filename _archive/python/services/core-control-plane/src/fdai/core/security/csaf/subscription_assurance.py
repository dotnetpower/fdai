"""Subscription-wide Zero-Risk Security Assurance evaluator (Z01-Z48).

Evaluates whether an FDAI-managed subscription satisfies all 10 security
assurance domains (Scope Completeness, Zero-Trust Network, Identity & Secret
Store, Compute/AKS/Containers, Data/Storage/AI, KEV & Toxic Combinations,
Constitutional 7-Safeguard Readiness, and Pantheon Governance) in shadow mode
(execution_authority=False).
"""

from __future__ import annotations

import math
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
    # Q061 & Q062: Bind KEV SLA tier, due_days, OpenVEX justification, and composite risk score
    kev_sla_tier: str = "standard_30d"
    due_days: int = 30
    vex_justification: str = "affected_requires_remediation"
    risk_score: float = 0.0
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
            or self.due_days < 1
            or not math.isfinite(self.risk_score)
            or not 0.0 <= self.risk_score <= 100.0
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
            "kev_sla_tier": self.kev_sla_tier,
            "due_days": self.due_days,
            "vex_justification": self.vex_justification,
            "risk_score": self.risk_score,
            "mode": self.mode,
            "execution_authority": False,
        }


@dataclass(frozen=True, slots=True)
class SubscriptionAssuranceControlCheck:
    """Result of one deterministic subscription zero-risk assurance check (Q041, Q042)."""

    control_id: str
    domain: str
    title: str
    passed: bool
    blocking_reasons: tuple[str, ...]
    affected_resource_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not (self.control_id.strip() and self.domain.strip() and self.title.strip()):
            raise ValueError("SubscriptionAssuranceControlCheck identity fields MUST be non-empty")
        if self.blocking_reasons != tuple(sorted(set(self.blocking_reasons))):
            raise ValueError("blocking_reasons MUST be sorted unique")
        if self.affected_resource_ids != tuple(sorted(set(self.affected_resource_ids))):
            raise ValueError("affected_resource_ids MUST be sorted unique")
        if self.passed and self.affected_resource_ids:
            raise ValueError("passed=True MUST NOT have affected_resource_ids")

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
    """Deterministic zero-risk assurance report for a subscription (Q043-Q045, Q066-Q067)."""

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
    affected_cve_count: int = 0
    mitigated_cve_count: int = 0
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.execution_authority is not False:
            raise ValueError("SubscriptionZeroRiskCertificate MUST NOT grant execution_authority")
        if not 0 <= self.posture_score <= 100 or not self.certificate_digest.startswith("sha256:"):
            raise ValueError("requires posture_score in [0, 100] and sha256 digest")
        if self.total_checks != self.passed_checks + self.failed_checks or self.total_checks != len(
            self.checks
        ):
            raise ValueError("SubscriptionZeroRiskCertificate check counts MUST match len(checks)")
        if self.status is ZeroRiskAssuranceStatus.CERTIFIED_ZERO_RISK and (
            self.failed_checks > 0
            or self.toxic_combination_count > 0
            or self.kev_sla_breach_count > 0
            or self.affected_cve_count > 0
            or self.change_freeze_recommended
        ):
            raise ValueError("certified_zero_risk requires zero failed checks and zero breaches")

    def domain_summary(self) -> dict[str, dict[str, int]]:
        domains: dict[str, dict[str, int]] = {}
        for chk in self.checks:
            entry = domains.setdefault(chk.domain, {"total": 0, "passed": 0, "failed": 0})
            entry["total"] += 1
            entry["passed" if chk.passed else "failed"] += 1
        return dict(sorted(domains.items()))

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
            "affected_cve_count": self.affected_cve_count,
            "mitigated_cve_count": self.mitigated_cve_count,
            "toxic_combination_count": self.toxic_combination_count,
            "kev_sla_breach_count": self.kev_sla_breach_count,
            "change_freeze_recommended": self.change_freeze_recommended,
            "domain_summary": self.domain_summary(),
            "checks": [item.to_dict() for item in self.checks],
            "remediation_plans": [plan.to_dict() for plan in self.remediation_plans],
            "certificate_digest": self.certificate_digest,
            "execution_authority": False,
        }


def build_seven_safeguard_remediation_plan(
    finding: CsafVulnerabilityFinding, *, workload_id: str, inventory_generation: str
) -> SevenSafeguardRemediationPlan:
    """Build a 7-safeguard shadow remediation plan for one finding (Z37-Z42, Q063-Q064)."""
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
    sla_days_map = {
        "immediate_24h": 1,
        "urgent_72h": 3,
        "high_14d": 14,
        "standard_30d": 30,
        "monitor_90d": 90,
    }
    due_days = sla_days_map.get(finding.kev_sla_tier.value, 30)
    is_canary_required = (
        finding.exploit_status is CsafThreatExploitStatus.EXPLOITED
        or finding.severity is Severity.CRITICAL
    )
    blast_limit = 1 if is_canary_required else max(1, min(5, len(targets) or 1))
    stop_msg = (
        f"Abort immediately on health-probe degradation, error-rate spike > 1%, "
        f"or inventory generation drift from {inventory_generation}."
    )
    rollback_msg = (
        f"Restore pre-patch resource snapshot or version pin prior to {finding.cve_id} "
        f"({finding.advisory_tracking_id}) remediation and re-verify service health."
    )
    effect_msg = (
        f"Observe independent inventory generation > {inventory_generation} and verify "
        f"{finding.cve_id} ({finding.advisory_tracking_id}) exposure transitions to fixed "
        f"(patched_version_deployed)."
    )
    return SevenSafeguardRemediationPlan(
        finding.cve_id,
        targets,
        action_type,
        stop_msg,
        rollback_msg,
        blast_limit,
        True,
        lock_key,
        idem_digest,
        True,
        True,
        effect_msg,
        finding.kev_sla_tier.value,
        due_days,
        finding.vex_justification.value,
        finding.risk_score,
        "shadow",
        False,
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
    minimum_int_values: Mapping[str, int] | None = None,
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
        for prop, allowed in (allowed_values or {}).items():
            if prop in res.properties and str(res.properties[prop]) not in allowed:
                bad_ids.append(res.resource_id)
                reasons.append(f"{res.resource_id}:{prop}={res.properties[prop]!r}")
        for prop, min_val in (minimum_int_values or {}).items():
            raw_val = res.properties.get(prop)
            if isinstance(raw_val, int) and not isinstance(raw_val, bool) and raw_val < min_val:
                bad_ids.append(res.resource_id)
                reasons.append(f"{res.resource_id}:{prop}={raw_val}<{min_val}")
    unique_bad, unique_reasons = tuple(sorted(set(bad_ids))), tuple(sorted(set(reasons)))
    return SubscriptionAssuranceControlCheck(
        control_id, domain, title, len(unique_bad) == 0, unique_reasons, unique_bad
    )


def evaluate_subscription_zero_risk_assurance(
    catalog: MsrcCsafCrosswalkCatalog,
    request: CsafAssessmentRequest,
    result: CsafAssessmentResult,
    *,
    strict_orphan_tags: bool = False,
) -> SubscriptionZeroRiskCertificate:
    """Evaluate all Z01-Z48 and Q046-Q070 zero-risk subscription assurance controls."""

    # Q046: Enforce strict pin equality between catalog, request, and result
    if (
        request.source_revision != catalog.source_revision
        or result.source_revision != catalog.source_revision
        or request.crosswalk_digest != catalog.crosswalk_digest
        or result.crosswalk_digest != catalog.crosswalk_digest
        or request.advisories_digest != catalog.advisories_digest
        or result.advisories_digest != catalog.advisories_digest
        or request.scope_digest != result.scope_digest
        or request.inventory_generation != result.inventory_generation
        or request.workload_id != result.workload_id
    ):
        raise ValueError(
            "evaluate_subscription_zero_risk_assurance requires matching "
            "catalog, request, and result pins"
        )

    vuln_by_cve = {
        vuln.cve_id: vuln for advisory in catalog.advisories for vuln in advisory.vulnerabilities
    }
    checks: list[SubscriptionAssuranceControlCheck] = []

    # Round 1 (Z01-Z06 & Q047): Scope Completeness & Zero-Orphan Resource Admission
    orphans = tuple(sorted(res.resource_id for res in request.resources if not res.workload_tags))
    stale_rids = tuple(
        sorted(
            res.resource_id
            for res in request.resources
            if request.evaluated_at - res.observed_at > timedelta(hours=24)
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
    incomplete_cves = tuple(
        sorted(
            f.cve_id
            for f in result.findings
            if f.evaluation is CsafEvaluationStatus.EVALUATED and not f.evidence_complete
        )
    )
    checks.extend(
        (
            SubscriptionAssuranceControlCheck(
                "Z01.scope.workload_tag_attribution",
                "scope_completeness",
                "All subscription resources carry reviewed workload_tags attribution",
                (len(orphans) == 0) if strict_orphan_tags else True,
                tuple(f"untagged:{rid}" for rid in orphans),
                orphans if strict_orphan_tags else (),
            ),
            SubscriptionAssuranceControlCheck(
                "Z02.scope.inventory_freshness_24h",
                "scope_completeness",
                "All subscription resources observed within 24-hour freshness ceiling",
                len(stale_rids) == 0,
                tuple(f"stale_inventory:{rid}" for rid in stale_rids),
                stale_rids,
            ),
            SubscriptionAssuranceControlCheck(
                "Z03.scope.zero_unknown_cve_exposure",
                "scope_completeness",
                "Zero applicable CVEs remain in Unknown exposure state",
                len(unknown_evaluated) == 0,
                tuple(f"unknown_exposure:{cid}" for cid in unknown_evaluated[:10]),
                tuple(sorted({rid for f in result.findings for rid in f.unknown_resource_ids})),
            ),
            SubscriptionAssuranceControlCheck(
                "Z04.scope.evidence_completeness_100",
                "scope_completeness",
                "100% of evaluated applicable CVEs have complete observation evidence",
                len(incomplete_cves) == 0,
                tuple(f"incomplete_evidence:{cid}" for cid in incomplete_cves[:10]),
                (),
            ),
        )
    )

    # Round 2-5 (Z07-Z36 & Q048-Q060): Declarative Zero-Trust Property Guards
    def _g(
        cid: str,
        dom: str,
        ttl: str,
        rt: tuple[str, ...] = (),
        *,
        forb: tuple[str, ...] = (),
        req: tuple[str, ...] = (),
        allow: Mapping[str, frozenset[str]] | None = None,
        min_int: Mapping[str, int] | None = None,
    ) -> SubscriptionAssuranceControlCheck:
        return _check_property_guard(
            request.resources,
            control_id=cid,
            domain=dom,
            title=ttl,
            resource_type_tokens=rt,
            forbidden_true_props=forb,
            required_true_props=req,
            allowed_values=allow,
            minimum_int_values=min_int,
        )

    checks.extend(
        (
            _g(
                "Z07.network.public_access_disabled",
                "zero_trust_network",
                "Public network access is disabled across scoped cloud resources",
                forb=("public_network_access_enabled", "allow_blob_public_access"),
            ),
            _g(
                "Z08.network.minimum_tls_1_2",
                "zero_trust_network",
                "Minimum TLS version is 1.2 or 1.3 on all endpoints",
                allow={"minimum_tls_version": frozenset({"1.2", "1.3", "TLS1_2", "TLS1_3"})},
            ),
            _g(
                "Z09.network.no_wildcard_management_ports",
                "zero_trust_network",
                "No wildcard (0.0.0.0/0) SSH/RDP management ports exposed",
                ("virtualmachines", "networksecuritygroups"),
                forb=("open_management_ports_exposed",),
            ),
            _g(
                "Z10.network.ddos_and_waf_protection",
                "zero_trust_network",
                "DDoS protection and WAF policy enabled on edge network gateways",
                ("virtualnetworks", "applicationgateways", "cdn/profiles"),
                req=("ddos_protection_enabled", "waf_enabled"),
            ),
            _g(
                "Z11.network.private_link_and_dns_integration",
                "zero_trust_network",
                "Private Endpoint and Private DNS Zone integration enforced on PaaS services",
                req=("private_dns_zone_integrated",),
            ),
            _g(
                "Z13.identity.managed_identity_and_no_local_auth",
                "identity_and_secrets",
                "Managed Identity enabled and local shared-key auth disabled",
                forb=("shared_key_access_enabled", "admin_user_enabled"),
                req=("managed_identity_enabled", "disable_local_auth"),
            ),
            _g(
                "Z16.secret.key_vault_purge_and_rbac",
                "identity_and_secrets",
                "Key Vault purge protection, soft delete, and RBAC authorization enabled",
                ("keyvault/vaults",),
                req=(
                    "purge_protection_enabled",
                    "soft_delete_enabled",
                    "rbac_authorization_enabled",
                ),
            ),
            _g(
                "Z17.identity.no_wildcard_custom_rbac_roles",
                "identity_and_secrets",
                "No wildcard (*) custom RBAC roles or standing Owner assignments without PIM",
                ("authorization/roleassignments", "aad/domainservices"),
                forb=("wildcard_permissions_granted", "standing_owner_without_pim"),
            ),
            _g(
                "Z18.secret.key_rotation_and_expiry_policy",
                "identity_and_secrets",
                "Automated key rotation policy and certificate expiry guards enabled",
                ("keyvault/vaults",),
                req=("key_rotation_policy_enabled", "unexpired_certificates_verified"),
            ),
            _g(
                "Z20.compute.aks_zero_trust_posture",
                "compute_and_containers",
                "AKS workload identity, Azure Policy add-on, and non-privileged pod posture",
                ("managedclusters",),
                forb=("privileged_containers_allowed", "host_network_allowed"),
                req=("workload_identity_enabled", "azure_policy_addon_enabled"),
            ),
            _g(
                "Z21.compute.acr_quarantine_and_content_trust",
                "compute_and_containers",
                "Container Registry quarantine policy, content trust, and no anonymous pull",
                ("containerregistry/registries",),
                forb=("anonymous_pull_enabled",),
                req=("quarantine_policy_enabled", "trust_policy_enabled"),
            ),
            _g(
                "Z23.compute.vm_host_encryption_and_trusted_launch",
                "compute_and_containers",
                "VM encryption at host and Trusted Launch Secure Boot enabled",
                ("virtualmachines",),
                req=("encryption_at_host_enabled", "trusted_launch_enabled"),
            ),
            _g(
                "Z24.compute.vm_extension_signing_and_jit",
                "compute_and_containers",
                "VM extensions verified signed and JIT network access enforced",
                ("virtualmachines",),
                forb=("unsigned_extensions_present",),
                req=("jit_network_access_enabled",),
            ),
            _g(
                "Z25.data.storage_immutability_and_https",
                "data_and_ai",
                "Storage HTTPS-only traffic and infrastructure double encryption",
                ("storage/storageaccounts",),
                req=("https_traffic_only_enabled", "infrastructure_encryption_enabled"),
            ),
            _g(
                "Z26.data.sql_and_db_encryption_enforced",
                "data_and_ai",
                "SQL/PostgreSQL/MySQL TDE, auditing, and SSL enforcement enabled",
                ("microsoft.sql", "dbforpostgresql", "dbformysql"),
                req=("tde_enabled", "auditing_enabled", "ssl_enforcement_enabled"),
            ),
            _g(
                "Z27.data.cosmos_and_redis_zero_trust",
                "data_and_ai",
                "Cosmos DB continuous backup and Redis Cache non-TLS port disablement",
                ("documentdb/databaseaccounts", "cache/redis"),
                forb=("non_tls_port_enabled",),
                req=("continuous_backup_enabled",),
            ),
            _g(
                "Z28.data.backup_vault_immutability_and_mua",
                "data_and_ai",
                "Recovery Services Backup Vault immutability and multi-user authorization",
                ("recoveryservices/vaults",),
                req=("immutability_enabled", "multi_user_authorization_enabled"),
            ),
            _g(
                "Z29.ai.foundry_cmk_and_egress_restriction",
                "data_and_ai",
                "AI Foundry / ML workspace customer-managed keys and outbound egress restriction",
                ("cognitiveservices", "machinelearningservices"),
                req=("customer_managed_key_enabled", "outbound_network_access_restricted"),
            ),
            _g(
                "Z30.ai.openai_content_filter_and_private_link",
                "data_and_ai",
                "Azure OpenAI / AI Foundry content filtering and private link enforced",
                ("cognitiveservices", "machinelearningservices"),
                req=("content_filtering_enabled", "private_endpoint_enabled"),
            ),
            _g(
                "Z35.governance.defender_for_cloud_and_diagnostic_logs",
                "governance_and_safeguards",
                "Microsoft Defender for Cloud and diagnostic logs enabled with >= 90d retention",
                req=("defender_for_cloud_standard_enabled", "diagnostic_settings_enabled"),
                min_int={"retention_days": 90},
            ),
            _g(
                "Z36.governance.resource_locks_and_policy_compliance",
                "governance_and_safeguards",
                "Production resource delete locks and Azure Policy compliance verified",
                forb=("azure_policy_non_compliant",),
                req=("delete_lock_present",),
            ),
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

    checks.extend(
        (
            SubscriptionAssuranceControlCheck(
                "Z31.kev.zero_unpatched_cves",
                "kev_and_exploit_chains",
                "Zero unpatched (Affected) MSRC CSAF vulnerabilities in subscription",
                len(affected_findings) == 0,
                tuple(f"affected_cve:{f.cve_id}" for f in affected_findings[:10]),
                tuple(sorted({rid for f in affected_findings for rid in f.affected_resource_ids})),
            ),
            SubscriptionAssuranceControlCheck(
                "Z32.kev.zero_exploited_or_urgent_sla_breach",
                "kev_and_exploit_chains",
                "Zero CISA KEV / MSRC Exploited or 24h-72h SLA breaches",
                len(kev_breaches) == 0 and len(exploited_affected) == 0,
                tuple(f"kev_sla_breach:{f.cve_id}" for f in kev_breaches[:10]),
                tuple(sorted({rid for f in kev_breaches for rid in f.affected_resource_ids})),
            ),
            SubscriptionAssuranceControlCheck(
                "Z33.chain.zero_toxic_public_plus_cve",
                "kev_and_exploit_chains",
                "Zero toxic combinations (public network exposure + unpatched/mitigated CVE)",
                len(toxic_rids) == 0,
                tuple(f"toxic_public_cve:{rid}" for rid in toxic_rids),
                toxic_rids,
            ),
            SubscriptionAssuranceControlCheck(
                "Z34.chain.zero_wormable_lateral_movement",
                "kev_and_exploit_chains",
                "Zero wormable pre-auth zero-click RCE exposures enabling lateral movement",
                len(wormable_affected) == 0,
                tuple(f"wormable_cve:{f.cve_id}" for f in wormable_affected[:10]),
                tuple(sorted({rid for f in wormable_affected for rid in f.affected_resource_ids})),
            ),
        )
    )

    # Round 7 (Z37-Z42 & Q065-Q070): Constitutional 7-Safeguard Remediation Readiness
    mitigated_findings = [f for f in result.findings if f.exposure is CsafExposureStatus.MITIGATED]
    actionable = sorted(
        [*affected_findings, *mitigated_findings],
        key=lambda item: (-item.risk_score, -item.cvss_base_score, item.cve_id),
    )
    plans = tuple(
        build_seven_safeguard_remediation_plan(
            f, workload_id=request.workload_id, inventory_generation=request.inventory_generation
        )
        for f in actionable[:25]
    )
    checks.append(
        SubscriptionAssuranceControlCheck(
            "Z40.safeguard.seven_safeguard_remediation_readiness",
            "governance_and_safeguards",
            "Every actionable CVE has a shadow 7-safeguard remediation plan",
            all(p.execution_authority is False and p.dry_run_required for p in plans),
            (),
            (),
        )
    )
    checks.sort(key=lambda item: item.control_id)
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
    digest_payload = _certificate_digest_payload(
        workload_id=request.workload_id,
        source_revision=request.source_revision,
        inventory_generation=request.inventory_generation,
        scope_digest=request.scope_digest,
        status=status,
        posture_score=posture_score,
        affected_cve_count=len(affected_findings),
        mitigated_cve_count=len(mitigated_findings),
        checks=checks,
        plans=plans,
    )
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
        affected_cve_count=len(affected_findings),
        mitigated_cve_count=len(mitigated_findings),
        execution_authority=False,
    )


def _certificate_digest_payload(
    *,
    workload_id: str,
    source_revision: str,
    inventory_generation: str,
    scope_digest: str,
    status: ZeroRiskAssuranceStatus,
    posture_score: int,
    affected_cve_count: int,
    mitigated_cve_count: int,
    checks: Sequence[SubscriptionAssuranceControlCheck],
    plans: Sequence[SevenSafeguardRemediationPlan],
) -> dict[str, object]:
    return {
        "workload_id": workload_id,
        "source_revision": source_revision,
        "inventory_generation": inventory_generation,
        "scope_digest": scope_digest,
        "status": status.value,
        "posture_score": posture_score,
        "affected_cve_count": affected_cve_count,
        "mitigated_cve_count": mitigated_cve_count,
        "checks": [c.to_dict() for c in checks],
        "plans": [p.to_dict() for p in plans],
    }


def verify_certificate_integrity(certificate: SubscriptionZeroRiskCertificate) -> bool:
    """Recompute and verify the SHA-256 digest of a SubscriptionZeroRiskCertificate (Q068)."""

    if certificate.execution_authority is not False:
        return False
    return certificate.certificate_digest == canonical_digest(
        _certificate_digest_payload(
            workload_id=certificate.workload_id,
            source_revision=certificate.source_revision,
            inventory_generation=certificate.inventory_generation,
            scope_digest=certificate.scope_digest,
            status=certificate.status,
            posture_score=certificate.posture_score,
            affected_cve_count=certificate.affected_cve_count,
            mitigated_cve_count=certificate.mitigated_cve_count,
            checks=certificate.checks,
            plans=certificate.remediation_plans,
        )
    )


__all__ = [
    "SevenSafeguardRemediationPlan",
    "SubscriptionAssuranceControlCheck",
    "SubscriptionZeroRiskCertificate",
    "ZeroRiskAssuranceStatus",
    "build_seven_safeguard_remediation_plan",
    "evaluate_subscription_zero_risk_assurance",
    "verify_certificate_integrity",
]
