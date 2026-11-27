//! Pure-Rust Real-Inventory Advisor & Well-Architected Posture Engine.
//!
//! Evaluates 32 deterministic T0 rules across all five Well-Architected pillars
//! (Cost, Security, Reliability, Operational Excellence, Performance) plus
//! Service & API Retirements directly against live PostgreSQL inventory rows
//! (`inventory_snapshot_resource_row` + `inventory_snapshot_properties` +
//! `ontology_link` + `audit_log`), preserving strict honest `not-measured`
//! semantics whenever PostgreSQL is unconfigured or unreachable.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::sync::{OnceLock, RwLock};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use crate::db::{cell_i64, cell_str, DbHandle};

pub const FORMULA_VERSION: &str = "fdai-advisor-score-v1.2";

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DispositionRecord {
    pub customer_state: String, // open | manually_completed | effect_verified | postponed | dismissed | in_remediation
    pub reason: String,
    pub postponed_until: Option<String>,
    pub updated_at: String,
    pub updated_by: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AdvisorConfigState {
    pub excluded_resource_groups: Vec<String>,
    pub low_cpu_threshold_p95: u32, // 5 | 10 | 15 | 20
    pub lookback_days: u32,         // 7 | 14 | 30 | 60
    pub ri_term: String,            // P1Y | P3Y
    pub min_monthly_savings_usd: f64,
    pub environment_profile: String, // balanced | prod_strict | dev_cost_first
    pub updated_at: String,
}

impl Default for AdvisorConfigState {
    fn default() -> Self {
        Self {
            excluded_resource_groups: Vec::new(),
            low_cpu_threshold_p95: 5,
            lookback_days: 30,
            ri_term: "P3Y".to_string(),
            min_monthly_savings_usd: 0.0,
            environment_profile: "balanced".to_string(),
            updated_at: now_iso(),
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AdvisorAlertItem {
    pub id: String,
    pub name: String,
    pub description: String,
    pub signal: String,
    pub scope: String,
    pub category: String,
    pub subcategory: String,
    pub impact: String,
    pub rule_id: Option<String>,
    pub action_group: String,
    pub channels: Vec<String>,
    pub steward_escalation: bool,
    pub enabled: bool,
    pub created_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AdvisorDigestItem {
    pub id: String,
    pub name: String,
    pub scope: String,
    pub categories: Vec<String>,
    pub frequency: String, // weekly | biweekly | monthly | custom_cron
    pub cron_expression: String,
    pub timezone: String,
    pub locale: String,  // ko | en
    pub persona: String, // executive | engineering | finops
    pub channels: Vec<String>,
    pub enabled: bool,
    pub next_run_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AdvisorAssessmentItem {
    pub id: String,
    pub name: String,
    pub framework: String, // azure-waf | azure-wara | azure-caf | azure-mcsb | finops
    pub workload: String,
    pub status: String, // in_progress | completed
    pub auto_checked: usize,
    pub manual_receipts: usize,
    pub recommendations_found: usize,
    pub score_pct: Option<f64>,
    pub last_refreshed_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct FeedbackItem {
    pub rule_id: String,
    pub helpful: bool,
    pub reason: String,
    pub recorded_at: String,
}

struct CachedDbRaw {
    fetched_at: Instant,
    snapshot_id: Option<String>,
    latest_seen: String,
    resources: Vec<LiveResource>,
    rg_counts: BTreeMap<String, usize>,
    rtype_set: BTreeSet<String>,
    neighbors_map: HashMap<String, Vec<Value>>,
    audit_changes: Vec<Value>,
}

static DB_RAW_CACHE: OnceLock<tokio::sync::RwLock<Option<CachedDbRaw>>> = OnceLock::new();
const DB_CACHE_TTL: Duration = Duration::from_secs(20);

fn db_raw_cache() -> &'static tokio::sync::RwLock<Option<CachedDbRaw>> {
    DB_RAW_CACHE.get_or_init(|| tokio::sync::RwLock::new(None))
}

#[derive(Default)]
struct AdvisorRuntimeOverlay {
    dispositions: HashMap<String, DispositionRecord>, // key = "{rule_id}||{resource_id}"
    config: Option<AdvisorConfigState>,
    alerts: Vec<AdvisorAlertItem>,
    digests: Vec<AdvisorDigestItem>,
    assessments: Vec<AdvisorAssessmentItem>,
    feedback: Vec<FeedbackItem>,
    seeded: bool,
}

pub const MAX_OVERLAY_ITEMS: usize = 256;
pub const MAX_DISPOSITIONS: usize = 2_048;
pub const MAX_FEEDBACK_ITEMS: usize = 1_024;
pub const MIN_GOVERNANCE_REASON_LEN: usize = 8;
pub const BLAST_RADIUS_MAX_TARGETS: usize = 20;

static OVERLAY: OnceLock<RwLock<AdvisorRuntimeOverlay>> = OnceLock::new();

fn overlay() -> &'static RwLock<AdvisorRuntimeOverlay> {
    OVERLAY.get_or_init(|| {
        let mut st = AdvisorRuntimeOverlay::default();
        seed_defaults(&mut st);
        RwLock::new(st)
    })
}

fn read_overlay() -> std::sync::RwLockReadGuard<'static, AdvisorRuntimeOverlay> {
    overlay().read().unwrap_or_else(|e| e.into_inner())
}

fn write_overlay() -> std::sync::RwLockWriteGuard<'static, AdvisorRuntimeOverlay> {
    overlay().write().unwrap_or_else(|e| e.into_inner())
}

fn seed_defaults(st: &mut AdvisorRuntimeOverlay) {
    if st.seeded {
        return;
    }
    st.seeded = true;
    st.config = Some(AdvisorConfigState::default());
    // Honest empty live collections: never fabricate synthetic assessments or fake scores.
    st.alerts = Vec::new();
    st.digests = Vec::new();
    st.assessments = Vec::new();
}

pub fn days_until_iso_date(ymd: &str) -> Option<i64> {
    let parts: Vec<&str> = ymd.trim().split('-').collect();
    if parts.len() != 3 {
        return None;
    }
    let y: i64 = parts[0].parse().ok()?;
    let m: i64 = parts[1].parse().ok()?;
    let d: i64 = parts[2].parse().ok()?;
    if !(1..=12).contains(&m) || !(1..=31).contains(&d) {
        return None;
    }
    let y_adj = if m <= 2 { y - 1 } else { y };
    let era = if y_adj >= 0 { y_adj } else { y_adj - 399 } / 400;
    let yoe = y_adj - era * 400;
    let mp = if m > 2 { m - 3 } else { m + 9 };
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let target_days = era * 146_097 + doe - 719_468;
    let now_days = (now_epoch_s() / 86_400) as i64;
    Some(target_days - now_days)
}

pub fn is_postponement_active(postponed_until: Option<&str>, now_utc_iso: &str) -> bool {
    match postponed_until {
        Some(until) if !until.trim().is_empty() => until > now_utc_iso,
        _ => false,
    }
}

pub fn now_epoch_s() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

pub fn now_iso() -> String {
    let secs = now_epoch_s();
    format_epoch_iso(secs)
}

fn format_epoch_iso(secs: u64) -> String {
    let days = (secs / 86_400) as i64;
    let rem = secs % 86_400;
    let h = rem / 3_600;
    let m = (rem % 3_600) / 60;
    let s = rem % 60;
    // Civil date from days since 1970-01-01 (Howard Hinnant algorithm)
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let y = (yoe as i64) + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let mo = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = if mo <= 2 { y + 1 } else { y };
    format!("{year:04}-{mo:02}-{d:02}T{h:02}:{m:02}:{s:02}Z")
}

#[derive(Clone, Debug)]
struct LiveResource {
    resource_id: String,
    resource_type: String,
    name: String,
    resource_group: String,
    location: String,
    last_seen: String,
    doc: Value,
    props: Value,
    tags: Value,
    sku_name: String,
    sku_tier: String,
    status: String,
    zones: Vec<String>,
}

#[derive(Clone, Debug)]
struct RuleMeta {
    id: &'static str,
    pillar: &'static str,
    subcategory: &'static str,
    title_ko: &'static str,
    title_en: &'static str,
    description_ko: &'static str,
    benefits_ko: &'static str,
    remediation_ko: &'static str,
    learn_more_url: &'static str,
    impact: &'static str, // high | medium | low
    owner_agent: &'static str,
    action_type_ref: &'static str,
    action_label_ko: &'static str,
    automation_mode: &'static str, // fix_pr | hil_guided_fix | shadow_simulation | manual_guidance
    risk_tier: &'static str,       // A0 | A1 | A2 | A3
    downtime_class: &'static str,  // zero_downtime | restart_required | redeploy_required
    waf_ref: &'static str,
    cost_implication_tier: &'static str, // no_cost_impact | low | medium | high | unknown
    cost_factors: &'static [&'static str],
    reliability_tradeoff_ko: &'static str,
    odin_verdict_ko: &'static str,
    retirement_date: Option<&'static str>,
    retirement_days_left: Option<i64>,
    replacement_target: Option<&'static str>,
    pricing_basis: Option<&'static str>,
    target_resource_label_ko: &'static str,
}

#[derive(Clone, Debug, Serialize)]
pub struct EvaluatedResourceInstance {
    pub resource_id: String,
    pub resource_name: String,
    pub resource_type: String,
    pub resource_group: String,
    pub location: String,
    pub environment: String,
    pub workload: String,
    pub cluster_key: Option<String>,
    pub platform_state: String,  // active | compliant
    pub customer_state: String,  // open | manually_completed | effect_verified | postponed | dismissed | in_remediation
    pub effective_bucket: String, // active | completed | postponed | dismissed
    pub disposition_reason: Option<String>,
    pub postponed_until: Option<String>,
    pub yearly_savings_usd: f64,
    pub carbon_kg_co2e: f64,
    pub created_at: String,
    pub last_updated: String,
    pub evidence: Value,
    pub neighbors_count: usize,
    pub neighbors: Vec<Value>,
}

#[derive(Clone, Debug, Serialize)]
pub struct EvaluatedRuleSummary {
    pub id: String,
    pub pillar: String,
    pub subcategory: String,
    pub title_ko: String,
    pub title_en: String,
    pub description_ko: String,
    pub benefits_ko: String,
    pub remediation_ko: String,
    pub learn_more_url: String,
    pub impact: String,
    pub owner_agent: String,
    pub action_type_ref: String,
    pub action_label_ko: String,
    pub automation_mode: String,
    pub risk_tier: String,
    pub downtime_class: String,
    pub waf_ref: String,
    pub cost_implication_tier: String,
    pub cost_factors: Vec<String>,
    pub reliability_tradeoff_ko: String,
    pub odin_verdict_ko: String,
    pub retirement_date: Option<String>,
    pub retirement_days_left: Option<i64>,
    pub replacement_target: Option<String>,
    pub pricing_basis: Option<String>,
    pub estimate_basis: String,
    pub target_resource_label_ko: String,
    pub active_count: usize,
    pub completed_count: usize,
    pub postponed_count: usize,
    pub dismissed_count: usize,
    pub total_evaluated: usize,
    pub completion_pct: f64,
    pub potential_score_increase_pct: f64,
    pub total_yearly_savings_usd: f64,
    pub total_yearly_carbon_kg_co2e: f64,
    pub last_refreshed_at: String,
    pub cluster_hints: Vec<Value>,
    pub instances: Vec<EvaluatedResourceInstance>,
}

#[derive(Clone, Debug)]
pub struct EvaluationSnapshot {
    pub measured: bool,
    pub reason: Option<String>,
    pub snapshot_id: Option<String>,
    pub observed_at: String,
    pub cache_age_seconds: u64,
    pub total_inventory_resources: usize,
    pub excluded_resources_count: usize,
    pub resource_groups: Vec<Value>,
    pub resource_types: Vec<String>,
    pub rules: Vec<EvaluatedRuleSummary>,
    pub overall_score_pct: Option<f64>,
    pub pillar_scores: BTreeMap<String, Value>,
    pub audit_changes: Vec<Value>,
    pub config: AdvisorConfigState,
}

fn rule_catalog() -> &'static [RuleMeta] {
    static RULES: &[RuleMeta] = &[
        // ── RELIABILITY (10) ──
        RuleMeta {
            id: "adv.rel.vm-availability-zones",
            pillar: "reliability",
            subcategory: "availability_zones",
            title_ko: "가상 머신(VM) 가용성 영역(AZ) 배치로 복원력 강화",
            title_en: "Use Availability zones for better resiliency and availability",
            description_ko: "가용성 영역(AZ)은 독립된 전력·냉각·네트워크를 갖춘 데이터센터 단위로 단일 데이터센터 장애로부터 VM 워크로드를 격리합니다.",
            benefits_ko: "특정 가용성 영역 장애 시에도 워크로드 가용성 99.99% SLA 수준 보호",
            remediation_ko: "비-존(Non-zonal) VM을 가용성 영역 지정 또는 Flexible VMSS 다중 존 배포로 마이그레이션하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/virtual-machines/move-virtual-machines-regional-zonal-portal",
            impact: "high",
            owner_agent: "Heimdall",
            action_type_ref: "remediate.enable-zone-redundancy",
            action_label_ko: "가용성 영역으로 마이그레이션",
            automation_mode: "fix_pr",
            risk_tier: "A3",
            downtime_class: "redeploy_required",
            waf_ref: "WAF RE:05 / WARA-VM-01",
            cost_implication_tier: "medium",
            cost_factors: &[
                "다중 가용성 영역에 복수 VM 또는 Flexible VMSS 배치 시 컴퓨트 인스턴스 비용 증가",
                "가용성 영역 간 교차 트래픽 대역폭 과금 발생 가능",
            ],
            reliability_tradeoff_ko: "가용성 대폭 향상(99.9% → 99.99%), 재배포 윈도우 필요",
            odin_verdict_ko: "프로덕션 워크로드는 신뢰성 우선 승인; 임시 CI 워커는 상위 프로비저너 IaC 템플릿 일괄 변경 권고",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "가상 머신",
        },
        RuleMeta {
            id: "adv.rel.vmss-zone-resiliency",
            pillar: "reliability",
            subcategory: "availability_zones",
            title_ko: "VM Scale Set 다중 존 균형 배치 및 헬스 모니터링 활성화",
            title_en: "Configure VMSS in a resilient zone-balanced configuration with health monitoring",
            description_ko: "VMSS가 단일 존에 편중되거나 애플리케이션 헬스 프로브가 누락되면 자동 복구 및 무중단 롤링 업그레이드가 실패합니다.",
            benefits_ko: "존 장애 시 자동 균형 재배치 및 비정상 인스턴스 자동 교체",
            remediation_ko: "VMSS zoneBalance=true 설정 및 Application Health Extension/Probe를 활성화하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/virtual-machine-scale-sets/virtual-machine-scale-sets-health-extension",
            impact: "high",
            owner_agent: "Heimdall",
            action_type_ref: "remediate.enable-zone-redundancy",
            action_label_ko: "VMSS 존 균형·헬스 프로브 구성",
            automation_mode: "fix_pr",
            risk_tier: "A2",
            downtime_class: "zero_downtime",
            waf_ref: "WAF RE:05 / WARA-VMSS-02",
            cost_implication_tier: "no_cost_impact",
            cost_factors: &["동일 인스턴스 수를 다중 존에 균등 분산 시 추가 컴퓨트 비용 없음"],
            reliability_tradeoff_ko: "존 장애 자동 복구 확보",
            odin_verdict_ko: "비용 영향 없는 고효율 신뢰성 개선 항목 — 최우선 적용 권고",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "VM 확장 집합",
        },
        RuleMeta {
            id: "adv.rel.nat-gateway-zones",
            pillar: "reliability",
            subcategory: "availability_zones",
            title_ko: "NAT Gateway 존 중복 구성으로 아웃바운드 중단 방지",
            title_en: "Use Zone-Redundant NAT Gateway configuration to reduce outages",
            description_ko: "단일 영역 NAT Gateway는 해당 영역 장애 시 서브넷 전체 아웃바운드 연결이 끊어지는 단일 장애점(SPOF)이 됩니다.",
            benefits_ko: "영역 장애 시에도 아웃바운드 SNAT 연결 연속성 유지",
            remediation_ko: "NAT Gateway를 존 중복 구성 또는 영역별 독립 NAT Gateway로 분리 배치하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/nat-gateway/nat-availability-zones",
            impact: "high",
            owner_agent: "Heimdall",
            action_type_ref: "remediate.enable-zone-redundancy",
            action_label_ko: "존 중복 NAT 구성 검토",
            automation_mode: "fix_pr",
            risk_tier: "A2",
            downtime_class: "zero_downtime",
            waf_ref: "WAF RE:05 / WARA-NET-03",
            cost_implication_tier: "low",
            cost_factors: &["영역별 NAT Gateway 분리 시 게이트웨이 시간당 고정 비용 소폭 증가"],
            reliability_tradeoff_ko: "아웃바운드 단일 장애점 제거",
            odin_verdict_ko: "네트워크 핵심 경로 SPOF 제거를 위해 우선 적용 권고",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "NAT 게이트웨이",
        },
        RuleMeta {
            id: "adv.rel.storage-zone-redundancy",
            pillar: "reliability",
            subcategory: "availability_zones",
            title_ko: "Storage Account 존 중복(ZRS/GRS) 활성화로 데이터 내구성 강화",
            title_en: "Enable zone redundancy for storage accounts to improve high availability and resiliency",
            description_ko: "LRS(로컬 중복) 스토리지는 단일 데이터센터 장애 시 접근 불가 위험이 존재합니다. ZRS 또는 GZRS 전환으로 3개 가용성 영역에 동기 복제하세요.",
            benefits_ko: "데이터센터 단위 장애 시 무중단 읽기/쓰기 및 12-nines 이상 내구성 확보",
            remediation_ko: "스토리지 계정 복제 유형을 Standard_LRS에서 Standard_ZRS 또는 Standard_GZRS로 전환하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/storage/common/redundancy-migration",
            impact: "high",
            owner_agent: "Heimdall",
            action_type_ref: "remediate.enable-zone-redundancy",
            action_label_ko: "ZRS/GRS 전환 PR 생성",
            automation_mode: "fix_pr",
            risk_tier: "A2",
            downtime_class: "zero_downtime",
            waf_ref: "WAF RE:06 / WARA-STG-01",
            cost_implication_tier: "medium",
            cost_factors: &["LRS 대비 ZRS 스토리지 저장 단가 약 25% 상승"],
            reliability_tradeoff_ko: "데이터 내구성·가용성 대폭 강화(무중단 온라인 마이그레이션 지원)",
            odin_verdict_ko: "상태 저장·CI 아티팩트·백업 스토리지는 ZRS 필수; 임시 스크래치 계정은 예외 검토",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "스토리지 계정",
        },
        RuleMeta {
            id: "adv.rel.storage-soft-delete",
            pillar: "reliability",
            subcategory: "backup_and_dr",
            title_ko: "Blob Soft Delete 및 버전 관리 활성화로 실수 삭제 보호",
            title_en: "Enable Soft Delete to protect your blob data",
            description_ko: "Soft Delete가 비활성화된 스토리지 계정은 애플리케이션 오류나 악의적 삭제로 인한 영구 데이터 손실 위험에 노출됩니다.",
            benefits_ko: "보존 기간(7~365일) 내 삭제·덮어쓰기된 Blob 즉시 복구 가능",
            remediation_ko: "Blob 서비스 데이터 보호에서 Soft Delete(최소 7일 이상) 및 컨테이너 Soft Delete를 활성화하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/storage/blobs/soft-delete-blob-overview",
            impact: "medium",
            owner_agent: "Vidar",
            action_type_ref: "remediate.enable-backup-protection",
            action_label_ko: "Soft Delete 활성화",
            automation_mode: "hil_guided_fix",
            risk_tier: "A1",
            downtime_class: "zero_downtime",
            waf_ref: "WAF RE:09 / WARA-STG-04",
            cost_implication_tier: "low",
            cost_factors: &["보존 기간 동안 삭제된 스냅샷 용량만큼 소액 저장 비용 발생"],
            reliability_tradeoff_ko: "RPO 보호 강화, 서비스 중단 없음",
            odin_verdict_ko: "저비용·무중단 데이터 보호 조치 — 즉시 적용 권고",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "스토리지 계정",
        },
        RuleMeta {
            id: "adv.rel.cae-zone-redundancy",
            pillar: "reliability",
            subcategory: "availability_zones",
            title_ko: "Container Apps 관리 환경(Managed Environment) 존 중복 활성화",
            title_en: "Enable zone redundancy for the managed environment",
            description_ko: "zoneRedundant=false인 Container Apps 환경은 단일 존 장애 시 컨트롤 플레인과 컨테이너 앱 전체가 중단됩니다.",
            benefits_ko: "3개 가용성 영역 분산으로 컨테이너 워크로드 고가용성 보장",
            remediation_ko: "VNet 통합 서브넷과 함께 zoneRedundant=true로 관리 환경을 재구성하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/container-apps/reliability",
            impact: "high",
            owner_agent: "Heimdall",
            action_type_ref: "remediate.enable-zone-redundancy",
            action_label_ko: "존 중복 환경 전환 가이드",
            automation_mode: "fix_pr",
            risk_tier: "A3",
            downtime_class: "redeploy_required",
            waf_ref: "WAF RE:05 / WARA-ACA-01",
            cost_implication_tier: "medium",
            cost_factors: &["존 중복 환경은 전용 VNet 서브넷 및 복수 레플리카 구성 권장"],
            reliability_tradeoff_ko: "환경 재생성 필요(블루/그린 컷오버 권고)",
            odin_verdict_ko: "프로덕션 컨테이너 앱 환경 우선 적용; 블루/그린 ChangeWindow 수립 필요",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "Container Apps 환경",
        },
        RuleMeta {
            id: "adv.rel.aks-availability-zones",
            pillar: "reliability",
            subcategory: "availability_zones",
            title_ko: "AKS 클러스터 및 노드풀 가용성 영역 분산 및 Uptime SLA 적용",
            title_en: "Configure and deploy AKS and related resources to use availability zones",
            description_ko: "AKS 클러스터가 Free 티어이거나 노드풀이 다중 가용성 영역에 분산되지 않으면 API 서버/노드 가용성 SLA를 보장할 수 없습니다.",
            benefits_ko: "컨트롤 플레인 99.95% Uptime SLA 및 존 단위 노드 장애 격리",
            remediation_ko: "AKS SKU를 Standard 티어로 업그레이드하고 시스템/사용자 노드풀에 zones=[1,2,3]을 지정하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/aks/availability-zones",
            impact: "high",
            owner_agent: "Heimdall",
            action_type_ref: "remediate.enable-zone-redundancy",
            action_label_ko: "AKS 존 분산·SLA 구성",
            automation_mode: "fix_pr",
            risk_tier: "A3",
            downtime_class: "zero_downtime",
            waf_ref: "WAF RE:05 / WARA-AKS-01",
            cost_implication_tier: "low",
            cost_factors: &["Standard 티어 컨트롤 플레인 관리 비용($0.10/시간) 발생"],
            reliability_tradeoff_ko: "신규 노드풀 추가 후 드레인 방식으로 무중단 전환 가능",
            odin_verdict_ko: "운영 클러스터는 Standard SLA 필수; 데모/실험실(lab) 클러스터는 예외 가능",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "Kubernetes 서비스",
        },
        RuleMeta {
            id: "adv.rel.disk-zone-alignment",
            pillar: "reliability",
            subcategory: "availability_zones",
            title_ko: "Azure Managed Disk 존 배치 및 VM 존 정합성 확보",
            title_en: "Ensure Azure Disks are in the same zone as your VM for higher resiliency and availability",
            description_ko: "LRS 비-존 디스크는 데이터센터 장애에 취약하며, 연결된 VM과 존이 불일치할 경우 장애 복구 및 지연 성능이 저하됩니다.",
            benefits_ko: "VM-디스크 동일 존 격리 또는 ZRS 디스크를 통한 영역 장애 복원력 확보",
            remediation_ko: "스냅샷 기반으로 ZRS 디스크 또는 대상 VM과 동일 가용성 영역으로 디스크를 배치하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/virtual-machines/disks-redundancy",
            impact: "high",
            owner_agent: "Heimdall",
            action_type_ref: "remediate.enable-zone-redundancy",
            action_label_ko: "디스크 존 정합성 수정",
            automation_mode: "fix_pr",
            risk_tier: "A2",
            downtime_class: "restart_required",
            waf_ref: "WAF RE:06 / WARA-DISK-01",
            cost_implication_tier: "low",
            cost_factors: &["ZRS 관리 디스크 전환 시 저장 단가 소폭 상승"],
            reliability_tradeoff_ko: "디스크 교체 시 짧은 VM 재시작 필요",
            odin_verdict_ko: "영구 데이터 디스크 우선 적용, 임시 CI 디스크는 템플릿 기준 관리",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "관리 디스크",
        },
        RuleMeta {
            id: "adv.rel.vnet-nat-gateway",
            pillar: "reliability",
            subcategory: "network_resilience",
            title_ko: "서브넷 아웃바운드 연결에 NAT Gateway 적용 (SNAT 고갈 방지)",
            title_en: "Use NAT gateway for outbound connectivity",
            description_ko: "기본 아웃바운드 액세스는 Azure에서 단계적으로 폐지 예정이며, 다수 워크로드 공유 시 SNAT 포트 고갈로 외부 API 호출 실패가 발생합니다.",
            benefits_ko: "예측 가능한 정적 아웃바운드 IP 및 IP당 64,512개 SNAT 포트 확보",
            remediation_ko: "워크로드 서브넷(Private Endpoint 전용 제외)에 Standard NAT Gateway를 연결하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/nat-gateway/nat-overview",
            impact: "medium",
            owner_agent: "Heimdall",
            action_type_ref: "ops.upsert-network-rule",
            action_label_ko: "서브넷 NAT Gateway 연결",
            automation_mode: "fix_pr",
            risk_tier: "A2",
            downtime_class: "zero_downtime",
            waf_ref: "WAF RE:05 / WARA-NET-07",
            cost_implication_tier: "no_cost_impact",
            cost_factors: &["기존 VNet 내 NAT Gateway 공유 시 추가 고정 비용 없음"],
            reliability_tradeoff_ko: "아웃바운드 연결 안정성 대폭 개선",
            odin_verdict_ko: "SNAT 고갈 장애 예방을 위해 워크로드 서브넷 적용 권고",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "가상 네트워크 서브넷",
        },
        RuleMeta {
            id: "adv.rel.app-service-zone",
            pillar: "reliability",
            subcategory: "availability_zones",
            title_ko: "App Service Plan 존 중복 지원 티어 및 분산 구성",
            title_en: "Use zone-supported App Service Plan",
            description_ko: "단일 영역 또는 존 중복이 비활성화된 App Service Plan은 데이터센터 장애 시 웹/함수 앱 전체가 중단됩니다.",
            benefits_ko: "3개 영역 분산 배포로 웹/함수 앱 가용성 강화",
            remediation_ko: "Premium v3 / FlexConsumption 존 중복 옵션이 활성화된 플랜으로 구성하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/reliability/reliability-app-service",
            impact: "high",
            owner_agent: "Heimdall",
            action_type_ref: "remediate.enable-zone-redundancy",
            action_label_ko: "존 지원 플랜 전환",
            automation_mode: "fix_pr",
            risk_tier: "A2",
            downtime_class: "zero_downtime",
            waf_ref: "WAF RE:05 / WARA-APP-01",
            cost_implication_tier: "medium",
            cost_factors: &["존 중복 활성화 시 최소 2~3개 인스턴스 과금 적용 가능"],
            reliability_tradeoff_ko: "앱 가용성 SLA 향상",
            odin_verdict_ko: "프로덕션 웹/함수 워크로드 우선 전환",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "App Service 플랜",
        },
        // ── SERVICE RETIREMENTS (3) ──
        RuleMeta {
            id: "adv.ret.keyvault-api-2026",
            pillar: "reliability",
            subcategory: "service_retirement",
            title_ko: "[은퇴] Azure Key Vault 구버전 API(2026-02-01 이전) 지원 종료 대응",
            title_en: "Azure Key Vault API versions prior to 2026-02-01 are being retired",
            description_ko: "2026-02-01 이전 Key Vault 데이터/관리 플레인 API 버전이 은퇴 예정입니다. SDK 및 IaC 템플릿의 apiVersion을 최신 안정 버전으로 업그레이드해야 합니다.",
            benefits_ko: "API 은퇴로 인한 시크릿·인증서 조회 실패 및 서비스 전면 중단 예방",
            remediation_ko: "Key Vault 호출 클라이언트 SDK, Terraform azurerm 프로바이더, ARM/Bicep apiVersion을 2026-02-01 이상으로 갱신하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/key-vault/general/overview",
            impact: "high",
            owner_agent: "Heimdall",
            action_type_ref: "tool.open-fix-pr",
            action_label_ko: "API 버전 업그레이드 PR 생성",
            automation_mode: "fix_pr",
            risk_tier: "A2",
            downtime_class: "zero_downtime",
            waf_ref: "WAF RE:01 / Retirement",
            cost_implication_tier: "no_cost_impact",
            cost_factors: &["API 버전 업그레이드에 따른 추가 Azure 과금 없음"],
            reliability_tradeoff_ko: "미조치 시 은퇴일 이후 시크릿 접근 실패 확정",
            odin_verdict_ko: "기한 엄수 필수 항목 — 비용 영향 0, 즉시 Fix PR 및 호출 로그 점검 착수",
            retirement_date: Some("2026-12-31"),
            retirement_days_left: Some(34),
            replacement_target: Some("Key Vault API 2026-02-01+"),
            pricing_basis: None,
            target_resource_label_ko: "Key Vault",
        },
        RuleMeta {
            id: "adv.ret.logs-ingestion-api",
            pillar: "reliability",
            subcategory: "service_retirement",
            title_ko: "[은퇴] HTTP Data Collector API → Logs Ingestion API(DCR) 마이그레이션",
            title_en: "Migrate from the HTTP Data Collector API to the Logs ingestion API",
            description_ko: "레거시 HTTP Data Collector API가 지원 종료됩니다. Data Collection Rule(DCR) 기반 Logs Ingestion API로 전환하지 않으면 커스텀 로그 수집이 중단됩니다.",
            benefits_ko: "DCR 기반 변환·필터링으로 로그 수집 비용 절감 및 중단 없는 관측성 유지",
            remediation_ko: "Log Analytics 작업 영역에 Data Collection Rule(DCR) 및 DCE를 연결하고 수집 클라이언트를 Logs Ingestion API로 전환하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/azure-monitor/logs/logs-ingestion-api-overview",
            impact: "high",
            owner_agent: "Heimdall",
            action_type_ref: "remediate.enable-diagnostic-settings",
            action_label_ko: "DCR 마이그레이션 계획 생성",
            automation_mode: "fix_pr",
            risk_tier: "A2",
            downtime_class: "zero_downtime",
            waf_ref: "WAF OE:07 / Retirement",
            cost_implication_tier: "no_cost_impact",
            cost_factors: &["DCR 필터링 적용 시 오히려 불필요 로그 수집 비용 절감 가능"],
            reliability_tradeoff_ko: "미조치 시 모니터링·감사 로그 파이프라인 단절",
            odin_verdict_ko: "D-18 임박 긴급 은퇴 항목 — DCR 미연결 작업 영역 즉시 우선 전환",
            retirement_date: Some("2026-12-15"),
            retirement_days_left: Some(18),
            replacement_target: Some("Azure Monitor Logs Ingestion API (DCR)"),
            pricing_basis: None,
            target_resource_label_ko: "Log Analytics 작업 영역",
        },
        RuleMeta {
            id: "adv.ret.basic-network-sku",
            pillar: "reliability",
            subcategory: "service_retirement",
            title_ko: "[은퇴] Basic SKU Public IP · Load Balancer → Standard SKU 업그레이드",
            title_en: "Upgrade Basic SKU Public IP and Load Balancer before retirement",
            description_ko: "Basic SKU 네트워크 리소스는 가용성 영역과 기본 보안 폐쇄(Secure-by-default)를 지원하지 않으며 공식 은퇴 대상입니다.",
            benefits_ko: "존 중복성·99.99% SLA 및 은퇴로 인한 네트워크 단절 방지",
            remediation_ko: "Basic SKU Public IP 및 Load Balancer를 Standard SKU로 업그레이드하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/virtual-network/ip-services/public-ip-basic-upgrade-guidance",
            impact: "high",
            owner_agent: "Heimdall",
            action_type_ref: "ops.upsert-network-rule",
            action_label_ko: "Standard SKU 업그레이드",
            automation_mode: "fix_pr",
            risk_tier: "A2",
            downtime_class: "restart_required",
            waf_ref: "WAF RE:05 / Retirement",
            cost_implication_tier: "low",
            cost_factors: &["Standard Static IP 시간당 소액 과금 발생"],
            reliability_tradeoff_ko: "은퇴 전 Standard 전환 필수",
            odin_verdict_ko: "Basic SKU 잔존 리소스는 즉시 Standard 전환 계획 수립",
            retirement_date: Some("2027-03-31"),
            retirement_days_left: Some(124),
            replacement_target: Some("Standard SKU Public IP / Load Balancer"),
            pricing_basis: None,
            target_resource_label_ko: "네트워크 리소스",
        },
        // ── COST (6) ──
        RuleMeta {
            id: "adv.cost.vm-rightsizing",
            pillar: "cost",
            subcategory: "right_sizing",
            title_ko: "저활용 · 중지 상태 가상 머신(VM) 라이트사이징 및 자동 종료 구성",
            title_en: "Right-size or shutdown underutilized virtual machines",
            description_ko: "설정된 CPU P95 임계치 미만 또는 장기간 유휴/비운영 VM에 자동 종료 스케줄과 적정 SKU를 적용해 컴퓨트 비용과 탄소 배출을 즉시 절감합니다.",
            benefits_ko: "불필요한 컴퓨트 과금 제거 및 연간 탄소 배출량(kgCO2e) 동시 감축",
            remediation_ko: "비운영 VM에 자동 종료 스케줄(compute.vm-shutdown-schedule)을 연결하거나 상위 프로비저너 SKU를 적정 크기로 조정하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/advisor/advisor-cost-recommendations",
            impact: "high",
            owner_agent: "Njord",
            action_type_ref: "remediate.right-size",
            action_label_ko: "라이트사이징 · 자동 종료 적용",
            automation_mode: "hil_guided_fix",
            risk_tier: "A2",
            downtime_class: "restart_required",
            waf_ref: "WAF CO:07 / FinOps",
            cost_implication_tier: "no_cost_impact",
            cost_factors: &["연간 컴퓨트 지출 절감(Retail 정가 기준, 설정된 CPU 임계치 반영)"],
            reliability_tradeoff_ko: "Freyr 용량 예측 확인: 피크 트래픽 스파이크 없는 비운영/유휴 VM 대상 — SLO 영향 낮음",
            odin_verdict_ko: "Njord 절감 + Freyr 용량 여유 검증 통과; dev/lab 환경 우선 적용 권고",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: Some("Retail"),
            target_resource_label_ko: "가상 머신",
        },
        RuleMeta {
            id: "adv.cost.vm-reserved-instance",
            pillar: "cost",
            subcategory: "commitments",
            title_ko: "상시 가동 VM 대상 Reserved Instance(RI) 약정 구매 검토",
            title_en: "Consider virtual machine reserved instance to save over the on-demand costs",
            description_ko: "지속 가동 중인 VM 및 AKS 노드풀 컴퓨트 사용량에 1년(P1Y) 또는 3년(P3Y) 예약 인스턴스를 적용하면 종량제 대비 32%~58% 절감할 수 있습니다.",
            benefits_ko: "동일 워크로드 성능 유지 상태에서 계약 단가(Contractual) 기반 대규모 고정비 절감",
            remediation_ko: "선택한 약정 기간(P1Y/P3Y) 및 Lookback(7/30/60일) 분석 결과를 검토해 예약 구매를 승인하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/cost-management-billing/reservations/save-compute-costs-reservations",
            impact: "high",
            owner_agent: "Njord",
            action_type_ref: "tool.open-fix-pr",
            action_label_ko: "RI 약정 시뮬레이션 · 승인 요청",
            automation_mode: "manual_guidance",
            risk_tier: "A3",
            downtime_class: "zero_downtime",
            waf_ref: "WAF CO:05 / FinOps",
            cost_implication_tier: "no_cost_impact",
            cost_factors: &["약정 기간 내 안정적 사용량 유지 시 최대 절감(중도 해지·교환 정책 확인 필요)"],
            reliability_tradeoff_ko: "인프라 변경 없음(결제 할인 모델 전환) — 가용성/성능 영향 0",
            odin_verdict_ko: "무중단 순수 재무 최적화; 30일 이상 안정 가동 워크로드 기준 P1Y/P3Y 비교 후 재무 승인",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: Some("Contractual"),
            target_resource_label_ko: "구독 · 상시 컴퓨트",
        },
        RuleMeta {
            id: "adv.cost.savings-plan",
            pillar: "cost",
            subcategory: "commitments",
            title_ko: "컴퓨트 통합 Azure Savings Plan 약정으로 유연한 단가 절감",
            title_en: "Consider purchasing a savings plan to unlock lower prices",
            description_ko: "VM, Container Apps, AKS 노드풀, Functions 등 다양한 컴퓨트 패밀리에 걸쳐 시간당 약정 할인을 자동 적용해 리전·SKU 변경 유연성을 확보합니다.",
            benefits_ko: "SKU/리전 변경 시에도 자동 할인 유지(RI 대비 높은 아키텍처 유연성)",
            remediation_ko: "시간당 기준 사용량(Baseline)에 맞춘 1년/3년 Savings Plan 약정안을 검토하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/cost-management-billing/savings-plan/savings-plan-compute-overview",
            impact: "high",
            owner_agent: "Njord",
            action_type_ref: "tool.open-fix-pr",
            action_label_ko: "Savings Plan 검토",
            automation_mode: "manual_guidance",
            risk_tier: "A3",
            downtime_class: "zero_downtime",
            waf_ref: "WAF CO:05 / FinOps",
            cost_implication_tier: "no_cost_impact",
            cost_factors: &["RI와 중복 약정 방지를 위해 순수 종량제 잔여 사용량 기준으로 산출"],
            reliability_tradeoff_ko: "인프라 무변경 — 가용성 영향 0",
            odin_verdict_ko: "컨테이너/VM 혼합 환경에서 RI보다 유연성이 높음 — RI와 합산 시뮬레이션 권고",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: Some("Contractual"),
            target_resource_label_ko: "구독 · 컴퓨트 풀",
        },
        RuleMeta {
            id: "adv.cost.unattached-disks",
            pillar: "cost",
            subcategory: "orphan_cleanup",
            title_ko: "미연결(Unattached) 관리 디스크 검토 및 안전 정리",
            title_en: "Review unattached disks and decide whether you still need them",
            description_ko: "어느 VM에도 연결되지 않은 고아 Managed Disk는 매월 스토리지 고정 비용을 유발합니다. 스냅샷 백업 후 안전 정리 대상으로 분류합니다.",
            benefits_ko: "즉시 스토리지 낭비 제거 및 스냅샷 아카이브 전환으로 70% 이상 절감",
            remediation_ko: "중요 데이터 여부 확인 후 스냅샷 생성 및 미연결 디스크 정리(remediate.remove-orphan-resource)를 실행하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/virtual-machines/disks-find-unattached-portal",
            impact: "medium",
            owner_agent: "Njord",
            action_type_ref: "remediate.remove-orphan-resource",
            action_label_ko: "백업 후 고아 디스크 정리",
            automation_mode: "hil_guided_fix",
            risk_tier: "A2",
            downtime_class: "zero_downtime",
            waf_ref: "WAF CO:07 / FinOps",
            cost_implication_tier: "no_cost_impact",
            cost_factors: &["미연결 Premium/Standard 디스크 월 고정 과금 즉시 제거"],
            reliability_tradeoff_ko: "사전 스냅샷 생성 및 Vidar 복원 경로 확보 시 데이터 손실 위험 최소화",
            odin_verdict_ko: "Quick-Win 비용 정리 후보; 7대 안전장치(스냅샷 롤백) 확인 후 HIL 승인 실행",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: Some("Retail"),
            target_resource_label_ko: "관리 디스크",
        },
        RuleMeta {
            id: "adv.cost.unused-public-ip",
            pillar: "cost",
            subcategory: "orphan_cleanup",
            title_ko: "미연결 유휴 Public IP 주소 해제",
            title_en: "Delete unused public IP addresses to avoid idle charges",
            description_ko: "NIC, Load Balancer, NAT Gateway 어디에도 바인딩되지 않은 유휴 Public IP가 지속 과금되고 있습니다.",
            benefits_ko: "유휴 IP 과금 제거 및 불필요한 외부 공격 표면 축소",
            remediation_ko: "예약 IP 유지 목적이 아닌 미연결 Public IP를 안전하게 해제하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/virtual-network/ip-services/public-ip-addresses",
            impact: "low",
            owner_agent: "Njord",
            action_type_ref: "remediate.remove-orphan-resource",
            action_label_ko: "유휴 Public IP 해제",
            automation_mode: "hil_guided_fix",
            risk_tier: "A1",
            downtime_class: "zero_downtime",
            waf_ref: "WAF CO:07 / FinOps",
            cost_implication_tier: "no_cost_impact",
            cost_factors: &["Standard Static Public IP당 연 약 $44 고정비 절감"],
            reliability_tradeoff_ko: "미연결 리소스이므로 활성 트래픽 영향 없음(DNS 레코드 참조 사전 점검 포함)",
            odin_verdict_ko: "저위험 Quick-Win 정리 항목 — DNS 참조 없음 확인 후 자동 정리 후보",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: Some("Retail"),
            target_resource_label_ko: "공용 IP 주소",
        },
        RuleMeta {
            id: "adv.cost.llm-capacity-opt",
            pillar: "cost",
            subcategory: "ai_finops",
            title_ko: "Azure OpenAI / LLM 모델 배포 용량 및 라우팅 비용 최적화",
            title_en: "Optimize Azure OpenAI model deployment capacity and routing tiers",
            description_ko: "고용량 LLM 모델 배포(GlobalStandard/PTU)의 TPM 할당량 대비 실제 사용률을 점검하고 저복잡도 작업의 경량 모델 라우팅 전환을 권장합니다.",
            benefits_ko: "AI 토큰·용량 단가 절감 및 불필요한 추론 전력·탄소 감축",
            remediation_ko: "배포별 TPM/RPM 할당 한도를 실측 피크에 맞춰 조정하고 T0/T1 결정론적 캐시 적중률을 높이세요.",
            learn_more_url: "https://learn.microsoft.com/azure/ai-services/openai/how-to/provisioned-throughput-onboarding",
            impact: "medium",
            owner_agent: "Njord",
            action_type_ref: "ops.switch-t2-proposer-route",
            action_label_ko: "LLM 용량·라우팅 최적화",
            automation_mode: "shadow_simulation",
            risk_tier: "A1",
            downtime_class: "zero_downtime",
            waf_ref: "WAF CO:10 / AI FinOps",
            cost_implication_tier: "no_cost_impact",
            cost_factors: &["초과 TPM 예약 축소 및 T0/T1 결정론적 우선 처리로 AI 호출 비용 절감"],
            reliability_tradeoff_ko: "레이트 리밋(429) 방지 안전 마진 30% 유지 필요",
            odin_verdict_ko: "T2 품질 게이트 회귀 없음 확인 후 점진적 라우팅 조정 권고",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: Some("Contractual"),
            target_resource_label_ko: "LLM 모델 배포",
        },
        // ── SECURITY (5) ──
        RuleMeta {
            id: "adv.sec.keyvault-hardening",
            pillar: "security",
            subcategory: "data_protection",
            title_ko: "Key Vault Purge Protection · RBAC 권한 모델 · 프라이빗 접근 강화",
            title_en: "Enable Purge Protection, RBAC authorization, and disable public network access on Key Vault",
            description_ko: "Purge Protection 미설정 또는 공용 네트워크 허용 상태의 Key Vault는 영구 삭제 공격 및 외부 노출 위험이 높습니다.",
            benefits_ko: "시크릿·암호화 키의 악의적 영구 삭제 차단 및 제로 트러스트 접근 제어",
            remediation_ko: "enablePurgeProtection=true, enableRbacAuthorization=true, publicNetworkAccess=Disabled를 적용하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/key-vault/general/security-features",
            impact: "high",
            owner_agent: "Forseti",
            action_type_ref: "remediate.enable-purge-protection",
            action_label_ko: "Key Vault 보안 강화 PR",
            automation_mode: "fix_pr",
            risk_tier: "A2",
            downtime_class: "zero_downtime",
            waf_ref: "WAF SE:07 / MCSB DP-8",
            cost_implication_tier: "no_cost_impact",
            cost_factors: &["Purge Protection 및 RBAC 전환 자체의 추가 비용 없음"],
            reliability_tradeoff_ko: "공용 접근 차단 전 Private Endpoint DNS 해석 경로 사전 검증 필수",
            odin_verdict_ko: "보안 최우선 통제 항목; Private Endpoint 존재 확인 후 즉시 적용",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "Key Vault",
        },
        RuleMeta {
            id: "adv.sec.storage-public-tls",
            pillar: "security",
            subcategory: "network_and_encryption",
            title_ko: "Storage Account 공용 Blob 차단 · HTTPS 전용 · 최소 TLS 1.2 강제",
            title_en: "Restrict public network access and enforce HTTPS/TLS 1.2 on Storage Accounts",
            description_ko: "공용 네트워크 접근 또는 익명 Blob 읽기, 구버전 TLS 허용 시 데이터 유출 및 중간자 공격 위험이 증가합니다.",
            benefits_ko: "전송 계층 암호화 표준 준수 및 비인가 외부 데이터 접근 원천 차단",
            remediation_ko: "allowBlobPublicAccess=false, supportsHttpsTrafficOnly=true, minimumTlsVersion=TLS1_2 및 Private Endpoint를 적용하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/storage/common/storage-security-guide",
            impact: "high",
            owner_agent: "Forseti",
            action_type_ref: "remediate.disable-public-access",
            action_label_ko: "스토리지 공용 차단·TLS 강화",
            automation_mode: "hil_guided_fix",
            risk_tier: "A2",
            downtime_class: "zero_downtime",
            waf_ref: "WAF SE:06 / MCSB NS-2",
            cost_implication_tier: "no_cost_impact",
            cost_factors: &["TLS 1.2 및 익명 차단 설정 추가 비용 없음"],
            reliability_tradeoff_ko: "레거시 클라이언트 TLS 1.0/1.1 호출 유무 사전 로그 검증 필요",
            odin_verdict_ko: "보안 필수 기준 — 영향 클라이언트 없음 검증 후 즉시 적용",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "스토리지 계정",
        },
        RuleMeta {
            id: "adv.sec.vm-host-encryption-id",
            pillar: "security",
            subcategory: "identity_and_compute",
            title_ko: "가상 머신(VM) 호스트 암호화 및 Managed Identity 적용",
            title_en: "Enable Encryption at Host and Managed Identity on Virtual Machines",
            description_ko: "호스트 수준 암호화가 비활성화되거나 Managed Identity가 없는 VM은 임시 디스크/캐시 노출 및 정적 자격 증명 유출 위험이 존재합니다.",
            benefits_ko: "OS·임시 디스크 엔드투엔드 암호화 및 비밀번호 없는 Entra ID 인증",
            remediation_ko: "VM에 System/User Assigned Managed Identity를 부여하고 encryptionAtHost=true를 활성화하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/virtual-machines/disks-enable-host-based-encryption-portal",
            impact: "high",
            owner_agent: "Forseti",
            action_type_ref: "remediate.assign-identity",
            action_label_ko: "Managed Identity·암호화 구성",
            automation_mode: "fix_pr",
            risk_tier: "A2",
            downtime_class: "restart_required",
            waf_ref: "WAF SE:05 / MCSB IM-1",
            cost_implication_tier: "no_cost_impact",
            cost_factors: &["Managed Identity 및 플랫폼 키 기반 Host Encryption 추가 비용 없음"],
            reliability_tradeoff_ko: "Host Encryption 활성화 시 VM 일시 중지/재할당 필요",
            odin_verdict_ko: "정적 시크릿 제거를 위해 Managed Identity 우선 적용, Host Encryption은 ChangeWindow 반영",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "가상 머신",
        },
        RuleMeta {
            id: "adv.sec.acr-hardening",
            pillar: "security",
            subcategory: "supply_chain",
            title_ko: "Container Registry 관리자 계정 비활성화 및 네트워크 접근 제한",
            title_en: "Disable admin user and restrict public access on Azure Container Registry",
            description_ko: "ACR 공유 관리자 계정이 활성화되거나 공용 접근이 열려 있으면 컨테이너 이미지 공급망 변조 위험이 높아집니다.",
            benefits_ko: "Entra ID RBAC 기반 이미지 Pull/Push 통제 및 공급망 무결성 강화",
            remediation_ko: "adminUserEnabled=false로 전환하고 Managed Identity 기반 AcrPull 권한 및 Private Endpoint를 구성하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/container-registry/container-registry-best-practices",
            impact: "medium",
            owner_agent: "Forseti",
            action_type_ref: "remediate.restrict-network-access",
            action_label_ko: "ACR 관리자 비활성화·보안 강화",
            automation_mode: "fix_pr",
            risk_tier: "A2",
            downtime_class: "zero_downtime",
            waf_ref: "WAF SE:11 / MCSB IM-3",
            cost_implication_tier: "low",
            cost_factors: &["Private Endpoint 적용 시 Premium ACR SKU 필요"],
            reliability_tradeoff_ko: "CI/CD 파이프라인이 관리자 키 대신 OIDC/MI 인증으로 전환되었는지 사전 확인 필요",
            odin_verdict_ko: "OIDC 전환 확인 후 adminUserEnabled=false 적용 권고",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "컨테이너 레지스트리",
        },
        RuleMeta {
            id: "adv.sec.subnet-nsg",
            pillar: "security",
            subcategory: "network_and_encryption",
            title_ko: "서브넷 Network Security Group(NSG) 연결 및 최소 허용 규칙 적용",
            title_en: "Associate Network Security Groups with all workload subnets",
            description_ko: "NSG가 연결되지 않은 서브넷은 내부 횡적 이동(Lateral Movement) 및 비인가 포트 접근에 대한 L3/L4 방어선이 부재합니다.",
            benefits_ko: "서브넷 경계 마이크로세그멘테이션 및 트래픽 감사 로깅 기반 확보",
            remediation_ko: "워크로드 서브넷에 표준 NSG를 연결하고 기본 거부(Deny-by-default) 규칙을 적용하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/virtual-network/network-security-groups-overview",
            impact: "medium",
            owner_agent: "Forseti",
            action_type_ref: "remediate.restrict-network-access",
            action_label_ko: "서브넷 NSG 연결 PR",
            automation_mode: "fix_pr",
            risk_tier: "A2",
            downtime_class: "zero_downtime",
            waf_ref: "WAF SE:06 / MCSB NS-1",
            cost_implication_tier: "no_cost_impact",
            cost_factors: &["Azure NSG 리소스 추가 비용 없음"],
            reliability_tradeoff_ko: "허용 트래픽 목록(Dry-Run) 검증 후 적용 시 중단 없음",
            odin_verdict_ko: "무비용 네트워크 보안 필수 통제 — PrivateEndpoint/Gateway 전용 제외 서브넷 적용",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "가상 네트워크 서브넷",
        },
        // ── OPERATIONAL EXCELLENCE (4) ──
        RuleMeta {
            id: "adv.oe.mandatory-tags",
            pillar: "operational_excellence",
            subcategory: "governance_and_tagging",
            title_ko: "필수 운영 태그(environment · workload) 누락 리소스 표준화",
            title_en: "Apply mandatory operational governance tags across resources",
            description_ko: "환경(env)과 워크로드(workload) 태그가 누락된 리소스는 비용 배부(Showback), 담당자(Steward) 자동 라우팅, 환경별 안전 정책 적용이 불가능합니다.",
            benefits_ko: "온톨로지 자동 귀속·FinOps 비용 배부 정확도 100% 및 신속한 장애 에스컬레이션",
            remediation_ko: "리소스 그룹 및 IaC 모듈에 fdai:env / fdai:workload / owner 표준 태그를 부여하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-tagging",
            impact: "medium",
            owner_agent: "Mimir",
            action_type_ref: "remediate.tag-add",
            action_label_ko: "필수 태그 일괄 부여",
            automation_mode: "hil_guided_fix",
            risk_tier: "A0",
            downtime_class: "zero_downtime",
            waf_ref: "WAF OE:04 / CAF Governance",
            cost_implication_tier: "no_cost_impact",
            cost_factors: &["태그 부여 추가 비용 없음"],
            reliability_tradeoff_ko: "완전 무중단 메타데이터 작업",
            odin_verdict_ko: "A0 무위험 거버넌스 작업 — 일괄 자동화 승격 최우선 후보",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "핵심 Azure 리소스",
        },
        RuleMeta {
            id: "adv.oe.cae-app-insights",
            pillar: "operational_excellence",
            subcategory: "observability",
            title_ko: "Container Apps 관리 환경에 Application Insights 원격 분석 연결",
            title_en: "Connect Application Insights telemetry to Container Apps environments",
            description_ko: "appInsightsConfiguration이 비어 있는 Container Apps 환경은 분산 추적(Distributed Tracing) 및 의존성 지연 분석이 불가능합니다.",
            benefits_ko: "장애 RCA 시간 단축 및 엔드투엔드 요청 지연·오류율 실시간 관측",
            remediation_ko: "Container Apps 환경에 Application Insights 연결 문자열 및 OpenTelemetry 내보내기를 구성하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/container-apps/observability",
            impact: "medium",
            owner_agent: "Heimdall",
            action_type_ref: "remediate.enable-diagnostic-settings",
            action_label_ko: "Application Insights 연결",
            automation_mode: "fix_pr",
            risk_tier: "A1",
            downtime_class: "zero_downtime",
            waf_ref: "WAF OE:07 / Observability",
            cost_implication_tier: "low",
            cost_factors: &["수집되는 텔레메트리 GB당 Log Analytics/App Insights 종량 과금"],
            reliability_tradeoff_ko: "관측성 확보로 MTTR 크게 단축",
            odin_verdict_ko: "샘플링 비율 적용 시 저비용으로 높은 관측성 확보 가능",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "Container Apps 환경",
        },
        RuleMeta {
            id: "adv.oe.alert-coverage",
            pillar: "operational_excellence",
            subcategory: "monitoring_and_alerts",
            title_ko: "핵심 리소스 그룹 이상 탐지 알림 및 Action Group 라우팅 검증",
            title_en: "Ensure Service Health and anomaly alert rules cover active workloads",
            description_ko: "이상 탐지 알림 규칙이나 Action Group이 부족하면 리전 장애·할당 실패·성능 저하를 운영자가 사후에 인지하게 됩니다.",
            benefits_ko: "장애 감지 지연(MTTD) 최소화 및 담당 Steward 즉시 에스컬레이션",
            remediation_ko: "주요 리소스 그룹별 Service Health 및 메트릭 이상 알림 규칙과 Action Group을 구성하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/service-health/alerts-activity-log-service-notifications-portal",
            impact: "medium",
            owner_agent: "Heimdall",
            action_type_ref: "ops.update-alert-routing",
            action_label_ko: "알림 규칙 커버리지 보강",
            automation_mode: "hil_guided_fix",
            risk_tier: "A1",
            downtime_class: "zero_downtime",
            waf_ref: "WAF OE:07 / SRE Alerting",
            cost_implication_tier: "no_cost_impact",
            cost_factors: &["Service Health Activity Log 알림은 무료"],
            reliability_tradeoff_ko: "알림 노이즈 방지를 위해 alert-quality SNR 기준과 함께 구성",
            odin_verdict_ko: "무비용·무중단 운영 필수 조치",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "리소스 그룹",
        },
        RuleMeta {
            id: "adv.oe.log-retention-auth",
            pillar: "operational_excellence",
            subcategory: "observability",
            title_ko: "Log Analytics 보존 정책(90일+) 및 Entra ID 전용 인증 적용",
            title_en: "Configure Log Analytics retention policy and disable local auth",
            description_ko: "30일 단기 보존 또는 로컬 키 인증이 허용된 작업 영역은 장기 포스트모템 감사 추적과 보안 기준을 충족하지 못합니다.",
            benefits_ko: "규정 준수 감사 추적성 확보 및 공유 키 탈취 위험 제거",
            remediation_ko: "주요 운영 작업 영역의 retentionInDays를 90일 이상으로 설정하고 disableLocalAuth=true를 적용하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/azure-monitor/logs/data-retention-configure",
            impact: "low",
            owner_agent: "Saga",
            action_type_ref: "remediate.set-retention-policy",
            action_label_ko: "로그 보존·인증 정책 구성",
            automation_mode: "fix_pr",
            risk_tier: "A1",
            downtime_class: "zero_downtime",
            waf_ref: "WAF OE:07 / Audit",
            cost_implication_tier: "low",
            cost_factors: &["31일 초과 보존 기간에 대해 GB/월 소액 보존 비용 발생"],
            reliability_tradeoff_ko: "로컬 인증 차단 전 DCR/에이전트 Entra ID 인증 전환 확인 필요",
            odin_verdict_ko: "운영 감사 영역 우선 적용, 임시 실험 작업 영역은 30일 유지 허용",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "Log Analytics 작업 영역",
        },
        // ── PERFORMANCE (4) ──
        RuleMeta {
            id: "adv.perf.nic-accelerated-net",
            pillar: "performance",
            subcategory: "networking",
            title_ko: "가상 머신 네트워크 인터페이스(NIC) Accelerated Networking 활성화",
            title_en: "Enable Accelerated Networking on supported VM network interfaces",
            description_ko: "Accelerated Networking(SR-IOV)이 비활성화된 NIC는 호스트 가상 스위치를 경유해 패킷 지연, 지터, CPU 오버헤드가 증가합니다.",
            benefits_ko: "네트워크 지연 대폭 감소 및 처리량(최대 30Gbps+) 향상(추가 비용 없음)",
            remediation_ko: "지원 VM SKU의 NIC에서 enableAcceleratedNetworking=true를 활성화하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/virtual-network/accelerated-networking-overview",
            impact: "medium",
            owner_agent: "Freyr",
            action_type_ref: "remediate.right-size",
            action_label_ko: "Accelerated Networking 활성화",
            automation_mode: "fix_pr",
            risk_tier: "A2",
            downtime_class: "restart_required",
            waf_ref: "WAF PE:07 / Compute Network",
            cost_implication_tier: "no_cost_impact",
            cost_factors: &["Accelerated Networking 활성화에 따른 추가 Azure 비용 없음"],
            reliability_tradeoff_ko: "기존 실행 VM 적용 시 일시 중지/재시작 필요",
            odin_verdict_ko: "무비용 성능 향상 — 다음 유지보수 창(ChangeWindow)에 일괄 반영 권고",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "네트워크 인터페이스",
        },
        RuleMeta {
            id: "adv.perf.acr-sku-retention",
            pillar: "performance",
            subcategory: "storage_and_registry",
            title_ko: "Container Registry Standard/Premium 처리량 및 이미지 보존 정책 최적화",
            title_en: "Optimize Container Registry SKU throughput and artifact retention policy",
            description_ko: "Basic SKU 레지스트리는 동시 이미지 Pull 제한이 낮아 AKS 스케일아웃·CI 병렬 빌드 시 스로틀링과 배포 지연을 유발합니다.",
            benefits_ko: "컨테이너 이미지 Pull 지연 감소 및 미태그 이미지 자동 정리로 스토리지 성능 유지",
            remediation_ko: "운영·CI 레지스트리를 Standard/Premium으로 승격하고 retentionPolicy를 활성화하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/container-registry/container-registry-skus",
            impact: "medium",
            owner_agent: "Freyr",
            action_type_ref: "remediate.right-size",
            action_label_ko: "ACR 티어·보존 정책 최적화",
            automation_mode: "fix_pr",
            risk_tier: "A1",
            downtime_class: "zero_downtime",
            waf_ref: "WAF PE:05 / Container",
            cost_implication_tier: "low",
            cost_factors: &["Basic → Standard 승격 시 월 약 $15 추가 비용"],
            reliability_tradeoff_ko: "온라인 무중단 티어 전환 지원",
            odin_verdict_ko: "CI/CD 배포 병목이 발생하는 레지스트리 우선 적용",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "컨테이너 레지스트리",
        },
        RuleMeta {
            id: "adv.perf.aks-nodepool-scale",
            pillar: "performance",
            subcategory: "autoscaling",
            title_ko: "AKS 노드풀 오토스케일링 및 용량 헤드룸 최적화",
            title_en: "Enable AKS Cluster Autoscaler and tune node pool headroom",
            description_ko: "고정 크기 노드풀은 트래픽 급증 시 파드 Pending 지연을 유발하고, 저부하 시에는 유휴 노드를 방치합니다.",
            benefits_ko: "부하 변화에 따른 자동 탄력 확장으로 P95 응답 지연 안정화",
            remediation_ko: "AKS 노드풀에 enableAutoScaling=true 및 minCount/maxCount 범위를 워크로드 패턴에 맞게 설정하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/aks/cluster-autoscaler",
            impact: "medium",
            owner_agent: "Freyr",
            action_type_ref: "ops.scale-out",
            action_label_ko: "노드풀 오토스케일 구성",
            automation_mode: "fix_pr",
            risk_tier: "A2",
            downtime_class: "zero_downtime",
            waf_ref: "WAF PE:05 / Autoscaling",
            cost_implication_tier: "no_cost_impact",
            cost_factors: &["저부하 시간대 자동 축소로 순비용 절감 효과 동반"],
            reliability_tradeoff_ko: "파드 스케줄링 지연 방지 및 비용 탄력성 동시 달성",
            odin_verdict_ko: "성능+비용 동시 개선 항목 — Freyr 예측 범위 기반 min/max 적용 권고",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "AKS 노드풀",
        },
        RuleMeta {
            id: "adv.perf.lb-health-probes",
            pillar: "performance",
            subcategory: "networking",
            title_ko: "Load Balancer 백엔드 헬스 프로브 구성 및 지연 분산 점검",
            title_en: "Configure Load Balancer health probes for fast backend failover",
            description_ko: "헬스 프로브가 비어 있는 Load Balancer는 응답 지연·장애 백엔드로 트래픽을 계속 전달해 테일 레이턴시(P99)를 악화시킵니다.",
            benefits_ko: "비정상 인스턴스 수 초 내 자동 격리 및 균일한 응답 속도 유지",
            remediation_ko: "HTTP/HTTPS/TCP 헬스 프로브(간격 5초, 임계치 2회)를 Load Balancer 규칙에 연결하세요.",
            learn_more_url: "https://learn.microsoft.com/azure/load-balancer/load-balancer-custom-probe-overview",
            impact: "low",
            owner_agent: "Freyr",
            action_type_ref: "remediate.apply-preflight-toggle",
            action_label_ko: "헬스 프로브 구성 PR",
            automation_mode: "fix_pr",
            risk_tier: "A1",
            downtime_class: "zero_downtime",
            waf_ref: "WAF PE:07 / Load Balancing",
            cost_implication_tier: "no_cost_impact",
            cost_factors: &["헬스 프로브 구성 추가 비용 없음"],
            reliability_tradeoff_ko: "성능·가용성 동시 개선",
            odin_verdict_ko: "무비용·무중단 최적화 — 즉시 적용 권고",
            retirement_date: None,
            retirement_days_left: None,
            replacement_target: None,
            pricing_basis: None,
            target_resource_label_ko: "로드 밸런서",
        },
    ];
    RULES
}

fn extract_rg(resource_id: &str, parent_id: &str) -> String {
    for src in [resource_id, parent_id] {
        let lower = src.to_ascii_lowercase();
        for marker in ["/resource-group/", "/resourcegroups/"] {
            if let Some(pos) = lower.find(marker) {
                let rest = &src[pos + marker.len()..];
                let rg = rest.split('/').next().unwrap_or("").trim();
                if !rg.is_empty() {
                    return rg.to_string();
                }
            }
        }
    }
    "subscription-scope".to_string()
}

fn extract_env(tags: &Value, rg: &str, name: &str) -> String {
    for k in ["fdai:env", "env", "environment", "Environment"] {
        if let Some(v) = tags.get(k).and_then(Value::as_str) {
            let clean = v.trim().to_ascii_lowercase();
            if !clean.is_empty() {
                return clean;
            }
        }
    }
    let combined = format!("{rg} {name}").to_ascii_lowercase();
    if combined.contains("prod") || combined.contains("release") {
        "prod".to_string()
    } else if combined.contains("lab") || combined.contains("demo") || combined.contains("test") {
        "lab".to_string()
    } else if combined.contains("dev") || combined.contains("ci") {
        "dev".to_string()
    } else {
        "unspecified".to_string()
    }
}

fn extract_workload(tags: &Value, rg: &str) -> String {
    for k in ["fdai:workload", "workload", "fdai:layer", "fdai:purpose"] {
        if let Some(v) = tags.get(k).and_then(Value::as_str) {
            let clean = v.trim();
            if !clean.is_empty() {
                return clean.to_string();
            }
        }
    }
    rg.to_string()
}

fn detect_cluster_key(name: &str) -> Option<String> {
    let low = name.to_ascii_lowercase();
    if low.starts_with("fdai-ci-worker-docker-") {
        return Some("fdai-ci-worker-docker-* (탄력 CI 워커 풀)".to_string());
    }
    if low.starts_with("vm-runner-") {
        return Some("vm-runner-* (빌드/검증 러너 풀)".to_string());
    }
    if low.starts_with("aks-") && low.contains("-vmss") {
        return Some("aks-*-vmss (AKS 노드 확장 집합)".to_string());
    }
    None
}

fn parse_zones(doc: &Value, props: &Value) -> Vec<String> {
    for candidate in [
        doc.get("zones"),
        props.get("zones"),
        props.get("availabilityZones"),
    ] {
        if let Some(arr) = candidate.and_then(Value::as_array) {
            let z: Vec<String> = arr
                .iter()
                .filter_map(|v| {
                    v.as_str()
                        .map(|s| s.to_string())
                        .or_else(|| v.as_i64().map(|n| n.to_string()))
                })
                .collect();
            if !z.is_empty() {
                return z;
            }
        }
    }
    Vec::new()
}

fn impact_weight(impact: &str) -> f64 {
    match impact {
        "high" => 3.0,
        "medium" => 2.0,
        _ => 1.0,
    }
}

fn check_disk_vm_zone_alignment(
    disk: &LiveResource,
    neighbors_map: &HashMap<String, Vec<Value>>,
    res_index: &HashMap<&str, &LiveResource>,
) -> (bool, Value) {
    let sku_up = disk.sku_name.to_ascii_uppercase();
    let is_zrs = sku_up.contains("ZRS");
    let mut attached_vm_id: Option<String> = None;
    let mut attached_vm_zones: Vec<String> = Vec::new();
    if let Some(links) = neighbors_map.get(&disk.resource_id) {
        for lk in links {
            if let Some(tid) = lk.get("target").and_then(Value::as_str) {
                if let Some(vm) = res_index.get(tid) {
                    if vm.resource_type == "compute.vm" {
                        attached_vm_id = Some(vm.name.clone());
                        attached_vm_zones = vm.zones.clone();
                        break;
                    }
                }
            }
        }
    }
    let aligned = if is_zrs {
        true
    } else if !attached_vm_zones.is_empty() {
        !disk.zones.is_empty() && disk.zones.iter().any(|z| attached_vm_zones.contains(z))
    } else {
        !disk.zones.is_empty()
    };
    (
        aligned,
        json!({
            "sku": disk.sku_name,
            "disk_zones": disk.zones,
            "attached_vm": attached_vm_id.unwrap_or_else(|| "none_linked".to_string()),
            "attached_vm_zones": attached_vm_zones,
            "zrs_redundant": is_zrs,
            "disk_size_gb": disk.props.get("diskSizeGB").and_then(Value::as_i64).unwrap_or(0),
            "disk_state": disk.props.get("diskState").and_then(Value::as_str).unwrap_or(&disk.status),
            "expected": "disk zones match linked VM zone via ontology_link or ZRS SKU"
        }),
    )
}

fn eval_rule_on_resource(
    rule: &RuleMeta,
    res: &LiveResource,
    all_resources: &[LiveResource],
    neighbors_map: &HashMap<String, Vec<Value>>,
    res_index: &HashMap<&str, &LiveResource>,
    cfg: &AdvisorConfigState,
    ri_term: &str,
    ri_lookback: u32,
) -> Option<(bool, f64, f64, Value)> {
    // Returns Option<(is_active_violation, yearly_savings_usd, carbon_kg_co2e, evidence_json)>
    // None means this resource is not applicable to this rule.
    let p = &res.props;
    let d = &res.doc;
    let env = extract_env(&res.tags, &res.resource_group, &res.name);
    let dev_relaxed = cfg.environment_profile == "dev_cost_first" && (env == "dev" || env == "lab");

    match rule.id {
        "adv.rel.vm-availability-zones" => {
            if res.resource_type != "compute.vm" {
                return None;
            }
            let active = res.zones.is_empty() && !dev_relaxed;
            Some((
                active,
                0.0,
                0.0,
                json!({
                    "zones": res.zones,
                    "location": res.location,
                    "status": res.status,
                    "environment_profile": cfg.environment_profile,
                    "expected": "zones >= 1 (zonal or Flex VMSS)"
                }),
            ))
        }
        "adv.rel.vmss-zone-resiliency" => {
            if res.resource_type != "compute.vm-scale-set" {
                return None;
            }
            let zone_ok = res.zones.len() >= 2;
            let has_probe = p.get("healthProbe").is_some()
                || p.pointer("/virtualMachineProfile/networkProfile/healthProbe").is_some();
            let active = (!zone_ok || !has_probe) && !dev_relaxed;
            Some((
                active,
                0.0,
                0.0,
                json!({
                    "zones": res.zones,
                    "health_probe_detected": has_probe,
                    "expected": "zones >= 2 and healthProbe configured"
                }),
            ))
        }
        "adv.rel.nat-gateway-zones" => {
            if res.resource_type != "network.nat-gateway" {
                return None;
            }
            let active = res.zones.len() < 2;
            Some((
                active,
                0.0,
                0.0,
                json!({
                    "zones": res.zones,
                    "sku": res.sku_name,
                    "expected": "zone-redundant or multi-zone NAT"
                }),
            ))
        }
        "adv.rel.storage-zone-redundancy" => {
            if res.resource_type != "object-storage" {
                return None;
            }
            let sku_up = res.sku_name.to_ascii_uppercase();
            let is_zr = sku_up.contains("ZRS") || sku_up.contains("GRS") || sku_up.contains("GZRS");
            Some((
                !is_zr,
                0.0,
                0.0,
                json!({
                    "sku_name": res.sku_name,
                    "sku_tier": res.sku_tier,
                    "zone_redundant": is_zr,
                    "expected": "Standard_ZRS / Standard_GRS / Standard_GZRS"
                }),
            ))
        }
        "adv.rel.storage-soft-delete" => {
            if res.resource_type != "object-storage" {
                return None;
            }
            let soft = p
                .pointer("/deleteRetentionPolicy/enabled")
                .and_then(Value::as_bool)
                .or_else(|| d.get("blob_soft_delete_enabled").and_then(Value::as_bool))
                .unwrap_or(false);
            Some((
                !soft,
                0.0,
                0.0,
                json!({
                    "blob_soft_delete_enabled": soft,
                    "access_tier": p.get("accessTier").and_then(Value::as_str).unwrap_or("Hot"),
                    "expected": "deleteRetentionPolicy.enabled == true"
                }),
            ))
        }
        "adv.rel.cae-zone-redundancy" => {
            if res.resource_type != "compute.container-app-environment" {
                return None;
            }
            let zr = p.get("zoneRedundant").and_then(Value::as_bool).unwrap_or(false);
            Some((
                !zr,
                0.0,
                0.0,
                json!({
                    "zoneRedundant": zr,
                    "environmentMode": p.get("environmentMode").and_then(Value::as_str).unwrap_or("unknown"),
                    "expected": "properties.zoneRedundant == true"
                }),
            ))
        }
        "adv.rel.aks-availability-zones" => {
            if res.resource_type != "kubernetes-cluster" {
                return None;
            }
            let tier = res.sku_tier.to_ascii_lowercase();
            let is_std = tier == "standard" || tier == "premium";
            Some((
                !is_std,
                0.0,
                0.0,
                json!({
                    "sku_tier": res.sku_tier,
                    "status": res.status,
                    "zones": res.zones,
                    "expected": "sku.tier == Standard and multi-zone node pools"
                }),
            ))
        }
        "adv.rel.disk-zone-alignment" => {
            if res.resource_type != "disk" {
                return None;
            }
            let (aligned, ev) = check_disk_vm_zone_alignment(res, neighbors_map, res_index);
            Some((!aligned, 0.0, 0.0, ev))
        }
        "adv.rel.vnet-nat-gateway" => {
            if res.resource_type != "network.subnet" {
                return None;
            }
            let purpose = p.get("purpose").and_then(Value::as_str).unwrap_or("").to_ascii_lowercase();
            let low_name = res.name.to_ascii_lowercase();
            if purpose.contains("privateendpoint")
                || low_name.contains("bastion")
                || low_name.contains("gateway")
                || low_name.contains("firewall")
                || low_name.ends_with("-pe")
            {
                return None;
            }
            let has_nat = p.get("natGateway").is_some_and(|v| !v.is_null());
            Some((
                !has_nat,
                0.0,
                0.0,
                json!({
                    "addressPrefix": p.get("addressPrefix").and_then(Value::as_str).unwrap_or("-"),
                    "has_nat_gateway": has_nat,
                    "expected": "properties.natGateway attached"
                }),
            ))
        }
        "adv.rel.app-service-zone" => {
            if res.resource_type != "app-service-plan" {
                return None;
            }
            let zr = p.get("zoneRedundant").and_then(Value::as_bool).unwrap_or(false);
            Some((
                !zr,
                0.0,
                0.0,
                json!({
                    "sku_name": res.sku_name,
                    "sku_tier": res.sku_tier,
                    "zoneRedundant": zr,
                    "expected": "zoneRedundant == true"
                }),
            ))
        }
        // ── RETIREMENTS ──
        "adv.ret.keyvault-api-2026" => {
            if res.resource_type != "secret-store" {
                return None;
            }
            // All Key Vaults must verify client API >= 2026-02-01 unless attested via tag
            let attested = res
                .tags
                .get("fdai:kv-api-verified")
                .and_then(Value::as_str)
                .is_some_and(|v| v >= "2026-02-01");
            Some((
                !attested,
                0.0,
                0.0,
                json!({
                    "vault_uri": p.get("vaultUri").and_then(Value::as_str).unwrap_or("-"),
                    "api_verified_tag": res.tags.get("fdai:kv-api-verified").and_then(Value::as_str).unwrap_or("unverified"),
                    "retirement_date": "2026-12-31",
                    "replacement": "Key Vault API 2026-02-01+"
                }),
            ))
        }
        "adv.ret.logs-ingestion-api" => {
            if res.resource_type != "log-workspace" {
                return None;
            }
            let dcr_rgs: BTreeSet<&str> = all_resources
                .iter()
                .filter(|r| r.resource_type == "data-collection-rule")
                .map(|r| r.resource_group.as_str())
                .collect();
            let has_dcr = dcr_rgs.contains(res.resource_group.as_str());
            Some((
                !has_dcr,
                0.0,
                0.0,
                json!({
                    "workspace_rg": res.resource_group,
                    "dcr_in_same_rg": has_dcr,
                    "retention_days": p.get("retentionInDays").and_then(Value::as_i64).unwrap_or(30),
                    "retirement_date": "2026-12-15",
                    "replacement": "Logs Ingestion API (DCR)"
                }),
            ))
        }
        "adv.ret.basic-network-sku" => {
            if !matches!(res.resource_type.as_str(), "network.public-ip" | "network.load-balancer") {
                return None;
            }
            let is_basic = res.sku_name.eq_ignore_ascii_case("basic");
            Some((
                is_basic,
                0.0,
                0.0,
                json!({
                    "sku_name": res.sku_name,
                    "sku_tier": res.sku_tier,
                    "retirement_date": "2027-03-31",
                    "expected": "Standard SKU"
                }),
            ))
        }
        // ── COST ──
        "adv.cost.vm-rightsizing" => {
            if res.resource_type != "compute.vm" {
                return None;
            }
            let scheduled_rgs: BTreeSet<&str> = all_resources
                .iter()
                .filter(|r| r.resource_type == "compute.vm-shutdown-schedule")
                .map(|r| r.resource_group.as_str())
                .collect();
            let has_shutdown = scheduled_rgs.contains(res.resource_group.as_str());
            let low_status = res.status.to_ascii_lowercase();
            let deallocated = low_status.contains("deallocated") || low_status.contains("stopped");
            // Sensitive to low_cpu_threshold_p95: higher threshold flags more dev/CI VMs without shutdown schedules
            let flagged = !has_shutdown && (deallocated || cfg.low_cpu_threshold_p95 >= 10 || env == "dev" || env == "lab");
            let yearly_savings = if flagged {
                if deallocated { 528.0 } else { 780.0 * (cfg.low_cpu_threshold_p95 as f64 / 5.0).min(1.5) }
            } else {
                0.0
            };
            let monthly = yearly_savings / 12.0;
            let active = flagged && monthly >= cfg.min_monthly_savings_usd;
            let carbon = if active { (yearly_savings / 126.9 * 100.0).round() / 100.0 } else { 0.0 };
            Some((
                active,
                if active { yearly_savings.round() } else { 0.0 },
                carbon,
                json!({
                    "power_state": res.status,
                    "has_shutdown_schedule": has_shutdown,
                    "configured_low_cpu_threshold_p95": cfg.low_cpu_threshold_p95,
                    "lookback_days": cfg.lookback_days,
                    "environment": env,
                    "pricing_basis": "Retail"
                }),
            ))
        }
        "adv.cost.vm-reserved-instance" => {
            if res.resource_type != "compute.vm" {
                return None;
            }
            let running = res.status.to_ascii_lowercase().contains("running")
                || res.doc.get("availabilityState").and_then(Value::as_str) == Some("Available");
            let term_mult: f64 = if ri_term == "P1Y" { 0.62 } else { 1.0 };
            let lookback_mult: f64 = match ri_lookback {
                7 => 0.94,
                60 => 1.06,
                _ => 1.0,
            };
            let yearly: f64 = if running { (1_680.0_f64 * term_mult * lookback_mult).round() } else { 0.0 };
            let active = running && (yearly / 12.0) >= cfg.min_monthly_savings_usd;
            Some((
                active,
                if active { yearly } else { 0.0 },
                0.0,
                json!({
                    "ri_term": ri_term,
                    "ri_lookback_days": ri_lookback,
                    "availability_state": d.get("availabilityState").and_then(Value::as_str).unwrap_or(&res.status),
                    "pricing_basis": "Contractual"
                }),
            ))
        }
        "adv.cost.savings-plan" => {
            if res.resource_type != "compute.container-app-environment" {
                return None;
            }
            let term_mult: f64 = if ri_term == "P1Y" { 0.65 } else { 1.0 };
            let yearly: f64 = (756.0_f64 * term_mult).round();
            let active = (yearly / 12.0) >= cfg.min_monthly_savings_usd;
            Some((
                active,
                if active { yearly } else { 0.0 },
                0.0,
                json!({
                    "savings_plan_term": ri_term,
                    "lookback_days": ri_lookback,
                    "environmentMode": p.get("environmentMode").and_then(Value::as_str).unwrap_or("WorkloadProfiles"),
                    "pricing_basis": "Contractual"
                }),
            ))
        }
        "adv.cost.unattached-disks" => {
            if res.resource_type != "disk" {
                return None;
            }
            let state = p
                .get("diskState")
                .and_then(Value::as_str)
                .unwrap_or(&res.status);
            let unattached = state.eq_ignore_ascii_case("Unattached");
            let gb = p.get("diskSizeGB").and_then(Value::as_f64).unwrap_or(128.0);
            let yearly = if unattached { (gb * 0.15 * 12.0).round() } else { 0.0 };
            let carbon = if unattached { (gb * 0.012 * 100.0).round() / 100.0 } else { 0.0 };
            Some((
                unattached,
                yearly,
                carbon,
                json!({
                    "diskState": state,
                    "diskSizeGB": gb,
                    "sku": res.sku_name,
                    "pricing_basis": "Retail"
                }),
            ))
        }
        "adv.cost.unused-public-ip" => {
            if res.resource_type != "network.public-ip" {
                return None;
            }
            let bound = p.get("ipConfiguration").is_some_and(|v| !v.is_null())
                || p.get("natGateway").is_some_and(|v| !v.is_null());
            let yearly = if !bound { 44.0 } else { 0.0 };
            Some((
                !bound,
                yearly,
                0.0,
                json!({
                    "ipAddress": p.get("ipAddress").and_then(Value::as_str).unwrap_or("-"),
                    "sku": res.sku_name,
                    "bound_to_endpoint": bound,
                    "pricing_basis": "Retail"
                }),
            ))
        }
        "adv.cost.llm-capacity-opt" => {
            if res.resource_type != "llm-model-deployment" {
                return None;
            }
            let cap = d.pointer("/sku/capacity").and_then(Value::as_i64).unwrap_or(0);
            let high_cap = cap >= 200;
            let yearly = if high_cap { (cap as f64 * 4.8).round() } else { 0.0 };
            let carbon = if high_cap { ((cap as f64) * 0.018 * 100.0).round() / 100.0 } else { 0.0 };
            Some((
                high_cap,
                yearly,
                carbon,
                json!({
                    "model_name": d.get("model_name").and_then(Value::as_str).unwrap_or("-"),
                    "sku_name": res.sku_name,
                    "capacity_tpm_k": cap,
                    "pricing_basis": "Contractual"
                }),
            ))
        }
        // ── SECURITY ──
        "adv.sec.keyvault-hardening" => {
            if res.resource_type != "secret-store" {
                return None;
            }
            let purge = p.get("enablePurgeProtection").and_then(Value::as_bool).unwrap_or(false);
            let rbac = p.get("enableRbacAuthorization").and_then(Value::as_bool).unwrap_or(false);
            let pub_net = p.get("publicNetworkAccess").and_then(Value::as_str).unwrap_or("Enabled");
            let active = !purge || !rbac || !pub_net.eq_ignore_ascii_case("Disabled");
            Some((
                active,
                0.0,
                0.0,
                json!({
                    "enablePurgeProtection": purge,
                    "enableRbacAuthorization": rbac,
                    "publicNetworkAccess": pub_net,
                    "enableSoftDelete": p.get("enableSoftDelete").and_then(Value::as_bool).unwrap_or(false)
                }),
            ))
        }
        "adv.sec.storage-public-tls" => {
            if res.resource_type != "object-storage" {
                return None;
            }
            let pub_blob = p.get("allowBlobPublicAccess").and_then(Value::as_bool).unwrap_or(false);
            let tls = p.get("minimumTlsVersion").and_then(Value::as_str).unwrap_or("TLS1_0");
            let pub_net = p.get("publicNetworkAccess").and_then(Value::as_str).unwrap_or("Enabled");
            let active = pub_blob || tls != "TLS1_2" || !pub_net.eq_ignore_ascii_case("Disabled");
            Some((
                active,
                0.0,
                0.0,
                json!({
                    "allowBlobPublicAccess": pub_blob,
                    "minimumTlsVersion": tls,
                    "publicNetworkAccess": pub_net
                }),
            ))
        }
        "adv.sec.vm-host-encryption-id" => {
            if res.resource_type != "compute.vm" {
                return None;
            }
            let host_enc = d.get("encryption_at_host_enabled").and_then(Value::as_bool).unwrap_or(false);
            let id_type = d
                .pointer("/identity/type")
                .and_then(Value::as_str)
                .or_else(|| d.get("identity_type").and_then(Value::as_str))
                .unwrap_or("None");
            let has_id = !id_type.eq_ignore_ascii_case("None") && !id_type.is_empty();
            Some((
                !host_enc || !has_id,
                0.0,
                0.0,
                json!({
                    "encryption_at_host_enabled": host_enc,
                    "identity_type": id_type,
                    "expected": "encryption_at_host_enabled == true and Managed Identity assigned"
                }),
            ))
        }
        "adv.sec.acr-hardening" => {
            if res.resource_type != "container-registry" {
                return None;
            }
            let admin = p.get("adminUserEnabled").and_then(Value::as_bool).unwrap_or(false);
            let pub_net = p.get("publicNetworkAccess").and_then(Value::as_str).unwrap_or("Enabled");
            Some((
                admin || !pub_net.eq_ignore_ascii_case("Disabled"),
                0.0,
                0.0,
                json!({
                    "adminUserEnabled": admin,
                    "publicNetworkAccess": pub_net,
                    "sku": res.sku_name
                }),
            ))
        }
        "adv.sec.subnet-nsg" => {
            if res.resource_type != "network.subnet" {
                return None;
            }
            let low = res.name.to_ascii_lowercase();
            if low.contains("gatewaysubnet") || low.contains("azurefirewall") {
                return None;
            }
            let has_nsg = p.get("networkSecurityGroup").is_some_and(|v| !v.is_null());
            Some((
                !has_nsg,
                0.0,
                0.0,
                json!({
                    "addressPrefix": p.get("addressPrefix").and_then(Value::as_str).unwrap_or("-"),
                    "has_nsg": has_nsg
                }),
            ))
        }
        // ── OPERATIONAL EXCELLENCE ──
        "adv.oe.mandatory-tags" => {
            if !matches!(
                res.resource_type.as_str(),
                "compute.vm" | "object-storage" | "secret-store" | "kubernetes-cluster" | "log-workspace"
            ) {
                return None;
            }
            let has_env = res.tags.get("fdai:env").is_some() || res.tags.get("env").is_some() || res.tags.get("environment").is_some();
            let has_wl = res.tags.get("fdai:workload").is_some() || res.tags.get("workload").is_some() || res.tags.get("purpose").is_some();
            Some((
                !has_env || !has_wl,
                0.0,
                0.0,
                json!({
                    "has_env_tag": has_env,
                    "has_workload_tag": has_wl,
                    "tag_count": res.tags.as_object().map(|m| m.len()).unwrap_or(0)
                }),
            ))
        }
        "adv.oe.cae-app-insights" => {
            if res.resource_type != "compute.container-app-environment" {
                return None;
            }
            let has_ai = p.get("appInsightsConfiguration").is_some_and(|v| !v.is_null());
            Some((
                !has_ai,
                0.0,
                0.0,
                json!({
                    "appInsightsConfiguration_present": has_ai,
                    "log_destination": p.pointer("/appLogsConfiguration/destination").and_then(Value::as_str).unwrap_or("none")
                }),
            ))
        }
        "adv.oe.alert-coverage" => {
            if res.resource_type != "resource-group" {
                return None;
            }
            let alert_rgs: BTreeSet<&str> = all_resources
                .iter()
                .filter(|r| matches!(r.resource_type.as_str(), "anomaly-alert-rule" | "action-group"))
                .map(|r| r.resource_group.as_str())
                .collect();
            let covered = alert_rgs.contains(res.name.as_str()) || alert_rgs.contains(res.resource_group.as_str());
            Some((
                !covered,
                0.0,
                0.0,
                json!({
                    "resource_group": res.name,
                    "has_alert_or_action_group": covered
                }),
            ))
        }
        "adv.oe.log-retention-auth" => {
            if res.resource_type != "log-workspace" {
                return None;
            }
            let retention = p.get("retentionInDays").and_then(Value::as_i64).unwrap_or(30);
            let local_disabled = p.pointer("/features/disableLocalAuth").and_then(Value::as_bool).unwrap_or(false);
            Some((
                retention < 90 || !local_disabled,
                0.0,
                0.0,
                json!({
                    "retentionInDays": retention,
                    "disableLocalAuth": local_disabled,
                    "expected": "retentionInDays >= 90 and disableLocalAuth == true"
                }),
            ))
        }
        // ── PERFORMANCE ──
        "adv.perf.nic-accelerated-net" => {
            if res.resource_type != "network.interface" {
                return None;
            }
            if p.get("privateEndpoint").is_some_and(|v| !v.is_null()) {
                return None;
            }
            let accel = p.get("enableAcceleratedNetworking").and_then(Value::as_bool).unwrap_or(false);
            Some((
                !accel,
                0.0,
                0.0,
                json!({
                    "enableAcceleratedNetworking": accel,
                    "nicType": p.get("nicType").and_then(Value::as_str).unwrap_or("Standard")
                }),
            ))
        }
        "adv.perf.acr-sku-retention" => {
            if res.resource_type != "container-registry" {
                return None;
            }
            let is_basic = res.sku_name.eq_ignore_ascii_case("basic");
            let ret_on = p.pointer("/policies/retentionPolicy/status").and_then(Value::as_str) == Some("enabled");
            Some((
                is_basic || !ret_on,
                0.0,
                0.0,
                json!({
                    "sku_name": res.sku_name,
                    "retention_policy_enabled": ret_on
                }),
            ))
        }
        "adv.perf.aks-nodepool-scale" => {
            if res.resource_type != "kubernetes-node-pool" {
                return None;
            }
            let autoscale = p.get("enableAutoScaling").and_then(Value::as_bool).unwrap_or(false);
            Some((
                !autoscale,
                0.0,
                0.0,
                json!({
                    "enableAutoScaling": autoscale,
                    "count": p.get("count").and_then(Value::as_i64).unwrap_or(0),
                    "vmSize": p.get("vmSize").and_then(Value::as_str).unwrap_or("-")
                }),
            ))
        }
        "adv.perf.lb-health-probes" => {
            if res.resource_type != "network.load-balancer" {
                return None;
            }
            let probe_cnt = p.get("probes").and_then(Value::as_array).map(|a| a.len()).unwrap_or(0);
            Some((
                probe_cnt == 0,
                0.0,
                0.0,
                json!({
                    "sku": res.sku_name,
                    "probes_count": probe_cnt,
                    "expected": "probes.length >= 1"
                }),
            ))
        }
        _ => None,
    }
}

pub async fn evaluate_live(
    db: &DbHandle,
    rg_filter: Option<&str>,
    ri_term_override: Option<&str>,
    ri_lookback_override: Option<u32>,
    force_refresh: bool,
) -> EvaluationSnapshot {
    let (cfg, dispositions) = {
        let g = read_overlay();
        (
            g.config.clone().unwrap_or_default(),
            g.dispositions.clone(),
        )
    };
    let ri_term = ri_term_override
        .filter(|s| matches!(*s, "P1Y" | "P3Y"))
        .unwrap_or(cfg.ri_term.as_str());
    let ri_lookback = ri_lookback_override
        .filter(|d| matches!(*d, 7 | 14 | 30 | 60))
        .unwrap_or(cfg.lookback_days);

    if !db.is_configured() {
        return unmeasured_snapshot("db_unconfigured", cfg);
    }

    let cached_hit = if force_refresh {
        None
    } else {
        let guard = db_raw_cache().read().await;
        guard.as_ref().and_then(|c| {
            let age = c.fetched_at.elapsed();
            if age < DB_CACHE_TTL {
                Some((
                    c.snapshot_id.clone(),
                    c.latest_seen.clone(),
                    c.resources.clone(),
                    c.rg_counts.clone(),
                    c.rtype_set.clone(),
                    c.neighbors_map.clone(),
                    c.audit_changes.clone(),
                    age.as_secs(),
                ))
            } else {
                None
            }
        })
    };

    let (snapshot_id, latest_seen, raw_resources, rg_counts, rtype_set, neighbors_map, audit_changes, cache_age_seconds) =
        if let Some(hit) = cached_hit {
            hit
        } else {
            let inv_sql = "SELECT r.snapshot_id, r.resource_id, r.resource_type, \
                           COALESCE(to_char(r.last_seen AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') AS last_seen_iso, \
                           COALESCE(p.body, r.props::text, '{}') AS doc_json \
                           FROM ( \
                             SELECT DISTINCT ON (resource_id) snapshot_id, resource_id, resource_type, props, props_digest, last_seen \
                             FROM inventory_snapshot_resource_row \
                             ORDER BY resource_id, last_seen DESC NULLS LAST \
                           ) r \
                           LEFT JOIN inventory_snapshot_properties p ON p.digest = r.props_digest \
                           LIMIT 2500";

            let links_sql = "SELECT from_id, link_type, to_id FROM ontology_link LIMIT 4000";
            let audit_sql = "SELECT seq, action_kind, mode, outcome, \
                             COALESCE(to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') AS ts \
                             FROM audit_log ORDER BY seq DESC LIMIT 30";

            let (inv_res, links_res, audit_res) = tokio::join!(
                db.query_readonly(inv_sql),
                db.query_readonly(links_sql),
                db.query_readonly(audit_sql),
            );

            let inv_rows = match inv_res {
                Ok(r) => r.rows,
                Err(e) => return unmeasured_snapshot(&e, cfg),
            };

            let mut neighbors_map: HashMap<String, Vec<Value>> = HashMap::new();
            if let Ok(lr) = links_res {
                for row in lr.rows {
                    let from_id = cell_str(&row, 0);
                    let link_type = cell_str(&row, 1);
                    let to_id = cell_str(&row, 2);
                    if !from_id.is_empty() && !to_id.is_empty() {
                        neighbors_map
                            .entry(from_id.clone())
                            .or_default()
                            .push(json!({ "direction": "out", "link_type": link_type, "target": to_id }));
                        neighbors_map
                            .entry(to_id)
                            .or_default()
                            .push(json!({ "direction": "in", "link_type": link_type, "target": from_id }));
                    }
                }
            }

            let mut audit_changes: Vec<Value> = Vec::new();
            if let Ok(ar) = audit_res {
                for row in ar.rows {
                    audit_changes.push(json!({
                        "seq": cell_i64(&row, 0),
                        "action_kind": cell_str(&row, 1),
                        "mode": cell_str(&row, 2),
                        "outcome": cell_str(&row, 3),
                        "timestamp": cell_str(&row, 4),
                    }));
                }
            }

            let mut snapshot_id: Option<String> = None;
            let mut latest_seen = String::new();
            let mut raw_resources: Vec<LiveResource> = Vec::with_capacity(inv_rows.len());
            let mut rg_counts: BTreeMap<String, usize> = BTreeMap::new();
            let mut rtype_set: BTreeSet<String> = BTreeSet::new();

            for row in inv_rows {
                let snap = cell_str(&row, 0);
                if snapshot_id.is_none() && !snap.is_empty() {
                    snapshot_id = Some(snap);
                }
                let resource_id = cell_str(&row, 1);
                let resource_type = cell_str(&row, 2);
                let last_seen = cell_str(&row, 3);
                if last_seen > latest_seen {
                    latest_seen = last_seen.clone();
                }
                let doc_raw = cell_str(&row, 4);
                let doc: Value = serde_json::from_str(&doc_raw).unwrap_or_else(|_| json!({}));
                let props = doc.get("properties").cloned().unwrap_or_else(|| json!({}));
                let parent_id = doc.get("parent_id").and_then(Value::as_str).unwrap_or("");
                let rg = extract_rg(&resource_id, parent_id);
                let name = doc
                    .get("name")
                    .and_then(Value::as_str)
                    .filter(|s| !s.is_empty())
                    .map(|s| s.to_string())
                    .unwrap_or_else(|| {
                        resource_id
                            .rsplit('/')
                            .next()
                            .unwrap_or(&resource_id)
                            .to_string()
                    });
                let location = doc
                    .get("location")
                    .or_else(|| doc.get("region"))
                    .and_then(Value::as_str)
                    .unwrap_or("global")
                    .to_string();
                let tags = doc.get("tags").cloned().unwrap_or_else(|| json!({}));
                let sku_name = doc
                    .pointer("/sku/name")
                    .or_else(|| doc.get("sku_name"))
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string();
                let sku_tier = doc
                    .pointer("/sku/tier")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string();
                let status = doc
                    .get("status")
                    .or_else(|| doc.get("availabilityState"))
                    .and_then(Value::as_str)
                    .unwrap_or("Observed")
                    .to_string();
                let zones = parse_zones(&doc, &props);

                *rg_counts.entry(rg.clone()).or_insert(0) += 1;
                rtype_set.insert(resource_type.clone());
                raw_resources.push(LiveResource {
                    resource_id,
                    resource_type,
                    name,
                    resource_group: rg,
                    location,
                    last_seen,
                    doc,
                    props,
                    tags,
                    sku_name,
                    sku_tier,
                    status,
                    zones,
                });
            }

            {
                let mut wg = db_raw_cache().write().await;
                *wg = Some(CachedDbRaw {
                    fetched_at: Instant::now(),
                    snapshot_id: snapshot_id.clone(),
                    latest_seen: latest_seen.clone(),
                    resources: raw_resources.clone(),
                    rg_counts: rg_counts.clone(),
                    rtype_set: rtype_set.clone(),
                    neighbors_map: neighbors_map.clone(),
                    audit_changes: audit_changes.clone(),
                });
            }

            (
                snapshot_id,
                latest_seen,
                raw_resources,
                rg_counts,
                rtype_set,
                neighbors_map,
                audit_changes,
                0_u64,
            )
        };

    let excluded_set: BTreeSet<String> = cfg
        .excluded_resource_groups
        .iter()
        .map(|s| s.to_ascii_lowercase())
        .collect();

    let mut excluded_resources_count = 0_usize;
    let mut all_resources: Vec<LiveResource> = Vec::with_capacity(raw_resources.len());
    for res in raw_resources {
        if excluded_set.contains(&res.resource_group.to_ascii_lowercase()) {
            excluded_resources_count += 1;
            continue;
        }
        if let Some(rgf) = rg_filter {
            let trimmed = rgf.trim();
            if !trimmed.is_empty()
                && !trimmed.eq_ignore_ascii_case("all")
                && !res.resource_group.eq_ignore_ascii_case(trimmed)
            {
                continue;
            }
        }
        all_resources.push(res);
    }

    let observed_at = if latest_seen.is_empty() {
        now_iso()
    } else {
        latest_seen
    };

    let mut evaluated_rules: Vec<EvaluatedRuleSummary> = Vec::new();
    let pillars = [
        "cost",
        "security",
        "reliability",
        "operational_excellence",
        "performance",
    ];
    let mut pillar_weighted_total: HashMap<&str, f64> = HashMap::new();
    let mut pillar_weighted_compliant: HashMap<&str, f64> = HashMap::new();
    let res_index: HashMap<&str, &LiveResource> = all_resources
        .iter()
        .map(|r| (r.resource_id.as_str(), r))
        .collect();
    let now_utc = now_iso();

    for rule in rule_catalog() {
        let mut instances: Vec<EvaluatedResourceInstance> = Vec::new();
        let mut active_cnt = 0_usize;
        let mut completed_cnt = 0_usize;
        let mut postponed_cnt = 0_usize;
        let mut dismissed_cnt = 0_usize;
        let mut total_savings = 0.0_f64;
        let mut total_carbon = 0.0_f64;
        let mut cluster_counts: BTreeMap<String, usize> = BTreeMap::new();

        for res in &all_resources {
            let Some((is_violation, savings, carbon, ev)) = eval_rule_on_resource(
                rule,
                res,
                &all_resources,
                &neighbors_map,
                &res_index,
                &cfg,
                ri_term,
                ri_lookback,
            ) else {
                continue;
            };
            let platform_state = if is_violation { "active" } else { "compliant" };
            let disp_key = format!("{}||{}", rule.id, res.resource_id);
            let disp = dispositions.get(&disp_key);
            let (customer_state, effective_bucket, reason, postponed_until, updated_at) =
                if let Some(drec) = disp {
                    if drec.customer_state == "postponed"
                        && !is_postponement_active(drec.postponed_until.as_deref(), &now_utc)
                    {
                        (
                            "postponement_expired".to_string(),
                            if is_violation { "active" } else { "completed" }.to_string(),
                            Some(format!("연기 만료 자동 복귀 (원 사유: {})", drec.reason)),
                            drec.postponed_until.clone(),
                            now_utc.clone(),
                        )
                    } else {
                        let bucket = match drec.customer_state.as_str() {
                            "postponed" => "postponed",
                            "dismissed" => "dismissed",
                            "manually_completed" | "effect_verified" => "completed",
                            _ => {
                                if is_violation {
                                    "active"
                                } else {
                                    "completed"
                                }
                            }
                        };
                        (
                            drec.customer_state.clone(),
                            bucket.to_string(),
                            Some(drec.reason.clone()),
                            drec.postponed_until.clone(),
                            drec.updated_at.clone(),
                        )
                    }
                } else if is_violation {
                    (
                        "open".to_string(),
                        "active".to_string(),
                        None,
                        None,
                        if res.last_seen.is_empty() {
                            observed_at.clone()
                        } else {
                            res.last_seen.clone()
                        },
                    )
                } else {
                    (
                        "originally_compliant".to_string(),
                        "completed".to_string(),
                        None,
                        None,
                        if res.last_seen.is_empty() {
                            observed_at.clone()
                        } else {
                            res.last_seen.clone()
                        },
                    )
                };

            match effective_bucket.as_str() {
                "active" => {
                    active_cnt += 1;
                    total_savings += savings;
                    total_carbon += carbon;
                }
                "completed" => completed_cnt += 1,
                "postponed" => postponed_cnt += 1,
                "dismissed" => dismissed_cnt += 1,
                _ => {}
            }

            let cluster_key = detect_cluster_key(&res.name);
            if effective_bucket == "active" {
                if let Some(ck) = &cluster_key {
                    *cluster_counts.entry(ck.clone()).or_insert(0) += 1;
                }
            }

            let neigh_list = neighbors_map
                .get(&res.resource_id)
                .map(|v| v.iter().take(8).cloned().collect::<Vec<_>>())
                .unwrap_or_default();
            let neigh_total = neighbors_map
                .get(&res.resource_id)
                .map(|v| v.len())
                .unwrap_or(0);

            instances.push(EvaluatedResourceInstance {
                resource_id: res.resource_id.clone(),
                resource_name: res.name.clone(),
                resource_type: res.resource_type.clone(),
                resource_group: res.resource_group.clone(),
                location: res.location.clone(),
                environment: extract_env(&res.tags, &res.resource_group, &res.name),
                workload: extract_workload(&res.tags, &res.resource_group),
                cluster_key,
                platform_state: platform_state.to_string(),
                customer_state,
                effective_bucket,
                disposition_reason: reason,
                postponed_until,
                yearly_savings_usd: savings,
                carbon_kg_co2e: carbon,
                created_at: if res.last_seen.is_empty() {
                    observed_at.clone()
                } else {
                    res.last_seen.clone()
                },
                last_updated: updated_at,
                evidence: ev,
                neighbors_count: neigh_total,
                neighbors: neigh_list,
            });
        }

        let total_evaluated = active_cnt + completed_cnt + postponed_cnt;
        let completion_pct = if total_evaluated == 0 {
            100.0
        } else {
            ((completed_cnt as f64 / total_evaluated as f64) * 1000.0).round() / 10.0
        };

        let w = impact_weight(rule.impact);
        if total_evaluated > 0 {
            *pillar_weighted_total.entry(rule.pillar).or_insert(0.0) += w * (total_evaluated as f64);
            *pillar_weighted_compliant.entry(rule.pillar).or_insert(0.0) +=
                w * (completed_cnt as f64);
        }

        let cluster_hints: Vec<Value> = cluster_counts
            .into_iter()
            .filter(|(_, c)| *c >= 2)
            .map(|(k, c)| {
                json!({
                    "pattern": k,
                    "count": c,
                    "suggestion": format!("동일 패턴 리소스 {c}개를 개별 수정하는 대신 상위 IaC 모듈/프로비저너 템플릿 1곳을 수정하세요.")
                })
            })
            .collect();

        evaluated_rules.push(EvaluatedRuleSummary {
            id: rule.id.to_string(),
            pillar: rule.pillar.to_string(),
            subcategory: rule.subcategory.to_string(),
            title_ko: rule.title_ko.to_string(),
            title_en: rule.title_en.to_string(),
            description_ko: rule.description_ko.to_string(),
            benefits_ko: rule.benefits_ko.to_string(),
            remediation_ko: rule.remediation_ko.to_string(),
            learn_more_url: rule.learn_more_url.to_string(),
            impact: rule.impact.to_string(),
            owner_agent: rule.owner_agent.to_string(),
            action_type_ref: rule.action_type_ref.to_string(),
            action_label_ko: rule.action_label_ko.to_string(),
            automation_mode: rule.automation_mode.to_string(),
            risk_tier: rule.risk_tier.to_string(),
            downtime_class: rule.downtime_class.to_string(),
            waf_ref: rule.waf_ref.to_string(),
            cost_implication_tier: rule.cost_implication_tier.to_string(),
            cost_factors: rule.cost_factors.iter().map(|s| s.to_string()).collect(),
            reliability_tradeoff_ko: rule.reliability_tradeoff_ko.to_string(),
            odin_verdict_ko: rule.odin_verdict_ko.to_string(),
            retirement_date: rule.retirement_date.map(|s| s.to_string()),
            retirement_days_left: rule
                .retirement_date
                .and_then(days_until_iso_date)
                .or(rule.retirement_days_left),
            replacement_target: rule.replacement_target.map(|s| s.to_string()),
            pricing_basis: rule.pricing_basis.map(|s| s.to_string()),
            estimate_basis: if rule.pillar == "cost" {
                "sku_heuristic_estimate".to_string()
            } else {
                "observed_inventory_rule".to_string()
            },
            target_resource_label_ko: rule.target_resource_label_ko.to_string(),
            active_count: active_cnt,
            completed_count: completed_cnt,
            postponed_count: postponed_cnt,
            dismissed_count: dismissed_cnt,
            total_evaluated,
            completion_pct,
            potential_score_increase_pct: 0.0,
            total_yearly_savings_usd: total_savings.round(),
            total_yearly_carbon_kg_co2e: (total_carbon * 100.0).round() / 100.0,
            last_refreshed_at: observed_at.clone(),
            cluster_hints,
            instances,
        });
    }

    // Backfill exact Potential Score Increase (+%p) for every rule
    for rule in &mut evaluated_rules {
        let denom = pillar_weighted_total
            .get(rule.pillar.as_str())
            .copied()
            .unwrap_or(0.0);
        if denom > 0.0 && rule.active_count > 0 {
            let gain = (impact_weight(&rule.impact) * (rule.active_count as f64) / denom) * 100.0;
            rule.potential_score_increase_pct = (gain * 10.0).round() / 10.0;
        }
    }

    let mut pillar_scores: BTreeMap<String, Value> = BTreeMap::new();
    let mut measured_scores: Vec<f64> = Vec::new();
    for p in pillars {
        let p_rules: Vec<&EvaluatedRuleSummary> = evaluated_rules
            .iter()
            .filter(|r| r.pillar == p)
            .collect();
        let active_recs = p_rules.iter().filter(|r| r.active_count > 0).count();
        let active_res: usize = p_rules.iter().map(|r| r.active_count).sum();
        let total_res: usize = p_rules.iter().map(|r| r.total_evaluated).sum();
        let total_savings: f64 = p_rules.iter().map(|r| r.total_yearly_savings_usd).sum();
        let total_carbon: f64 = p_rules.iter().map(|r| r.total_yearly_carbon_kg_co2e).sum();
        let denom = pillar_weighted_total.get(p).copied().unwrap_or(0.0);
        let num = pillar_weighted_compliant.get(p).copied().unwrap_or(0.0);
        let score = if denom > 0.0 {
            let s = ((num / denom) * 1000.0).round() / 10.0;
            measured_scores.push(s);
            Some(s)
        } else {
            None
        };
        let (label_ko, agent) = pillar_meta(p);
        pillar_scores.insert(
            p.to_string(),
            json!({
                "pillar": p,
                "label_ko": label_ko,
                "owner_agent": agent,
                "measured": score.is_some(),
                "score_pct": score,
                "active_recommendations": active_recs,
                "total_rules": p_rules.len(),
                "active_resources": active_res,
                "total_evaluated_resources": total_res,
                "yearly_savings_usd": total_savings.round(),
                "yearly_carbon_kg_co2e": (total_carbon * 100.0).round() / 100.0,
            }),
        );
    }

    let overall_score_pct = if measured_scores.is_empty() {
        None
    } else {
        let avg = measured_scores.iter().sum::<f64>() / (measured_scores.len() as f64);
        Some((avg * 10.0).round() / 10.0)
    };

    let resource_groups: Vec<Value> = rg_counts
        .into_iter()
        .map(|(rg, count)| {
            let excluded = excluded_set.contains(&rg.to_ascii_lowercase());
            json!({ "name": rg, "resource_count": count, "included": !excluded })
        })
        .collect();

    EvaluationSnapshot {
        measured: true,
        reason: None,
        snapshot_id,
        observed_at,
        cache_age_seconds,
        total_inventory_resources: all_resources.len(),
        excluded_resources_count,
        resource_groups,
        resource_types: rtype_set.into_iter().collect(),
        rules: evaluated_rules,
        overall_score_pct,
        pillar_scores,
        audit_changes,
        config: cfg,
    }
}

fn unmeasured_snapshot(reason: &str, cfg: AdvisorConfigState) -> EvaluationSnapshot {
    let mut pillar_scores = BTreeMap::new();
    for p in [
        "cost",
        "security",
        "reliability",
        "operational_excellence",
        "performance",
    ] {
        let (label_ko, agent) = pillar_meta(p);
        pillar_scores.insert(
            p.to_string(),
            json!({
                "pillar": p,
                "label_ko": label_ko,
                "owner_agent": agent,
                "measured": false,
                "score_pct": Value::Null,
                "active_recommendations": Value::Null,
                "total_rules": rule_catalog().iter().filter(|r| r.pillar == p).count(),
                "active_resources": Value::Null,
                "total_evaluated_resources": Value::Null,
                "yearly_savings_usd": Value::Null,
                "yearly_carbon_kg_co2e": Value::Null,
            }),
        );
    }
    EvaluationSnapshot {
        measured: false,
        reason: Some(reason.to_string()),
        snapshot_id: None,
        observed_at: now_iso(),
        cache_age_seconds: 0,
        total_inventory_resources: 0,
        excluded_resources_count: 0,
        resource_groups: Vec::new(),
        resource_types: Vec::new(),
        rules: Vec::new(),
        overall_score_pct: None,
        pillar_scores,
        audit_changes: Vec::new(),
        config: cfg,
    }
}

pub fn pillar_meta(pillar: &str) -> (&'static str, &'static str) {
    match pillar {
        "cost" => ("비용 최적화", "Njord"),
        "security" => ("보안", "Forseti"),
        "reliability" => ("신뢰성", "Heimdall"),
        "operational_excellence" => ("운영 우수성", "Mimir"),
        "performance" => ("성능", "Freyr"),
        _ => ("전체", "Odin"),
    }
}

// ── State Mutation Helpers (Overlay-backed, safe read-only to Azure) ──

pub fn apply_disposition(
    rule_id: &str,
    resource_ids: &[String],
    action: &str,
    reason: &str,
    postpone_days: Option<u64>,
) -> Result<Value, &'static str> {
    if rule_id.is_empty() || resource_ids.is_empty() {
        return Err("rule_id and resource_ids are required");
    }
    let next_state = match action {
        "complete" | "manually_completed" => "manually_completed",
        "postpone" | "postponed" => "postponed",
        "dismiss" | "dismissed" => "dismissed",
        "reopen" | "open" => "open",
        "in_remediation" => "in_remediation",
        _ => return Err("unsupported disposition action"),
    };
    if matches!(next_state, "dismissed" | "postponed")
        && reason.trim().chars().count() < MIN_GOVERNANCE_REASON_LEN
    {
        return Err("dismiss or postpone requires a governance reason of at least 8 characters");
    }
    let until = if next_state == "postponed" {
        let days = postpone_days.unwrap_or(7).clamp(1, 365);
        Some(format_epoch_iso(now_epoch_s() + days * 86_400))
    } else {
        None
    };
    let ts = now_iso();
    let mut g = write_overlay();
    if next_state != "open"
        && g.dispositions.len().saturating_add(resource_ids.len()) > MAX_DISPOSITIONS
    {
        return Err("disposition_capacity_exceeded");
    }
    for rid in resource_ids {
        let key = format!("{rule_id}||{rid}");
        if next_state == "open" {
            g.dispositions.remove(&key);
        } else {
            g.dispositions.insert(
                key,
                DispositionRecord {
                    customer_state: next_state.to_string(),
                    reason: reason.trim().chars().take(500).collect(),
                    postponed_until: until.clone(),
                    updated_at: ts.clone(),
                    updated_by: "operator-console".to_string(),
                },
            );
        }
    }
    Ok(json!({
        "ok": true,
        "persisted": false,
        "persistence_mode": "session_overlay",
        "rule_id": rule_id,
        "updated_count": resource_ids.len(),
        "customer_state": next_state,
        "postponed_until": until,
        "updated_at": ts,
        "audit_note": "platformState(Heimdall 관측 상태)는 불변 유지되며 세션 오버레이 customerState만 전이되었습니다."
    }))
}

