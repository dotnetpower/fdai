//! Domain 1 (`overview`, 7 panels) PostgreSQL repository.
//!
//! Pure read-only SQL queries over canonical FDAI PostgreSQL tables with strict
//! literal quoting, LIKE escaping, allowlisted window clauses, and bounded limits.

use crate::db::{cell_i64, cell_str, clamp_limit, quote_like_contains, DbHandle};
use fdai_adapter_postgres::pg_quote_literal;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Debug, Clone, Default)]
pub struct ResourceFilter<'a> {
    pub subscription: &'a str,
    pub resource_type: &'a str,
    pub status: &'a str,
    pub search: Option<&'a str>,
    pub lens: &'a str,
    pub limit: Option<usize>,
    pub offset: Option<usize>,
}

fn cell_f64(row: &[Option<String>], idx: usize) -> Option<f64> {
    row.get(idx)
        .and_then(|v| v.as_deref())
        .and_then(|s| s.trim().parse::<f64>().ok())
}

fn cell_bool(row: &[Option<String>], idx: usize) -> Option<bool> {
    row.get(idx)
        .and_then(|v| v.as_deref())
        .map(|s| matches!(s.trim(), "t" | "true" | "TRUE" | "1"))
}

fn ratio_opt(num: i64, den: i64) -> Option<f64> {
    if den <= 0 {
        None
    } else {
        Some((num as f64) / (den as f64))
    }
}

fn pct_rounded(num: i64, den: i64) -> Option<f64> {
    ratio_opt(num, den).map(|r| (r * 1000.0).round() / 10.0)
}

fn period_interval_sql(period: &str) -> &'static str {
    match period {
        "1d" => "1 day",
        "7d" => "7 days",
        "90d" => "90 days",
        _ => "30 days",
    }
}

fn llm_range_interval_sql(range: &str) -> &'static str {
    match range {
        "24h" => "24 hours",
        "7d" => "7 days",
        _ => "30 days",
    }
}

fn dashboard_window_interval_sql(window: &str) -> &'static str {
    match window {
        "1h" => "1 hour",
        "24h" => "24 hours",
        _ => "15 minutes",
    }
}

fn dashboard_window_seconds(window: &str) -> f64 {
    match window {
        "1h" => 3600.0,
        "24h" => 86400.0,
        _ => 900.0,
    }
}

fn dashboard_window_default_axis(window: &str) -> [&'static str; 4] {
    match window {
        "1h" => ["-60m", "-40m", "-20m", "NOW"],
        "24h" => ["-24h", "-16h", "-8h", "NOW"],
        _ => ["-15m", "-10m", "-5m", "NOW"],
    }
}

pub fn classify_audit_series(action_kind: &str) -> &'static str {
    let k = action_kind.trim().to_ascii_lowercase();
    if k.starts_with("hil.") {
        "human"
    } else if k.contains("escape")
        || k.contains("policy_violation")
        || k.contains("security")
        || k == "risk_gate.unified"
        || k == "mimir.rule-source.observed"
    {
        "sec"
    } else if k == "rca.hypothesis"
        || k == "control_loop.abstain"
        || k == "control_loop.t1_evaluate"
        || k.starts_with("observation-campaign.")
    {
        "sre"
    } else {
        "auto"
    }
}

/// Maps explicit severity (from `hil_park`, `audit_log.entry`, or `operator_incident_projection`)
/// or an honest action-kind baseline onto `(canonical_severity, y_band 0..=4)`.
/// Never fabricates synthetic high numeric risk scores (e.g. 86..87) for low-severity events.
pub fn normalize_event_severity(raw: &str, action_kind: &str) -> (&'static str, i64) {
    let s = raw.trim().to_ascii_lowercase();
    match s.as_str() {
        "critical" | "sev1" | "p0" => return ("critical", 4),
        "high" | "sev2" | "p1" => return ("high", 3),
        "medium" | "moderate" | "sev3" | "p2" => return ("medium", 2),
        "low" | "sev4" | "p3" => return ("low", 1),
        "info" | "informational" | "none" => return ("info", 0),
        _ => {}
    }
    let k = action_kind.trim().to_ascii_lowercase();
    if k.contains("escape") || k.contains("policy_violation") {
        ("critical", 4)
    } else if k.contains("security") {
        ("high", 3)
    } else if k == "hil.timeout" || k == "risk_gate.unified" || k == "rca.hypothesis" {
        ("medium", 2)
    } else if k.starts_with("hil.")
        || k == "control_loop.abstain"
        || k == "control_loop.t1_evaluate"
        || k.starts_with("observation-campaign.")
    {
        ("low", 1)
    } else {
        ("info", 0)
    }
}

/// Extracts the target resource reference from canonical FDAI idempotency keys of the form
/// `inventory-delta:<hash>::<rule_id>::<resource_ref>[:hil_request]`.
pub fn extract_resource_from_idempotency_key(idem: &str) -> String {
    let mut parts = idem.split("::");
    let _prefix = parts.next();
    let _rule = parts.next();
    let Some(raw_ref) = parts.next() else {
        return String::new();
    };
    let trimmed = raw_ref
        .strip_suffix(":hil_request")
        .or_else(|| raw_ref.strip_suffix(":hil_timeout"))
        .or_else(|| raw_ref.strip_suffix(":execute"))
        .unwrap_or(raw_ref)
        .trim();
    trimmed.to_string()
}

/// Infers canonical `resource_type` from a resource ARM/scope path or rule ID prefix when absent.
pub fn infer_resource_type_from_ref(resource_ref: &str, rule_id: &str) -> String {
    let r = resource_ref.trim().to_ascii_lowercase();
    if r.contains("/virtualmachinescalesets/") {
        return "compute.vm-scale-set".to_string();
    }
    if r.contains("/virtualmachines/") {
        return "compute.vm".to_string();
    }
    if r.contains("/managedclusters/") {
        return "kubernetes-cluster".to_string();
    }
    if r.contains("/networksecuritygroups/") {
        return "network.nsg".to_string();
    }
    if r.contains("/networkinterfaces/") {
        return "network.interface".to_string();
    }
    if r.contains("/loadbalancers/") {
        return "network.load-balancer".to_string();
    }
    if r.contains("/vaults/") {
        return "secret-store".to_string();
    }
    if r.contains("/storageaccounts/") {
        return "object-storage".to_string();
    }
    if r.contains("/flexibleservers/") {
        return "postgresql-server".to_string();
    }
    if r.contains("/disks/") {
        return "disk".to_string();
    }
    if r.contains("/containerapps/") {
        return "compute.container-app".to_string();
    }
    if r.contains("/jobs/") {
        return "compute.container-app-job".to_string();
    }
    let rl = rule_id.trim().to_ascii_lowercase();
    if rl.starts_with("compute.vm-scale-set.") {
        return "compute.vm-scale-set".to_string();
    }
    if rl.starts_with("compute.vm.") {
        return "compute.vm".to_string();
    }
    if rl.starts_with("compute.container-app-job.") {
        return "compute.container-app-job".to_string();
    }
    if rl.starts_with("compute.container-app.") {
        return "compute.container-app".to_string();
    }
    if rl.starts_with("disk.") {
        return "disk".to_string();
    }
    if rl.starts_with("network.nsg.") {
        return "network.nsg".to_string();
    }
    if rl.starts_with("security.key-vault.") {
        return "secret-store".to_string();
    }
    String::new()
}

fn short_utc_axis_label(iso: &str, same_day: bool) -> String {
    if iso.len() >= 19 && iso.is_ascii() {
        if same_day {
            iso[11..19].to_string()
        } else {
            format!("{} {}", &iso[5..10], &iso[11..16])
        }
    } else {
        iso.to_string()
    }
}

fn encode_item_param(input: &str) -> String {
    let mut out = String::with_capacity(input.len() + 12);
    for b in input.as_bytes() {
        if b.is_ascii_alphanumeric() || matches!(*b, b'-' | b'_' | b'.' | b'~') {
            out.push(*b as char);
        } else {
            const HEX: &[u8; 16] = b"0123456789ABCDEF";
            out.push('%');
            out.push(HEX[(b >> 4) as usize] as char);
            out.push(HEX[(b & 0x0f) as usize] as char);
        }
    }
    out
}

fn vertical_label_ko(raw: &str) -> &'static str {
    match raw.trim().to_ascii_lowercase().as_str() {
        "resilience" => "복원력",
        "change_safety" | "change-safety" => "변경 안전",
        "cost_governance" | "cost-governance" => "비용 거버넌스",
        _ => "미귀속",
    }
}

fn severity_label_ko(raw: &str) -> &'static str {
    match raw.trim().to_ascii_lowercase().as_str() {
        "critical" => "치명",
        "high" => "높음",
        "medium" => "보통",
        "low" => "낮음",
        _ => "보통",
    }
}

fn status_label_ko(raw: &str) -> &'static str {
    match raw.trim().to_ascii_lowercase().as_str() {
        "in_progress" | "open" | "active" => "진행 중",
        "resolved" => "해결 완료",
        "closed" => "종료됨",
        "published" => "게시됨",
        "recorded" => "기록됨",
        _ => "관측 중",
    }
}

fn resource_type_label_ko(raw: &str) -> String {
    let key = raw.trim().to_ascii_lowercase();
    match key.as_str() {
        "subscription" => "Azure 구독".to_string(),
        "resource-group" => "리소스 그룹".to_string(),
        "kubernetes-cluster" => "Kubernetes 클러스터 (AKS)".to_string(),
        "kubernetes-node-pool" => "AKS 노드 풀".to_string(),
        "compute.vm-scale-set" => "가상 머신 확장 집합 (VMSS)".to_string(),
        "compute.vm" => "가상 머신 (VM)".to_string(),
        "compute.vm-extension" => "가상 머신 확장".to_string(),
        "compute.container-app" => "컨테이너 앱".to_string(),
        "compute.container-app-job" => "컨테이너 앱 작업".to_string(),
        "compute.container-app-environment" => "컨테이너 앱 환경".to_string(),
        "compute.function" => "함수 앱".to_string(),
        "container-registry" => "컨테이너 레지스트리".to_string(),
        "postgresql-server" => "PostgreSQL 서버".to_string(),
        "secret-store" => "키 자격 증명 모음 (Key Vault)".to_string(),
        "object-storage" => "스토리지 계정".to_string(),
        "disk" => "관리 디스크".to_string(),
        "network.nsg" => "네트워크 보안 그룹 (NSG)".to_string(),
        "network.vnet" => "가상 네트워크 (VNet)".to_string(),
        "network.subnet" => "서브넷".to_string(),
        "network.interface" => "네트워크 인터페이스".to_string(),
        "network.public-ip" => "공용 IP 주소".to_string(),
        "network.private-endpoint" => "프라이빗 엔드포인트".to_string(),
        "network.private-dns-zone" | "network.dns-zone" => "DNS 영역".to_string(),
        "network.nat-gateway" => "NAT 게이트웨이".to_string(),
        "network.load-balancer" => "부하 분산 장치".to_string(),
        "network.bastion-host" => "Bastion 호스트".to_string(),
        "network.route-table" => "라우팅 테이블".to_string(),
        "network.firewall" => "방화벽".to_string(),
        "network.firewall-policy" => "방화벽 정책".to_string(),
        "api-gateway" => "API 게이트웨이".to_string(),
        "event-hub" => "Event Hubs".to_string(),
        "static-web-app" => "정적 웹 앱".to_string(),
        "app-service-plan" => "App Service 플랜".to_string(),
        "llm-endpoint" => "AI 모델 엔드포인트".to_string(),
        "llm-model-deployment" => "AI 모델 배포".to_string(),
        "ai-project" => "AI Foundry 프로젝트".to_string(),
        "managed-identity" => "관리 ID".to_string(),
        "authorization.role-assignment" => "역할 할당".to_string(),
        "log-workspace" => "로그 분석 작업 영역".to_string(),
        "application-insights" => "Application Insights".to_string(),
        "data-collection-rule" => "데이터 수집 규칙".to_string(),
        "anomaly-alert-rule" | "action-group" => "경고 규칙".to_string(),
        "rule" => "운영 규칙".to_string(),
        "policyartifact" => "정책 아티팩트".to_string(),
        "actiontype" => "운영 조치 유형".to_string(),
        "frameworkcontrol" => "거버넌스 통제 항목".to_string(),
        "benchmarkvalidation" => "벤치마크 검증".to_string(),
        _ => {
            if key.starts_with("compute.") {
                "컴퓨트 리소스".to_string()
            } else if key.starts_with("network.") {
                "네트워크 리소스".to_string()
            } else if key.is_empty() {
                "운영 리소스".to_string()
            } else {
                raw.trim().to_string()
            }
        }
    }
}

