import type { PillKind } from "../components/ui";
import type { AuditItem } from "../types";

const AGENT_LAYER = new Map<string, string>([
  ["Odin", "planning"],
  ["Thor", "execution"],
  ["Forseti", "judgment"],
  ["Huginn", "sensing"],
  ["Heimdall", "sensing"],
  ["Var", "approval"],
  ["Vidar", "recovery"],
  ["Bragi", "conversational"],
  ["Saga", "audit"],
  ["Mimir", "governance"],
  ["Norns", "governance"],
  ["Muninn", "governance"],
  ["Njord", "domain"],
  ["Freyr", "domain"],
  ["Loki", "domain"],
]);

const LEGACY_OBSERVATION_OWNER_BY_SOURCE = new Map<string, string>([
  ["inventory", "Huginn"],
  ["activity-log", "Huginn"],
  ["resource-health", "Heimdall"],
  ["service-health", "Heimdall"],
  ["metrics", "Heimdall"],
  ["logs", "Heimdall"],
  ["guest-logs", "Heimdall"],
  ["network-config", "Heimdall"],
  ["cost", "Njord"],
  ["recovery", "Vidar"],
]);

export function agentOf(item: AuditItem): string {
  const principal = entryAgent(item, "producer_principal");
  if (principal !== null) return principal;
  const owner = entryAgent(item, "owner_agent");
  if (owner !== null) return owner;
  if (AGENT_LAYER.has(item.actor)) return item.actor;
  const semanticOwner = semanticAgentOwner(item);
  if (semanticOwner !== null) return semanticOwner;
  const mechanicalPrincipal = item.entry["producer_principal"];
  if (typeof mechanicalPrincipal === "string" && mechanicalPrincipal.trim()) {
    return mechanicalPrincipal.trim();
  }
  if (item.actor === "fdai") return "System";
  if (item.actor === "fdai.system") return "System";
  if (item.actor && item.actor.trim()) return humanizeActor(item.actor);
  return "System";
}

function semanticAgentOwner(item: AuditItem): string | null {
  const rawPrincipal = item.entry["producer_principal"];
  const mechanicalSource = item.actor.startsWith("fdai.") ||
    item.actor.startsWith("runtime.") ||
    rawPrincipal === "control-loop";
  if (!mechanicalSource) return null;
  const actionKind = item.action_kind.toLowerCase();
  const stage = typeof item.entry["stage"] === "string"
    ? item.entry["stage"].toLowerCase()
    : "";
  if (actionKind === "observation-campaign.source-transition") {
    const sourceId = item.entry["source_id"];
    return typeof sourceId === "string"
      ? LEGACY_OBSERVATION_OWNER_BY_SOURCE.get(sourceId) ?? null
      : null;
  }
  if (isSagaAuditMirror(item) || actionKind === "startup_readiness.audit_probe") return "Saga";
  if (actionKind.startsWith("measurement.control_loop.")) return "Heimdall";
  if (actionKind.startsWith("hil.") || item.actor === "fdai.core.hil_resume") return "Var";
  if (actionKind.startsWith("risk_gate.")) return "Forseti";
  if (actionKind.startsWith("rca.") || item.actor === "fdai.core.rca") return "Forseti";
  if (actionKind.startsWith("governance.")) return "Mimir";
  if (actionKind.startsWith("measurement.pattern_growth")) return "Norns";
  if (actionKind.startsWith("executor.") || item.actor === "fdai.core.executor") return "Thor";
  if (actionKind.startsWith("rollback.") || actionKind.startsWith("recovery.")) return "Vidar";
  if (actionKind.startsWith("workflow.") || actionKind.startsWith("arbitration.")) return "Odin";
  if (actionKind.startsWith("cost.")) return "Njord";
  if (actionKind.startsWith("capacity.")) return "Freyr";
  if (actionKind.startsWith("chaos.")) return "Loki";
  if (actionKind.startsWith("memory.") || actionKind.startsWith("context.")) return "Muninn";
  if (actionKind.startsWith("conversation.") || actionKind.startsWith("narrator.")) return "Bragi";
  if (actionKind.startsWith("control_loop.")) {
    return stage === "trust_router" ? "Heimdall" : "Forseti";
  }
  return null;
}

