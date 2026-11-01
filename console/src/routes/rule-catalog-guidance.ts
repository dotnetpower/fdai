import { resolveControlReferenceImage } from "./reference-images.catalog";
import type { RuleDetailDto, RuleDto } from "./rule-catalog-types";
import type { GuidanceNode, GuidancePresentation, GuidanceText } from "./wara-guidance.model";

function text(en: string, ko: string): GuidanceText {
  return { en, ko };
}

interface ActiveRuleGuidanceSpec {
  readonly titleKo: string;
  readonly summaryKo: string;
  readonly benefitEn: string;
  readonly benefitKo: string;
  readonly beforeEn: string;
  readonly beforeKo: string;
  readonly afterEn: string;
  readonly afterKo: string;
  readonly verifyEn: string;
  readonly verifyKo: string;
}

export const ACTIVE_RULE_GUIDANCE_SPECS: Readonly<Record<string, ActiveRuleGuidanceSpec>> = {
  "cache.zone-redundant": {
    titleKo: "캐시(Cache) 영역 중복(Zone Redundancy) 구성 필수",
    summaryKo: "단일 가용 영역 장애 시 전체 캐시 데이터가 유실되지 않도록 캐시 인스턴스를 최소 2개 이상의 가용 영역에 분산 배치해야 합니다.",
    benefitEn: "Prevents cache-wide eviction and backend database stampedes during a single availability-zone outage.",
    benefitKo: "단일 가용 영역 장애 발생 시 전체 캐시 증발과 백엔드 데이터베이스 부하 폭주(Stampede)를 방지합니다.",
    beforeEn: "Cache instance runs in a single availability zone (`count(zones) < 2`), creating a single point of failure.",
    beforeKo: "캐시 인스턴스가 단일 가용 영역(`count(zones) < 2`)에만 배치되어 영역 장애 시 서비스 중단 위험에 노출됩니다.",
    afterEn: "Configure the cache across at least two availability zones (`zones` >= 2) via `remediate.enable-zone-redundancy`.",
    afterKo: "`remediate.enable-zone-redundancy` 조치를 통해 캐시 인스턴스를 최소 2개 이상의 가용 영역(`zones` >= 2)에 분산 구성합니다.",
    verifyEn: "Inspect `property.cache.zones` in the latest inventory snapshot and confirm at least two distinct zones are active.",
    verifyKo: "최신 인벤토리 스냅샷에서 `property.cache.zones` 속성을 확인하여 2개 이상의 가용 영역이 활성화되었는지 검증합니다.",
  },
  "compute.vm-scale-set.zone-redundancy": {
    titleKo: "가상 머신 확장 집합(VMSS) 영역 중복 구성 필수",
    summaryKo: "단일 가용 영역 장애 시에도 컴퓨팅 용량을 유지할 수 있도록 compute.vm-scale-set을 최소 2개 이상의 가용 영역에 걸쳐 배치해야 합니다.",
    benefitEn: "Maintains horizontal compute capacity and load-balanced traffic serving when one availability zone fails.",
    benefitKo: "특정 가용 영역에 장애가 발생하더라도 수평 확장 컴퓨팅 용량과 부하 분산 트래픽 처리를 중단 없이 유지합니다.",
    beforeEn: "VM Scale Set is pinned to a single zone or regional non-zonal placement (`count(zones) < 2`).",
    beforeKo: "가상 머신 확장 집합(VMSS)이 단일 영역에 고정되어 있거나 영역 지정 없이 배포되어 있습니다.",
    afterEn: "Span the VM Scale Set across multiple availability zones (`zones` >= 2) with zone-balanced scaling.",
    afterKo: "VM 확장 집합을 2개 이상의 가용 영역(`zones` >= 2)에 분산 배치하고 영역 균형 스케일링을 활성화합니다.",
    verifyEn: "Verify `property.compute.vm-scale-set.zones` lists at least two zones and T0 evaluation returns compliant.",
    verifyKo: "`property.compute.vm-scale-set.zones` 속성에 2개 이상의 영역이 기록되고 T0 평가 결과가 준수(Compliant)인지 확인합니다.",
  },
  "compute.vm.environment-tag.required": {
    titleKo: "가상 머신(VM)에 environment 태그 지정 필수",
    summaryKo: "환경별 수명주기 및 운영 정책이 일관되게 적용되도록 모든 compute.vm 리소스에 environment 태그를 반드시 부여해야 합니다.",
    benefitEn: "Enables deterministic environment classification (prod/staging/dev) for change-safety, patching, and cost policies.",
    benefitKo: "운영·스테이징·개발 환경을 결정론적으로 구분하여 변경 안전성, 패치 일정, 비용 거버넌스 정책을 정확히 적용합니다.",
    beforeEn: "Virtual machine is missing the `environment` tag (`property.compute.vm.tags.required_tag`), leaving its lifecycle tier ambiguous.",
    beforeKo: "가상 머신에 `environment` 태그가 누락되어 해당 리소스의 운영 등급과 수명주기 정책 범위를 식별할 수 없습니다.",
    afterEn: "Apply the standardized `environment` tag via `remediate.tag-add` (`remediation/compute/vm_environment_tag.tftpl`).",
    afterKo: "`remediate.tag-add` 교정 템플릿을 통해 표준화된 `environment` 태그(예: prod, staging, dev)를 부여합니다.",
    verifyEn: "Confirm `property.compute.vm.tags.required_tag` is present and non-empty in the next inventory observation.",
    verifyKo: "다음 인벤토리 관측에서 `property.compute.vm.tags.required_tag` 값이 정상적으로 존재하는지 확인합니다.",
  },
  "compute.vm.managed-identity.assigned": {
    titleKo: "가상 머신(VM)에 관리 ID(Managed Identity) 할당 필수",
    summaryKo: "애플리케이션 설정에 자격 증명이나 비밀값을 하드코딩하지 않도록 compute.vm에 시스템 할당 또는 사용자 할당 관리 ID를 구성해야 합니다.",
    benefitEn: "Eliminates long-lived client secrets on compute hosts by using Entra ID token acquisition via IMDS.",
    benefitKo: "인스턴스 메타데이터 서비스(IMDS) 기반 Entra ID 단기 토큰을 사용하여 호스트 내 정적 자격 증명 유출 위험을 제거합니다.",
    beforeEn: "Virtual machine has no managed identity (`identity_type` is empty or `None`), forcing workloads to store credentials.",
    beforeKo: "가상 머신에 관리 ID(`identity_type`)가 할당되지 않아 애플리케이션이 별도 비밀키나 연결 문자열에 의존합니다.",
    afterEn: "Assign a system- or user-assigned Managed Identity to the VM (`remediate.assign-identity`).",
    afterKo: "`remediate.assign-identity` 조치를 통해 가상 머신에 시스템 할당 또는 사용자 할당 관리 ID를 연결합니다.",
    verifyEn: "Check `property.compute.vm.identity_type` in inventory and verify minimum RBAC scope for the assigned identity.",
    verifyKo: "인벤토리의 `property.compute.vm.identity_type` 속성과 할당된 관리 ID의 최소 권한 RBAC 범위를 검증합니다.",
  },
  "disk.snapshot-policy.required": {
    titleKo: "상태 저장 디스크(Disk) 스냅샷 보호 정책 연결 필수",
    summaryKo: "데이터 손상이나 오작동 발생 시 안전한 복구 지점(Rollback Point)을 확보할 수 있도록 상태를 보유한 디스크에 스냅샷 정책을 등록해야 합니다.",
    benefitEn: "Guarantees a recent point-in-time disk recovery image before maintenance or accidental corruption.",
    benefitKo: "구성 변경 실패나 데이터 손상 발생 시 즉시 되돌릴 수 있는 최신 디스크 복구 지점을 보장합니다.",
    beforeEn: "Managed disk has `snapshot_policy_present == false`, leaving stateful volumes without automated recovery points.",
    beforeKo: "관리 디스크의 `snapshot_policy_present`가 `false`여서 자동화된 스냅샷 복구 지점이 생성되지 않습니다.",
    afterEn: "Enroll the disk in an automated backup/snapshot schedule via `remediate.enable-backup-protection`.",
    afterKo: "`remediate.enable-backup-protection` 조치를 통해 디스크를 자동 스냅샷 및 백업 보호 정책에 등록합니다.",
    verifyEn: "Verify `property.disk.snapshot_policy_present == true` and confirm recent recovery point creation.",
    verifyKo: "`property.disk.snapshot_policy_present == true` 상태와 최근 스냅샷 복구 지점 생성 이력을 확인합니다.",
  },
  "kubernetes-cluster.diagnostic-settings-required": {
    titleKo: "Kubernetes 클러스터 진단 설정(Diagnostic Settings) 활성화 필수",
    summaryKo: "API 서버 감사 로그와 컨트롤러 매니저 로그를 중앙 Log Analytics 워크스페이스로 전송하도록 진단 설정을 구성해야 합니다.",
    benefitEn: "Provides complete control-plane audit trails (`kube-audit`, `kube-controller-manager`) for incident RCA and security forensics.",
    benefitKo: "인시던트 근본 원인 분석(RCA)과 보안 포렌식을 위한 컨트롤 플레인 감사 로그(`kube-audit` 등)를 빠짐없이 확보합니다.",
    beforeEn: "AKS cluster has no diagnostic settings routing control-plane logs to a Log Analytics workspace.",
    beforeKo: "AKS 클러스터에 컨트롤 플레인 진단 로그를 Log Analytics 워크스페이스로 보내는 진단 설정이 없습니다.",
    afterEn: "Attach diagnostic settings forwarding audit and controller logs via `remediate.enable-diagnostic-settings`.",
    afterKo: "`remediate.enable-diagnostic-settings` 조치를 통해 감사 및 컨트롤러 로그를 중앙 워크스페이스로 전송하도록 구성합니다.",
    verifyEn: "Inspect `property.kubernetes-cluster.diagnostic_settings` and confirm log ingestion in the target workspace.",
    verifyKo: "`property.kubernetes-cluster.diagnostic_settings` 속성과 대상 워크스페이스의 로그 수집 상태를 검증합니다.",
  },
  "kubernetes-cluster.network-policy": {
    titleKo: "Kubernetes 클러스터 네트워크 정책(Network Policy) 엔진 활성화 필수",
    summaryKo: "파드 간(Pod-to-Pod) 동서 트래픽을 최소 권한으로 격리·제한할 수 있도록 Calico 또는 Azure 네트워크 정책 엔진을 활성화해야 합니다.",
    benefitEn: "Prevents unrestricted lateral movement between pods across namespaces inside the Kubernetes cluster.",
    benefitKo: "클러스터 내부에서 침해된 파드가 다른 네임스페이스나 워크로드로 수평 이동(Lateral Movement)하는 것을 차단합니다.",
    beforeEn: "Cluster `network_policy` is unset or `none`, allowing any pod to reach any other pod on the cluster network.",
    beforeKo: "클러스터의 `network_policy`가 비활성화되어 모든 파드 간 네트워크 통신이 무제한 허용됩니다.",
    afterEn: "Configure `network_policy` (`azure` or `calico`) on the cluster (`remediate.restrict-network-access`).",
    afterKo: "클러스터에 `azure` 또는 `calico` 네트워크 정책 엔진을 구성하여 파드 간 트래픽 제어를 활성화합니다.",
    verifyEn: "Confirm `property.kubernetes-cluster.network_policy` is set to `azure` or `calico` in the inventory snapshot.",
    verifyKo: "인벤토리 스냅샷에서 `property.kubernetes-cluster.network_policy` 값이 `azure` 또는 `calico`로 설정되었는지 확인합니다.",
  },
  "kubernetes-cluster.private-cluster": {
    titleKo: "Kubernetes 클러스터 프라이빗 API 서버 구성 필수",
    summaryKo: "클러스터 제어 플레인(API 서버)이 공용 인터넷에 노출되지 않고 프라이빗 엔드포인트를 통해서만 접근되도록 구성해야 합니다.",
    benefitEn: "Removes the Kubernetes API server from the public internet attack surface by binding it to a Private Link endpoint.",
    benefitKo: "Kubernetes API 서버를 공용 인터넷 공격 표면에서 완전히 격리하고 Private Link 사설 네트워크로만 접근을 제한합니다.",
    beforeEn: "AKS API server has `private_cluster_enabled != true`, exposing control-plane endpoints publicly.",
    beforeKo: "`private_cluster_enabled`가 `true`가 아니어서 클러스터 API 서버 엔드포인트가 외부 인터넷에 노출됩니다.",
    afterEn: "Enable private cluster mode (`private_cluster_enabled = true`) via `remediate.restrict-network-access`.",
    afterKo: "`remediate.restrict-network-access` 템플릿을 통해 프라이빗 클러스터 모드(`private_cluster_enabled = true`)를 적용합니다.",
    verifyEn: "Verify `property.kubernetes-cluster.private_cluster_enabled == true` and private DNS resolution.",
    verifyKo: "`property.kubernetes-cluster.private_cluster_enabled == true` 여부와 프라이빗 DNS 해석 상태를 검증합니다.",
  },
  "kubernetes-cluster.rbac-enabled": {
    titleKo: "Kubernetes 클러스터 Azure RBAC 통합 권한 제어 활성화 필수",
    summaryKo: "로컬 관리자 정적 자격 증명 대신 Azure RBAC 통합 인증·인가를 사용하여 클러스터 접근 권한을 통제해야 합니다.",
    benefitEn: "Unifies cluster authorization with Entra ID conditional access, PIM elevation, and centralized audit logs.",
    benefitKo: "클러스터 권한 제어를 Entra ID 조건부 액세스, PIM 권한 승격, 중앙 감사 로그와 단일 체계로 통합합니다.",
    beforeEn: "Cluster relies on local static kubeconfig admin credentials with `azure_rbac_enabled != true`.",
    beforeKo: "`azure_rbac_enabled`가 비활성화되어 공유 로컬 관리자 kubeconfig 자격 증명에 의존하고 있습니다.",
    afterEn: "Enable Azure RBAC for Kubernetes Authorization (`azure_rbac_enabled = true`) via `remediate.enable-rbac`.",
    afterKo: "`remediate.enable-rbac` 조치를 통해 Kubernetes 권한 부여용 Azure RBAC 통합(`azure_rbac_enabled = true`)을 활성화합니다.",
    verifyEn: "Check `property.kubernetes-cluster.azure_rbac_enabled == true` in the cluster inventory record.",
    verifyKo: "클러스터 인벤토리 레코드에서 `property.kubernetes-cluster.azure_rbac_enabled == true` 상태를 확인합니다.",
  },
  "kubernetes-node-pool.multi-zone": {
    titleKo: "Kubernetes 노드 풀 다중 가용 영역(Multi-Zone) 배치 필수",
    summaryKo: "단일 가용 영역 장애로 전체 워커 노드 풀이 중단되지 않도록 노드 풀을 최소 2개 이상의 가용 영역에 분산 배치해야 합니다.",
    benefitEn: "Ensures pod scheduling and workload availability survive a datacenter availability-zone failure.",
    benefitKo: "데이터센터 단일 가용 영역 장애 시에도 파드 재스케일링과 워크로드 가용성이 중단 없이 유지되도록 보장합니다.",
    beforeEn: "Node pool is deployed in a single zone or without availability zones (`count(availability_zones) < 2`).",
    beforeKo: "노드 풀이 단일 가용 영역에만 배치되어 있거나 영역 중복 구성(`availability_zones`)이 누락되어 있습니다.",
    afterEn: "Configure the node pool across at least two availability zones (`availability_zones` >= 2) via `remediate.enable-zone-redundancy`.",
    afterKo: "`remediate.enable-zone-redundancy`를 통해 노드 풀을 최소 2개 이상의 가용 영역(`availability_zones` >= 2)에 분산 구성합니다.",
    verifyEn: "Verify `property.kubernetes-node-pool.availability_zones` contains two or more zones and nodes are balanced.",
    verifyKo: "`property.kubernetes-node-pool.availability_zones`에 2개 이상의 영역이 포함되고 노드가 균형 배치되었는지 확인합니다.",
  },
  "llm-endpoint.t2-proposer-unavailable": {
    titleKo: "T2 추론 제안자(Proposer) 모델 엔드포인트 전체 경로 장애 탐지",
    summaryKo: "모든 T2 추론 모델 경로가 실패한 컨트롤 플레인 관측 신호를 감지하며, 자동 변경 없이 인간 개입(HIL) 복구 판단으로 안전하게 전환합니다.",
    benefitEn: "Fails closed toward human review when frontier LLM proposer routes are exhausted or unreachable.",
    benefitKo: "T2 프론티어 모델 경로가 모두 실패했을 때 임의 동작 대신 인간 개입(HIL) 검토 및 경로 전환 절차로 안전하게 폴백합니다.",
    beforeEn: "All configured T2 proposer endpoints emit terminal failure events (`t2_proposer_unavailable`).",
    beforeKo: "구성된 모든 T2 추론 제안자 모델 엔드포인트에서 최종 호출 실패(`t2_proposer_unavailable`)가 관측됩니다.",
    afterEn: "Escalate to HIL operator review and switch to a verified standby proposer route via `ops.switch-t2-proposer-route`.",
    afterKo: "인간 승인(HIL) 검토를 거쳐 `ops.switch-t2-proposer-route` 조치로 검증된 대체 모델 경로로 안전하게 전환합니다.",
    verifyEn: "Confirm `llm-endpoint` health probe recovery and verify T2 cross-check availability before resuming.",
    verifyKo: "`llm-endpoint` 상태 프로브 복구와 T2 교차 검증 가용성을 확인한 뒤 추론 경로를 재개합니다.",
  },
  "managed-identity.role-assignment.no-privileged-subscription-scope": {
    titleKo: "관리 ID에 구독 범위 고권한 역할(Owner/Contributor 등) 부여 금지",
    summaryKo: "단일 워크로드 침해가 구독 전체의 영향 반경으로 확산되지 않도록 관리 ID에 구독 범위의 Owner, Contributor, User Access Administrator 권한 부여를 차단합니다.",
    benefitEn: "Prevents a single compromised workload identity from taking over or deleting every resource in the subscription.",
    benefitKo: "단일 워크로드 관리 ID가 침해되더라도 구독 전체 리소스의 탈취나 삭제(전체 영향 반경 확산)로 이어지는 것을 차단합니다.",
    beforeEn: "A workload Managed Identity holds Owner, Contributor, or User Access Administrator at `/subscriptions/<id>` scope.",
    beforeKo: "워크로드 관리 ID에 구독 전체 범위(`/subscriptions/<id>`)의 Owner, Contributor 등 고권한 역할이 부여되어 있습니다.",
    afterEn: "Right-size the role assignment to the minimum required resource or resource-group scope via `remediate.right-size-role`.",
    afterKo: "`remediate.right-size-role` 조치를 통해 권한 범위를 실제 필요한 리소스 또는 리소스 그룹의 최소 권한 역할로 축소합니다.",
    verifyEn: "Inspect `property.managed-identity.role_assignments` and confirm zero subscription-scoped privileged roles remain.",
    verifyKo: "`property.managed-identity.role_assignments`를 검사하여 구독 범위의 고권한 역할 할당이 완전히 제거되었는지 확인합니다.",
  },
  "managed-identity.role-assignment.no-wildcard-action": {
    titleKo: "관리 ID 역할에 와일드카드(*) 작업 권한 부여 금지",
    summaryKo: "최소 권한 원칙을 위반하고 실제 권한 범위를 불투명하게 만드는 와일드카드(*) 액션 또는 데이터 액션이 포함된 역할 할당을 차단합니다.",
    benefitEn: "Enforces explicit permission declarations so every action a workload identity can perform is auditable.",
    benefitKo: "워크로드 관리 ID가 수행할 수 있는 모든 작업을 명시적으로 제한하여 최소 권한 원칙과 감사 투명성을 보장합니다.",
    beforeEn: "A custom or built-in role assigned to the Managed Identity grants `*` in `actions` or `data_actions`.",
    beforeKo: "관리 ID에 할당된 역할 정의의 `actions` 또는 `data_actions`에 모든 작업을 허용하는 와일드카드(`*`)가 포함되어 있습니다.",
    afterEn: "Replace wildcard role definitions with explicit narrow permission verbs via `remediate.right-size-role`.",
    afterKo: "`remediate.right-size-role` 조치를 통해 와일드카드 역할을 명시적인 최소 권한 작업 목록만 가진 역할로 교체합니다.",
    verifyEn: "Verify no role assignment in `property.managed-identity.role_assignments` contains wildcard actions.",
    verifyKo: "`property.managed-identity.role_assignments`의 모든 역할 할당에 와일드카드(`*`) 권한이 없는지 검증합니다.",
  },
  "network.nsg.no-inbound-any-rdp": {
    titleKo: "NSG에서 전체 소스(Any) 대상 인바운드 RDP(TCP/3389) 허용 금지",
    summaryKo: "무차별 대입 공격(Brute-force) 표면을 제거하기 위해 네트워크 보안 그룹(NSG)에서 임의 소스로부터의 TCP/3389(RDP) 인바운드 허용 규칙을 금지합니다.",
    benefitEn: "Eliminates direct RDP credential-stuffing and remote exploitation vectors on Windows virtual machines.",
    benefitKo: "Windows 가상 머신에 대한 직접적인 RDP 무차별 대입 공격과 원격 익스플로잇 공격 경로를 원천 차단합니다.",
    beforeEn: "NSG contains an inbound Allow rule for destination port 3389 with source `*` or `Any`.",
    beforeKo: "NSG 보안 규칙에 소스 `*` 또는 `Any`로부터 대상 포트 3389(RDP)를 허용하는 인바운드 규칙이 존재합니다.",
    afterEn: "Remove or restrict the public RDP rule via `remediate.restrict-network-access` and use Azure Bastion or Private Link.",
    afterKo: "`remediate.restrict-network-access`로 무제한 RDP 허용 규칙을 제거·제한하고 Azure Bastion 또는 사설 연결을 사용합니다.",
    verifyEn: "Inspect `property.network.nsg.security_rules` and confirm TCP/3389 is denied from untrusted sources.",
    verifyKo: "`property.network.nsg.security_rules`를 확인하여 비신뢰 소스로부터의 TCP/3389 인바운드 허용이 없는지 검증합니다.",
  },
  "network.nsg.no-inbound-any-ssh": {
    titleKo: "NSG에서 전체 소스(Any) 대상 인바운드 SSH(TCP/22) 허용 금지",
    summaryKo: "무차별 대입 공격 표면을 제거하기 위해 네트워크 보안 그룹(NSG)에서 임의 소스로부터의 TCP/22(SSH) 인바운드 허용 규칙을 금지합니다.",
    benefitEn: "Blocks automated botnet scanning and brute-force attacks against Linux SSH management ports.",
    benefitKo: "Linux 관리 포트(SSH TCP/22)를 겨냥한 자동화된 봇넷 스캔과 무차별 대입 공격을 차단합니다.",
    beforeEn: "NSG contains an inbound Allow rule for destination port 22 with source `*` or `Any`.",
    beforeKo: "NSG 보안 규칙에 소스 `*` 또는 `Any`로부터 대상 포트 22(SSH)를 허용하는 인바운드 규칙이 존재합니다.",
    afterEn: "Restrict inbound TCP/22 via `remediate.restrict-network-access` and require Bastion or JIT access.",
    afterKo: "`remediate.restrict-network-access`로 무제한 SSH 허용 규칙을 제거하고 Bastion 또는 JIT 접근만 허용합니다.",
    verifyEn: "Verify `property.network.nsg.security_rules` has no unrestricted inbound allow rule covering port 22.",
    verifyKo: "`property.network.nsg.security_rules`에서 포트 22를 포괄하는 무제한 인바운드 허용 규칙이 없는지 확인합니다.",
  },
  "network.nsg.no-internet-inbound-rdp": {
    titleKo: "NSG에서 인터넷 도달 가능 인바운드 RDP(TCP/3389) 노출 금지",
    summaryKo: "더 높은 우선순위의 명시적 거부 규칙으로 보호되지 않은 상태에서 인터넷(*, Internet, Any, 0.0.0.0/0, ::/0)으로부터 TCP/3389에 도달할 수 있는 NSG 구성을 차단합니다.",
    benefitEn: "Detects effective internet RDP exposure across port ranges, prefix lists, and rule priority ordering.",
    benefitKo: "포트 범위, 접두사 목록, 규칙 우선순위를 종합 분석하여 실제 인터넷에서 도달 가능한 RDP 노출을 정밀하게 차단합니다.",
    beforeEn: "An inbound allow rule exposes TCP/3389 to `Internet`/`0.0.0.0/0` without a lower-priority-number blocking deny rule.",
    beforeKo: "더 낮은 우선순위 번호(더 높은 우선순위)의 차단 규칙 없이 인터넷(`0.0.0.0/0` 등)에서 TCP/3389로 진입 가능한 허용 규칙이 존재합니다.",
    afterEn: "Remove the internet-facing RDP allow rule or insert a higher-priority deny rule via `remediate.restrict-network-access`.",
    afterKo: "`remediate.restrict-network-access`를 통해 인터넷 노출 RDP 허용 규칙을 제거하거나 상위 우선순위 거부 규칙을 적용합니다.",
    verifyEn: "Evaluate effective `property.network.nsg.inbound_security_rules` priorities and confirm TCP/3389 is unreachable from Internet.",
    verifyKo: "`property.network.nsg.inbound_security_rules`의 우선순위 조합을 평가하여 인터넷발 TCP/3389 도달이 불가한지 검증합니다.",
  },
  "network.nsg.no-internet-inbound-ssh": {
    titleKo: "NSG에서 인터넷 도달 가능 인바운드 SSH(TCP/22) 노출 금지",
    summaryKo: "더 높은 우선순위의 명시적 거부 규칙으로 보호되지 않은 상태에서 인터넷(*, Internet, Any, 0.0.0.0/0, ::/0)으로부터 TCP/22에 도달할 수 있는 NSG 구성을 차단합니다.",
    benefitEn: "Detects effective internet SSH exposure across wildcard ports, CIDR lists, and NSG priority rules.",
    benefitKo: "와일드카드 포트, CIDR 목록, NSG 우선순위를 종합 평가하여 실제 인터넷에서 도달 가능한 SSH 노출을 정밀 차단합니다.",
    beforeEn: "An inbound allow rule exposes TCP/22 to `Internet`/`0.0.0.0/0` without a superseding deny rule.",
    beforeKo: "상위 우선순위 거부 규칙 없이 인터넷(`Internet`, `0.0.0.0/0` 등)에서 TCP/22로 진입 가능한 인바운드 허용 규칙이 존재합니다.",
    afterEn: "Block internet inbound TCP/22 via `remediate.restrict-network-access` (`remediation/network/nsg_block_ssh.tftpl`).",
    afterKo: "`remediate.restrict-network-access` 템플릿을 적용하여 인터넷발 TCP/22 인바운드 노출을 차단합니다.",
    verifyEn: "Confirm `property.network.nsg.inbound_security_rules` denies internet traffic to TCP/22.",
    verifyKo: "`property.network.nsg.inbound_security_rules` 평가 결과 인터넷발 TCP/22 트래픽이 거부되는지 검증합니다.",
  },
  "network.vnet.ddos-plan.required": {
    titleKo: "가상 네트워크(VNet)에 DDoS 보호 계획 연결 필수",
    summaryKo: "외부 노출 워크로드를 수용하는 가상 네트워크(network.vnet)를 볼륨 기반 및 프로토콜 DDoS 공격으로부터 보호하기 위해 DDoS 보호 계획을 연결해야 합니다.",
    benefitEn: "Provides adaptive traffic scrubbing and attack telemetry for public-facing virtual networks.",
    benefitKo: "외부 접점 가상 네트워크에 대해 적응형 트래픽 스크러빙과 DDoS 공격 완화 메트릭을 제공합니다.",
    beforeEn: "Virtual network has `ddos_protection_plan_id` unset or empty while hosting internet-facing resources.",
    beforeKo: "가상 네트워크(`network.vnet`)에 `ddos_protection_plan_id`가 연결되지 않아 대용량 DDoS 공격에 취약합니다.",
    afterEn: "Link the virtual network to an Azure DDoS Protection plan via `remediate.restrict-network-access`.",
    afterKo: "`remediate.restrict-network-access` 조치를 통해 가상 네트워크에 Azure DDoS 보호 계획을 연결합니다.",
    verifyEn: "Check `property.network.vnet.ddos_protection_plan_id` is populated in the latest VNet inventory record.",
    verifyKo: "최신 VNet 인벤토리 레코드에서 `property.network.vnet.ddos_protection_plan_id`가 유효하게 설정되었는지 확인합니다.",
  },
  "object-storage.cost-center-tag.required": {
    titleKo: "오브젝트 스토리지에 cost_center 비용 귀속 태그 지정 필수",
    summaryKo: "스토리지 사용 비용을 책임 부서 및 비용 센터에 정확히 배분할 수 있도록 모든 object-storage 계정에 cost_center 태그를 부여해야 합니다.",
    benefitEn: "Ensures every storage account's capacity and egress charges map to an accountable financial cost center.",
    benefitKo: "모든 스토리지 계정의 저장 용량 및 전송 요금을 책임 비용 센터(Cost Center)에 누락 없이 귀속시킵니다.",
    beforeEn: "Storage account is missing the `cost_center` tag (`property.object-storage.tags.required_tag`).",
    beforeKo: "오브젝트 스토리지 계정에 `cost_center` 태그가 누락되어 비용 귀속 부서를 식별할 수 없습니다.",
    afterEn: "Add the `cost_center` tag via `remediate.tag-add` (`remediation/storage/cost_center_tag.tftpl`).",
    afterKo: "`remediate.tag-add` 교정 템플릿을 통해 스토리지 계정에 `cost_center` 태그를 부여합니다.",
    verifyEn: "Verify `property.object-storage.tags.required_tag` is present on the storage account.",
    verifyKo: "스토리지 계정 인벤토리에서 `property.object-storage.tags.required_tag` 값을 확인합니다.",
  },
  "object-storage.diagnostic-settings-required": {
    titleKo: "오브젝트 스토리지 진단 설정(Diagnostic Settings) 활성화 필수",
    summaryKo: "스토리지 및 Blob 데이터 플레인 접근·변경 이벤트를 감사할 수 있도록 Log Analytics 워크스페이스로 진단 로그를 전송해야 합니다.",
    benefitEn: "Captures storage read/write/delete audit trails for data-exfiltration detection and compliance.",
    benefitKo: "데이터 유출 탐지 및 규정 준수 감사를 위해 스토리지 읽기·쓰기·삭제 진단 로그를 중앙 워크스페이스에 보존합니다.",
    beforeEn: "Storage account has no diagnostic settings forwarding blob/storage logs to Log Analytics.",
    beforeKo: "오브젝트 스토리지 계정에 Blob 및 스토리지 로그를 Log Analytics로 전송하는 진단 설정이 없습니다.",
    afterEn: "Configure storage diagnostic settings via `remediate.enable-diagnostic-settings`.",
    afterKo: "`remediate.enable-diagnostic-settings` 조치를 통해 스토리지 진단 로그 전송을 활성화합니다.",
    verifyEn: "Confirm `property.object-storage.diagnostic_settings` includes an active workspace destination.",
    verifyKo: "`property.object-storage.diagnostic_settings`에 활성 Log Analytics 대상이 포함되었는지 검증합니다.",
  },
  "object-storage.encryption-at-rest.required": {
    titleKo: "오브젝트 스토리지 저장 데이터 인프라 이중 암호화 필수",
    summaryKo: "저장 데이터의 다계층 암호화 보호를 위해 오브젝트 스토리지 계정에 인프라 암호화(Infrastructure Encryption)를 활성화해야 합니다.",
    benefitEn: "Protects data at rest with two independent encryption layers (service-level and infrastructure-level).",
    benefitKo: "서비스 수준 암호화와 물리 인프라 수준 암호화의 이중 계층으로 저장 데이터를 안전하게 보호합니다.",
    beforeEn: "Storage account has `infrastructure_encryption_enabled != true`.",
    beforeKo: "오브젝트 스토리지 계정에 인프라 이중 암호화(`infrastructure_encryption_enabled`)가 비활성화되어 있습니다.",
    afterEn: "Enable infrastructure encryption at rest via `remediate.enable-encryption`.",
    afterKo: "`remediate.enable-encryption` 조치를 통해 오브젝트 스토리지 저장 데이터 인프라 암호화를 활성화합니다.",
    verifyEn: "Verify `property.object-storage.infrastructure_encryption_enabled == true` in inventory.",
    verifyKo: "인벤토리에서 `property.object-storage.infrastructure_encryption_enabled == true` 상태를 확인합니다.",
  },
  "object-storage.https-only.required": {
    titleKo: "오브젝트 스토리지 HTTPS 전용 암호화 전송 강제 필수",
    summaryKo: "전송 구간 평문 노출을 방지하기 위해 HTTP 요청을 거부하고 보안 HTTPS 트래픽만 허용하도록 구성해야 합니다.",
    benefitEn: "Prevents man-in-the-middle interception and credential/data sniffing over plaintext HTTP.",
    benefitKo: "평문 HTTP 통신을 통한 중간자 공격(MITM)과 SAS 토큰·데이터 도청 위험을 원천 차단합니다.",
    beforeEn: "Storage account allows plaintext HTTP requests (`enable_https_traffic_only == false`).",
    beforeKo: "오브젝트 스토리지 계정이 평문 HTTP 요청을 허용(`enable_https_traffic_only == false`)하고 있습니다.",
    afterEn: "Enforce `enable_https_traffic_only = true` via `remediate.set-tls-policy`.",
    afterKo: "`remediate.set-tls-policy` 조치를 통해 HTTPS 전용 트래픽 강제(`enable_https_traffic_only = true`)를 설정합니다.",
    verifyEn: "Confirm `property.object-storage.enable_https_traffic_only == true` and HTTP requests are rejected.",
    verifyKo: "`property.object-storage.enable_https_traffic_only == true` 설정과 평문 HTTP 요청 거부를 확인합니다.",
  },
  "object-storage.min-tls-version": {
    titleKo: "오브젝트 스토리지 최소 TLS 1.2 버전 강제 필수",
    summaryKo: "취약한 구형 암호화 프로토콜(TLS 1.0/1.1) 연결을 차단하고 최소 TLS 1.2 이상으로만 클라이언트 통신을 허용해야 합니다.",
    benefitEn: "Blocks protocol-downgrade attacks and weak cipher negotiations on storage endpoints.",
    benefitKo: "스토리지 엔드포인트에서 취약한 구형 TLS 1.0/1.1 프로토콜 다운그레이드 협상을 차단합니다.",
    beforeEn: "Storage account `min_tls_version` is set to `TLS1_0` or `TLS1_1`.",
    beforeKo: "오브젝트 스토리지의 최소 TLS 버전(`min_tls_version`)이 구형 `TLS1_0` 또는 `TLS1_1`로 허용되어 있습니다.",
    afterEn: "Set `min_tls_version = TLS1_2` via `remediate.set-tls-policy` (`remediation/storage/min_tls_1_2.tftpl`).",
    afterKo: "`remediate.set-tls-policy` 템플릿을 통해 최소 TLS 버전을 `TLS1_2` 이상으로 상향 설정합니다.",
    verifyEn: "Verify `property.object-storage.min_tls_version` equals `TLS1_2` in the inventory snapshot.",
    verifyKo: "인벤토리 스냅샷에서 `property.object-storage.min_tls_version` 값이 `TLS1_2`인지 검증합니다.",
  },
  "object-storage.owner-tag.required": {
    titleKo: "오브젝트 스토리지에 owner 책임자 태그 지정 필수",
    summaryKo: "자산 소유권과 보안·운영 책임 주체를 명확히 추적할 수 있도록 모든 object-storage 계정에 owner 태그를 지정해야 합니다.",
    benefitEn: "Maps every storage account to an accountable owner for incident escalation and access governance.",
    benefitKo: "모든 스토리지 계정에 보안 인시던트 대응 및 접근 검토를 담당할 책임 주체(Owner)를 명확히 연결합니다.",
    beforeEn: "Storage account lacks the required `owner` tag (`property.object-storage.tags.required_tag`).",
    beforeKo: "오브젝트 스토리지 계정에 필수 `owner` 태그가 누락되어 관리 책임자를 즉시 확인할 수 없습니다.",
    afterEn: "Apply the `owner` tag via `remediate.tag-add` (`remediation/storage/owner_tag.tftpl`).",
    afterKo: "`remediate.tag-add` 템플릿을 통해 스토리지 계정에 `owner` 태그를 부여합니다.",
    verifyEn: "Confirm `property.object-storage.tags.required_tag` is populated in inventory.",
    verifyKo: "인벤토리에서 `property.object-storage.tags.required_tag` 태그 값이 기록되었는지 확인합니다.",
  },
  "object-storage.private-endpoint.required": {
    titleKo: "오브젝트 스토리지 프라이빗 엔드포인트 연결 및 공용 네트워크 차단 필수",
    summaryKo: "데이터를 저장하는 오브젝트 스토리지 계정에 공용 네트워크 접근을 차단하고 프라이빗 엔드포인트(Private Endpoint)를 통해서만 접근하도록 구성해야 합니다.",
    benefitEn: "Isolates storage data-plane traffic onto private VNet addressing and blocks internet exfiltration.",
    benefitKo: "스토리지 데이터 플레인 트래픽을 사설 VNet 내부로 격리하고 공용 인터넷을 통한 데이터 접근을 차단합니다.",
    beforeEn: "Storage account has `public_network_access_enabled == true` or no attached `private_endpoints`.",
    beforeKo: "오브젝트 스토리지에 공용 네트워크 접근이 열려 있거나 연결된 프라이빗 엔드포인트가 없습니다.",
    afterEn: "Disable public network access and attach a Private Endpoint via `remediate.restrict-network-access`.",
    afterKo: "`remediate.restrict-network-access`를 통해 공용 네트워크 접근을 끄고 프라이빗 엔드포인트를 구성합니다.",
    verifyEn: "Verify `public_network_access_enabled == false` and non-empty `private_endpoints` in inventory.",
    verifyKo: "인벤토리에서 `public_network_access_enabled == false` 및 `private_endpoints` 연결 상태를 확인합니다.",
  },
  "object-storage.public-access.deny": {
    titleKo: "오브젝트 스토리지 익명 공용 액세스(Public Access) 차단 필수",
    summaryKo: "비인증 사용자의 컨테이너·Blob 열람 및 데이터 유출을 방지하기 위해 오브젝트 스토리지의 공용 액세스 허용 속성을 비활성화해야 합니다.",
    benefitEn: "Prevents anonymous public read access to containers and blobs even if a container ACL is misconfigured.",
    benefitKo: "개별 컨테이너 ACL이 잘못 설정되더라도 계정 수준에서 익명 공용 Blob 열람과 유출을 원천 차단합니다.",
    beforeEn: "Storage account has `public_access == true` (`allowBlobPublicAccess` enabled).",
    beforeKo: "스토리지 계정의 익명 공용 액세스(`public_access == true`)가 허용되어 비인증 노출 위험이 있습니다.",
    afterEn: "Disable anonymous blob public access via `remediate.disable-public-access`.",
    afterKo: "`remediate.disable-public-access` 조치를 통해 계정 수준의 익명 공용 액세스를 비활성화합니다.",
    verifyEn: "Confirm `property.object-storage.public_access == false` in the next inventory evaluation.",
    verifyKo: "다음 인벤토리 평가에서 `property.object-storage.public_access == false` 상태를 검증합니다.",
  },
  "object-storage.shared-key-access.disabled": {
    titleKo: "오브젝트 스토리지 공유 키(Shared Key) 인증 비활성화 필수",
    summaryKo: "장기 정적 스토리지 계정 키 대신 관리 ID 기반 Entra ID RBAC 인증만 사용하도록 공유 키 접근을 비활성화해야 합니다.",
    benefitEn: "Eliminates full-account master key bypass and forces per-principal Entra ID RBAC and audit logging.",
    benefitKo: "계정 전체 권한을 가진 마스터 공유 키 우회를 차단하고 주체별 Entra ID RBAC 인가 및 감사 추적을 강제합니다.",
    beforeEn: "Storage account permits Shared Key / SAS master key authentication (`allow_shared_key_access == true`).",
    beforeKo: "스토리지 계정이 공유 마스터 키 인증(`allow_shared_key_access == true`)을 허용하고 있습니다.",
    afterEn: "Set `allow_shared_key_access = false` via `remediate.enable-rbac` after migrating callers to Managed Identity.",
    afterKo: "호출 워크로드를 관리 ID로 전환한 후 `remediate.enable-rbac` 조치로 공유 키 접근(`allow_shared_key_access = false`)을 차단합니다.",
    verifyEn: "Check `property.object-storage.allow_shared_key_access == false` in inventory.",
    verifyKo: "인벤토리에서 `property.object-storage.allow_shared_key_access == false` 상태를 검증합니다.",
  },
  "object-storage.soft-delete-blob": {
    titleKo: "오브젝트 스토리지 Blob 소프트 삭제(Soft Delete) 활성화 필수",
    summaryKo: "실수나 악의적인 삭제 발생 시 보존 기간 내에 데이터를 즉시 복원할 수 있도록 Blob 소프트 삭제 정책을 활성화해야 합니다.",
    benefitEn: "Retains deleted blobs in a recoverable soft-deleted state throughout the configured retention window.",
    benefitKo: "삭제된 Blob 객체를 지정된 보존 기간 동안 소프트 삭제 상태로 유지하여 무손실 복구를 보장합니다.",
    beforeEn: "Storage account has `blob_soft_delete_enabled != true`, making blob deletions immediately permanent.",
    beforeKo: "Blob 소프트 삭제(`blob_soft_delete_enabled`)가 비활성화되어 삭제 시 데이터가 즉시 영구 소실됩니다.",
    afterEn: "Enable blob soft delete with retention policy via `remediate.enable-backup-protection`.",
    afterKo: "`remediate.enable-backup-protection` 조치를 통해 Blob 소프트 삭제 및 보존 기간 정책을 활성화합니다.",
    verifyEn: "Verify `property.object-storage.blob_soft_delete_enabled == true` in the storage inventory snapshot.",
    verifyKo: "스토리지 인벤토리 스냅샷에서 `property.object-storage.blob_soft_delete_enabled == true` 여부를 확인합니다.",
  },
  "object-storage.versioning-enabled": {
    titleKo: "오브젝트 스토리지 Blob 버전 관리(Versioning) 활성화 필수",
    summaryKo: "덮어쓰기나 변조 발생 시 이전 버전을 복구할 수 있도록 오브젝트 스토리지의 Blob 자동 버전 관리를 활성화해야 합니다.",
    benefitEn: "Preserves immutable prior versions on every overwrite so corrupted or tampered objects can be restored.",
    benefitKo: "객체 덮어쓰기나 변조 발생 시마다 이전 버전을 자동으로 보존하여 시점 복구 능력을 제공합니다.",
    beforeEn: "Storage account has `blob_versioning_enabled != true`, so overwrites destroy previous object state.",
    beforeKo: "Blob 버전 관리(`blob_versioning_enabled`)가 꺼져 있어 덮어쓰기 시 이전 데이터가 즉시 유실됩니다.",
    afterEn: "Enable automatic blob versioning via `remediate.enable-backup-protection`.",
    afterKo: "`remediate.enable-backup-protection` 조치를 통해 Blob 자동 버전 관리를 활성화합니다.",
    verifyEn: "Confirm `property.object-storage.blob_versioning_enabled == true` in inventory.",
    verifyKo: "인벤토리에서 `property.object-storage.blob_versioning_enabled == true` 설정을 확인합니다.",
  },
  "ops.change-summary": {
    titleKo: "리소스 그룹 변경 요약 보고서(Change Summary) 발행 규칙",
    summaryKo: "리소스 그룹 범위 이벤트에 change-summary 요청 마커가 포함된 경우 감사 로그로부터 변경 요약 마크다운 보고서를 결정론적으로 생성합니다.",
    benefitEn: "Automates deterministic audit-backed change summary reports on operator or scheduled requests.",
    benefitKo: "운영자 요청이나 예약 주기에 따라 감사 원장 기반의 변경 요약 보고서를 결정론적으로 생성·발행합니다.",
    beforeEn: "An operator or scheduled workflow emits a resource-group event with `request_kind == 'change-summary'`.",
    beforeKo: "운영자 또는 예약 작업이 `request_kind == 'change-summary'` 마커가 포함된 리소스 그룹 이벤트를 발행합니다.",
    afterEn: "Dispatch `ops.publish-change-summary` to compile and publish the audited Markdown change report.",
    afterKo: "`ops.publish-change-summary` ActionType을 실행하여 감사 로그 기반 변경 요약 보고서를 생성·게시합니다.",
    verifyEn: "Verify the generated `ChangeSummary` artifact and Saga audit receipt for the target resource group.",
    verifyKo: "생성된 `ChangeSummary` 산출물과 대상 리소스 그룹의 Saga 감사 증적을 확인합니다.",
  },
  "postgresql-server.diagnostic-settings-required": {
    titleKo: "PostgreSQL 서버 진단 설정(Diagnostic Settings) 활성화 필수",
    summaryKo: "데이터베이스 연결, 쿼리, 오류 로그를 중앙 Log Analytics 워크스페이스로 수집하도록 PostgreSQL 진단 설정을 구성해야 합니다.",
    benefitEn: "Provides database log-plane visibility for query performance troubleshooting and security auditing.",
    benefitKo: "데이터베이스 연결·쿼리·오류 로그를 중앙 수집하여 장애 분석과 보안 감사를 위한 가시성을 확보합니다.",
    beforeEn: "PostgreSQL server has no diagnostic settings forwarding logs to a Log Analytics workspace.",
    beforeKo: "PostgreSQL 서버에 로그를 중앙 Log Analytics 워크스페이스로 전송하는 진단 설정이 구성되어 있지 않습니다.",
    afterEn: "Enable PostgreSQL diagnostic settings via `remediate.enable-diagnostic-settings`.",
    afterKo: "`remediate.enable-diagnostic-settings` 조치를 통해 PostgreSQL 진단 로그 전송 설정을 활성화합니다.",
    verifyEn: "Confirm `property.postgresql-server.diagnostic_settings` is non-empty in inventory.",
    verifyKo: "인벤토리에서 `property.postgresql-server.diagnostic_settings` 설정이 유효한지 검증합니다.",
  },
  "postgresql-server.encryption-at-rest": {
    titleKo: "PostgreSQL 서버 저장 데이터 암호화(Encryption at Rest) 활성화 필수",
    summaryKo: "데이터베이스 스토리지 및 백업 스냅샷이 암호화 상태로만 보관되도록 PostgreSQL 저장 데이터 암호화를 활성화해야 합니다.",
    benefitEn: "Protects relational data files, WAL logs, and backups from unauthorized media access.",
    benefitKo: "데이터 파일, 트랜잭션 로그(WAL), 백업 스냅샷을 저장 상태에서 암호화하여 물리·스토리지 유출을 방지합니다.",
    beforeEn: "PostgreSQL server reports `encryption_at_rest_enabled == false`.",
    beforeKo: "PostgreSQL 서버의 저장 데이터 암호화(`encryption_at_rest_enabled`)가 `false`로 관측됩니다.",
    afterEn: "Enforce storage encryption at rest on the PostgreSQL server via `remediate.enable-encryption`.",
    afterKo: "`remediate.enable-encryption` 조치를 통해 PostgreSQL 저장 데이터 암호화를 활성화합니다.",
    verifyEn: "Verify `property.postgresql-server.encryption_at_rest_enabled == true` in inventory.",
    verifyKo: "인벤토리에서 `property.postgresql-server.encryption_at_rest_enabled == true` 여부를 확인합니다.",
  },
  "postgresql-server.high-availability": {
    titleKo: "PostgreSQL 서버 영역 중복 고가용성(Zone-Redundant HA) 구성 필수",
    summaryKo: "단일 가용 영역 장애 시 운영자 개입 없이 자동 장애 조치(Failover)될 수 있도록 PostgreSQL 서버를 영역 중복 HA 모드로 구성해야 합니다.",
    benefitEn: "Provides synchronous standby replication across availability zones with automatic sub-minute failover.",
    benefitKo: "가용 영역 간 동기식 대기 복제본을 유지하여 영역 장애 시 운영자 개입 없이 즉시 자동 장애 조치를 수행합니다.",
    beforeEn: "PostgreSQL server runs with `ha_mode != 'ZoneRedundant'` (disabled or single-zone HA).",
    beforeKo: "PostgreSQL 서버의 고가용성 모드(`ha_mode`)가 `ZoneRedundant`가 아닌 단일 인스턴스 또는 단일 영역 상태입니다.",
    afterEn: "Configure `ha_mode = 'ZoneRedundant'` via `remediate.enable-zone-redundancy`.",
    afterKo: "`remediate.enable-zone-redundancy` 조치를 통해 PostgreSQL 고가용성 모드를 `ZoneRedundant`로 구성합니다.",
    verifyEn: "Check `property.postgresql-server.ha_mode == 'ZoneRedundant'` and standby health.",
    verifyKo: "`property.postgresql-server.ha_mode == 'ZoneRedundant'` 설정과 대기 서버 정상 상태를 검증합니다.",
  },
  "postgresql-server.point-in-time-restore": {
    titleKo: "PostgreSQL 서버 시점 복원(PITR) 최소 백업 보존 기간 확보 필수",
    summaryKo: "우발적인 데이터 변경이나 손상 후 특정 시점으로 복구할 수 있도록 최소 기준 일수(기본 7일 이상)의 백업 보존 기간을 유지해야 합니다.",
    benefitEn: "Ensures WAL and snapshot retention spans at least 7 days for fine-grained point-in-time recovery.",
    benefitKo: "최소 7일 이상의 백업 및 로그 보존 주기를 유지하여 데이터 손상 시 원하는 시점으로 정밀 복원할 수 있습니다.",
    beforeEn: "PostgreSQL `backup_retention_days` is shorter than the required minimum window (default 7 days).",
    beforeKo: "PostgreSQL 백업 보존 일수(`backup_retention_days`)가 최소 요구 기준(기본 7일)보다 짧게 설정되어 있습니다.",
    afterEn: "Increase `backup_retention_days` to at least 7 days via `remediate.enable-backup-protection`.",
    afterKo: "`remediate.enable-backup-protection` 조치를 통해 백업 보존 일수(`backup_retention_days`)를 최소 기준 이상으로 상향합니다.",
    verifyEn: "Confirm `property.postgresql-server.backup_retention_days >= 7` in inventory.",
    verifyKo: "인벤토리에서 `property.postgresql-server.backup_retention_days` 값이 기준 일수 이상인지 확인합니다.",
  },
  "postgresql-server.ssl-enforcement": {
    titleKo: "PostgreSQL 서버 SSL/TLS 암호화 연결 강제 필수",
    summaryKo: "클라이언트와 데이터베이스 간 평문 트래픽 노출을 차단하기 위해 PostgreSQL 서버에서 SSL/TLS 연결을 강제해야 합니다.",
    benefitEn: "Prevents credential and query result interception on database network paths.",
    benefitKo: "데이터베이스 네트워크 경로에서 자격 증명과 쿼리 결과가 평문으로 도청되는 것을 방지합니다.",
    beforeEn: "PostgreSQL server allows unencrypted client connections (`ssl_enforcement != 'Enabled'`).",
    beforeKo: "PostgreSQL 서버에 SSL 연결 강제(`ssl_enforcement`)가 비활성화되어 평문 접속이 가능합니다.",
    afterEn: "Enforce SSL/TLS connections (`ssl_enforcement = 'Enabled'`) via `remediate.enable-encryption`.",
    afterKo: "`remediate.enable-encryption` 조치를 통해 PostgreSQL 서버의 SSL/TLS 연결 강제를 활성화합니다.",
    verifyEn: "Verify `property.postgresql-server.ssl_enforcement == 'Enabled'` in inventory.",
    verifyKo: "인벤토리에서 `property.postgresql-server.ssl_enforcement`가 활성화 상태인지 검증합니다.",
  },
  "resource-group.cost-center-tag.required": {
    titleKo: "리소스 그룹에 cost_center 비용 귀속 태그 지정 필수",
    summaryKo: "하위 리소스 비용을 책임 조직에 정확히 귀속하고 추적할 수 있도록 모든 resource-group에 cost_center 태그를 부여해야 합니다.",
    benefitEn: "Establishes container-level FinOps cost attribution for all child resources in the resource group.",
    benefitKo: "리소스 그룹 단위에서 하위 리소스 비용의 재무 귀속 기준(FinOps Cost Attribution)을 확립합니다.",
    beforeEn: "Resource group is missing the `cost_center` tag (`property.resource-group.tags.required_tag`).",
    beforeKo: "리소스 그룹에 `cost_center` 태그가 지정되지 않아 비용 귀속 조직을 식별할 수 없습니다.",
    afterEn: "Apply the `cost_center` tag to the resource group via `remediate.tag-add`.",
    afterKo: "`remediate.tag-add` 조치를 통해 리소스 그룹에 표준 `cost_center` 태그를 추가합니다.",
    verifyEn: "Confirm `property.resource-group.tags.required_tag` is present on the resource group.",
    verifyKo: "리소스 그룹 인벤토리에서 `property.resource-group.tags.required_tag` 존재 여부를 확인합니다.",
  },
  "resource-group.environment-tag.required": {
    titleKo: "리소스 그룹에 environment 환경 분류 태그 지정 필수",
    summaryKo: "운영(prod), 스테이징(staging), 개발(dev) 등 환경별 정책이 정확히 적용되도록 모든 resource-group에 environment 태그를 부여해야 합니다.",
    benefitEn: "Scopes environment-specific governance, approval gates, and alerting rules across the resource group.",
    benefitKo: "리소스 그룹 전체에 환경별 거버넌스, 승인 게이트, 경보 기준이 일관되게 적용되도록 보장합니다.",
    beforeEn: "Resource group lacks the `environment` tag (`property.resource-group.tags.required_tag`).",
    beforeKo: "리소스 그룹에 `environment` 태그가 없어 운영·개발 환경 구분이 불명확합니다.",
    afterEn: "Set the `environment` tag on the resource group via `remediate.tag-add`.",
    afterKo: "`remediate.tag-add` 조치를 통해 리소스 그룹에 `environment` 태그를 부여합니다.",
    verifyEn: "Verify `property.resource-group.tags.required_tag` is set on the resource group.",
    verifyKo: "인벤토리에서 리소스 그룹의 `environment` 태그 설정을 검증합니다.",
  },
  "resource-group.owner-tag.required": {
    titleKo: "리소스 그룹에 owner 책임자 태그 지정 필수",
    summaryKo: "리소스 그룹 단위의 운영·보안 책임 주체를 즉시 식별할 수 있도록 모든 resource-group에 owner 태그를 부여해야 합니다.",
    benefitEn: "Identifies the accountable team or steward for every resource group during incidents and reviews.",
    benefitKo: "인시던트 발생 및 정기 보안 검토 시 각 리소스 그룹의 책임 팀·담당자를 즉시 식별할 수 있습니다.",
    beforeEn: "Resource group is missing the `owner` tag (`property.resource-group.tags.required_tag`).",
    beforeKo: "리소스 그룹에 `owner` 태그가 누락되어 책임 담당자가 지정되어 있지 않습니다.",
    afterEn: "Assign the `owner` tag on the resource group via `remediate.tag-add`.",
    afterKo: "`remediate.tag-add` 조치를 통해 리소스 그룹에 `owner` 태그를 지정합니다.",
    verifyEn: "Confirm `property.resource-group.tags.required_tag` is non-empty in inventory.",
    verifyKo: "인벤토리에서 리소스 그룹의 `owner` 태그 값을 확인합니다.",
  },
  "resource-group.role-assignment.owner-count-within-limit": {
    titleKo: "리소스 그룹 범위 Owner(소유자) 역할 할당 인원 상한 준수",
    summaryKo: "과도한 고권한 계정 확산을 방지하고 책임 추적성을 유지하기 위해 리소스 그룹 범위의 Owner 역할 보유 주체 수를 허용 상한(기본 3명) 이하로 제한합니다.",
    benefitEn: "Prevents privilege sprawl and maintains clear administrative accountability at resource-group scope.",
    benefitKo: "리소스 그룹 범위에서 최고 권한(Owner)의 무분별한 확산을 막고 명확한 관리 책임성을 유지합니다.",
    beforeEn: "More than `max_owner_count` (default 3) principals hold the Owner role on the resource group.",
    beforeKo: "리소스 그룹에 허용 상한(`max_owner_count`, 기본 3명)을 초과하는 주체에게 Owner 역할이 부여되어 있습니다.",
    afterEn: "Reduce standing Owner assignments to <= `max_owner_count` via `remediate.right-size-role`.",
    afterKo: "`remediate.right-size-role` 조치를 통해 불필요한 Owner 할당을 최소 권한 역할로 축소하여 상한 이하로 유지합니다.",
    verifyEn: "Inspect `property.resource-group.role_assignments` and confirm Owner count <= `max_owner_count`.",
    verifyKo: "`property.resource-group.role_assignments`에서 Owner 역할 보유 주체 수가 상한 이하인지 검증합니다.",
  },
  "secret-store.diagnostic-settings-required": {
    titleKo: "비밀 저장소(Key Vault) 감사 진단 설정 활성화 필수",
    summaryKo: "비밀값, 키, 인증서의 모든 조회·수정 이벤트를 추적할 수 있도록 secret-store의 AuditEvent 로그를 Log Analytics로 전송해야 합니다.",
    benefitEn: "Ensures every secret, key, and certificate access or mutation is recorded in an immutable audit workspace.",
    benefitKo: "모든 비밀값·암호화 키·인증서 조회 및 변경 이력을 중앙 감사 워크스페이스에 보존하여 침해 여부를 추적합니다.",
    beforeEn: "Key Vault (`secret-store`) has no diagnostic settings routing `AuditEvent` logs to Log Analytics.",
    beforeKo: "비밀 저장소(`secret-store`)에 `AuditEvent` 감사 로그를 Log Analytics로 전송하는 진단 설정이 없습니다.",
    afterEn: "Configure `AuditEvent` diagnostic forwarding via `remediate.enable-diagnostic-settings`.",
    afterKo: "`remediate.enable-diagnostic-settings`를 통해 `AuditEvent` 진단 로그 전송을 활성화합니다.",
    verifyEn: "Confirm `property.secret-store.diagnostic_settings` routes `AuditEvent` to an active workspace.",
    verifyKo: "`property.secret-store.diagnostic_settings`에서 `AuditEvent` 워크스페이스 전송 설정을 확인합니다.",
  },
  "secret-store.public-network-access.disabled": {
    titleKo: "비밀 저장소(Key Vault) 공용 네트워크 접근 비활성화 필수",
    summaryKo: "공용 인터넷으로부터의 비밀 저장소 접근을 차단하고 프라이빗 엔드포인트 또는 신뢰할 수 있는 플랫폼 우회 경로만 허용해야 합니다.",
    benefitEn: "Isolates cryptographic keys and secrets from public internet probing and token-replay attempts.",
    benefitKo: "공용 인터넷에서의 비밀 저장소 접근 시도와 탈취된 토큰을 이용한 외부 유출을 차단합니다.",
    beforeEn: "Secret store has `public_network_access_enabled == true`, accepting public internet requests.",
    beforeKo: "비밀 저장소에 공용 네트워크 접근(`public_network_access_enabled == true`)이 허용되어 있습니다.",
    afterEn: "Disable public network access on the secret store via `remediate.restrict-network-access`.",
    afterKo: "`remediate.restrict-network-access` 조치를 통해 비밀 저장소의 공용 네트워크 접근을 비활성화합니다.",
    verifyEn: "Verify `property.secret-store.public_network_access_enabled == false` in inventory.",
    verifyKo: "인벤토리에서 `property.secret-store.public_network_access_enabled == false` 상태를 확인합니다.",
  },
  "secret-store.purge-protection.enabled": {
    titleKo: "비밀 저장소(Key Vault) 영구 삭제 방지(Purge Protection) 활성화 필수",
    summaryKo: "보존 기간 내에 소프트 삭제된 비밀값이나 암호화 키가 강제로 영구 파기되지 않도록 영구 삭제 방지(Purge Protection)를 활성화해야 합니다.",
    benefitEn: "Protects against ransomware or malicious insiders permanently destroying encryption keys and secrets.",
    benefitKo: "랜섬웨어나 악의적인 내부자가 소프트 삭제된 암호화 키·비밀값을 강제로 영구 파기하는 것을 방지합니다.",
    beforeEn: "Secret store has `purge_protection_enabled != true`, allowing immediate permanent purge of deleted secrets.",
    beforeKo: "영구 삭제 방지(`purge_protection_enabled`)가 비활성화되어 삭제된 비밀값이 보존 기간 중 영구 파기될 수 있습니다.",
    afterEn: "Enable purge protection (`purge_protection_enabled = true`) via HIL-gated `remediate.enable-purge-protection`.",
    afterKo: "HIL 승인을 거치는 `remediate.enable-purge-protection` 조치로 영구 삭제 방지(`purge_protection_enabled = true`)를 활성화합니다.",
    verifyEn: "Confirm `property.secret-store.purge_protection_enabled == true` in inventory.",
    verifyKo: "인벤토리에서 `property.secret-store.purge_protection_enabled == true` 설정을 검증합니다.",
  },
  "secret-store.rbac-authorization.enabled": {
    titleKo: "비밀 저장소(Key Vault) Azure RBAC 권한 모델 활성화 필수",
    summaryKo: "세분화된 권한 제어와 일관된 감사가 어려운 레거시 액세스 정책 대신 Azure RBAC 기반 권한 부여 모델을 사용해야 합니다.",
    benefitEn: "Enables per-secret/key least-privilege RBAC, PIM just-in-time access, and unified governance.",
    benefitKo: "개별 비밀값·키 단위의 세분화된 최소 권한 RBAC 제어와 PIM 적시 권한 부여를 가능하게 합니다.",
    beforeEn: "Secret store uses legacy vault access policies (`rbac_authorization_enabled != true`).",
    beforeKo: "비밀 저장소가 레거시 자격 증명 모음 액세스 정책(`rbac_authorization_enabled != true`)을 사용하고 있습니다.",
    afterEn: "Enable Azure RBAC authorization (`rbac_authorization_enabled = true`) via `remediate.enable-rbac`.",
    afterKo: "`remediate.enable-rbac` 조치를 통해 비밀 저장소의 Azure RBAC 권한 부여 모델을 활성화합니다.",
    verifyEn: "Verify `property.secret-store.rbac_authorization_enabled == true` in inventory.",
    verifyKo: "인벤토리에서 `property.secret-store.rbac_authorization_enabled == true` 상태를 확인합니다.",
  },
  "secret-store.rotation-overdue": {
    titleKo: "비밀 저장소(Key Vault) 비밀값 최대 교체 주기(Rotation) 초과 탐지",
    summaryKo: "생성 후 경과 일수가 허용 임계값(기본 90일)을 초과한 비밀값을 탐지하고 위험 게이트를 거쳐 안전한 비밀값 교체(remediate.rotate-secret)를 제안합니다.",
    benefitEn: "Limits the exposure window of compromised or leaked credentials by enforcing periodic secret rotation.",
    benefitKo: "장기 미교체 비밀값의 노출 기간을 제한하고 정기적인 자격 증명 교체(Rotation) 주기를 강제합니다.",
    beforeEn: "Secret `age_days` exceeds `parameters.max_age_days` (default 90 days).",
    beforeKo: "비밀값의 생성 후 경과 일수(`age_days`)가 최대 허용 주기(`max_age_days`, 기본 90일)를 초과했습니다.",
    afterEn: "Rotate the overdue secret and update dependent consumers via `remediate.rotate-secret`.",
    afterKo: "`remediate.rotate-secret` 조치를 통해 만료된 비밀값을 새 버전으로 교체하고 연동 구성을 갱신합니다.",
    verifyEn: "Confirm `property.secret-store.age_days <= max_age_days` after secret rotation.",
    verifyKo: "비밀값 교체 후 인벤토리에서 `property.secret-store.age_days`가 허용 주기 이내인지 확인합니다.",
  },
  "secret-store.soft-delete.enabled": {
    titleKo: "비밀 저장소(Key Vault) 소프트 삭제(Soft Delete) 활성화 필수",
    summaryKo: "실수나 침해로 삭제된 비밀값·키를 보존 기간 동안 안전하게 복구할 수 있도록 소프트 삭제 기능을 활성화해야 합니다.",
    benefitEn: "Ensures accidentally deleted secrets, keys, and certificates remain recoverable during the retention window.",
    benefitKo: "실수로 삭제된 비밀값, 암호화 키, 인증서를 보존 기간 내에 데이터 손실 없이 복원할 수 있도록 보장합니다.",
    beforeEn: "Secret store has `soft_delete_enabled != true`.",
    beforeKo: "비밀 저장소에 소프트 삭제(`soft_delete_enabled`)가 비활성화되어 있습니다.",
    afterEn: "Enable soft delete (`soft_delete_enabled = true`) via `remediate.enable-backup-protection`.",
    afterKo: "`remediate.enable-backup-protection` 조치를 통해 비밀 저장소 소프트 삭제를 활성화합니다.",
    verifyEn: "Verify `property.secret-store.soft_delete_enabled == true` in inventory.",
    verifyKo: "인벤토리에서 `property.secret-store.soft_delete_enabled == true` 설정을 확인합니다.",
  },
  "sql-database.audit-enabled": {
    titleKo: "SQL 데이터베이스 보안 감사(Auditing) 활성화 필수",
    summaryKo: "관리자 작업과 데이터 접근 이력을 포렌식 및 규정 준수 목적으로 추적할 수 있도록 sql-database 감사를 활성화하고 로그 워크스페이스에 연결해야 합니다.",
    benefitEn: "Records database authentication, schema changes, and sensitive queries for security investigation.",
    benefitKo: "데이터베이스 인증, 스키마 변경, 민감 데이터 조회 활동을 기록하여 보안 조사 및 감사 추적성을 확보합니다.",
    beforeEn: "SQL database has `audit_enabled != true`.",
    beforeKo: "SQL 데이터베이스의 보안 감사(`audit_enabled`)가 비활성화되어 있습니다.",
    afterEn: "Enable SQL auditing to Log Analytics via `remediate.enable-diagnostic-settings`.",
    afterKo: "`remediate.enable-diagnostic-settings` 조치를 통해 SQL 데이터베이스 감사를 활성화하고 워크스페이스에 연결합니다.",
    verifyEn: "Confirm `property.sql-database.audit_enabled == true` in inventory.",
    verifyKo: "인벤토리에서 `property.sql-database.audit_enabled == true` 상태를 검증합니다.",
  },
  "sql-database.diagnostic-settings-required": {
    titleKo: "SQL 데이터베이스 진단 설정(Diagnostic Settings) 활성화 필수",
    summaryKo: "SQL 데이터베이스의 감사 및 성능 메트릭 로그를 중앙 Log Analytics 워크스페이스로 수집하도록 진단 설정을 구성해야 합니다.",
    benefitEn: "Streams deadlock, timeout, resource-utilization, and audit telemetry to the central observability workspace.",
    benefitKo: "데드락, 타임아웃, 리소스 포화도 및 감사 원격 분석 데이터를 중앙 관측성 워크스페이스로 실시간 수집합니다.",
    beforeEn: "SQL database has no diagnostic settings configured (`diagnostic_settings` is empty).",
    beforeKo: "SQL 데이터베이스에 중앙 로그 워크스페이스로 연결된 진단 설정(`diagnostic_settings`)이 없습니다.",
    afterEn: "Attach diagnostic settings to the SQL database via `remediate.enable-diagnostic-settings`.",
    afterKo: "`remediate.enable-diagnostic-settings` 조치를 통해 SQL 데이터베이스 진단 설정을 구성합니다.",
    verifyEn: "Verify `property.sql-database.diagnostic_settings` is populated in inventory.",
    verifyKo: "인벤토리에서 `property.sql-database.diagnostic_settings` 설정이 유효한지 확인합니다.",
  },
  "sql-database.geo-redundant-backup": {
    titleKo: "SQL 데이터베이스 지역 중복 백업(Geo-Redundant Backup) 구성 필수",
    summaryKo: "주 리전 전체 장애 시에도 시점 복원(PITR) 백업 데이터를 보호할 수 있도록 지역 중복 백업 스토리지(GRS/RA-GRS)를 사용해야 합니다.",
    benefitEn: "Preserves database backup recovery points in a paired secondary region during a regional disaster.",
    benefitKo: "주 리전 전체 재해 발생 시에도 쌍으로 연결된 보조 리전에서 데이터베이스 백업을 안전하게 복원할 수 있습니다.",
    beforeEn: "SQL database uses locally or zone-only redundant backup storage (`geo_redundant_backup_enabled != true`).",
    beforeKo: "SQL 데이터베이스의 지역 중복 백업(`geo_redundant_backup_enabled`)이 비활성화되어 리전 장애 시 백업 유실 위험이 있습니다.",
    afterEn: "Enable geo-redundant backup storage (`geo_redundant_backup_enabled = true`) via `remediate.enable-backup-protection`.",
    afterKo: "`remediate.enable-backup-protection` 조치를 통해 지역 중복 백업 스토리지를 활성화합니다.",
    verifyEn: "Confirm `property.sql-database.geo_redundant_backup_enabled == true` in inventory.",
    verifyKo: "인벤토리에서 `property.sql-database.geo_redundant_backup_enabled == true` 상태를 확인합니다.",
  },
  "sql-database.tde-required": {
    titleKo: "SQL 데이터베이스 투명한 데이터 암호화(TDE) 활성화 필수",
    summaryKo: "데이터베이스 파일과 백업을 저장 상태에서 암호화하기 위해 TDE(Transparent Data Encryption)를 반드시 활성화해야 합니다.",
    benefitEn: "Encrypts SQL database data, log, and backup files at rest in real time without application changes.",
    benefitKo: "애플리케이션 변경 없이 SQL 데이터베이스 파일, 트랜잭션 로그, 백업을 실시간으로 저장 암호화합니다.",
    beforeEn: "SQL database reports `tde_enabled == false`, leaving database files unencrypted at rest.",
    beforeKo: "SQL 데이터베이스의 투명한 데이터 암호화(`tde_enabled == false`)가 꺼져 있어 데이터 파일이 평문으로 저장됩니다.",
    afterEn: "Enable Transparent Data Encryption (`tde_enabled = true`) via `remediate.enable-tde`.",
    afterKo: "`remediate.enable-tde` 조치를 통해 투명한 데이터 암호화(`tde_enabled = true`)를 즉시 활성화합니다.",
    verifyEn: "Verify `property.sql-database.tde_enabled == true` in the SQL database inventory record.",
    verifyKo: "SQL 데이터베이스 인벤토리 레코드에서 `property.sql-database.tde_enabled == true` 상태를 검증합니다.",
  },
  "sql-database.zone-redundant": {
    titleKo: "SQL 데이터베이스 영역 중복(Zone Redundant) 구성 필수",
    summaryKo: "단일 가용 영역 장애 시 데이터 손실 없이 자동 전환되도록 sql-database를 영역 중복 구성으로 실행해야 합니다.",
    benefitEn: "Replicates SQL database compute and storage across availability zones for zero-data-loss failover.",
    benefitKo: "SQL 데이터베이스 컴퓨팅과 스토리지를 여러 가용 영역에 복제하여 영역 장애 시 무손실 자동 전환을 제공합니다.",
    beforeEn: "SQL database runs with `zone_redundant != true`.",
    beforeKo: "SQL 데이터베이스가 단일 영역 구성(`zone_redundant != true`)으로 실행되고 있습니다.",
    afterEn: "Enable `zone_redundant = true` on the SQL database via `remediate.enable-zone-redundancy`.",
    afterKo: "`remediate.enable-zone-redundancy` 조치를 통해 SQL 데이터베이스 영역 중복(`zone_redundant = true`)을 활성화합니다.",
    verifyEn: "Confirm `property.sql-database.zone_redundant == true` in inventory.",
    verifyKo: "인벤토리에서 `property.sql-database.zone_redundant == true` 여부를 확인합니다.",
  },
  "subscription.role-assignment.no-guest-privileged": {
    titleKo: "구독 범위에서 외부 게스트(Guest) 주체에 고권한 역할 부여 금지",
    summaryKo: "테넌트 수명주기 통제 밖에 있는 외부 게스트 계정이 구독 전체의 지속적인 권한 상승 경로가 되지 않도록 구독 범위 고권한 역할(Owner, Contributor 등) 할당을 차단합니다.",
    benefitEn: "Prevents external B2B guest identities from holding subscription-wide administrative control.",
    benefitKo: "외부 테넌트(B2B Guest) 계정이 구독 전체의 관리자 권한을 보유하여 발생하는 침해 및 권한 남용 위험을 차단합니다.",
    beforeEn: "A guest principal (`principal_type == 'Guest'` or external user) holds Owner/Contributor at subscription scope.",
    beforeKo: "외부 게스트(Guest) 주체에 구독 범위의 Owner, Contributor, User Access Administrator 등 고권한 역할이 할당되어 있습니다.",
    afterEn: "Remove or scope down the guest privileged role assignment via `remediate.right-size-role`.",
    afterKo: "`remediate.right-size-role` 조치를 통해 외부 게스트 계정의 구독 범위 고권한 역할을 회수하거나 최소 권한으로 축소합니다.",
    verifyEn: "Inspect `property.subscription.role_assignments` and confirm zero guest principals hold privileged roles.",
    verifyKo: "`property.subscription.role_assignments`를 검사하여 고권한 역할을 보유한 외부 게스트 주체가 0명인지 확인합니다.",
  },
  "subscription.role-assignment.no-standing-privileged-access": {
    titleKo: "구독 범위 고권한 역할의 상시(Standing) 할당 금지 및 JIT(PIM) 전환 필수",
    summaryKo: "상시 활성화된 관리자 공격 표면을 제거하기 위해 구독 범위 고권한 역할은 영구(Standing) 할당이 아닌 적시(Just-In-Time, PIM) 적격 권한으로만 부여해야 합니다.",
    benefitEn: "Eliminates permanent standing administrative access in favor of time-bounded, audited PIM activation.",
    benefitKo: "상시 활성화된 영구 관리자 권한을 제거하고 시간 제한 및 승인 감사가 적용되는 PIM 적시(JIT) 활성화로 전환합니다.",
    beforeEn: "A privileged subscription-scoped role assignment is marked permanent (`standing == true` or missing JIT flag).",
    beforeKo: "구독 범위의 고권한 역할 할당이 시간 제한 없는 상시(Standing) 활성 권한으로 부여되어 있습니다.",
    afterEn: "Convert standing privileged role assignments to PIM eligible-only access via `remediate.right-size-role`.",
    afterKo: "`remediate.right-size-role` 조치를 통해 상시 고권한 할당을 PIM 적격(Eligible) JIT 권한으로 전환합니다.",
    verifyEn: "Verify all privileged assignments in `property.subscription.role_assignments` are JIT/eligible rather than standing.",
    verifyKo: "`property.subscription.role_assignments`의 모든 고권한 역할이 상시(Standing)가 아닌 JIT 적격 상태인지 검증합니다.",
  },
};