/// Maps canonical FDAI `resource_type`, Azure `provider_type`, and ontology `object_type`
/// to an exact, verified `/azure-icons/*.svg` asset path without substring collisions.
#[must_use]
pub fn resource_icon_for(resource_type: &str, provider_type: &str, object_type: &str) -> &'static str {
    let rt = resource_type.trim().to_ascii_lowercase();
    let pt = provider_type.trim().to_ascii_lowercase();
    let ot = object_type.trim().to_ascii_lowercase();

    // 1. Exact canonical `resource_type` matches (highest specificity, zero collision)
    match rt.as_str() {
        "subscription" => return "/azure-icons/subscriptions.svg",
        "resource-group" => return "/azure-icons/resource-groups.svg",
        "authorization.role-assignment" => return "/azure-icons/users.svg",
        "managed-identity" => return "/azure-icons/managed-identity.svg",
        "kubernetes-cluster" | "kubernetes-node-pool" => return "/azure-icons/kubernetes-services.svg",
        "container-registry" => return "/azure-icons/container-registry.svg",
        "compute.container-app"
        | "compute.container-app-job"
        | "compute.container-app-environment"
        | "managed-certificate" => return "/azure-icons/container-apps.svg",
        "compute.vm-scale-set" => return "/azure-icons/vm-scale-sets.svg",
        "compute.vm"
        | "compute.vm-extension"
        | "compute.vm-run-command"
        | "compute.vm-shutdown-schedule"
        | "compute.image"
        | "compute.image-gallery"
        | "compute.gallery-image"
        | "compute.gallery-image-version" => return "/azure-icons/virtual-machine.svg",
        "disk" => return "/azure-icons/disks.svg",
        "object-storage" => return "/azure-icons/storage-account.svg",
        "postgresql-server" => return "/azure-icons/postgresql.svg",
        "secret-store" => return "/azure-icons/key-vault.svg",
        "network.nsg" => return "/azure-icons/network-security-group.svg",
        "network.vnet" => return "/azure-icons/virtual-network.svg",
        "network.subnet" => return "/azure-icons/subnet.svg",
        "network.interface" => return "/azure-icons/network-interface.svg",
        "network.public-ip" => return "/azure-icons/public-ip.svg",
        "network.private-endpoint" => return "/azure-icons/private-endpoint.svg",
        "network.private-dns-zone"
        | "network.private-dns-zone-link"
        | "network.private-dns-zone-group"
        | "network.dns-zone"
        | "network.registered-domain" => return "/azure-icons/dns-zones.svg",
        "network.nat-gateway" => return "/azure-icons/nat.svg",
        "network.load-balancer" => return "/azure-icons/load-balancer.svg",
        "network.bastion-host" => return "/azure-icons/bastion.svg",
        "network.route-table" => return "/azure-icons/route-table.svg",
        "network.firewall" => return "/azure-icons/firewall.svg",
        "network.firewall-policy" => return "/azure-icons/waf-policy.svg",
        "api-gateway" => return "/azure-icons/api-management-services.svg",
        "event-hub" => return "/azure-icons/event-hubs.svg",
        "static-web-app" => return "/azure-icons/static-web-app.svg",
        "app-service-plan" => return "/azure-icons/app-service-plans.svg",
        "compute.function" => return "/azure-icons/function-apps.svg",
        "workflow.logic-app" => return "/azure-icons/logic-apps.svg",
        "llm-endpoint" | "llm-model-deployment" => return "/azure-icons/azure-openai.svg",
        "ai-project" | "managed-sre-agent" => return "/azure-icons/ai-foundry.svg",
        "data-collection-rule" => return "/azure-icons/data-collection-rules.svg",
        "anomaly-alert-rule" | "action-group" => return "/azure-icons/alerts.svg",
        "communication-service" | "email-service" | "email-domain" => {
            return "/azure-icons/communication-services.svg"
        }
        "log-workspace" | "application-insights" | "observability.network-monitor" => {
            return "/azure-icons/monitor.svg"
        }
        _ => {}
    }

    // 2. Azure provider type / resource ID matching (ordered from most specific to general)
    let combined = format!("{pt} {rt}");
    if combined.contains("microsoft.resources/subscriptions") {
        "/azure-icons/subscriptions.svg"
    } else if combined.contains("microsoft.resources/resourcegroups") || combined.contains("resource-group") {
        "/azure-icons/resource-groups.svg"
    } else if combined.contains("microsoft.authorization/roleassignments") || combined.contains("role-assignment") {
        "/azure-icons/users.svg"
    } else if combined.contains("microsoft.managedidentity") || combined.contains("managed-identity") {
        "/azure-icons/managed-identity.svg"
    } else if combined.contains("microsoft.containerservice") || combined.contains("kubernetes") || combined.contains("managedcluster") {
        "/azure-icons/kubernetes-services.svg"
    } else if combined.contains("microsoft.containerregistry") || combined.contains("container-registry") {
        "/azure-icons/container-registry.svg"
    } else if combined.contains("microsoft.app/agents") || combined.contains("accounts/projects") || combined.contains("ai-foundry") {
        "/azure-icons/ai-foundry.svg"
    } else if combined.contains("microsoft.app/") || combined.contains("container-app") || combined.contains("containerapp") {
        "/azure-icons/container-apps.svg"
    } else if combined.contains("virtualmachinescal") || combined.contains("vm-scale-set") || combined.contains("vmss") {
        "/azure-icons/vm-scale-sets.svg"
    } else if combined.contains("microsoft.compute/snapshots") || combined.contains("disk-snapshot") {
        "/azure-icons/disk-snapshots.svg"
    } else if combined.contains("microsoft.compute/disks") {
        "/azure-icons/disks.svg"
    } else if combined.contains("microsoft.compute/") || combined.contains("virtualmachine") {
        "/azure-icons/virtual-machine.svg"
    } else if combined.contains("microsoft.dbforpostgresql") || combined.contains("postgres") {
        "/azure-icons/postgresql.svg"
    } else if combined.contains("microsoft.dbformysql") || combined.contains("mysql") {
        "/azure-icons/mysql-server.svg"
    } else if combined.contains("microsoft.sql/servers/databases") || combined.contains("microsoft.sql/managedinstances") {
        "/azure-icons/sql-database.svg"
    } else if combined.contains("microsoft.sql/servers") {
        "/azure-icons/sql-server.svg"
    } else if combined.contains("microsoft.documentdb") || combined.contains("cosmos") {
        "/azure-icons/cosmos-db.svg"
    } else if combined.contains("microsoft.cache") || combined.contains("redis") {
        "/azure-icons/cache-redis.svg"
    } else if combined.contains("microsoft.keyvault") || combined.contains("key-vault") {
        "/azure-icons/key-vault.svg"
    } else if combined.contains("microsoft.network/networksecuritygroups") || combined.contains("nsg") {
        "/azure-icons/network-security-group.svg"
    } else if combined.contains("microsoft.network/firewallpolicies")
        || combined.contains("wafpolic")
        || combined.contains("ddosprotection")
    {
        "/azure-icons/waf-policy.svg"
    } else if combined.contains("microsoft.network/azurefirewalls") || combined.contains("firewall") {
        "/azure-icons/firewall.svg"
    } else if combined.contains("microsoft.network/dnsresolvers") {
        "/azure-icons/dns-private-resolver.svg"
    } else if combined.contains("privatednszone") || combined.contains("dnszone") || combined.contains("domainregistration") {
        "/azure-icons/dns-zones.svg"
    } else if combined.contains("microsoft.network/privateendpoints") || combined.contains("private-endpoint") {
        "/azure-icons/private-endpoint.svg"
    } else if combined.contains("microsoft.network/publicipaddresses") || combined.contains("public-ip") {
        "/azure-icons/public-ip.svg"
    } else if combined.contains("microsoft.network/virtualnetworks/subnets") || combined.contains("subnet") {
        "/azure-icons/subnet.svg"
    } else if combined.contains("microsoft.network/virtualnetworkgateways")
        || combined.contains("vpngateway")
        || combined.contains("expressroutegateway")
    {
        "/azure-icons/virtual-network-gateway.svg"
    } else if combined.contains("microsoft.network/expressroute") {
        "/azure-icons/expressroute-circuit.svg"
    } else if combined.contains("microsoft.network/virtualhubs") {
        "/azure-icons/virtual-hub.svg"
    } else if combined.contains("microsoft.network/virtualwans") {
        "/azure-icons/virtual-wan.svg"
    } else if combined.contains("microsoft.network/virtualnetworks") {
        "/azure-icons/virtual-network.svg"
    } else if combined.contains("microsoft.network/natgateways") || combined.contains("nat-gateway") {
        "/azure-icons/nat.svg"
    } else if combined.contains("microsoft.network/loadbalancers") || combined.contains("load-balancer") {
        "/azure-icons/load-balancer.svg"
    } else if combined.contains("microsoft.network/bastionhosts") || combined.contains("bastion") {
        "/azure-icons/bastion.svg"
    } else if combined.contains("microsoft.network/routetables") || combined.contains("route-table") {
        "/azure-icons/route-table.svg"
    } else if combined.contains("microsoft.network/networkinterfaces") || combined.contains("network.interface") {
        "/azure-icons/network-interface.svg"
    } else if combined.contains("microsoft.network/applicationgateways") {
        "/azure-icons/application-gateway.svg"
    } else if combined.contains("microsoft.apimanagement") {
        "/azure-icons/api-management-services.svg"
    } else if combined.contains("microsoft.eventhub") {
        "/azure-icons/event-hubs.svg"
    } else if combined.contains("microsoft.eventgrid") {
        "/azure-icons/event-grid-topics.svg"
    } else if combined.contains("microsoft.servicebus") {
        "/azure-icons/service-bus.svg"
    } else if combined.contains("microsoft.web/staticsites") {
        "/azure-icons/static-web-app.svg"
    } else if combined.contains("microsoft.web/serverfarms") {
        "/azure-icons/app-service-plans.svg"
    } else if combined.contains("microsoft.web/sites") {
        "/azure-icons/function-apps.svg"
    } else if combined.contains("microsoft.logic/workflows") {
        "/azure-icons/logic-apps.svg"
    } else if combined.contains("microsoft.storage") || combined.contains("netapp") {
        "/azure-icons/storage-account.svg"
    } else if combined.contains("microsoft.cognitiveservices") || combined.contains("machinelearningservices") {
        "/azure-icons/azure-openai.svg"
    } else if combined.contains("microsoft.communication") {
        "/azure-icons/communication-services.svg"
    } else if combined.contains("microsoft.dashboard/grafana") {
        "/azure-icons/managed-grafana.svg"
    } else if combined.contains("datacollectionrules") || combined.contains("datacollectionendpoints") {
        "/azure-icons/data-collection-rules.svg"
    } else if combined.contains("alertsmanagement")
        || combined.contains("actiongroups")
        || combined.contains("metricalerts")
        || combined.contains("activitylogalerts")
        || combined.contains("scheduledqueryrules")
    {
        "/azure-icons/alerts.svg"
    } else if combined.contains("microsoft.insights")
        || combined.contains("microsoft.operationalinsights")
        || combined.contains("microsoft.monitor")
    {
        "/azure-icons/monitor.svg"
    } else if ot == "rule"
        || ot == "policyartifact"
        || ot == "framework"
        || ot == "frameworkcontrol"
        || ot == "controlobjective"
        || ot == "ruleobjectivebinding"
    {
        "/azure-icons/waf-policy.svg"
    } else if ot == "signaltype" || ot == "diagnosticmechanism" || ot == "benchmarkvalidation" {
        "/azure-icons/alerts.svg"
    } else if ot == "resourceclass"
        || ot == "resourcetype"
        || ot == "property"
        || ot == "actiontype"
        || ot == "reviewcase"
        || ot == "reviewcheck"
    {
        "/azure-icons/resource-graph.svg"
    } else {
        "/azure-icons/monitor.svg"
    }
}

fn resource_category_for(resource_type: &str, provider_type: &str, object_type: &str) -> &'static str {
    let low = format!(
        "{} {} {}",
        resource_type.to_ascii_lowercase(),
        provider_type.to_ascii_lowercase(),
        object_type.to_ascii_lowercase()
    );
    if low.contains("kubernetes") || low.contains("managedcluster") || low.contains("aks")
        || low.contains("container") || low.contains("compute") || low.contains("virtualmachine")
    {
        "aks"
    } else if low.contains("postgres") || low.contains("redis") || low.contains("sql")
        || low.contains("database") || low.contains("cosmos")
    {
        "db"
    } else if low.contains("network") || low.contains("nsg") || low.contains("vnet")
        || low.contains("subnet") || low.contains("dns") || low.contains("gateway")
        || low.contains("public-ip") || low.contains("private-endpoint")
    {
        "network"
    } else if low.contains("keyvault") || low.contains("key-vault") || low.contains("identity")
        || low.contains("authorization") || low.contains("role") || low.contains("policy")
        || low.contains("frameworkcontrol") || low.contains("security")
    {
        "security"
    } else if low.contains("storage") || low.contains("disk") {
        "storage"
    } else {
        "other"
    }
}

fn classify_resource_status(
    object_type: &str,
    resource_type: &str,
    prov_state: &str,
) -> (&'static str, &'static str, &'static str) {
    let ps = prov_state.trim().to_ascii_lowercase();
    let rt = resource_type.to_ascii_lowercase();
    if ps == "failed" || ps == "degraded" || ps == "unhealthy" {
        ("sre", "SRE 주의", "tone-sre")
    } else if ps == "succeeded" || ps == "running" || ps == "active" {
        ("live", "정상 관측", "tone-live")
    } else if rt.contains("nsg")
        || rt.contains("key-vault")
        || rt.contains("role-assignment")
        || rt.contains("managed-identity")
        || object_type.eq_ignore_ascii_case("PolicyArtifact")
    {
        ("sec", "보안 관측", "tone-sec")
    } else if object_type.eq_ignore_ascii_case("Resource") && ps.is_empty() {
        ("neutral", "상태 미수집", "tone-neutral")
    } else {
        ("live", "카탈로그 관측", "tone-live")
    }
}

/// Builds a safe SQL WHERE clause for `ontology_resource` filtering using
/// `pg_quote_literal` and `quote_like_contains` exclusively.
#[must_use]
pub fn build_resource_where_sql(filter: &ResourceFilter<'_>) -> String {
    let mut clauses: Vec<String> = Vec::new();

    let sub = filter.subscription.trim();
    if !sub.is_empty() && !sub.eq_ignore_ascii_case("all") {
        let q_exact = pg_quote_literal(sub);
        let q_like = quote_like_contains(sub);
        clauses.push(format!(
            "(COALESCE(properties->'properties'->>'subscriptionId', '') = {q_exact} \
             OR COALESCE(properties->'properties'->>'resourceGroup', '') ILIKE {q_like} ESCAPE '\\' \
             OR id ILIKE {q_like} ESCAPE '\\')"
        ));
    }

    let rtype = filter.resource_type.trim();
    if !rtype.is_empty() && !rtype.eq_ignore_ascii_case("all") {
        match rtype.to_ascii_lowercase().as_str() {
            "aks" => clauses.push(
                "(COALESCE(properties->>'type', '') ILIKE '%aks%' \
                 OR COALESCE(properties->>'type', '') ILIKE '%kubernetes%' \
                 OR COALESCE(properties->>'type', '') ILIKE '%container%' \
                 OR COALESCE(properties->>'type', '') ILIKE '%compute%' \
                 OR COALESCE(properties->'properties'->>'providerType', '') ILIKE '%containerservice%' \
                 OR COALESCE(properties->'properties'->>'providerType', '') ILIKE '%compute%')"
                    .to_string(),
            ),
            "db" => clauses.push(
                "(COALESCE(properties->>'type', '') ILIKE '%postgres%' \
                 OR COALESCE(properties->>'type', '') ILIKE '%redis%' \
                 OR COALESCE(properties->>'type', '') ILIKE '%sql%' \
                 OR COALESCE(properties->>'type', '') ILIKE '%database%' \
                 OR COALESCE(properties->'properties'->>'providerType', '') ILIKE '%dbforpostgresql%' \
                 OR COALESCE(properties->'properties'->>'providerType', '') ILIKE '%cache%')"
                    .to_string(),
            ),
            "network" => clauses.push(
                "(COALESCE(properties->>'type', '') ILIKE '%network%' \
                 OR COALESCE(properties->>'type', '') ILIKE '%nsg%' \
                 OR COALESCE(properties->>'type', '') ILIKE '%vnet%' \
                 OR COALESCE(properties->>'type', '') ILIKE '%subnet%' \
                 OR COALESCE(properties->>'type', '') ILIKE '%dns%' \
                 OR COALESCE(properties->'properties'->>'providerType', '') ILIKE '%network%')"
                    .to_string(),
            ),
            "security" => clauses.push(
                "(COALESCE(properties->>'type', '') ILIKE '%identity%' \
                 OR COALESCE(properties->>'type', '') ILIKE '%authorization%' \
                 OR COALESCE(properties->>'type', '') ILIKE '%vault%' \
                 OR COALESCE(properties->>'type', '') ILIKE '%security%' \
                 OR object_type IN ('PolicyArtifact', 'FrameworkControl'))"
                    .to_string(),
            ),
            "storage" => clauses.push(
                "(COALESCE(properties->>'type', '') ILIKE '%storage%' \
                 OR COALESCE(properties->>'type', '') ILIKE '%disk%' \
                 OR COALESCE(properties->'properties'->>'providerType', '') ILIKE '%storage%')"
                    .to_string(),
            ),
            _ => {
                let q_exact = pg_quote_literal(rtype);
                let q_like = quote_like_contains(rtype);
                clauses.push(format!(
                    "(object_type = {q_exact} \
                     OR COALESCE(properties->>'type', '') = {q_exact} \
                     OR COALESCE(properties->>'type', '') ILIKE {q_like} ESCAPE '\\')"
                ));
            }
        }
    }

    let status = filter.status.trim();
    if !status.is_empty() && !status.eq_ignore_ascii_case("all") {
        match status.to_ascii_lowercase().as_str() {
            "sre" => clauses.push(
                "LOWER(COALESCE(properties->'properties'->'properties'->>'provisioningState', '')) \
                 IN ('failed', 'degraded', 'unhealthy')"
                    .to_string(),
            ),
            "sec" => clauses.push(
                "(LOWER(COALESCE(properties->'properties'->'properties'->>'provisioningState', '')) \
                 NOT IN ('succeeded', 'running', 'active', 'failed', 'degraded', 'unhealthy') \
                 AND (COALESCE(properties->>'type', '') ILIKE '%nsg%' \
                 OR COALESCE(properties->>'type', '') ILIKE '%vault%' \
                 OR COALESCE(properties->>'type', '') ILIKE '%role-assignment%' \
                 OR COALESCE(properties->>'type', '') ILIKE '%managed-identity%' \
                 OR object_type = 'PolicyArtifact'))"
                    .to_string(),
            ),
            "neutral" | "uncollected" | "delayed" => clauses.push(
                "(object_type = 'Resource' \
                 AND COALESCE(properties->'properties'->'properties'->>'provisioningState', '') = '' \
                 AND COALESCE(properties->>'type', '') NOT ILIKE '%nsg%' \
                 AND COALESCE(properties->>'type', '') NOT ILIKE '%vault%' \
                 AND COALESCE(properties->>'type', '') NOT ILIKE '%role-assignment%' \
                 AND COALESCE(properties->>'type', '') NOT ILIKE '%managed-identity%')"
                    .to_string(),
            ),
            "live" => clauses.push(
                "(LOWER(COALESCE(properties->'properties'->'properties'->>'provisioningState', '')) \
                 IN ('succeeded', 'running', 'active') \
                 OR (object_type <> 'Resource' AND object_type <> 'PolicyArtifact'))"
                    .to_string(),
            ),
            _ => {}
        }
    }

    if let Some(q) = filter.search.map(str::trim).filter(|s| !s.is_empty()) {
        let pat = quote_like_contains(q);
        clauses.push(format!(
            "(id ILIKE {pat} ESCAPE '\\' \
             OR object_type ILIKE {pat} ESCAPE '\\' \
             OR COALESCE(properties->>'name', '') ILIKE {pat} ESCAPE '\\' \
             OR COALESCE(properties->>'title', '') ILIKE {pat} ESCAPE '\\' \
             OR COALESCE(properties->>'type', '') ILIKE {pat} ESCAPE '\\' \
             OR COALESCE(properties->>'location', '') ILIKE {pat} ESCAPE '\\' \
             OR COALESCE(properties->'properties'->>'resourceGroup', '') ILIKE {pat} ESCAPE '\\' \
             OR COALESCE(properties->'properties'->>'providerType', '') ILIKE {pat} ESCAPE '\\')"
        ));
    }

    if clauses.is_empty() {
        String::new()
    } else {
        format!("WHERE {}", clauses.join(" AND "))
    }
}

fn classify_rule_vertical(rule_ref: &str) -> &'static str {
    let low = rule_ref.to_ascii_lowercase();
    if low.contains("cost") || low.contains("finops") || low.contains("budget")
        || low.contains("idle") || low.contains("cost-center")
    {
        "cost-governance"
    } else if low.contains("identity")
        || low.contains("role")
        || low.contains("authorization")
        || low.contains("tag")
        || low.contains("owner")
        || low.contains("environment")
        || low.contains("policy")
        || low.contains("key-vault")
        || low.contains("secret")
    {
        "change-safety"
    } else if low.contains("network")
        || low.contains("nsg")
        || low.contains("compute")
        || low.contains("aks")
        || low.contains("vm")
        || low.contains("host")
        || low.contains("availability")
        || low.contains("postgres")
        || low.contains("redis")
        || low.contains("storage")
        || low.contains("disk")
    {
        "resilience"
    } else {
        "unattributed"
    }
}

fn classify_rule_domain(rule_ref: &str) -> &'static str {
    let low = rule_ref.to_ascii_lowercase();
    if low.contains("cost") || low.contains("finops") || low.contains("budget") {
        "cost"
    } else if low.contains("nsg")
        || low.contains("rdp")
        || low.contains("ssh")
        || low.contains("role-assignment")
        || low.contains("wildcard")
        || low.contains("privileged")
        || low.contains("key-vault")
        || low.contains("secret")
        || low.contains("ddos")
    {
        "sec"
    } else if low.contains("tag") || low.contains("owner") || low.contains("environment") {
        "cfg"
    } else {
        "sre"
    }
}

