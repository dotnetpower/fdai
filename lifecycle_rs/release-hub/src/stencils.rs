//! Release Hub Stencils, FDAI Console v4 (8 domains / 65 panels) alignment, feature flags, and decisions.

use crate::hub_state::{
    canonical_json_bytes, is_hex_len, is_valid_semver, sha256_hex, CatalogError,
    ReleaseHubState, SYNCED_COMPONENT_DIGESTS,
};
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::Path;

pub const STENCIL_DEFINITION_SCHEMA: &str = "fdai.stencil-definition.v1";
pub const STENCIL_FEATURE_FLAGS_SCHEMA: &str = "fdai.stencil-feature-flags.v1";
pub const CONSOLE_V4_GROUPS: &[&str] = &[
    "overview",
    "operations",
    "agents",
    "governance",
    "evidence",
    "chat",
    "labs",
    "settings",
];

pub const LOCKED_WORKLOADS: &[&str] = &["core-control-plane", "operator-service"];
pub const ALL_WORKLOADS: &[&str] = &[
    "core-control-plane",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
    "operator-service",
];
pub const LOCKED_JOBS: &[&str] = &["analyzer", "inventory"];
pub const ALL_JOBS: &[&str] = &["analyzer", "canary", "cost-collector", "inventory"];
pub const LOCKED_LOOPS: &[&str] = &[
    "anomaly-analyzer",
    "inventory-reconciliation",
    "notification-dispatch",
    "saga-audit",
];
pub const ALL_LOOPS: &[&str] = &[
    "anomaly-analyzer",
    "assurance-twin",
    "code-security",
    "cost-governance",
    "document-ingestion",
    "inventory-reconciliation",
    "notification-dispatch",
    "remediation-execution",
    "saga-audit",
];
pub const LOCKED_ADDONS: &[&str] = &["notifications", "read-only-console"];
pub const ALL_ADDONS: &[&str] = &[
    "enterprise-identity-governance",
    "governed-execution",
    "notifications",
    "policy-administration",
    "read-only-console",
];
pub const LOCKED_PANELS: &[&str] = &["audit", "dashboard", "settings-general"];

struct PanelSpec {
    id: &'static str,
    path: &'static str,
    group: &'static str,
    label: &'static str,
    label_ko: &'static str,
    locked: bool,
    workloads: &'static [&'static str],
    loops: &'static [&'static str],
    addons: &'static [&'static str],
    features: &'static [&'static str],
}