const COLLECTED_POLICY_PHRASES_KO: readonly (readonly [RegExp, string])[] = [
  [/should use a customer-managed key/i, "고객 관리형 키(CMK) 사용 필요"],
  [/should use customer-managed keys/i, "고객 관리형 키(CMK) 사용 필요"],
  [/infrastructure encryption/i, "인프라 이중 암호화 활성화 필요"],
  [/double encryption/i, "이중 암호화 사용 필요"],
  [/should use private link/i, "Private Link 사설 연결 사용 필요"],
  [/should use private endpoints/i, "프라이빗 엔드포인트 사용 필요"],
  [/private endpoint connections should be enabled/i, "프라이빗 엔드포인트 연결 활성화 필요"],
  [/should disable public network access/i, "공용 네트워크 접근 비활성화 필요"],
  [/public network access should be disabled/i, "공용 네트워크 접근 비활성화 필요"],
  [/should not have a public ip/i, "공용 IP 주소 할당 금지"],
  [/should use a virtual network/i, "가상 네트워크(VNet) 통합 필요"],
  [/should be associated with a data collection rule/i, "데이터 수집 규칙(DCR) 연결 필요"],
  [/should have diagnostic settings/i, "진단 설정 활성화 필요"],
  [/resource logs should be enabled/i, "리소스 진단 로그 활성화 필요"],
  [/audit logs should be enabled/i, "감사 로그 활성화 필요"],
  [/should have firewall rules/i, "방화벽 규칙 구성 필요"],
  [/should use managed identity/i, "관리 ID(Managed Identity) 사용 필요"],
  [/system-assigned managed identity/i, "시스템 할당 관리 ID 활성화 필요"],
  [/local authentication methods should be disabled/i, "로컬 인증 방식 비활성화 필요"],
  [/shared key access should be disabled/i, "공유 키 접근 비활성화 필요"],
  [/anonymous access should be disabled/i, "익명 접근 비활성화 필요"],
  [/should be zone redundant/i, "영역 중복(Zone Redundant) 구성 필요"],
  [/minimum tls version/i, "최소 TLS 버전(TLS 1.2+) 강제 필요"],
  [/latest tls version/i, "최신 TLS 버전(TLS 1.2+) 사용 필요"],
  [/secure transfer to storage accounts/i, "보안 전송(HTTPS 전용) 활성화 필요"],
  [/only be accessible over https/i, "HTTPS 보안 연결만 허용 필요"],
  [/soft delete should be enabled/i, "일시 삭제(Soft Delete) 보호 활성화 필요"],
  [/purge protection should be enabled/i, "영구 삭제 방지(Purge Protection) 활성화 필요"],
  [/azure backup should be enabled/i, "Azure Backup 백업 보호 활성화 필요"],
  [/ddos protection standard/i, "DDoS 네트워크 보호 표준 플랜 활성화 필요"],
  [/microsoft defender for/i, "Microsoft Defender 클라우드 워크로드 보호 활성화 필요"],
  [/vulnerability assessment should be enabled/i, "취약점 평가 활성화 필요"],
  [/disk encryption should be applied/i, "디스크 암호화 적용 필요"],
  [/flow logs should be enabled/i, "NSG 흐름 로그 활성화 필요"],
];