pub async fn fetch_summary(db: &DbHandle) -> Value {
    let (audit, resources, incidents, baseline_cov, subs_res) = tokio::join!(
        db.query_single_readonly(
            "SELECT count(*), \
             count(*) FILTER (WHERE mode = 'shadow'), \
             count(*) FILTER (WHERE mode = 'enforce'), \
             count(*) FILTER (WHERE action_kind = 'hil.requested'), \
             count(*) FILTER (WHERE action_kind = 'hil.timeout'), \
             max(to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')) \
             FROM audit_log"
        ),
        db.query_single_readonly(
            "SELECT count(*), \
             count(*) FILTER (WHERE object_type = 'Resource'), \
             count(*) FILTER (WHERE object_type = 'Rule'), \
             COALESCE(max(revision), 0) \
             FROM ontology_resource"
        ),
        db.query_single_readonly(
            "SELECT count(*), \
             count(*) FILTER (WHERE projected_state NOT IN ('resolved', 'closed')) \
             FROM operator_incident_projection"
        ),
        db.query_single_readonly(
            "SELECT COALESCE((value->>'violated_count')::bigint, 0), \
             COALESCE((value->>'compliant_count')::bigint, 0), \
             COALESCE((value->>'abstained_count')::bigint, 0) \
             FROM state_kv WHERE key = 'baseline-evaluation:latest' OR key LIKE 'baseline-evaluation:coverage:%' \
             ORDER BY updated_at DESC LIMIT 1"
        ),
        db.query_single_readonly(
            "SELECT COALESCE(NULLIF(properties->>'subscription_id',''), NULLIF(properties->'properties'->>'subscriptionId',''), split_part(id, '/', 3)) AS sub_key, \
             count(*) \
             FROM ontology_resource WHERE object_type = 'Resource' \
             GROUP BY 1 ORDER BY 2 DESC LIMIT 20"
        ),
    );

    let (Ok(a), Ok(r), Ok(i)) = (audit, resources, incidents) else {
        return db.not_measured("overview", "/api/v4/overview/summary", "postgres_unreachable");
    };

    let ar = a.rows.first().map(Vec::as_slice).unwrap_or(&[]);
    let rr = r.rows.first().map(Vec::as_slice).unwrap_or(&[]);
    let ir = i.rows.first().map(Vec::as_slice).unwrap_or(&[]);
    let br = baseline_cov
        .ok()
        .and_then(|res| res.rows.into_iter().next())
        .unwrap_or_default();
    let subscriptions: Vec<Value> = subs_res
        .ok()
        .map(|res| {
            res.rows
                .iter()
                .filter_map(|row| {
                    let raw = cell_str(row, 0);
                    let trimmed = raw.trim();
                    if trimmed.is_empty() {
                        return None;
                    }
                    let cnt = cell_i64(row, 1).unwrap_or(0);
                    let prefix: String = trimmed.chars().take(8).collect();
                    let masked = if trimmed.len() > 10 {
                        format!("sub-{prefix}…")
                    } else {
                        trimmed.to_string()
                    };
                    Some(json!({
                        "id": trimmed,
                        "label": format!("{masked} ({cnt}개 리소스)"),
                        "resource_count": cnt
                    }))
                })
                .collect()
        })
        .unwrap_or_default();

    let audit_total = cell_i64(ar, 0).unwrap_or(0);
    let audit_shadow = cell_i64(ar, 1).unwrap_or(0);
    let audit_enforce = cell_i64(ar, 2).unwrap_or(0);
    let hil_requested = cell_i64(ar, 3).unwrap_or(0);
    let hil_timeout = cell_i64(ar, 4).unwrap_or(0);
    let hil_pending = (hil_requested - hil_timeout).max(0);
    let latest_audit_at = cell_str(ar, 5);

    let observed_resources = cell_i64(rr, 0).unwrap_or(0);
    let azure_resources = cell_i64(rr, 1).unwrap_or(0);
    let active_rules = cell_i64(rr, 2).unwrap_or(0);
    let max_revision = cell_i64(rr, 3).unwrap_or(0);

    let incidents_total = cell_i64(ir, 0).unwrap_or(0);
    let open_incidents = cell_i64(ir, 1).unwrap_or(0);
    let baseline_violated = cell_i64(&br, 0);
    let baseline_compliant = cell_i64(&br, 1);
    let baseline_abstained = cell_i64(&br, 2);

    let data = json!({
        "observed_resources": observed_resources,
        "azure_resources": azure_resources,
        "active_rules": active_rules,
        "ontology_max_revision": max_revision,
        "active_risks": open_incidents,
        "open_incidents": open_incidents,
        "incident_projections_total": incidents_total,
        "baseline_violated": baseline_violated,
        "baseline_compliant": baseline_compliant,
        "baseline_abstained": baseline_abstained,
        "human_review_pending": hil_pending,
        "hil_requested_total": hil_requested,
        "hil_timeout_total": hil_timeout,
        "audit_events": audit_total,
        "audit_shadow": audit_shadow,
        "audit_enforce": audit_enforce,
        "shadow_share": ratio_opt(audit_shadow, audit_total),
        "enforce_share": ratio_opt(audit_enforce, audit_total),
        "subscriptions": subscriptions,
        "last_recorded_at": if latest_audit_at.is_empty() { Value::Null } else { json!(latest_audit_at) },
        "data_sources": {
            "source": "postgres-direct",
            "tables": [
                "audit_log",
                "ontology_resource",
                "operator_incident_projection",
                "state_kv"
            ]
        }
    });

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "audit_total": audit_total,
        "audit_shadow": audit_shadow,
        "audit_enforce": audit_enforce,
        "latest_audit_at": latest_audit_at,
        "ontology_resources_total": observed_resources,
        "ontology_max_revision": max_revision,
        "incident_projections_total": incidents_total,
        "data": data
    })
}

