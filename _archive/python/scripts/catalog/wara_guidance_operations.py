"""Operational mechanisms; these explain observations and never grant authority."""
# ruff: noqa: E501

from wara_guidance_reliability import profile

PROFILES = {
    "monitor": profile(
        "monitoring",
        (
            "Monitoring connects an observable symptom or resource condition to an actionable notification. Coverage requires the correct resource scope, a useful threshold and a delivery path that still works during the failure being detected.",
            "모니터링은 관찰 가능한 증상이나 리소스 상태를 대응 가능한 알림으로 연결합니다. 올바른 리소스 범위, 유효한 임계값과 탐지하려는 장애 중에도 동작하는 전달 경로가 필요합니다.",
        ),
        (
            "Select the recommendation's exact metric, health event or change event and the responsible response owner.",
            "권고가 요구하는 정확한 메트릭, 상태 이벤트 또는 변경 이벤트와 대응 책임자를 선택합니다.",
        ),
        (
            "A resource may emit signals without an alert, or an alert may exist without usable scope, thresholds or delivery.",
            "리소스가 신호를 내보내도 경고가 없거나, 경고가 있어도 범위, 임계값 또는 전달 경로가 유효하지 않을 수 있습니다.",
        ),
        (
            "The intended signal is collected, evaluated against a reviewed condition and delivered with enough context to act.",
            "필요한 신호를 수집하고 검토한 조건으로 평가하며 대응에 필요한 맥락과 함께 전달합니다.",
        ),
        (
            "Configure resource scope, signal, aggregation window, severity and destination; choose thresholds from baseline behavior and the required response lead time.",
            "리소스 범위, 신호, 집계 구간, 심각도와 수신 대상을 설정합니다. 평상시 동작과 대응에 필요한 시간을 바탕으로 임계값을 정합니다.",
        ),
        (
            "Inspect recent signal samples and alert evaluation history, then test notification delivery using an approved harmless test. Check both false positives and silent missing data.",
            "최근 신호와 경고 평가 이력을 확인한 뒤 승인된 무해한 시험으로 알림 전달을 검증합니다. 오탐과 데이터 누락에 따른 미탐을 함께 확인합니다.",
        ),
        (
            "An alert is not remediation or proof of service health. Missing telemetry can indicate collection failure and must not be interpreted as a healthy resource.",
            "경고는 복구 조치나 정상 상태의 증명이 아닙니다. 원격 분석 데이터가 없으면 수집 실패일 수 있으므로 정상으로 해석해서는 안 됩니다.",
        ),
    ),
    "logs": profile(
        "log-delivery",
        (
            "Diagnostic configuration creates a path from service events to retained records. Category selection, destination access and recent ingestion must all be checked; enabling a setting without delivered records leaves an observability gap.",
            "진단 구성은 서비스 이벤트를 보존된 기록으로 전달하는 경로를 만듭니다. 범주 선택, 대상 접근과 최근 수집을 모두 확인해야 합니다. 설정만 활성화하고 기록이 전달되지 않으면 관찰 공백이 남습니다.",
        ),
        (
            "Identify supported categories, destinations, retention and any regional or service-specific export restrictions.",
            "지원되는 범주, 대상, 보존 기간과 지역 또는 서비스별 내보내기 제약을 확인합니다.",
        ),
        (
            "Relevant events may be absent, sent to an inaccessible destination or retained for too short a period.",
            "필요한 이벤트가 없거나 접근할 수 없는 대상으로 전송되거나 보존 기간이 너무 짧을 수 있습니다.",
        ),
        (
            "Required categories reach a controlled destination with recent records and sufficient investigation retention.",
            "필수 범주를 통제된 대상으로 전달하고 조사에 충분한 기간 동안 최근 기록을 보존합니다.",
        ),
        (
            "Choose the exact source categories and destination, validate identity and network permissions, and define retention and access controls before enabling collection.",
            "정확한 원본 범주와 대상을 선택하고 신원 및 네트워크 권한을 검증합니다. 수집 전에 보존 기간과 접근 통제를 정합니다.",
        ),
        (
            "Generate or use an authorized known event and locate its source, event time and ingestion time in the destination. Check category completeness and delivery errors.",
            "승인된 알려진 이벤트를 사용하거나 발생시켜 대상에서 원본, 이벤트 시각과 수집 시각을 확인합니다. 범주의 누락과 전달 오류도 확인합니다.",
        ),
        (
            "Logs can contain sensitive operational data and incur ingestion cost. A diagnostic-setting resource alone does not prove complete or timely delivery.",
            "로그에는 민감한 운영 정보가 포함될 수 있고 수집 비용이 발생합니다. 진단 설정 리소스만으로 완전하고 신속한 전달을 입증할 수는 없습니다.",
        ),
    ),
    "probe": profile(
        "health-probe",
        (
            "A health signal informs routing or lifecycle handling, so its semantics must match the failure it is meant to detect. Process liveness, request readiness, dependency health and management-plane state are different observations.",
            "상태 신호는 라우팅이나 수명 주기 처리에 사용되므로 탐지하려는 장애와 의미가 일치해야 합니다. 프로세스 생존, 요청 처리 준비, 의존 리소스 상태와 관리 상태는 서로 다른 관찰입니다.",
        ),
        (
            "Use the resource-specific supported probe or state field, including protocol, authentication, timeout and success criteria where applicable.",
            "프로토콜, 인증, 시간 제한과 성공 기준을 포함해 해당 리소스가 지원하는 프로브나 상태 필드를 사용합니다.",
        ),
        (
            "A superficial success response or unobserved state can leave an unusable backend receiving work.",
            "표면적인 성공 응답이나 확인하지 않은 상태 때문에 사용할 수 없는 백엔드가 계속 작업을 받을 수 있습니다.",
        ),
        (
            "The configured signal distinguishes the intended healthy and unhealthy conditions and has a documented consumer.",
            "설정한 신호가 필요한 정상과 비정상 조건을 구분하며 해당 신호를 사용하는 구성 요소가 명확합니다.",
        ),
        (
            "Define the failure represented by the signal, configure the supported path or state observation and align its consumer's thresholds and startup grace period.",
            "신호가 나타내는 장애를 정의하고 지원되는 경로나 상태 관찰을 구성합니다. 사용하는 쪽의 임계값과 시작 유예 시간을 맞춥니다.",
        ),
        (
            "Compare observed signal transitions with actual request behavior during an approved slow-start or failure scenario; verify routing, restart or escalation behavior separately.",
            "승인된 느린 시작 또는 장애 시나리오에서 신호 변화와 실제 요청 처리를 비교합니다. 라우팅, 재시작 또는 에스컬레이션 동작을 따로 검증합니다.",
        ),
        (
            "An overly broad dependency probe can remove every instance at once; a management state of Available is not an application transaction success.",
            "범위가 지나치게 넓은 의존성 프로브는 모든 인스턴스를 동시에 제외할 수 있습니다. 관리 상태가 Available이어도 애플리케이션 트랜잭션 성공을 뜻하지는 않습니다.",
        ),
    ),
    "maintenance": profile(
        "patch-workflow",
        (
            "A maintenance window coordinates eligible platform, image or application updates with workload readiness. The scope determines prerequisites and what is controlled; scheduling a window is not a guarantee of zero interruption or proof that assignments are complete.",
            "유지 관리 시간대는 지원되는 플랫폼, 이미지 또는 애플리케이션 업데이트를 워크로드의 준비 상태와 조율합니다. 범위에 따라 전제 조건과 통제 대상이 달라집니다. 시간대를 정해도 무중단이나 할당의 완전성이 보장되지는 않습니다.",
        ),
        (
            "Confirm the exact maintenance scope, supported resource or SKU, scheduling limits and update-orchestration prerequisites.",
            "정확한 유지 관리 범위, 지원 리소스나 SKU, 일정 제약과 업데이트 오케스트레이션 조건을 확인합니다.",
        ),
        (
            "Updates can arrive without a workload-aligned schedule, or an existing schedule can omit eligible targets.",
            "업데이트 일정이 워크로드와 맞지 않거나 기존 일정에서 지원 대상이 빠져 있을 수 있습니다.",
        ),
        (
            "Eligible targets have effective maintenance assignments and a coordinated drain, update and health-validation procedure.",
            "지원 대상에 실제 유지 관리 할당을 적용하고 작업 마무리, 업데이트와 상태 검증 절차를 조율합니다.",
        ),
        (
            "Choose the service-supported scope and window, enumerate effective target assignments and prepare workload draining, rollback and post-update validation.",
            "서비스가 지원하는 범위와 시간대를 선택하고 실제 대상 할당을 열거합니다. 작업 마무리, 롤백과 업데이트 후 검증을 준비합니다.",
        ),
        (
            "Inspect the effective schedule, assignment coverage and completed update history. Compare application errors and reconnect behavior during the window against the agreed limits.",
            "적용된 일정, 할당 범위와 완료된 업데이트 이력을 확인합니다. 시간대 중 애플리케이션 오류와 재연결 동작을 합의한 기준과 비교합니다.",
        ),
        (
            "Do not transfer Host, OS image or Guest prerequisites to another scope. Emergency or unsupported maintenance can follow different rules.",
            "Host, OS image, Guest 중 한 범위의 전제 조건을 다른 범위에 적용하지 않습니다. 긴급하거나 지원 범위 밖인 유지 관리에는 다른 규칙이 적용될 수 있습니다.",
        ),
    ),
    "scheduled-events": profile(
        "event-drain",
        (
            "Scheduled Events notify a guest about eligible upcoming infrastructure events. A guest-side consumer must interpret event type, affected resources and timing, then carry out a supported drain or recovery procedure.",
            "Scheduled Events는 지원되는 인프라 이벤트가 다가오면 게스트에 알립니다. 게스트의 처리기가 이벤트 종류, 대상 리소스와 시각을 해석하고 지원되는 작업 마무리나 복구 절차를 수행해야 합니다.",
        ),
        (
            "Check guest access to the metadata event service and workload support for the required event types and acknowledgement.",
            "게스트의 메타데이터 이벤트 서비스 접근과 필요한 이벤트 종류 및 승인 응답에 대한 워크로드 지원을 확인합니다.",
        ),
        (
            "The workload may be unaware of planned interruption or receive events without a functioning handler.",
            "워크로드가 예정된 중단을 알지 못하거나 이벤트를 받아도 처리기가 동작하지 않을 수 있습니다.",
        ),
        (
            "A monitored guest consumer maps relevant events to documented, bounded workload preparation.",
            "모니터링되는 게스트 처리기가 관련 이벤트를 문서화되고 범위가 제한된 준비 절차에 연결합니다.",
        ),
        (
            "Implement supported event polling and deduplication, map each relevant event to graceful drain or failover and preserve event acknowledgements and timing.",
            "지원되는 이벤트 조회와 중복 처리를 구현합니다. 관련 이벤트를 안전한 작업 마무리나 장애 조치에 연결하고 응답과 시각을 기록합니다.",
        ),
        (
            "Use an approved event simulation or retained maintenance record to verify receipt, resource targeting, handling latency and workload continuity.",
            "승인된 이벤트 모의 시험이나 보존된 유지 관리 기록으로 수신, 대상 선택, 처리 지연과 워크로드 연속성을 검증합니다.",
        ),
        (
            "Notifications do not prevent every interruption and are not an authorization to fail over or shut down resources.",
            "알림이 모든 중단을 막아 주지는 않으며 리소스를 장애 조치하거나 종료할 권한을 부여하지도 않습니다.",
        ),
    ),
    "lifecycle": profile(
        "supported-migration",
        (
            "Retiring platforms, images, SDKs and runtimes introduce support and compatibility risk. Migration must preserve the application's behavior and dependencies; a newer version is not automatically a compatible or reversible replacement.",
            "사용 중단되는 플랫폼, 이미지, SDK와 런타임은 지원과 호환성 위험을 만듭니다. 이전할 때 애플리케이션 동작과 의존성을 유지해야 합니다. 새 버전이라고 해서 자동으로 호환되거나 되돌릴 수 있는 것은 아닙니다.",
        ),
        (
            "Read the current support or retirement notice for the exact version, SKU and deployment model named by the source.",
            "원본이 지정한 정확한 버전, SKU와 배포 모델의 현재 지원 또는 사용 중단 안내를 확인합니다.",
        ),
        (
            "The current component may be unsupported, nearing retirement or incompatible with required service capabilities.",
            "현재 구성 요소가 지원 종료 상태이거나 종료를 앞두고 있거나 필요한 서비스 기능과 호환되지 않을 수 있습니다.",
        ),
        (
            "A supported target has passed compatibility tests and has an explicit cutover and recovery plan.",
            "지원되는 대상을 호환성 시험으로 검증하고 명시적인 전환 및 복구 계획을 마련합니다.",
        ),
        (
            "Inventory exact versions and dependencies, choose a supported target, test in a representative isolated environment and prepare the documented migration and rollback path.",
            "정확한 버전과 의존성을 확인하고 지원되는 대상을 선택합니다. 대표적인 격리 환경에서 시험한 뒤 문서가 정한 이전 및 롤백 경로를 준비합니다.",
        ),
        (
            "Read back effective versions and provisioning state, run application and telemetry regression checks and confirm old dependencies are no longer required.",
            "적용된 버전과 프로비전 상태를 다시 확인합니다. 애플리케이션과 원격 분석의 회귀 시험을 수행하고 이전 의존성이 더 이상 필요하지 않은지 확인합니다.",
        ),
        (
            "Pinned APRL guidance can predate today's retirement schedule. Consult the current official notice before planning changes; unsupported direct upgrades must not be invented.",
            "고정된 APRL 권고는 현재 사용 중단 일정보다 오래되었을 수 있습니다. 변경을 계획하기 전에 최신 공식 안내를 확인하고 지원되지 않는 직접 업그레이드를 만들어 내지 않습니다.",
        ),
    ),
    "deployment": profile(
        "staged-deployment",
        (
            "Versioned, staged deployment makes a replacement reproducible and separates preparation from traffic cutover. Validation must cover configuration, identity, state and warmup, because a successfully created resource can still be unusable.",
            "버전으로 관리하는 단계적 배포는 대체 환경을 재현하고 준비와 트래픽 전환을 분리합니다. 리소스 생성이 성공해도 사용할 수 없을 수 있으므로 구성, 신원, 데이터와 준비 과정을 검증해야 합니다.",
        ),
        (
            "Confirm the source-specific deployment model, supported migration or swap operations and treatment of persistent and ephemeral state.",
            "권고에 맞는 배포 모델, 지원되는 이전 또는 교환 작업과 영속 및 임시 상태의 처리 방식을 확인합니다.",
        ),
        (
            "In-place or manually reconstructed changes can expose users before readiness is established and complicate rollback.",
            "직접 변경하거나 수동으로 재구축하면 준비 상태를 확인하기 전에 사용자에게 노출되고 롤백도 어려워질 수 있습니다.",
        ),
        (
            "A reproducible candidate is validated before an explicitly controlled replacement, promotion or traffic switch.",
            "재현 가능한 후보를 검증한 다음 명시적으로 통제한 교체, 승격 또는 트래픽 전환을 수행합니다.",
        ),
        (
            "Version the desired state, prepare a candidate with correct dependencies and configuration, and define readiness, drain, cutover and rollback criteria.",
            "원하는 상태를 버전으로 관리하고 올바른 의존성과 구성을 가진 후보를 준비합니다. 준비 상태, 작업 마무리, 전환과 롤백 기준을 정합니다.",
        ),
        (
            "Compare effective candidate configuration with the intended version, exercise representative requests and validate state and configuration behavior across an approved replacement.",
            "후보의 실제 구성과 의도한 버전을 비교하고 대표 요청을 시험합니다. 승인된 교체 과정에서 데이터 상태와 구성 동작을 검증합니다.",
        ),
        (
            "Staging does not authorize promotion, and rollback can require data reconciliation rather than merely restoring an old image.",
            "단계적 배포가 승격 권한을 부여하지는 않습니다. 롤백에는 이전 이미지 복원뿐 아니라 데이터 조정이 필요할 수도 있습니다.",
        ),
    ),
    "selfheal": profile(
        "bounded-recovery",
        (
            "Automated recovery consumes a health signal and performs a bounded repair, restart or failover. Correct thresholds, fencing and stop conditions prevent an unhealthy signal from causing a repeated restart loop or conflicting active owners.",
            "자동 복구는 상태 신호를 받아 범위가 제한된 수리, 재시작 또는 장애 조치를 수행합니다. 정확한 임계값, 펜싱과 중단 조건으로 잘못된 신호가 반복 재시작이나 이중 활성 소유자를 만들지 않도록 해야 합니다.",
        ),
        (
            "Use only the service's supported repair mechanism and verify the health source, grace period, state ownership and recovery prerequisites.",
            "서비스가 지원하는 복구 방식만 사용하고 상태 신호, 유예 시간, 데이터 소유권과 복구 전제 조건을 확인합니다.",
        ),
        (
            "A failed instance can remain in service, while an overly aggressive repair can repeatedly disrupt otherwise recoverable work.",
            "장애 인스턴스가 계속 처리에 참여하거나 지나치게 공격적인 복구가 회복 가능한 작업을 반복해서 중단할 수 있습니다.",
        ),
        (
            "Reviewed health conditions trigger a controlled supported recovery with visible completion and bounded retry behavior.",
            "검토한 상태 조건으로 지원되는 복구를 통제하고 완료 여부와 제한된 재시도 동작을 관찰합니다.",
        ),
        (
            "Configure the exact health source and supported action, include grace and cooldown periods, protect persistent state and define a stop or escalation condition.",
            "정확한 상태 신호와 지원 작업을 설정하고 유예 및 대기 시간을 둡니다. 영속 상태를 보호하고 중단 또는 에스컬레이션 조건을 정합니다.",
        ),
        (
            "Use an approved failure exercise to observe detection, repair, restored application behavior and protection against repeated or simultaneous unsafe recovery.",
            "승인된 장애 시험으로 탐지, 복구, 애플리케이션 회복과 반복 또는 동시의 위험한 복구를 막는 동작을 확인합니다.",
        ),
        (
            "An enabled repair policy is neither a healthy instance nor permission to execute a repair. Stateful cluster fencing and split-brain prevention remain mandatory.",
            "복구 정책이 활성화되었다고 인스턴스가 정상인 것도, 복구 실행 권한이 생기는 것도 아닙니다. 상태 저장 클러스터의 펜싱과 이중 활성 방지는 계속 필요합니다.",
        ),
    ),
    "retry": profile(
        "bounded-retry",
        (
            "Transient failures can be retried, but persistent errors and non-idempotent operations need different handling. Bounded attempts, delay and jitter limit retry amplification and preserve an observable terminal failure.",
            "일시적 오류는 재시도할 수 있지만 지속적인 오류와 멱등성이 없는 작업은 다르게 처리해야 합니다. 횟수, 지연과 지터를 제한해 재시도 폭증을 막고 최종 실패를 관찰할 수 있어야 합니다.",
        ),
        (
            "Classify the exact SDK or job errors, timeout budget, server retry hints and duplicate-side-effect risks.",
            "정확한 SDK 또는 작업 오류, 시간 제한, 서버의 재시도 안내와 중복 부작용 위험을 분류합니다.",
        ),
        (
            "Immediate failure loses recoverable work, while unbounded retries can overload a dependency or duplicate side effects.",
            "즉시 실패하면 복구 가능한 작업을 잃고, 무제한 재시도는 의존 리소스를 과부하시키거나 부작용을 중복 발생시킬 수 있습니다.",
        ),
        (
            "Retryable conditions use bounded delay and an overall deadline with idempotent outputs and terminal failure handling.",
            "재시도 가능한 조건에 지연과 전체 기한을 제한하고 멱등한 출력과 최종 실패 처리를 마련합니다.",
        ),
        (
            "Choose supported retryable errors, honor server delay hints, set per-attempt and total deadlines and make writes or job outputs safe to repeat.",
            "지원되는 재시도 대상 오류를 선택하고 서버의 지연 안내를 따릅니다. 시도별 및 전체 기한을 정하고 쓰기나 작업 출력을 안전하게 반복할 수 있게 합니다.",
        ),
        (
            "Inject an approved transient and persistent failure; verify attempt bounds, delay, total latency, no duplicate side effects and visible exhaustion.",
            "승인된 일시적 및 지속적 장애를 주입해 시도 제한, 지연, 전체 지연 시간, 중복 부작용 방지와 재시도 소진 표시를 검증합니다.",
        ),
        (
            "Retries are not failover or a cure for sustained quota exhaustion; stacked SDK and application retries can multiply load.",
            "재시도는 장애 조치나 지속적인 할당량 부족의 해결책이 아닙니다. SDK와 애플리케이션의 재시도가 겹치면 부하가 배로 늘 수 있습니다.",
        ),
    ),
    "draining": profile(
        "connection-drain",
        (
            "Graceful draining stops assigning new work while existing work finishes within a bounded interval. Load-balancer draining and Kubernetes disruption budgets have different scopes, but both must be coordinated with shutdown and remaining serving capacity.",
            "안전한 작업 마무리는 새 작업 할당을 중단하고 정해진 시간 안에 기존 작업을 끝내는 과정입니다. 부하 분산기의 연결 정리와 Kubernetes 중단 예산은 범위가 다르지만 종료와 남은 처리 용량을 함께 조율해야 합니다.",
        ),
        (
            "Identify supported drain or voluntary-disruption controls, long-running work and the minimum healthy capacity.",
            "지원되는 연결 정리 또는 자발적 중단 제어, 장기 실행 작업과 최소 정상 용량을 확인합니다.",
        ),
        (
            "Backend removal or maintenance can terminate active work, or an overly strict disruption limit can block necessary upgrades.",
            "백엔드 제거나 유지 관리가 진행 중인 작업을 끊거나 지나치게 엄격한 중단 제한이 필요한 업그레이드를 막을 수 있습니다.",
        ),
        (
            "Reviewed drain or disruption settings preserve the intended minimum service capacity while permitting supported maintenance.",
            "검토한 작업 마무리 또는 중단 설정으로 최소 서비스 용량을 유지하면서 지원되는 유지 관리를 허용합니다.",
        ),
        (
            "Set source-specific selectors, allowed disruptions or drain timeout, align application termination behavior and ensure enough remaining ready instances.",
            "대상 선택 조건, 허용 중단 수 또는 연결 정리 제한 시간을 정합니다. 애플리케이션 종료 동작을 맞추고 충분한 준비 인스턴스를 남깁니다.",
        ),
        (
            "Perform an approved controlled removal or voluntary drain and inspect new-request routing, in-flight completion, remaining readiness and maintenance progress.",
            "승인된 통제된 제거 또는 자발적 작업 정리를 수행합니다. 새 요청 라우팅, 기존 작업 완료, 남은 준비 상태와 유지 관리 진행을 확인합니다.",
        ),
        (
            "A disruption budget does not prevent involuntary node or zone failure, and drain timeout expiry can still terminate long-running connections.",
            "중단 예산은 비자발적인 노드나 영역 장애를 막지 못합니다. 연결 정리 제한 시간이 지나면 장기 연결이 종료될 수도 있습니다.",
        ),
    ),
    "cache": profile(
        "cache",
        (
            "Caching reduces repeated backend work but introduces a retained copy with freshness and availability behavior of its own. Policies must define what can be cached, how long it remains valid and what happens on a miss or cache failure.",
            "캐시는 백엔드의 반복 작업을 줄이지만 자체 최신성과 가용성을 가진 사본을 추가합니다. 무엇을 얼마 동안 저장할지, 적중하지 않거나 캐시에 장애가 나면 어떻게 처리할지 정책으로 정해야 합니다.",
        ),
        (
            "Review response sensitivity, cache keys, user isolation, expiry and support for the selected API Management tier.",
            "응답의 민감도, 캐시 키, 사용자 간 격리, 만료와 선택한 API Management 계층의 지원을 검토합니다.",
        ),
        (
            "Repeated requests always reach the backend or an existing cache has undefined freshness and failure behavior.",
            "반복 요청이 항상 백엔드에 도달하거나 기존 캐시의 최신성과 장애 동작이 정의되어 있지 않을 수 있습니다.",
        ),
        (
            "Explicit cache policies reduce backend load while preserving response correctness and safe miss handling.",
            "명시적인 캐시 정책으로 응답 정확성과 안전한 미적중 처리를 유지하면서 백엔드 부하를 줄입니다.",
        ),
        (
            "Define safe cache keys and lifetimes, configure supported lookup and store policies and preserve rate or capacity protection when falling back to the backend.",
            "안전한 캐시 키와 유효 기간을 정하고 지원되는 조회 및 저장 정책을 설정합니다. 백엔드로 대체할 때도 요청 제한과 용량 보호를 유지합니다.",
        ),
        (
            "Compare hit, miss, expiry and unavailable-cache requests with the original backend response; measure backend load and verify no cross-user data leakage.",
            "적중, 미적중, 만료와 캐시 장애 요청을 원래 백엔드 응답과 비교합니다. 백엔드 부하를 측정하고 사용자 간 데이터 누출이 없는지 검증합니다.",
        ),
        (
            "A cache is not an authoritative backup or proof of backend health; stale or incorrectly keyed data can be a correctness and privacy failure.",
            "캐시는 원본 백업이나 백엔드 정상 상태의 증명이 아닙니다. 오래되거나 잘못된 키로 저장한 데이터는 정확성과 개인정보 보호를 해칠 수 있습니다.",
        ),
    ),
}