const COLLECTED_KUBE_BENCH_PHRASES_KO: readonly (readonly [RegExp, string])[] = [
  [/anonymous-auth/i, "익명 인증 비활성화"],
  [/authorization-mode/i, "인가 모드(RBAC/Node) 설정 준수"],
  [/client-ca-file/i, "클라이언트 CA 인증서 설정 준수"],
  [/audit-log/i, "감사 로그(Audit Log) 보존·경로 설정 준수"],
  [/profiling/i, "프로파일링 비활성화"],
  [/read-only-port/i, "읽기 전용 포트 비활성화"],
  [/protect-kernel-defaults/i, "커널 기본값 보호 활성화"],
  [/kubelet-https/i, "Kubelet HTTPS 암호화 통신 강제"],
  [/file permissions/i, "파일 권한 설정 준수"],
  [/file ownership/i, "파일 소유권(root:root) 설정 준수"],
  [/admission control plugin/i, "어드미션 컨트롤 플러그인 활성화"],
  [/minimize the admission of/i, "컨테이너 고위험 권한 허용 최소화"],
];

export function ruleDisplayTitle(
  rule: Pick<RuleDto, "id" | "title" | "title_ko">,
  locale: string,
): string {
  const baseTitle = rule.title?.trim() || rule.id;
  if (locale !== "ko") return baseTitle;
  if (rule.title_ko?.trim()) return rule.title_ko.trim();
  const activeSpec = ACTIVE_RULE_GUIDANCE_SPECS[rule.id];
  if (activeSpec) return activeSpec.titleKo;
  if (rule.id.startsWith("kube-bench.")) {
    const parts = rule.id.split(".");
    const ruleset = parts.slice(1, 3).join(".");
    const slug = (parts[parts.length - 1] ?? "").replace(/-(?:automated|manual|m|a)$/, "").replace(/-/g, " ");
    for (const [pattern, koPhrase] of COLLECTED_KUBE_BENCH_PHRASES_KO) {
      if (pattern.test(slug) || pattern.test(baseTitle)) {
        return `CIS ${ruleset} Kubernetes ${koPhrase} (${slug || baseTitle})`;
      }
    }
    return `CIS ${ruleset} Kubernetes 보안 점검: ${slug || baseTitle}`;
  }
  if (rule.id.startsWith("azure-builtin.")) {
    const lifecyclePrefix = /\bdeprecated\b/i.test(baseTitle)
      ? "[사용 중단됨(Deprecated)] "
      : /^\[preview\]:/i.test(baseTitle)
        ? "[미리 보기(Preview)] "
        : "";
    for (const [pattern, koPhrase] of COLLECTED_POLICY_PHRASES_KO) {
      if (pattern.test(baseTitle)) {
        return `[Azure Policy] ${lifecyclePrefix}${baseTitle} - ${koPhrase}`;
      }
    }
    return `[Azure Policy] ${lifecyclePrefix}${baseTitle}`;
  }
  return baseTitle;
}