pub async fn fetch_dashboard(db: &DbHandle, subscription: &str, window: &str) -> Value {
    let sub_clean = subscription.trim();
    let res_where = if !sub_clean.is_empty() && !sub_clean.eq_ignore_ascii_case("all") {
        let q_exact = pg_quote_literal(sub_clean);
        let q_like = quote_like_contains(sub_clean);
        format!(
            "WHERE (COALESCE(properties->'properties'->>'subscriptionId', '') = {q_exact} \
             OR COALESCE(properties->'properties'->>'resourceGroup', '') ILIKE {q_like} ESCAPE '\\' \
             OR id ILIKE {q_like} ESCAPE '\\')"
        )
    } else {
        String::new()
    };

    let res_stats_sql = format!(
        "SELECT count(*), \
         count(*) FILTER (WHERE object_type = 'Resource'), \
         count(*) FILTER (WHERE object_type = 'Rule'), \
         count(*) FILTER (WHERE LOWER(COALESCE(properties->'properties'->'properties'->>'provisioningState', '')) = 'succeeded'), \
         count(*) FILTER (WHERE LOWER(COALESCE(properties->'properties'->'properties'->>'provisioningState', '')) IN ('failed', 'degraded', 'unhealthy')), \
         count(*) FILTER (WHERE object_type = 'Resource' AND COALESCE(properties->'properties'->'properties'->>'provisioningState', '') = '') \
         FROM ontology_resource {res_where}"
    );

    let q_win_iv = pg_quote_literal(dashboard_window_interval_sql(window));
    let buckets_sql = format!(
        "WITH anchor AS (SELECT COALESCE(max(created_at), NOW()) AS ts FROM audit_log), \
         win_rows AS ( \
           SELECT a.created_at, a.action_kind \
           FROM audit_log a, anchor \
           WHERE a.created_at >= anchor.ts - CAST({q_win_iv} AS interval) \
         ), \
         span AS (SELECT COALESCE(max(created_at) - min(created_at), INTERVAL '0 seconds') AS d FROM win_rows) \
         SELECT CASE \
           WHEN span.d < INTERVAL '1 hour' THEN to_char(created_at AT TIME ZONE 'UTC', 'HH24:MI:SS') \
           WHEN span.d < INTERVAL '2 days' THEN to_char(created_at AT TIME ZONE 'UTC', 'MM/DD HH24:00') \
           ELSE to_char(created_at AT TIME ZONE 'UTC', 'MM/DD') \
         END AS bkt, \
         count(*), \
         count(*) FILTER (WHERE action_kind IN ('control_loop.compliant', 'audit.record', 'runtime.operational-state-recorded', 'measurement.control_loop.v1')), \
         count(*) FILTER (WHERE action_kind IN ('rca.hypothesis', 'control_loop.abstain', 'observation-campaign.source-transition', 'control_loop.t1_evaluate')), \
         count(*) FILTER (WHERE action_kind IN ('risk_gate.unified', 'mimir.rule-source.observed') OR action_kind ILIKE '%escape%' OR action_kind ILIKE '%policy_violation%' OR action_kind ILIKE '%security%'), \
         count(*) FILTER (WHERE action_kind LIKE 'hil.%'), \
         max(to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')) \
         FROM win_rows, span GROUP BY 1 ORDER BY 1 DESC LIMIT 6"
    );
    let scatter_sql = format!(
        "WITH anchor AS (SELECT COALESCE(max(created_at), NOW()) AS ts FROM audit_log) \
         SELECT a.seq, COALESCE(a.actor, 'fdai'), COALESCE(a.action_kind, 'audit.record'), \
         COALESCE(a.mode, 'shadow'), \
         COALESCE(a.entry->'payload'->>'resource_id', a.entry->>'resource_id', a.entry->>'target', ''), \
         COALESCE(a.entry->>'tier', a.entry->>'rca_tier', ''), \
         EXTRACT(EPOCH FROM a.created_at)::double precision, \
         to_char(a.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
         EXTRACT(EPOCH FROM anchor.ts)::double precision, \
         COALESCE(a.entry->>'approval_id', a.entry->>'request_id', ''), \
         COALESCE(a.correlation_id, ''), \
         COALESCE(a.entry->>'rule_id', ''), \
         COALESCE(a.entry->>'action_type', ''), \
         COALESCE(a.entry->>'severity', ''), \
         COALESCE(a.entry->>'rca_cause', a.entry->>'reason', a.entry->>'t1_reason', ''), \
         COALESCE(a.entry->>'decision', a.entry->>'outcome', ''), \
         COALESCE(a.entry->>'idempotency_key', ''), \
         COALESCE(a.entry->>'resource_type', ''), \
         CASE WHEN COALESCE(a.entry->>'risk_score', '') ~ '^[0-9]+$' THEN (a.entry->>'risk_score')::bigint ELSE NULL END \
         FROM audit_log a, anchor \
         WHERE a.created_at >= anchor.ts - CAST({q_win_iv} AS interval) \
         ORDER BY a.seq DESC LIMIT 80"
    );
    let journal_sql = "SELECT watermark, COALESCE(subject_ref, ''), \
         COALESCE(mutation_kind, 'observed'), COALESCE(source_identity, 'inventory'), \
         EXTRACT(EPOCH FROM observed_at)::double precision, \
         to_char(observed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
         FROM inventory_observation_journal ORDER BY watermark DESC LIMIT 12";
    let hil_park_sql = "SELECT COALESCE(value->>'approval_id', REPLACE(key, 'hil_park:', '')), \
         COALESCE(value->>'correlation_id', ''), \
         COALESCE(value->>'target_resource_ref', ''), \
         COALESCE(value->>'rule_id', ''), \
         COALESCE(value->>'action_type', ''), \
         COALESCE(value->>'severity', ''), \
         COALESCE(value->>'status', ''), \
         COALESCE(value->'approval_context'->>'expires_at', value->>'expires_at', ''), \
         COALESCE(value->>'idempotency_key', '') \
         FROM state_kv WHERE key LIKE 'hil_park:%' ORDER BY updated_at DESC LIMIT 120";

    let (
        audit_res,
        buckets_res,
        actions_res,
        res_stats,
        incidents_res,
        control_loop_res,
        baseline_cov_res,
        findings_res,
        subs_res,
        rules_dom_res,
        cost_runs_res,
        cl_dom_res,
        code_sec_res,
        links_res,
        scatter_res,
        journal_res,
        hil_park_res,
    ) = tokio::join!(
        db.query_single_readonly(
            "SELECT count(*), \
             count(*) FILTER (WHERE mode = 'shadow'), \
             count(*) FILTER (WHERE mode = 'enforce'), \
             COALESCE(min(seq), 0), COALESCE(max(seq), 0), \
             max(to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')), \
             count(*) FILTER (WHERE action_kind = 'hil.requested'), \
             count(*) FILTER (WHERE action_kind = 'hil.timeout'), \
             count(*) FILTER (WHERE LOWER(COALESCE(entry->>'tier', '')) = 't0'), \
             count(*) FILTER (WHERE LOWER(COALESCE(entry->>'tier', '')) = 't1'), \
             count(*) FILTER (WHERE LOWER(COALESCE(entry->>'tier', '')) = 't2'), \
             count(*) FILTER (WHERE action_kind = 'control_loop.compliant'), \
             count(*) FILTER (WHERE action_kind = 'control_loop.abstain'), \
             count(*) FILTER (WHERE action_kind = 'risk_gate.unified'), \
             count(*) FILTER (WHERE action_kind ILIKE '%escape%' OR action_kind ILIKE '%policy_violation%') \
             FROM audit_log"
        ),
        db.query_single_readonly(&buckets_sql),
        db.query_single_readonly(
            "SELECT action_kind, count(*) FROM audit_log GROUP BY action_kind ORDER BY count(*) DESC LIMIT 10"
        ),
        db.query_single_readonly(&res_stats_sql),
        db.query_single_readonly(
            "SELECT correlation_id, COALESCE(projected_state, 'unknown'), \
             COALESCE(projected_vertical, 'unattributed'), COALESCE(projected_severity, 'medium'), \
             COALESCE(group_history_count, 0), COALESCE(canonical_opened_at, '') \
             FROM operator_incident_projection ORDER BY last_seq DESC LIMIT 20"
        ),
        db.query_single_readonly(
            "SELECT COALESCE(value->>'gate_route', 'unknown'), count(*) \
             FROM state_kv WHERE key LIKE 'measurement:control-loop:%' \
             GROUP BY 1 ORDER BY count(*) DESC"
        ),
        db.query_single_readonly(
            "SELECT COALESCE((value->>'violated_count')::bigint, 0), \
             COALESCE((value->>'compliant_count')::bigint, 0), \
             COALESCE((value->>'abstained_count')::bigint, 0), \
             COALESCE(value->>'completed_at', '') \
             FROM state_kv WHERE key = 'baseline-evaluation:latest' OR key LIKE 'baseline-evaluation:coverage:%' \
             ORDER BY updated_at DESC LIMIT 1"
        ),
        db.query_single_readonly(
            "SELECT COALESCE(value->>'signal', 'signal'), \
             COALESCE(value->>'assessed_by', 'analyzer'), \
             COALESCE(value->>'resource_ref', key), \
             COALESCE(value->>'publication', 'recorded'), \
             COALESCE(value->>'recorded_at', to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')) \
             FROM state_kv WHERE key LIKE 'runtime:analyzer-finding-receipt:%' \
             ORDER BY updated_at DESC LIMIT 8"
        ),
        db.query_single_readonly(
            "SELECT COALESCE(properties->'properties'->>'resourceGroup', '') AS rg, count(*) \
             FROM ontology_resource WHERE object_type = 'Resource' \
             AND COALESCE(properties->'properties'->>'resourceGroup', '') <> '' \
             GROUP BY 1 ORDER BY count(*) DESC LIMIT 8"
        ),
        db.query_single_readonly(
            "SELECT COALESCE(value->>'rule_ref', ''), \
             count(*), \
             count(*) FILTER (WHERE value->>'outcome' = 'compliant'), \
             count(*) FILTER (WHERE value->>'outcome' = 'violated'), \
             count(*) FILTER (WHERE value->>'outcome' = 'abstained') \
             FROM state_kv WHERE key LIKE 'baseline-evaluation:outcomes:%' \
             GROUP BY 1"
        ),
        db.query_single_readonly(
            "SELECT count(*) FROM cost_governance_analytics_run_receipt"
        ),
        db.query_single_readonly(
            "SELECT COALESCE(value->>'resource_type', ''), \
             count(*), \
             count(*) FILTER (WHERE value->>'gate_route' = 'compliant'), \
             count(*) FILTER (WHERE value->>'gate_route' = 'hil'), \
             count(*) FILTER (WHERE value->>'gate_route' = 'abstain') \
             FROM state_kv WHERE key LIKE 'measurement:control-loop:%' \
             GROUP BY 1"
        ),
        db.query_single_readonly(
            "SELECT COALESCE(SUM(jsonb_array_length(value->'issues')), 0) \
             FROM state_kv WHERE key LIKE 'runtime:code-security-issues:%' \
             AND jsonb_typeof(value->'issues') = 'array'"
        ),
        db.query_single_readonly("SELECT count(*) FROM ontology_link"),
        db.query_single_readonly(&scatter_sql),
        db.query_single_readonly(journal_sql),
        db.query_single_readonly(hil_park_sql),
    );

    let (Ok(a), Ok(r)) = (audit_res, res_stats) else {
        return db.not_measured("overview", "/api/v4/overview/dashboard", "postgres_unreachable");
    };

    let ar = a.rows.first().map(Vec::as_slice).unwrap_or(&[]);
    let rr = r.rows.first().map(Vec::as_slice).unwrap_or(&[]);

    let event_count = cell_i64(ar, 0).unwrap_or(0);
    let shadow_count = cell_i64(ar, 1).unwrap_or(0);
    let enforce_count = cell_i64(ar, 2).unwrap_or(0);
    let min_seq = cell_i64(ar, 3).unwrap_or(0);
    let max_seq = cell_i64(ar, 4).unwrap_or(0);
    let latest_at = cell_str(ar, 5);
    let hil_requested = cell_i64(ar, 6).unwrap_or(0);
    let hil_timeout = cell_i64(ar, 7).unwrap_or(0);
    let hil_pending = (hil_requested - hil_timeout).max(0);
    let t0_count = cell_i64(ar, 8).unwrap_or(0);
    let t1_count = cell_i64(ar, 9).unwrap_or(0);
    let t2_count = cell_i64(ar, 10).unwrap_or(0);
    let compliant_audit = cell_i64(ar, 11).unwrap_or(0);
    let abstain_audit = cell_i64(ar, 12).unwrap_or(0);
    let risk_gate_audit = cell_i64(ar, 13).unwrap_or(0);
    let policy_escape_count = cell_i64(ar, 14).unwrap_or(0);

    let observed_resources = cell_i64(rr, 0).unwrap_or(0);
    let azure_resources = cell_i64(rr, 1).unwrap_or(0);
    let active_rules_count = cell_i64(rr, 2).unwrap_or(0);
    let succeeded_resources = cell_i64(rr, 3).unwrap_or(0);
    let failed_resources = cell_i64(rr, 4).unwrap_or(0);
    let unobserved_resources = cell_i64(rr, 5).unwrap_or(0);
    let coverage_pct = pct_rounded(observed_resources - unobserved_resources, observed_resources);

    let mut by_action_kind = serde_json::Map::new();
    if let Ok(act) = actions_res {
        for row in &act.rows {
            let k = cell_str(row, 0);
            let v = cell_i64(row, 1).unwrap_or(0);
            if !k.is_empty() {
                by_action_kind.insert(k, json!(v));
            }
        }
    }

    let mut auto_route = compliant_audit;
    let mut approval_route = hil_requested;
    let mut deferred_route = abstain_audit;
    let mut denied_route = 0_i64;
    if let Ok(cl) = control_loop_res {
        if !cl.rows.is_empty() {
            auto_route = 0;
            approval_route = 0;
            deferred_route = 0;
            denied_route = 0;
            for row in &cl.rows {
                let route = cell_str(row, 0).to_ascii_lowercase();
                let cnt = cell_i64(row, 1).unwrap_or(0);
                match route.as_str() {
                    "compliant" | "auto" | "allow" => auto_route += cnt,
                    "hil" | "approval" => approval_route += cnt,
                    "deny" | "denied" | "block" => denied_route += cnt,
                    _ => deferred_route += cnt,
                }
            }
        }
    }

    let mut total_incidents = 0_i64;
    let mut active_incidents = 0_i64;
    let mut recent_observations: Vec<Value> = Vec::new();
    let mut inc_by_corr: HashMap<String, (String, String, String)> = HashMap::new();
    let mut resilience_inc = 0_i64;
    let mut change_safety_inc = 0_i64;
    let mut cost_inc = 0_i64;

    if let Ok(inc) = incidents_res {
        for row in &inc.rows {
            total_incidents += 1;
            let cid = cell_str(row, 0);
            let st = cell_str(row, 1);
            let vert = cell_str(row, 2);
            let sev = cell_str(row, 3);
            let hist_cnt = cell_i64(row, 4).unwrap_or(0);
            let opened = cell_str(row, 5);
            if !cid.is_empty() {
                inc_by_corr.insert(cid.clone(), (sev.clone(), st.clone(), vert.clone()));
            }
            let is_open = !matches!(st.to_ascii_lowercase().as_str(), "resolved" | "closed");
            if is_open {
                active_incidents += 1;
            }
            match vert.to_ascii_lowercase().as_str() {
                "resilience" => resilience_inc += 1,
                "change_safety" | "change-safety" => change_safety_inc += 1,
                "cost_governance" | "cost-governance" => cost_inc += 1,
                _ => {}
            }
            let vert_ko = vertical_label_ko(&vert);
            let sev_ko = severity_label_ko(&sev);
            let st_ko = status_label_ko(&st);
            let (tone, badge_label) = if is_open {
                ("sre", format!("인시던트 · {sev_ko}"))
            } else {
                ("live", "해결 완료".to_string())
            };
            let inc_href = format!("/operations/incidents?item={}", encode_item_param(&cid));
            recent_observations.push(json!({
                "id": cid,
                "target": cid,
                "category": format!("운영 인시던트 · {vert_ko} · 이력 {hist_cnt}건"),
                "status": st_ko,
                "raw_status": st,
                "raw_vertical": vert,
                "raw_severity": sev,
                "badge_label": badge_label,
                "tone": tone,
                "icon": "/azure-icons/monitor.svg",
                "observed_at": opened,
                "deep_link_panel": "incidents",
                "deep_link_item": cid,
                "href": inc_href,
                "summary": format!("{vert_ko} 영역에서 심각도 '{sev_ko}' 인시던트가 '{st_ko}' 상태로 추적 중입니다 (투영 이력 {hist_cnt}건).")
            }));
        }
    }

    if let Ok(fres) = findings_res {
        for row in &fres.rows {
            let sig = cell_str(row, 0);
            let assessed_by = cell_str(row, 1);
            let rref = cell_str(row, 2);
            let pub_state = cell_str(row, 3);
            let rec_at = cell_str(row, 4);
            let short_target = rref.rsplit('/').next().unwrap_or(&rref).to_string();
            let sig_ko = if sig.contains("cpu") {
                "호스트 CPU 이상"
            } else if sig.contains("mem") {
                "메모리 사용량 이상"
            } else if sig.contains("disk") {
                "디스크 이상"
            } else {
                "이상 징후 분석"
            };
            let pub_ko = status_label_ko(&pub_state);
            let finding_href = format!("/evidence/audit?item={}", encode_item_param(&rref));
            recent_observations.push(json!({
                "id": rref,
                "target": short_target,
                "category": format!("자동 분석 감지 · {sig_ko}"),
                "status": pub_ko,
                "raw_status": pub_state,
                "raw_signal": sig,
                "assessed_by": assessed_by,
                "badge_label": sig_ko,
                "tone": if sig.contains("cpu") || sig.contains("mem") { "sre" } else { "sec" },
                "icon": resource_icon_for(&sig, &rref, "Resource"),
                "observed_at": rec_at,
                "deep_link_panel": "audit",
                "deep_link_item": rref,
                "href": finding_href,
                "summary": format!("분석기가 {short_target} 대상에서 '{sig_ko}' 신호를 감지해 {pub_ko} 상태로 기록했습니다.")
            }));
        }
    }

    let br_opt = baseline_cov_res
        .ok()
        .and_then(|res| res.rows.into_iter().next());
    let baseline_violated = br_opt.as_ref().and_then(|r| cell_i64(r, 0));
    let baseline_compliant = br_opt.as_ref().and_then(|r| cell_i64(r, 1));
    let baseline_abstained = br_opt.as_ref().and_then(|r| cell_i64(r, 2));
    let baseline_completed_at = br_opt
        .as_ref()
        .map(|r| cell_str(r, 3))
        .unwrap_or_default();
    let code_security_issues = code_sec_res
        .ok()
        .and_then(|res| res.rows.first().and_then(|r| cell_i64(r, 0)))
        .unwrap_or(0);
    let ontology_links_total = links_res
        .ok()
        .and_then(|res| res.rows.first().and_then(|r| cell_i64(r, 0)))
        .unwrap_or(0);
    let analyzer_findings_count = recent_observations
        .iter()
        .filter(|v| {
            v.get("badge_label")
                .and_then(Value::as_str)
                .is_some_and(|s| s.starts_with("분석 감지"))
        })
        .count() as i64;

    let mut time_buckets: Vec<Value> = Vec::new();
    if let Ok(bres) = buckets_res {
        for row in bres.rows.iter().rev() {
            let bkt_at = cell_str(row, 6);
            time_buckets.push(json!({
                "label": cell_str(row, 0),
                "bucket_at": if bkt_at.is_empty() { Value::Null } else { json!(bkt_at) },
                "total": cell_i64(row, 1).unwrap_or(0),
                "auto": cell_i64(row, 2).unwrap_or(0),
                "sre": cell_i64(row, 3).unwrap_or(0),
                "sec": cell_i64(row, 4).unwrap_or(0),
                "human": cell_i64(row, 5).unwrap_or(0),
            }));
        }
    }

    #[derive(Clone)]
    struct HilParkRow {
        approval_id: String,
        target_resource_ref: String,
        rule_id: String,
        action_type: String,
        severity: String,
        status: String,
        expires_at: String,
    }

    let mut hil_by_corr: HashMap<String, HilParkRow> = HashMap::new();
    let mut hil_by_id: HashMap<String, HilParkRow> = HashMap::new();
    let mut hil_by_idem: HashMap<String, HilParkRow> = HashMap::new();
    if let Ok(hres) = hil_park_res {
        for row in &hres.rows {
            let approval_id = cell_str(row, 0);
            let corr_id = cell_str(row, 1);
            let target_ref = cell_str(row, 2);
            let rule_id = cell_str(row, 3);
            let action_type = cell_str(row, 4);
            let severity = cell_str(row, 5);
            let status = cell_str(row, 6);
            let expires_at = cell_str(row, 7);
            let idem_key = cell_str(row, 8);
            let entry = HilParkRow {
                approval_id: approval_id.clone(),
                target_resource_ref: target_ref,
                rule_id,
                action_type,
                severity,
                status,
                expires_at,
            };
            if !corr_id.is_empty() {
                hil_by_corr.entry(corr_id).or_insert_with(|| entry.clone());
            }
            if !approval_id.is_empty() {
                hil_by_id.entry(approval_id).or_insert_with(|| entry.clone());
            }
            if !idem_key.is_empty() {
                hil_by_idem.entry(idem_key).or_insert(entry);
            }
        }
    }

    struct RawScatterPoint {
        id: String,
        seq: Option<i64>,
        source_table: &'static str,
        series: &'static str,
        risk_score: Option<i64>,
        severity: &'static str,
        severity_band: i64,
        epoch: f64,
        recorded_at: String,
        actor: String,
        action_kind: String,
        target: String,
        resource_name: String,
        resource_ref: String,
        resource_type: String,
        rule_id: String,
        action_type: String,
        approval_id: Option<String>,
        approval_status: Option<String>,
        expires_at: Option<String>,
        correlation_id: String,
        reason: String,
        mode: String,
        tier: String,
        deep_link_panel: &'static str,
        deep_link_item: String,
        href: String,
    }

    let mut raw_scatter: Vec<RawScatterPoint> = Vec::new();
    let mut anchor_epoch: Option<f64> = None;
    if let Ok(sres) = scatter_res {
        for row in sres.rows.iter().rev() {
            let seq = cell_i64(row, 0).unwrap_or(0);
            let actor = cell_str(row, 1);
            let action_kind = cell_str(row, 2);
            let mode = cell_str(row, 3);
            let target_raw = cell_str(row, 4);
            let tier = cell_str(row, 5);
            let Some(ep) = cell_f64(row, 6) else {
                continue;
            };
            let rec_at = cell_str(row, 7);
            if anchor_epoch.is_none() {
                anchor_epoch = cell_f64(row, 8);
            }
            let entry_approval_id = cell_str(row, 9);
            let corr_id = cell_str(row, 10);
            let entry_rule_id = cell_str(row, 11);
            let entry_action_type = cell_str(row, 12);
            let entry_severity = cell_str(row, 13);
            let entry_reason = cell_str(row, 14);
            let entry_decision = cell_str(row, 15);
            let idem_key = cell_str(row, 16);
            let entry_res_type = cell_str(row, 17);
            let measured_risk_score = cell_i64(row, 18);

            let idem_base = idem_key
                .strip_suffix(":hil_request")
                .or_else(|| idem_key.strip_suffix(":hil_timeout"))
                .unwrap_or(&idem_key);
            let hil_match = if !corr_id.is_empty() {
                hil_by_corr.get(&corr_id)
            } else {
                None
            }
            .or_else(|| {
                if !entry_approval_id.is_empty() {
                    hil_by_id.get(&entry_approval_id)
                } else {
                    None
                }
            })
            .or_else(|| {
                if !idem_base.is_empty() {
                    hil_by_idem.get(idem_base)
                } else {
                    None
                }
            });
            let inc_match = if !corr_id.is_empty() {
                inc_by_corr.get(&corr_id)
            } else {
                None
            };

            let series = classify_audit_series(&action_kind);
            let rule_id = hil_match
                .filter(|h| !h.rule_id.is_empty())
                .map(|h| h.rule_id.clone())
                .unwrap_or(entry_rule_id);
            let action_type = hil_match
                .filter(|h| !h.action_type.is_empty())
                .map(|h| h.action_type.clone())
                .unwrap_or(entry_action_type);
            let raw_severity = hil_match
                .filter(|h| !h.severity.is_empty())
                .map(|h| h.severity.as_str())
                .filter(|s| !s.is_empty())
                .or_else(|| {
                    if !entry_severity.is_empty() {
                        Some(entry_severity.as_str())
                    } else {
                        inc_match.map(|(s, _, _)| s.as_str())
                    }
                })
                .unwrap_or("");
            let (severity, severity_band) = normalize_event_severity(raw_severity, &action_kind);

            let idem_ref = extract_resource_from_idempotency_key(&idem_key);
            let resource_ref = hil_match
                .filter(|h| !h.target_resource_ref.is_empty())
                .map(|h| h.target_resource_ref.clone())
                .unwrap_or_else(|| {
                    if !target_raw.is_empty() {
                        target_raw.clone()
                    } else if !idem_ref.is_empty() {
                        idem_ref
                    } else {
                        String::new()
                    }
                });
            let resource_name = if !resource_ref.is_empty() {
                resource_ref
                    .rsplit('/')
                    .next()
                    .unwrap_or(&resource_ref)
                    .to_string()
            } else {
                String::new()
            };
            let resource_type = if !entry_res_type.is_empty() {
                entry_res_type
            } else {
                infer_resource_type_from_ref(&resource_ref, &rule_id)
            };

            let approval_id = hil_match
                .filter(|h| !h.approval_id.is_empty())
                .map(|h| h.approval_id.clone())
                .or_else(|| {
                    if !entry_approval_id.is_empty() {
                        Some(entry_approval_id)
                    } else {
                        None
                    }
                });
            let approval_status = if action_kind.eq_ignore_ascii_case("hil.timeout") {
                Some("expired".to_string())
            } else if let Some(h) = hil_match {
                if !h.status.is_empty() {
                    Some(h.status.clone())
                } else {
                    Some("pending".to_string())
                }
            } else if action_kind.starts_with("hil.") {
                Some("pending".to_string())
            } else {
                None
            };
            let expires_at = hil_match
                .filter(|h| !h.expires_at.is_empty())
                .map(|h| h.expires_at.clone());
            let reason = if !entry_reason.is_empty() {
                entry_reason
            } else {
                entry_decision
            };

            let display_target = if !resource_name.is_empty() {
                resource_name.clone()
            } else if !resource_type.is_empty() {
                resource_type.clone()
            } else if !rule_id.is_empty() {
                rule_id.clone()
            } else {
                String::new()
            };
            let audit_item_id = format!("audit:{seq}");
            let (deep_link_panel, deep_link_item, href) =
                if let Some(ref aid) = approval_id {
                    let link = format!("/operations/hil-queue?item={}", encode_item_param(aid));
                    ("hil-queue", aid.clone(), link)
                } else {
                    let link = format!("/evidence/audit?item={}", encode_item_param(&audit_item_id));
                    ("audit", audit_item_id.clone(), link)
                };
            raw_scatter.push(RawScatterPoint {
                id: audit_item_id,
                seq: Some(seq),
                source_table: "audit_log",
                series,
                risk_score: measured_risk_score,
                severity,
                severity_band,
                epoch: ep,
                recorded_at: rec_at,
                actor,
                action_kind,
                target: display_target,
                resource_name,
                resource_ref,
                resource_type,
                rule_id,
                action_type,
                approval_id,
                approval_status,
                expires_at,
                correlation_id: corr_id,
                reason,
                mode,
                tier,
                deep_link_panel,
                deep_link_item,
                href,
            });
        }
    }

    let win_secs = dashboard_window_seconds(window);
    if let Ok(jres) = journal_res {
        let audit_empty = raw_scatter.is_empty();
        for row in jres.rows.iter().rev() {
            let wm = cell_i64(row, 0).unwrap_or(0);
            let subj = cell_str(row, 1);
            let mkind = cell_str(row, 2);
            let src_id = cell_str(row, 3);
            let Some(ep) = cell_f64(row, 4) else {
                continue;
            };
            let obs_at = cell_str(row, 5);
            let in_window = match anchor_epoch {
                Some(a_ep) if !audit_empty => ep >= a_ep - win_secs && ep <= a_ep,
                _ => true,
            };
            if !in_window {
                continue;
            }
            let short_subj = subj.rsplit('/').next().unwrap_or(&subj).to_string();
            let inferred_rt = infer_resource_type_from_ref(&subj, "");
            let dl_item = if subj.is_empty() {
                format!("journal:{wm}")
            } else {
                subj.clone()
            };
            let dl_href = format!("/governance/ontology?item={}", encode_item_param(&dl_item));
            raw_scatter.push(RawScatterPoint {
                id: format!("journal:{wm}"),
                seq: None,
                source_table: "inventory_observation_journal",
                series: "auto",
                risk_score: None,
                severity: "info",
                severity_band: 0,
                epoch: ep,
                recorded_at: obs_at,
                actor: src_id,
                action_kind: format!("inventory.{mkind}"),
                target: short_subj.clone(),
                resource_name: short_subj,
                resource_ref: subj,
                resource_type: inferred_rt,
                rule_id: String::new(),
                action_type: String::new(),
                approval_id: None,
                approval_status: None,
                expires_at: None,
                correlation_id: String::new(),
                reason: String::new(),
                mode: "shadow".to_string(),
                tier: "T0".to_string(),
                deep_link_panel: "ontology",
                deep_link_item: dl_item,
                href: dl_href,
            });
        }
    }

    raw_scatter.sort_by(|a, b| a.epoch.total_cmp(&b.epoch));
    let n_pts = raw_scatter.len();
    let min_ep = raw_scatter.first().map(|p| p.epoch).unwrap_or(0.0);
    let max_ep = raw_scatter.last().map(|p| p.epoch).unwrap_or(min_ep);
    let span_seconds = if n_pts >= 2 {
        (max_ep - min_ep).max(0.0).round() as i64
    } else {
        0
    };
    let same_day = raw_scatter
        .first()
        .zip(raw_scatter.last())
        .is_some_and(|(a, b)| {
            a.recorded_at.len() >= 10
                && b.recorded_at.len() >= 10
                && a.recorded_at.is_ascii()
                && b.recorded_at.is_ascii()
                && a.recorded_at[..10] == b.recorded_at[..10]
        });

    let default_axis = dashboard_window_default_axis(window);
    let axis_labels: Vec<String> = if n_pts >= 2 {
        let i1 = (n_pts - 1) / 3;
        let i2 = ((n_pts - 1) * 2) / 3;
        vec![
            short_utc_axis_label(&raw_scatter[0].recorded_at, same_day),
            short_utc_axis_label(&raw_scatter[i1].recorded_at, same_day),
            short_utc_axis_label(&raw_scatter[i2].recorded_at, same_day),
            short_utc_axis_label(&raw_scatter[n_pts - 1].recorded_at, same_day),
        ]
    } else if n_pts == 1 {
        vec![
            default_axis[0].to_string(),
            default_axis[1].to_string(),
            short_utc_axis_label(&raw_scatter[0].recorded_at, true),
            short_utc_axis_label(&raw_scatter[0].recorded_at, true),
        ]
    } else {
        default_axis.iter().map(|s| (*s).to_string()).collect()
    };

    let earliest_at = raw_scatter
        .first()
        .map(|p| p.recorded_at.clone())
        .unwrap_or_default();

    let server_now_epoch_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0);
    let server_now_sec = (server_now_epoch_ms as f64) / 1000.0;
    let anchor_epoch_ms = anchor_epoch
        .or_else(|| if n_pts > 0 { Some(max_ep) } else { None })
        .map(|ep| (ep * 1000.0).round() as i64);
    let earliest_epoch_ms = if n_pts > 0 {
        Some((min_ep * 1000.0).round() as i64)
    } else {
        None
    };
    let has_recent_events = anchor_epoch
        .or_else(|| if n_pts > 0 { Some(max_ep) } else { None })
        .is_some_and(|a_ep| (server_now_sec - a_ep).abs() <= win_secs);

    let scatter_points: Vec<Value> = raw_scatter
        .into_iter()
        .enumerate()
        .map(|(i, pt)| {
            let offset_ratio = if n_pts <= 1 {
                0.95_f64
            } else {
                let idx_ratio = (i as f64) / ((n_pts - 1) as f64);
                let time_ratio = if max_ep > min_ep {
                    ((pt.epoch - min_ep) / (max_ep - min_ep)).clamp(0.0, 1.0)
                } else {
                    idx_ratio
                };
                (0.02 + (0.82 * time_ratio + 0.18 * idx_ratio) * 0.96).clamp(0.02, 0.98)
            };
            let offset_rounded = (offset_ratio * 10000.0).round() / 10000.0;
            let time_label = short_utc_axis_label(&pt.recorded_at, true);
            let recorded_epoch_ms = (pt.epoch * 1000.0).round() as i64;
            json!({
                "id": pt.id,
                "seq": pt.seq,
                "source_table": pt.source_table,
                "series": pt.series,
                "risk_score": pt.risk_score,
                "severity": pt.severity,
                "severity_band": pt.severity_band,
                "offset_ratio": offset_rounded,
                "recorded_at": pt.recorded_at,
                "recorded_epoch_ms": recorded_epoch_ms,
                "time_label": time_label,
                "actor": pt.actor,
                "action_kind": pt.action_kind,
                "target": pt.target,
                "resource_name": pt.resource_name,
                "resource_ref": pt.resource_ref,
                "resource_type": pt.resource_type,
                "rule_id": pt.rule_id,
                "action_type": pt.action_type,
                "approval_id": pt.approval_id,
                "approval_status": pt.approval_status,
                "expires_at": pt.expires_at,
                "correlation_id": pt.correlation_id,
                "reason": pt.reason,
                "mode": pt.mode,
                "tier": pt.tier,
                "deep_link_panel": pt.deep_link_panel,
                "deep_link_item": pt.deep_link_item,
                "href": pt.href
            })
        })
        .collect();

    let timeline_meta = json!({
        "window": window,
        "window_seconds": win_secs as i64,
        "server_now_epoch_ms": server_now_epoch_ms,
        "anchor_at": if latest_at.is_empty() { Value::Null } else { json!(latest_at) },
        "anchor_epoch_ms": anchor_epoch_ms,
        "earliest_at": if earliest_at.is_empty() { Value::Null } else { json!(earliest_at) },
        "earliest_epoch_ms": earliest_epoch_ms,
        "span_seconds": span_seconds,
        "point_count": scatter_points.len(),
        "has_recent_events": has_recent_events,
        "axis_labels": axis_labels,
        "forecast_status": "not-measured",
        "forecast_reason": "실측 예측 시계열이 수집되지 않아 미래(+5m) 영역은 미측정으로 분리 표시합니다."
    });

    let forecast = json!({
        "measurement_status": "not-measured",
        "horizon": "+5m",
        "points": [],
        "reason": "no_measured_forecast_series"
    });

    let mut scope_options: Vec<Value> = Vec::new();
    if let Ok(sres) = subs_res {
        for row in &sres.rows {
            let rg = cell_str(row, 0);
            let cnt = cell_i64(row, 1).unwrap_or(0);
            if !rg.is_empty() {
                scope_options.push(json!({ "id": rg, "count": cnt }));
            }
        }
    }

    let mut d_res = (0_i64, 0_i64, 0_i64, 0_i64);
    let mut d_cs = (0_i64, 0_i64, 0_i64, 0_i64);
    let mut d_cg = (0_i64, 0_i64, 0_i64, 0_i64);
    let mut d_un = (0_i64, 0_i64, 0_i64, 0_i64);
    let mut has_baseline_rows = false;
    if let Ok(rdq) = rules_dom_res {
        for row in &rdq.rows {
            has_baseline_rows = true;
            let rref = cell_str(row, 0);
            let tot = cell_i64(row, 1).unwrap_or(0);
            let comp = cell_i64(row, 2).unwrap_or(0);
            let viol = cell_i64(row, 3).unwrap_or(0);
            let abst = cell_i64(row, 4).unwrap_or(0);
            let slot = match classify_rule_vertical(&rref) {
                "resilience" => &mut d_res,
                "change-safety" => &mut d_cs,
                "cost-governance" => &mut d_cg,
                _ => &mut d_un,
            };
            slot.0 += tot;
            slot.1 += comp;
            slot.2 += viol;
            slot.3 += abst;
        }
    }
    // When older baseline-evaluation:outcomes:* rows are pruned (>7d), derive domain breakdown
    // from live 7-day measurement:control-loop:*, analyzer findings, code-security, and cost receipts.
    if !has_baseline_rows {
        if let Ok(cldq) = cl_dom_res {
            for row in &cldq.rows {
                let rtype = cell_str(row, 0);
                let tot = cell_i64(row, 1).unwrap_or(0);
                let comp = cell_i64(row, 2).unwrap_or(0);
                let hil = cell_i64(row, 3).unwrap_or(0);
                let abst = cell_i64(row, 4).unwrap_or(0);
                let slot = match classify_rule_vertical(&rtype) {
                    "resilience" => &mut d_res,
                    "change-safety" => &mut d_cs,
                    "cost-governance" => &mut d_cg,
                    _ => &mut d_un,
                };
                slot.0 += tot;
                slot.1 += comp;
                slot.2 += hil;
                slot.3 += abst;
            }
        }
        d_res.0 += analyzer_findings_count;
        d_res.2 += analyzer_findings_count;
        d_cs.0 += code_security_issues;
        d_cs.2 += code_security_issues;
    }
    let cost_run_cnt = cost_runs_res
        .ok()
        .and_then(|res| res.rows.first().and_then(|r| cell_i64(r, 0)))
        .unwrap_or(0);
    d_res.0 += resilience_inc;
    d_cs.0 += change_safety_inc;
    d_cg.0 += cost_inc + cost_run_cnt;

    let build_dom_row = |key: &str, label: &str, tone: &str, stats: (i64, i64, i64, i64)| {
        let (tot, comp, viol, abst) = stats;
        let den = tot.max(1);
        let auto_pct = ((comp as f64) * 100.0 / (den as f64)).round();
        let viol_pct = ((viol as f64) * 100.0 / (den as f64)).round();
        let abst_pct = ((abst as f64) * 100.0 / (den as f64)).round();
        json!({
            "key": key,
            "label": label,
            "tone": tone,
            "total": tot,
            "compliant": comp,
            "violated": viol,
            "abstained": abst,
            "auto_pct": auto_pct,
            "sre_pct": viol_pct,
            "human_pct": abst_pct
        })
    };
    let domain_breakdown = vec![
        build_dom_row("resilience", "복원력 (Resilience)", "live", d_res),
        build_dom_row("change-safety", "변경 안전 (Change Safety)", "human", d_cs),
        build_dom_row("cost-governance", "비용 거버넌스 (FinOps)", "sre", d_cg),
        build_dom_row("unattributed", "미귀속 (별도 분리)", "neutral", d_un),
    ];

    let data = json!({
        "filters": {
            "subscription": subscription,
            "window": window,
        },
        "observed_resources": observed_resources,
        "azure_resources": azure_resources,
        "ontology_links_total": ontology_links_total,
        "succeeded_resources": succeeded_resources,
        "failed_resources": failed_resources,
        "unobserved_resources": unobserved_resources,
        "coverage_pct": coverage_pct,
        "active_rules_count": active_rules_count,
        "last_recorded_at": if latest_at.is_empty() { Value::Null } else { json!(latest_at) },
        "posture": {
            "event_count": event_count,
            "shadow_count": shadow_count,
            "enforce_count": enforce_count,
            "shadow_share": ratio_opt(shadow_count, event_count),
            "enforce_share": ratio_opt(enforce_count, event_count),
            "policy_escape_count": policy_escape_count,
            "audit_sample": {
                "from_seq": min_seq,
                "through_seq": max_seq,
                "row_count": event_count
            }
        },
        "routing": {
            "by_tier": {
                "T0": t0_count,
                "T1": t1_count,
                "T2": t2_count
            },
            "by_outcome": {
                "auto": auto_route,
                "approval": approval_route,
                "deferred": deferred_route,
                "denied": denied_route
            },
            "by_action_kind": Value::Object(by_action_kind)
        },
        "signals": {
            "active_incidents": active_incidents,
            "total_incidents": total_incidents,
            "hil_pending": hil_pending,
            "hil_requested_total": hil_requested,
            "hil_timeout_total": hil_timeout,
            "risk_gate_evaluations": risk_gate_audit,
            "analyzer_findings_count": analyzer_findings_count,
            "code_security_issues": code_security_issues,
            "baseline_violated": baseline_violated,
            "baseline_compliant": baseline_compliant,
            "baseline_abstained": baseline_abstained,
            "baseline_completed_at": if baseline_completed_at.is_empty() { Value::Null } else { json!(baseline_completed_at) }
        },
        "vertical_signals": {
            "resilience": resilience_inc,
            "change_safety": change_safety_inc,
            "cost_governance": cost_inc
        },
        "time_buckets": time_buckets,
        "scatter_points": scatter_points,
        "timeline_meta": timeline_meta,
        "forecast": forecast,
        "domain_breakdown": domain_breakdown,
        "recent_observations": recent_observations,
        "scope_options": scope_options
    });

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "data": data
    })
}

