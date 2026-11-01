"""Bilingual (EN/KO) titles, explanations, and RAG passages for active and collected Rules."""
# ruff: noqa: E501

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

ACTIVE_RULE_KO: dict[str, tuple[str, str]] = {
    "cache.zone-redundant": (
        "캐시(Cache) 영역 중복(Zone Redundancy) 구성 필수",
        "단일 가용 영역 장애 시 전체 캐시 데이터가 유실되지 않도록 캐시 인스턴스를 최소 2개 이상의 가용 영역에 분산 배치해야 합니다.",
    ),
    "compute.vm-scale-set.zone-redundancy": (
        "가상 머신 확장 집합(VMSS) 영역 중복 구성 필수",
        "단일 가용 영역 장애 시에도 컴퓨팅 용량을 유지할 수 있도록 compute.vm-scale-set을 최소 2개 이상의 가용 영역에 걸쳐 배치해야 합니다.",
    ),
    "compute.vm.environment-tag.required": (
        "가상 머신(VM)에 environment 태그 지정 필수",
        "환경별 수명주기 및 운영 정책이 일관되게 적용되도록 모든 compute.vm 리소스에 environment 태그를 반드시 부여해야 합니다.",
    ),
    "compute.vm.managed-identity.assigned": (
        "가상 머신(VM)에 관리 ID(Managed Identity) 할당 필수",
        "애플리케이션 설정에 자격 증명이나 비밀값을 하드코딩하지 않도록 compute.vm에 시스템 할당 또는 사용자 할당 관리 ID를 구성해야 합니다.",
    ),
    "disk.snapshot-policy.required": (
        "상태 저장 디스크(Disk) 스냅샷 보호 정책 연결 필수",
        "데이터 손상이나 오작동 발생 시 안전한 복구 지점(Rollback Point)을 확보할 수 있도록 상태를 보유한 디스크에 스냅샷 정책을 등록해야 합니다.",
    ),
    "kubernetes-cluster.diagnostic-settings-required": (
        "Kubernetes 클러스터 진단 설정(Diagnostic Settings) 활성화 필수",
        "API 서버 감사 로그와 컨트롤러 매니저 로그를 중앙 Log Analytics 워크스페이스로 전송하도록 진단 설정을 구성해야 합니다.",
    ),
    "kubernetes-cluster.network-policy": (
        "Kubernetes 클러스터 네트워크 정책(Network Policy) 엔진 활성화 필수",
        "파드 간(Pod-to-Pod) 동서 트래픽을 최소 권한으로 격리·제한할 수 있도록 Calico 또는 Azure 네트워크 정책 엔진을 활성화해야 합니다.",
    ),
    "kubernetes-cluster.private-cluster": (
        "Kubernetes 클러스터 프라이빗 API 서버 구성 필수",
        "클러스터 제어 플레인(API 서버)이 공용 인터넷에 노출되지 않고 프라이빗 엔드포인트를 통해서만 접근되도록 구성해야 합니다.",
    ),
    "kubernetes-cluster.rbac-enabled": (
        "Kubernetes 클러스터 Azure RBAC 통합 권한 제어 활성화 필수",
        "로컬 관리자 정적 자격 증명 대신 Azure RBAC 통합 인증·인가를 사용하여 클러스터 접근 권한을 통제해야 합니다.",
    ),
    "kubernetes-node-pool.multi-zone": (
        "Kubernetes 노드 풀 다중 가용 영역(Multi-Zone) 배치 필수",
        "단일 가용 영역 장애로 전체 워커 노드 풀이 중단되지 않도록 노드 풀을 최소 2개 이상의 가용 영역에 분산 배치해야 합니다.",
    ),
    "llm-endpoint.t2-proposer-unavailable": (
        "T2 추론 제안자(Proposer) 모델 엔드포인트 전체 경로 장애 탐지",
        "모든 T2 추론 모델 경로가 실패한 컨트롤 플레인 관측 신호를 감지하며, 자동 변경 없이 인간 개입(HIL) 복구 판단으로 안전하게 전환합니다.",
    ),
    "managed-identity.role-assignment.no-privileged-subscription-scope": (
        "관리 ID에 구독 범위 고권한 역할(Owner/Contributor 등) 부여 금지",
        "단일 워크로드 침해가 구독 전체의 영향 반경으로 확산되지 않도록 관리 ID에 구독 범위의 Owner, Contributor, User Access Administrator 권한 부여를 차단합니다.",
    ),
    "managed-identity.role-assignment.no-wildcard-action": (
        "관리 ID 역할에 와일드카드(*) 작업 권한 부여 금지",
        "최소 권한 원칙을 위반하고 실제 권한 범위를 불투명하게 만드는 와일드카드(*) 액션 또는 데이터 액션이 포함된 역할 할당을 차단합니다.",
    ),
    "network.nsg.no-inbound-any-rdp": (
        "NSG에서 전체 소스(Any) 대상 인바운드 RDP(TCP/3389) 허용 금지",
        "무차별 대입 공격(Brute-force) 표면을 제거하기 위해 네트워크 보안 그룹(NSG)에서 임의 소스로부터의 TCP/3389(RDP) 인바운드 허용 규칙을 금지합니다.",
    ),
    "network.nsg.no-inbound-any-ssh": (
        "NSG에서 전체 소스(Any) 대상 인바운드 SSH(TCP/22) 허용 금지",
        "무차별 대입 공격 표면을 제거하기 위해 네트워크 보안 그룹(NSG)에서 임의 소스로부터의 TCP/22(SSH) 인바운드 허용 규칙을 금지합니다.",
    ),
    "network.nsg.no-internet-inbound-rdp": (
        "NSG에서 인터넷 도달 가능 인바운드 RDP(TCP/3389) 노출 금지",
        "더 높은 우선순위의 명시적 거부 규칙으로 보호되지 않은 상태에서 인터넷(*, Internet, Any, 0.0.0.0/0, ::/0)으로부터 TCP/3389에 도달할 수 있는 NSG 구성을 차단합니다.",
    ),
    "network.nsg.no-internet-inbound-ssh": (
        "NSG에서 인터넷 도달 가능 인바운드 SSH(TCP/22) 노출 금지",
        "더 높은 우선순위의 명시적 거부 규칙으로 보호되지 않은 상태에서 인터넷(*, Internet, Any, 0.0.0.0/0, ::/0)으로부터 TCP/22에 도달할 수 있는 NSG 구성을 차단합니다.",
    ),
    "network.vnet.ddos-plan.required": (
        "가상 네트워크(VNet)에 DDoS 보호 계획 연결 필수",
        "외부 노출 워크로드를 수용하는 가상 네트워크(network.vnet)를 볼륨 기반 및 프로토콜 DDoS 공격으로부터 보호하기 위해 DDoS 보호 계획을 연결해야 합니다.",
    ),
    "object-storage.cost-center-tag.required": (
        "오브젝트 스토리지에 cost_center 비용 귀속 태그 지정 필수",
        "스토리지 사용 비용을 책임 부서 및 비용 센터에 정확히 배분할 수 있도록 모든 object-storage 계정에 cost_center 태그를 부여해야 합니다.",
    ),
    "object-storage.diagnostic-settings-required": (
        "오브젝트 스토리지 진단 설정(Diagnostic Settings) 활성화 필수",
        "스토리지 및 Blob 데이터 플레인 접근·변경 이벤트를 감사할 수 있도록 Log Analytics 워크스페이스로 진단 로그를 전송해야 합니다.",
    ),
    "object-storage.encryption-at-rest.required": (
        "오브젝트 스토리지 저장 데이터 인프라 이중 암호화 필수",
        "저장 데이터의 다계층 암호화 보호를 위해 오브젝트 스토리지 계정에 인프라 암호화(Infrastructure Encryption)를 활성화해야 합니다.",
    ),
    "object-storage.https-only.required": (
        "오브젝트 스토리지 HTTPS 전용 암호화 전송 강제 필수",
        "전송 구간 평문 노출을 방지하기 위해 HTTP 요청을 거부하고 보안 HTTPS 트래픽만 허용하도록 구성해야 합니다.",
    ),
    "object-storage.min-tls-version": (
        "오브젝트 스토리지 최소 TLS 1.2 버전 강제 필수",
        "취약한 구형 암호화 프로토콜(TLS 1.0/1.1) 연결을 차단하고 최소 TLS 1.2 이상으로만 클라이언트 통신을 허용해야 합니다.",
    ),
    "object-storage.owner-tag.required": (
        "오브젝트 스토리지에 owner 책임자 태그 지정 필수",
        "자산 소유권과 보안·운영 책임 주체를 명확히 추적할 수 있도록 모든 object-storage 계정에 owner 태그를 지정해야 합니다.",
    ),
    "object-storage.private-endpoint.required": (
        "오브젝트 스토리지 프라이빗 엔드포인트 연결 및 공용 네트워크 차단 필수",
        "데이터를 저장하는 오브젝트 스토리지 계정에 공용 네트워크 접근을 차단하고 프라이빗 엔드포인트(Private Endpoint)를 통해서만 접근하도록 구성해야 합니다.",
    ),
    "object-storage.public-access.deny": (
        "오브젝트 스토리지 익명 공용 액세스(Public Access) 차단 필수",
        "비인증 사용자의 컨테이너·Blob 열람 및 데이터 유출을 방지하기 위해 오브젝트 스토리지의 공용 액세스 허용 속성을 비활성화해야 합니다.",
    ),
    "object-storage.shared-key-access.disabled": (
        "오브젝트 스토리지 공유 키(Shared Key) 인증 비활성화 필수",
        "장기 정적 스토리지 계정 키 대신 관리 ID 기반 Entra ID RBAC 인증만 사용하도록 공유 키 접근을 비활성화해야 합니다.",
    ),
    "object-storage.soft-delete-blob": (
        "오브젝트 스토리지 Blob 소프트 삭제(Soft Delete) 활성화 필수",
        "실수나 악의적인 삭제 발생 시 보존 기간 내에 데이터를 즉시 복원할 수 있도록 Blob 소프트 삭제 정책을 활성화해야 합니다.",
    ),
    "object-storage.versioning-enabled": (
        "오브젝트 스토리지 Blob 버전 관리(Versioning) 활성화 필수",
        "덮어쓰기나 변조 발생 시 이전 버전을 복구할 수 있도록 오브젝트 스토리지의 Blob 자동 버전 관리를 활성화해야 합니다.",
    ),
    "ops.change-summary": (
        "리소스 그룹 변경 요약 보고서(Change Summary) 발행 규칙",
        "리소스 그룹 범위 이벤트에 change-summary 요청 마커가 포함된 경우 감사 로그로부터 변경 요약 마크다운 보고서를 결정론적으로 생성합니다.",
    ),
    "postgresql-server.diagnostic-settings-required": (
        "PostgreSQL 서버 진단 설정(Diagnostic Settings) 활성화 필수",
        "데이터베이스 연결, 쿼리, 오류 로그를 중앙 Log Analytics 워크스페이스로 수집하도록 PostgreSQL 진단 설정을 구성해야 합니다.",
    ),
    "postgresql-server.encryption-at-rest": (
        "PostgreSQL 서버 저장 데이터 암호화(Encryption at Rest) 활성화 필수",
        "데이터베이스 스토리지 및 백업 스냅샷이 암호화 상태로만 보관되도록 PostgreSQL 저장 데이터 암호화를 활성화해야 합니다.",
    ),
    "postgresql-server.high-availability": (
        "PostgreSQL 서버 영역 중복 고가용성(Zone-Redundant HA) 구성 필수",
        "단일 가용 영역 장애 시 운영자 개입 없이 자동 장애 조치(Failover)될 수 있도록 PostgreSQL 서버를 영역 중복 HA 모드로 구성해야 합니다.",
    ),
    "postgresql-server.point-in-time-restore": (
        "PostgreSQL 서버 시점 복원(PITR) 최소 백업 보존 기간 확보 필수",
        "우발적인 데이터 변경이나 손상 후 특정 시점으로 복구할 수 있도록 최소 기준 일수(기본 7일 이상)의 백업 보존 기간을 유지해야 합니다.",
    ),
    "postgresql-server.ssl-enforcement": (
        "PostgreSQL 서버 SSL/TLS 암호화 연결 강제 필수",
        "클라이언트와 데이터베이스 간 평문 트래픽 노출을 차단하기 위해 PostgreSQL 서버에서 SSL/TLS 연결을 강제해야 합니다.",
    ),
    "resource-group.cost-center-tag.required": (
        "리소스 그룹에 cost_center 비용 귀속 태그 지정 필수",
        "하위 리소스 비용을 책임 조직에 정확히 귀속하고 추적할 수 있도록 모든 resource-group에 cost_center 태그를 부여해야 합니다.",
    ),
    "resource-group.environment-tag.required": (
        "리소스 그룹에 environment 환경 분류 태그 지정 필수",
        "운영(prod), 스테이징(staging), 개발(dev) 등 환경별 정책이 정확히 적용되도록 모든 resource-group에 environment 태그를 부여해야 합니다.",
    ),
    "resource-group.owner-tag.required": (
        "리소스 그룹에 owner 책임자 태그 지정 필수",
        "리소스 그룹 단위의 운영·보안 책임 주체를 즉시 식별할 수 있도록 모든 resource-group에 owner 태그를 부여해야 합니다.",
    ),
    "resource-group.role-assignment.owner-count-within-limit": (
        "리소스 그룹 범위 Owner(소유자) 역할 할당 인원 상한 준수",
        "과도한 고권한 계정 확산을 방지하고 책임 추적성을 유지하기 위해 리소스 그룹 범위의 Owner 역할 보유 주체 수를 허용 상한(기본 3명) 이하로 제한합니다.",
    ),
    "secret-store.diagnostic-settings-required": (
        "비밀 저장소(Key Vault) 감사 진단 설정 활성화 필수",
        "비밀값, 키, 인증서의 모든 조회·수정 이벤트를 추적할 수 있도록 secret-store의 AuditEvent 로그를 Log Analytics로 전송해야 합니다.",
    ),
    "secret-store.public-network-access.disabled": (
        "비밀 저장소(Key Vault) 공용 네트워크 접근 비활성화 필수",
        "공용 인터넷으로부터의 비밀 저장소 접근을 차단하고 프라이빗 엔드포인트 또는 신뢰할 수 있는 플랫폼 우회 경로만 허용해야 합니다.",
    ),
    "secret-store.purge-protection.enabled": (
        "비밀 저장소(Key Vault) 영구 삭제 방지(Purge Protection) 활성화 필수",
        "보존 기간 내에 소프트 삭제된 비밀값이나 암호화 키가 강제로 영구 파기되지 않도록 영구 삭제 방지(Purge Protection)를 활성화해야 합니다.",
    ),
    "secret-store.rbac-authorization.enabled": (
        "비밀 저장소(Key Vault) Azure RBAC 권한 모델 활성화 필수",
        "세분화된 권한 제어와 일관된 감사가 어려운 레거시 액세스 정책 대신 Azure RBAC 기반 권한 부여 모델을 사용해야 합니다.",
    ),
    "secret-store.rotation-overdue": (
        "비밀 저장소(Key Vault) 비밀값 최대 교체 주기(Rotation) 초과 탐지",
        "생성 후 경과 일수가 허용 임계값(기본 90일)을 초과한 비밀값을 탐지하고 위험 게이트를 거쳐 안전한 비밀값 교체(remediate.rotate-secret)를 제안합니다.",
    ),
    "secret-store.soft-delete.enabled": (
        "비밀 저장소(Key Vault) 소프트 삭제(Soft Delete) 활성화 필수",
        "실수나 침해로 삭제된 비밀값·키를 보존 기간 동안 안전하게 복구할 수 있도록 소프트 삭제 기능을 활성화해야 합니다.",
    ),
    "sql-database.audit-enabled": (
        "SQL 데이터베이스 보안 감사(Auditing) 활성화 필수",
        "관리자 작업과 데이터 접근 이력을 포렌식 및 규정 준수 목적으로 추적할 수 있도록 sql-database 감사를 활성화하고 로그 워크스페이스에 연결해야 합니다.",
    ),
    "sql-database.diagnostic-settings-required": (
        "SQL 데이터베이스 진단 설정(Diagnostic Settings) 활성화 필수",
        "SQL 데이터베이스의 감사 및 성능 메트릭 로그를 중앙 Log Analytics 워크스페이스로 수집하도록 진단 설정을 구성해야 합니다.",
    ),
    "sql-database.geo-redundant-backup": (
        "SQL 데이터베이스 지역 중복 백업(Geo-Redundant Backup) 구성 필수",
        "주 리전 전체 장애 시에도 시점 복원(PITR) 백업 데이터를 보호할 수 있도록 지역 중복 백업 스토리지(GRS/RA-GRS)를 사용해야 합니다.",
    ),
    "sql-database.tde-required": (
        "SQL 데이터베이스 투명한 데이터 암호화(TDE) 활성화 필수",
        "데이터베이스 파일과 백업을 저장 상태에서 암호화하기 위해 TDE(Transparent Data Encryption)를 반드시 활성화해야 합니다.",
    ),
    "sql-database.zone-redundant": (
        "SQL 데이터베이스 영역 중복(Zone Redundant) 구성 필수",
        "단일 가용 영역 장애 시 데이터 손실 없이 자동 전환되도록 sql-database를 영역 중복 구성으로 실행해야 합니다.",
    ),
    "subscription.role-assignment.no-guest-privileged": (
        "구독 범위에서 외부 게스트(Guest) 주체에 고권한 역할 부여 금지",
        "테넌트 수명주기 통제 밖에 있는 외부 게스트 계정이 구독 전체의 지속적인 권한 상승 경로가 되지 않도록 구독 범위 고권한 역할(Owner, Contributor 등) 할당을 차단합니다.",
    ),
    "subscription.role-assignment.no-standing-privileged-access": (
        "구독 범위 고권한 역할의 상시(Standing) 할당 금지 및 JIT(PIM) 전환 필수",
        "상시 활성화된 관리자 공격 표면을 제거하기 위해 구독 범위 고권한 역할은 영구(Standing) 할당이 아닌 적시(Just-In-Time, PIM) 적격 권한으로만 부여해야 합니다.",
    ),
}