export function buildRuleGuidance(data: RuleDetailDto): GuidancePresentation {
  const activeSpec = ACTIVE_RULE_GUIDANCE_SPECS[data.id];
  const expDetails = data.explanation.details ?? {};
  const detailTitleKo = typeof expDetails["title_ko"] === "string" ? expDetails["title_ko"] : undefined;
  const detailDescKo = typeof expDetails["description_ko"] === "string" ? expDetails["description_ko"] : undefined;

  const titleEn = data.explanation.title?.trim() || data.id;
  const titleKo = detailTitleKo || activeSpec?.titleKo || ruleDisplayTitle(data, "ko");
  const title = text(titleEn, titleKo);

  const summaryEn = data.explanation.description?.trim()
    || `Evaluates ${data.check_logic.kind} check (${data.check_logic.reference}) on ${data.resource_type} (${data.category}, ${data.severity} severity) and links violations to ${data.remediates}.`;
  const summaryKo = detailDescKo
    || activeSpec?.summaryKo
    || `대상 리소스(${data.resource_type})에 대해 ${data.check_logic.kind} 검사(${data.check_logic.reference})를 수행하여 ${titleKo} 준수 여부를 평가하고 위반 시 ${data.remediates} 조치를 제안합니다.`;

  const benefits = activeSpec
    ? text(activeSpec.benefitEn, activeSpec.benefitKo)
    : text(
        `Detects ${data.category} drift on ${data.resource_type} deterministically and bounds remediation through ${data.remediates}.`,
        `${data.resource_type} 리소스의 ${data.category} 기준 이탈을 결정론적으로 탐지하고 ${data.remediates} 조치를 통해 위험을 완화합니다.`,
      );

  const before = activeSpec
    ? text(activeSpec.beforeEn, activeSpec.beforeKo)
    : text(
        `${data.resource_type} violates ${data.id} (${titleEn}), triggering a ${data.severity}-severity finding under ${data.check_logic.reference}.`,
        `${data.resource_type} 리소스 구성이 '${titleKo}' 기준을 충족하지 못하여 ${data.check_logic.reference} 평가에서 ${data.severity} 심각도 위반이 발생합니다.`,
      );

  const after = activeSpec
    ? text(activeSpec.afterEn, activeSpec.afterKo)
    : text(
        `Bring ${data.resource_type} into compliance with ${data.id} using ${data.remediates} (${data.remediation.template_ref}).`,
        `${data.remediates}(${data.remediation.template_ref}) 교정 절차를 통해 ${data.resource_type} 구성을 '${titleKo}' 기준에 맞게 전환합니다.`,
      );

  const verify = activeSpec
    ? text(activeSpec.verifyEn, activeSpec.verifyKo)
    : text(
        `Re-evaluate ${data.check_logic.reference} on the next complete inventory generation and confirm zero active violations for ${data.id}.`,
        `다음 완전한 인벤토리 세대에서 ${data.check_logic.reference} 검사를 다시 평가하여 ${data.id} 위반 리소스가 0개인지 검증합니다.`,
      );

  const evaluatesList = Array.isArray(data.applies_to?.["resource_types"])
    ? (data.applies_to["resource_types"] as unknown[]).map(String).join(", ")
    : data.resource_type;
  const evaluatedProps = typeof expDetails["evaluated_properties"] === "string"
    ? expDetails["evaluated_properties"]
    : data.check_logic.reference;
  const triggerSignals = typeof expDetails["trigger_signals"] === "string"
    ? expDetails["trigger_signals"]
    : "resource.configuration.observed";

  const nodes: readonly GuidanceNode[] = [
    {
      id: "subject",
      label: text(`Target resource (${data.resource_type})`, `평가 대상 리소스 (${data.resource_type})`),
      detail: before,
      role: "subject",
    },
    {
      id: "configuration",
      label: text("Compliant configuration target", "준수 목표 구성 (After)"),
      detail: after,
      role: "configuration",
    },
    {
      id: "evidence",
      label: text(`T0 check (${data.check_logic.kind})`, `T0 결정론적 검사 (${data.check_logic.kind})`),
      detail: verify,
      role: "evidence",
    },
    {
      id: "remediation",
      label: text(`Governed action (${data.remediates})`, `교정 ActionType (${data.remediates})`),
      detail: text(
        `Evaluates ${evaluatedProps} on signal ${triggerSignals}; proposes ${data.remediates} (${data.remediation.template_ref}) through the risk and approval gates.`,
        `신호(${triggerSignals}) 수신 시 ${evaluatedProps} 속성을 평가하며, 위험 게이트와 승인 절차를 거쳐 ${data.remediates}(${data.remediation.template_ref}) 교정을 제안합니다.`,
      ),
      role: "dependency",
    },
    {
      id: "outcome",
      label: text("Verified compliance outcome", "위반 해소 및 보호 목표 달성"),
      detail: benefits,
      role: "outcome",
    },
  ];

  const referenceImage = resolveControlReferenceImage("rule", data.id, data.resource_type);
  const sourceUrl = data.provenance.source_url?.startsWith("https://")
    ? data.provenance.source_url
    : "https://learn.microsoft.com/en-us/azure/governance/policy/overview";

  return {
    title,
    summary: text(summaryEn, summaryKo),
    benefits,
    rationale: text(
      `Rule ${data.id} (v${data.version}, origin: ${data.origin}, source: ${data.source}) applies to ${evaluatesList}. Check reference: ${data.check_logic.reference}. Paired ActionType: ${data.remediates}.`,
      `규칙 ${data.id}(버전 ${data.version}, 계층: ${data.origin}, 출처: ${data.source})는 ${evaluatesList} 리소스에 적용됩니다. 검사 참조는 ${data.check_logic.reference}이며 교정 ActionType은 ${data.remediates}입니다.`,
    ),
    applicability: [
      text(
        `Applies to canonical resource type ${data.resource_type} (${evaluatesList}) when evaluated by ${data.origin === "active" ? "the active T0 deterministic engine" : "collected reference catalog analysis"}.`,
        `${data.origin === "active" ? "활성 T0 결정론적 엔진" : "수집된 참조 코퍼스 분석"}에서 정규 리소스 유형 ${data.resource_type}(${evaluatesList})을 평가할 때 적용됩니다.`,
      ),
      text(
        "Missing or unobserved resource properties abstain to unknown/HIL rather than assuming compliance.",
        "필수 리소스 속성이 관측되지 않거나 누락된 경우 준수로 가정하지 않고 판단 보류(Abstain) 및 인간 검토(HIL)로 처리합니다.",
      ),
    ],
    configuration: {
      before: [
        before,
        text(
          `Check reference: ${data.check_logic.reference} (${data.check_logic.kind}, severity: ${data.severity}).`,
          `검사 참조: ${data.check_logic.reference} (유형: ${data.check_logic.kind}, 심각도: ${data.severity}).`,
        ),
      ],
      after: [
        after,
        text(
          `Remediation template: ${data.remediation.template_ref} -> ActionType ${data.remediates}.`,
          `교정 템플릿: ${data.remediation.template_ref} -> 교정 ActionType ${data.remediates}.`,
        ),
      ],
    },
    implementation_steps: [
      text(
        `Inspect affected ${data.resource_type} resources and confirm ${data.id} activation membership and scope.`,
        `영향받는 ${data.resource_type} 리소스 목록과 ${data.id} 규칙의 T0 활성화 멤버십 및 적용 범위를 확인합니다.`,
      ),
      after,
      text(
        `Submit the change through ${data.remediates} with dry-run preview, blast-radius check, rollback plan, and required human approval.`,
        `사전 시뮬레이션(Dry-run), 영향 반경 확인, 롤백 계획, 필수 인간 승인을 거쳐 ${data.remediates} 교정 변경을 적용합니다.`,
      ),
    ],
    verification_steps: [
      verify,
      ...(typeof data.parameters["kube_bench_audit"] === "string" && data.parameters["kube_bench_audit"].trim()
        ? [
            text(
              `Run CIS audit command on the node/control-plane: \`${data.parameters["kube_bench_audit"].trim()}\`.`,
              `대상 노드·컨트롤 플레인에서 CIS 감사 명령어(\`${data.parameters["kube_bench_audit"].trim()}\`)를 실행하여 설정값을 직접 검증합니다.`,
            ),
          ]
        : typeof data.parameters["azure_policy_effect_default"] === "string" && data.parameters["azure_policy_effect_default"].trim()
          ? [
              text(
                `Verify Azure Policy assignment default effect (\`${data.parameters["azure_policy_effect_default"].trim()}\`) and compliance state on \`${data.resource_type}\`.`,
                `\`${data.resource_type}\` 범위에서 Azure Policy 할당 기본 효과(\`${data.parameters["azure_policy_effect_default"].trim()}\`) 및 정책 준수 상태를 확인합니다.`,
              ),
            ]
          : []),
      text(
        `Confirm Forseti records a compliant terminal outcome for ${data.id} on the updated inventory generation.`,
        `갱신된 인벤토리 세대에서 Forseti가 ${data.id} 규칙에 대해 준수(Compliant) 최종 판정을 기록하는지 확인합니다.`,
      ),
      text(
        "Check citing WAF/MCSB framework controls if this rule supplies supporting or decisive rule evidence.",
        "이 규칙을 인용하는 WAF/MCSB 프레임워크 통제 항목에서 규칙 커버리지 수치가 정상 갱신되었는지 확인합니다.",
      ),
    ],
    cautions: [
      text(
        "Rule catalog presence and T0 activation membership never bypass the risk gate, promotion gate, or human approval.",
        "규칙 카탈로그 등록이나 T0 활성화 멤버십만으로 위험 게이트, 승격 게이트, 인간 승인 절차를 우회하여 자동 실행하지 않습니다.",
      ),
      text(
        data.origin === "collected"
          ? "Collected corpus rules are reference definitions imported from upstream sources and must be reviewed and promoted before active T0 enforcement."
          : "Even for active catalog rules, state-changing remediations remain governed by the ActionType's shadow/enforce mode.",
        data.origin === "collected"
          ? "수집된 코퍼스(Collected) 규칙은 업스트림에서 가져온 참조 정의이므로 T0에서 실행하려면 선별 검토 및 승격 절차를 거쳐야 합니다."
          : "선별된 활성(Active) 규칙이라 하더라도 실제 리소스 변경 조치는 연결된 ActionType의 Shadow/Enforce 모드 및 안전 게이트 통제를 받습니다.",
      ),
    ],
    ...(referenceImage ? { reference_image: referenceImage } : {}),
    diagram: {
      id: `rule.${data.id.replace(/[^a-zA-Z0-9_.-]/g, "-")}`,
      kind: `rule-${data.category}-flow`,
      title,
      description: text(
        "Illustrative T0 rule detection, evaluation and governed remediation flow; not an observed installation result.",
        "실제 환경 관측 결과가 아닌, T0 탐지 규칙의 조건 평가·위반 판정 및 통제된 교정 조치 흐름 도식입니다.",
      ),
      nodes,
      edges: [
        {
          from: "subject",
          to: "configuration",
          label: text("Require compliant state", "준수 목표 구성 요구"),
          style: "solid",
        },
        {
          from: "subject",
          to: "remediation",
          label: text("Trigger remediation candidate", "위반 시 교정 후보 연결"),
          style: "solid",
        },
        {
          from: "configuration",
          to: "evidence",
          label: text("Evaluate property predicate", "T0 정책 조건식 평가"),
          style: "solid",
        },
        {
          from: "remediation",
          to: "evidence",
          label: text("Verify post-change state", "교정 후 상태 독립 검증"),
          style: "dashed",
        },
        {
          from: "evidence",
          to: "outcome",
          label: text("Confirm compliance receipt", "준수 증적 확정 (가정 금지)"),
          style: "dashed",
        },
      ],
    },
    sources: [
      {
        kind: "learn",
        url: sourceUrl,
        label: text(
          `Rule provenance source (${data.source}, license: ${data.provenance.license})`,
          `규칙 원본 출처 (${data.source}, 라이선스: ${data.provenance.license})`,
        ),
      },
    ],
  };
}