function entryAgent(item: AuditItem, key: "producer_principal" | "owner_agent"): string | null {
  const value = item.entry[key];
  if (typeof value !== "string") return null;
  const candidate = value.trim();
  return AGENT_LAYER.has(candidate) ? candidate : null;
}

export function isSagaAuditMirror(item: AuditItem): boolean {
  if (item.action_kind !== "audit.record") return false;
  if (item.actor === "Saga") return true;
  return typeof item.entry["principal"] === "string" &&
    typeof item.entry["topic"] === "string" &&
    typeof item.entry["payload_digest"] === "string" &&
    typeof item.entry["payload"] === "object" &&
    item.entry["payload"] !== null &&
    !Array.isArray(item.entry["payload"]);
}

function humanizeActor(actor: string): string {
  const parts = actor.split(".");
  if (parts.length >= 2 && parts[0] === "fdai") return parts.slice(1).join(".");
  return actor;
}

export function isAgentActivitySelectionValid(
  selected: string | null,
  observedAgents: readonly string[],
): boolean {
  return selected === null || AGENT_LAYER.has(selected) || observedAgents.includes(selected);
}

export interface ActivityPresentationState {
  readonly showLiveSummary: boolean;
  readonly emptyKind: "all-audit" | "filtered" | "selected-audit" | null;
}

export function activityPresentationState({
  totalAuditCount,
  visibleAuditCount,
  selected,
  selectionValid,
  hasSelectedNode,
}: {
  readonly totalAuditCount: number;
  readonly visibleAuditCount: number;
  readonly selected: string | null;
  readonly selectionValid: boolean;
  readonly hasSelectedNode: boolean;
}): ActivityPresentationState {
  return {
    showLiveSummary: selectionValid && selected !== null && hasSelectedNode,
    emptyKind: !selectionValid || visibleAuditCount > 0
      ? null
      : selected !== null
        ? "selected-audit"
        : totalAuditCount === 0
          ? "all-audit"
          : "filtered",
  };
}

export function agentActivityRank(label: string): number {
  return label === "System" ? 2 : AGENT_LAYER.has(label) ? 0 : 1;
}

export function layerOf(agent: string): string {
  return AGENT_LAYER.get(agent) ?? "system";
}

export function outcomeOf(item: AuditItem): string | null {
  const outcome = item.entry["outcome"];
  return typeof outcome === "string" ? outcome : null;
}

export function summaryOf(item: AuditItem): string | null {
  const summary = item.entry["summary"];
  if (typeof summary === "string" && summary.trim()) return summary;
  if (item.action_kind === "control_loop.t1_evaluate") {
    const outcome = item.entry["t1_outcome"];
    const reason = item.entry["t1_reason"];
    if (typeof outcome === "string") {
      return typeof reason === "string" && reason ? `T1 ${outcome} (${reason})` : `T1 ${outcome}`;
    }
  }
  if (item.action_kind === "control_loop.t2_evaluate") {
    const outcome = item.entry["t2_outcome"];
    const reason = item.entry["t2_reason"];
    if (typeof outcome === "string") {
      return typeof reason === "string" && reason ? `T2 ${outcome} (${reason})` : `T2 ${outcome}`;
    }
  }
  if (item.action_kind === "rca.hypothesis") {
    const cause = item.entry["rca_cause"];
    if (typeof cause === "string" && cause.trim()) return cause.trim();
  }
  return null;
}

export function tierOf(item: AuditItem): string | null {
  const tier =
    item.entry["tier"] ??
    item.entry["rca_tier"] ??
    item.entry["routed_to"];
  if (typeof tier === "string" && tier.trim()) return tier.trim().toUpperCase();
  if (
    item.entry["stage"] === "t1_similarity" ||
    typeof item.entry["t1_outcome"] === "string" ||
    item.action_kind === "control_loop.t1_evaluate" ||
    item.action_kind === "control_loop.t1_reuse_advisory"
  ) {
    return "T1";
  }
  if (
    item.entry["stage"] === "t2_reasoning" ||
    typeof item.entry["t2_outcome"] === "string" ||
    item.action_kind === "control_loop.t2_evaluate"
  ) {
    return "T2";
  }
  return null;
}

