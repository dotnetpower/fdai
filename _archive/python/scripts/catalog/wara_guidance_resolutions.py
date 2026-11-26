"""Apply complete conditional guidance without laundering historical source claims."""
# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from wara_guidance_edges_ko import EDGES_KO
from wara_guidance_graphs import graph
from wara_guidance_labels_ko import LABELS_KO
from wara_guidance_node_details import qualified_node_details
from wara_guidance_qualified_edges_ko import QUALIFIED_EDGES_KO
from wara_guidance_qualified_labels_ko import QUALIFIED_LABELS_KO
from wara_guidance_reliability import localized as text
from wara_guidance_resolutions_ko import RESOLUTIONS_KO
from wara_guidance_resolutions_network import RESOLUTIONS as NETWORK
from wara_guidance_resolutions_workloads import RESOLUTIONS as WORKLOADS

RESOLUTIONS = NETWORK | WORKLOADS

FIGURE_TITLES = {
    "e7dbd21f": ("IoT Hub routing and fallback configuration", "IoT Hub 라우팅과 대체 경로 구성"),
    "98bd7098": (
        "Resource-group metadata and resource access",
        "리소스 그룹 메타데이터와 리소스 접근",
    ),
    "63491f70": ("ACR zone support and feature boundaries", "ACR 영역 지원과 기능별 범위"),
    "84636c6c": (
        "Event Hubs support conditions and event flow",
        "Event Hubs 지원 조건과 이벤트 흐름",
    ),
    "b376281d": ("AI Search replicas and zone placement", "AI Search 복제본과 영역 배치"),
    "740f2c1c": ("APIM zone configuration and component scope", "APIM 영역 구성과 구성 요소 범위"),
    "1c6c97d7": ("AVD connectivity paths and dependencies", "AVD 연결 경로와 의존성"),
    "9ec5b4c8": (
        "AVS stretched-cluster configuration and dependencies",
        "AVS 확장 클러스터 구성과 의존성",
    ),
    "38721758": ("AVD host recovery choices and dependencies", "AVD 호스트 복구 선택과 의존성"),
    "a18d60f8": ("Delta version selection and ETL recovery", "Delta 버전 선택과 ETL 복구"),
    "c15b2b73": ("FSLogix configuration and profile attachment", "FSLogix 구성과 프로필 연결"),
    "4884cada": ("SAP and ANF timeout layers", "SAP와 ANF의 계층별 시간 제한"),
    "6648fe61": ("HANA replication, ownership and fencing", "HANA 복제, 소유권과 펜싱"),
    "9d8f6678": ("ASCS/ERS resources and shared storage", "ASCS/ERS 리소스와 공유 저장소"),
    "ee4dc309": ("SAP shared-file protection and recovery", "SAP 공유 파일 보호와 복구"),
    "c041d596": (
        "Citrix capacity limits and expansion dependencies",
        "Citrix 용량 한도와 확장 의존성",
    ),
}

TITLES = {
    "e7dbd21f": "Review IoT Hub unmatched-message fallback delivery",
    "98bd7098": "Separate resource-group metadata location from workload recovery",
    "63491f70": "Verify automatic ACR zone protection by region and feature",
    "84636c6c": "Verify current Event Hubs zone eligibility and client continuity",
    "b376281d": "Size AI Search replicas with qualified zone and SLA behavior",
    "740f2c1c": "Select the exact APIM tier's supported zone mode",
    "1c6c97d7": "Provide narrowly scoped paths to required AVD destinations",
    "9ec5b4c8": "Plan a supported AVS stretched-cluster deployment",
    "38721758": "Historical AVD recovery: distinguish recreation, replication and backup",
    "a18d60f8": "Repair Delta ETL from a validated retained version",
    "c15b2b73": "Select and safely apply a supported FSLogix baseline",
    "4884cada": "Coordinate SAP and ANF timeout layers for the selected stack",
    "6648fe61": "Validate a supported HANA replication and Pacemaker contract",
    "9d8f6678": "Validate an OS and ENSA-specific ASCS/ERS cluster contract",
    "ee4dc309": "Protect SAP shared files independently of VM replication",
    "c041d596": "Apply current product-scoped Citrix VDA capacity limits",
}