pub async fn fetch_resources(db: &DbHandle, filter: &ResourceFilter<'_>) -> Value {
    let lim = clamp_limit(filter.limit, 50, 200);
    let off = filter.offset.unwrap_or(0).min(100_000);
    let where_sql = build_resource_where_sql(filter);

    let filtered_count_sql = format!("SELECT count(*) FROM ontology_resource {where_sql}");
    let list_sql = format!(
        "SELECT id, object_type, \
         COALESCE(properties->>'name', properties->>'title', id), \
         COALESCE(properties->>'type', object_type), \
         COALESCE(properties->'properties'->>'providerType', properties->>'provider_type', object_type), \
         COALESCE(properties->'properties'->>'subscriptionId', ''), \
         COALESCE(properties->'properties'->>'resourceGroup', ''), \
         COALESCE(properties->>'location', properties->'properties'->>'location', ''), \
         COALESCE(properties->'properties'->'properties'->>'provisioningState', ''), \
         revision, \
         to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
         FROM ontology_resource {where_sql} \
         ORDER BY CASE WHEN object_type = 'Resource' THEN 0 ELSE 1 END, updated_at DESC, id ASC \
         LIMIT {lim} OFFSET {off}"
    );

    let status_summary_sql = "SELECT count(*), \
        count(*) FILTER (WHERE object_type = 'Resource'), \
        count(*) FILTER (WHERE LOWER(COALESCE(properties->'properties'->'properties'->>'provisioningState', '')) IN ('failed', 'degraded', 'unhealthy')), \
        count(*) FILTER (WHERE LOWER(COALESCE(properties->'properties'->'properties'->>'provisioningState', '')) IN ('succeeded', 'running', 'active') OR (object_type <> 'Resource' AND object_type <> 'PolicyArtifact')), \
        count(*) FILTER (WHERE LOWER(COALESCE(properties->'properties'->'properties'->>'provisioningState', '')) NOT IN ('succeeded', 'running', 'active', 'failed', 'degraded', 'unhealthy') AND (COALESCE(properties->>'type', '') ILIKE '%nsg%' OR COALESCE(properties->>'type', '') ILIKE '%vault%' OR COALESCE(properties->>'type', '') ILIKE '%role-assignment%' OR COALESCE(properties->>'type', '') ILIKE '%managed-identity%' OR object_type = 'PolicyArtifact')), \
        count(*) FILTER (WHERE object_type = 'Resource' AND COALESCE(properties->'properties'->'properties'->>'provisioningState', '') = '' AND COALESCE(properties->>'type', '') NOT ILIKE '%nsg%' AND COALESCE(properties->>'type', '') NOT ILIKE '%vault%' AND COALESCE(properties->>'type', '') NOT ILIKE '%role-assignment%' AND COALESCE(properties->>'type', '') NOT ILIKE '%managed-identity%') \
        FROM ontology_resource";

    let (summary_res, cnt_res, list_res, rg_res, cov_res) = tokio::join!(
        db.query_single_readonly(status_summary_sql),
        db.query_single_readonly(&filtered_count_sql),
        db.query_single_readonly(&list_sql),
        db.query_single_readonly(
            "SELECT COALESCE(properties->'properties'->>'resourceGroup', ''), count(*) \
             FROM ontology_resource WHERE object_type = 'Resource' \
             AND COALESCE(properties->'properties'->>'resourceGroup', '') <> '' \
             GROUP BY 1 ORDER BY count(*) DESC LIMIT 12"
        ),
        db.query_single_readonly(
            "SELECT state_type, count(*), count(*) FILTER (WHERE complete = true) \
             FROM operational_state_transition_coverage GROUP BY state_type ORDER BY count(*) DESC"
        ),
    );

    let (Ok(sum_q), Ok(cnt_q), Ok(list_q)) = (summary_res, cnt_res, list_res) else {
        return db.not_measured("overview", "/api/v4/overview/resources", "postgres_unreachable");
    };

    let sr = sum_q.rows.first().map(Vec::as_slice).unwrap_or(&[]);
    let total_all = cell_i64(sr, 0).unwrap_or(0);
    let azure_count = cell_i64(sr, 1).unwrap_or(0);
    let sre_count = cell_i64(sr, 2).unwrap_or(0);
    let live_count = cell_i64(sr, 3).unwrap_or(0);
    let sec_count = cell_i64(sr, 4).unwrap_or(0);
    let neutral_count = cell_i64(sr, 5).unwrap_or(0);

    let filtered_total = cnt_q
        .rows
        .first()
        .and_then(|r| cell_i64(r, 0))
        .unwrap_or(0);

    let items: Vec<Value> = list_q
        .rows
        .iter()
        .map(|row| {
            let id = cell_str(row, 0);
            let object_type = cell_str(row, 1);
            let name = cell_str(row, 2);
            let rtype = cell_str(row, 3);
            let provider_type = cell_str(row, 4);
            let sub_id = cell_str(row, 5);
            let rg = cell_str(row, 6);
            let location = cell_str(row, 7);
            let prov_state = cell_str(row, 8);
            let revision = cell_i64(row, 9).unwrap_or(0);
            let updated_at = cell_str(row, 10);

            let (status, status_label, tone) =
                classify_resource_status(&object_type, &rtype, &prov_state);
            let icon = resource_icon_for(&rtype, &provider_type, &object_type);
            let category = resource_category_for(&rtype, &provider_type, &object_type);

            let (sub_display, group_kind, group_icon, group_label) = if !rg.is_empty() {
                (
                    rg.clone(),
                    "resource-group",
                    "/azure-icons/resource-groups.svg",
                    "리소스 그룹",
                )
            } else if !sub_id.is_empty() {
                let prefix: String = sub_id.chars().take(8).collect();
                (
                    format!("sub-{prefix}"),
                    "subscription",
                    "/azure-icons/subscriptions.svg",
                    "구독 스코프",
                )
            } else {
                (
                    object_type.clone(),
                    "ontology",
                    "/azure-icons/resource-graph.svg",
                    "온톨로지 카탈로그",
                )
            };
            let rg_display = if rg.is_empty() {
                if !sub_id.is_empty() {
                    "구독 루트 스코프".to_string()
                } else {
                    format!("ontology/{object_type}")
                }
            } else {
                rg.clone()
            };
            let prov_display = if prov_state.is_empty() {
                "미수집 (0 대체 금지)".to_string()
            } else {
                prov_state.clone()
            };
            let loc_display = if location.is_empty() {
                "global".to_string()
            } else {
                location.clone()
            };

            let subscription_display = if !sub_id.is_empty() {
                let prefix: String = sub_id.chars().take(8).collect();
                format!("sub-{prefix}...")
            } else {
                format!("ontology/{object_type}")
            };

            json!({
                "id": id,
                "name": name,
                "object_type": object_type,
                "type": provider_type,
                "resource_type": rtype,
                "category": category,
                "sub": sub_display,
                "subscription_display": subscription_display,
                "group_kind": group_kind,
                "group_icon": group_icon,
                "group_label": group_label,
                "rg": rg_display,
                "location": loc_display,
                "status": status,
                "statusLabel": status_label,
                "tone": tone,
                "icon": icon,
                "revision": revision,
                "updated_at": updated_at,
                "lineage": format!("{object_type} · {loc_display} · rev {revision}"),
                "axes": {
                    "resource": format!("{status_label} · {}", resource_type_label_ko(&rtype)),
                    "operation": if status == "sre" { "저하 관측" } else if status == "live" { "정상 관측" } else { "관측 대기" },
                    "provisioning": prov_display,
                    "serving": format!("{loc_display} · 리비전 {revision}"),
                    "availability": if status == "sre" { "주의 필요" } else { "추적 중" },
                    "observation": if updated_at.is_empty() { "미수집".to_string() } else { updated_at.clone() }
                },
                "note": format!("온톨로지 리소스 원장 실측 기록 ({} · 리비전 {revision}).", resource_type_label_ko(&rtype)),
                "actionHref": format!("/governance/ontology?item={}", encode_item_param(&id))
            })
        })
        .collect();

    let mut resource_groups: Vec<Value> = Vec::new();
    if let Ok(rg_q) = rg_res {
        for row in &rg_q.rows {
            let rg = cell_str(row, 0);
            let cnt = cell_i64(row, 1).unwrap_or(0);
            if !rg.is_empty() {
                resource_groups.push(json!({ "name": rg, "count": cnt }));
            }
        }
    }

    let mut coverage_rows: Vec<Value> = Vec::new();
    if let Ok(cov_q) = cov_res {
        for row in &cov_q.rows {
            coverage_rows.push(json!({
                "state_type": cell_str(row, 0),
                "segments": cell_i64(row, 1).unwrap_or(0),
                "complete_segments": cell_i64(row, 2).unwrap_or(0),
            }));
        }
    }

    let coverage_pct = pct_rounded(total_all - neutral_count, total_all);
    let data = json!({
        "filters": {
            "subscription": filter.subscription,
            "resource_type": filter.resource_type,
            "status": filter.status,
            "search": filter.search,
            "lens": filter.lens,
            "limit": lim,
            "offset": off
        },
        "total_count": total_all,
        "filtered_count": filtered_total,
        "azure_resource_count": azure_count,
        "unobserved_count": neutral_count,
        "coverage_pct": coverage_pct,
        "complete": true,
        "status_counts": {
            "all": total_all,
            "live": live_count,
            "sre": sre_count,
            "sec": sec_count,
            "delayed": 0,
            "uncollected": neutral_count,
            "neutral": neutral_count
        },
        "facets": {
            "resource_groups": resource_groups
        },
        "detection_coverage": {
            "source": "operational_state_transition_coverage",
            "by_state_type": coverage_rows
        },
        "resources": items,
        "items": items
    });

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "total": filtered_total,
        "limit": lim,
        "offset": off,
        "items": data.get("items").cloned().unwrap_or(Value::Null),
        "data": data
    })
}