export function rcaOutcomeOf(item: AuditItem): string | null {
  const outcome = item.entry["rca_outcome"];
  return typeof outcome === "string" && outcome.trim() ? outcome.trim() : null;
}

export function citedRulesOf(item: AuditItem): readonly string[] {
  const direct = item.entry["citing_rule_ids"];
  if (Array.isArray(direct)) {
    return direct.filter((rule): rule is string => typeof rule === "string" && rule.trim().length > 0);
  }
  const candidate = item.entry["t2_candidate"];
  if (candidate !== null && typeof candidate === "object" && !Array.isArray(candidate)) {
    const cited = (candidate as Record<string, unknown>)["cited_rule_ids"];
    if (Array.isArray(cited)) {
      return cited.filter((rule): rule is string => typeof rule === "string" && rule.trim().length > 0);
    }
  }
  const ruleId = item.entry["rule_id"];
  return typeof ruleId === "string" && ruleId.trim() ? [ruleId.trim()] : [];
}

export type AuditProvenance = "operational" | "sample";

export function auditProvenanceOf(item: AuditItem): AuditProvenance {
  return item.entry["fixture_source"] === "operator-api-dev-seed" ||
    item.entry["observation_source"] === "synthetic-dev"
    ? "sample"
    : "operational";
}

export function activityProvenanceCounts(items: readonly AuditItem[]): {
  readonly operational: number;
  readonly sample: number;
} {
  let operational = 0;
  let sample = 0;
  for (const item of items) {
    if (auditProvenanceOf(item) === "sample") sample += 1;
    else operational += 1;
  }
  return { operational, sample };
}

export function outcomePill(outcome: string): PillKind {
  if (outcome.includes("hil") || outcome.includes("await")) return "hil";
  if (outcome.includes("escalat")) return "warning";
  if (outcome === "auto") return "auto";
  if (outcome.includes("pr_opened") || outcome.includes("recorded")) return "success";
  if (outcome.includes("matched") || outcome.includes("normalized")) return "info";
  return "neutral";
}

export function modePill(mode: string): PillKind {
  if (mode === "enforce") return "enforce";
  if (mode === "shadow") return "shadow";
  return "neutral";
}

export function milliseconds(iso: string): number {
  const value = new Date(iso).getTime();
  return Number.isNaN(value) ? 0 : value;
}

export function entryStr(item: AuditItem, key: string): string | null {
  const value = item.entry[key];
  return typeof value === "string" ? value : null;
}

export function entryNum(item: AuditItem, key: string): number | null {
  const value = item.entry[key];
  return typeof value === "number" ? value : null;
}

export function entryMap(
  item: AuditItem,
  key: string,
): ReadonlyArray<readonly [string, string]> | null {
  const value = item.entry[key];
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const pairs = Object.entries(value as Record<string, unknown>)
    .filter((entry): entry is [string, string] => typeof entry[1] === "string");
  return pairs.length > 0 ? pairs : null;
}

export interface AgentTurn {
  readonly from: string;
  readonly to: string;
  readonly text: string;
}

export function entryConversation(item: AuditItem): readonly AgentTurn[] | null {
  const value = item.entry["conversation"];
  if (!Array.isArray(value)) return null;
  const turns = value.filter(
    (turn): turn is AgentTurn =>
      turn !== null &&
      typeof turn === "object" &&
      typeof (turn as AgentTurn).from === "string" &&
      typeof (turn as AgentTurn).to === "string" &&
      typeof (turn as AgentTurn).text === "string",
  );
  return turns.length > 0 ? turns : null;
}