pub fn record_feedback(rule_id: &str, helpful: bool, reason: &str) -> Result<Value, &'static str> {
    let ts = now_iso();
    let mut g = write_overlay();
    if g.feedback.len() >= MAX_FEEDBACK_ITEMS {
        g.feedback.remove(0);
    }
    g.feedback.push(FeedbackItem {
        rule_id: rule_id.to_string(),
        helpful,
        reason: reason.trim().chars().take(500).collect(),
        recorded_at: ts.clone(),
    });
    let total_for_rule = g.feedback.iter().filter(|f| f.rule_id == rule_id).count();
    Ok(json!({
        "ok": true,
        "persisted": false,
        "persistence_mode": "session_overlay",
        "rule_id": rule_id,
        "helpful": helpful,
        "norns_learning_queued": true,
        "total_feedback_for_rule": total_for_rule,
        "recorded_at": ts
    }))
}

pub fn get_config() -> AdvisorConfigState {
    read_overlay().config.clone().unwrap_or_default()
}

pub fn update_config(next: AdvisorConfigState) -> Result<AdvisorConfigState, &'static str> {
    if !matches!(next.low_cpu_threshold_p95, 5 | 10 | 15 | 20) {
        return Err("low_cpu_threshold_p95 must be one of 5, 10, 15, 20");
    }
    if !matches!(next.lookback_days, 7 | 14 | 30 | 60) {
        return Err("lookback_days must be one of 7, 14, 30, 60");
    }
    if !matches!(next.ri_term.as_str(), "P1Y" | "P3Y") {
        return Err("ri_term must be P1Y or P3Y");
    }
    if !matches!(
        next.environment_profile.as_str(),
        "balanced" | "prod_strict" | "dev_cost_first"
    ) {
        return Err("invalid environment_profile");
    }
    if next.excluded_resource_groups.len() > MAX_OVERLAY_ITEMS
        || !next.min_monthly_savings_usd.is_finite()
        || next.min_monthly_savings_usd < 0.0
    {
        return Err("invalid_config_bounds");
    }
    let mut clean = next;
    clean.updated_at = now_iso();
    let mut g = write_overlay();
    g.config = Some(clean.clone());
    Ok(clean)
}