SUMMARIES = {
    "e7dbd21f": (
        "Reconcile the historical title before changing IoT Hub routing: fallback delivers messages matching no route when enabled. Choose enablement from the required delivery contract, not from the phrase Disabled Fallback Route.",
        "IoT Hub 경로를 변경하기 전에 과거 제목의 의미를 대조합니다. 대체 경로는 활성화되어야 어떤 경로에도 일치하지 않는 메시지를 전달합니다. Disabled Fallback Route라는 제목이 아니라 필요한 전달 계약에 따라 선택합니다.",
    ),
    "98bd7098": (
        "Resource-group location controls management metadata placement, not a universal location requirement for contained resources. Review ARM control-plane continuity separately from each resource's data-plane recovery; do not relocate resources just to match location strings.",
        "리소스 그룹 위치는 관리 메타데이터 위치이며 포함 리소스의 공통 지역 요구가 아닙니다. ARM 관리 연속성과 각 리소스의 데이터 복구를 따로 검토하고 지역 문자열을 맞추려는 이유만으로 리소스를 이전하지 않습니다.",
    ),
    "63491f70": (
        "ACR zone redundancy is now automatic across all tiers in supported regions. The legacy zoneRedundancy field can say Disabled without disabling protection; verify region and feature scope instead of prescribing a Premium-only toggle.",
        "ACR 영역 중복은 현재 지원 지역의 모든 계층에 자동 적용됩니다. 이전 zoneRedundancy 필드가 Disabled여도 보호를 끄지는 않습니다. Premium 전용 설정을 지시하지 말고 지역과 기능 범위를 확인합니다.",
    ),
    "84636c6c": (
        "Event Hubs zone support is automatically provided in supported regions subject to tier/capacity prerequisites. Standard and Premium need no extra zone setting; Dedicated requires at least three CUs. Historical portal/IaC defaults are not the current decision rule.",
        "Event Hubs는 계층과 용량 조건에 따라 지원 지역에서 자동 영역 지원을 제공합니다. Standard와 Premium은 별도 영역 설정이 없고 Dedicated는 최소 3개 CU가 필요합니다. 과거 포털과 IaC 기본값 차이를 현재 판단 기준으로 쓰지 않습니다.",
    ),
    "b376281d": (
        "Eligible Basic-or-higher AI Search services with at least two replicas receive automatic zone support, but exact replica placement is not guaranteed. Distinguish read-only and read-write SLA replica requirements from partitions and regional recovery.",
        "지원 지역의 Basic 이상 AI Search는 복제본이 둘 이상이면 자동 영역 지원을 받지만 정확한 배치는 보장되지 않습니다. 읽기 전용과 읽기·쓰기 SLA 복제본 조건을 파티션 및 지역 복구와 구분합니다.",
    ),
    "740f2c1c": (
        "Select the exact APIM classic or v2 tier's supported zone mode and capacity. Classic automatic support, explicit manual zone selection, and a single-zone pin have different meanings; primary management/portal and secondary gateway scope must remain distinct.",
        "정확한 APIM classic 또는 v2 계층이 지원하는 영역 모드와 용량을 선택합니다. classic 자동 지원, 명시적 수동 선택과 단일 영역 고정은 의미가 다릅니다. 주 지역 관리·포털과 보조 지역 게이트웨이의 범위를 구분합니다.",
    ),
    "1c6c97d7": (
        "Provide scoped paths to current required AVD destinations using supported service/FQDN tags and effective-route checks. The recommendation is not permission to add a blanket Internet route, bypass inspection for all traffic or invent a fixed control-plane subnet.",
        "지원 서비스 및 FQDN 태그와 실제 경로 확인으로 현재 필수 AVD 대상에 제한된 경로를 제공합니다. 전체 인터넷 경로 추가, 모든 트래픽의 검사 우회 또는 고정 관리 서브넷 가정을 허용하는 권고가 아닙니다.",
    ),
    "9ec5b4c8": (
        "Deploy AVS stretched clusters only through the supported paired-zone private-cloud and reserved-quota path. Validate host counts, vSAN storage policies and both-zone network paths; a storage mirroring claim is not an application RPO or universal SLA guarantee.",
        "AVS 확장 클러스터는 지원되는 두 영역 프라이빗 클라우드와 예약 할당량 경로로 배포합니다. 호스트 수, vSAN 정책과 양쪽 영역 네트워크를 확인하며 저장소 미러링을 애플리케이션 RPO나 공통 SLA 보장으로 해석하지 않습니다.",
    ),
    "38721758": (
        "This Disabled APRL recommendation is historical, not an active ASR mandate or a product-support denial. Choose reproducible host recreation or currently supported VM replication for the actual AVD state model; ASR is not a synonym for independent backup.",
        "이 Disabled APRL 권고는 과거 참고이며 활성 ASR 지시나 제품 미지원 선언이 아닙니다. 실제 AVD 상태 모델에 따라 호스트 재생성 또는 현재 지원되는 VM 복제를 선택합니다. ASR은 독립 백업과 같은 뜻이 아닙니다.",
    ),
    "a18d60f8": (
        "Repair ETL with a validated retained Delta version, not table history alone. Preview the historical data before an approved replay or RESTORE, and reconcile writers, checkpoints and downstream outputs; this is not automatic workflow rollback.",
        "테이블 이력만 보지 말고 보존되어 실제 읽을 수 있는 Delta 버전으로 ETL을 복구합니다. 승인된 재실행이나 RESTORE 전에 데이터를 확인하고 쓰기, 체크포인트와 하위 출력을 조정합니다. 자동 워크플로 롤백이 아닙니다.",
    ),
    "c15b2b73": (
        "Select a named FSLogix baseline appropriate to Standard, Cloud Cache and session concurrency. Validate effective settings, permissions and existing profile attachment; do not copy naming or profile-deletion recommendations into a live deployment without migration protection.",
        "Standard, Cloud Cache와 세션 동시성에 맞는 이름이 정해진 FSLogix 기준을 선택합니다. 실제 설정, 권한과 기존 프로필 연결을 확인하고 이전 보호 없이 이름이나 프로필 삭제 권고를 운영 환경에 복사하지 않습니다.",
    ),
    "4884cada": (
        "Build an OS/protocol/architecture-specific SAP-on-ANF timeout matrix. NFS behavior, SAP keepalive, Pacemaker operation limits and fencing are separate; example resource-operation seconds are not universal SAP or NFS defaults.",
        "OS, 프로토콜과 아키텍처별 SAP 및 ANF 시간 제한 표를 만듭니다. NFS 동작, SAP keepalive, Pacemaker 작업 제한과 펜싱은 별개이며 예제의 리소스 작업 시간은 공통 SAP 또는 NFS 기본값이 아닙니다.",
    ),
    "6648fe61": (
        "Configure HANA system replication, Pacemaker resource ownership, fencing and virtual client access as one certified-stack contract. Select the matching OS/HANA/resource-agent guide rather than inventing universal agent parameters or disabling safety controls.",
        "HANA 시스템 복제, Pacemaker 리소스 소유권, 펜싱과 가상 클라이언트 접근을 인증된 구성의 한 계약으로 설정합니다. 공통 에이전트 값을 만들거나 안전장치를 끄지 말고 해당 OS, HANA와 리소스 에이전트 문서를 선택합니다.",
    ),
    "9d8f6678": (
        "Configure ASCS/ERS using the matching OS, ENSA and shared-filesystem design. Simple mount and classic cluster-controlled mounts have different ownership contracts; central-service HA, HANA replication and shared-storage protection are not interchangeable.",
        "OS, ENSA와 공유 파일시스템 설계에 맞춰 ASCS/ERS를 설정합니다. 단순 마운트와 classic 클러스터 제어 마운트는 소유권 계약이 다릅니다. 중앙 서비스 HA, HANA 복제와 공유 저장소 보호를 서로 대체하지 않습니다.",
    ),
    "ee4dc309": (
        "Protect SAP shared-directory contents with a storage-specific recovery mechanism. Current SAP guidance explicitly excludes mounted NFS data from ASR VM/disk replication; monitoring alone is not protection, despite the pinned description's monitoring emphasis.",
        "저장소별 복구 기능으로 SAP 공유 디렉터리 내용을 보호합니다. 현재 SAP 문서는 ASR VM·디스크 복제에 NFS 마운트 데이터가 포함되지 않는다고 명시합니다. 과거 설명이 모니터링을 강조해도 모니터링만으로 보호되지는 않습니다.",
    ),
    "c041d596": (
        "Treat the APRL title's 4000 as historical Citrix Managed Azure context, not an Azure-wide quota. The current public Citrix DaaS Standard for Azure page lists 5000 VDAs per subscription; select the actual product, subscription model and contract before applying any limit.",
        "APRL 제목의 4000은 과거 Citrix Managed Azure 맥락이며 Azure 공통 할당량이 아닙니다. 현재 Citrix DaaS Standard for Azure 공개 페이지는 구독당 VDA 5000개를 제시합니다. 한도를 적용하기 전에 실제 제품, 구독 모델과 계약을 확인합니다.",
    ),
}

