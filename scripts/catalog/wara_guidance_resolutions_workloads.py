"""Scoped current-document guidance for historical and workload-specific controls."""
# ruff: noqa: E501

RESOLUTIONS = {
    "9ec5b4c8": {
        "explanation": (
            "An AVS stretched cluster distributes the vSAN datastore across two availability zones using supported dual-site storage policies. The current deployment guide requires a separately enabled stretched-cluster private-cloud deployment and reserved host quota; it is not an in-place switch for any existing private cloud. Storage mirroring, local failure tolerance and network path diversity have separate prerequisites.",
            "AVS 확장 클러스터는 지원되는 이중 사이트 저장소 정책으로 vSAN 데이터스토어를 두 가용성 영역에 분산합니다. 현재 배포 문서는 확장 클러스터 전용으로 허용된 프라이빗 클라우드 배포와 예약 호스트 할당량을 요구합니다. 임의의 기존 클라우드에서 켜는 설정이 아닙니다. 저장소 미러링, 로컬 장애 허용과 네트워크 경로 분리는 별도 조건입니다.",
        ),
        "before": "An ordinary private cloud or an unsupported host/policy combination is assumed convertible by toggling zone redundancy.",
        "after": "An eligible stretched-cluster deployment has reserved paired-zone capacity, supported vSAN PFTT/SFTT policies and independently resilient network connectivity.",
        "actions": [
            "Select the current stretched-cluster deployment path and published region eligibility, and request the required dedicated subscription enablement and reserved host quota through the documented process. Do not copy any operator identity into this catalog.",
            "Plan paired host counts and expansion using current supported limits. The reviewed guide specifies an initial even host count from six to sixteen; verify the current contract and required hosts per zone for the chosen policy before creating anything.",
            "Select Hosts in two availability zones at deployment, review Dual Site Mirroring and local SFTT requirements, and arrange connectivity to both AZs rather than a single shared peering path.",
        ],
        "checks": [
            "Does the actual private-cloud deployment type and approved quota identify the supported stretched-cluster path rather than an ordinary existing cloud?",
            "Do actual per-zone host capacity and vSAN storage policies support the selected local failure-tolerance level?",
            "Does retained authorized failure evidence verify datastore access, network reachability and application recovery separately? Limit synchronous storage/RPO and SLA statements to the eligible component and current contract.",
        ],
        "limits": [
            "Do not promise an application RPO of zero from a vSAN storage policy, and do not invent an in-place conversion or a universal SLA from the pinned source."
        ],
        "urls": [
            "https://learn.microsoft.com/en-us/azure/azure-vmware/deploy-vsan-stretched-clusters"
        ],
        "nodes": "cloud|Eligible stretched private cloud|subject;quota|Reserved paired-zone host quota|configuration;first|Zone A vSAN hosts|dependency;second|Zone B vSAN hosts|dependency;policy|Dual-site and local failure policy|configuration;paths|Independent AZ network paths|dependency;evidence|Storage, network and application observations|evidence",
        "edges": "quota>cloud|enables supported new deployment path|solid;cloud>first|deploys paired host capacity|solid;cloud>second|deploys paired host capacity|solid;policy>first|defines site and local tolerance|solid;first>second|supported synchronous vSAN mirroring|solid;paths>cloud|must reach both AZs|solid;evidence>second|checks policy and failure behavior|dashed",
    },
    "38721758": {
        "explanation": (
            "This GUID remains Disabled in the pinned APRL catalog. It is historical planning content, not an active mandate or a claim that ASR is unsupported. Current AVD guidance treats session hosts, profiles, applications, user data and identity as separate customer responsibilities. ASR supports eligible AVD infrastructure VMs when the Azure-to-Azure prerequisites are met; replication and recovery points are not an independent backup of every dependency.",
            "이 GUID는 고정된 APRL에서 Disabled를 유지합니다. 과거 설계 참고이며 활성 지시나 ASR 미지원 선언이 아닙니다. 현재 AVD 문서는 세션 호스트, 프로필, 앱, 사용자 데이터와 신원을 별도 고객 책임으로 구분합니다. ASR은 Azure 간 복제 조건을 충족하는 AVD 인프라 VM을 지원하지만 복제와 복구 지점이 모든 의존성의 독립 백업인 것은 아닙니다.",
        ),
        "before": "Historical ASR wording is treated as a current instruction to replicate every session host and as a synonym for backup.",
        "after": "The historical lifecycle remains disabled, while a separately reviewed current BCDR plan chooses recreation or supported VM replication and protects profiles and data independently.",
        "actions": [
            "Classify session hosts as reproducible/stateless or containing required persistent state. Compare image-based regional recreation with supported ASR replication rather than forcing one method on every host pool.",
            "For a selected replication design validate the current support matrix for OS, disks, network, region or zone topology, vault and subscription constraints before proposing protection.",
            "Prepare recovery networking, host-pool registration and capacity plus independent FSLogix profile, application, identity and user-data recovery. Keep catalog lifecycle and evaluator state unchanged.",
        ],
        "checks": [
            "Does each protected VM meet the exact support matrix, and are replication health and recovery-point freshness observed?",
            "Does an authorized isolated test verify VM startup, host-pool registration, user sign-in, application access and profile attachment?",
            "Can persistent profiles and required data recover independently, and does the plan distinguish replication, retained backup and image-based recreation?",
        ],
        "limits": [
            "Disabled is historical recommendation lifecycle, not current product eligibility. A supported VM replication feature is neither automatic AVD disaster recovery nor permission to reactivate the recommendation."
        ],
        "urls": [
            "https://learn.microsoft.com/en-us/azure/virtual-desktop/disaster-recovery-concepts",
            "https://learn.microsoft.com/en-us/azure/site-recovery/azure-to-azure-support-matrix",
        ],
        "nodes": "hosts|Session-host state classification|subject;choice|Recreate or replicate decision|configuration;image|Versioned image and deployment definition|dependency;asr|Eligible ASR recovery points|dependency;target|Isolated recovered session hosts|outcome;profiles|Profiles, identity and application data|dependency;evidence|Registration and user-flow observations|evidence",
        "edges": "hosts>choice|identifies persistent state requirements|solid;choice>image|stateless recreation path|solid;choice>asr|separately supported replication path|solid;image>target|recreates host configuration|solid;asr>target|authorized test recovery|dashed;target>profiles|requires independent dependency recovery|solid;evidence>target|checks sign-in and profile attachment|dashed",
    },
    "a18d60f8": {
        "explanation": (
            "Delta time travel reads a previous table version identified by history, version or timestamp. Available transaction history alone does not establish recoverability: the required data files and applicable retention must still exist. RESTORE changes table state to an earlier version; it is a separate approved mutation, not automatic rollback of an ETL workflow or its downstream effects.",
            "Delta 시간 여행은 이력, 버전 또는 시각으로 선택한 이전 테이블을 조회합니다. 트랜잭션 이력이 보인다고 복구 가능한 것은 아니며 필요한 데이터 파일과 보존 조건이 남아 있어야 합니다. RESTORE는 테이블 상태를 이전 버전으로 바꾸는 별도 승인 작업이고 ETL 흐름이나 하위 부작용의 자동 롤백이 아닙니다.",
        ),
        "before": "A visible historic version or a successful ETL restart is assumed sufficient to repair data and all downstream results.",
        "after": "A retained recoverable version is validated read-only, then an approved replay or restore plan reconciles table state, job checkpoints and downstream outputs.",
        "actions": [
            "Inspect DESCRIBE HISTORY and identify the last known correct version or timestamp using the business failure boundary, not simply the latest available row.",
            "Check both transaction-log retention and data-file retention, including VACUUM or external deletion. Use read-only VERSION AS OF or TIMESTAMP AS OF validation before considering mutation.",
            "Choose controlled ETL replay, a corrective write or supported RESTORE for the exact table. Pause or coordinate writers and downstream consumers and plan checkpoint/output reconciliation and rollback.",
        ],
        "checks": [
            "Can the selected version actually be read with expected schema, row counts and business invariants, not merely listed in history?",
            "Does the proposed repair preserve required inputs and reconcile previously committed outputs and consumer checkpoints?",
            "After an approved repair, do table history, application invariants and downstream counts show the intended state without silent loss or duplicate side effects?",
        ],
        "limits": [
            "Retention is table/runtime-dependent; do not treat documented defaults as a universal recovery window. A missing data file cannot be recovered solely from table history."
        ],
        "urls": [
            "https://learn.microsoft.com/en-us/azure/databricks/tables/history",
            "https://learn.microsoft.com/en-us/azure/databricks/sql/language-manual/delta-restore",
        ],
        "nodes": "job|Failed ETL and business boundary|subject;history|Version and timestamp history|dependency;retention|Required retained logs and data files|configuration;preview|Read-only historical validation|evidence;repair|Approved replay or RESTORE choice|configuration;outputs|Table and downstream outputs|outcome",
        "edges": "job>history|selects last known correct state|solid;retention>preview|must retain actual required files|solid;history>preview|identifies candidate version|solid;preview>repair|supplies validated repair evidence|dashed;repair>outputs|controlled state change and reconciliation|solid;outputs>job|checkpoint and output consistency feedback|dashed",
    },
    "c15b2b73": {
        "explanation": (
            "The current FSLogix Standard example uses a single SMB VHDLocations path, one profile container, ProfileType 0 or unset for a single connection, and no custom redirections.xml. These are a named example baseline, not universal values for Cloud Cache, concurrent sessions or an existing deployment. Enabled and storage permissions are required; changing naming or profile-deletion settings can disrupt or remove existing profiles.",
            "현재 FSLogix Standard 예제는 하나의 SMB VHDLocations 경로, 단일 프로필 컨테이너, 단일 연결용 ProfileType 0 또는 미설정과 사용자 지정 redirections.xml 미사용을 기준으로 합니다. 이는 이름이 정해진 예제이며 Cloud Cache, 동시 세션이나 기존 배포의 공통 값은 아닙니다. Enabled와 저장소 권한이 필요하고 이름 또는 프로필 삭제 설정 변경은 기존 프로필을 끊거나 삭제할 수 있습니다.",
        ),
        "before": "Standard configuration is an undefined phrase, or recommended example values are copied over a live deployment without checking profile paths.",
        "after": "A selected documented baseline maps each host's effective settings to storage, permissions, session model and migration constraints.",
        "actions": [
            "Choose the Standard, Cloud Cache or other supported design before comparing settings. For the Standard example review Enabled=1, VHDLocations, single-container semantics and ProfileType=0 or unset; never insert real share paths into this corpus.",
            "Verify share and NTFS permissions, supported FSLogix/OS versions and antivirus exclusions. Inventory effective policy/registry sources and compare them across all intended session hosts.",
            "Treat FlipFlopProfileDirectoryName, SID/VHD naming patterns and DeleteLocalProfileWhenVHDShouldApply as migration-sensitive settings. Preserve existing profiles and obtain an explicit migration/rollback plan before changing them.",
        ],
        "checks": [
            "Does the selected baseline actually match single-connection Standard versus Cloud Cache or concurrent-session requirements?",
            "Can a representative authorized user attach the existing intended container with the correct permissions and no unexpected temporary or new empty profile?",
            "Do readback, FSLogix logs and controlled sign-out/sign-in demonstrate consistent settings and preserved user data on all host groups?",
        ],
        "limits": [
            "Recommended retry counts, size defaults and naming choices are example-scoped, not universal tuning. Do not enable profile deletion or rename existing containers merely to match a sample."
        ],
        "urls": [
            "https://learn.microsoft.com/en-us/fslogix/concepts-configuration-examples",
            "https://learn.microsoft.com/en-us/fslogix/reference-configuration-settings",
        ],
        "nodes": "hosts|Session-host effective configuration|subject;baseline|Selected Standard or Cloud Cache baseline|configuration;access|SMB share and NTFS permissions|dependency;container|Existing intended profile container|dependency;session|Validated user session|outcome;evidence|Policy readback and attachment logs|evidence",
        "edges": "baseline>hosts|defines design-specific settings|solid;hosts>access|authenticates authorized share access|solid;access>container|opens existing profile path|solid;container>session|attaches preserved user profile|solid;evidence>hosts|compares effective policy across hosts|dashed;evidence>session|checks no new empty or temporary profile|dashed",
    },
    "4884cada": {
        "explanation": (
            "SAP on ANF has several independent timeout layers: NFS/client behavior, SAP instance behavior, Pacemaker resource operations and fencing. Select the matching OS, NFS protocol and classic versus simple-mount architecture before taking values from a supported guide. A documented example operation timeout is not a universal NFS or SAP timeout.",
            "ANF 위 SAP에는 NFS 및 클라이언트 동작, SAP 인스턴스, Pacemaker 리소스 작업과 펜싱이라는 서로 다른 시간 제한 계층이 있습니다. 지원 문서의 값을 적용하기 전에 OS, NFS 프로토콜과 classic 또는 단순 마운트 구조를 선택해야 합니다. 예제의 리소스 작업 제한 시간이 모든 NFS나 SAP 작업의 공통 제한 시간은 아닙니다.",
        ),
        "before": "A single timeout number is proposed for every SAP, NFS, resource-agent and fencing layer.",
        "after": "A versioned baseline matrix records the source, setting, scope, expected value and rationale for each selected timeout layer.",
        "actions": [
            "Inventory SLES/RHEL release, SAP/ENSA version, ANF NFSv3 or NFSv4.1 and classic cluster-managed mounts versus simple mount. Select the exact supported architecture guide before editing parameters.",
            "Build a baseline matrix for NFS mount/client options, SAP keepalive behavior, Filesystem/SAPInstance start-stop-monitor operations and fencing. For example, the reviewed classic SUSE ANF guide shows Filesystem start/stop 60s and monitor timeout 40s with interval 20s; these are that example's resource operations, not universal NFS settings.",
            "Compare effective values with the selected guide and linked vendor support requirements. Plan one coordinated change with rollback and test application I/O during maintenance/reconnect without weakening fencing.",
        ],
        "checks": [
            "Can every effective timeout be traced to the chosen OS, protocol, resource agent and architecture rather than copied from a different stack?",
            "Do resource monitoring and failure detection allow supported recovery without premature fencing or an unbounded I/O stall?",
            "Does an authorized maintenance/failure exercise show SAP requests, NFS I/O and cluster transitions recover within the workload's agreed limits?",
        ],
        "limits": [
            "Do not use the example 60s/40s/20s values as global SAP or NFS defaults. Product-specific SAP/SUSE/RHEL support conditions remain deployment prerequisites, not a missing instructional baseline."
        ],
        "urls": [
            "https://learn.microsoft.com/en-us/azure/sap/workloads/high-availability-guide-suse-netapp-files",
            "https://learn.microsoft.com/en-us/azure/sap/workloads/high-availability-guide-rhel-netapp-files",
            "https://learn.microsoft.com/en-us/azure/sap/workloads/high-availability-guide-rhel-pacemaker",
        ],
        "nodes": "sap|SAP request and I/O path|subject;nfs|Selected NFS protocol and mount model|dependency;baseline|OS and architecture timeout matrix|configuration;agent|Pacemaker resource operations|dependency;fence|Supported fencing mechanism|dependency;evidence|I/O and transition timing|evidence",
        "edges": "sap>nfs|uses mounted shared storage|solid;baseline>nfs|selects protocol-specific client behavior|solid;baseline>agent|selects start, stop and monitor limits|solid;agent>fence|coordinates supported failure handling|solid;evidence>sap|measures request and I/O recovery|dashed;evidence>agent|checks no premature or stalled transition|dashed",
    },
    "6648fe61": {
        "explanation": (
            "HANA HA combines database system replication with Pacemaker ownership, fencing and a supported virtual access path. Current Learn guides require selecting the certified OS/VM/HANA combination and matching SUSE or RHEL cluster design. Replication alone does not elect a safe owner, and a generic cluster defaults list cannot replace the supported HANA resource-agent contract.",
            "HANA HA는 데이터베이스 시스템 복제와 Pacemaker 소유권, 펜싱 및 지원되는 가상 접근 경로를 결합합니다. 현재 Learn 문서는 인증된 OS, VM과 HANA 조합 및 해당 SUSE 또는 RHEL 설계를 선택하도록 요구합니다. 복제만으로 안전한 소유자를 정할 수 없으며 일반 클러스터 기본값 목록은 지원되는 HANA 리소스 에이전트 계약을 대신하지 못합니다.",
        ),
        "before": "A cluster exists, but database replication state, fencing and the selected HANA resource-agent baseline are not correlated.",
        "after": "A certified stack has one coherent replication, resource-agent, fencing and client-access configuration with tested safe role change.",
        "actions": [
            "Identify HANA revision, scale-up/scale-out design, OS release, certified VM and the selected vendor-supported HANA resource-agent implementation; choose its matching Learn and linked vendor baseline.",
            "Validate system replication mode/state and configure the supported topology/database resources, ordering, colocation, operation timeouts and fencing mechanism as one versioned contract. Choose Azure fencing or supported SBD design according to the actual platform.",
            "Review virtual hostname/IP and Standard Load Balancer probe/rule integration, remaining capacity and rollback. Never disable STONITH or remove quorum protection to make a demonstration pass.",
        ],
        "checks": [
            "Do the running resource agents, parameters and timeouts match the selected supported OS/HANA design rather than a different guide's sample?",
            "Are replication status, current primary ownership, fencing access and client routing mutually consistent?",
            "Does a separately approved isolated failover prove fencing, safe promotion, request recovery and no split brain, with measured RPO/RTO and failback evidence?",
        ],
        "limits": [
            "No universal HANA agent name, timeout or replication mode is imposed across every version. Missing observed stack or fencing access is a deployment prerequisite that keeps an assessment unknown, not a reason to invent values."
        ],
        "urls": [
            "https://learn.microsoft.com/en-us/azure/sap/workloads/sap-hana-high-availability",
            "https://learn.microsoft.com/en-us/azure/sap/workloads/sap-hana-high-availability-rhel",
            "https://learn.microsoft.com/en-us/azure/sap/workloads/high-availability-guide-suse-pacemaker",
            "https://learn.microsoft.com/en-us/azure/sap/workloads/high-availability-guide-rhel-pacemaker",
        ],
        "nodes": "client|HANA client virtual access|subject;primary|Current HANA primary|dependency;secondary|System-replication secondary|dependency;cluster|Supported HANA Pacemaker baseline|configuration;fence|Independent supported fencing|dependency;evidence|Replication, ownership and request records|evidence",
        "edges": "client>primary|routes to current safe owner|solid;primary>secondary|selected supported HANA replication mode|solid;cluster>primary|controls database resource ownership|solid;cluster>secondary|controls safe promotion|solid;cluster>fence|requires successful exclusion of unsafe owner|solid;evidence>cluster|checks role, quorum and fencing consistency|dashed;evidence>client|observes application recovery|dashed",
    },
    "9d8f6678": {
        "explanation": (
            "ASCS/ERS HA protects SAP central-service ownership and enqueue availability, not HANA database replication. Current SUSE guidance distinguishes new SLES 15 simple-mount designs from still-supported classic cluster-controlled filesystems. The selected OS, ENSA version and shared-storage design determine SAPInstance resources, constraints, virtual access and fencing requirements.",
            "ASCS/ERS HA는 SAP 중앙 서비스의 소유권과 enqueue 가용성을 보호하며 HANA 데이터베이스 복제가 아닙니다. 현재 SUSE 문서는 새 SLES 15 단순 마운트 설계와 계속 지원되는 classic 클러스터 제어 파일시스템을 구분합니다. OS, ENSA 버전과 공유 저장소 설계에 따라 SAPInstance 리소스, 제약, 가상 접근과 펜싱 조건이 달라집니다.",
        ),
        "before": "ASCS/ERS parameters are copied from a different OS, ENSA generation or shared-filesystem architecture.",
        "after": "A selected supported ASCS/ERS baseline coherently defines shared files, resources, constraints, fencing and client virtual access.",
        "actions": [
            "Identify SLES/RHEL release, SAP kernel and ENSA1/ENSA2, then select simple mount or the supported classic storage architecture. Do not mix mount ownership models.",
            "Validate shared filesystem accessibility and configure the selected SAPInstance resources, ASCS/ERS ordering and colocation, supported probes and virtual IPs using the exact guide's parameterized instance numbers.",
            "Configure supported fencing/quorum and test the complete central-service recovery path. Preserve permanent placement and safety constraints when cleaning up temporary maintenance constraints.",
        ],
        "checks": [
            "Are ASCS and ERS resources, instance identifiers, storage mounts and constraints correct for the chosen ENSA and OS branch?",
            "Can intended nodes access required shared files while fencing prevents conflicting active ownership?",
            "Does an approved failover validate enqueue/central-service availability, virtual routing and application reconnect rather than just an Online cluster state?",
        ],
        "limits": [
            "Example instance numbers and probe ports are derived from that deployment, not universal constants. Central-service HA does not protect every database or shared-storage failure automatically."
        ],
        "urls": [
            "https://learn.microsoft.com/en-us/azure/sap/workloads/high-availability-guide-suse",
            "https://learn.microsoft.com/en-us/azure/sap/workloads/high-availability-guide-rhel",
            "https://learn.microsoft.com/en-us/azure/sap/workloads/high-availability-guide-suse-netapp-files",
        ],
        "nodes": "apps|SAP application servers|subject;ascs|Current ASCS owner|dependency;ers|Enqueue replication server|dependency;shared|Selected shared-filesystem architecture|dependency;cluster|OS and ENSA-specific cluster contract|configuration;fence|Supported quorum and fencing|dependency;evidence|Enqueue and reconnect observations|evidence",
        "edges": "apps>ascs|uses virtual central-service access|solid;ascs>ers|ENSA-specific enqueue protection|solid;ascs>shared|requires supported shared files|solid;cluster>ascs|controls resource ownership and ordering|solid;cluster>ers|applies supported constraints|solid;cluster>fence|prevents conflicting ownership|solid;evidence>apps|validates real reconnect and enqueue behavior|dashed",
    },
    "ee4dc309": {
        "explanation": (
            "The pinned title asks for SAP shared-file protection while its description discusses monitoring. Current SAP DR guidance resolves the missing mechanism: ASR replicates VMs and attached managed disks, not mounted NFS data. Shared-directory recovery must use the storage-specific path; ANF supports cross-region replication, while other NFS designs may need a supported custom copy strategy. Monitoring is additional evidence, not the recovery copy.",
            "고정된 제목은 SAP 공유 파일 보호를 요구하지만 설명은 모니터링을 다룹니다. 현재 SAP DR 문서는 ASR이 VM과 연결된 관리 디스크를 복제할 뿐 NFS 마운트 데이터를 복제하지 않는다고 명확히 합니다. 공유 디렉터리는 저장소별 복구 경로가 필요하며 ANF는 지역 간 복제를 지원하고 다른 NFS 구조는 지원되는 별도 복사 전략이 필요할 수 있습니다. 모니터링은 추가 근거이지 복구 사본이 아닙니다.",
        ),
        "before": "Healthy monitoring or replicated session/server VMs are mistaken for protected SAP shared-directory contents.",
        "after": "Each required shared directory has a selected storage-specific recovery copy, target mount/permission plan and tested application recovery order.",
        "actions": [
            "Inventory actual sapmnt, transport, profile and other required shared-directory contents and classify ANF, Azure Files NFS, an NFS cluster or Windows shared storage separately.",
            "Select the supported storage-specific replication or backup/copy strategy. For ANF review Cross Region Replication and controlled failover; for other NFS designs define the supported custom method, consistency and retention instead of assuming ASR includes mounted files.",
            "Prepare DR mount targets, exports, permissions, name resolution and dependent cluster/fencing reconfiguration before restoring SAP services. Add lag/failure alerts to the actual copy mechanism.",
        ],
        "checks": [
            "Can every required shared directory be traced to an actual retained copy or replication relationship and its current recovery-point age?",
            "Does the isolated recovery target mount the intended data with correct ownership and permissions before dependent SAP resources start?",
            "Do an authorized recovery and failback validate file consistency, application start order, replication lag/data-loss acceptance and the workload's RPO/RTO?",
        ],
        "limits": [
            "The title-description mismatch is preserved as provenance but no longer substitutes monitoring for protection. Local HA and replicated VM disks do not automatically provide regional shared-file recovery."
        ],
        "urls": [
            "https://learn.microsoft.com/en-us/azure/sap/workloads/disaster-recovery-sap-guide",
            "https://learn.microsoft.com/en-us/azure/azure-netapp-files/cross-region-replication-introduction",
        ],
        "nodes": "sap|SAP services requiring shared files|subject;mounts|NFS or SMB shared directories|dependency;choice|Storage-specific protection choice|configuration;copy|Retained or replicated recovery content|dependency;target|DR mounts and permissions|outcome;asr|VM and attached-disk ASR scope|dependency;evidence|Copy freshness and application recovery|evidence",
        "edges": "sap>mounts|requires application shared content|solid;mounts>choice|selects mechanism by actual storage type|solid;choice>copy|creates supported recovery content|solid;copy>target|controlled restore or replication failover|solid;asr>mounts|mounted NFS content is outside VM replication|dashed;evidence>target|checks files, permissions and startup order|dashed",
    },
    "c041d596": {
        "explanation": (
            "The pinned APRL title's 4000 figure comes from its Citrix Managed Azure subscription context; it is not an Azure-wide VM quota. The current public Citrix DaaS Standard for Azure limits page lists 5000 VDAs per subscription and different per-catalog/resource-location limits. These are product-scoped recommendations and must be matched to the actual managed/customer subscription model and current service agreement before a capacity decision.",
            "고정된 APRL 제목의 4000은 Citrix Managed Azure 구독 맥락의 값이며 Azure 전체 VM 할당량이 아닙니다. 현재 Citrix DaaS Standard for Azure 공개 한도 페이지는 구독당 VDA 5000개와 별도의 카탈로그 및 리소스 위치 한도를 제시합니다. 이는 제품 범위의 권고이므로 실제 관리형 또는 고객 구독 유형과 현재 서비스 계약을 확인한 뒤 용량을 판단해야 합니다.",
        ),
        "before": "The historical 4000 title is applied as a universal Azure VDA limit or mixed with trial and catalog limits.",
        "after": "The actual Citrix product, subscription ownership model and current applicable limit are recorded separately from Azure quota and other Citrix scaling boundaries.",
        "actions": [
            "Identify the exact Citrix product/edition and whether the subscription is Citrix Managed Azure or customer-managed. Separate production, trial, per-catalog and per-resource-location constraints.",
            "Consult the current Citrix public limits page and service agreement; record the applicable scoped recommendation. The reviewed DaaS Standard for Azure page currently lists 5000 per subscription, not a replacement Azure platform quota.",
            "Count the intended VDA population separately from other infrastructure such as Cloud Connectors, review licenses and Azure quota/capacity, and plan supported catalog/resource-location/subscription partitioning before reaching the applicable boundary.",
        ],
        "checks": [
            "Which exact vendor product, subscription model and contract make the selected count limit applicable?",
            "Are VDA counts, catalog/resource-location limits and Azure regional/VM-family quotas tracked independently with a tested expansion lead time?",
            "Does the capacity plan avoid treating the source's historical 4000 or the current product page's 5000 as universal across every Citrix or Azure deployment?",
        ],
        "limits": [
            "The vendor source card cites Citrix DaaS Standard for Azure limits, not an Azure platform quota. Confirm the exact product, subscription model and current service agreement before applying a stated limit.",
            "The current product-specific 5000 recommendation is not a guarantee of available Azure capacity, and it does not automatically amend a managed-service contract.",
        ],
        "urls": [],
        "vendor_url": "https://docs.citrix.com/us/en/citrix-daas-azure/limits.html",
        "nodes": "product|Exact Citrix product and edition|subject;model|Managed or customer subscription model|configuration;vendor|Current scoped vendor limits|dependency;count|Actual VDA population|dependency;azure|Independent Azure quota and capacity|dependency;plan|Supported scale-unit expansion|outcome;evidence|Scope, count and contract observations|evidence",
        "edges": "product>model|selects actual service ownership model|solid;model>vendor|determines applicable production or trial scope|solid;count>plan|compares VDA demand with scoped limit|solid;vendor>plan|constrains product-specific scaling|solid;azure>plan|separate quota and supply constraint|solid;evidence>model|checks product and contract applicability|dashed;evidence>count|excludes unrelated infrastructure counts|dashed",
    },
}
