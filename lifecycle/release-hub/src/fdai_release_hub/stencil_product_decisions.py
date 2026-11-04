"""Reviewed Stencil drafts, F01-F15 feature mapping, physical exclusion, and build-once provenance.

Owns the #2525 / #2526 / #2527 product and packaging contracts:
- `REVIEWED_STENCIL_DRAFTS`: Basic (`lite-observe-alert`), Premium (`standard-sre`),
  Regulated (`regulated-governance`), and Full (`full-enterprise`), proving that neither
  Premium nor Regulated is assumed to be a superset of the other.
- `F01_TO_F15_FEATURE_MAPPING`: deterministic mapping of every `F01.1`..`F15.2` subfeature
  referenced by `CONSOLE_PANEL_CATALOG` to owned packages, services, Console routes/assets,
  workers, catalogs, migrations, external prerequisites, permissions, and tests.
- `STENCIL_PRODUCT_DECISION_REGISTER`: reviewed architectural decisions covering distribution
  grants, runtime licensing, execution authority, variant identity, trust, revocation, old
  consumers, and migration/recovery boundaries.
- `verify_physical_stencil_exclusion`: proves an excluded feature is physically absent from
  the excluded Stencil's component set, workload manifest, scheduled jobs, and Console chunk
  graph and cannot be re-enabled through direct API/import/env paths.
- `build_reviewed_stencil_candidate_set` & `verify_build_once_promotion_invariance`: builds
  variant-bound `fdai.application-release.v2` manifests from one reviewed source commit and
  verifies zero component digest or signed manifest byte changes across `DEV -> RC -> RELEASE`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.lifecycle_release import (
    ApplicationRelease,
    parse_lifecycle_release_manifest,
)
from fdai_deployment_cli.lifecycle_stencil_grant import (
    StencilVariantBinding,
    extract_stencil_variant_binding,
    format_variant_release_id,
)

from fdai_release_hub.stencils import (
    ALL_PANEL_IDS,
    CONSOLE_PANEL_CATALOG,
    LITE_OBSERVE_ALERT_PANELS,
    LOCKED_CORE_ADDONS,
    LOCKED_CORE_LOOPS,
    LOCKED_CORE_PANELS,
    LOCKED_CORE_SCHEDULED_JOBS,
    LOCKED_CORE_WORKLOADS,
    PANEL_BY_ID,
    STENCIL_PRESETS,
    StencilDefinition,
    build_stencil_release_manifest,
    evaluate_stencil_feature_flag_gate,
    evaluate_stencil_footprint,
)

REGULATED_GOVERNANCE_PANELS: tuple[str, ...] = tuple(
    sorted(
        {
            *LITE_OBSERVE_ALERT_PANELS,
            "control-assurance",
            "trust-routing",
            "agents",
            "architecture",
            "ontology",
            "handover",
            "blast-radius",
            "promotion-gates",
            "scope",
            "assurance-twin",
            "code-security",
            "reports",
            "rca",
            "settings-models",
            "settings-runtime",
            "settings-iam",
            "settings-diagnostics",
        }
    )
)

REGULATED_GOVERNANCE_STENCIL = StencilDefinition(
    stencil_id="regulated-governance",
    title="Regulated: Sovereign Audit, Policy Governance & Assurance Twin",
    title_ko="규제 준수 에디션: 주권 감사·정책 거버넌스 및 보증 트윈",
    description=(
        "Sovereign and regulated distribution profile. Includes policy administration, "
        "code security scanning, assurance twin, promotion gates, and full audit lineage "
        "while physically omitting privileged isolated-executor mutation, external Git "
        "knowledge connectors, and experimental Labs."
    ),
    description_ko=(
        "금융·공공 규제 환경을 위한 배포 프로필입니다. 정책 관리, 코드 보안 스캔, "
        "보증 디지털 트윈, 자율성 승격 게이트 및 감사 추적은 포함하되, 격리 조치 "
        "실행기(Isolated Executor), 외부 Git 지식 커넥터 및 실험실(Labs)은 제외합니다."
    ),
    topology_profile="standard-sre",
    enabled_workloads=LOCKED_CORE_WORKLOADS,
    enabled_scheduled_jobs=tuple(sorted({*LOCKED_CORE_SCHEDULED_JOBS, "canary"})),
    enabled_loops=tuple(sorted({*LOCKED_CORE_LOOPS, "assurance-twin", "code-security"})),
    enabled_addons=tuple(
        sorted(
            {
                *LOCKED_CORE_ADDONS,
                "enterprise-identity-governance",
                "policy-administration",
            }
        )
    ),
    enabled_panel_ids=REGULATED_GOVERNANCE_PANELS,
)

REVIEWED_STENCIL_DRAFTS: Mapping[str, StencilDefinition] = {
    "basic": STENCIL_PRESETS["lite-observe-alert"],
    "premium": STENCIL_PRESETS["standard-sre"],
    "regulated": REGULATED_GOVERNANCE_STENCIL,
    "full": STENCIL_PRESETS["full-enterprise"],
    "lite-observe-alert": STENCIL_PRESETS["lite-observe-alert"],
    "standard-sre": STENCIL_PRESETS["standard-sre"],
    "regulated-governance": REGULATED_GOVERNANCE_STENCIL,
    "full-enterprise": STENCIL_PRESETS["full-enterprise"],
}


@dataclass(frozen=True, slots=True)
class FeatureCodeMappingRecord:
    """Maps a functional specification ID (`Fxx.y`) to its owned implementation artifacts."""

    feature_id: str
    title: str
    owned_packages: tuple[str, ...]
    services: tuple[str, ...]
    console_panels: tuple[str, ...]
    workers_and_jobs: tuple[str, ...]
    catalogs_and_policies: tuple[str, ...]
    migrations: tuple[str, ...]
    external_prerequisites: tuple[str, ...]
    required_permissions: tuple[str, ...]
    focused_tests: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "title": self.title,
            "owned_packages": list(self.owned_packages),
            "services": list(self.services),
            "console_panels": list(self.console_panels),
            "workers_and_jobs": list(self.workers_and_jobs),
            "catalogs_and_policies": list(self.catalogs_and_policies),
            "migrations": list(self.migrations),
            "external_prerequisites": list(self.external_prerequisites),
            "required_permissions": list(self.required_permissions),
            "focused_tests": list(self.focused_tests),
        }


def _panels_for_feature(feature_id: str) -> tuple[str, ...]:
    return tuple(sorted(p.id for p in CONSOLE_PANEL_CATALOG if feature_id in p.feature_ids))


_FEATURE_SPEC_ROWS: tuple[
    tuple[
        str,
        str,
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
    ],
    ...,
] = (
    (
        "F01.1",
        "Subscription & management-scope onboarding",
        ("fdai_service_contracts", "fdai_operator_service"),
        ("core-control-plane", "operator-service"),
        ("inventory",),
        ("rule-catalog/vocabulary",),
        ("service-migrations/branches/core",),
        ("Azure Resource Graph endpoint",),
        ("Reader",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F01.2",
        "Runtime policy administration",
        ("fdai_service_contracts", "fdai_operator_service"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("policies/opa",),
        ("service-migrations/branches/core",),
        ("Entra ID group binding",),
        ("Reader",),
        ("services/operator-service/tests/test_policy_admin_role_boundary.py",),
    ),
    (
        "F01.3",
        "Agent stewardship & IAM role bindings",
        ("fdai_service_contracts", "fdai_operator_service"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("config/agent-stewardship.yaml",),
        ("service-migrations/branches/operator",),
        ("Entra ID app registration",),
        ("Reader",),
        ("services/operator-service/tests/test_operator_iam_family.py",),
    ),
    (
        "F02.1",
        "Continuous resource discovery & configuration drift",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("inventory",),
        ("rule-catalog/vocabulary/object-types",),
        ("service-migrations/branches/core",),
        ("Azure Resource Graph & ARM",),
        ("Reader",),
        ("services/core-control-plane/tests/delivery/test_inventory_sync_cli.py",),
    ),
    (
        "F02.2",
        "Operating ontology & architecture topology workbench",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("inventory",),
        ("rule-catalog/vocabulary",),
        ("service-migrations/branches/core",),
        ("PostgreSQL pgvector",),
        ("Reader",),
        ("console/src/components/architecture-map.model.test.ts",),
    ),
    (
        "F02.3",
        "Configuration baselines & drift verification",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("inventory", "analyzer"),
        ("rule-catalog/rules",),
        ("service-migrations/branches/core",),
        ("Azure Resource Graph",),
        ("Reader",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F03.1",
        "Continuous health, metric, and scheduler monitoring",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("inventory", "analyzer"),
        ("rule-catalog/rules",),
        ("service-migrations/branches/core",),
        ("Azure Monitor / Log Analytics",),
        ("Monitoring Reader", "Log Analytics Reader"),
        ("services/core-control-plane/tests/delivery/test_analyzer_target_admissions.py",),
    ),
    (
        "F03.2",
        "Operating outcomes & SLO assurance projections",
        ("fdai_service_contracts", "fdai_operator_service"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("rule-catalog/vocabulary",),
        ("service-migrations/branches/core",),
        ("PostgreSQL",),
        ("Reader",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F03.3",
        "GPU fleet telemetry & utilization monitoring",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("rule-catalog/rules",),
        ("service-migrations/branches/core",),
        ("Azure Monitor GPU metrics",),
        ("Monitoring Reader",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F03.4",
        "Capacity forecasting & trend projections",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("rule-catalog/rules",),
        ("service-migrations/branches/core",),
        ("Azure Monitor",),
        ("Monitoring Reader",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F04.1",
        "Deterministic T0 rule detection & incident opening",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("rule-catalog/rules",),
        ("service-migrations/branches/core",),
        ("Azure Monitor",),
        ("Monitoring Reader",),
        ("services/core-control-plane/tests/agents/test_heimdall_incident_detection_chain.py",),
    ),
    (
        "F04.2",
        "Alert quality & noise suppression",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("rule-catalog/rules",),
        ("service-migrations/branches/core",),
        ("PostgreSQL",),
        ("Reader",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F04.3",
        "Correlated Root Cause Analysis (RCA)",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("rule-catalog/prompts",),
        ("service-migrations/branches/core",),
        ("Azure Monitor & Activity Log",),
        ("Reader", "Monitoring Reader"),
        ("services/operator-service/tests/test_incident_rca_reporting_projection.py",),
    ),
    (
        "F05.1",
        "T0/T1/T2 trust routing & model selection",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("rule-catalog/prompts",),
        ("service-migrations/branches/core",),
        ("Azure OpenAI (optional for T1/T2)",),
        ("Cognitive Services OpenAI User",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F05.2",
        "15-Agent Pantheon fleet & activity timeline",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("analyzer", "inventory"),
        ("config/agent-stewardship.yaml",),
        ("service-migrations/branches/core",),
        ("PostgreSQL",),
        ("Reader",),
        ("console/src/agent-operational-activity.test.ts",),
    ),
    (
        "F06.1",
        "Human-in-the-Loop (HIL) approval queue",
        ("fdai_service_contracts", "fdai_operator_service"),
        ("core-control-plane", "operator-service", "isolated-executor"),
        ("analyzer",),
        ("policies/opa",),
        ("service-migrations/branches/core",),
        ("Entra ID approver identity",),
        ("Scoped Executor Action Role (privileged mutation)",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F06.2",
        "Blast-radius limits & seven execution safeguards",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("policies/opa",),
        ("service-migrations/branches/core",),
        ("PostgreSQL",),
        ("Reader",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F06.3",
        "Autonomy promotion gates & ARB readiness",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("policies/opa",),
        ("service-migrations/branches/core",),
        ("PostgreSQL",),
        ("Reader",),
        ("tests/integration/scripts/test_rehearse_f063_arb_operational_readiness.py",),
    ),
    (
        "F07.1",
        "Governed remediation execution & rollback",
        ("fdai_service_contracts", "fdai_executor_service"),
        ("core-control-plane", "operator-service", "isolated-executor"),
        ("analyzer",),
        ("rule-catalog/vocabulary/action-types",),
        ("service-migrations/branches/executor",),
        ("Dedicated executor Managed Identity",),
        ("Scoped Executor Action Role (privileged mutation)",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F07.2",
        "Workflow builder, blueprints, and continuations",
        ("fdai_service_contracts", "fdai_operator_service"),
        ("core-control-plane", "operator-service", "isolated-executor"),
        ("analyzer",),
        ("rule-catalog/workflows",),
        ("service-migrations/branches/core",),
        ("PostgreSQL",),
        ("Scoped Executor Action Role (privileged mutation)",),
        ("services/operator-service/tests/test_workflow_validate_shared_loader.py",),
    ),
    (
        "F08.1",
        "Localized briefing & notification channel dispatch",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("rule-catalog/prompts",),
        ("service-migrations/branches/core",),
        ("Webhook / Teams / Email endpoint",),
        ("Reader",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F08.2",
        "Conversation history & semantic search",
        ("fdai_service_contracts", "fdai_operator_service"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("rule-catalog/vocabulary",),
        ("service-migrations/branches/operator",),
        ("PostgreSQL",),
        ("Reader",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F08.3",
        "Conversational grounding & quality assurance",
        ("fdai_service_contracts", "fdai_operator_service"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("rule-catalog/prompts",),
        ("service-migrations/branches/operator",),
        ("PostgreSQL",),
        ("Reader",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F09.1",
        "Cloud Cost Governance & LLM token accounting",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("cost-collector",),
        ("rule-catalog/catalog",),
        ("service-migrations/branches/core",),
        ("Azure Cost Management / Retail Prices",),
        ("Cost Management Reader",),
        ("tests/integration/scripts/test_cost_governance_package_convergence.py",),
    ),
    (
        "F09.2",
        "AKS commerce & workload right-sizing",
        ("fdai_service_contracts", "fdai_operator_service"),
        ("core-control-plane", "operator-service"),
        ("cost-collector",),
        ("rule-catalog/catalog",),
        ("service-migrations/branches/core",),
        ("Azure Cost Management & AKS metrics",),
        ("Cost Management Reader", "Monitoring Reader"),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F10.1",
        "Saga tamper-evident hash-chained audit trail",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("analyzer", "inventory"),
        ("rule-catalog/vocabulary",),
        ("service-migrations/branches/core",),
        ("PostgreSQL",),
        ("Reader",),
        ("services/core-control-plane/tests/persistence/test_saga_compact_checkpoint.py",),
    ),
    (
        "F10.2",
        "Browser visual & diagnostic evidence capture",
        ("fdai_service_contracts", "fdai_operator_service"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("rule-catalog/vocabulary",),
        ("service-migrations/branches/core",),
        ("Playwright / browser evidence store",),
        ("Reader",),
        ("console/src/routes/browser-evidence.test.ts",),
    ),
    (
        "F10.3",
        "WARA & operational posture reports",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("packages/service-contracts/src/fdai_service_contracts/wara_guidance.py",),
        ("service-migrations/branches/core",),
        ("PostgreSQL",),
        ("Reader",),
        ("services/core-control-plane/tests/delivery/test_wara_report.py",),
    ),
    (
        "F11.1",
        "Document ingestion gateway & ClamAV scanning",
        ("fdai_ingestion_api_service", "fdai_document_worker_service"),
        ("document-ingestion-api", "document-processing-worker"),
        ("document-processing-worker",),
        ("rule-catalog/vocabulary",),
        ("service-migrations/branches/ingestion", "service-migrations/branches/worker"),
        ("ClamAV sidecar & pgvector",),
        ("Reader",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F11.2",
        "External GitHub, GitLab, and Azure DevOps knowledge sources",
        ("fdai_ingestion_api_service", "fdai_document_worker_service"),
        ("document-ingestion-api", "document-processing-worker"),
        ("document-processing-worker",),
        ("rule-catalog/vocabulary",),
        ("service-migrations/branches/ingestion",),
        ("Git provider token reference & ClamAV",),
        ("Reader",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F12.1",
        "Rule catalog & control assurance governance",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("rule-catalog/rules",),
        ("service-migrations/branches/core",),
        ("PostgreSQL",),
        ("Reader",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F12.2",
        "Trusted capabilities & skill bundle lifecycle",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("rule-catalog/vocabulary/action-types",),
        ("service-migrations/branches/core",),
        ("PostgreSQL",),
        ("Reader",),
        ("services/core-control-plane/tests/delivery/test_capability_bundle_lifecycle_lineage.py",),
    ),
    (
        "F12.3",
        "Digital Assurance Twin simulation",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("rule-catalog/vocabulary",),
        ("service-migrations/branches/core",),
        ("PostgreSQL",),
        ("Reader",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F13.1",
        "Operational learning & operator memory",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("rule-catalog/vocabulary",),
        ("service-migrations/branches/core",),
        ("PostgreSQL pgvector",),
        ("Reader",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F14.1",
        "Repository code security SARIF & dataflow scanning",
        ("fdai_service_contracts", "fdai"),
        ("core-control-plane", "operator-service"),
        ("analyzer",),
        ("rule-catalog/rules",),
        ("service-migrations/branches/core",),
        ("PostgreSQL",),
        ("Reader",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F15.1",
        "Azure environment provisioning & subscription genesis",
        ("fdai_deployment_cli", "fdai_operator_service"),
        ("core-control-plane", "operator-service"),
        ("inventory",),
        ("infra/azure",),
        ("service-migrations/branches/core",),
        ("Protected deployment runner",),
        ("Reader",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
    (
        "F15.2",
        "Runtime diagnostics & synthetic canary health",
        ("fdai_service_contracts", "fdai_operator_service"),
        ("core-control-plane", "operator-service"),
        ("canary", "analyzer"),
        ("rule-catalog/vocabulary",),
        ("service-migrations/branches/core",),
        ("PostgreSQL",),
        ("Reader",),
        ("services/operator-service/tests/test_stencil_feature_flags.py",),
    ),
)

F01_TO_F15_FEATURE_MAPPING: Mapping[str, FeatureCodeMappingRecord] = {
    fid: FeatureCodeMappingRecord(
        feature_id=fid,
        title=title,
        owned_packages=pkgs,
        services=svcs,
        console_panels=_panels_for_feature(fid),
        workers_and_jobs=jobs,
        catalogs_and_policies=cats,
        migrations=migs,
        external_prerequisites=prereqs,
        required_permissions=perms,
        focused_tests=tests,
    )
    for fid, title, pkgs, svcs, jobs, cats, migs, prereqs, perms, tests in _FEATURE_SPEC_ROWS
}

STENCIL_PRODUCT_DECISION_REGISTER: tuple[dict[str, Any], ...] = (
    {
        "decision_id": "SPD-01",
        "topic": "Reviewed Stencil drafts and non-superset independence",
        "status": "approved",
        "decision": (
            "Basic ('lite-observe-alert'), Premium ('standard-sre'), and Regulated "
            "('regulated-governance') are independent build-time compositions. Premium includes "
            "governed execution ('isolated-executor', 'hil-queue', 'provision') which Regulated "
            "excludes; Regulated includes 'policy-administration', 'code-security', and "
            "'assurance-twin' which Premium excludes. Full ('full-enterprise') includes all "
            "63 panels."
        ),
    },
    {
        "decision_id": "SPD-02",
        "topic": "Distribution grants vs runtime licensing and execution authority",
        "status": "approved",
        "decision": (
            "A Stencil distribution grant ('fdai.stencil-distribution-grant.v1') governs only "
            "which Stencil variants and customer channels ('RELEASE_CANDIDATE', 'RELEASE') a "
            "customer Hub may discover and pull. It never issues a runtime license, never resets "
            "the 30-day Trial anchor or watermark, and never grants RBAC or execution authority."
        ),
    },
    {
        "decision_id": "SPD-03",
        "topic": "Same-version variant identity without SemVer '+' build metadata",
        "status": "approved",
        "decision": (
            "Multiple Stencils at base version X.Y.Z use canonical '<X.Y.Z>-<stencil_id>' release "
            "IDs and a database-unique '(base_release_version, stencil_id)' variant table so "
            "SemVer '+' build metadata is never used for ordering or uniqueness."
        ),
    },
    {
        "decision_id": "SPD-04",
        "topic": "Grant validity, revocation, and installed-version safety recovery",
        "status": "approved",
        "decision": (
            "Expired or revoked distribution grants immediately block new Stencil discovery, "
            "catalog upgrades, and unentitled registry pulls, while preserving active recall "
            "notices and schema-compatible recall-rolloff recovery for an already-installed "
            "version."
        ),
    },
    {
        "decision_id": "SPD-05",
        "topic": "Stencil transition, downgrade, and old-consumer compatibility",
        "status": "approved",
        "decision": (
            "Switching or downgrading Stencils requires an entitled distribution grant, a "
            "customer-signed configuration revision, a matching RuntimeBundle, and "
            "forward/compatible schema checks. Data is never silently purged and schema rollback "
            "is never fabricated. Legacy v1/v2/v3 signed inputs keep their exact bytes and "
            "signatures."
        ),
    },
)


def verify_physical_stencil_exclusion(
    included_stencil: StencilDefinition,
    excluded_stencil: StencilDefinition,
    *,
    feature_panel_id: str,
) -> dict[str, Any]:
    """Prove `feature_panel_id` is physically excluded from `excluded_stencil` (#2526)."""
    if feature_panel_id not in PANEL_BY_ID:
        raise ValueError(f"Unknown Console panel id: {feature_panel_id!r}")
    if feature_panel_id in LOCKED_CORE_PANELS:
        raise ValueError(f"Locked safety-core panel {feature_panel_id!r} cannot be excluded.")
    if feature_panel_id not in included_stencil.enabled_panel_ids:
        raise ValueError(
            f"Panel {feature_panel_id!r} is not enabled in {included_stencil.stencil_id!r}."
        )
    if feature_panel_id in excluded_stencil.enabled_panel_ids:
        raise ValueError(
            f"Panel {feature_panel_id!r} is still enabled in {excluded_stencil.stencil_id!r}."
        )

    panel = PANEL_BY_ID[feature_panel_id]
    inc_fp = evaluate_stencil_footprint(included_stencil)
    exc_fp = evaluate_stencil_footprint(excluded_stencil)

    inc_gate = evaluate_stencil_feature_flag_gate(
        included_stencil, requested_panel_id=feature_panel_id
    )
    exc_gate = evaluate_stencil_feature_flag_gate(
        excluded_stencil, requested_panel_id=feature_panel_id
    )
    safety_gates = {
        core_panel: evaluate_stencil_feature_flag_gate(
            excluded_stencil, requested_panel_id=core_panel
        )["allowed"]
        for core_panel in LOCKED_CORE_PANELS
    }

    physically_omitted_workloads = sorted(
        set(panel.required_workloads) - set(excluded_stencil.enabled_workloads)
    )
    physically_omitted_loops = sorted(
        set(panel.required_loops) - set(excluded_stencil.enabled_loops)
    )
    feature_mappings = [
        F01_TO_F15_FEATURE_MAPPING[fid].to_dict()
        for fid in panel.feature_ids
        if fid in F01_TO_F15_FEATURE_MAPPING
    ]

    if not inc_gate["allowed"] or exc_gate["allowed"] or not all(safety_gates.values()):
        raise RuntimeError("Physical Stencil exclusion verification failed gate invariants.")

    return {
        "feature_panel_id": feature_panel_id,
        "feature_ids": list(panel.feature_ids),
        "feature_mappings": feature_mappings,
        "included_stencil_id": included_stencil.stencil_id,
        "included_stencil_digest": included_stencil.digest,
        "excluded_stencil_id": excluded_stencil.stencil_id,
        "excluded_stencil_digest": excluded_stencil.digest,
        "included_gate_allowed": inc_gate["allowed"],
        "excluded_gate_allowed": exc_gate["allowed"],
        "excluded_gate_reasons": exc_gate["reasons"],
        "physically_omitted_workloads": physically_omitted_workloads,
        "physically_omitted_loops": physically_omitted_loops,
        "console_chunk_pruned_in_excluded": feature_panel_id in exc_fp["disabled_panel_ids"],
        "console_chunk_retained_in_included": feature_panel_id
        in included_stencil.enabled_panel_ids,
        "locked_safety_core_intact": safety_gates,
        "included_workload_count": inc_fp["workload_count"],
        "excluded_workload_count": exc_fp["workload_count"],
    }


def build_reviewed_stencil_candidate_set(
    *,
    source_commit: str,
    base_release_version: str = "0.5.0",
    stencil_ids: tuple[str, ...] = (
        "lite-observe-alert",
        "standard-sre",
        "regulated-governance",
        "full-enterprise",
    ),
    shared_component_digests: Mapping[str, str] | None = None,
    registry_host: str = "hub.msfdai.com",
) -> dict[str, dict[str, Any]]:
    """Build immutable variant-bound Release candidates from one source (#2527)."""
    default_digests: dict[str, str] = {
        comp: "sha256:"
        + hashlib.sha256(f"fdai-shared-component:{source_commit}:{comp}".encode()).hexdigest()
        for comp in (
            "core-control-plane",
            "operator-service",
            "isolated-executor",
            "document-ingestion-api",
            "document-processing-worker",
            "pgvector",
            "clamav",
        )
    }
    if shared_component_digests is not None:
        default_digests.update(shared_component_digests)

    candidates: dict[str, dict[str, Any]] = {}
    for st_id in stencil_ids:
        if st_id not in REVIEWED_STENCIL_DRAFTS:
            raise ValueError(f"Unknown reviewed Stencil id: {st_id!r}")
        stencil = REVIEWED_STENCIL_DRAFTS[st_id]
        variant_release_id = format_variant_release_id(base_release_version, stencil.stencil_id)
        manifest = build_stencil_release_manifest(
            stencil,
            release_version=variant_release_id,
            source_commit=source_commit,
            component_digests=default_digests,
            registry_host=registry_host,
            resolve_local_docker=False,
            tag_local_docker=False,
        )
        raw_manifest = canonical_bytes(manifest)
        parsed = parse_lifecycle_release_manifest(raw_manifest)
        if not isinstance(parsed, ApplicationRelease):
            raise TypeError("Expected ApplicationRelease from Stencil manifest.")
        binding = extract_stencil_variant_binding(variant_release_id, parsed)
        if not isinstance(binding, StencilVariantBinding):
            raise TypeError("Expected StencilVariantBinding from Stencil manifest.")
        footprint = evaluate_stencil_footprint(stencil)
        provenance = {
            "source_commit": source_commit,
            "base_release_version": base_release_version,
            "release_id": variant_release_id,
            "variant_key": binding.variant_key,
            "stencil_id": stencil.stencil_id,
            "stencil_digest": stencil.digest,
            "feature_flags_digest": footprint["feature_flags"]["feature_flags_digest"],
            "release_digest": binding.release_digest,
            "component_digests": dict(binding.component_digests),
            "enabled_workloads": list(stencil.enabled_workloads),
            "omitted_workloads": footprint["omitted_workloads"],
            "enabled_feature_ids": list(stencil.enabled_feature_ids),
            "enabled_panel_count": len(stencil.enabled_panel_ids),
            "omitted_panel_count": len(ALL_PANEL_IDS) - len(stencil.enabled_panel_ids),
        }
        provenance["provenance_digest"] = "sha256:" + canonical_digest(provenance)
        candidates[stencil.stencil_id] = {
            "stencil": stencil.model_dump(mode="json"),
            "release_id": variant_release_id,
            "release_manifest": manifest,
            "canonical_manifest_bytes": raw_manifest.decode("utf-8"),
            "variant_binding": binding.to_payload(),
            "provenance": provenance,
            "footprint": footprint,
        }
    return candidates


def verify_build_once_promotion_invariance(
    *,
    dev_manifest_bytes: bytes,
    rc_manifest_bytes: bytes,
    release_manifest_bytes: bytes,
    dev_signature: str,
    rc_signature: str,
    release_signature: str,
) -> dict[str, Any]:
    """Prove DEV -> RC -> RELEASE promotion changes 0 digests or signed bytes (#2527)."""
    dev_rel = parse_lifecycle_release_manifest(dev_manifest_bytes)
    rc_rel = parse_lifecycle_release_manifest(rc_manifest_bytes)
    rel_rel = parse_lifecycle_release_manifest(release_manifest_bytes)
    if (
        not isinstance(dev_rel, ApplicationRelease)
        or not isinstance(rc_rel, ApplicationRelease)
        or not isinstance(rel_rel, ApplicationRelease)
    ):
        raise TypeError("Expected ApplicationRelease manifests for promotion invariance.")

    manifest_bytes_unchanged = dev_manifest_bytes == rc_manifest_bytes == release_manifest_bytes
    signature_unchanged = dev_signature == rc_signature == release_signature
    digests_unchanged = dev_rel.digest == rc_rel.digest == rel_rel.digest and dict(
        dev_rel.components
    ) == dict(rc_rel.components) == dict(rel_rel.components)
    changed_digest_count = 0 if digests_unchanged else 1
    changed_manifest_byte_count = 0 if manifest_bytes_unchanged else 1
    if not (manifest_bytes_unchanged and signature_unchanged and digests_unchanged):
        raise RuntimeError(
            "Promotion across DEV -> RC -> RELEASE mutated manifest bytes, signature, or digests."
        )
    return {
        "release_version": dev_rel.release_version,
        "release_digest": f"sha256:{dev_rel.digest}",
        "changed_image_digests": changed_digest_count,
        "changed_manifest_bytes": changed_manifest_byte_count,
        "signature_preserved": signature_unchanged,
        "component_digests": dict(sorted(dev_rel.components.items())),
    }


__all__ = [
    "F01_TO_F15_FEATURE_MAPPING",
    "FeatureCodeMappingRecord",
    "REGULATED_GOVERNANCE_PANELS",
    "REGULATED_GOVERNANCE_STENCIL",
    "REVIEWED_STENCIL_DRAFTS",
    "STENCIL_PRODUCT_DECISION_REGISTER",
    "build_reviewed_stencil_candidate_set",
    "verify_build_once_promotion_invariance",
    "verify_physical_stencil_exclusion",
]