_EFFECT_LABELS_KO: dict[str, str] = {
    "audit": "감사(Audit)",
    "auditifnotexists": "미존재 시 감사(AuditIfNotExists)",
    "deny": "거부(Deny)",
    "deployifnotexists": "미존재 시 배포(DeployIfNotExists)",
    "modify": "수정(Modify)",
    "disabled": "비활성(Disabled)",
    "append": "추가(Append)",
}

_AZURE_POLICY_PHRASE_KO: tuple[tuple[str, str], ...] = (
    (
        "should use a customer-managed key to encrypt data at rest",
        "저장 데이터 암호화에 고객 관리형 키(CMK) 사용 필요",
    ),
    (
        "should use customer-managed keys to encrypt data at rest",
        "저장 데이터 암호화에 고객 관리형 키(CMK) 사용 필요",
    ),
    ("should use a customer-managed key", "고객 관리형 키(CMK) 사용 필요"),
    ("should use private link", "Private Link 사설 연결 사용 필요"),
    ("should use private endpoints", "프라이빗 엔드포인트(Private Endpoint) 사용 필요"),
    ("should disable public network access", "공용 네트워크 접근 비활성화 필요"),
    ("should have public network access disabled", "공용 네트워크 접근 비활성화 필요"),
    ("should use a virtual network", "가상 네트워크(VNet) 통합 사용 필요"),
    ("should be associated with a data collection rule", "데이터 수집 규칙(DCR) 연결 필요"),
    ("should have diagnostic settings", "진단 설정(Diagnostic Settings) 활성화 필요"),
    ("resource logs should be enabled", "리소스 진단 로그 활성화 필요"),
    ("should have firewall rules", "방화벽(Firewall) 규칙 구성 필요"),
    ("should use managed identity", "관리 ID(Managed Identity) 사용 필요"),
    ("local authentication methods should be disabled", "로컬 인증 방식 비활성화 필요"),
    ("should have local authentication methods disabled", "로컬 인증 방식 비활성화 필요"),
    ("should be zone redundant", "영역 중복(Zone Redundant) 구성 필요"),
)

