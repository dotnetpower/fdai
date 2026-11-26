"""Current-document resolutions for network, metadata and zone recommendations."""
# ruff: noqa: E501

RESOLUTIONS = {
    "e7dbd21f": {
        "explanation": (
            "The pinned title describes a disabled fallback route, while its description warns about lost unmatched messages. Current IoT Hub documentation defines fallback as the path for messages that match no configured routing query. With ordinary fallback configuration these reach the built-in messages/events endpoint only when fallback is enabled. This is a delivery-policy decision, not an instruction to disable fallback.",
            "고정된 제목은 비활성 대체 경로를 가리키지만 설명은 미일치 메시지의 유실을 경고합니다. 현재 IoT Hub 문서에서 대체 경로는 어떤 라우팅 쿼리에도 일치하지 않는 메시지의 경로입니다. 일반 구성에서는 활성화해야 기본 messages/events 엔드포인트로 전달됩니다. 이는 전달 정책의 선택이며 비활성화 지시가 아닙니다.",
        ),
        "before": "Fallback state and unmatched-message expectations are unreviewed; the historical title is treated as an imperative.",
        "after": "Fallback enablement and destination are explicitly selected from the required delivery contract, with matched and unmatched messages tested separately.",
        "actions": [
            "Inventory all enabled route conditions, sources and endpoints and identify whether messages/events has an explicit route. Once routes exist, do not assume the built-in endpoint still receives every message.",
            "If unmatched telemetry must be retained, plan an enabled fallback route to the supported intended destination. If intentional filtering requires disabling fallback, document accepted message loss and owner approval instead of calling disablement universally compliant.",
            "Review custom FallbackRouteProperties separately if using a nondefault endpoint; validate destination authorization, health and capacity before any approved route change.",
        ],
        "checks": [
            "Does a known matching message reach each intended matching endpoint without unexplained duplicates?",
            "Does a known unmatched message reach the selected fallback destination when enabled, and is intentional nondelivery explicit when disabled?",
            "After deletion of ordinary routes, is fallback still enabled if all telemetry must reach the built-in endpoint? Inspect delivery failures and destination ingestion, not only an enabled flag.",
        ],
        "limits": [
            "The source title-description polarity conflict remains historical provenance, but the instructional interpretation is now explicit. A fallback route does not repair an unavailable matching custom endpoint."
        ],
        "urls": [
            "https://learn.microsoft.com/en-us/azure/iot-hub/iot-hub-devguide-messages-d2c#fallback-route"
        ],
        "nodes": "message|Device telemetry|subject;queries|Enabled route conditions|configuration;custom|Matching custom endpoints|dependency;fallback|Fallback enablement and destination|configuration;builtin|Unmatched-message destination|outcome;loss|Explicitly accepted unmatched-message loss|outcome;evidence|Matched and unmatched delivery observations|evidence",
        "edges": "message>queries|evaluates route conditions|solid;queries>custom|matching messages|solid;queries>fallback|messages matching no route|solid;fallback>builtin|only when fallback permits delivery|solid;fallback>loss|disabled fallback requires accepted loss contract|dashed;evidence>custom|checks matching-message delivery|dashed;evidence>builtin|checks unmatched-message outcome|dashed",
    },
    "98bd7098": {
        "explanation": (
            "A resource group's location selects where its management metadata is stored; contained resources may be in different regions. Current ARM documentation describes transparent rerouting of control-plane requests to a backup region. That does not fail over resource data planes, and matching a group's region is not a universal relocation requirement.",
            "리소스 그룹 위치는 관리 메타데이터의 저장 지역을 정하며 포함 리소스는 다른 지역에 있을 수 있습니다. 현재 ARM 문서는 관리 요청을 백업 지역으로 투명하게 전환한다고 설명합니다. 이 기능은 리소스 데이터 경로를 장애 조치하지 않으며 그룹과 지역을 맞추려는 이유만으로 모든 리소스를 이전할 필요는 없습니다.",
        ),
        "before": "Group metadata location, resource data-plane location and management-request continuity are conflated.",
        "after": "Metadata placement has a documented management and compliance rationale; each workload resource retains its independently justified regional design.",
        "actions": [
            "Inventory group metadata location separately from each resource's location, nonregional status and actual data-plane dependencies.",
            "For a new group choose metadata location using control-operation origin, compliance and workload management needs. For an existing group, assess supported management-continuity behavior before proposing any group or resource restructuring.",
            "Document ARM backup-region handling separately from application regional recovery. Do not propose moving resources solely to equalize location strings.",
        ],
        "checks": [
            "Which location stores group metadata, and which regions actually serve each resource's data-plane requests?",
            "Does the recorded management-continuity design distinguish ARM transparent control-plane rerouting from an application or storage failover?",
            "Do regional workload tests or retained evidence validate data-plane recovery independently of management API acceptance? Record any compliance-specific metadata placement constraint.",
        ],
        "limits": [
            "The pinned alignment recommendation is not a universal resource relocation command. ARM backup-region availability is a service behavior, not proof that the workload's deployment region is healthy."
        ],
        "urls": [
            "https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/overview#which-location-should-i-use-for-my-resource-group"
        ],
        "nodes": "operator|Management client|subject;arm|ARM control plane|dependency;metadata|Group metadata primary region|configuration;backup|Metadata backup region|dependency;provider|Resource provider|dependency;data|Resource data plane|outcome;evidence|Separate management and data observations|evidence",
        "edges": "operator>arm|management operation|solid;arm>metadata|uses group management metadata|solid;metadata>backup|transparent ARM recovery behavior|dashed;arm>provider|authorized control-plane operation|solid;provider>data|manages resource, not data-plane failover|dashed;evidence>arm|checks management continuity|dashed;evidence>data|checks workload continuity independently|dashed",
    },
    "63491f70": {
        "explanation": (
            "Current ACR documentation says zone redundancy is automatic for all registry tiers in supported regions, including existing registries. The legacy zoneRedundancy property can show Disabled and no longer controls this behavior. Geo-replicas in supported regions are automatic too, while ACR Tasks currently have a different availability-zone scope.",
            "현재 ACR 문서에 따르면 지원 지역의 모든 레지스트리 계층과 기존 레지스트리에 영역 중복이 자동 적용됩니다. 이전 zoneRedundancy 속성은 Disabled로 표시되어도 현재 동작을 제어하지 않습니다. 지원 지역의 지역 복제본에도 자동 적용되지만 ACR Tasks의 가용성 영역 범위는 다릅니다.",
        ),
        "before": "A legacy Disabled property is interpreted as missing protection and a Premium-only toggle is prescribed.",
        "after": "Registry and replica regional eligibility determine documented data-plane zone behavior; legacy flags and Tasks are interpreted separately.",
        "actions": [
            "Record the registry and each geo-replica region and compare them with the current supported-region list. Do not require Premium solely to obtain current registry data-plane zone redundancy.",
            "Keep compatible legacy IaC settings if required by the existing deployment contract, but do not claim writing zoneRedundancy Enabled newly creates protection or that Disabled removes it.",
            "If the region lacks zone support, assess an approved image import or transfer migration to an eligible region; separately design Tasks and application recovery.",
        ],
        "checks": [
            "Is the actual registry or replica region supported, regardless of the displayed zoneRedundancy field?",
            "Do authenticated push and pull paths, replicated artifact digests and transient-error handling work in the intended networks?",
            "Are ACR Tasks excluded from the registry data-plane zone claim, and are separate cross-region and retained-artifact recovery requirements documented?",
        ],
        "limits": [
            "Do not classify a supported-region registry as unprotected from the legacy Disabled value alone. Zone redundancy is not geo-replication or a backup of deleted images."
        ],
        "urls": ["https://learn.microsoft.com/en-us/azure/container-registry/zone-redundancy"],
        "nodes": "registry|Registry image data plane|subject;region|Supported region eligibility|configuration;zones|Managed zone-distributed replicas|dependency;legacy|Legacy zoneRedundancy field|configuration;tasks|ACR Tasks scope|dependency;evidence|Region and push/pull observations|evidence",
        "edges": "region>registry|determines documented automatic coverage|solid;registry>zones|managed redundancy across zones|solid;legacy>registry|legacy field no longer controls coverage|dashed;tasks>registry|separate feature scope, not covered by this claim|dashed;evidence>region|checks actual regional eligibility|dashed;evidence>registry|checks data-plane requests separately|dashed",
    },
    "84636c6c": {
        "explanation": (
            "Current Event Hubs reliability documentation describes automatic zone support for namespaces in supported regions, rather than a portal-versus-IaC toggle. Standard and Premium need no extra zone configuration; Dedicated requires at least three capacity units. Events, metadata and configuration are synchronously replicated across zones, but clients still need retries and idempotent checkpoint recovery.",
            "현재 Event Hubs 복원력 문서는 포털과 IaC의 설정 차이가 아니라 지원 지역 네임스페이스의 자동 영역 지원을 설명합니다. Standard와 Premium은 별도 영역 설정이 필요 없고 Dedicated는 최소 3개 CU가 필요합니다. 이벤트, 메타데이터와 구성을 영역 간 동기 복제하지만 클라이언트 재시도와 멱등한 체크포인트 복구도 필요합니다.",
        ),
        "before": "Historical portal and IaC defaults are used as the current zone-eligibility decision.",
        "after": "Region, actual tier and Dedicated capacity establish documented zone eligibility; client continuity and checkpoint behavior are verified independently.",
        "actions": [
            "Record namespace region, tier and effective capacity units. Use current reliability requirements rather than inferring protection from historical deployment-tool defaults.",
            "For Dedicated deployments confirm at least three CUs and supported regional capacity. For supported Standard or Premium namespaces do not prescribe an unnecessary zone-enablement change.",
            "Configure supported SDK retries, durable consumer checkpoints and idempotent processing, and keep regional disaster recovery separate from in-region synchronous zone replication.",
        ],
        "checks": [
            "Is the namespace region supported, and does Dedicated meet the three-CU prerequisite where applicable?",
            "Do retained producer and consumer observations show bounded reconnection and replay without unexplained duplicate side effects?",
            "Are zone-managed failover, consumer checkpoint recovery and any cross-region recovery configuration recorded as separate mechanisms?",
        ],
        "limits": [
            "Service-managed zone failover can drop active requests briefly; current documentation still calls for client retries. Neither a static flag nor a zone claim establishes regional DR readiness."
        ],
        "urls": [
            "https://learn.microsoft.com/en-us/azure/reliability/reliability-event-hubs#resilience-to-availability-zone-failures"
        ],
        "nodes": "producer|Event producer|subject;namespace|Namespace tier and regional eligibility|configuration;replicas|Synchronous zone replicas|dependency;consumer|Consumer with durable checkpoint|dependency;evidence|Acknowledgement, reconnect and replay observations|evidence",
        "edges": "producer>namespace|sends events with bounded retry|solid;namespace>replicas|synchronously retains acknowledged events|solid;replicas>consumer|serves partition reads|solid;consumer>namespace|resumes from durable checkpoint|dashed;evidence>namespace|checks tier, region and Dedicated CUs|dashed;evidence>consumer|checks replay idempotency|dashed",
    },
    "b376281d": {
        "explanation": (
            "Current AI Search documentation automatically enables zone redundancy for eligible Basic-or-higher services in supported regions with at least two replicas. It attempts to spread replicas across zones but does not guarantee exact placement. The SLA's two replicas for read-only and three for read-write workloads are distinct from a universal three-zone placement guarantee.",
            "현재 AI Search 문서는 지원 지역의 Basic 이상 서비스에 복제본이 둘 이상이면 영역 중복이 자동 적용된다고 설명합니다. 영역별 분산을 시도하지만 정확한 배치는 보장하지 않습니다. 읽기 전용 SLA의 복제본 2개와 읽기·쓰기 SLA의 3개는 모든 복제본이 특정 3개 영역에 배치된다는 보장과 다릅니다.",
        ),
        "before": "Replica count alone is treated as proof of exact zone placement or a universal SLA.",
        "after": "Region, tier and replica prerequisites are documented, and requested read/write reliability is distinguished from best-effort placement.",
        "actions": [
            "Identify whether the workload is read-only or includes indexing writes, then record actual tier, replica count, region support and capacity constraints.",
            "Plan at least two replicas for eligible production resilience, and assess three or more for the documented read-write SLA requirement; validate current contract applicability before claiming an SLA.",
            "Configure transient-fault handling for both queries and indexing, preserve the original source data and document independent regional search-service and index-rebuild recovery.",
        ],
        "checks": [
            "Do Basic-or-higher tier, supported region and at least two replicas hold for this service?",
            "Does the selected count satisfy the intended read-only or read-write requirement without asserting exact replica-to-zone mapping?",
            "Do query and indexing requests recover after transient interruptions, and can indexes be recreated from authoritative source data rather than treating Search as the only data store?",
        ],
        "limits": [
            "Exact replica placement is not guaranteed. Partitions are storage capacity, not replicas; extra replicas are neither a backup nor automatic multi-region failover."
        ],
        "urls": [
            "https://learn.microsoft.com/en-us/azure/reliability/reliability-ai-search#resilience-to-availability-zone-failures"
        ],
        "nodes": "client|Search queries and indexing|subject;service|Eligible Search tier and replica count|configuration;primary|Primary write replica|dependency;reads|Read replicas with managed zone placement|dependency;source|Authoritative source data|dependency;evidence|Eligibility and request observations|evidence",
        "edges": "client>service|query or indexing operation|solid;service>primary|writes through primary replica|solid;service>reads|routes read workload|solid;source>service|rebuilds searchable indexes|dashed;evidence>service|checks tier, region and replica prerequisites|dashed;evidence>reads|does not infer exact zone placement|dashed",
    },
    "740f2c1c": {
        "explanation": (
            "Current APIM guidance distinguishes classic Premium automatic and manual zone support from v2 tier configuration. Classic Premium automatic placement can spread the two compute resources of a single unit across zones; multiple units improve remaining capacity. In the primary region zone replication covers gateway, management plane and developer portal; secondary regions contain gateway units only. Units themselves size gateways, not management components.",
            "현재 APIM 문서는 classic Premium의 자동·수동 영역 지원과 v2 계층 구성을 구분합니다. classic Premium의 자동 배치는 단일 단위의 두 컴퓨팅 리소스를 영역 간 분산할 수 있고 여러 단위는 잔여 용량을 늘립니다. 주 지역의 영역 복제에는 게이트웨이, 관리 계층과 개발자 포털이 포함되지만 보조 지역에는 게이트웨이 단위만 있습니다. 단위 수는 관리 구성 요소가 아니라 게이트웨이 용량을 정합니다.",
        ),
        "before": "Premium labels, unit counts and zone selection are conflated across classic and v2 tiers.",
        "after": "Exact tier/platform, primary versus secondary role and automatic versus manual zone mode have explicit supported interpretation.",
        "actions": [
            "Read the actual APIM tier, platform, region role, unit count and zone selection. Select the matching current classic or v2 documentation branch.",
            "For classic Premium distinguish unspecified-zone automatic support from explicit manual selection; selecting one zone is zonal, not zone-redundant. Review remaining gateway capacity before changing units or zones.",
            "For Premium v2 or Standard v2 use their supported zone-redundancy configuration and do not infer classic multiregion support. Review primary management/portal continuity separately from secondary gateway availability.",
        ],
        "checks": [
            "Which tier and platform branch applies, and is the instance automatic, manually zone-redundant, or pinned to one zone?",
            "Does remaining gateway capacity support expected demand if a zone is unavailable, without claiming guaranteed unit placement?",
            "Are management plane and developer portal claims limited to documented primary-region scope, with secondary-region gateway-only behavior explicit?",
        ],
        "limits": [
            "A single selected zone is not redundant. Do not transfer classic Premium multiregion support to v2 tiers or use gateway unit counts as a measurement of management-plane replicas.",
            "These managed APIM service claims do not configure self-hosted gateways, whose hosting infrastructure needs its own resilience design.",
        ],
        "urls": [
            "https://learn.microsoft.com/en-us/azure/reliability/reliability-api-management#resilience-to-availability-zone-failures"
        ],
        "nodes": "clients|API consumers|subject;mode|Exact APIM tier and zone mode|configuration;gateway|Zone-distributed gateway capacity|dependency;primary|Primary management plane and portal|dependency;secondary|Secondary gateways only|dependency;evidence|Tier, mode and request observations|evidence",
        "edges": "clients>gateway|API request path|solid;mode>gateway|controls supported zone mode and capacity|solid;mode>primary|defines documented primary-region scope|solid;mode>secondary|classic supported regional gateway scope|dashed;evidence>mode|distinguishes classic, v2 and single-zone pinning|dashed;evidence>gateway|checks surviving capacity and requests|dashed",
    },
    "1c6c97d7": {
        "explanation": (
            "AVD connectivity depends on current required FQDNs, service tags and outbound protocols, not a fictional fixed control-plane subnet. WindowsVirtualDesktop service tags and the corresponding FQDN tag simplify supported rules, but do not replace all identity, storage, monitoring or update dependencies. A direct route is a scoped network-design choice and never a blanket permission to bypass inspection.",
            "AVD 연결에는 고정된 관리 서브넷을 가정하지 말고 현재 필수 FQDN, 서비스 태그와 아웃바운드 프로토콜을 사용해야 합니다. WindowsVirtualDesktop 서비스 태그와 해당 FQDN 태그는 규칙을 단순화하지만 신원, 저장소, 모니터링과 업데이트 의존성을 모두 대체하지는 않습니다. 직접 경로는 범위가 정해진 설계 선택이며 전체 검사 우회 권한이 아닙니다.",
        ),
        "before": "A generic Internet route or stale fixed address list is proposed for all session-host traffic.",
        "after": "Required AVD and supporting-service destinations have reviewed effective paths and security rules; unrelated traffic retains its intended controls.",
        "actions": [
            "Select the current required-endpoint list for the actual Azure cloud and identify control-plane, identity, monitoring, update and platform dependencies separately.",
            "Review effective UDR, NSG and firewall paths and use supported dynamic service/FQDN tags where applicable; approve narrowly scoped route changes rather than a universal Internet next hop.",
            "Keep required Azure platform traffic unintercepted as documented and distinguish outbound AVD connectivity from separately configured RDP Shortpath UDP requirements.",
        ],
        "checks": [
            "Does the AVD Agent URL Tool or retained equivalent validate every required endpoint category from the actual session hosts?",
            "Do effective routes and security rules preserve the reviewed path for each required destination without exposing unrelated outbound traffic?",
            "Are identity, DNS, storage and update dependencies verified independently, and are no unnecessary inbound ports opened for ordinary AVD control-plane access?",
        ],
        "limits": [
            "Do not treat WindowsVirtualDesktop as a complete substitute for every required service tag or endpoint. No customer endpoints or copied address inventories are embedded in this guide."
        ],
        "urls": ["https://learn.microsoft.com/en-us/azure/virtual-desktop/required-fqdn-endpoint"],
        "nodes": "host|Session host|subject;policy|Scoped route and security policy|configuration;avd|Required AVD service destinations|dependency;support|Identity, updates and monitoring|dependency;platform|Required Azure platform traffic|dependency;evidence|Endpoint-tool and effective-path observations|evidence",
        "edges": "host>policy|outbound traffic by destination category|solid;policy>avd|supported dynamic AVD path|solid;policy>support|separately required service paths|solid;host>platform|documented direct platform handling|solid;evidence>policy|checks no blanket inspection bypass|dashed;evidence>avd|validates required endpoint reachability|dashed",
    },
}