const SHOWN_ENTRY_KEYS: ReadonlySet<string> = new Set([
  "event_ts", "received_at", "started_at", "finished_at", "duration_ms", "queue_ms",
  "detail", "summary", "inputs", "outputs", "conversation",
  "tier", "outcome", "decision", "pipeline_stage", "reason",
  "producer_principal", "action_kind", "correlation_id", "recorded_at", "event_id",
  "actor", "mode",
  "fixture_source", "observation_source",
]);

function fmtScalar(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function fmtEntryValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.map(fmtScalar).join(", ");
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, nested]) => `${key}: ${fmtScalar(nested)}`)
      .join(" · ");
  }
  return String(value);
}

export function otherEntryFields(item: AuditItem): ReadonlyArray<readonly [string, string]> {
  return Object.entries(item.entry)
    .filter(([key, value]) =>
      !SHOWN_ENTRY_KEYS.has(key) && value !== null && value !== undefined && value !== "")
    .map(([key, value]) => [key, fmtEntryValue(value)] as const)
    .filter(([, value]) => value !== "");
}

export function clockMs(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const value = String(date.getMilliseconds()).padStart(3, "0");
  return `${clock(iso)}.${value}`;
}

function clock(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  const seconds = String(date.getSeconds()).padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
}

export function startClockOf(item: AuditItem): string {
  return clock(entryStr(item, "started_at") ?? item.recorded_at);
}

export function fmtDur(millis: number): string {
  if (millis <= 0) return "0s";
  if (millis < 1000) return `${Math.round(millis)}ms`;
  const totalSeconds = Math.round(millis / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) return `${seconds}s`;
  if (seconds === 0) return `${minutes}m`;
  return `${minutes}m ${seconds}s`;
}

export interface BilingualText {
  readonly en: string;
  readonly ko: string;
}