_KUBE_BENCH_PHRASE_KO: tuple[tuple[str, str], ...] = (
    ("file permissions are set to", "파일 권한 설정 준수"),
    ("file ownership is set to", "파일 소유권(root:root) 설정 준수"),
    ("argument is set to", "실행 인자(Argument) 보안 설정 준수"),
    ("admission control plugin", "어드미션 컨트롤 플러그인 활성화"),
    ("minimize the admission of", "컨테이너 고위험 권한 허용 최소화"),
    ("ensure that the", "보안 기준 점검:"),
)


def _translate_policy_phrase_ko(display_name: str) -> str:
    lower = display_name.lower()
    for pattern, ko_phrase in _AZURE_POLICY_PHRASE_KO:
        if pattern in lower:
            return f"{display_name} - {ko_phrase}"
    if lower.startswith("configure "):
        return f"{display_name} (자동 구성 정책)"
    if lower.startswith("deploy "):
        return f"{display_name} (자동 배포 정책)"
    if lower.startswith("microsoft managed control"):
        return f"{display_name} (Microsoft 관리형 규정 준수 통제)"
    return display_name


def _translate_kube_bench_clause_ko(clause: str) -> str:
    lower = clause.lower()
    for pattern, ko_phrase in _KUBE_BENCH_PHRASE_KO:
        if pattern in lower:
            return f"{ko_phrase} ({clause})"
    return clause