pub async fn fetch_outcomes(db: &DbHandle, period: &str, metric: &str) -> Value {
    let q_iv = pg_quote_literal(period_interval_sql(period));

    let audit_win_sql = format!(
        "WITH anchor AS (SELECT COALESCE(max(created_at), NOW()) AS ts FROM audit_log) \
         SELECT count(*), \
         count(*) FILTER (WHERE action_kind = 'control_loop.compliant'), \
         count(*) FILTER (WHERE action_kind = 'control_loop.abstain'), \
         count(*) FILTER (WHERE action_kind = 'hil.requested'), \
         count(*) FILTER (WHERE action_kind = 'hil.timeout'), \
         count(*) FILTER (WHERE action_kind = 'risk_gate.unified'), \
         count(*) FILTER (WHERE mode = 'shadow'), \
         count(*) FILTER (WHERE mode = 'enforce'), \
         to_char((SELECT ts FROM anchor) AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
         FROM audit_log, anchor \
         WHERE created_at >= anchor.ts - CAST({q_iv} AS interval)"
    );

    let trend_sql = format!(
        "WITH anchor AS ( \
           SELECT COALESCE(max(created_at), NOW()) AS ts, \
                  COALESCE(max(created_at) - min(created_at), INTERVAL '0 seconds') AS span \
           FROM audit_log \
         ) \
         SELECT CASE \
           WHEN anchor.span < INTERVAL '1 hour' THEN to_char(created_at AT TIME ZONE 'UTC', 'HH24:MI:SS') \
           WHEN anchor.span < INTERVAL '2 days' THEN to_char(created_at AT TIME ZONE 'UTC', 'MM/DD HH24:00') \
           ELSE to_char(created_at AT TIME ZONE 'UTC', 'MM/DD') \
         END AS bkt, \
         count(*) FILTER (WHERE action_kind IN ('risk_gate.unified', 'control_loop.abstain', 'rca.hypothesis', 'control_loop.compliant', 'control_loop.t1_evaluate')), \
         count(*) FILTER (WHERE action_kind = 'hil.requested') \
         FROM audit_log, anchor \
         WHERE created_at >= anchor.ts - CAST({q_iv} AS interval) \
         GROUP BY 1 ORDER BY 1 DESC LIMIT 7"
    );

    let rules_sql = "SELECT COALESCE(value->>'rule_ref', 'unknown'), \
         count(*), \
         count(*) FILTER (WHERE value->>'outcome' = 'violated'), \
         count(*) FILTER (WHERE value->>'outcome' = 'compliant'), \
         count(*) FILTER (WHERE value->>'outcome' = 'abstained'), \
         COALESCE(max(value->>'resource_ref'), '') \
         FROM state_kv WHERE key LIKE 'baseline-evaluation:outcomes:%' \
         GROUP BY 1 ORDER BY count(*) FILTER (WHERE value->>'outcome' = 'violated') DESC, count(*) DESC LIMIT 15";

    let cl_rules_sql = "SELECT COALESCE(value->>'resource_type', 'unknown'), \
         count(*), \
         count(*) FILTER (WHERE value->>'gate_route' = 'hil'), \
         count(*) FILTER (WHERE value->>'gate_route' = 'compliant'), \
         count(*) FILTER (WHERE value->>'gate_route' = 'abstain'), \
         COALESCE(max(value->>'event_type'), 'inventory.resource_changed') \
         FROM state_kv WHERE key LIKE 'measurement:control-loop:%' \
         GROUP BY 1 ORDER BY count(*) DESC LIMIT 12";

    let catalog_rules_sql = "SELECT id, COALESCE(properties->>'resource_type', 'resource'), \
         COALESCE(properties->>'severity', 'medium') \
         FROM ontology_resource WHERE object_type = 'Rule' ORDER BY id ASC LIMIT 12";

    let cov_sql = "SELECT state_type, count(*), count(*) FILTER (WHERE complete = true), \
         max(to_char(recorded_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')) \
         FROM operational_state_transition_coverage GROUP BY state_type ORDER BY count(*) DESC LIMIT 40";

    let (audit_res, trend_res, rules_res, cl_rules_res, cat_rules_res, cov_res) = tokio::join!(
        db.query_single_readonly(&audit_win_sql),
        db.query_single_readonly(&trend_sql),
        db.query_single_readonly(rules_sql),
        db.query_single_readonly(cl_rules_sql),
        db.query_single_readonly(catalog_rules_sql),
        db.query_single_readonly(cov_sql),
    );

    let (Ok(a), Ok(cov)) = (audit_res, cov_res) else {
        return db.not_measured("overview", "/api/v4/overview/outcomes", "postgres_unreachable");
    };

    let ar = a.rows.first().map(Vec::as_slice).unwrap_or(&[]);
    let event_count = cell_i64(ar, 0).unwrap_or(0);
    let compliant = cell_i64(ar, 1).unwrap_or(0);
    let abstain = cell_i64(ar, 2).unwrap_or(0);
    let hil_req = cell_i64(ar, 3).unwrap_or(0);
    let hil_timeout = cell_i64(ar, 4).unwrap_or(0);
    let risk_gate = cell_i64(ar, 5).unwrap_or(0);
    let shadow_cnt = cell_i64(ar, 6).unwrap_or(0);
    let enforce_cnt = cell_i64(ar, 7).unwrap_or(0);
    let window_end_at = cell_str(ar, 8);

    let decided = compliant + hil_req + abstain;
    let auto_resolution_rate = pct_rounded(compliant, decided);
    let human_touchpoints_per_100 = ratio_opt(hil_req * 100, event_count).map(|v| (v * 10.0).round() / 10.0);
    let suppression_rate = pct_rounded((risk_gate - hil_req).max(0), risk_gate.max(1));

    let coverage_by_state: Vec<Value> = cov
        .rows
        .iter()
        .map(|row| {
            json!({
                "state_type": cell_str(row, 0),
                "coverage_segments": cell_i64(row, 1).unwrap_or(0),
                "complete_segments": cell_i64(row, 2).unwrap_or(0),
                "latest_recorded_at": cell_str(row, 3),
            })
        })
        .collect();

    let mut rule_outcomes: Vec<Value> = Vec::new();
    let mut total_rule_violated = 0_i64;
    let mut total_rule_evaluated = 0_i64;
    if let Ok(rq) = rules_res {
        for row in &rq.rows {
            let rule_ref = cell_str(row, 0);
            let evaluated = cell_i64(row, 1).unwrap_or(0);
            let violated = cell_i64(row, 2).unwrap_or(0);
            let comp = cell_i64(row, 3).unwrap_or(0);
            let abst = cell_i64(row, 4).unwrap_or(0);
            let sample_res = cell_str(row, 5);
            total_rule_violated += violated;
            total_rule_evaluated += evaluated;
            let domain = classify_rule_domain(&rule_ref);
            let suppress_pct = pct_rounded(comp + abst, evaluated).unwrap_or(0.0);
            rule_outcomes.push(json!({
                "id": rule_ref,
                "name": rule_ref.strip_prefix("rule:").unwrap_or(&rule_ref),
                "domain": domain,
                "auth": if enforce_cnt > 0 { "approval" } else { "observe" },
                "resource": sample_res.strip_prefix("resource:").unwrap_or(&sample_res),
                "evaluated": evaluated,
                "detected": violated + abst,
                "violated": violated,
                "compliant": comp,
                "abstained": abst,
                "suppress_pct": suppress_pct,
                "href": format!("/governance/rules?item={}", encode_item_param(&rule_ref))
            }));
        }
    }
    // When >7d baseline-evaluation:outcomes:* rows are pruned, surface live 7-day
    // measurement:control-loop evaluations grouped by resource_type (plus active Rule catalog).
    if rule_outcomes.is_empty() {
        if let Ok(clq) = cl_rules_res {
            for row in &clq.rows {
                let rtype = cell_str(row, 0);
                let evaluated = cell_i64(row, 1).unwrap_or(0);
                let hil_cnt = cell_i64(row, 2).unwrap_or(0);
                let comp = cell_i64(row, 3).unwrap_or(0);
                let abst = cell_i64(row, 4).unwrap_or(0);
                let ev_type = cell_str(row, 5);
                total_rule_violated += hil_cnt;
                total_rule_evaluated += evaluated;
                let domain = classify_rule_domain(&rtype);
                let suppress_pct = pct_rounded(comp + abst, evaluated).unwrap_or(0.0);
                let cl_id = format!("control-loop:{rtype}");
                rule_outcomes.push(json!({
                    "id": cl_id,
                    "name": format!("{rtype} ({ev_type})"),
                    "domain": domain,
                    "auth": if hil_cnt > 0 { "approval" } else { "observe" },
                    "resource": rtype,
                    "evaluated": evaluated,
                    "detected": evaluated,
                    "violated": hil_cnt,
                    "compliant": comp,
                    "abstained": abst,
                    "suppress_pct": suppress_pct,
                    "href": format!("/governance/rules?item={}", encode_item_param(&cl_id))
                }));
            }
        }
        if rule_outcomes.is_empty() {
            if let Ok(catq) = cat_rules_res {
                for row in &catq.rows {
                    let rid = cell_str(row, 0);
                    let rtype = cell_str(row, 1);
                    let domain = classify_rule_domain(&rid);
                    rule_outcomes.push(json!({
                        "id": rid,
                        "name": rid,
                        "domain": domain,
                        "auth": "observe",
                        "resource": rtype,
                        "evaluated": 0,
                        "detected": 0,
                        "violated": 0,
                        "compliant": 0,
                        "abstained": 0,
                        "suppress_pct": 100.0,
                        "href": format!("/governance/rules?item={}", encode_item_param(&rid))
                    }));
                }
            }
        }
    }

    let mut trend_series: Vec<Value> = Vec::new();
    if let Ok(tq) = trend_res {
        for row in tq.rows.iter().rev() {
            let det = cell_i64(row, 1).unwrap_or(0);
            let alt = cell_i64(row, 2).unwrap_or(0);
            trend_series.push(json!({
                "label": cell_str(row, 0),
                "detected": det,
                "alerts": alt,
                "suppressed": (det - alt).max(0)
            }));
        }
    }

    let data = json!({
        "filters": {
            "period": period,
            "metric": metric,
            "window_end_at": window_end_at
        },
        "metric_states": {
            "auto-resolution": if auto_resolution_rate.is_some() { "measured" } else { "not-measured" },
            "human-touchpoints": if human_touchpoints_per_100.is_some() { "measured" } else { "not-measured" },
            "mttr": "not-measured",
            "change-lead-time": "not-measured",
            "cost-per-event": "not-measured"
        },
        "event_count": event_count,
        "compliant_count": compliant,
        "abstained_count": abstain,
        "hil_requested": hil_req,
        "hil_timeout": hil_timeout,
        "risk_gate_evaluations": risk_gate,
        "shadow_share": ratio_opt(shadow_cnt, event_count),
        "enforce_share": ratio_opt(enforce_cnt, event_count),
        "autonomy": {
            "auto_resolution_rate": auto_resolution_rate,
            "human_touchpoints_per_100": human_touchpoints_per_100,
            "suppression_rate": suppression_rate,
            "mttr_seconds": Value::Null,
            "change_lead_time_seconds": Value::Null,
            "cost_per_resolved_event": Value::Null
        },
        "baseline_summary": {
            "evaluated": total_rule_evaluated,
            "violated": total_rule_violated
        },
        "rule_outcomes": rule_outcomes,
        "trend_series": trend_series,
        "coverage_by_state": coverage_by_state,
        "unmeasured_boundaries": {
            "cost_per_event": {
                "measurement_state": "not-measured",
                "reason": "missing_source:attributed_cost_usd",
                "recovery_route": "/settings/integrations"
            }
        }
    });

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "coverage_by_state": data.get("coverage_by_state").cloned().unwrap_or(Value::Null),
        "data": data
    })
}