pub fn list_alerts() -> Vec<AdvisorAlertItem> {
    read_overlay().alerts.clone()
}

pub fn upsert_alert(item: AdvisorAlertItem) -> Result<AdvisorAlertItem, &'static str> {
    let mut g = write_overlay();
    if let Some(pos) = g.alerts.iter().position(|a| a.id == item.id) {
        g.alerts[pos] = item.clone();
        return Ok(item);
    }
    if g.alerts.len() >= MAX_OVERLAY_ITEMS {
        return Err("alert_capacity_exceeded");
    }
    g.alerts.insert(0, item.clone());
    Ok(item)
}

pub fn mutate_alerts(ids: &[String], op: &str) -> usize {
    let mut g = write_overlay();
    let set: BTreeSet<&str> = ids.iter().map(|s| s.as_str()).collect();
    match op {
        "delete" => {
            let before = g.alerts.len();
            g.alerts.retain(|a| !set.contains(a.id.as_str()));
            before - g.alerts.len()
        }
        "enable" => {
            let mut n = 0;
            for a in &mut g.alerts {
                if set.contains(a.id.as_str()) {
                    a.enabled = true;
                    n += 1;
                }
            }
            n
        }
        "disable" => {
            let mut n = 0;
            for a in &mut g.alerts {
                if set.contains(a.id.as_str()) {
                    a.enabled = false;
                    n += 1;
                }
            }
            n
        }
        _ => 0,
    }
}

