"""Individually authored semantic pilots, grounded only in public documentation."""
# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from wara_guidance_reliability import localized as text

DNS_ID = "a2341513-2ab8-4aa1-b100-302e54640f18"
MAINTENANCE_ID = "52ab9e5c-eec0-3148-8bd7-b6dd9e1be870"
AI_ID = "61187af4-7d36-4b48-b16e-de78bef143a0"
PILOT_IDS = {DNS_ID, MAINTENANCE_ID, AI_ID}


def _node(node_id: str, en: str, ko: str, detail: dict[str, str], role: str) -> dict[str, Any]:
    return {"id": node_id, "label": text(en, ko), "detail": detail, "role": role}


def _edge(a: str, b: str, en: str, ko: str, style: str = "solid") -> dict[str, Any]:
    return {"from": a, "to": b, "label": text(en, ko), "style": style}


def _source(url: str, en: str, ko: str) -> dict[str, Any]:
    return {"kind": "learn", "url": url, "label": text(en, ko)}


def _dns() -> dict[str, Any]:
    return {
        "title": text(
            "Link regional virtual networks to the global Private DNS zone",
            "지역별 Virtual Network를 전역 Private DNS 영역에 연결",
        ),
        "summary": text(
            "Azure DNS private zones are nonregional. Link the required virtual networks in each operating or recovery region, or provide the documented resolver path, so clients can resolve the same private records. This configures access to the zone, not a second zone or application failover.",
            "Azure DNS 프라이빗 영역은 특정 지역에 종속되지 않습니다. 운영 또는 복구 지역의 필요한 Virtual Network를 연결하거나 문서가 정한 확인자 경로를 구성해 같은 프라이빗 레코드를 조회하도록 합니다. 이는 영역 접근 구성이지 새 영역 생성이나 애플리케이션 장애 조치가 아닙니다.",
        ),
        "benefits": text(
            "Clients in more than one region can resolve shared private records without making the primary region's VNet the only resolution path. Application recovery still requires reachable healthy targets.",
            "여러 지역의 클라이언트가 주 지역 VNet에만 의존하지 않고 공통 프라이빗 레코드를 조회할 수 있습니다. 애플리케이션을 복구하려면 접근 가능한 정상 대상도 필요합니다.",
        ),
        "rationale": text(
            "Microsoft replicates private-zone data across its nonregional DNS infrastructure. A VNet link makes the zone available to that VNet's DNS resolution path; it does not replicate the application. VM autoregistration is a separate per-link choice for managing eligible VM records. Private Endpoint DNS zone groups and manually managed records have their own ownership. DNS can successfully return an address belonging to a VM that is down.",
            "Microsoft는 비지역 DNS 인프라에 프라이빗 영역 데이터를 복제합니다. VNet 링크는 해당 VNet의 이름 해석 경로에서 영역을 사용할 수 있게 하며 애플리케이션을 복제하지는 않습니다. VM 자동 등록은 지원되는 VM 레코드를 관리하기 위한 링크별 선택 사항입니다. Private Endpoint DNS 영역 그룹과 수동 레코드의 관리 주체는 따로 확인합니다. DNS가 성공적으로 응답해도 반환 주소의 VM은 중단되어 있을 수 있습니다.",
        ),
        "applicability": [
            text(
                "Private DNS zones used by workloads in at least two operating or recovery regions.",
                "둘 이상의 운영 또는 복구 지역 워크로드가 사용하는 Private DNS 영역에 적용합니다.",
            ),
            text(
                "Inspect Azure-provided DNS, custom DNS forwarding and Private Resolver separately; VNet peering alone does not link a private zone.",
                "Azure 제공 DNS, 사용자 지정 DNS 전달과 Private Resolver를 따로 확인합니다. VNet 피어링만으로 프라이빗 영역이 연결되지는 않습니다.",
            ),
        ],
        "configuration": {
            "before": [
                text(
                    "Only the primary region's VNet has a zone link, or recovery-network forwarding is undocumented.",
                    "주 지역 VNet에만 영역 링크가 있거나 복구 네트워크의 전달 경로가 문서화되지 않은 상태입니다.",
                ),
                text(
                    "Autoregistration, private endpoint record management and lookup access are treated as the same setting.",
                    "자동 등록, 프라이빗 엔드포인트 레코드 관리와 조회 접근을 같은 설정으로 다루는 상태입니다.",
                ),
            ],
            "after": [
                text(
                    "Every required regional VNet has an explicit supported zone link or a verified resolver-forwarding path.",
                    "필요한 각 지역 VNet에 지원되는 영역 링크 또는 검증한 확인자 전달 경로를 명시합니다.",
                ),
                text(
                    "Record ownership and optional VM autoregistration are documented separately from target health and recovery routing.",
                    "레코드 관리와 선택적인 VM 자동 등록을 대상 정상 상태 및 복구 라우팅과 분리해 문서화합니다.",
                ),
            ],
        },
        "implementation_steps": [
            text(
                "Inventory the zone's virtualNetworkLinks and the actual client DNS settings in every required region; identify missing or duplicate resolution paths.",
                "필요한 각 지역에서 영역의 virtualNetworkLinks와 실제 클라이언트 DNS 설정을 확인하고 누락되거나 중복된 경로를 찾습니다.",
            ),
            text(
                "Plan the missing VNet links or supported resolver forwarding. Review permissions and link limits without creating another private zone as a regional replica.",
                "부족한 VNet 링크나 지원되는 확인자 전달을 계획합니다. 지역 복제본이라는 이유로 새 프라이빗 영역을 만들지 말고 권한과 링크 한도를 검토합니다.",
            ),
            text(
                "Choose VM autoregistration only where VM record management requires it; inspect Private Endpoint DNS zone groups and manual records independently.",
                "VM 레코드 관리에 필요한 경우에만 자동 등록을 선택합니다. Private Endpoint DNS 영역 그룹과 수동 레코드는 별도로 확인합니다.",
            ),
            text(
                "Prepare separate application health, routing and state-recovery procedures for the addresses returned by DNS.",
                "DNS가 반환하는 주소에 대해 별도의 애플리케이션 상태, 라우팅과 데이터 복구 절차를 준비합니다.",
            ),
        ],
        "verification_steps": [
            text(
                "Read back each link's target VNet, provisioning state and registrationEnabled choice and compare with the required regional network inventory.",
                "각 링크의 대상 VNet, 프로비전 상태와 registrationEnabled 선택을 다시 읽고 필요한 지역 네트워크 목록과 비교합니다.",
            ),
            text(
                "Resolve representative records from each required client network and confirm the intended resolver, returned address and effective TTL.",
                "필요한 각 클라이언트 네트워크에서 대표 레코드를 조회하고 의도한 확인자, 반환 주소와 실제 TTL을 확인합니다.",
            ),
            text(
                "Validate target reachability and application health independently; retain a DNS success and an unhealthy target as distinct possible observations.",
                "대상 접근과 애플리케이션 상태를 독립적으로 검증합니다. DNS 성공과 대상 비정상이 동시에 가능하다는 점을 구분해 기록합니다.",
            ),
            text(
                "Use only an independently authorized regional-path exercise or retained evidence to assess recovery; a static graph supplies no environmental finding.",
                "지역 경로의 복구는 별도로 승인된 시험이나 보존된 기록으로 평가합니다. 정적 그림을 환경 평가 결과로 사용하지 않습니다.",
            ),
        ],
        "cautions": [
            text(
                "Global DNS availability does not imply a healthy backend, a reachable private endpoint or automatic application failover.",
                "전역 DNS 가용성이 백엔드 정상, 프라이빗 엔드포인트 접근 또는 자동 애플리케이션 장애 조치를 뜻하지는 않습니다.",
            ),
            text(
                "VNet regional links are not VM autoregistration. Do not enable autoregistration just to satisfy multi-region lookup access.",
                "지역별 VNet 링크와 VM 자동 등록은 다릅니다. 여러 지역의 조회 접근을 충족하려는 이유만으로 자동 등록을 켜지 않습니다.",
            ),
            text(
                "Private DNS links do not grant application authorization or bypass network rules; custom resolver dependencies and caches remain in scope.",
                "Private DNS 링크는 애플리케이션 권한을 부여하거나 네트워크 규칙을 우회하지 않습니다. 사용자 지정 확인자와 캐시도 검토 대상입니다.",
            ),
        ],
        "diagram": {
            "id": "private-dns-regional-links",
            "kind": "dns-resolution",
            "title": text(
                "One nonregional zone, explicit regional resolution paths",
                "하나의 비지역 영역과 명시적인 지역별 조회 경로",
            ),
            "description": text(
                "Repository-authored configuration concept. Solid paths show zone access; dashed paths show optional record management or independent health checks. No deployed network or healthy backend is asserted.",
                "저장소에서 작성한 구성 개념도입니다. 실선은 영역 접근, 점선은 선택적 레코드 관리 또는 독립적인 상태 확인을 나타냅니다. 실제 네트워크 배포나 백엔드 정상을 주장하지 않습니다.",
            ),
            "nodes": [
                _node(
                    "zone",
                    "Nonregional Private DNS zone",
                    "비지역 Private DNS 영역",
                    text(
                        "Global zone data managed by Azure; not a customer-created regional replica.",
                        "Azure가 관리하는 전역 영역 데이터이며 고객이 생성한 지역 복제본이 아닙니다.",
                    ),
                    "subject",
                ),
                _node(
                    "primary",
                    "Primary-region VNet",
                    "주 지역 VNet",
                    text(
                        "Explicit link or supported resolver path.",
                        "명시적 링크 또는 지원되는 확인자 경로입니다.",
                    ),
                    "dependency",
                ),
                _node(
                    "secondary",
                    "Recovery-region VNet",
                    "복구 지역 VNet",
                    text(
                        "Independent required resolution path.",
                        "별도로 필요한 이름 해석 경로입니다.",
                    ),
                    "dependency",
                ),
                _node(
                    "registration",
                    "Optional VM autoregistration",
                    "선택적인 VM 자동 등록",
                    text(
                        "VM record lifecycle, not regional failover.",
                        "VM 레코드 관리이며 지역 장애 조치가 아닙니다.",
                    ),
                    "configuration",
                ),
                _node(
                    "target",
                    "Returned target address",
                    "반환된 대상 주소",
                    text(
                        "May resolve while its backend is unhealthy.",
                        "이름이 해석되어도 백엔드는 비정상일 수 있습니다.",
                    ),
                    "outcome",
                ),
                _node(
                    "health",
                    "Independent target check",
                    "독립적인 대상 확인",
                    text(
                        "Application health and routing require their own evidence.",
                        "애플리케이션 상태와 라우팅은 별도 근거가 필요합니다.",
                    ),
                    "evidence",
                ),
            ],
            "edges": [
                _edge("primary", "zone", "name-resolution link", "이름 해석 링크"),
                _edge("secondary", "zone", "name-resolution link", "이름 해석 링크"),
                _edge(
                    "registration",
                    "zone",
                    "optional VM record updates",
                    "선택적 VM 레코드 갱신",
                    "dashed",
                ),
                _edge(
                    "zone",
                    "target",
                    "DNS answer, not backend health",
                    "DNS 응답이며 백엔드 상태 아님",
                ),
                _edge(
                    "health",
                    "target",
                    "separate reachability observation",
                    "별도 접근 확인",
                    "dashed",
                ),
            ],
        },
        "_extra_sources": [
            _source(
                "https://learn.microsoft.com/en-us/azure/reliability/reliability-dns-private",
                "Private DNS reliability",
                "Private DNS 복원력",
            ),
            _source(
                "https://learn.microsoft.com/en-us/azure/dns/private-dns-autoregistration",
                "VM autoregistration behavior and limits",
                "VM 자동 등록 동작과 제약",
            ),
        ],
    }