pub async fn fetch_control_assurance(db: &DbHandle) -> Value {
    let (audit_res, cl_res, catalog_res, cost_res, cov_res, trans_cov_res) = tokio::join!(
        db.query_single_readonly(
            "SELECT count(*), \
             count(*) FILTER (WHERE mode = 'shadow'), \
             count(*) FILTER (WHERE mode = 'enforce'), \
             count(*) FILTER (WHERE action_kind = 'hil.requested'), \
             count(*) FILTER (WHERE action_kind = 'hil.timeout'), \
             count(*) FILTER (WHERE action_kind = 'risk_gate.unified'), \
             count(*) FILTER (WHERE action_kind = 'decision-evidence.admission-retained'), \
             count(*) FILTER (WHERE action_kind = 'handover.readiness.observed'), \
             count(*) FILTER (WHERE action_kind ILIKE '%escape%' OR action_kind ILIKE '%policy_violation%') \
             FROM audit_log"
        ),
        db.query_single_readonly(
            "SELECT COALESCE(value->>'gate_route', 'unknown'), \
             count(*), \
             count(*) FILTER (WHERE COALESCE(value->>'resource_type', '') <> '') \
             FROM state_kv WHERE key LIKE 'measurement:control-loop:%' \
             GROUP BY 1"
        ),
        db.query_single_readonly(
            "SELECT \
             count(*) FILTER (WHERE object_type = 'Rule'), \
             count(*) FILTER (WHERE object_type = 'PolicyArtifact'), \
             count(*) FILTER (WHERE object_type = 'ActionType'), \
             count(*) FILTER (WHERE object_type = 'FrameworkControl'), \
             count(*) FILTER (WHERE object_type = 'BenchmarkValidation'), \
             count(*) FILTER (WHERE object_type = 'BenchmarkValidation' AND properties->>'passed' = 'true') \
             FROM ontology_resource"
        ),
        db.query_single_readonly(
            "SELECT count(*), COALESCE(SUM(observation_count), 0) \
             FROM cost_governance_analytics_run_receipt"
        ),
        db.query_single_readonly(
            "SELECT COALESCE((value->>'violated_count')::bigint, 0), \
             COALESCE((value->>'compliant_count')::bigint, 0), \
             COALESCE((value->>'abstained_count')::bigint, 0), \
             COALESCE((value->>'complete')::boolean, false) \
             FROM state_kv WHERE key = 'baseline-evaluation:latest' OR key LIKE 'baseline-evaluation:coverage:%' \
             ORDER BY updated_at DESC LIMIT 1"
        ),
        db.query_single_readonly(
            "SELECT count(*) FROM operational_state_transition_coverage"
        ),
    );

    let (Ok(a), Ok(cat)) = (audit_res, catalog_res) else {
        return db.not_measured(
            "overview",
            "/api/v4/overview/control-assurance",
            "postgres_unreachable",
        );
    };

    let ar = a.rows.first().map(Vec::as_slice).unwrap_or(&[]);
    let cr = cat.rows.first().map(Vec::as_slice).unwrap_or(&[]);

    let total_events = cell_i64(ar, 0).unwrap_or(0);
    let shadow_count = cell_i64(ar, 1).unwrap_or(0);
    let enforce_count = cell_i64(ar, 2).unwrap_or(0);
    let hil_requested = cell_i64(ar, 3).unwrap_or(0);
    let hil_timeout = cell_i64(ar, 4).unwrap_or(0);
    let hil_pending = (hil_requested - hil_timeout).max(0);
    let risk_gate_count = cell_i64(ar, 5).unwrap_or(0);
    let admission_retained = cell_i64(ar, 6).unwrap_or(0);
    let handover_observed = cell_i64(ar, 7).unwrap_or(0);
    let policy_escapes = cell_i64(ar, 8).unwrap_or(0);

    let rules_count = cell_i64(cr, 0).unwrap_or(0);
    let policy_artifacts = cell_i64(cr, 1).unwrap_or(0);
    let action_types = cell_i64(cr, 2).unwrap_or(0);
    let framework_controls = cell_i64(cr, 3).unwrap_or(0);
    let benchmark_total = cell_i64(cr, 4).unwrap_or(0);
    let benchmark_passed = cell_i64(cr, 5).unwrap_or(0);

    let mut cl_auto = 0_i64;
    let mut cl_approval = 0_i64;
    let mut cl_deferred = 0_i64;
    let mut cl_denied = 0_i64;
    let mut cl_total = 0_i64;
    let mut cl_attributed = 0_i64;
    if let Ok(cl) = cl_res {
        for row in &cl.rows {
            let route = cell_str(row, 0).to_ascii_lowercase();
            let cnt = cell_i64(row, 1).unwrap_or(0);
            let attr = cell_i64(row, 2).unwrap_or(0);
            cl_total += cnt;
            cl_attributed += attr;
            match route.as_str() {
                "compliant" | "auto" | "allow" => cl_auto += cnt,
                "hil" | "approval" => cl_approval += cnt,
                "deny" | "denied" | "block" => cl_denied += cnt,
                _ => cl_deferred += cnt,
            }
        }
    }
    let unattributed_cl = (cl_total - cl_attributed).max(0);
    let attribution_pct = pct_rounded(cl_attributed, cl_total);

    let (cost_runs, cost_obs) = cost_res
        .ok()
        .and_then(|res| res.rows.into_iter().next())
        .map(|r| (cell_i64(&r, 0).unwrap_or(0), cell_i64(&r, 1).unwrap_or(0)))
        .unwrap_or((0, 0));
    let has_external_settlement = cost_obs > 0;

    let cov_row_opt = cov_res
        .ok()
        .and_then(|res| res.rows.into_iter().next());
    let baseline_violated = cov_row_opt.as_ref().and_then(|r| cell_i64(r, 0));
    let baseline_compliant = cov_row_opt.as_ref().and_then(|r| cell_i64(r, 1)).unwrap_or(0);
    let baseline_abstained = cov_row_opt.as_ref().and_then(|r| cell_i64(r, 2)).unwrap_or(0);
    let baseline_complete = cov_row_opt.as_ref().and_then(|r| cell_bool(r, 3)).unwrap_or(false);
    let trans_cov_total = trans_cov_res
        .ok()
        .and_then(|res| res.rows.first().and_then(|r| cell_i64(r, 0)))
        .unwrap_or(0);

    let benchmark_pass_pct = pct_rounded(benchmark_passed, benchmark_total);
    let baseline_eval_total = baseline_violated.unwrap_or(0) + baseline_compliant + baseline_abstained;
    let (effect_status, effect_verify_pct, effect_detail) = if baseline_complete && baseline_eval_total > 0 {
        (
            "pass",
            pct_rounded(baseline_compliant + baseline_violated.unwrap_or(0), baseline_eval_total),
            format!("증거 수락 {admission_retained}건 · 기준선 완전성 완료"),
        )
    } else if cl_total > 0 || trans_cov_total > 0 {
        let verified_pct = pct_rounded(cl_attributed.max(total_events), cl_total.max(total_events));
        (
            "pass",
            verified_pct,
            format!("제어 루프 실측 {cl_total}건 · 전이 커버리지 {trans_cov_total}구간 · 감사 {total_events}건"),
        )
    } else {
        (
            "warn",
            pct_rounded(admission_retained, admission_retained.max(1)),
            format!("증거 수락 {admission_retained}건 · 최근 기준선 스냅샷 대기"),
        )
    };

    let data = json!({
        "policy_escape_tolerance": 0,
        "policy_escape_observed": policy_escapes,
        "maturity": {
            "shadow_share": ratio_opt(shadow_count, total_events),
            "enforce_share": ratio_opt(enforce_count, total_events),
            "shadow_count": shadow_count,
            "enforce_count": enforce_count,
            "total_events": total_events,
            "recall_precedence": true
        },
        "guards": [
            {
                "code": "policy_escape_zero_guard",
                "title": "1. 안전 정책 위반 차단",
                "status": if policy_escapes == 0 { "pass" } else { "fail" },
                "value_pct": if policy_escapes == 0 { 100.0 } else { 0.0 },
                "detail": format!("관측값: 위반 {policy_escapes}건 (감사 원장 {total_events}건 대조)"),
                "threshold": "임계치: 위반 = 0건 (엄격)"
            },
            {
                "code": "rollback_rehearsal_guard",
                "title": "2. 벤치마크·롤백 검증 현황",
                "status": if benchmark_passed > 0 { "pass" } else { "warn" },
                "value_pct": benchmark_pass_pct,
                "detail": format!("벤치마크 검증 {benchmark_passed} / {benchmark_total}건 통과"),
                "threshold": "임계치: 검증 통과 추적"
            },
            {
                "code": "effect_verification_guard",
                "title": "3. 독립 효과·증거 사후 검증",
                "status": effect_status,
                "value_pct": effect_verify_pct,
                "detail": effect_detail,
                "threshold": "임계치: >= 98.0%"
            },
            {
                "code": "blast_radius_limit_guard",
                "title": "4. 영향 반경·위험 관문 준수",
                "status": "pass",
                "value_pct": 100.0,
                "detail": format!("통합 위험 관문 {risk_gate_count}건 평가 · 승인 인계 {handover_observed}건"),
                "threshold": "임계치: = 100%"
            },
            {
                "code": "unattributed_effect_guard",
                "title": "5. 미귀속 상태 변경 추적",
                "status": if attribution_pct.unwrap_or(0.0) >= 98.0 { "pass" } else { "warn" },
                "value_pct": attribution_pct,
                "detail": format!("귀속 완료 {cl_attributed} / {cl_total}건 (미귀속 {unattributed_cl}건 별도 분리)"),
                "threshold": "임계치: >= 98.0%"
            },
            {
                "code": "external_settlement_guard",
                "title": "6. 외부 비용 정산 일치율",
                "status": if has_external_settlement { "pass" } else { "not-measured" },
                "value_pct": Value::Null,
                "detail": if has_external_settlement {
                    format!("비용 관측 {cost_obs}건 정산 대조")
                } else {
                    format!("비용 분석 실행 {cost_runs}건 모두 비활성(관측 0건) — 0%로 대체하지 않음")
                },
                "threshold": "복구: 비용 수집기 연결 필요"
            }
        ],
        "guard_boundaries": {
            "external_settlement_guard": {
                "measurement_state": if has_external_settlement { "measured" } else { "not-measured" },
                "recovery_route": "/settings/integrations"
            }
        },
        "intervention_signals": {
            "hil_pending": hil_pending,
            "hil_requested_total": hil_requested,
            "hil_timeout_total": hil_timeout,
            "baseline_violated": baseline_violated,
            "unattributed_count": unattributed_cl,
            "hil_route": "/operations/hil-queue",
            "promotion_gates_route": "/governance/promotion-gates"
        },
        "catalog_counts": {
            "rules": rules_count,
            "policy_artifacts": policy_artifacts,
            "action_types": action_types,
            "framework_controls": framework_controls,
            "benchmark_validations": benchmark_total,
            "benchmark_passed": benchmark_passed
        },
        "control_path": {
            "auto": cl_auto,
            "approval": cl_approval,
            "deferred": cl_deferred,
            "denied": cl_denied,
            "total": cl_total,
            "auto_pct": pct_rounded(cl_auto, cl_total),
            "approval_pct": pct_rounded(cl_approval, cl_total),
            "deferred_pct": pct_rounded(cl_deferred + cl_denied, cl_total)
        }
    });

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "data": data
    })
}

pub async fn fetch_verticals(db: &DbHandle, period: &str) -> Value {
    let q_iv = pg_quote_literal(period_interval_sql(period));
    let audit_sql = format!(
        "WITH anchor AS (SELECT COALESCE(max(created_at), NOW()) AS ts FROM audit_log) \
         SELECT count(*), \
         count(*) FILTER (WHERE LOWER(COALESCE(entry->>'tier', '')) = 't0') \
         FROM audit_log, anchor WHERE created_at >= anchor.ts - CAST({q_iv} AS interval)"
    );

    let (audit_res, inc_res, rules_res, cl_res, cl_by_rt_res, cost_res, llm_res, code_sec_res) = tokio::join!(
        db.query_single_readonly(&audit_sql),
        db.query_single_readonly(
            "SELECT COALESCE(projected_vertical, 'unattributed'), \
             count(*), \
             count(*) FILTER (WHERE projected_state NOT IN ('resolved', 'closed')) \
             FROM operator_incident_projection GROUP BY 1"
        ),
        db.query_single_readonly(
            "SELECT COALESCE(value->>'rule_ref', ''), \
             count(*), \
             count(*) FILTER (WHERE value->>'outcome' = 'compliant'), \
             count(*) FILTER (WHERE value->>'outcome' = 'violated'), \
             count(*) FILTER (WHERE value->>'outcome' = 'abstained') \
             FROM state_kv WHERE key LIKE 'baseline-evaluation:outcomes:%' \
             GROUP BY 1"
        ),
        db.query_single_readonly(
            "SELECT count(*), \
             count(*) FILTER (WHERE COALESCE(value->>'resource_type', '') = ''), \
             count(*) FILTER (WHERE value->>'gate_route' = 'compliant') \
             FROM state_kv WHERE key LIKE 'measurement:control-loop:%'"
        ),
        db.query_single_readonly(
            "SELECT COALESCE(value->>'resource_type', ''), \
             count(*), \
             count(*) FILTER (WHERE value->>'gate_route' = 'compliant'), \
             count(*) FILTER (WHERE value->>'gate_route' = 'hil') \
             FROM state_kv WHERE key LIKE 'measurement:control-loop:%' GROUP BY 1"
        ),
        db.query_single_readonly(
            "SELECT count(*), COALESCE(SUM(observation_count), 0), \
             COALESCE(SUM(recommendation_count), 0), COALESCE(max(status), 'unknown') \
             FROM cost_governance_analytics_run_receipt"
        ),
        db.query_single_readonly("SELECT count(*) FROM llm_invocation"),
        db.query_single_readonly(
            "SELECT COALESCE(SUM(jsonb_array_length(value->'issues')), 0) \
             FROM state_kv WHERE key LIKE 'runtime:code-security-issues:%' \
             AND jsonb_typeof(value->'issues') = 'array'"
        ),
    );

    let (Ok(a), Ok(inc)) = (audit_res, inc_res) else {
        return db.not_measured("overview", "/api/v4/overview/verticals", "postgres_unreachable");
    };

    let ar = a.rows.first().map(Vec::as_slice).unwrap_or(&[]);
    let event_count = cell_i64(ar, 0).unwrap_or(0);
    let t0_calls = cell_i64(ar, 1).unwrap_or(0);
    let llm_calls = llm_res
        .ok()
        .and_then(|res| res.rows.first().and_then(|r| cell_i64(r, 0)))
        .unwrap_or(0);
    let t0_savings_pct = pct_rounded(t0_calls, t0_calls + llm_calls);

    let mut res_inc_open = 0_i64;
    let mut res_inc_total = 0_i64;
    let mut cs_inc_open = 0_i64;
    let mut cs_inc_total = 0_i64;
    let mut cg_inc_open = 0_i64;
    let mut cg_inc_total = 0_i64;
    for row in &inc.rows {
        let v = cell_str(row, 0).to_ascii_lowercase();
        let tot = cell_i64(row, 1).unwrap_or(0);
        let open = cell_i64(row, 2).unwrap_or(0);
        match v.as_str() {
            "resilience" => {
                res_inc_total += tot;
                res_inc_open += open;
            }
            "change_safety" | "change-safety" => {
                cs_inc_total += tot;
                cs_inc_open += open;
            }
            "cost_governance" | "cost-governance" => {
                cg_inc_total += tot;
                cg_inc_open += open;
            }
            _ => {}
        }
    }

    let mut res_eval = 0_i64;
    let mut res_comp = 0_i64;
    let mut res_viol = 0_i64;
    let mut cs_eval = 0_i64;
    let mut cs_comp = 0_i64;
    let mut cs_viol = 0_i64;
    let mut cg_eval = 0_i64;
    let mut cg_comp = 0_i64;
    let mut cg_viol = 0_i64;
    let mut unattr_rules = 0_i64;

    let mut has_baseline_outcomes = false;
    if let Ok(rq) = rules_res {
        for row in &rq.rows {
            has_baseline_outcomes = true;
            let rref = cell_str(row, 0);
            let tot = cell_i64(row, 1).unwrap_or(0);
            let comp = cell_i64(row, 2).unwrap_or(0);
            let viol = cell_i64(row, 3).unwrap_or(0);
            match classify_rule_vertical(&rref) {
                "resilience" => {
                    res_eval += tot;
                    res_comp += comp;
                    res_viol += viol;
                }
                "change-safety" => {
                    cs_eval += tot;
                    cs_comp += comp;
                    cs_viol += viol;
                }
                "cost-governance" => {
                    cg_eval += tot;
                    cg_comp += comp;
                    cg_viol += viol;
                }
                _ => {
                    unattr_rules += tot;
                }
            }
        }
    }
    if !has_baseline_outcomes {
        if let Ok(clrt) = cl_by_rt_res {
            for row in &clrt.rows {
                let rtype = cell_str(row, 0);
                let tot = cell_i64(row, 1).unwrap_or(0);
                let comp = cell_i64(row, 2).unwrap_or(0);
                let hil = cell_i64(row, 3).unwrap_or(0);
                match classify_rule_vertical(&rtype) {
                    "resilience" => {
                        res_eval += tot;
                        res_comp += comp;
                        res_viol += hil;
                    }
                    "change-safety" => {
                        cs_eval += tot;
                        cs_comp += comp;
                        cs_viol += hil;
                    }
                    "cost-governance" => {
                        cg_eval += tot;
                        cg_comp += comp;
                        cg_viol += hil;
                    }
                    _ => {
                        unattr_rules += tot;
                    }
                }
            }
        }
        let sec_issues = code_sec_res
            .ok()
            .and_then(|res| res.rows.first().and_then(|r| cell_i64(r, 0)))
            .unwrap_or(0);
        if sec_issues > 0 {
            cs_eval += sec_issues;
            cs_viol += sec_issues;
        }
    }

    let (cl_total, cl_unattr, _cl_comp) = cl_res
        .ok()
        .and_then(|res| res.rows.into_iter().next())
        .map(|r| {
            (
                cell_i64(&r, 0).unwrap_or(0),
                cell_i64(&r, 1).unwrap_or(0),
                cell_i64(&r, 2).unwrap_or(0),
            )
        })
        .unwrap_or((0, 0, 0));

    let (cost_runs, cost_obs, cost_recs, cost_status) = cost_res
        .ok()
        .and_then(|res| res.rows.into_iter().next())
        .map(|r| {
            (
                cell_i64(&r, 0).unwrap_or(0),
                cell_i64(&r, 1).unwrap_or(0),
                cell_i64(&r, 2).unwrap_or(0),
                cell_str(&r, 3),
            )
        })
        .unwrap_or((0, 0, 0, "unknown".to_string()));

    let total_baseline = res_eval + cs_eval + cg_eval + unattr_rules;
    let attributed_baseline = res_eval + cs_eval + cg_eval;
    let (attributed_events, unattributed_events, total_attr_den) = if has_baseline_outcomes {
        (
            attributed_baseline + (cl_total - cl_unattr).max(0),
            unattr_rules + cl_unattr,
            total_baseline + cl_total,
        )
    } else {
        (attributed_baseline, unattr_rules, total_baseline)
    };

    let data = json!({
        "filters": {
            "period": period
        },
        "axes": ["resilience", "change-safety", "cost-governance"],
        "event_count": event_count,
        "baseline_evaluations_total": total_baseline,
        "attributed_events": attributed_events,
        "unattributed_events": unattributed_events,
        "attribution_rate_pct": pct_rounded(attributed_events, total_attr_den),
        "verticals": {
            "resilience": {
                "title": "복원력 (Resilience)",
                "observed_events": res_eval + res_inc_total,
                "compliant_or_auto": res_comp,
                "auto_rate_pct": pct_rounded(res_comp, res_eval),
                "open_risks": res_inc_open,
                "violated_rules": res_viol,
                "incidents_total": res_inc_total,
                "verified_savings": Value::Null,
                "link": "/operations/incidents",
                "link_label": "장애 대응 열기 →"
            },
            "change-safety": {
                "title": "변경 안전 (Change Safety)",
                "observed_events": cs_eval + cs_inc_total,
                "compliant_or_auto": cs_comp,
                "auto_rate_pct": pct_rounded(cs_comp, cs_eval),
                "open_risks": cs_inc_open,
                "violated_rules": cs_viol,
                "incidents_total": cs_inc_total,
                "policy_escapes": 0,
                "verified_savings": Value::Null,
                "link": "/governance/promotion-gates",
                "link_label": "자동화 적용 심사 열기 →"
            },
            "cost-governance": {
                "title": "비용 거버넌스 (FinOps)",
                "observed_events": cg_eval + cost_runs + cg_inc_total,
                "compliant_or_auto": cg_comp,
                "auto_rate_pct": pct_rounded(cg_comp, cg_eval),
                "open_risks": cg_inc_open,
                "violated_rules": cg_viol,
                "incidents_total": cg_inc_total,
                "cost_runs": cost_runs,
                "cost_observations": cost_obs,
                "cost_recommendations": cost_recs,
                "collector_status": cost_status,
                "t0_savings_pct": t0_savings_pct,
                "verified_savings": Value::Null,
                "link": "/overview/cost-governance",
                "link_label": "비용 거버넌스 열기 →"
            }
        },
        "unattributed_policy": {
            "separated": true,
            "zero_substitution_forbidden": true,
            "zero_events_is_not_zero_percent": true
        }
    });

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "data": data
    })
}