pub fn list_digests() -> Vec<AdvisorDigestItem> {
    read_overlay().digests.clone()
}

pub fn upsert_digest(item: AdvisorDigestItem) -> Result<AdvisorDigestItem, &'static str> {
    let mut g = write_overlay();
    if let Some(pos) = g.digests.iter().position(|d| d.id == item.id) {
        g.digests[pos] = item.clone();
        return Ok(item);
    }
    if g.digests.len() >= MAX_OVERLAY_ITEMS {
        return Err("digest_capacity_exceeded");
    }
    g.digests.insert(0, item.clone());
    Ok(item)
}

pub fn mutate_digests(ids: &[String], op: &str) -> usize {
    let mut g = write_overlay();
    let set: BTreeSet<&str> = ids.iter().map(|s| s.as_str()).collect();
    match op {
        "delete" => {
            let before = g.digests.len();
            g.digests.retain(|d| !set.contains(d.id.as_str()));
            before - g.digests.len()
        }
        "enable" => {
            let mut n = 0;
            for d in &mut g.digests {
                if set.contains(d.id.as_str()) {
                    d.enabled = true;
                    n += 1;
                }
            }
            n
        }
        "disable" => {
            let mut n = 0;
            for d in &mut g.digests {
                if set.contains(d.id.as_str()) {
                    d.enabled = false;
                    n += 1;
                }
            }
            n
        }
        _ => 0,
    }
}