def humanize_kube_bench_slug(rule_id: str, ruleset: str, bench_id: str) -> str:
    prefix = f"kube-bench.{ruleset}.{bench_id.replace('.', '-')}."
    slug = (
        rule_id.removeprefix(prefix) if rule_id.startswith(prefix) else rule_id.rsplit(".", 1)[-1]
    )
    slug = re.sub(r"-(?:automated|manual|m|a)$", "", slug)
    words = slug.replace("-", " ").strip()
    if not words:
        return f"CIS {ruleset} {bench_id}".strip()
    sentence = words[0].upper() + words[1:]
    return f"CIS {ruleset} {bench_id}: {sentence}"


def localize_kube_bench_explanation(
    *,
    rule_id: str,
    resource_type: str,
    parameters: Mapping[str, Any],
) -> tuple[str, str, str, str]:
    ruleset = str(parameters.get("kube_bench_ruleset", "")).strip()
    bench_id = str(parameters.get("kube_bench_id", "")).strip()
    group_id = str(parameters.get("kube_bench_group_id", "")).strip()
    scored = bool(parameters.get("kube_bench_scored", False))
    audit_cmd = str(parameters.get("kube_bench_audit", "")).strip()

    title_en = humanize_kube_bench_slug(rule_id, ruleset, bench_id)
    readable_clause = title_en.split(": ", 1)[1] if ": " in title_en else title_en

    component_ko = (
        "컨트롤 플레인(마스터 노드)"
        if "control-plane" in resource_type or "master" in resource_type
        else "워커 노드(Kubelet)"
        if "node" in resource_type
        else "클러스터 보안 정책"
    )
    scored_en = "scored" if scored else "not scored (advisory)"
    scored_ko = "점수 반영(Scored)" if scored else "권고 점검(Not Scored)"

    clause_ko = _translate_kube_bench_clause_ko(readable_clause)
    title_ko = f"CIS {ruleset} {bench_id}: Kubernetes {component_ko} {clause_ko}"
    audit_clause_en = f" Audit command: `{audit_cmd}`." if audit_cmd else ""
    audit_clause_ko = f" 감사 명령: `{audit_cmd}`." if audit_cmd else ""

    description_en = (
        f"Evaluates CIS Kubernetes Benchmark ({ruleset}, section {group_id or bench_id}, {scored_en}) "
        f"on `{resource_type}` to verify: {readable_clause}.{audit_clause_en}"
    )
    description_ko = (
        f"`{resource_type}`({component_ko})를 대상으로 CIS Kubernetes 벤치마크({ruleset}, 섹션 {group_id or bench_id}, {scored_ko}) "
        f"권고 기준({readable_clause}) 충족 여부를 검사합니다.{audit_clause_ko}"
    )
    return title_en, title_ko, description_en, description_ko


