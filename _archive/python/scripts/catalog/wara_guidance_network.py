"""Network, access and data-placement mechanisms with distinct failure boundaries."""
# ruff: noqa: E501

from wara_guidance_reliability import profile

PROFILES = {
    "private-network": profile(
        "private-network",
        (
            "Private access joins a client network, a name-resolution path and a service-specific private connection. An approved endpoint without correct DNS or an allowed data path does not provide usable private connectivity.",
            "프라이빗 접근은 클라이언트 네트워크, 이름 해석 경로와 서비스별 프라이빗 연결을 함께 구성해야 합니다. 엔드포인트를 승인해도 DNS나 허용된 데이터 경로가 올바르지 않으면 연결할 수 없습니다.",
        ),
        (
            "Check service and tier support, required subresources, endpoint approval, private DNS zones and client network topology.",
            "서비스와 계층의 지원, 필요한 하위 리소스, 엔드포인트 승인, Private DNS 영역과 클라이언트 네트워크 구조를 확인합니다.",
        ),
        (
            "Clients may use a public path or resolve a private name to an address they cannot reach.",
            "클라이언트가 공용 경로를 사용하거나 접근할 수 없는 주소로 이름을 해석할 수 있습니다.",
        ),
        (
            "The intended client resolves the service through the correct private path and can make an authorized data-plane request.",
            "의도한 클라이언트가 올바른 프라이빗 경로로 서비스를 해석하고 승인된 데이터 요청을 보낼 수 있습니다.",
        ),
        (
            "Plan private endpoint subresources, approve the connection through the normal owner process, configure DNS links or forwarding and validate access before changing public-network settings.",
            "프라이빗 엔드포인트 하위 리소스를 계획하고 정상적인 소유자 절차로 연결을 승인합니다. DNS 링크나 전달을 구성하고 공용 네트워크 설정을 바꾸기 전에 접근을 검증합니다.",
        ),
        (
            "Observe endpoint state, resolve from each required client network and verify the returned address and authorized service request. Test the intended public-access restriction separately.",
            "각 클라이언트 네트워크에서 엔드포인트 상태와 이름 해석을 확인한 뒤 반환 주소와 승인된 서비스 요청을 검증합니다. 의도한 공용 접근 제한도 따로 시험합니다.",
        ),
        (
            "Private endpoints do not automatically configure every custom DNS server, grant application permissions or remove all public access.",
            "프라이빗 엔드포인트가 모든 사용자 지정 DNS를 설정하거나 애플리케이션 권한을 부여하거나 모든 공용 접근을 제거하지는 않습니다.",
        ),
    ),
    "dns": profile(
        "dns-resolution",
        (
            "DNS resilience requires reachable resolvers and the intended authoritative records from every required network. A successful answer identifies an address; it does not demonstrate that the resource behind that address is healthy.",
            "DNS 복원력에는 필요한 각 네트워크에서 접근할 수 있는 확인자와 올바른 권한 있는 레코드가 필요합니다. 응답 성공은 주소를 확인했다는 뜻이며 그 주소의 리소스가 정상이라는 의미는 아닙니다.",
        ),
        (
            "Identify authoritative zones, client DNS settings, forwarding and links, and the independent availability of resolver instances.",
            "권한 있는 영역, 클라이언트 DNS 설정, 전달과 링크, 확인자 인스턴스의 독립적인 가용성을 확인합니다.",
        ),
        (
            "Resolution can depend on one resolver or on links and forwarding paths missing from a recovery network.",
            "이름 해석이 하나의 확인자에 의존하거나 복구 네트워크에 필요한 링크와 전달 경로가 빠져 있을 수 있습니다.",
        ),
        (
            "Each required network has a documented resolution path with appropriate independent resolver or zone access.",
            "필요한 각 네트워크에 적절한 독립 확인자 또는 영역 접근을 갖춘 이름 해석 경로를 문서화합니다.",
        ),
        (
            "Map the client-to-resolver-to-zone path, configure the source-specific links or resilient DNS servers and separate record ownership from resolution access.",
            "클라이언트, 확인자, 영역으로 이어지는 경로를 정리합니다. 권고에 맞는 링크나 복원력 있는 DNS 서버를 구성하고 레코드 관리와 조회 접근을 구분합니다.",
        ),
        (
            "Query representative records from every required network and inspect the responding path and expected address. Validate alternate resolution and backend reachability separately.",
            "필요한 각 네트워크에서 대표 레코드를 조회하고 응답 경로와 예상 주소를 확인합니다. 대체 이름 해석과 백엔드 접근은 따로 검증합니다.",
        ),
        (
            "VM autoregistration, Private Endpoint record management, DNS failover and application failover are different mechanisms and must not be conflated.",
            "VM 자동 등록, Private Endpoint 레코드 관리, DNS 장애 조치와 애플리케이션 장애 조치는 서로 다른 기능이므로 혼동하지 않습니다.",
        ),
    ),
    "dns-ttl": profile(
        "dns-cache",
        (
            "DNS TTL controls how long compliant recursive resolvers can retain an answer. Lower TTL can shorten one part of a traffic change, but resolver caching, client behavior, health detection and new-target readiness also contribute to recovery time.",
            "DNS TTL은 규약을 따르는 재귀 확인자가 응답을 보관할 수 있는 시간을 정합니다. TTL을 낮추면 트래픽 전환의 일부 시간을 줄일 수 있지만 캐시, 클라이언트 동작, 장애 탐지와 새 대상의 준비 시간도 복구 시간에 영향을 줍니다.",
        ),
        (
            "Use the recovery objective and actual record consumers to choose TTL; inspect intermediate and application-side caches.",
            "복구 목표와 실제 레코드 소비자를 바탕으로 TTL을 정하고 중간 캐시와 애플리케이션 캐시를 확인합니다.",
        ),
        (
            "A long or unexamined TTL can leave clients using an old address after an intended endpoint change.",
            "TTL이 길거나 확인되지 않으면 엔드포인트를 변경한 뒤에도 클라이언트가 이전 주소를 계속 사용할 수 있습니다.",
        ),
        (
            "Record TTL and measured end-to-end cache expiry are consistent with the allocated DNS portion of recovery time.",
            "레코드 TTL과 실제 전체 캐시 만료 시간이 복구 시간 중 DNS에 배정한 시간과 맞도록 구성합니다.",
        ),
        (
            "Budget health detection, DNS publication and cache expiry separately; set record TTL according to official limits and expected query load.",
            "상태 탐지, DNS 게시와 캐시 만료 시간을 따로 산정합니다. 공식 한도와 예상 조회 부하를 반영해 레코드 TTL을 정합니다.",
        ),
        (
            "Inspect authoritative TTL and repeated client observations during an approved record change; measure last use of the old answer without assuming all clients honor TTL exactly.",
            "승인된 레코드 변경 때 권한 있는 TTL과 반복 클라이언트 관찰을 확인합니다. 모든 클라이언트가 TTL을 정확히 따른다고 가정하지 않고 이전 응답의 마지막 사용 시각을 측정합니다.",
        ),
        (
            "A low TTL increases query load and cannot guarantee a complete RTO or make an unhealthy replacement application available.",
            "낮은 TTL은 조회 부하를 늘리며 전체 RTO를 보장하거나 비정상인 대체 애플리케이션을 정상으로 만들지는 못합니다.",
        ),
    ),
    "network-route": profile(
        "network-path",
        (
            "Reliable routing requires an explicit path through the intended gateway, next hop or application endpoint. Control-plane routes, connection settings and observed packets must agree; route presence alone is not end-to-end connectivity.",
            "안정적인 라우팅에는 의도한 게이트웨이, 다음 홉 또는 애플리케이션 엔드포인트를 거치는 명시적인 경로가 필요합니다. 관리 경로, 연결 설정과 실제 패킷이 일치해야 하며 경로가 있다는 사실만으로 전체 연결을 확인할 수는 없습니다.",
        ),
        (
            "Review the exact route, connection mode, protocol, destination and supported topology specified by the recommendation.",
            "권고가 지정한 정확한 경로, 연결 모드, 프로토콜, 대상과 지원 구조를 검토합니다.",
        ),
        (
            "Traffic can follow an unintended dependency, encounter an unsupported mode or fail to reach an intended destination.",
            "트래픽이 의도하지 않은 의존 경로를 따르거나 지원되지 않는 모드를 사용하거나 대상에 도달하지 못할 수 있습니다.",
        ),
        (
            "The effective routing and connection configuration matches the intended path and has observable application reachability.",
            "실제 라우팅과 연결 구성이 의도한 경로와 일치하고 애플리케이션 접근을 관찰할 수 있습니다.",
        ),
        (
            "Map both forward and return paths, configure the source-specific route or connection setting and review firewall, NSG and name-resolution prerequisites.",
            "순방향과 반환 경로를 정리하고 권고에 맞는 경로나 연결 설정을 적용합니다. 방화벽, NSG와 이름 해석 조건을 검토합니다.",
        ),
        (
            "Inspect effective routes or service connection state and make approved representative requests from the actual source network; verify return-path and failure behavior.",
            "실제 원본 네트워크에서 유효 경로나 서비스 연결 상태를 확인하고 승인된 대표 요청을 보냅니다. 반환 경로와 장애 동작도 검증합니다.",
        ),
        (
            "Changing routes or connection modes can black-hole traffic or bypass a security boundary; routing guidance does not grant change approval.",
            "경로나 연결 모드 변경은 트래픽을 끊거나 보안 경계를 우회할 수 있습니다. 라우팅 가이드가 변경 승인을 부여하지는 않습니다.",
        ),
    ),
    "network-redundancy": profile(
        "network-redundancy",
        (
            "Two logical connections provide resilience only when their physical paths, devices and relevant locations do not share the failure being mitigated. Active control-plane sessions must be matched to usable data paths and tested convergence.",
            "논리 연결이 두 개여도 물리 경로, 장비와 위치가 같은 장애에 노출되면 복원력이 생기지 않습니다. 활성 관리 세션과 실제 데이터 경로를 대조하고 수렴 동작을 시험해야 합니다.",
        ),
        (
            "Identify device, circuit, peering-location and gateway failure domains and the supported active-active or HA model.",
            "장비, 회선, 피어링 위치와 게이트웨이의 장애 범위 및 지원되는 활성-활성 또는 HA 방식을 확인합니다.",
        ),
        (
            "Nominally redundant links can terminate on one device or location, or one path can be disabled or unusable.",
            "겉으로는 중복인 링크가 한 장비나 위치에 모여 있거나 한 경로가 비활성 또는 사용 불가 상태일 수 있습니다.",
        ),
        (
            "Independent supported paths are operational and provide the intended forwarding behavior after a single-path failure.",
            "지원되는 독립 경로를 가동하고 단일 경로 장애 뒤에도 의도한 전달 동작을 유지합니다.",
        ),
        (
            "Document physical and logical diversity, configure both supported sessions or links and align route preference, detection and customer-edge behavior.",
            "물리적 및 논리적 분리를 문서화하고 지원되는 양쪽 세션이나 링크를 설정합니다. 경로 우선순위, 탐지와 고객 측 경계 장비의 동작을 맞춥니다.",
        ),
        (
            "Inspect both administrative and operational states and verify traffic on intended paths; use a separately authorized path-loss exercise to measure convergence and remaining bandwidth.",
            "관리 상태와 동작 상태를 모두 확인하고 의도한 경로의 트래픽을 검증합니다. 별도로 승인된 경로 장애 시험으로 수렴 시간과 남은 대역폭을 측정합니다.",
        ),
        (
            "Two tunnels over the same physical circuit or two circuits at one peering location do not cover every circuit or location failure.",
            "같은 물리 회선 위의 두 터널이나 한 피어링 위치의 두 회선은 모든 회선 또는 위치 장애를 보호하지 못합니다.",
        ),
    ),
    "network-capacity": profile(
        "network-capacity",
        (
            "Address space, SNAT ports, interface bandwidth and service connection limits constrain different parts of a network. Plan against peak concurrency, scale and recovery demand using the exact bottleneck named in the recommendation.",
            "주소 공간, SNAT 포트, 인터페이스 대역폭과 서비스 연결 한도는 서로 다른 네트워크 구간을 제한합니다. 권고가 지정한 병목을 기준으로 최대 동시 연결, 확장과 복구 수요를 계획합니다.",
        ),
        (
            "Check service-reserved addresses, growth and upgrade surge, connection reuse and exact tier or subnet limitations.",
            "서비스 예약 주소, 증가분과 업그레이드 추가 용량, 연결 재사용과 정확한 계층 또는 서브넷 제약을 확인합니다.",
        ),
        (
            "Average traffic can look healthy while address, port or bandwidth exhaustion prevents new instances or connections.",
            "평균 트래픽은 정상이어도 주소, 포트 또는 대역폭 부족으로 새 인스턴스나 연결을 만들지 못할 수 있습니다.",
        ),
        (
            "The relevant address, port or bandwidth budget covers peak and recovery demand with observable remaining headroom.",
            "필요한 주소, 포트 또는 대역폭으로 최대 및 복구 수요를 감당하고 남은 여유를 관찰합니다.",
        ),
        (
            "Calculate the source-specific network budget, include reserved capacity and growth, and plan supported subnet, IP, interface or connection changes with rollback.",
            "권고에 맞는 네트워크 용량을 계산하고 예약 용량과 증가분을 반영합니다. 지원되는 서브넷, IP, 인터페이스 또는 연결 변경과 롤백을 계획합니다.",
        ),
        (
            "Compare effective allocations and measured peaks with limits, then validate representative connection or scale demand and alerts before exhaustion.",
            "실제 할당과 최대 측정값을 한도와 비교합니다. 대표 연결 또는 확장 수요와 자원 소진 전 경고를 검증합니다.",
        ),
        (
            "Adding public IPs, enabling acceleration or enlarging a subnet addresses different constraints; none automatically removes every network bottleneck.",
            "공용 IP 추가, 가속 활성화와 서브넷 확대는 서로 다른 제약을 해결합니다. 어느 하나도 모든 네트워크 병목을 자동으로 없애지는 못합니다.",
        ),
    ),
    "identity": profile(
        "identity-boundary",
        (
            "Authenticated access and resilient identity dependencies reduce anonymous exposure and single-source authentication failure. Tightening access must preserve intended principals and an audited recovery path without disclosing credentials.",
            "인증된 접근과 복원력 있는 신원 의존성은 익명 노출과 단일 인증 원본 장애를 줄입니다. 접근을 제한할 때도 의도한 주체와 감사 가능한 복구 경로를 유지하고 자격 증명을 노출하지 않아야 합니다.",
        ),
        (
            "Identify intended principals, supported authentication modes, directory dependencies and emergency access requirements.",
            "의도한 주체, 지원 인증 방식, 디렉터리 의존성과 비상 접근 조건을 확인합니다.",
        ),
        (
            "Anonymous or local access may bypass intended identity controls, or authentication may depend on one unavailable source.",
            "익명 또는 로컬 접근이 의도한 신원 통제를 우회하거나 인증이 하나의 사용 불가 원본에 의존할 수 있습니다.",
        ),
        (
            "Only intended authenticated paths are available and required identity dependencies have tested continuity.",
            "의도한 인증 경로만 사용하고 필요한 신원 의존성의 연속성을 시험합니다.",
        ),
        (
            "Configure the exact identity setting or supported redundant sources, review least privilege and validate intended access before removing legacy paths.",
            "정확한 신원 설정이나 지원되는 중복 원본을 구성합니다. 최소 권한을 검토하고 기존 경로를 없애기 전에 의도한 접근을 검증합니다.",
        ),
        (
            "Check effective authentication settings, test allowed and denied principals and use an approved source-loss scenario where redundancy is required.",
            "실제 인증 설정을 확인하고 허용 및 거부 주체를 시험합니다. 중복이 필요하면 승인된 인증 원본 장애 시나리오를 사용합니다.",
        ),
        (
            "An identity migration can lock out operators or workloads. Preserve governed emergency access and never include credential values in guidance or evidence.",
            "신원 이전은 운영자나 워크로드의 접근을 막을 수 있습니다. 통제된 비상 접근을 유지하고 가이드나 확인 자료에 자격 증명 값을 넣지 않습니다.",
        ),
    ),
    "security": profile(
        "security-boundary",
        (
            "Access restrictions, policy and resource locks protect different operations. The exact intended boundary must be evaluated using effective rules and legitimate traffic, rather than treating an enabled protection flag as universal coverage.",
            "접근 제한, 정책과 리소스 잠금은 서로 다른 작업을 보호합니다. 보호 설정의 활성화를 만능으로 보지 않고 실제 규칙과 정상 트래픽으로 의도한 경계를 평가해야 합니다.",
        ),
        (
            "Determine the protected operation, effective scope, supported policy mode and necessary workload or emergency exceptions.",
            "보호할 작업, 실제 범위, 지원 정책 모드와 필요한 워크로드 또는 비상 예외를 정합니다.",
        ),
        (
            "Unreviewed defaults, broad access or missing associations can leave the intended resource boundary unprotected.",
            "검토하지 않은 기본값, 광범위한 접근이나 누락된 연결로 리소스 경계가 보호되지 않을 수 있습니다.",
        ),
        (
            "Effective restrictions protect the intended operation while documented legitimate requests and recovery operations remain possible.",
            "실제 제한으로 의도한 작업을 보호하면서 문서화된 정상 요청과 복구 작업을 계속 허용합니다.",
        ),
        (
            "Inspect effective inherited and local rules, choose narrow supported controls and review impact and exceptions before changing enforcement.",
            "상속 규칙과 로컬 규칙의 실제 효과를 확인합니다. 범위가 좁고 지원되는 통제를 선택하고 적용 수준을 바꾸기 전에 영향과 예외를 검토합니다.",
        ),
        (
            "Validate representative allowed and denied operations and inspect matching logs or policy results; investigate false positives before narrowing exclusions.",
            "대표 허용 및 거부 작업을 검증하고 일치 로그나 정책 결과를 확인합니다. 제외 범위를 조정하기 전에 오탐 원인을 조사합니다.",
        ),
        (
            "Security controls can interrupt valid traffic or emergency recovery. Disabling protection broadly is not a safe response to one false positive.",
            "보안 통제는 정상 트래픽이나 비상 복구를 중단할 수 있습니다. 오탐 하나를 해결하려고 보호를 광범위하게 끄는 것은 안전하지 않습니다.",
        ),
    ),
    "encryption": profile(
        "key-lifecycle",
        (
            "TLS and encryption-key lifecycle preserve confidentiality and recoverability only while compatible keys, certificates and access remain available. Rotation, expiry and backup must be checked for the exact connection or encrypted object.",
            "TLS와 암호화 키 관리는 호환되는 키, 인증서와 접근을 사용할 수 있어야 기밀성과 복구 가능성을 유지합니다. 정확한 연결 또는 암호화 대상에 대해 교체, 만료와 백업을 확인해야 합니다.",
        ),
        (
            "Identify the exact TLS leg, minimum version, certificate or encryption key and required recovery permissions.",
            "정확한 TLS 구간, 최소 버전, 인증서 또는 암호화 키와 필요한 복구 권한을 확인합니다.",
        ),
        (
            "A connection can use an old protocol or certificate, or encrypted data can depend on an unavailable key version.",
            "연결이 오래된 프로토콜이나 인증서를 사용하거나 암호화 데이터가 사용할 수 없는 키 버전에 의존할 수 있습니다.",
        ),
        (
            "Supported protocol and key settings are effective, with validated rotation or recovery and no credential disclosure.",
            "지원되는 프로토콜과 키 설정을 적용하고 자격 증명을 노출하지 않은 채 교체 또는 복구를 검증합니다.",
        ),
        (
            "Review compatibility, configure the exact TLS or key policy and preserve required historical keys and access before rotation, migration or deletion.",
            "호환성을 검토하고 정확한 TLS 또는 키 정책을 설정합니다. 교체, 이전 또는 삭제 전에 필요한 이전 키와 접근을 보존합니다.",
        ),
        (
            "Inspect negotiated protocol or active key version, test intended clients and validate renewal, rotation or backup restoration in an authorized isolated scope.",
            "협상된 프로토콜이나 활성 키 버전을 확인하고 의도한 클라이언트를 시험합니다. 승인된 격리 범위에서 갱신, 교체 또는 백업 복원을 검증합니다.",
        ),
        (
            "Deleting a required encryption key can make retained data irrecoverable. Certificate and key material must never appear in catalog content or test output.",
            "필요한 암호화 키를 삭제하면 보존된 데이터도 복구할 수 없게 됩니다. 인증서나 키 자료를 카탈로그 본문 또는 시험 출력에 넣지 않습니다.",
        ),
    ),
    "storage-layout": profile(
        "storage-dependencies",
        (
            "Storage placement determines persistence, sharing, throughput and failure coupling. Shared, ephemeral, OS, data and profile storage have different semantics; use the supported layout for the exact workload rather than applying one disk rule everywhere.",
            "저장 위치는 영속성, 공유, 처리량과 장애 결합을 결정합니다. 공유, 임시, OS, 데이터와 프로필 저장소는 의미가 다르므로 하나의 디스크 규칙을 모두에 적용하지 말고 정확한 워크로드가 지원하는 배치를 사용합니다.",
        ),
        (
            "Review the actual data type, durability requirement, sharing and fencing model and supported client or VM configuration.",
            "실제 데이터 종류, 내구성 요구, 공유와 펜싱 방식, 지원 클라이언트 또는 VM 구성을 검토합니다.",
        ),
        (
            "State can be placed on inappropriate storage or share capacity and lifecycle with unrelated workloads.",
            "상태가 부적절한 저장소에 놓이거나 관련 없는 워크로드와 용량 및 수명 주기를 공유할 수 있습니다.",
        ),
        (
            "Data and configuration follow the documented workload-specific storage layout with explicit ownership and recovery dependencies.",
            "데이터와 구성을 워크로드별 문서가 정한 배치에 두고 소유권과 복구 의존성을 명시합니다.",
        ),
        (
            "Map persistent and temporary state, select the supported disk, share or storage boundary and plan migration with consistency, permissions and rollback.",
            "영속 상태와 임시 상태를 정리하고 지원되는 디스크, 공유 또는 저장소 경계를 선택합니다. 일관성, 권한과 롤백을 포함해 이전을 계획합니다.",
        ),
        (
            "Inspect actual mounts, disk or share settings and access from every required node; validate persistence and application behavior after an approved restart or failover.",
            "실제 마운트, 디스크 또는 공유 설정과 필요한 모든 노드의 접근을 확인합니다. 승인된 재시작이나 장애 조치 뒤 영속성과 애플리케이션 동작을 검증합니다.",
        ),
        (
            "Shared storage is not automatically highly available, and ephemeral or local storage must not hold the only copy of required persistent state.",
            "공유 저장소라고 자동으로 고가용성이 생기는 것은 아닙니다. 필요한 영속 상태의 유일한 사본을 임시 또는 로컬 저장소에 두지 않습니다.",
        ),
    ),
    "topology": profile(
        "isolation-boundary",
        (
            "Explicit deployment and ownership boundaries reduce shared capacity, policy and lifecycle failures. Isolation must preserve required connectivity and does not by itself replicate data or create an independent recovery environment.",
            "명시적인 배포와 소유권 경계는 공통 용량, 정책과 수명 주기로 인한 장애를 줄입니다. 격리할 때도 필요한 연결은 유지해야 하며 격리 자체가 데이터 복제나 독립 복구 환경을 만들지는 않습니다.",
        ),
        (
            "Identify the boundary named by the recommendation: subscription, resource group, workspace, network, node pool, repository or hosting plan.",
            "구독, 리소스 그룹, 작업 영역, 네트워크, 노드 풀, 저장소 또는 호스팅 계획 중 권고가 지정한 경계를 확인합니다.",
        ),
        (
            "Unrelated workloads can share a failure domain, administrative lifecycle or constrained capacity without an explicit ownership model.",
            "관련 없는 워크로드가 명확한 소유권 없이 장애 범위, 관리 수명 주기 또는 제한된 용량을 공유할 수 있습니다.",
        ),
        (
            "The intended ownership and placement boundary is explicit, with reviewed connectivity and dependency contracts.",
            "의도한 소유권과 배치 경계를 명확히 하고 연결과 의존성 계약을 검토합니다.",
        ),
        (
            "Map ownership and shared dependencies, apply the supported separation or placement model and review access, policy inheritance and migration impact.",
            "소유권과 공통 의존성을 정리하고 지원되는 분리 또는 배치 방식을 적용합니다. 접근, 정책 상속과 이전 영향을 검토합니다.",
        ),
        (
            "Read actual associations and workload placement, verify required cross-boundary access and confirm unrelated test or maintenance load does not consume protected production capacity.",
            "실제 연결과 워크로드 배치를 확인하고 필요한 경계 간 접근을 검증합니다. 관련 없는 시험이나 유지 관리 부하가 보호된 운영 용량을 소모하지 않는지 확인합니다.",
        ),
        (
            "Separation can increase cost and operational complexity. A resource-group metadata region is not the physical location of every contained resource.",
            "분리는 비용과 운영 복잡도를 늘릴 수 있습니다. 리소스 그룹 메타데이터의 지역이 모든 포함 리소스의 실제 위치를 뜻하지는 않습니다.",
        ),
    ),
    "settings": profile(
        "configuration-contract",
        (
            "A small configuration value can control runtime identity, state attachment, placement or connection behavior. Its effective value must agree with the deployed artifact and dependencies, including inheritance and swap or restart behavior.",
            "작은 설정값이 런타임 신원, 상태 연결, 배치 또는 연결 동작을 결정할 수 있습니다. 상속, 교환과 재시작 동작을 포함해 실제 값이 배포 아티팩트와 의존 리소스에 맞는지 확인해야 합니다.",
        ),
        (
            "Identify the exact documented setting, supported value and relevant app, slot, host or cluster scope.",
            "문서가 정한 정확한 설정, 지원 값과 앱, 슬롯, 호스트 또는 클러스터 범위를 확인합니다.",
        ),
        (
            "A missing, conflicting or inherited value can cause runtime failures or unintended sharing of state.",
            "누락되거나 충돌하거나 상속된 값이 런타임 오류 또는 의도하지 않은 상태 공유를 일으킬 수 있습니다.",
        ),
        (
            "Effective nonsecret configuration matches the intended runtime contract and is validated across relevant lifecycle operations.",
            "실제 비밀이 아닌 구성을 의도한 런타임 계약에 맞추고 관련 수명 주기 작업에서 검증합니다.",
        ),
        (
            "Read the supported configuration contract, compare desired and effective values and plan a controlled change with any restart, swap or session-drain requirement.",
            "지원 구성 계약을 확인하고 원하는 값과 실제 값을 비교합니다. 필요한 재시작, 교환 또는 세션 마무리를 포함해 변경을 통제합니다.",
        ),
        (
            "Verify the exact setting without exposing secret values, then observe startup, state attachment and the source-specific behavior after an approved lifecycle operation.",
            "비밀 값을 노출하지 않고 정확한 설정을 검증합니다. 승인된 수명 주기 작업 뒤 시작, 상태 연결과 권고가 요구하는 동작을 관찰합니다.",
        ),
        (
            "Do not copy secret values into evidence or apply a familiar setting to an unsupported runtime or scope.",
            "비밀 값을 확인 자료에 복사하거나 익숙한 설정을 지원되지 않는 런타임 또는 범위에 적용하지 않습니다.",
        ),
    ),
}