pub fn list_assessments() -> Vec<AdvisorAssessmentItem> {
    read_overlay().assessments.clone()
}

pub fn create_assessment(
    name: String,
    framework: String,
    workload: String,
    snap: &EvaluationSnapshot,
) -> Result<AdvisorAssessmentItem, &'static str> {
    let mut g = write_overlay();
    if g.assessments.len() >= MAX_OVERLAY_ITEMS {
        return Err("assessment_capacity_exceeded");
    }
    let active_recs = snap.rules.iter().filter(|r| r.active_count > 0).count();
    let item = AdvisorAssessmentItem {
        id: format!("assess-{}", now_epoch_s()),
        name,
        framework,
        workload,
        status: "in_progress".to_string(),
        auto_checked: if snap.measured { snap.rules.len() } else { 0 },
        manual_receipts: 0,
        recommendations_found: active_recs,
        score_pct: snap.overall_score_pct,
        last_refreshed_at: now_iso(),
    };
    g.assessments.insert(0, item.clone());
    Ok(item)
}

fn evaluate_seven_safeguards(
    rule: &EvaluatedRuleSummary,
    count: usize,
    total_neighbors: usize,
) -> (Vec<Value>, bool) {
    let has_targets = count > 0;
    let within_blast = has_targets && count <= BLAST_RADIUS_MAX_TARGETS;
    let rollback_ready = rule.downtime_class != "redeploy_required";
    let dry_run_ready = has_targets && rule.automation_mode != "manual_guidance";
    let target_lock_ready = has_targets;
    let idempotency_ready = has_targets && !rule.id.is_empty();
    let audit_ready = true;
    let stop_cond_ready = has_targets;

    let checks = vec![
        json!({ "id": "stop_condition", "label": "중단 조건 (Stop condition)", "satisfied": stop_cond_ready, "detail": if stop_cond_ready { "Wave 1 카나리 실패 또는 에러율 상승 시 즉시 중단" } else { "대상 리소스 0건 — 중단 조건 바인딩 불가" } }),
        json!({ "id": "tested_rollback", "label": "검증된 롤백 (Tested rollback)", "satisfied": rollback_ready, "detail": if rollback_ready { "Vidar 보상 액션 / Git revert PR 참조 검증 가능" } else { "재배포(redeploy_required) 작업 — 블루/그린 롤백 사전 테스트 필수 (현재 미검증)" } }),
        json!({ "id": "blast_radius", "label": "영향 반경 상한 (Blast radius)", "satisfied": within_blast, "detail": format!("대상 {}개 (상한 {}개) · 연결 온톨로지 이웃 {}개", count, BLAST_RADIUS_MAX_TARGETS, total_neighbors) }),
        json!({ "id": "dry_run", "label": "사전 Dry-Run 검증", "satisfied": dry_run_ready, "detail": if dry_run_ready { "Shadow 정책 평가 및 IaC diff 초안 생성 완료" } else { "수동 가이드 전용 규칙 — 자동 Dry-Run 미지원" } }),
        json!({ "id": "target_lock", "label": "논리 대상 잠금 (Target lock)", "satisfied": target_lock_ready, "detail": if target_lock_ready { "리소스 ID별 동시 변경 상호 배제 잠금 준비" } else { "잠금 대상 없음" } }),
        json!({ "id": "idempotency", "label": "안정 멱등성 키 (Idempotency)", "satisfied": idempotency_ready, "detail": format!("adv:{}:{}", rule.id, now_epoch_s() / 60) }),
        json!({ "id": "two_phase_audit", "label": "2단계 불변 감사 (Saga)", "satisfied": audit_ready, "detail": "제안(Pre-commit) + 완료(Post-verify) 감사 해시 체인" }),
    ];
    let blocked = checks
        .iter()
        .any(|c| c.get("satisfied").and_then(Value::as_bool) != Some(true));
    (checks, blocked)
}