BENEFITS = {
    "e7dbd21f": "An explicit unmatched-message policy avoids accidental telemetry loss while preserving intentional filtering.",
    "98bd7098": "Separating metadata and data-plane continuity prevents unnecessary relocation and targets the actual regional failure dependency.",
    "63491f70": "Automatic zonal redundancy supports eligible registry data-plane continuity; correctly interpreting legacy fields avoids false findings and unnecessary registry changes.",
    "84636c6c": "Correct tier and capacity interpretation supports zonal resilience while client retry and checkpoint design preserve processing continuity.",
    "b376281d": "Appropriate replicas improve query/indexing resilience without claiming exact zone placement or treating the index as primary backup.",
    "740f2c1c": "A tier-specific zone design preserves available gateway capacity and accurately scopes management and portal continuity.",
    "1c6c97d7": "Scoped supported connectivity preserves AVD access without unnecessarily weakening unrelated network controls.",
    "9ec5b4c8": "A supported stretched topology improves in-region storage resilience while making capacity, policy and network prerequisites explicit.",
    "38721758": "An explicit historical/current distinction supports a suitable AVD recovery plan without conflating replication, backup and host recreation.",
    "a18d60f8": "Validated historical data and controlled reconciliation can repair ETL results without silently losing or duplicating downstream business state.",
    "c15b2b73": "A selected supported baseline makes host behavior consistent while preserving existing profile data and access.",
    "4884cada": "Coordinated supported timeout layers reduce premature cluster recovery and unbounded I/O stalls.",
    "6648fe61": "A coherent supported HANA HA contract enables safe ownership transitions and observable application recovery.",
    "9d8f6678": "A supported ASCS/ERS design preserves central-service ownership and enqueue recovery without mixing incompatible storage models.",
    "ee4dc309": "An actual shared-file recovery copy and tested mount sequence protect SAP dependencies that VM replication alone omits.",
    "c041d596": "Product-scoped capacity planning avoids both obsolete ceilings and unsupported assumptions about Citrix licensing or Azure capacity.",
}


