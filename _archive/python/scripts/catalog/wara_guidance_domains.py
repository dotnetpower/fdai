"""Service-specific interpretation boundaries, independent of generic mechanisms."""
# ruff: noqa: E501

from wara_guidance_reliability import localized

DOMAIN_NOTES = (
    (
        "/CognitiveServices/",
        (
            "Model deployment type, processing geography, quota and customer routing are separate. Review Global, Data Zone and Regional support for the exact model and version.",
            "모델 배포 유형, 처리 지역, 할당량과 고객 라우팅은 별개입니다. 정확한 모델과 버전의 Global, Data Zone 및 Regional 지원을 검토합니다.",
        ),
    ),
    (
        "/ContainerService/",
        (
            "AKS node availability does not establish pod or persistent-volume resilience. Check scheduling, resource requests, disruption budgets and storage together; PDBs cover voluntary disruptions only.",
            "AKS 노드의 가용성이 Pod나 영구 볼륨의 복원력을 입증하지는 않습니다. 배치, 리소스 요청, 중단 예산과 저장소를 함께 확인합니다. PDB는 자발적 중단만 다룹니다.",
        ),
    ),
    (
        "/Databricks/",
        (
            "Workspace configuration, external data and job progress have separate recovery boundaries. Delta time travel depends on retained history and data files; it is not an unlimited independent backup.",
            "작업 영역 구성, 외부 데이터와 작업 진행은 복구 경계가 다릅니다. Delta 시간 여행은 보존된 이력과 데이터 파일에 의존하며 무제한의 독립 백업이 아닙니다.",
        ),
    ),
    (
        "/Compute/",
        (
            "Compute placement, guest readiness, disk durability and quota are distinct. A replicated disk or supported VM SKU does not automatically recover a running application.",
            "컴퓨팅 배치, 게스트 준비, 디스크 내구성과 할당량은 별개입니다. 복제 디스크나 지원 VM SKU가 실행 중인 애플리케이션을 자동으로 복구하지는 않습니다.",
        ),
    ),
    (
        "/Network/",
        (
            "Review effective forward and return paths, DNS and security rules from the actual source network. An ARM provisioning success does not establish packet or application delivery.",
            "실제 원본 네트워크에서 순방향 및 반환 경로, DNS와 보안 규칙을 확인합니다. ARM 프로비전 성공이 패킷이나 애플리케이션 전달을 입증하지는 않습니다.",
        ),
    ),
    (
        "/SQL/",
        (
            "Database replication, backup, TDE key recovery and listener routing have independent requirements. Readable secondaries and async failover can have lag and data-loss tradeoffs.",
            "데이터베이스 복제, 백업, TDE 키 복구와 수신기 라우팅은 별도 조건을 가집니다. 읽기 보조와 비동기 장애 조치에는 지연 및 데이터 손실의 절충이 있을 수 있습니다.",
        ),
    ),
    (
        "/DBfor",
        (
            "Managed database HA, read replicas and geo-backups solve different failures. Confirm supported tier and region, promotion behavior and application reconnection separately.",
            "관리형 데이터베이스 HA, 읽기 복제본과 지역 백업은 서로 다른 장애를 해결합니다. 지원 계층과 지역, 승격 동작과 애플리케이션 재연결을 따로 확인합니다.",
        ),
    ),
    (
        "/DocumentDB/",
        (
            "Cosmos DB regional, write and consistency settings interact with SDK routing. Continuous backup and multi-region replication are separate protection mechanisms.",
            "Cosmos DB의 지역, 쓰기와 일관성 설정은 SDK 라우팅과 상호작용합니다. 연속 백업과 다중 지역 복제는 별도 보호 기능입니다.",
        ),
    ),
    (
        "/Storage/",
        (
            "LRS, ZRS, GRS and GZRS cover different failure domains. Blob, file and account recovery features differ; replication does not undo a deletion or corruption.",
            "LRS, ZRS, GRS와 GZRS는 보호 장애 범위가 다릅니다. Blob, 파일과 계정의 복구 기능도 다르며 복제가 삭제나 손상을 되돌리지는 못합니다.",
        ),
    ),
    (
        "/RecoveryServices/",
        (
            "Backup and Site Recovery have different state and failover semantics. Confirm protected item coverage, recovery points, target networks and required key access.",
            "Backup과 Site Recovery는 데이터 상태와 장애 조치 의미가 다릅니다. 보호 항목 범위, 복구 지점, 대상 네트워크와 필요한 키 접근을 확인합니다.",
        ),
    ),
    (
        "/NetApp/",
        (
            "ANF snapshots, backup, cross-zone replication, cross-region replication and SMB continuous availability are distinct. Check supported volume, protocol and application combinations.",
            "ANF 스냅샷, 백업, 영역 간 복제, 지역 간 복제와 SMB 지속적 가용성은 서로 다릅니다. 볼륨, 프로토콜과 애플리케이션의 지원 조합을 확인합니다.",
        ),
    ),
    (
        "/Web/",
        (
            "App Service and Functions behavior depends on the hosting plan and runtime. Check instance counts, slot-specific settings, startup, state and dependency limits independently.",
            "App Service와 Functions 동작은 호스팅 계획과 런타임에 따라 달라집니다. 인스턴스 수, 슬롯별 설정, 시작, 데이터 상태와 의존성 한도를 따로 확인합니다.",
        ),
    ),
    (
        "/CDN/",
        (
            "Front Door routes, origin probes, WAF and origin identity serve different purposes. A single-origin probe policy must be interpreted with the actual origin group, not copied to multi-origin failover.",
            "Front Door 경로, 원본 프로브, WAF와 원본 신원은 목적이 다릅니다. 단일 원본 프로브 정책은 실제 원본 그룹으로 해석하고 다중 원본 장애 조치에 그대로 적용하지 않습니다.",
        ),
    ),
    (
        "/MachineLearningServices/",
        (
            "ML workspace metadata, registry artifacts, training checkpoints, serving endpoints and regional compute quota have different recovery requirements.",
            "ML 작업 영역 메타데이터, 레지스트리 아티팩트, 학습 체크포인트, 처리 엔드포인트와 지역 컴퓨팅 할당량은 복구 조건이 다릅니다.",
        ),
    ),
    (
        "/AVS/",
        (
            "AVS private-cloud and cluster limits, vSAN storage policy, HCX and ExpressRoute have separate support boundaries. Validate the current vendor-supported topology.",
            "AVS 프라이빗 클라우드와 클러스터 한도, vSAN 저장소 정책, HCX와 ExpressRoute는 지원 경계가 다릅니다. 현재 공급업체가 지원하는 구조를 검증합니다.",
        ),
    ),
    (
        "/avd/",
        (
            "AVD control-plane availability does not recover session hosts, FSLogix profiles, directory services or networking. Include those dependencies and user reconnection in recovery.",
            "AVD 관리 계층의 가용성이 세션 호스트, FSLogix 프로필, 디렉터리 서비스나 네트워크를 복구하지는 않습니다. 해당 의존성과 사용자 재연결을 복구에 포함합니다.",
        ),
    ),
    (
        "/sap/",
        (
            "Use the supported SAP, OS and database HA design. Synchronous local HA, asynchronous DR, fencing, load-balancer probes and shared files are not interchangeable.",
            "지원되는 SAP, OS와 데이터베이스 HA 설계를 사용합니다. 동기 로컬 HA, 비동기 DR, 펜싱, 부하 분산기 프로브와 공유 파일은 서로 바꿔 쓸 수 없습니다.",
        ),
    ),
    (
        "/oracle/",
        (
            "Oracle infrastructure lifecycle, Data Guard, observer placement, backup and encryption-key availability are separate from application transaction health.",
            "Oracle 인프라 수명 주기, Data Guard, 관찰자 배치, 백업과 암호화 키 가용성은 애플리케이션 트랜잭션 상태와 별개입니다.",
        ),
    ),
    (
        "/Devices/",
        (
            "IoT Hub device identity, message routing, fallback routing and regional failover have different continuity requirements. Reconcile title and description when route polarity is ambiguous.",
            "IoT Hub 장치 신원, 메시지 라우팅, 대체 라우팅과 지역 장애 조치는 연속성 조건이 다릅니다. 경로의 활성화 의미가 모호하면 제목과 설명을 대조합니다.",
        ),
    ),
    (
        "/ServiceBus/",
        (
            "Service Bus autoscale is tier-specific; the source names Premium capacity. Namespace redundancy does not prove consumer recovery or preservation of application side effects.",
            "Service Bus 자동 크기 조정은 계층별로 다르며 원본은 Premium 용량을 지정합니다. 네임스페이스 중복이 소비자 복구나 애플리케이션 부작용의 보존을 입증하지는 않습니다.",
        ),
    ),
)


def domain_note(source_path: str) -> dict[str, str] | None:
    for fragment, note in DOMAIN_NOTES:
        if fragment.casefold() in source_path.casefold():
            return localized(*note)
    return None