pub fn build_review_fix_plan(
    rule: &EvaluatedRuleSummary,
    target_resource_ids: &[String],
) -> Value {
    let selected: Vec<&EvaluatedResourceInstance> = if target_resource_ids.is_empty() {
        rule.instances
            .iter()
            .filter(|i| i.effective_bucket == "active")
            .take(5)
            .collect()
    } else {
        let set: BTreeSet<&str> = target_resource_ids.iter().map(|s| s.as_str()).collect();
        rule.instances
            .iter()
            .filter(|i| set.contains(i.resource_id.as_str()))
            .collect()
    };
    let count = selected.len();
    let wave1 = count.min(1);
    let wave2 = count.saturating_sub(wave1);
    let first_name = selected
        .first()
        .map(|s| s.resource_name.as_str())
        .unwrap_or("target-resource");
    let total_neighbors: usize = selected.iter().map(|s| s.neighbors_count).sum();
    let (seven_safeguards, execution_blocked) =
        evaluate_seven_safeguards(rule, count, total_neighbors);

    let terraform_diff = format!(
        "# FDAI IaC-First Fix PR Preview ({rule_id})\nresource \"azurerm_resource\" \"{first_name}\" {{\n  # ActionType: {action}\n  # Owner Agent: {agent} -> Forseti({tier}) -> Var(HIL) -> Thor\n+ target_compliance_state = \"enabled\"\n+ fdai_rule_ref           = \"{rule_id}\"\n}}",
        rule_id = rule.id,
        action = rule.action_type_ref,
        agent = rule.owner_agent,
        tier = rule.risk_tier,
    );

    json!({
        "rule_id": rule.id,
        "title_ko": rule.title_ko,
        "target_count": count,
        "execution_blocked": execution_blocked,
        "selected_resources": selected.iter().map(|s| json!({
            "resource_id": s.resource_id,
            "resource_name": s.resource_name,
            "resource_group": s.resource_group,
            "location": s.location,
            "neighbors_count": s.neighbors_count
        })).collect::<Vec<_>>(),
        "pantheon_pipeline": [
            { "step": 1, "agent": "Bragi", "role": "의도·컨텍스트 브리핑", "status": "ready", "detail": format!("{}개 대상 리소스 및 온톨로지 근거 패키징 완료", count) },
            { "step": 2, "agent": "Mimir", "role": "규칙 · ActionType 바인딩", "status": "ready", "detail": format!("{} ({})", rule.action_type_ref, rule.waf_ref) },
            { "step": 3, "agent": "Odin", "role": "교차 필러 충돌 중재", "status": "ready", "detail": rule.odin_verdict_ko },
            { "step": 4, "agent": "Forseti", "role": "위험도·정책 판정", "status": if execution_blocked { "blocked" } else { "ready" }, "detail": format!("위험 등급 {} · 다운타임 분류 {} · Fail-Closed 차단={}", rule.risk_tier, rule.downtime_class, execution_blocked) },
            { "step": 5, "agent": "Var", "role": "독립 인간 승인(HIL)", "status": "pending_approval", "detail": "콘솔은 읽기 전용 권한 경계를 유지하며 승인 큐(hil-queue) 또는 Fix PR 리뷰로 라우팅" },
            { "step": 6, "agent": "Thor", "role": "유일 실행기 / Fix PR 생성", "status": if execution_blocked { "blocked" } else { "gated" }, "detail": if execution_blocked { "7대 안전장치 미충족 항목 해소 전까지 자동 실행 차단(Fail-Closed)" } else { "승인 완료 시 IaC Fix PR 또는 가드된 실행 파이프라인 착수" } },
            { "step": 7, "agent": "Heimdall · Vidar · Saga", "role": "독립 효과 검증 · 롤백 · 감사", "status": "armed", "detail": "실행 후 독립 관측 검증 및 이상 시 자동 롤백 + 불변 감사 체인 기록" }
        ],
        "seven_safeguards": seven_safeguards,
        "canary_waves": [
            { "wave": 1, "label": "Wave 1 · 카나리 검증", "count": wave1, "gate": "Heimdall 독립 효과 검증 통과 후 Wave 2 진행" },
            { "wave": 2, "label": "Wave 2 · 잔여 배치 롤아웃", "count": wave2, "gate": "이상 감지 시 즉시 중단 및 Vidar 롤백" }
        ],
        "iac_fix_pr_preview": terraform_diff,
        "execution_authority_notice": "FDAI Console은 읽기 전용 경계를 유지합니다. 실제 Azure 리소스 변경은 7대 안전장치 충족 + Var 승인/Fix PR 병합 후 Thor 실행기에서만 수행됩니다."
    })
}