export const RESOURCE_TYPE_LABELS: Readonly<Record<string, BilingualText>> = {
  "authorization.role-assignment": { en: "IAM Role Assignment", ko: "IAM 역할 할당" },
  "compute.vm-scale-set": { en: "VM Scale Set (VMSS)", ko: "가상 머신 확장 집합(VMSS)" },
  "compute.vm": { en: "Virtual Machine (VM)", ko: "가상 머신(VM)" },
  "compute.vm-extension": { en: "VM Extension", ko: "가상 머신 확장(Extension)" },
  "compute.vm-run-command": { en: "VM Run Command", ko: "가상 머신 실행 명령" },
  "compute.vm-shutdown-schedule": { en: "VM Auto-Shutdown Schedule", ko: "가상 머신 자동 종료 일정" },
  "compute.image": { en: "Compute Image", ko: "컴퓨팅 이미지" },
  "compute.image-gallery": { en: "Compute Image Gallery", ko: "컴퓨팅 이미지 갤러리" },
  "compute.gallery-image": { en: "Gallery Image Definition", ko: "갤러리 이미지 정의" },
  "compute.gallery-image-version": { en: "Gallery Image Version", ko: "갤러리 이미지 버전" },
  "compute.container-app": { en: "Container App", ko: "컨테이너 앱(Container App)" },
  "compute.container-app-job": { en: "Container Apps Job", ko: "컨테이너 앱 작업(Job)" },
  "compute.container-app-environment": { en: "Container Apps Environment", ko: "컨테이너 앱 환경" },
  "compute.function": { en: "Function App", ko: "함수 앱(Function App)" },
  "network.nsg": { en: "Network Security Group (NSG)", ko: "네트워크 보안 그룹(NSG)" },
  "network.vnet": { en: "Virtual Network (VNet)", ko: "가상 네트워크(VNet)" },
  "network.subnet": { en: "Subnet", ko: "서브넷(Subnet)" },
  "network.interface": { en: "Network Interface (NIC)", ko: "네트워크 인터페이스(NIC)" },
  "network.public-ip": { en: "Public IP Address", ko: "공인 IP 주소" },
  "network.load-balancer": { en: "Load Balancer", ko: "부하 분산 장치(Load Balancer)" },
  "network.nat-gateway": { en: "NAT Gateway", ko: "NAT 게이트웨이" },
  "network.private-endpoint": { en: "Private Endpoint", ko: "프라이빗 엔드포인트" },
  "network.private-dns-zone": { en: "Private DNS Zone", ko: "프라이빗 DNS 영역" },
  "network.private-dns-zone-link": { en: "Private DNS VNet Link", ko: "프라이빗 DNS 가상 네트워크 링크" },
  "network.private-dns-zone-group": { en: "Private DNS Zone Group", ko: "프라이빗 DNS 영역 그룹" },
  "network.dns-zone": { en: "Public DNS Zone", ko: "DNS 영역" },
  "network.bastion-host": { en: "Azure Bastion Host", ko: "배스천 호스트(Bastion)" },
  "network.firewall": { en: "Network Firewall", ko: "네트워크 방화벽" },
  "network.firewall-policy": { en: "Firewall Policy", ko: "방화벽 정책" },
  "network.route-table": { en: "Route Table", ko: "라우팅 테이블" },
  "network.registered-domain": { en: "Registered Domain", ko: "등록 도메인" },
  "managed-identity": { en: "Managed Identity", ko: "관리 ID(Managed Identity)" },
  "resource-group": { en: "Resource Group", ko: "리소스 그룹" },
  "subscription": { en: "Subscription", ko: "구독(Subscription)" },
  "log-workspace": { en: "Log Analytics Workspace", ko: "로그 분석 작업 영역(Log Analytics)" },
  "disk": { en: "Managed Disk", ko: "관리 디스크(Disk)" },
  "object-storage": { en: "Storage Account", ko: "스토리지 계정" },
  "postgresql-server": { en: "PostgreSQL Flexible Server", ko: "PostgreSQL 서버" },
  "secret-store": { en: "Key Vault Secret Store", ko: "비밀 저장소(Key Vault)" },
  "container-registry": { en: "Container Registry (ACR)", ko: "컨테이너 레지스트리(ACR)" },
  "kubernetes-cluster": { en: "AKS Kubernetes Cluster", ko: "AKS 쿠버네티스 클러스터" },
  "kubernetes-node-pool": { en: "AKS Node Pool", ko: "AKS 노드 풀" },
  "llm-model-deployment": { en: "AI Model Deployment", ko: "AI 모델 배포" },
  "llm-endpoint": { en: "AI Services Endpoint", ko: "AI 서비스 엔드포인트" },
  "ai-project": { en: "AI Foundry Project", ko: "AI 파운드리 프로젝트" },
  "event-hub": { en: "Event Hubs Namespace", ko: "이벤트 허브(Event Hubs)" },
  "event-grid-topic": { en: "Event Grid Topic", ko: "이벤트 그리드 토픽" },
  "application-insights": { en: "Application Insights", ko: "애플리케이션 인사이트" },
  "anomaly-alert-rule": { en: "Alert Rule", ko: "경고 규칙" },
  "action-group": { en: "Alert Action Group", ko: "경고 작업 그룹" },
  "data-collection-rule": { en: "Data Collection Rule", ko: "데이터 수집 규칙(DCR)" },
  "diagnostic-settings": { en: "Diagnostic Settings", ko: "진단 설정" },
  "observability.network-monitor": { en: "Network Watcher Monitor", ko: "네트워크 모니터(Network Watcher)" },
  "static-web-app": { en: "Static Web App", ko: "정적 웹앱(Static Web App)" },
  "app-service-plan": { en: "App Service Plan", ko: "앱 서비스 플랜" },
  "managed-certificate": { en: "Managed Certificate", ko: "관리형 인증서" },
  "api-gateway": { en: "API Management Gateway", ko: "API 게이트웨이" },
  "communication-service": { en: "Communication Service", ko: "커뮤니케이션 서비스" },
  "email-service": { en: "Email Communication Service", ko: "이메일 서비스" },
  "email-domain": { en: "Email Domain", ko: "이메일 도메인" },
  "workflow.logic-app": { en: "Logic App Workflow", ko: "로직 앱 워크플로" },
  "managed-sre-agent": { en: "Managed SRE Agent", ko: "관리형 SRE 에이전트" },
  "unclassified-resource": { en: "Unclassified Resource", ko: "미분류 리소스" },
};