def _maintenance() -> dict[str, Any]:
    return {
        "title": text(
            "Coordinate maintenance for Dedicated and Isolated VM SKUs",
            "Dedicated 및 Isolated VM SKU의 유지 관리 조율",
        ),
        "summary": text(
            "This APRL recommendation concerns maintenance configuration for eligible Dedicated or Isolated compute. The pinned source impact is Medium. Review the maintenance scope before applying scheduling prerequisites: Host, OS image and Guest control different update layers.",
            "이 APRL 권고는 지원되는 Dedicated 또는 Isolated 컴퓨팅의 유지 관리 구성을 다룹니다. 고정 원본의 영향도는 Medium입니다. 일정 조건을 적용하기 전에 범위를 확인합니다. Host, OS image와 Guest는 서로 다른 업데이트 계층을 제어합니다.",
        ),
        "rationale": text(
            "A Host maintenance configuration can coordinate supported host updates for Dedicated Hosts and Isolated VMs or VM scale sets. OS image scope instead controls supported VMSS OS image upgrades and requires automatic OS upgrades to be enabled in the current documentation. Guest scope integrates with Azure Update Manager and has its own patch orchestration and scheduling requirements. A matching schedule without complete assignments or verified Isolated SKU eligibility is insufficient.",
            "Host 유지 관리 구성은 Dedicated Host와 Isolated VM 또는 VMSS에서 지원되는 호스트 업데이트를 조율합니다. OS image 범위는 VMSS OS 이미지 업그레이드를 제어하며 현재 문서는 자동 OS 업그레이드 활성화를 요구합니다. Guest 범위는 Azure Update Manager와 통합되고 별도의 패치 오케스트레이션 및 일정 조건을 가집니다. 일정이 있어도 할당이 완전하거나 Isolated SKU가 지원되는지 확인하지 못하면 충분하지 않습니다.",
        ),
        "applicability": [
            text(
                "For this GUID, establish Dedicated Host or Isolated VM/VMSS eligibility before interpreting a Host configuration.",
                "이 GUID에서는 Host 구성을 해석하기 전에 Dedicated Host 또는 Isolated VM/VMSS 지원 여부를 확인합니다.",
            ),
            text(
                "Review OS image and Guest scope separately; ordinary shared-host VMs do not inherit Host eligibility merely by having a schedule.",
                "OS image와 Guest 범위를 따로 검토합니다. 일반 공유 호스트 VM은 일정이 있다는 이유만으로 Host 지원 대상이 되지 않습니다.",
            ),
        ],
        "configuration": {
            "before": [
                text(
                    "Host: Dedicated Host or Isolated VM/VMSS eligibility and effective maintenance assignments are unverified.",
                    "Host: Dedicated Host 또는 Isolated VM/VMSS 지원 여부와 실제 유지 관리 할당을 확인하지 않은 상태입니다.",
                ),
                text(
                    "OS image: VMSS automatic OS upgrade state and supported image-maintenance scheduling are unverified.",
                    "OS image: VMSS 자동 OS 업그레이드 상태와 지원되는 이미지 유지 관리 일정을 확인하지 않은 상태입니다.",
                ),
                text(
                    "Guest: Update Manager scope, patch orchestration and effective guest patch schedule are unverified.",
                    "Guest: Update Manager 범위, 패치 오케스트레이션과 실제 게스트 패치 일정을 확인하지 않은 상태입니다.",
                ),
            ],
            "after": [
                text(
                    "Host: Eligible Dedicated or Isolated targets have supported windows and complete assignment observations; OS image prerequisites do not apply to Host automatically.",
                    "Host: 지원되는 Dedicated 또는 Isolated 대상에 유효 시간대와 전체 할당 관찰을 확보합니다. OS image 조건을 Host에 자동으로 적용하지 않습니다.",
                ),
                text(
                    "OS image: Supported VMSS has automatic OS upgrades enabled and an effective image-scope schedule with its own window limits.",
                    "OS image: 지원 VMSS에 자동 OS 업그레이드를 활성화하고 해당 범위의 시간대 제약에 맞는 이미지 일정을 적용합니다.",
                ),
                text(
                    "Guest: Supported Update Manager targets meet AutomaticByPlatform and applicable guest scheduling prerequisites, verified separately from Host.",
                    "Guest: 지원되는 Update Manager 대상이 AutomaticByPlatform과 해당 게스트 일정 조건을 충족하는지 Host와 별도로 검증합니다.",
                ),
            ],
        },
        "implementation_steps": [
            text(
                "Inventory target compute and classify Dedicated Host, Isolated VM or VMSS, OS image and Guest scope without relying only on a SKU name substring.",
                "대상 컴퓨팅을 확인하고 Dedicated Host, Isolated VM 또는 VMSS, OS image와 Guest 범위를 분류합니다. SKU 이름 일부만으로 판단하지 않습니다.",
            ),
            text(
                "Read the current scope-specific maintenance documentation, choose a supported window and enumerate actual configuration assignments.",
                "현재 범위별 유지 관리 문서에서 지원 시간대를 선택하고 실제 구성 할당을 열거합니다.",
            ),
            text(
                "For OS image scope, verify automatic OS upgrades are enabled on supported VMSS; for Guest, review AutomaticByPlatform and Update Manager scheduling requirements separately.",
                "OS image는 지원 VMSS의 자동 OS 업그레이드 활성화를 확인합니다. Guest는 AutomaticByPlatform과 Update Manager 일정 조건을 따로 검토합니다.",
            ),
            text(
                "Coordinate application draining, rollback and health validation before any independently approved maintenance change.",
                "별도로 승인된 유지 관리 변경 전에 애플리케이션 작업 마무리, 롤백과 상태 검증을 조율합니다.",
            ),
        ],
        "verification_steps": [
            text(
                "Inspect maintenanceScope, effective assignments, target eligibility, recurrence and time zone with complete observation coverage.",
                "전체 관찰 범위에서 maintenanceScope, 실제 할당, 대상 지원 여부, 반복 주기와 표준 시간대를 확인합니다.",
            ),
            text(
                "Compare completed maintenance records and workload error or reconnect observations with the planned window; schedule existence is not completion evidence.",
                "완료된 유지 관리 기록과 워크로드 오류 또는 재연결 관찰을 계획한 시간대와 비교합니다. 일정 존재를 완료 근거로 사용하지 않습니다.",
            ),
            text(
                "Keep the existing blocked automated query result blocked until query joins, assignment completeness and eligibility semantics are independently resolved.",
                "쿼리 조인, 할당 완전성과 지원 여부의 의미를 독립적으로 해결할 때까지 기존 자동 쿼리의 blocked 상태를 유지합니다.",
            ),
            text(
                "Record missing or conflicting evidence as unknown or manual review, not a compliant resource inferred from this guide.",
                "누락되거나 충돌하는 정보는 이 가이드로 충족 상태를 추정하지 말고 알 수 없음 또는 수동 검토로 기록합니다.",
            ),
        ],
        "cautions": [
            text(
                "The source impact is Medium, not High; explanatory content must not change source severity or the evaluator's blocked disposition.",
                "원본 영향도는 High가 아니라 Medium입니다. 설명을 보강해도 원본 심각도나 평가기의 blocked 상태를 바꾸지 않습니다.",
            ),
            text(
                "Automatic OS upgrades are required for supported VMSS OS image scheduling, not a universal Host or Guest requirement.",
                "자동 OS 업그레이드는 지원 VMSS의 OS image 일정에 필요한 조건이며 모든 Host 또는 Guest의 공통 조건은 아닙니다.",
            ),
            text(
                "Host eligibility does not cover every VM SKU. Schedules do not eliminate emergency updates or guarantee interruption-free application behavior.",
                "모든 VM SKU가 Host 범위를 지원하는 것은 아닙니다. 일정은 긴급 업데이트를 없애거나 무중단 애플리케이션 동작을 보장하지 않습니다.",
            ),
        ],
        "diagram": {
            "id": "maintenance-scope-separation",
            "kind": "patch-workflow",
            "title": text(
                "Separate Host, OS image and Guest maintenance scopes",
                "Host, OS image와 Guest 유지 관리 범위 분리",
            ),
            "description": text(
                "Repository-authored scope map. Separate branches express different prerequisites; they are not interchangeable. The blocked evaluator remains separate from the configuration concept.",
                "저장소에서 작성한 범위 지도입니다. 각 분기는 서로 바꿔 쓸 수 없는 전제 조건을 나타냅니다. blocked 평가기는 구성 개념과 분리되어 있습니다.",
            ),
            "nodes": [
                _node(
                    "configuration",
                    "Maintenance configuration",
                    "유지 관리 구성",
                    text("Scope plus actual target assignments.", "범위와 실제 대상 할당입니다."),
                    "configuration",
                ),
                _node(
                    "host",
                    "Host scope",
                    "Host 범위",
                    text(
                        "Dedicated Hosts and eligible Isolated VM/VMSS only.",
                        "Dedicated Host와 지원되는 Isolated VM/VMSS 대상입니다.",
                    ),
                    "subject",
                ),
                _node(
                    "image",
                    "OS image scope",
                    "OS image 범위",
                    text(
                        "Supported VMSS requires automatic OS upgrades enabled.",
                        "지원 VMSS에 자동 OS 업그레이드 활성화가 필요합니다.",
                    ),
                    "subject",
                ),
                _node(
                    "guest",
                    "Guest scope",
                    "Guest 범위",
                    text(
                        "Update Manager and scope-specific patch orchestration.",
                        "Update Manager와 해당 범위의 패치 오케스트레이션입니다.",
                    ),
                    "subject",
                ),
                _node(
                    "application",
                    "Workload preparation",
                    "워크로드 준비",
                    text(
                        "Drain, rollback and independent post-update health.",
                        "작업 마무리, 롤백과 독립적인 업데이트 후 상태 확인입니다.",
                    ),
                    "dependency",
                ),
                _node(
                    "evidence",
                    "Assignments and eligibility",
                    "할당과 지원 여부",
                    text(
                        "Complete attributed observations required.",
                        "출처가 있는 전체 관찰이 필요합니다.",
                    ),
                    "evidence",
                ),
                _node(
                    "blocked",
                    "Automated query remains blocked",
                    "자동 쿼리는 blocked 유지",
                    text(
                        "Guidance does not resolve joins or eligibility semantics.",
                        "가이드는 조인이나 지원 여부의 의미를 해결하지 않습니다.",
                    ),
                    "outcome",
                ),
            ],
            "edges": [
                _edge("configuration", "host", "scope-specific assignment", "범위별 할당"),
                _edge("configuration", "image", "different prerequisites", "별도 전제 조건"),
                _edge("configuration", "guest", "different orchestration", "별도 오케스트레이션"),
                _edge("host", "application", "coordinate update", "업데이트 조율"),
                _edge("image", "application", "coordinate upgrade", "업그레이드 조율"),
                _edge("guest", "application", "coordinate patch", "패치 조율"),
                _edge(
                    "evidence",
                    "configuration",
                    "verify actual coverage",
                    "실제 범위 검증",
                    "dashed",
                ),
                _edge(
                    "evidence",
                    "blocked",
                    "unresolved semantics stay explicit",
                    "미해결 의미 명시",
                    "dashed",
                ),
            ],
        },
    }