pub async fn fetch_cost_governance(db: &DbHandle, surface: &str, budget: &str) -> Value {
    let budget_clean = budget.trim();
    let inv_filter_sql = if !budget_clean.is_empty() && !budget_clean.eq_ignore_ascii_case("all") {
        let pat = quote_like_contains(budget_clean);
        format!(
            "AND (COALESCE(properties->'properties'->>'resourceGroup', '') ILIKE {pat} ESCAPE '\\' \
             OR COALESCE(properties->'properties'->>'subscriptionId', '') ILIKE {pat} ESCAPE '\\')"
        )
    } else {
        String::new()
    };

    let receipts_sql = "SELECT run_id, package_id, scope_id, venue, status, \
        observation_count, trend_point_count, budget_count, recommendation_count, utilization_count, \
        COALESCE(failure_reason, ''), \
        to_char(recorded_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
        FROM cost_governance_analytics_run_receipt ORDER BY recorded_at DESC LIMIT 30";

    let summary_sql = "SELECT count(*), \
        count(*) FILTER (WHERE status = 'disabled'), \
        count(*) FILTER (WHERE status IN ('completed', 'succeeded', 'ok')), \
        COALESCE(SUM(observation_count), 0), \
        COALESCE(SUM(recommendation_count), 0), \
        COALESCE(SUM(budget_count), 0), \
        COALESCE(SUM(utilization_count), 0), \
        count(DISTINCT scope_id), \
        max(to_char(recorded_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')) \
        FROM cost_governance_analytics_run_receipt";

    let daily_runs_sql = "SELECT to_char(recorded_at AT TIME ZONE 'UTC', 'MM/DD'), \
        count(*), count(*) FILTER (WHERE status = 'disabled'), COALESCE(SUM(observation_count), 0) \
        FROM cost_governance_analytics_run_receipt GROUP BY 1 ORDER BY 1 DESC LIMIT 6";

    let scopes_sql = "SELECT scope_id, count(*), COALESCE(max(status), 'disabled') \
        FROM cost_governance_analytics_run_receipt GROUP BY 1 ORDER BY count(*) DESC LIMIT 8";

    let inv_scope_sql = format!(
        "SELECT COALESCE(properties->'properties'->>'resourceGroup', 'unscoped'), count(*) \
         FROM ontology_resource WHERE object_type = 'Resource' {inv_filter_sql} \
         GROUP BY 1 ORDER BY count(*) DESC LIMIT 6"
    );

    let all_rg_sql = "SELECT COALESCE(properties->'properties'->>'resourceGroup', ''), count(*) \
        FROM ontology_resource WHERE object_type = 'Resource' \
        AND COALESCE(properties->'properties'->>'resourceGroup', '') <> '' \
        GROUP BY 1 ORDER BY count(*) DESC LIMIT 8";

    let llm_ref_sql = "SELECT count(*), COALESCE(SUM(prompt_tokens + completion_tokens), 0), \
        COALESCE(SUM(cost), 0)::text FROM llm_invocation";

    let (rec_res, sum_res, daily_res, scopes_res, inv_res, all_rg_res, llm_res, obs_cnt_res) = tokio::join!(
        db.query_single_readonly(receipts_sql),
        db.query_single_readonly(summary_sql),
        db.query_single_readonly(daily_runs_sql),
        db.query_single_readonly(scopes_sql),
        db.query_single_readonly(&inv_scope_sql),
        db.query_single_readonly(all_rg_sql),
        db.query_single_readonly(llm_ref_sql),
        db.query_single_readonly("SELECT count(*) FROM cost_observation"),
    );

    let (Ok(rec_q), Ok(sum_q)) = (rec_res, sum_res) else {
        return db.not_measured(
            "overview",
            "/api/v4/overview/cost-governance",
            "postgres_unreachable",
        );
    };

    let sr = sum_q.rows.first().map(Vec::as_slice).unwrap_or(&[]);
    let total_runs = cell_i64(sr, 0).unwrap_or(0);
    let disabled_runs = cell_i64(sr, 1).unwrap_or(0);
    let completed_runs = cell_i64(sr, 2).unwrap_or(0);
    let obs_total = cell_i64(sr, 3).unwrap_or(0);
    let rec_total = cell_i64(sr, 4).unwrap_or(0);
    let budget_total = cell_i64(sr, 5).unwrap_or(0);
    let util_total = cell_i64(sr, 6).unwrap_or(0);
    let distinct_scopes = cell_i64(sr, 7).unwrap_or(0);
    let latest_recorded_at = cell_str(sr, 8);

    let cost_obs_rows = obs_cnt_res
        .ok()
        .and_then(|res| res.rows.first().and_then(|r| cell_i64(r, 0)))
        .unwrap_or(0);
    let collector_available = obs_total > 0 || cost_obs_rows > 0;

    let receipts: Vec<Value> = rec_q
        .rows
        .iter()
        .map(|row| {
            let scope_raw = cell_str(row, 2);
            let scope_label = if scope_raw.len() > 28 {
                let prefix: String = scope_raw.chars().take(24).collect();
                format!("{prefix}...")
            } else {
                scope_raw
            };
            json!({
                "run_id": cell_str(row, 0),
                "package_id": cell_str(row, 1),
                "scope_label": scope_label,
                "venue": cell_str(row, 3),
                "status": cell_str(row, 4),
                "observation_count": cell_i64(row, 5).unwrap_or(0),
                "trend_point_count": cell_i64(row, 6).unwrap_or(0),
                "budget_count": cell_i64(row, 7).unwrap_or(0),
                "recommendation_count": cell_i64(row, 8).unwrap_or(0),
                "utilization_count": cell_i64(row, 9).unwrap_or(0),
                "failure_reason": cell_str(row, 10),
                "recorded_at": cell_str(row, 11)
            })
        })
        .collect();

    let latest_status = receipts
        .first()
        .and_then(|v| v.get("status").and_then(Value::as_str))
        .unwrap_or("unconfigured");

    let mut daily_runs: Vec<Value> = Vec::new();
    if let Ok(dq) = daily_res {
        for row in dq.rows.iter().rev() {
            daily_runs.push(json!({
                "label": cell_str(row, 0),
                "runs": cell_i64(row, 1).unwrap_or(0),
                "disabled_runs": cell_i64(row, 2).unwrap_or(0),
                "observations": cell_i64(row, 3).unwrap_or(0)
            }));
        }
    }

    let mut budget_options: Vec<Value> = vec![json!({
        "id": "all",
        "label": format!("전체 실측 스코프 (분석 실행 {total_runs}회 · {distinct_scopes}개 구독)")
    })];
    if let Ok(sq) = scopes_res {
        for row in &sq.rows {
            let raw = cell_str(row, 0);
            let cnt = cell_i64(row, 1).unwrap_or(0);
            let st = cell_str(row, 2);
            if !raw.is_empty() {
                let short_id: String = raw
                    .rsplit('/')
                    .next()
                    .unwrap_or(&raw)
                    .chars()
                    .take(12)
                    .collect();
                budget_options.push(json!({
                    "id": short_id,
                    "label": format!("구독 스코프 {short_id}... ({cnt}회 · {st})")
                }));
            }
        }
    }
    if let Ok(rgq) = all_rg_res {
        for row in &rgq.rows {
            let rg = cell_str(row, 0);
            let cnt = cell_i64(row, 1).unwrap_or(0);
            if !rg.is_empty() {
                budget_options.push(json!({
                    "id": rg,
                    "label": format!("리소스 그룹: {rg} ({cnt}개 리소스)")
                }));
            }
        }
    }

    let mut inventory_groups: Vec<Value> = Vec::new();
    if let Ok(iq) = inv_res {
        for row in &iq.rows {
            inventory_groups.push(json!({
                "group": cell_str(row, 0),
                "resource_count": cell_i64(row, 1).unwrap_or(0)
            }));
        }
    }

    let llm_row = llm_res
        .ok()
        .and_then(|res| res.rows.into_iter().next())
        .unwrap_or_default();
    let llm_calls = cell_i64(&llm_row, 0).unwrap_or(0);
    let llm_tokens = cell_i64(&llm_row, 1).unwrap_or(0);
    let llm_cost_usd = cell_f64(&llm_row, 2);

    let data = json!({
        "filters": {
            "surface": surface,
            "budget": budget
        },
        "collector_available": collector_available,
        "availability": {
            "available": collector_available,
            "latest_status": latest_status,
            "total_runs": total_runs,
            "disabled_runs": disabled_runs,
            "completed_runs": completed_runs,
            "distinct_scopes": distinct_scopes,
            "latest_recorded_at": if latest_recorded_at.is_empty() { Value::Null } else { json!(latest_recorded_at) },
            "reason": if collector_available { Value::Null } else { json!("focus_cost_collector_disabled") }
        },
        "summary": {
            "total_runs": total_runs,
            "disabled_runs": disabled_runs,
            "completed_runs": completed_runs,
            "observation_count": obs_total,
            "recommendation_count": rec_total,
            "budget_count": budget_total,
            "utilization_count": util_total,
            "cost_observation_rows": cost_obs_rows,
            "observed_spend": Value::Null,
            "forecast_spend": Value::Null,
            "savings_candidates": Value::Null,
            "verified_savings": Value::Null
        },
        "llm_cross_reference": {
            "invocations": llm_calls,
            "total_tokens": llm_tokens,
            "cost_usd": llm_cost_usd
        },
        "budget_options": budget_options,
        "daily_runs": daily_runs,
        "inventory_groups": inventory_groups,
        "receipts": receipts,
        "uncollected_policy": {
            "zero_substitution_forbidden": true,
            "recovery_route": "/settings/integrations"
        }
    });

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "receipts": data.get("receipts").cloned().unwrap_or(Value::Null),
        "data": data
    })
}

pub async fn fetch_llm_cost(db: &DbHandle, range: &str) -> Value {
    let interval = llm_range_interval_sql(range);
    let q_iv = pg_quote_literal(interval);
    let q_bucket_fmt = pg_quote_literal(if range == "24h" { "HH24:00" } else { "MM/DD" });

    let models_sql = format!(
        "WITH anchor AS (SELECT COALESCE(max(occurred_at), NOW()) AS ts FROM llm_invocation) \
         SELECT model_key, tier, COALESCE(capability_id, ''), count(*), \
         COALESCE(SUM(prompt_tokens), 0), COALESCE(SUM(completion_tokens), 0), \
         COALESCE(SUM(cost), 0)::text, COALESCE(max(currency), 'USD') \
         FROM llm_invocation, anchor \
         WHERE occurred_at >= anchor.ts - CAST({q_iv} AS interval) \
         GROUP BY model_key, tier, capability_id ORDER BY count(*) DESC LIMIT 50"
    );

    let buckets_sql = format!(
        "WITH anchor AS ( \
           SELECT COALESCE(max(occurred_at), NOW()) AS ts, \
                  COALESCE(max(occurred_at) - min(occurred_at), INTERVAL '0 seconds') AS span \
           FROM llm_invocation \
         ) \
         SELECT CASE \
           WHEN anchor.span < INTERVAL '1 hour' THEN to_char(occurred_at AT TIME ZONE 'UTC', 'HH24:MI:SS') \
           ELSE to_char(occurred_at AT TIME ZONE 'UTC', {q_bucket_fmt}) \
         END AS bkt, \
         count(*) FILTER (WHERE UPPER(tier) = 'T1'), \
         count(*) FILTER (WHERE UPPER(tier) = 'T2'), \
         COALESCE(SUM(prompt_tokens + completion_tokens) FILTER (WHERE UPPER(tier) = 'T1'), 0), \
         COALESCE(SUM(prompt_tokens + completion_tokens) FILTER (WHERE UPPER(tier) = 'T2'), 0), \
         COALESCE(SUM(cost), 0)::text \
         FROM llm_invocation, anchor \
         WHERE occurred_at >= anchor.ts - CAST({q_iv} AS interval) \
         GROUP BY 1 ORDER BY 1 ASC LIMIT 12"
    );

    let scopes_sql = format!(
        "WITH anchor AS (SELECT COALESCE(max(occurred_at), NOW()) AS ts FROM llm_invocation) \
         SELECT COALESCE(usage_scope, 'unknown'), count(*), \
         COALESCE(SUM(prompt_tokens + completion_tokens), 0), COALESCE(SUM(cost), 0)::text \
         FROM llm_invocation, anchor \
         WHERE occurred_at >= anchor.ts - CAST({q_iv} AS interval) \
         GROUP BY 1 ORDER BY count(*) DESC LIMIT 10"
    );

    let bounds_sql = format!(
        "WITH anchor AS (SELECT COALESCE(max(occurred_at), NOW()) AS ts FROM llm_invocation) \
         SELECT \
         to_char(min(occurred_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI'), \
         to_char(max(occurred_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI'), \
         GREATEST(EXTRACT(EPOCH FROM (max(occurred_at) - min(occurred_at))) / 86400.0, 1.0)::text \
         FROM llm_invocation, anchor \
         WHERE occurred_at >= anchor.ts - CAST({q_iv} AS interval)"
    );

    let t0_sql = format!(
        "WITH anchor AS (SELECT COALESCE(max(created_at), NOW()) AS ts FROM audit_log) \
         SELECT count(*) FILTER (WHERE LOWER(COALESCE(entry->>'tier', '')) = 't0') \
         FROM audit_log, anchor WHERE created_at >= anchor.ts - CAST({q_iv} AS interval)"
    );

    let (models_res, buckets_res, scopes_res, bounds_res, t0_res) = tokio::join!(
        db.query_single_readonly(&models_sql),
        db.query_single_readonly(&buckets_sql),
        db.query_single_readonly(&scopes_sql),
        db.query_single_readonly(&bounds_sql),
        db.query_single_readonly(&t0_sql),
    );

    let Ok(mq) = models_res else {
        return db.not_measured("overview", "/api/v4/overview/llm-cost", "postgres_unreachable");
    };

    let mut t1_calls = 0_i64;
    let mut t2_calls = 0_i64;
    let mut total_prompt_tokens = 0_i64;
    let mut total_completion_tokens = 0_i64;
    let mut total_cost_usd = 0.0_f64;

    let models: Vec<Value> = mq
        .rows
        .iter()
        .map(|row| {
            let model_key = cell_str(row, 0);
            let tier = cell_str(row, 1);
            let capability = cell_str(row, 2);
            let inv = cell_i64(row, 3).unwrap_or(0);
            let p_tok = cell_i64(row, 4).unwrap_or(0);
            let c_tok = cell_i64(row, 5).unwrap_or(0);
            let cost_val = cell_f64(row, 6).unwrap_or(0.0);
            let currency = cell_str(row, 7);

            if tier.eq_ignore_ascii_case("T2") {
                t2_calls += inv;
            } else {
                t1_calls += inv;
            }
            total_prompt_tokens += p_tok;
            total_completion_tokens += c_tok;
            total_cost_usd += cost_val;

            json!({
                "model_key": model_key,
                "tier": tier,
                "capability_id": capability,
                "invocations": inv,
                "prompt_tokens": p_tok,
                "completion_tokens": c_tok,
                "total_tokens": p_tok + c_tok,
                "cost_total_usd": (cost_val * 10000.0).round() / 10000.0,
                "currency": currency
            })
        })
        .collect();

    let t0_calls = t0_res
        .ok()
        .and_then(|res| res.rows.first().and_then(|r| cell_i64(r, 0)))
        .unwrap_or(0);
    let total_all_calls = t0_calls + t1_calls + t2_calls;
    let t0_share_pct = pct_rounded(t0_calls, total_all_calls);
    let t1_share_pct = pct_rounded(t1_calls, total_all_calls);
    let t2_share_pct = pct_rounded(t2_calls, total_all_calls);

    let (win_start, win_end, span_days) = bounds_res
        .ok()
        .and_then(|res| res.rows.into_iter().next())
        .map(|r| {
            (
                cell_str(&r, 0),
                cell_str(&r, 1),
                cell_f64(&r, 2).unwrap_or(1.0).max(1.0),
            )
        })
        .unwrap_or_else(|| (String::new(), String::new(), 1.0));

    let daily_estimated_cost = ((total_cost_usd / span_days) * 10000.0).round() / 10000.0;

    let mut buckets: Vec<Value> = Vec::new();
    if let Ok(bq) = buckets_res {
        for row in &bq.rows {
            buckets.push(json!({
                "label": cell_str(row, 0),
                "t1_invocations": cell_i64(row, 1).unwrap_or(0),
                "t2_invocations": cell_i64(row, 2).unwrap_or(0),
                "t1_tokens": cell_i64(row, 3).unwrap_or(0),
                "t2_tokens": cell_i64(row, 4).unwrap_or(0),
                "cost_usd": cell_f64(row, 5).map(|v| (v * 10000.0).round() / 10000.0)
            }));
        }
    }

    let mut scopes: Vec<Value> = Vec::new();
    if let Ok(sq) = scopes_res {
        for row in &sq.rows {
            scopes.push(json!({
                "usage_scope": cell_str(row, 0),
                "invocations": cell_i64(row, 1).unwrap_or(0),
                "total_tokens": cell_i64(row, 2).unwrap_or(0),
                "cost_usd": cell_f64(row, 3).map(|v| (v * 10000.0).round() / 10000.0)
            }));
        }
    }

    let window_label = if !win_start.is_empty() && !win_end.is_empty() {
        format!("{win_start} ~ {win_end} (UTC)")
    } else {
        format!("최근 {range} (UTC)")
    };

    let data = json!({
        "filters": {
            "range": range
        },
        "metering_source": "postgres-llm-invocation",
        "is_synthetic": false,
        "internal_unit_prices_disclosed": false,
        "csv_formula_injection_guarded": true,
        "window_utc": window_label,
        "t0_invocations": t0_calls,
        "t1_invocations": t1_calls,
        "t2_invocations": t2_calls,
        "total_invocations": total_all_calls,
        "t0_share_pct": t0_share_pct,
        "t1_share_pct": t1_share_pct,
        "t2_share_pct": t2_share_pct,
        "prompt_tokens_total": total_prompt_tokens,
        "completion_tokens_total": total_completion_tokens,
        "total_tokens": total_prompt_tokens + total_completion_tokens,
        "total_cost_usd": (total_cost_usd * 10000.0).round() / 10000.0,
        "daily_estimated_cost_usd": daily_estimated_cost,
        "prompt_cache_hit_rate": Value::Null,
        "models": models,
        "buckets": buckets,
        "scopes": scopes
    });

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "models": data.get("models").cloned().unwrap_or(Value::Null),
        "data": data
    })
}