export const RULE_LABELS: Readonly<Record<string, BilingualText>> = {
  "compute.vm-scale-set.zone-redundancy": {
    en: "VM Scale Set zone-redundancy policy check",
    ko: "가상 머신 확장 집합(VMSS) 가용 영역 중복성 점검",
  },
  "network.nsg.no-inbound-any-rdp": {
    en: "NSG unrestricted inbound RDP block check",
    ko: "네트워크 보안 그룹(NSG) 전체 대역 RDP 인바운드 차단 점검",
  },
  "resource-group.cost-center-tag.required": {
    en: "Resource group required cost-center tag check",
    ko: "리소스 그룹 비용 센터(cost-center) 필수 태그 누락 점검",
  },
  "resource-group.environment-tag.required": {
    en: "Resource group required environment tag check",
    ko: "리소스 그룹 환경(environment) 필수 태그 누락 점검",
  },
  "resource-group.owner-tag.required": {
    en: "Resource group required owner tag check",
    ko: "리소스 그룹 소유자(owner) 필수 태그 누락 점검",
  },
  "managed-identity.role-assignment.no-privileged-subscription-scope": {
    en: "Managed Identity subscription-scope privileged role check",
    ko: "관리 ID 구독 범위 특권 역할 할당 제한 점검",
  },
  "managed-identity.role-assignment.no-wildcard-action": {
    en: "Managed Identity wildcard-permission role check",
    ko: "관리 ID 와일드카드(*) 권한 역할 할당 제한 점검",
  },
  "subscription.role-assignment.no-standing-privileged-access": {
    en: "Subscription standing privileged access check",
    ko: "구독 상시 특권 역할 할당 제한 점검",
  },
  "network.vnet.ddos-plan.required": {
    en: "Virtual Network DDoS protection plan check",
    ko: "가상 네트워크(VNet) DDoS 보호 계획 연결 점검",
  },
  "compute.vm.environment-tag.required": {
    en: "Virtual Machine required environment tag check",
    ko: "가상 머신(VM) 환경(environment) 필수 태그 누락 점검",
  },
  "compute.vm.managed-identity.assigned": {
    en: "Virtual Machine Managed Identity assignment check",
    ko: "가상 머신(VM) 관리 ID(Managed Identity) 할당 점검",
  },
  "disk.snapshot-policy.required": {
    en: "Managed disk snapshot backup policy check",
    ko: "관리 디스크 스냅샷 백업 정책 구성 점검",
  },
  "object-storage.owner-tag.required": {
    en: "Storage account required owner tag check",
    ko: "스토리지 계정 소유자(owner) 필수 태그 누락 점검",
  },
  "object-storage.cost-center-tag.required": {
    en: "Storage account required cost-center tag check",
    ko: "스토리지 계정 비용 센터(cost-center) 필수 태그 누락 점검",
  },
  "object-storage.diagnostic-settings-required": {
    en: "Storage account diagnostic settings check",
    ko: "스토리지 계정 진단 로그 설정 구성 점검",
  },
  "object-storage.encryption-at-rest.required": {
    en: "Storage account encryption-at-rest check",
    ko: "스토리지 계정 저장 데이터 암호화 구성 점검",
  },
  "object-storage.versioning-enabled": {
    en: "Storage account Blob versioning check",
    ko: "스토리지 계정 Blob 버전 관리 활성화 점검",
  },
  "object-storage.private-endpoint.required": {
    en: "Storage account private endpoint check",
    ko: "스토리지 계정 프라이빗 엔드포인트 연결 점검",
  },
  "object-storage.soft-delete-blob": {
    en: "Storage account Blob soft-delete protection check",
    ko: "스토리지 계정 Blob 일시 삭제(Soft Delete) 보호 점검",
  },
  "secret-store.diagnostic-settings-required": {
    en: "Key Vault diagnostic settings check",
    ko: "비밀 저장소(Key Vault) 진단 로그 설정 구성 점검",
  },
  "secret-store.purge-protection.enabled": {
    en: "Key Vault purge protection check",
    ko: "비밀 저장소(Key Vault) 영구 삭제 보호(Purge Protection) 점검",
  },
  "postgresql-server.high-availability": {
    en: "PostgreSQL server high-availability check",
    ko: "PostgreSQL 서버 고가용성(HA) 구성 점검",
  },
  "postgresql-server.diagnostic-settings-required": {
    en: "PostgreSQL server diagnostic settings check",
    ko: "PostgreSQL 서버 진단 로그 설정 구성 점검",
  },
  "postgresql-server.encryption-at-rest": {
    en: "PostgreSQL server encryption-at-rest check",
    ko: "PostgreSQL 서버 저장 데이터 암호화 점검",
  },
  "kubernetes-node-pool.multi-zone": {
    en: "AKS node pool multi-zone distribution check",
    ko: "AKS 노드 풀 다중 가용 영역(Multi-Zone) 분산 점검",
  },
  "kubernetes-cluster.diagnostic-settings-required": {
    en: "AKS cluster diagnostic settings check",
    ko: "AKS 클러스터 진단 로그 설정 구성 점검",
  },
  "kubernetes-cluster.private-cluster": {
    en: "AKS private cluster configuration check",
    ko: "AKS 프라이빗 클러스터 전환 구성 점검",
  },
  "kubernetes-cluster.network-policy": {
    en: "AKS cluster network policy check",
    ko: "AKS 클러스터 네트워크 정책(Network Policy) 구성 점검",
  },
};