def _ai() -> dict[str, Any]:
    return {
        "title": text(
            "Design explicit routing across regional model deployments",
            "지역별 모델 배포 사이의 명시적 라우팅 설계",
        ),
        "summary": text(
            "Prepare compatible primary and secondary Azure OpenAI model deployments and an explicit gateway or client routing policy. Review each route's model version, deployment type, quotas, identity, network path and permitted processing geography before treating it as eligible recovery capacity.",
            "호환되는 주 및 보조 Azure OpenAI 모델 배포와 명시적인 게이트웨이 또는 클라이언트 라우팅 정책을 준비합니다. 복구 용량으로 사용하기 전에 각 경로의 모델 버전, 배포 유형, 할당량, 신원, 네트워크와 허용 처리 지역을 검토합니다.",
        ),
        "benefits": text(
            "A reviewed alternate deployment can reduce dependence on a single regional request path. Explicit eligibility and route observations make recovery decisions explainable without claiming automatic failover or guaranteed capacity.",
            "검토한 대체 배포는 단일 지역 요청 경로에 대한 의존을 줄일 수 있습니다. 적격 조건과 실제 경로를 확인해 자동 장애 조치나 용량을 보장한다고 주장하지 않고 복구 판단을 설명할 수 있습니다.",
        ),
        "rationale": text(
            "Creating two accounts is not a routing policy. A gateway needs compatible deployment mappings, bounded retry and timeout handling, an explicit alternate route and observations showing which deployment was selected. Global, Data Zone and Regional deployment types describe different service processing models and cannot be treated as synonyms for resource location or customer failover. Shared identity, private DNS, retrieval data and exhausted regional quota can still make a secondary path unusable.",
            "계정을 두 개 만드는 것은 라우팅 정책이 아닙니다. 게이트웨이에는 호환 배포 대응 관계, 제한된 재시도와 시간 제한, 명시적인 대체 경로와 실제 선택한 배포의 관찰이 필요합니다. Global, Data Zone과 Regional은 서로 다른 서비스 처리 모델이며 리소스 위치나 고객 장애 조치와 같은 뜻이 아닙니다. 공통 신원, Private DNS, 검색 데이터나 소진된 지역 할당량 때문에 보조 경로도 사용할 수 없을 수 있습니다.",
        ),
        "applicability": [
            text(
                "Workloads whose availability objectives require alternate model-serving capacity in separately reviewed regions.",
                "가용성 목표에 따라 별도로 검토한 지역에 대체 모델 처리 용량이 필요한 워크로드에 적용합니다.",
            ),
            text(
                "Both deployments must support the required model version, API behavior and processing policy; residency and quota review precede route eligibility.",
                "양쪽 배포가 필요한 모델 버전, API 동작과 처리 정책을 지원해야 합니다. 경로 적격성보다 먼저 상주성과 할당량을 검토합니다.",
            ),
        ],
        "configuration": {
            "before": [
                text(
                    "All model requests use one regional path or an alternate deployment exists without a validated routing policy.",
                    "모든 모델 요청이 한 지역 경로를 사용하거나 대체 배포가 있어도 라우팅 정책을 검증하지 않은 상태입니다.",
                ),
                text(
                    "Global deployment names are mistaken for guaranteed regional failover or a fixed processing location.",
                    "Global 배포 이름을 지역 장애 조치 보장이나 고정된 처리 위치로 오해하는 상태입니다.",
                ),
            ],
            "after": [
                text(
                    "A gateway maps primary and eligible secondary model deployments through explicit bounded route policies.",
                    "게이트웨이가 명시적이고 제한된 경로 정책으로 주 배포와 적격 보조 모델 배포를 연결합니다.",
                ),
                text(
                    "Compatibility, quota, network and geography observations are recorded separately from actual route and request outcomes.",
                    "호환성, 할당량, 네트워크와 지역 조건을 실제 라우팅 및 요청 결과와 분리해 기록합니다.",
                ),
            ],
        },
        "implementation_steps": [
            text(
                "Select primary and secondary deployments using the current deployment-type and model support documentation; record exact model versions and throughput modes.",
                "현재 배포 유형과 모델 지원 문서로 주 및 보조 배포를 선택하고 정확한 모델 버전과 처리량 방식을 기록합니다.",
            ),
            text(
                "Review allowed processing geography, data handling, quotas, capacity, identity, network and stateful dependencies for each route with policy owners.",
                "정책 책임자와 각 경로의 허용 처리 지역, 데이터 처리, 할당량, 용량, 신원, 네트워크와 상태 저장 의존성을 검토합니다.",
            ),
            text(
                "Configure an explicit supported gateway or client policy with health or error criteria, bounded retries, timeouts and alternate-route eligibility; define stop and failback behavior.",
                "상태 또는 오류 기준, 제한된 재시도, 시간 제한과 대체 경로 적격성을 가진 지원 게이트웨이 또는 클라이언트 정책을 명시적으로 구성합니다. 중단과 원복 동작도 정합니다.",
            ),
            text(
                "Prepare redacted route and deployment observations. A separately authorized live-model exercise is outside corpus generation and is not performed by this build.",
                "민감 정보를 제거한 경로와 배포 관찰을 준비합니다. 별도 승인이 필요한 실제 모델 시험은 코퍼스 생성 범위 밖이며 이 빌드에서 수행하지 않습니다.",
            ),
        ],
        "verification_steps": [
            text(
                "Inspect effective gateway policy and deployment mappings, not just account count or resource region.",
                "계정 수나 리소스 지역뿐 아니라 실제 게이트웨이 정책과 배포 대응 관계를 확인합니다.",
            ),
            text(
                "Verify primary and secondary deployment eligibility from model version, type, granted quota, network and policy-review evidence.",
                "모델 버전, 유형, 부여된 할당량, 네트워크와 정책 검토 근거로 주 및 보조 배포의 적격성을 검증합니다.",
            ),
            text(
                "Use retained redacted request traces or an independently approved exercise to confirm selected routes, retry limits, throttling, latency and alternate behavior.",
                "보존된 비식별 요청 추적이나 독립적으로 승인된 시험으로 선택 경로, 재시도 제한, 처리 제한, 지연과 대체 동작을 확인합니다.",
            ),
            text(
                "Record missing route or readiness evidence as unverified. A static regional diagram or Global deployment type cannot establish operational failover.",
                "경로나 준비 상태 근거가 없으면 미검증으로 기록합니다. 정적 지역 그림이나 Global 배포 유형으로 운영 장애 조치를 입증할 수는 없습니다.",
            ),
        ],
        "cautions": [
            text(
                "Do not guarantee automatic failover, zero errors, alternate capacity or any processing location from this architecture.",
                "이 아키텍처만으로 자동 장애 조치, 무오류, 대체 용량 또는 처리 위치를 보장하지 않습니다.",
            ),
            text(
                "Global, Data Zone and Regional are not synonymous. An alternate route must not bypass residency or data-handling restrictions.",
                "Global, Data Zone과 Regional은 같은 뜻이 아닙니다. 대체 경로가 상주성이나 데이터 처리 제한을 우회해서는 안 됩니다.",
            ),
            text(
                "Model versions, quota and paid capacity can differ by region; retries and cross-route replay can increase cost or duplicate side effects.",
                "모델 버전, 할당량과 유료 용량은 지역마다 다를 수 있습니다. 재시도와 경로 간 재실행은 비용이나 중복 부작용을 늘릴 수 있습니다.",
            ),
        ],
        "diagram": {
            "id": "model-gateway-regional-eligibility",
            "kind": "regional-failover",
            "title": text(
                "Gateway routes only to reviewed eligible deployments",
                "검토한 적격 배포만 선택하는 게이트웨이",
            ),
            "description": text(
                "Repository-authored regional architecture, not a deployed topology. Solid arrows show request paths; dashed arrows supply eligibility and route observations. An alternate route is explicit, conditional and not guaranteed.",
                "실제 배포 구조가 아닌 저장소 작성 지역 아키텍처입니다. 실선은 요청 경로, 점선은 적격성 및 경로 확인 자료를 나타냅니다. 대체 경로는 명시적이고 조건부이며 보장되지 않습니다.",
            ),
            "nodes": [
                _node(
                    "clients",
                    "Application requests",
                    "애플리케이션 요청",
                    text("Model and latency requirements.", "모델과 지연 요구입니다."),
                    "subject",
                ),
                _node(
                    "gateway",
                    "Gateway route policy",
                    "게이트웨이 경로 정책",
                    text(
                        "Explicit route mappings, deadlines and bounded retries.",
                        "명시적 경로 대응, 기한과 제한된 재시도입니다.",
                    ),
                    "configuration",
                ),
                _node(
                    "primary",
                    "Primary regional deployment",
                    "주 지역 배포",
                    text(
                        "Specific model version, deployment type and quota.",
                        "특정 모델 버전, 배포 유형과 할당량입니다.",
                    ),
                    "dependency",
                ),
                _node(
                    "secondary",
                    "Secondary regional deployment",
                    "보조 지역 배포",
                    text(
                        "Separately reviewed compatibility and processing geography.",
                        "호환성과 처리 지역을 별도로 검토합니다.",
                    ),
                    "dependency",
                ),
                _node(
                    "eligibility",
                    "Compatibility and policy evidence",
                    "호환성과 정책 근거",
                    text(
                        "Model, quota, residency, identity and network observations.",
                        "모델, 할당량, 상주성, 신원과 네트워크 확인 자료입니다.",
                    ),
                    "evidence",
                ),
                _node(
                    "routes",
                    "Observed request routes",
                    "관찰된 요청 경로",
                    text(
                        "Redacted deployment selection, errors and latency; no assumed success.",
                        "비식별 배포 선택, 오류와 지연이며 성공을 가정하지 않습니다.",
                    ),
                    "evidence",
                ),
            ],
            "edges": [
                _edge("clients", "gateway", "model request", "모델 요청"),
                _edge("gateway", "primary", "primary eligible route", "주 적격 경로"),
                _edge(
                    "gateway",
                    "secondary",
                    "explicit conditional alternate",
                    "명시적 조건부 대체",
                    "dashed",
                ),
                _edge(
                    "eligibility",
                    "gateway",
                    "constrains route selection",
                    "경로 선택 제한",
                    "dashed",
                ),
                _edge(
                    "eligibility",
                    "primary",
                    "checks primary readiness",
                    "주 배포 준비 확인",
                    "dashed",
                ),
                _edge(
                    "eligibility",
                    "secondary",
                    "checks alternate readiness",
                    "대체 준비 확인",
                    "dashed",
                ),
                _edge("routes", "gateway", "observes actual selection", "실제 선택 관찰", "dashed"),
            ],
        },
        "_extra_sources": [
            _source(
                "https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/deployment-types",
                "Model deployment types",
                "모델 배포 유형",
            ),
            _source(
                "https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/generative-ai-gateway-multiple-models",
                "Gateway patterns for multiple model deployments",
                "다중 모델 배포 게이트웨이 패턴",
            ),
        ],
    }


def apply_pilot(entry: dict[str, Any]) -> None:
    builders = {DNS_ID: _dns, MAINTENANCE_ID: _maintenance, AI_ID: _ai}
    builder = builders.get(entry["recommendation_id"])
    if builder is None:
        return
    fields = builder()
    extra_sources = fields.pop("_extra_sources", [])
    entry.update(fields)
    entry["sources"].extend(extra_sources)