def apply_resolution(entry: dict[str, Any]) -> None:
    prefix = entry["recommendation_id"][:8]
    resolution = RESOLUTIONS.get(prefix)
    if resolution is None:
        return
    korean = RESOLUTIONS_KO[prefix]
    entry["title"] = text(TITLES[prefix])
    entry["summary"] = text(*SUMMARIES[prefix])
    entry["benefits"] = text(BENEFITS[prefix])
    entry["rationale"] = text(*resolution["explanation"])
    entry["configuration"] = {
        "before": [
            text(resolution["before"], korean["before"]),
            text(
                "The actual scope and prerequisites have not yet been mapped to this recommendation's qualified mechanism.",
                "실제 범위와 선행 조건을 이 권고의 조건부 원리에 아직 매핑하지 않았습니다.",
            ),
        ],
        "after": [
            text(resolution["after"], korean["after"]),
            text(
                "Current eligibility, effective configuration and independently observed workload behavior are recorded separately.",
                "현재 요건 충족 여부, 실효 구성, 독립적으로 관측한 워크로드 동작을 별도로 기록합니다.",
            ),
        ],
    }
    entry["implementation_steps"] = [
        text(en, ko) for en, ko in zip(resolution["actions"], korean["actions"], strict=True)
    ]
    entry["verification_steps"] = [
        *[text(en, ko) for en, ko in zip(resolution["checks"], korean["checks"], strict=True)],
        text(
            "Keep any existing blocked, manual, disabled or unsupported assessment status unchanged until its own evidence is sufficient. This guide grants no execution approval.",
            "각 평가의 근거가 충분해질 때까지 기존 차단, 수동, 비활성, 미지원 평가 상태를 유지합니다. 이 설명은 실행을 승인하지 않습니다.",
        ),
    ]
    historical = [
        caution
        for caution in entry["cautions"]
        if caution["en"].startswith("This recommendation is Disabled")
    ]
    entry["cautions"] = [
        *[text(en, ko) for en, ko in zip(resolution["limits"], korean["limits"], strict=True)],
        text(
            "Public documentation reviewed on 2026-10-30. These are conditional instructional requirements, not claims about the current installation. Missing deployment observations remain unknown; changes and failure exercises need their own approval.",
            "2026-10-30에 공개 문서를 검토했습니다. 이는 조건부 안내 요구사항이며 현재 설치 상태에 대한 주장이 아닙니다. 관측하지 않은 배포 상태는 미확정으로 유지하고 변경과 장애 훈련은 별도 승인을 받아야 합니다.",
        ),
        *historical,
    ]
    known_urls = {source["url"] for source in entry["sources"]}
    entry["sources"].extend(
        {"kind": "learn", "url": url, "label": text("Current scoped official documentation")}
        for url in resolution["urls"]
        if url not in known_urls
    )
    vendor_url = resolution.get("vendor_url")
    if vendor_url and vendor_url not in known_urls:
        entry["sources"].append(
            {
                "kind": "vendor",
                "url": vendor_url,
                "label": text(
                    "Citrix DaaS Standard for Azure limits",
                    "Citrix DaaS Standard for Azure 한도",
                ),
            }
        )
    nodes, edges = graph(resolution["nodes"], resolution["edges"])
    details = qualified_node_details(prefix, nodes)
    entry["diagram"] = {
        "id": f"qualified-{prefix}",
        "kind": entry["diagram"]["kind"],
        "title": text(*FIGURE_TITLES[prefix]),
        "description": text(
            "A repository-authored conditional concept, not an observed deployment. "
            "Full requirements and verification remain in the guide text.",
            "실제 배포를 관찰한 결과가 아닌 저장소 작성 조건부 개념도입니다. "
            "전체 요구사항과 검증 방법은 가이드 본문에 설명합니다.",
        ),
        "nodes": [
            {
                "id": identity,
                "label": text(label, QUALIFIED_LABELS_KO.get(label) or LABELS_KO.get(label)),
                "detail": details[identity],
                "role": role,
            }
            for identity, label, _ko, role in nodes
        ],
        "edges": [
            {
                "from": start,
                "to": end,
                "label": text(label, QUALIFIED_EDGES_KO.get(label) or EDGES_KO.get(label)),
                "style": style,
            }
            for start, end, label, style in edges
        ],
    }


def resolution_report(controls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    identities = {control["id"][:8]: control["id"] for control in controls}
    return [
        {
            "recommendation_id": identities[prefix],
            "resolution": "Rewritten primary summary and benefit, scoped mechanism explanation, "
            "three implementation steps, three verification questions and an "
            "individually authored conditional diagram.",
            "reviewed_public_sources": resolution["urls"],
            "documentation_reviewed_on": "2026-10-30",
            "vendor_source": resolution.get("vendor_url"),
            "deployment_prerequisites": resolution["checks"],
            "runtime_validation": "not_performed",
        }
        for prefix, resolution in sorted(RESOLUTIONS.items())
    ]