const PANELS: &[PanelSpec] = &[
    // 1. Overview (전체 현황 — 7 panels)
    PanelSpec { id: "dashboard", path: "/dashboard", group: "overview", label: "Dashboard", label_ko: "대시보드", locked: true, workloads: &[], loops: &[], addons: &[], features: &["F01.1", "F02.1", "F03.1"] },
    PanelSpec { id: "dashboard-v2", path: "/dashboard-v2", group: "overview", label: "Resource overview", label_ko: "리소스 현황", locked: false, workloads: &[], loops: &["inventory-reconciliation"], addons: &[], features: &["F02.1", "F03.1"] },
    PanelSpec { id: "operating-outcomes", path: "/operating-outcomes", group: "overview", label: "Operating outcomes", label_ko: "운영 성과", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F03.2"] },
    PanelSpec { id: "control-assurance", path: "/control-assurance", group: "overview", label: "Control assurance", label_ko: "안전 통제 현황", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F03.2", "F12.1"] },
    PanelSpec { id: "verticals", path: "/verticals", group: "overview", label: "Vertical outcomes", label_ko: "영역별 성과", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F03.2"] },
    PanelSpec { id: "cost-governance", path: "/cost-governance", group: "overview", label: "Cost governance", label_ko: "비용 거버넌스", locked: false, workloads: &[], loops: &["cost-governance"], addons: &[], features: &["F09.1", "F09.2"] },
    PanelSpec { id: "llm-cost", path: "/llm-cost", group: "overview", label: "AI model cost", label_ko: "AI 모델 비용", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F09.1"] },
    // 2. Operations (운영 — 18 panels)
    PanelSpec { id: "live", path: "/live", group: "operations", label: "Live monitoring", label_ko: "실시간 모니터링", locked: false, workloads: &[], loops: &["inventory-reconciliation"], addons: &[], features: &["F02.1", "F03.1"] },
    PanelSpec { id: "gpu", path: "/gpu", group: "operations", label: "GPU status", label_ko: "GPU 현황", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F03.3"] },
    PanelSpec { id: "incidents", path: "/incidents", group: "operations", label: "Incident response", label_ko: "장애 대응", locked: false, workloads: &[], loops: &["anomaly-analyzer", "notification-dispatch"], addons: &[], features: &["F04.1", "F08.1"] },
    PanelSpec { id: "code-security", path: "/code-security", group: "operations", label: "Code security", label_ko: "코드 보안", locked: false, workloads: &[], loops: &["code-security"], addons: &[], features: &["F14.1"] },
    PanelSpec { id: "vulnerability-risk", path: "/vulnerability-risk", group: "operations", label: "Vulnerability & risk forecast", label_ko: "취약점 · 위험 예측", locked: false, workloads: &[], loops: &["code-security"], addons: &[], features: &["F14.1"] },
    PanelSpec { id: "configuration-baselines", path: "/configuration-baselines", group: "operations", label: "Configuration baselines", label_ko: "설정 기준 관리", locked: false, workloads: &[], loops: &["inventory-reconciliation"], addons: &[], features: &["F02.1", "F02.3"] },
    PanelSpec { id: "hil-queue", path: "/hil-queue", group: "operations", label: "Approval requests (HIL)", label_ko: "승인 요청", locked: false, workloads: &["isolated-executor"], loops: &["remediation-execution"], addons: &["enterprise-identity-governance", "governed-execution"], features: &["F06.1", "F07.1"] },
    PanelSpec { id: "alert-quality", path: "/alert-quality", group: "operations", label: "Alert quality", label_ko: "알림 품질", locked: false, workloads: &[], loops: &["anomaly-analyzer", "notification-dispatch"], addons: &[], features: &["F04.2", "F08.1"] },
    PanelSpec { id: "detection-readiness", path: "/detection-readiness", group: "operations", label: "Detection coverage", label_ko: "탐지 커버리지", locked: false, workloads: &[], loops: &["anomaly-analyzer", "inventory-reconciliation"], addons: &[], features: &["F03.1", "F04.1"] },
    PanelSpec { id: "conversation-delivery", path: "/conversation-delivery", group: "operations", label: "Notification delivery", label_ko: "알림 전송 이력", locked: false, workloads: &[], loops: &["notification-dispatch"], addons: &[], features: &["F08.2"] },
    PanelSpec { id: "workflow-apps", path: "/workflow-apps", group: "operations", label: "Automation execution", label_ko: "자동화 실행", locked: false, workloads: &["isolated-executor"], loops: &["remediation-execution"], addons: &[], features: &["F07.2"] },
    PanelSpec { id: "automation-blueprints", path: "/automation-blueprints", group: "operations", label: "Automation blueprints", label_ko: "자동화 템플릿", locked: false, workloads: &["isolated-executor"], loops: &["remediation-execution"], addons: &[], features: &["F07.2"] },
    PanelSpec { id: "processes", path: "/processes", group: "operations", label: "Running processes", label_ko: "실행 중인 작업", locked: false, workloads: &["isolated-executor"], loops: &["remediation-execution"], addons: &[], features: &["F07.1"] },
    PanelSpec { id: "scheduler-runs", path: "/scheduler-runs", group: "operations", label: "Scheduled run history", label_ko: "정기 작업 이력", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F03.1"] },
    PanelSpec { id: "background-tasks", path: "/background-tasks", group: "operations", label: "Background tasks", label_ko: "백그라운드 작업", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F03.1"] },
    PanelSpec { id: "scheduled-continuations", path: "/scheduled-continuations", group: "operations", label: "Scheduled follow-ups", label_ko: "예약된 후속 점검", locked: false, workloads: &["isolated-executor"], loops: &["remediation-execution"], addons: &[], features: &["F07.1"] },
    PanelSpec { id: "provision", path: "/provision", group: "operations", label: "Deployment management", label_ko: "배포 관리", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F15.1"] },
    PanelSpec { id: "onboarding", path: "/onboarding", group: "operations", label: "Initial setup", label_ko: "초기 설정", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F01.1", "F15.1"] },
    // 3. Agents (에이전트 — 6 panels)
    PanelSpec { id: "agents", path: "/agents", group: "agents", label: "Agent fleet", label_ko: "에이전트 현황", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F01.1"] },
    PanelSpec { id: "pantheon", path: "/pantheon", group: "agents", label: "Roles & ownership", label_ko: "역할 · 담당 영역", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F01.1"] },
    PanelSpec { id: "handover", path: "/handover", group: "agents", label: "Stewards & handover", label_ko: "담당자 · 인수인계", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F01.3"] },
    PanelSpec { id: "agent-activity", path: "/agent-activity", group: "agents", label: "Agent activity log", label_ko: "에이전트 작업 이력", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F03.1"] },
    PanelSpec { id: "skills", path: "/skills", group: "agents", label: "Agent tools (Skills)", label_ko: "에이전트 도구(스킬)", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F07.1"] },
    PanelSpec { id: "capabilities", path: "/capabilities", group: "agents", label: "Supported capabilities", label_ko: "지원 기능 목록", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F07.1"] },
    // 4. Governance & Knowledge (거버넌스 · 지식 — 13 panels)
    PanelSpec { id: "rules", path: "/rules", group: "governance", label: "Operating rules", label_ko: "운영 규칙", locked: false, workloads: &[], loops: &["anomaly-analyzer"], addons: &[], features: &["F04.1"] },
    PanelSpec { id: "trust-routing", path: "/trust-routing", group: "governance", label: "Auto & AI routing ratio", label_ko: "자동 · AI 처리 비율", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F05.1"] },
    PanelSpec { id: "ontology", path: "/ontology", group: "governance", label: "Ontology", label_ko: "온톨로지", locked: false, workloads: &[], loops: &["inventory-reconciliation"], addons: &[], features: &["F02.2"] },
    PanelSpec { id: "scope", path: "/scope", group: "governance", label: "Managed scope", label_ko: "관리 대상 범위", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F01.1"] },
    PanelSpec { id: "architecture", path: "/architecture", group: "governance", label: "System architecture", label_ko: "시스템 구성도", locked: false, workloads: &[], loops: &["inventory-reconciliation"], addons: &[], features: &["F02.2"] },
    PanelSpec { id: "blast-radius", path: "/blast-radius", group: "governance", label: "Change impact analysis", label_ko: "변경 영향 분석", locked: false, workloads: &[], loops: &["inventory-reconciliation"], addons: &[], features: &["F06.1"] },
    PanelSpec { id: "promotion-gates", path: "/promotion-gates", group: "governance", label: "Automation promotion gates", label_ko: "자동화 적용 심사", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F06.2"] },
    PanelSpec { id: "workflow-builder", path: "/workflow-builder", group: "governance", label: "Automation builder", label_ko: "자동화 편집기", locked: false, workloads: &["isolated-executor"], loops: &["remediation-execution"], addons: &[], features: &["F07.2"] },
    PanelSpec { id: "knowledge", path: "/knowledge", group: "governance", label: "Knowledge management", label_ko: "지식 관리", locked: false, workloads: &["document-ingestion-api", "document-processing-worker"], loops: &["document-ingestion"], addons: &[], features: &["F11.1"] },
    PanelSpec { id: "github", path: "/github", group: "governance", label: "GitHub integration", label_ko: "GitHub 연동", locked: false, workloads: &["document-ingestion-api", "document-processing-worker"], loops: &["document-ingestion"], addons: &[], features: &["F11.1"] },
    PanelSpec { id: "gitlab", path: "/gitlab", group: "governance", label: "GitLab integration", label_ko: "GitLab 연동", locked: false, workloads: &["document-ingestion-api", "document-processing-worker"], loops: &["document-ingestion"], addons: &[], features: &["F11.1"] },
    PanelSpec { id: "azure-devops", path: "/azure-devops", group: "governance", label: "Azure DevOps integration", label_ko: "Azure DevOps 연동", locked: false, workloads: &["document-ingestion-api", "document-processing-worker"], loops: &["document-ingestion"], addons: &[], features: &["F11.1"] },
    PanelSpec { id: "documents", path: "/documents", group: "governance", label: "Operating documents", label_ko: "운영 문서", locked: false, workloads: &["document-ingestion-api", "document-processing-worker"], loops: &["document-ingestion"], addons: &[], features: &["F11.1"] },
    // 5. Evidence (감사 · 이력 — 6 panels)
    PanelSpec { id: "audit", path: "/audit", group: "evidence", label: "Audit log", label_ko: "감사 로그", locked: true, workloads: &[], loops: &["saga-audit"], addons: &[], features: &["F10.1"] },
    PanelSpec { id: "trace", path: "/trace", group: "evidence", label: "Execution trace", label_ko: "실행 추적", locked: false, workloads: &[], loops: &["anomaly-analyzer"], addons: &[], features: &["F04.1", "F10.1"] },
    PanelSpec { id: "rca", path: "/rca", group: "evidence", label: "Root cause analysis (RCA)", label_ko: "원인 분석(RCA)", locked: false, workloads: &[], loops: &["anomaly-analyzer"], addons: &[], features: &["F04.3"] },
    PanelSpec { id: "browser-evidence", path: "/browser-evidence", group: "evidence", label: "Browser evidence", label_ko: "웹 수집 기록", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F10.2"] },
    PanelSpec { id: "conversation-search", path: "/conversation-search", group: "evidence", label: "Conversation search", label_ko: "대화 이력 검색", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F08.2"] },
    PanelSpec { id: "reports", path: "/reports", group: "evidence", label: "Operational reports", label_ko: "운영 보고서", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F10.3"] },
    // 6. AI Chat (AI 채팅 — 1 panel)
    PanelSpec { id: "command-deck-chat", path: "/chat", group: "chat", label: "AI Chat (Command Deck)", label_ko: "AI 채팅", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F08.2"] },
    // 7. Labs (실험실 — 6 panels)
    PanelSpec { id: "labs", path: "/labs", group: "labs", label: "Labs overview", label_ko: "실험실 개요", locked: false, workloads: &[], loops: &[], addons: &[], features: &[] },
    PanelSpec { id: "aks-commerce", path: "/labs/aks-commerce", group: "labs", label: "AKS commerce demo", label_ko: "AKS 데모 환경", locked: false, workloads: &[], loops: &["cost-governance"], addons: &[], features: &["F09.2"] },
    PanelSpec { id: "assurance-twin", path: "/labs/assurance-twin", group: "labs", label: "Assurance twin simulation", label_ko: "사전 검증 시뮬레이션", locked: false, workloads: &[], loops: &["assurance-twin"], addons: &[], features: &["F12.3"] },
    PanelSpec { id: "forecast-learning", path: "/labs/forecast-learning", group: "labs", label: "Forecast model learning", label_ko: "예측 모델 학습", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F03.4", "F13.1"] },
    PanelSpec { id: "conversation-assurance", path: "/labs/conversation-assurance", group: "labs", label: "Conversation quality check", label_ko: "대화 품질 점검", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F08.3"] },
    PanelSpec { id: "context-selection-comparisons", path: "/labs/context-selection-comparisons", group: "labs", label: "Context comparison", label_ko: "참조 정보 비교", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F08.3"] },
    // 8. Settings (설정 — 8 panels)
    PanelSpec { id: "settings-general", path: "/settings/general", group: "settings", label: "General", label_ko: "일반", locked: true, workloads: &[], loops: &[], addons: &[], features: &["F01.1"] },
    PanelSpec { id: "settings-environment", path: "/settings/environment", group: "settings", label: "Environment & collectors", label_ko: "실행 환경 · 수집기", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F01.1", "F15.1"] },
    PanelSpec { id: "settings-models", path: "/settings/models", group: "settings", label: "AI models", label_ko: "AI 모델", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F05.1"] },
    PanelSpec { id: "settings-runtime", path: "/settings/runtime", group: "settings", label: "Runtime policies", label_ko: "운영 정책", locked: false, workloads: &[], loops: &[], addons: &["enterprise-identity-governance", "policy-administration"], features: &["F01.2"] },
    PanelSpec { id: "settings-iam", path: "/settings/iam", group: "settings", label: "Users & permissions", label_ko: "사용자 · 권한", locked: false, workloads: &[], loops: &[], addons: &["enterprise-identity-governance"], features: &["F01.3"] },
    PanelSpec { id: "settings-integrations", path: "/settings/integrations", group: "settings", label: "External integrations", label_ko: "외부 연동", locked: false, workloads: &[], loops: &["notification-dispatch"], addons: &[], features: &["F08.1"] },
    PanelSpec { id: "settings-diagnostics", path: "/settings/diagnostics", group: "settings", label: "System diagnostics", label_ko: "시스템 상태 진단", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F15.2"] },
    PanelSpec { id: "settings-memory", path: "/settings/memory", group: "settings", label: "Saved operator memory", label_ko: "저장된 운영 메모", locked: false, workloads: &[], loops: &[], addons: &[], features: &["F13.1"] },
];

struct FootprintInput<'a> {
    stencil_id: &'a str,
    stencil_digest: &'a str,
    topology_profile: &'a str,
    workloads: &'a [String],
    jobs: &'a [String],
    loops: &'a [String],
    addons: &'a [String],
    panels: &'a [String],
}

fn build_axis_flags(all: &[&str], enabled: &[String]) -> (Vec<String>, Map<String, Value>) {
    let en_set: BTreeSet<&str> = enabled.iter().map(String::as_str).collect();
    let mut disabled = Vec::new();
    let mut flags = Map::new();
    let mut sorted_all: Vec<&str> = all.to_vec();
    sorted_all.sort_unstable();
    for item in sorted_all {
        let on = en_set.contains(item);
        if !on {
            disabled.push(item.to_string());
        }
        flags.insert(item.to_string(), Value::Bool(on));
    }
    (disabled, flags)
}

#[must_use]
fn compile_feature_flags(inp: &FootprintInput<'_>) -> Value {
    let all_panel_ids: Vec<&str> = PANELS.iter().map(|p| p.id).collect();
    let (dis_panels, panel_flags) = build_axis_flags(&all_panel_ids, inp.panels);
    let (dis_loops, loop_flags) = build_axis_flags(ALL_LOOPS, inp.loops);
    let (dis_workloads, workload_flags) = build_axis_flags(ALL_WORKLOADS, inp.workloads);
    let (dis_jobs, job_flags) = build_axis_flags(ALL_JOBS, inp.jobs);
    let (dis_addons, addon_flags) = build_axis_flags(ALL_ADDONS, inp.addons);
    let runtime_env = json!({
        "FDAI_STENCIL_ID": inp.stencil_id,
        "FDAI_STENCIL_ENABLED_PANELS": inp.panels.join(","),
        "FDAI_STENCIL_DISABLED_PANELS": dis_panels.join(","),
        "FDAI_STENCIL_ENABLED_LOOPS": inp.loops.join(","),
        "FDAI_STENCIL_DISABLED_LOOPS": dis_loops.join(","),
        "FDAI_STENCIL_ENABLED_WORKLOADS": inp.workloads.join(","),
        "FDAI_STENCIL_DISABLED_WORKLOADS": dis_workloads.join(","),
        "FDAI_STENCIL_ENABLED_JOBS": inp.jobs.join(","),
        "FDAI_STENCIL_DISABLED_JOBS": dis_jobs.join(","),
        "FDAI_STENCIL_ENABLED_ADDONS": inp.addons.join(","),
        "FDAI_STENCIL_DISABLED_ADDONS": dis_addons.join(","),
        "FDAI_STENCIL_ENFORCE_INACTIVE_MENUS": "1",
    });
    let digest_seed = json!({
        "stencil_id": inp.stencil_id,
        "stencil_digest": inp.stencil_digest,
        "enforcement_mode": "fail-closed",
        "panel_flags": panel_flags,
        "loop_flags": loop_flags,
        "workload_flags": workload_flags,
        "scheduled_job_flags": job_flags,
        "addon_flags": addon_flags,
    });
    let ff_digest = format!("sha256:{}", sha256_hex(&canonical_json_bytes(&digest_seed)));
    json!({
        "schema_version": STENCIL_FEATURE_FLAGS_SCHEMA,
        "stencil_id": inp.stencil_id,
        "stencil_digest": inp.stencil_digest,
        "feature_flags_digest": ff_digest,
        "enforcement_mode": "fail-closed",
        "enabled_panel_ids": inp.panels,
        "disabled_panel_ids": dis_panels,
        "enabled_loops": inp.loops,
        "disabled_loops": dis_loops,
        "enabled_workloads": inp.workloads,
        "disabled_workloads": dis_workloads,
        "enabled_scheduled_jobs": inp.jobs,
        "disabled_scheduled_jobs": dis_jobs,
        "enabled_addons": inp.addons,
        "disabled_addons": dis_addons,
        "panel_flags": panel_flags,
        "loop_flags": loop_flags,
        "workload_flags": workload_flags,
        "scheduled_job_flags": job_flags,
        "addon_flags": addon_flags,
        "runtime_env": runtime_env,
    })
}

#[must_use]
fn evaluate_footprint(inp: &FootprintInput<'_>) -> Value {
    let all_panel_ids: Vec<&str> = PANELS.iter().map(|p| p.id).collect();
    let (omitted_workloads, _) = build_axis_flags(ALL_WORKLOADS, inp.workloads);
    let (omitted_jobs, _) = build_axis_flags(ALL_JOBS, inp.jobs);
    let (omitted_loops, _) = build_axis_flags(ALL_LOOPS, inp.loops);
    let (omitted_panels, _) = build_axis_flags(&all_panel_ids, inp.panels);
    let includes_clamav = inp.workloads.iter().any(|w| w == "document-ingestion-api");
    let includes_exec = inp.workloads.iter().any(|w| w == "isolated-executor");
    let rbac_posture = if includes_exec { "governed-execution" } else { "read-only-observation" };
    let mut rbac_roles = vec!["Reader", "Monitoring Reader", "Log Analytics Reader"];
    if inp.loops.iter().any(|l| l == "cost-governance") {
        rbac_roles.push("Cost Management Reader");
    }
    if includes_exec && inp.addons.iter().any(|a| a == "governed-execution") {
        rbac_roles.push("Scoped Executor Action Role (privileged mutation)");
    }
    let mut active_groups = BTreeSet::new();
    let mut enabled_features = BTreeSet::new();
    let mut w_reasons: BTreeMap<String, Vec<String>> = inp
        .workloads
        .iter()
        .map(|w| (w.clone(), if LOCKED_WORKLOADS.contains(&w.as_str()) { vec![String::from("locked-core")] } else { Vec::new() }))
        .collect();
    let mut l_reasons: BTreeMap<String, Vec<String>> = inp
        .loops
        .iter()
        .map(|l| (l.clone(), if LOCKED_LOOPS.contains(&l.as_str()) { vec![String::from("locked-core")] } else { Vec::new() }))
        .collect();
    for pid in inp.panels {
        if let Some(spec) = PANELS.iter().find(|p| p.id == pid) {
            active_groups.insert(spec.group.to_string());
            for f in spec.features { enabled_features.insert((*f).to_string()); }
            let tag = format!("menu:{pid}");
            for rw in spec.workloads {
                if let Some(list) = w_reasons.get_mut(*rw) {
                    if !list.contains(&tag) { list.push(tag.clone()); }
                }
            }
            for rl in spec.loops {
                if let Some(list) = l_reasons.get_mut(*rl) {
                    if !list.contains(&tag) { list.push(tag.clone()); }
                }
            }
        }
    }
    let feature_flags = compile_feature_flags(inp);
    let removed_sidecars: Vec<&str> = if includes_clamav { Vec::new() } else { vec!["clamav"] };
    let release_labels = vec![
        format!("stencil:{}", inp.stencil_id),
        format!("profile:{}", inp.topology_profile),
        format!("rbac:{rbac_posture}"),
        format!("clamav:{}", if includes_clamav { "included" } else { "omitted" }),
        format!("executor:{}", if includes_exec { "included" } else { "omitted" }),
        format!("workloads:{}", inp.workloads.len()),
        format!("menus:{}", inp.panels.len()),
    ];
    json!({
        "stencil_id": inp.stencil_id,
        "stencil_digest": inp.stencil_digest,
        "topology_profile": inp.topology_profile,
        "workload_count": inp.workloads.len(),
        "total_workloads": ALL_WORKLOADS.len(),
        "omitted_workloads": omitted_workloads,
        "scheduled_job_count": inp.jobs.len(),
        "omitted_scheduled_jobs": omitted_jobs,
        "omitted_loops": omitted_loops,
        "includes_clamav_sidecar": includes_clamav,
        "includes_privileged_executor": includes_exec,
        "enabled_panel_count": inp.panels.len(),
        "total_panel_count": PANELS.len(),
        "omitted_panel_count": omitted_panels.len(),
        "disabled_panel_ids": omitted_panels,
        "disabled_loops": omitted_loops,
        "active_navigation_groups": active_groups.into_iter().collect::<Vec<_>>(),
        "enabled_feature_ids": enabled_features.into_iter().collect::<Vec<_>>(),
        "azure_rbac_posture": rbac_posture,
        "required_azure_roles": rbac_roles,
        "release_labels": release_labels,
        "feature_flags": feature_flags,
        "dependency_reasons": { "workloads": w_reasons, "loops": l_reasons },
        "apollo_diff_vs_full": {
            "retained_workloads": inp.workloads,
            "removed_workloads": omitted_workloads,
            "removed_sidecars": removed_sidecars,
            "retained_scheduled_jobs": inp.jobs,
            "removed_scheduled_jobs": omitted_jobs,
            "retained_loops": inp.loops,
            "removed_loops": omitted_loops,
            "retained_panel_count": inp.panels.len(),
            "removed_panel_count": omitted_panels.len(),
        },
        "terraform_flags": {
            "enable_document_ingestion_workloads": includes_clamav,
            "enable_isolated_executor": includes_exec,
            "product_profile_mode": "observation-first",
        },
        "console_build_command": format!("FDAI_STENCIL_ENABLED_PANELS='{}' cargo build -p fdai-console-v4", inp.panels.join(",")),
    })
}

struct PresetSpec<'a> {
    id: &'a str,
    title: &'a str,
    title_ko: &'a str,
    desc: &'a str,
    desc_ko: &'a str,
    topo: &'a str,
    workloads: &'a [&'a str],
    jobs: &'a [&'a str],
    loops: &'a [&'a str],
    addons: &'a [&'a str],
    panels: &'a [&'a str],
}

fn sorted_unique(items: &[&str]) -> Vec<String> {
    items.iter().map(|s| String::from(*s)).collect::<BTreeSet<_>>().into_iter().collect()
}

fn build_preset(spec: &PresetSpec<'_>) -> Value {
    let ws = sorted_unique(spec.workloads);
    let js = sorted_unique(spec.jobs);
    let ls = sorted_unique(spec.loops);
    let ads = sorted_unique(spec.addons);
    let ps = sorted_unique(spec.panels);
    let stencil = json!({
        "schema_version": STENCIL_DEFINITION_SCHEMA,
        "stencil_id": spec.id,
        "title": spec.title,
        "title_ko": spec.title_ko,
        "description": spec.desc,
        "description_ko": spec.desc_ko,
        "topology_profile": spec.topo,
        "enabled_workloads": ws,
        "enabled_scheduled_jobs": js,
        "enabled_loops": ls,
        "enabled_addons": ads,
        "enabled_panel_ids": ps,
        "authority_granted": false,
    });
    let digest = format!("sha256:{}", sha256_hex(&canonical_json_bytes(&stencil)));
    let fp = evaluate_footprint(&FootprintInput {
        stencil_id: spec.id,
        stencil_digest: &digest,
        topology_profile: spec.topo,
        workloads: &ws,
        jobs: &js,
        loops: &ls,
        addons: &ads,
        panels: &ps,
    });
    json!({ "stencil": stencil, "footprint": fp })
}

#[must_use]
pub fn stencil_catalog_payload(state: &ReleaseHubState) -> Value {
    let lite_panels = &[
        "agent-activity", "agents", "alert-quality", "audit", "command-deck-chat",
        "configuration-baselines", "conversation-delivery", "dashboard", "detection-readiness",
        "incidents", "live", "pantheon", "rules", "settings-general", "settings-integrations",
        "settings-models", "trace",
    ];
    let std_panels = &[
        "agent-activity", "agents", "alert-quality", "architecture", "audit",
        "automation-blueprints", "background-tasks", "blast-radius", "capabilities",
        "command-deck-chat", "configuration-baselines", "control-assurance",
        "conversation-delivery", "conversation-search", "dashboard", "dashboard-v2",
        "detection-readiness", "handover", "hil-queue", "incidents", "live", "onboarding",
        "operating-outcomes", "ontology", "pantheon", "processes", "promotion-gates",
        "provision", "rca", "reports", "rules", "scheduled-continuations", "scheduler-runs",
        "scope", "settings-diagnostics", "settings-environment", "settings-general",
        "settings-iam", "settings-integrations", "settings-memory", "settings-models",
        "skills", "trace", "trust-routing", "verticals", "workflow-apps", "workflow-builder",
    ];
    let all_panel_ids: Vec<&str> = PANELS.iter().map(|p| p.id).collect();
    let presets = vec![
        build_preset(&PresetSpec {
            id: "lite-observe-alert",
            title: "Lite: Agent-Driven Observe, Drift & Alert",
            title_ko: "경량 에디션: 에이전트 주도 변경·장애 감지 및 알림",
            desc: "Minimal Azure resource footprint running Core 15-agent pantheon and Operator API only.",
            desc_ko: "최소한의 Azure 리소스로 Core 15-에이전트 판테온과 Operator API만 실행하는 경량 버전입니다.",
            topo: "lite-observe-alert",
            workloads: LOCKED_WORKLOADS,
            jobs: LOCKED_JOBS,
            loops: LOCKED_LOOPS,
            addons: LOCKED_ADDONS,
            panels: lite_panels,
        }),
        build_preset(&PresetSpec {
            id: "standard-sre",
            title: "Standard: SRE Detection, RCA & Governed Execution",
            title_ko: "표준 에디션: SRE 감지·근본원인 분석 및 승인 기반 조치",
            desc: "Adds RCA, topology workbench, human approval queue (HIL), and isolated executor.",
            desc_ko: "토폴로지 워크벤치, RCA, 인간 승인 대기열(HIL), 격리 실행기를 포함한 표준 에디션입니다.",
            topo: "standard-sre",
            workloads: &["core-control-plane", "isolated-executor", "operator-service"],
            jobs: &["analyzer", "canary", "inventory"],
            loops: &["anomaly-analyzer", "inventory-reconciliation", "notification-dispatch", "remediation-execution", "saga-audit"],
            addons: &["enterprise-identity-governance", "governed-execution", "notifications", "read-only-console"],
            panels: std_panels,
        }),
        build_preset(&PresetSpec {
            id: "full-enterprise",
            title: "Full Enterprise: Complete Platform, Knowledge & FinOps",
            title_ko: "엔터프라이즈 에디션: 지식베이스·FinOps·코드보안 전체 통합",
            desc: "Enables all workloads, document ingestion, cost governance, code security, and assurance twin.",
            desc_ko: "문서 지식 수집, 비용 거버넌스, 코드 보안, 보증 트윈 등 전체 65개 Console v4 메뉴를 활성화합니다.",
            topo: "full-enterprise",
            workloads: ALL_WORKLOADS,
            jobs: ALL_JOBS,
            loops: ALL_LOOPS,
            addons: ALL_ADDONS,
            panels: &all_panel_ids,
        }),
    ];

    let panels_json: Vec<Value> = PANELS
        .iter()
        .map(|p| {
            json!({
                "id": p.id,
                "path": p.path,
                "group": p.group,
                "label": p.label,
                "label_ko": p.label_ko,
                "locked": p.locked,
                "required_workloads": p.workloads,
                "required_loops": p.loops,
                "required_addons": p.addons,
                "feature_ids": p.features,
            })
        })
        .collect();

    let commit_sha = detect_git_head_sha().unwrap_or_else(|| "0".repeat(40));
    json!({
        "detected_source_commit": commit_sha,
        "detected_source_ref": "HEAD",
        "navigation_groups": CONSOLE_V4_GROUPS,
        "registry": state.registry_inventory_payload(),
        "presets": presets,
        "panels": panels_json,
        "workloads": ALL_WORKLOADS,
        "locked_workloads": LOCKED_WORKLOADS,
        "workloads_catalog": [
            {"id": "core-control-plane", "label": "Core Control Plane (15-Agent Pantheon)", "label_ko": "코어 컨트롤 플레인 (15-에이전트 판테온)", "summary": "In-process event bus running all 15 Pantheon agents and Saga audit.", "summary_ko": "15개 판테온 에이전트, T0/T1/T2 신뢰 라우팅, 해시 체인 감사를 구동합니다.", "agents": ["Huginn", "Heimdall", "Tyr", "Mimir", "Odin", "Forseti", "Bragi", "Saga"], "locked": true},
            {"id": "operator-service", "label": "Operator API & Console Read Service", "label_ko": "운영자 API 및 Console 프로젝션 서비스", "summary": "Non-privileged API serving Console projections, alerts, and bounded requests.", "summary_ko": "Console 화면 조회, 인시던트/알림 피드 및 권한 검증 요청을 처리합니다.", "agents": ["Bragi", "Var", "Saga"], "locked": true},
            {"id": "isolated-executor", "label": "Isolated Action Executor", "label_ko": "격리된 조치 실행기 (Isolated Executor)", "summary": "Holds scoped Azure mutation identity to execute approved remediation plans.", "summary_ko": "인간 승인(HIL)을 거친 리소스 변경 및 복구 조치를 수행합니다.", "agents": ["Thor", "Vidar", "Idunn"], "locked": false},
            {"id": "document-ingestion-api", "label": "Document Ingestion Gateway API", "label_ko": "문서 지식 수집 게이트웨이 API", "summary": "Receives uploaded runbooks and architecture documents for knowledge indexing.", "summary_ko": "업로드된 런북 및 아키텍처 문서를 수신하는 수집 게이트웨이입니다.", "agents": ["Huginn", "Heimdall", "Muninn"], "locked": false},
            {"id": "document-processing-worker", "label": "Document Processing Worker (+ ClamAV)", "label_ko": "문서 처리 워커 (+ ClamAV 백신 사이드카)", "summary": "Scans documents with ClamAV and extracts embeddings into pgvector.", "summary_ko": "ClamAV 악성코드 검사 및 문서 파싱·임베딩을 수행합니다.", "agents": ["Muninn", "Norns", "Saga"], "locked": false},
        ],
        "scheduled_jobs": ALL_JOBS,
        "locked_scheduled_jobs": LOCKED_JOBS,
        "scheduled_jobs_catalog": [
            {"id": "inventory", "label": "Inventory Reconciler CronJob", "label_ko": "인벤토리 변경 감지 스케줄러", "summary": "Scheduled Azure Resource Graph & Kubernetes topology discovery tick.", "summary_ko": "주기적으로 리소스 인벤토리와 토폴로지 변경 사항을 동기화합니다.", "agents": ["Huginn", "Tyr"], "locked": true},
            {"id": "analyzer", "label": "Anomaly & Health Analyzer CronJob", "label_ko": "장애 및 헬스 분석 스케줄러", "summary": "Scheduled metric, SLO, and Resource Health deterministic evaluation tick.", "summary_ko": "주기적으로 메트릭·SLO·리소스 헬스를 검사해 이상 징후를 판정합니다.", "agents": ["Heimdall", "Mimir", "Odin"], "locked": true},
            {"id": "canary", "label": "Synthetic Canary Observer CronJob", "label_ko": "카나리 자가 진단 스케줄러", "summary": "Verifies end-to-end control-plane liveness and post-upgrade canary health.", "summary_ko": "컨트롤 플레인의 종단간 응답성과 업그레이드 후 카나리 상태를 검증합니다.", "agents": ["Vidar", "Heimdall"], "locked": false},
            {"id": "cost-collector", "label": "Cost Telemetry Collector CronJob", "label_ko": "비용 텔레메트리 수집 스케줄러", "summary": "Scheduled retail price and billing meter synchronization job.", "summary_ko": "클라우드 과금 데이터 및 소매 요금표를 주기적으로 수집합니다.", "agents": ["Huginn", "Norns"], "locked": false},
        ],
        "loops": ALL_LOOPS,
        "locked_loops": LOCKED_LOOPS,
        "loops_catalog": [
            {"id": "inventory-reconciliation", "label": "Resource Change & Drift Detection", "label_ko": "리소스 변경 및 구성 드리프트 감지", "summary": "Observes Azure Resource Graph snapshots and detects configuration drift.", "summary_ko": "리소스 스냅샷을 수집해 변경·이탈을 감지합니다.", "agents": ["Huginn", "Tyr", "Heimdall"], "locked": true},
            {"id": "anomaly-analyzer", "label": "Failure & Anomaly Detection", "label_ko": "장애 및 이상 징후 감지", "summary": "Evaluates metrics, health, and deterministic T0 rules to open incidents.", "summary_ko": "결정론적(T0) 규칙으로 장애 인시던트를 생성합니다.", "agents": ["Heimdall", "Mimir", "Odin", "Forseti"], "locked": true},
            {"id": "notification-dispatch", "label": "Alert & Briefing Notification Dispatch", "label_ko": "알림 및 브리핑 발송", "summary": "Composes localized incident briefings and dispatches alerts.", "summary_ko": "한국어/영어 장애 브리핑을 작성해 알림을 발송합니다.", "agents": ["Bragi", "Var"], "locked": true},
            {"id": "saga-audit", "label": "Hash-Chained Audit Ledger", "label_ko": "해시 체인 불변 감사 원장", "summary": "Records every observation, detection, and notification in a tamper-evident chain.", "summary_ko": "모든 감지 결과와 알림 증적을 해시 체인 원장에 기록합니다.", "agents": ["Saga"], "locked": true},
            {"id": "remediation-execution", "label": "Governed Remediation & Rollback Loop", "label_ko": "승인 기반 자동 조치 및 롤백 루프", "summary": "Routes high-risk actions through HIL approval, dry-run, and verification.", "summary_ko": "위험 게이트, 인간 승인(HIL), 사전 검증, 실행 및 효과 검증을 수행합니다.", "agents": ["Forseti", "Var", "Thor", "Vidar", "Idunn"], "locked": false},
            {"id": "document-ingestion", "label": "Document Knowledge Ingestion Loop", "label_ko": "문서 및 외부 지식베이스 수집 루프", "summary": "Ingests, scans, and indexes operational documents and Git knowledge sources.", "summary_ko": "운영 문서와 Git 지식 소스를 수집·검증·인덱싱합니다.", "agents": ["Huginn", "Muninn", "Norns"], "locked": false},
            {"id": "cost-governance", "label": "Cloud Cost Governance & FinOps Loop", "label_ko": "클라우드 비용 거버넌스 및 이상 감지", "summary": "Collects billing telemetry, detects spend anomalies, and evaluates SKU sizing.", "summary_ko": "클라우드 비용 급증을 감지하고 SKU 최적화 권고안을 도출합니다.", "agents": ["Mimir", "Odin", "Norns"], "locked": false},
            {"id": "code-security", "label": "Repository Code Security Scanning Loop", "label_ko": "저장소 코드 보안 취약점 스캔 루프", "summary": "Scans connected repositories and surfaces SARIF/dataflow findings.", "summary_ko": "연결된 소스 저장소의 보안 취약점을 정적 분석합니다.", "agents": ["Heimdall", "Forseti", "Saga"], "locked": false},
            {"id": "assurance-twin", "label": "Digital Assurance Twin Loop", "label_ko": "보증 디지털 트윈 시뮬레이션 루프", "summary": "Evaluates change impact and resilience posture against twin state projections.", "summary_ko": "디지털 트윈 투영으로 변경 영향도와 복원력을 사전 검증합니다.", "agents": ["Loki", "Tyr", "Vidar"], "locked": false},
        ],
        "addons": ALL_ADDONS,
        "locked_addons": LOCKED_ADDONS,
        "locked_panels": LOCKED_PANELS,
    })
}

pub fn compose_stencil_response(
    state: &ReleaseHubState,
    body: &Map<String, Value>,
) -> Result<Value, CatalogError> {
    let stencil_id = body
        .get("stencil_id")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty() && s.len() <= 63 && s.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-'))
        .ok_or_else(|| CatalogError::unprocessable("Invalid Stencil compose fields: stencil_id."))?;
    let release_version = body
        .get("release_version")
        .and_then(Value::as_str)
        .unwrap_or("1.0.0");
    if !is_valid_semver(release_version) {
        return Err(CatalogError::unprocessable("release_version must be canonical SemVer."));
    }
    let title = body.get("title").and_then(Value::as_str).unwrap_or(stencil_id);
    let title_ko = body.get("title_ko").and_then(Value::as_str).unwrap_or(title);
    let description = body.get("description").and_then(Value::as_str).unwrap_or("Custom FDAI Stencil");
    let description_ko = body.get("description_ko").and_then(Value::as_str).unwrap_or(description);
    let auto_resolve = body.get("auto_resolve_dependencies").and_then(Value::as_bool).unwrap_or(true);
    let mut topology = body
        .get("topology_profile")
        .and_then(Value::as_str)
        .unwrap_or("lite-observe-alert")
        .to_string();
    if !matches!(topology.as_str(), "lite-observe-alert" | "standard-sre" | "full-enterprise") {
        return Err(CatalogError::unprocessable("Unsupported topology_profile."));
    }

    let mut panels: BTreeSet<String> = LOCKED_PANELS.iter().map(|s| String::from(*s)).collect();
    if let Some(arr) = body.get("requested_panel_ids").and_then(Value::as_array) {
        for item in arr {
            let pid = item.as_str().ok_or_else(|| CatalogError::unprocessable("Invalid panel id."))?;
            if !PANELS.iter().any(|p| p.id == pid) {
                return Err(CatalogError::unprocessable(format!("Unknown panel id: {pid}")));
            }
            panels.insert(pid.to_string());
        }
    }
    let mut workloads: BTreeSet<String> = LOCKED_WORKLOADS.iter().map(|s| String::from(*s)).collect();
    if let Some(arr) = body.get("requested_workloads").and_then(Value::as_array) {
        for item in arr {
            let w = item.as_str().ok_or_else(|| CatalogError::unprocessable("Invalid workload."))?;
            if !ALL_WORKLOADS.contains(&w) { return Err(CatalogError::unprocessable(format!("Unknown workload: {w}"))); }
            workloads.insert(w.to_string());
        }
    }
    let mut jobs: BTreeSet<String> = LOCKED_JOBS.iter().map(|s| String::from(*s)).collect();
    if let Some(arr) = body.get("requested_scheduled_jobs").and_then(Value::as_array) {
        for item in arr {
            let j = item.as_str().ok_or_else(|| CatalogError::unprocessable("Invalid job."))?;
            if !ALL_JOBS.contains(&j) { return Err(CatalogError::unprocessable(format!("Unknown scheduled job: {j}"))); }
            jobs.insert(j.to_string());
        }
    }
    let mut loops: BTreeSet<String> = LOCKED_LOOPS.iter().map(|s| String::from(*s)).collect();
    if let Some(arr) = body.get("requested_loops").and_then(Value::as_array) {
        for item in arr {
            let l = item.as_str().ok_or_else(|| CatalogError::unprocessable("Invalid loop."))?;
            if !ALL_LOOPS.contains(&l) { return Err(CatalogError::unprocessable(format!("Unknown loop: {l}"))); }
            loops.insert(l.to_string());
        }
    }
    let mut addons: BTreeSet<String> = LOCKED_ADDONS.iter().map(|s| String::from(*s)).collect();
    if let Some(arr) = body.get("requested_addons").and_then(Value::as_array) {
        for item in arr {
            let a = item.as_str().ok_or_else(|| CatalogError::unprocessable("Invalid addon."))?;
            if !ALL_ADDONS.contains(&a) { return Err(CatalogError::unprocessable(format!("Unknown addon: {a}"))); }
            addons.insert(a.to_string());
        }
    }

    if auto_resolve {
        if panels.contains("settings-environment") || panels.contains("provision") || panels.contains("onboarding") {
            panels.insert(String::from("settings-environment"));
            panels.insert(String::from("provision"));
            panels.insert(String::from("onboarding"));
        }
        for pid in &panels {
            if let Some(spec) = PANELS.iter().find(|p| p.id == pid) {
                for w in spec.workloads { workloads.insert((*w).to_string()); }
                for l in spec.loops { loops.insert((*l).to_string()); }
                for a in spec.addons { addons.insert((*a).to_string()); }
            }
        }
        if loops.contains("document-ingestion") || workloads.contains("document-ingestion-api") || workloads.contains("document-processing-worker") {
            loops.insert(String::from("document-ingestion"));
            workloads.insert(String::from("document-ingestion-api"));
            workloads.insert(String::from("document-processing-worker"));
        }
        if loops.contains("remediation-execution") || workloads.contains("isolated-executor") {
            loops.insert(String::from("remediation-execution"));
            workloads.insert(String::from("isolated-executor"));
            addons.insert(String::from("enterprise-identity-governance"));
            addons.insert(String::from("governed-execution"));
        }
        if loops.contains("cost-governance") || jobs.contains("cost-collector") {
            loops.insert(String::from("cost-governance"));
            jobs.insert(String::from("cost-collector"));
        }
        if addons.contains("governed-execution") || addons.contains("policy-administration") {
            addons.insert(String::from("enterprise-identity-governance"));
        }
        if loops.contains("document-ingestion") {
            topology = String::from("full-enterprise");
        } else if topology == "lite-observe-alert"
            && (workloads.len() > LOCKED_WORKLOADS.len() || addons.contains("governed-execution") || loops.contains("remediation-execution"))
        {
            topology = String::from("standard-sre");
        }
    } else {
        for pid in &panels {
            if let Some(spec) = PANELS.iter().find(|p| p.id == pid) {
                for w in spec.workloads {
                    if !workloads.contains(*w) {
                        return Err(CatalogError::unprocessable(format!("Panel '{pid}' requires workload '{w}'.")));
                    }
                }
                for l in spec.loops {
                    if !loops.contains(*l) {
                        return Err(CatalogError::unprocessable(format!("Panel '{pid}' requires loop '{l}'.")));
                    }
                }
                for a in spec.addons {
                    if !addons.contains(*a) {
                        return Err(CatalogError::unprocessable(format!("Panel '{pid}' requires add-on '{a}'.")));
                    }
                }
            }
        }
        if topology == "lite-observe-alert"
            && (workloads.iter().any(|w| !LOCKED_WORKLOADS.contains(&w.as_str())) || loops.contains("remediation-execution"))
        {
            return Err(CatalogError::unprocessable(
                "topology_profile 'lite-observe-alert' is observation-only and allows only core workloads.",
            ));
        }
    }

    let ws_vec: Vec<String> = workloads.into_iter().collect();
    let js_vec: Vec<String> = jobs.into_iter().collect();
    let ls_vec: Vec<String> = loops.into_iter().collect();
    let ads_vec: Vec<String> = addons.into_iter().collect();
    let ps_vec: Vec<String> = panels.into_iter().collect();
    let stencil_obj = json!({
        "schema_version": STENCIL_DEFINITION_SCHEMA,
        "stencil_id": stencil_id,
        "title": title,
        "title_ko": title_ko,
        "description": description,
        "description_ko": description_ko,
        "topology_profile": topology,
        "enabled_workloads": ws_vec,
        "enabled_scheduled_jobs": js_vec,
        "enabled_loops": ls_vec,
        "enabled_addons": ads_vec,
        "enabled_panel_ids": ps_vec,
        "authority_granted": false,
    });
    let stencil_digest = format!("sha256:{}", sha256_hex(&canonical_json_bytes(&stencil_obj)));

    let raw_commit = body.get("source_commit").and_then(Value::as_str).unwrap_or("auto").trim();
    let (source_commit, provenance_mode) = if raw_commit.is_empty() || raw_commit == "auto" {
        if let Some(sha) = detect_git_head_sha() {
            (sha, "workspace-git-head (HEAD)")
        } else {
            (sha256_hex(format!("{stencil_digest}:{release_version}").as_bytes())[..40].to_string(), "derived-from-stencil-digest")
        }
    } else if raw_commit == "derived" {
        (sha256_hex(format!("{stencil_digest}:{release_version}").as_bytes())[..40].to_string(), "derived-from-stencil-digest")
    } else if is_hex_len(raw_commit, 40) {
        (raw_commit.to_string(), "explicit-commit-sha")
    } else {
        return Err(CatalogError::unprocessable("source_commit must be 'auto', 'derived', or a 40-char hex SHA."));
    };

    let fp_inp = FootprintInput {
        stencil_id,
        stencil_digest: &stencil_digest,
        topology_profile: &topology,
        workloads: &ws_vec,
        jobs: &js_vec,
        loops: &ls_vec,
        addons: &ads_vec,
        panels: &ps_vec,
    };
    let mut footprint = evaluate_footprint(&fp_inp);
    let feature_flags = footprint.get("feature_flags").cloned().unwrap_or_else(|| compile_feature_flags(&fp_inp));

    let mut images = Map::new();
    for w in &ws_vec {
        if let Some(&(_, dg)) = SYNCED_COMPONENT_DIGESTS.iter().find(|&&(c, _)| c == w.as_str()) {
            images.insert(w.clone(), Value::String(dg.to_string()));
        }
    }
    let manifest = json!({
        "schema_version": "fdai.application-release.v2",
        "release_id": release_version,
        "source_commit": source_commit,
        "platform_tag": format!("v{release_version}-{stencil_id}"),
        "stencil": {
            "stencil_id": stencil_id,
            "stencil_digest": stencil_digest,
            "topology_profile": topology,
            "enabled_workloads": ws_vec,
            "enabled_scheduled_jobs": js_vec,
            "enabled_loops": ls_vec,
            "enabled_panel_ids": ps_vec,
            "feature_flags": feature_flags,
        },
        "feature_flags": feature_flags,
        "images": Value::Object(images),
    });

    if let Some(obj) = footprint.as_object_mut() {
        obj.insert(String::from("source_commit"), Value::String(source_commit));
        obj.insert(String::from("source_provenance_mode"), Value::String(String::from(provenance_mode)));
        obj.insert(String::from("registry_pipeline"), state.registry_inventory_payload());
    }

    Ok(json!({
        "stencil": stencil_obj,
        "footprint": footprint,
        "release_manifest": manifest,
    }))
}

#[must_use]
pub fn stencil_decisions_payload() -> Value {
    json!({
        "product_decision_register": [
            {"id": "PD-01", "decision": "Fixed 15-agent pantheon is immutable across all Stencils."},
            {"id": "PD-02", "decision": "Saga hash-chained audit and Trial watermark cannot be disabled."},
            {"id": "PD-03", "decision": "Inactive menus and loops fail closed at build and runtime."},
        ],
        "reviewed_drafts": {
            "lite-observe-alert": { "topology_profile": "lite-observe-alert", "locked_workloads": LOCKED_WORKLOADS },
            "standard-sre": { "topology_profile": "standard-sre", "workloads": ["core-control-plane", "isolated-executor", "operator-service"] },
            "full-enterprise": { "topology_profile": "full-enterprise", "workloads": ALL_WORKLOADS },
        },
        "feature_mappings": {
            "F01": {"title": "Core Identity & Scope", "panels": ["dashboard", "onboarding", "scope", "settings-general"]},
            "F02": {"title": "Ontology & Drift", "panels": ["live", "architecture", "ontology", "configuration-baselines"]},
            "F04": {"title": "Anomaly Detection & RCA", "panels": ["incidents", "rules", "trace", "rca"]},
            "F06": {"title": "Governed Autonomy & HIL", "panels": ["hil-queue", "blast-radius", "promotion-gates"]},
            "F09": {"title": "Cost Governance", "panels": ["llm-cost", "cost-governance"]},
            "F10": {"title": "Audit & Evidence", "panels": ["audit", "reports", "trace"]},
        },
    })
}

fn detect_git_head_sha() -> Option<String> {
    for base in [Path::new("."), Path::new(".."), Path::new("../..")] {
        let head = base.join(".git/HEAD");
        if let Ok(content) = fs::read_to_string(&head) {
            let trimmed = content.trim();
            if is_hex_len(trimmed, 40) {
                return Some(trimmed.to_string());
            }
            if let Some(ref_path) = trimmed.strip_prefix("ref: ") {
                if let Ok(sha) = fs::read_to_string(base.join(".git").join(ref_path)) {
                    let s = sha.trim();
                    if is_hex_len(s, 40) {
                        return Some(s.to_string());
                    }
                }
            }
        }
    }
    None
}