def localize_azure_policy_explanation(
    *,
    rule_id: str,
    resource_type: str,
    parameters: Mapping[str, Any],
) -> tuple[str, str, str, str]:
    display_name = str(parameters.get("azure_policy_display_name") or rule_id).strip()
    category = str(parameters.get("azure_policy_category") or "General").strip()
    effect_raw = str(parameters.get("azure_policy_effect_default") or "Audit").strip()
    policy_name = str(parameters.get("azure_policy_name") or "").strip()
    effect_ko = _EFFECT_LABELS_KO.get(effect_raw.lower(), effect_raw)

    title_en = display_name
    translated_ko = _translate_policy_phrase_ko(display_name)
    title_ko = f"[{category}] {translated_ko} ({effect_ko})"
    description_en = (
        f"Evaluates Azure Policy built-in definition `{policy_name or rule_id}` (category: {category}, "
        f"default effect: {effect_raw}) on `{resource_type}` to verify that the resource configuration "
        f"satisfies: {display_name}."
    )
    description_ko = (
        f"`{resource_type}` 리소스를 대상으로 Azure Policy 기본 제공 정책 `{policy_name or rule_id}`"
        f"(범주: {category}, 기본 효과: {effect_ko})를 평가하여 '{display_name}' 기준 충족 여부를 검증합니다."
    )
    return title_en, title_ko, description_en, description_ko