export const ACTION_TYPE_LABELS: Readonly<Record<string, BilingualText>> = {
  "remediate.tag-add": { en: "Add required governance tag", ko: "필수 거버넌스 태그 추가" },
  "remediate.enable-diagnostic-settings": { en: "Enable diagnostic settings", ko: "진단 로그 설정 활성화" },
  "remediate.enable-zone-redundancy": { en: "Enable zone redundancy", ko: "가용 영역 중복성 활성화" },
  "remediate.right-size-role": { en: "Right-size privileged role assignment", ko: "과도한 역할 권한 축소" },
  "remediate.assign-identity": { en: "Assign Managed Identity", ko: "관리 ID(Managed Identity) 할당" },
  "remediate.restrict-network-access": { en: "Restrict public network access", ko: "공용 네트워크 접근 제한" },
  "remediate.enable-encryption": { en: "Enable encryption at rest", ko: "저장 데이터 암호화 활성화" },
  "remediate.enable-backup-protection": { en: "Enable snapshot backup protection", ko: "스냅샷 백업 보호 활성화" },
  "remediate.enable-purge-protection": { en: "Enable Key Vault purge protection", ko: "영구 삭제 보호 활성화" },
};

export const OBSERVATION_DOMAIN_LABELS: Readonly<Record<string, BilingualText>> = {
  "metrics": { en: "Azure Monitor Metrics", ko: "메트릭(Azure Monitor Metrics)" },
  "service-health": { en: "Azure Service Health", ko: "서비스 상태(Service Health)" },
  "activity-log": { en: "Control-Plane Activity Log", ko: "활동 로그(Activity Log)" },
  "recovery": { en: "Backup & Recovery Posture", ko: "백업 및 복구 상태" },
  "logs": { en: "Log Analytics Workspace Logs", ko: "워크스페이스 로그(Log Analytics)" },
  "resource-health": { en: "Resource Health Status", ko: "리소스 상태(Resource Health)" },
  "inventory": { en: "Resource Graph Inventory", ko: "리소스 인벤토리(Resource Graph)" },
  "network-config": { en: "Network Topology & Security", ko: "네트워크 구성 및 보안" },
  "guest-logs": { en: "VM Guest Diagnostics", ko: "가상 머신 게스트 로그" },
  "cost": { en: "Cost & Billing Telemetry", ko: "비용 및 청구 데이터" },
};

export const REASON_LABELS: Readonly<Record<string, BilingualText>> = {
  "inventory_baseline_no_rule_match": {
    en: "No applicable policy rule for this resource type",
    ko: "해당 리소스 유형에 적용할 정책 규칙 없음",
  },
  "no_rule_matches_resource_and_signal_type": {
    en: "No rule matched the resource and signal type",
    ko: "리소스 및 신호 유형과 일치하는 규칙 없음",
  },
  "no_neighbour_found": {
    en: "No similar historical case above T1 threshold",
    ko: "유사도 임계값(T1)을 충족하는 과거 사례 없음",
  },
  "no_rule_denied": {
    en: "All evaluated rules passed without violation",
    ko: "검토한 모든 정책 규칙 준수(위반 없음)",
  },
  "grounded": {
    en: "Policy violation confirmed with grounded evidence",
    ko: "정책 규칙 위반 및 원인 확인됨",
  },
  "approval_expired": {
    en: "Human approval window expired without decision",
    ko: "운영자 승인 대기 기한 만료",
  },
  "event_payload_missing_resource_type": {
    en: "Change event payload omitted resource type",
    ko: "변경 이벤트 페이로드에 리소스 유형 누락",
  },
  "current_evidence": {
    en: "Observer deployment refreshed from current evidence",
    ko: "최신 수집 상태를 반영해 관측기 구성 갱신",
  },
  "t1_deadline_exceeded": {
    en: "T1 similarity evaluation timed out",
    ko: "T1 유사 사례 분석 제한 시간 초과",
  },
};

export const OUTCOME_LABELS: Readonly<Record<string, BilingualText>> = {
  "compliant": { en: "Compliant", ko: "정상 (정책 준수)" },
  "hil": { en: "Awaiting Approval (HIL)", ko: "운영자 승인 대기 (HIL)" },
  "hil_pending": { en: "Awaiting Approval (HIL)", ko: "운영자 승인 대기 (HIL)" },
  "abstain": { en: "Abstained (No Rule)", ko: "보류 (규칙 없음)" },
  "abstained": { en: "Abstained (No Rule)", ko: "보류 (규칙 없음)" },
  "abstained_routing": { en: "Routing Abstained", ko: "라우팅 보류" },
  "retained_for_replay": { en: "Audit Retained", ko: "감사 보존됨" },
  "aggregated": { en: "Aggregated", ko: "집계 기록됨" },
  "timed_out": { en: "Approval Expired", ko: "승인 기한 만료" },
  "degraded": { en: "Source Degraded", ko: "수집 지연" },
  "started": { en: "Started", ko: "점검 시작" },
  "completed": { en: "Completed", ko: "완료" },
  "delivered_all": { en: "Delivered", ko: "전송 완료" },
  "grounded": { en: "Violation Confirmed", ko: "위반 확인됨" },
  "shadow_queued": { en: "Queued (Shadow)", ko: "대기열 유지 (Shadow)" },
  "needs_evidence": { en: "Needs Evidence", ko: "추가 확인 필요" },
  "applied": { en: "Applied", ko: "적용됨" },
  "activated": { en: "Activated", ko: "활성화됨" },
  "hold": { en: "On Hold", ko: "보류됨" },
};

export interface LifecyclePhase {
  readonly key: string;
  readonly label: string;
  readonly iso: string | null;
  readonly gapLabel: string | null;
}

export function lifecycleOf(item: AuditItem): readonly LifecyclePhase[] {
  const raw: readonly (readonly [string, string, string | null])[] = [
    ["sent", "Event sent", entryStr(item, "event_ts")],
    ["received", "Received", entryStr(item, "received_at")],
    ["started", "Work started", entryStr(item, "started_at")],
    ["finished", "Finished", entryStr(item, "finished_at") ?? item.recorded_at],
  ];
  const present = raw.filter((row) => row[2] !== null) as (readonly [string, string, string])[];
  return present.map(([key, label, iso], index) => {
    const previous = index > 0 ? present[index - 1]![2] : null;
    const gap = previous !== null ? milliseconds(iso) - milliseconds(previous) : null;
    return {
      key,
      label,
      iso,
      gapLabel: gap === null ? null : gap <= 0 ? "0s" : `+${fmtDur(gap)}`,
    };
  });
}
