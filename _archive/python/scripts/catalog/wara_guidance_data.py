"""Data-flow, design-review and model-deployment explanations."""
# ruff: noqa: E501

from wara_guidance_reliability import profile

PROFILES = {
    "pipeline": profile(
        "durable-workflow",
        (
            "Durable checkpoints, task state and failure destinations let a pipeline resume without silently losing work. Recovery must account for already committed outputs, schema compatibility and how partially completed tasks are replayed.",
            "영속 체크포인트, 작업 상태와 실패 대상을 사용하면 파이프라인이 작업을 조용히 잃지 않고 재개할 수 있습니다. 이미 확정한 출력, 스키마 호환성과 부분 완료 작업의 재실행 방식을 복구에 반영해야 합니다.",
        ),
        (
            "Identify the exact streaming, batch, query-pagination or event-delivery mechanism and its supported replay and retention semantics.",
            "정확한 스트리밍, 일괄 작업, 조회 페이지 처리 또는 이벤트 전달 방식과 지원되는 재실행 및 보존 의미를 확인합니다.",
        ),
        (
            "Local or missing progress state can force a full restart, omit remaining results or duplicate committed outputs.",
            "진행 상태가 로컬에만 있거나 없으면 전체 재시작, 나머지 결과 누락 또는 확정 출력의 중복이 발생할 수 있습니다.",
        ),
        (
            "Durable progress and explicit failure handling preserve the intended workload's completion and replay boundaries.",
            "영속 진행 상태와 명시적인 실패 처리로 워크로드의 완료 및 재실행 경계를 보존합니다.",
        ),
        (
            "Configure the supported checkpoint, continuation, retry or dead-letter mechanism, protect progress-state storage and document idempotent replay and terminal failure handling.",
            "지원되는 체크포인트, 연속 토큰, 재시도 또는 배달 못한 메시지 처리를 구성합니다. 진행 상태 저장소를 보호하고 멱등한 재실행과 최종 실패 처리를 문서화합니다.",
        ),
        (
            "Use an approved partial-failure scenario and compare recovered input, progress and outputs; verify no skipped remaining work and no unexplained duplicate side effects.",
            "승인된 부분 장애 시나리오에서 복구한 입력, 진행 상태와 출력을 비교합니다. 남은 작업의 누락이나 설명되지 않는 중복 부작용이 없는지 검증합니다.",
        ),
        (
            "Checkpoint or dead-letter storage can expire or become inaccessible. A successful restart alone does not demonstrate complete or exactly-once business results.",
            "체크포인트나 배달 못한 메시지 저장소는 만료되거나 접근 불가가 될 수 있습니다. 재시작 성공만으로 완전하거나 정확히 한 번인 업무 결과를 입증할 수는 없습니다.",
        ),
    ),
    "data-integrity": profile(
        "data-lineage",
        (
            "Reliable data processing requires explicit quality, schema and ownership boundaries. Layering, transactional tables and rescued records serve different purposes, but each must make invalid, stale or competing data visible instead of hiding it.",
            "안정적인 데이터 처리에는 품질, 스키마와 소유권 경계가 필요합니다. 계층화, 트랜잭션 테이블과 구조가 맞지 않는 레코드의 별도 보존은 목적이 다르지만 잘못되거나 오래되거나 서로 다른 데이터가 드러나게 해야 합니다.",
        ),
        (
            "Identify authoritative datasets, supported table or ingestion features, schema contracts and downstream quality requirements.",
            "권한 있는 데이터셋, 지원되는 테이블 또는 수집 기능, 스키마 계약과 하위 처리의 품질 요구를 확인합니다.",
        ),
        (
            "Uncontrolled copies, invalid records or schema drift can obscure the authoritative state and break downstream processing.",
            "통제되지 않은 사본, 잘못된 레코드나 스키마 변경이 기준 상태를 흐리거나 하위 처리를 중단할 수 있습니다.",
        ),
        (
            "The source-specific data-quality mechanism has explicit acceptance, quarantine, lineage and recovery behavior.",
            "권고에 맞는 데이터 품질 기능에 수용, 격리, 계보와 복구 동작을 명시합니다.",
        ),
        (
            "Define ownership and quality boundaries, configure the exact constraints, layers, transactional format or rescue behavior and document schema evolution and retained history.",
            "소유권과 품질 경계를 정합니다. 정확한 제약, 계층, 트랜잭션 형식 또는 별도 보존 동작을 설정하고 스키마 변경과 이력 보존을 문서화합니다.",
        ),
        (
            "Test representative valid, invalid and changed-schema inputs in an approved scope; inspect accepted and quarantined records, lineage and downstream consistency.",
            "승인된 범위에서 정상, 오류와 변경된 스키마 입력을 시험합니다. 수용 및 격리 레코드, 계보와 하위 처리의 일관성을 확인합니다.",
        ),
        (
            "Reducing uncontrolled data copies does not mean removing intentional backups or resilience replicas; quality checks must not silently discard required records.",
            "통제되지 않은 사본을 줄인다는 것은 의도한 백업이나 복원력 복제본을 없앤다는 뜻이 아닙니다. 품질 검사가 필요한 레코드를 조용히 버려서는 안 됩니다.",
        ),
    ),
    "data-export": profile(
        "data-export",
        (
            "Export copies selected log tables to another storage boundary. It can improve data availability, but export coverage, delivery delay, destination redundancy and the supported recovery or query path must be evaluated separately.",
            "내보내기는 선택한 로그 테이블을 다른 저장소 경계에 복사합니다. 데이터 가용성에 도움이 될 수 있지만 범위, 전달 지연, 대상 중복과 지원되는 복구 또는 조회 경로는 따로 평가해야 합니다.",
        ),
        (
            "Check supported export tables, rule scope, destination region and supported GRS or GZRS behavior.",
            "내보내기를 지원하는 테이블, 규칙 범위, 대상 지역과 지원되는 GRS 또는 GZRS 동작을 확인합니다.",
        ),
        (
            "Workspace data may have no independent exported copy or export may cover only some required tables.",
            "작업 영역 데이터에 독립적인 내보낸 사본이 없거나 필요한 테이블 일부만 포함되어 있을 수 있습니다.",
        ),
        (
            "Selected supported tables reach the intended redundant destination with observable freshness and known coverage.",
            "선택한 지원 테이블을 의도한 중복 대상에 전달하고 최신성과 범위를 관찰합니다.",
        ),
        (
            "Select supported tables and an eligible destination, configure export rules and destination access and define how retained exported records will be used during recovery.",
            "지원 테이블과 적격 대상을 선택하고 내보내기 규칙과 대상 접근을 설정합니다. 복구 때 보존된 기록을 사용하는 방법도 정합니다.",
        ),
        (
            "Compare a known recent source record with its exported copy, inspect delivery errors and delay and verify the destination's actual redundancy configuration.",
            "알려진 최근 원본 레코드와 내보낸 사본을 비교합니다. 전달 오류와 지연 및 대상의 실제 중복 구성을 확인합니다.",
        ),
        (
            "Export is not a full workspace backup or automatic rehydration, and geo-redundant storage has its own replication and recovery constraints.",
            "내보내기는 전체 작업 영역 백업이나 자동 재수집이 아닙니다. 지역 중복 저장소에도 별도의 복제와 복구 제약이 있습니다.",
        ),
    ),
    "recovery-targets": profile(
        "recovery-objectives",
        (
            "Reliability targets turn business impact into measurable availability and recovery requirements. RTO measures tolerated recovery duration and RPO the tolerated data-loss interval; neither is established by selecting a service SKU.",
            "복원력 목표는 업무 영향을 측정 가능한 가용성과 복구 요구로 바꿉니다. RTO는 허용 복구 시간, RPO는 허용 데이터 손실 구간이며 서비스 SKU를 선택했다고 정해지는 값은 아닙니다.",
        ),
        (
            "Include business owners, critical flows, measurement windows and the boundaries of each availability or recovery target.",
            "업무 책임자, 중요 흐름, 측정 구간과 각 가용성 또는 복구 목표의 경계를 포함합니다.",
        ),
        (
            "Teams may use ambiguous availability claims without a shared recovery-time or data-loss budget.",
            "팀 사이에 공통 복구 시간이나 데이터 손실 예산 없이 모호한 가용성 주장을 사용할 수 있습니다.",
        ),
        (
            "Business-approved measurable targets guide architecture, protection, alerting and recovery exercises.",
            "업무에서 승인한 측정 가능한 목표를 아키텍처, 보호, 경고와 복구 시험의 기준으로 사용합니다.",
        ),
        (
            "Rank critical flows, quantify outage and data-loss impact and record approved SLO, RTO and RPO definitions with owners and assumptions.",
            "중요 흐름의 우선순위를 정하고 중단 및 데이터 손실 영향을 정량화합니다. 책임자와 가정을 포함해 승인된 SLO, RTO와 RPO 정의를 기록합니다.",
        ),
        (
            "Check that each target has a measurement method and compare retained incident or exercise results with the exact stated boundaries.",
            "목표마다 측정 방법이 있는지 확인하고 보존된 장애 또는 시험 결과를 명시한 정확한 경계와 비교합니다.",
        ),
        (
            "Service SLAs and component uptime do not automatically compose into a workload SLO or prove recovery objectives have been met.",
            "서비스 SLA와 구성 요소 가동률을 합쳐도 워크로드 SLO가 자동으로 만들어지거나 복구 목표 달성이 입증되지는 않습니다.",
        ),
    ),
    "workload-flows": profile(
        "critical-flows",
        (
            "Business-critical flows link user or system outcomes to their dependencies. Ranking those flows reveals where availability loss matters and prevents uniform investment in components that have very different business impact.",
            "중요 업무 흐름은 사용자 또는 시스템 결과와 의존성을 연결합니다. 우선순위를 정하면 가용성 손실이 중요한 지점을 드러내고 업무 영향이 크게 다른 구성 요소에 동일하게 투자하는 일을 줄일 수 있습니다.",
        ),
        (
            "Include interactive and background system flows, dependency ownership and agreed business-impact ratings.",
            "대화형 흐름과 백그라운드 시스템 흐름, 의존성 책임자와 합의한 업무 영향 등급을 포함합니다.",
        ),
        (
            "A resource inventory alone can omit critical end-to-end flows and their shared dependencies.",
            "리소스 목록만으로는 중요한 전체 흐름과 공통 의존성을 놓칠 수 있습니다.",
        ),
        (
            "Ranked flow maps connect business objectives to dependency risks, measurements and recovery priorities.",
            "우선순위를 정한 흐름 지도로 업무 목표를 의존성 위험, 측정과 복구 우선순위에 연결합니다.",
        ),
        (
            "Map actual user and system flows with business owners, rate impact and identify required and optional dependencies and acceptable degraded behavior.",
            "업무 책임자와 실제 사용자 및 시스템 흐름을 정리합니다. 영향을 평가하고 필수 및 선택 의존성과 허용되는 기능 축소를 확인합니다.",
        ),
        (
            "Walk representative flows with owners and compare maps against retained traces or architecture evidence; confirm each critical flow has an objective and recovery owner.",
            "책임자와 대표 흐름을 따라가며 보존된 추적 또는 아키텍처 근거와 지도를 비교합니다. 중요 흐름마다 목표와 복구 책임자가 있는지 확인합니다.",
        ),
        (
            "Component counts or generic architecture diagrams do not establish business criticality; unresolved business assumptions remain open review items.",
            "구성 요소 수나 일반 아키텍처 그림만으로 업무 중요도를 정할 수 없습니다. 해결되지 않은 업무 가정은 검토 항목으로 남깁니다.",
        ),
    ),
    "partition": profile(
        "data-partition",
        (
            "Partitioning distributes data and load but changes transaction, consistency and recovery boundaries. A useful partition strategy avoids hot keys and makes cross-partition operations and failures explicit.",
            "분할은 데이터와 부하를 분산하지만 트랜잭션, 일관성과 복구 경계를 바꿉니다. 특정 키에 부하가 집중되지 않게 하고 분할 간 작업과 장애를 명시해야 합니다.",
        ),
        (
            "Use actual access patterns, tenant-independent workload characteristics, skew and supported storage transaction semantics.",
            "실제 접근 패턴, 특정 고객과 무관한 워크로드 특성, 편중과 저장소가 지원하는 트랜잭션 의미를 사용합니다.",
        ),
        (
            "A single hot partition or an unbounded cross-partition operation can become a shared availability bottleneck.",
            "부하가 몰린 단일 분할이나 범위 제한 없는 분할 간 작업이 공통 가용성 병목이 될 수 있습니다.",
        ),
        (
            "Reviewed partition keys and boundaries distribute expected load with explicit consistency and recovery behavior.",
            "검토한 분할 키와 경계로 예상 부하를 분산하고 일관성 및 복구 동작을 명시합니다.",
        ),
        (
            "Model key distribution and access paths, choose supported partition boundaries and plan movement, resharding and cross-partition transaction handling.",
            "키 분포와 접근 경로를 모델링하고 지원되는 분할 경계를 선택합니다. 이동, 재분할과 분할 간 트랜잭션 처리를 계획합니다.",
        ),
        (
            "Measure per-partition load and skew under representative demand and verify a single-partition failure and recovery do not silently corrupt cross-partition results.",
            "대표 수요에서 분할별 부하와 편중을 측정합니다. 단일 분할 장애와 복구가 분할 간 결과를 조용히 손상하지 않는지 검증합니다.",
        ),
        (
            "Partitioning is not replication or backup, and changing a partition key can require a disruptive data migration.",
            "분할은 복제나 백업이 아니며 분할 키 변경에는 서비스 중단을 동반하는 데이터 이전이 필요할 수 있습니다.",
        ),
    ),
    "fault-analysis": profile(
        "failure-modes",
        (
            "Failure-mode analysis links a concrete fault to its propagation, detection and business impact. Prioritization must include shared dependencies and residual risk, not merely list components or assume redundant instances fail independently.",
            "장애 모드 분석은 구체적인 결함을 전파, 탐지와 업무 영향에 연결합니다. 구성 요소를 나열하거나 중복 인스턴스가 독립적으로 고장 난다고 가정하지 말고 공통 의존성과 남은 위험을 우선순위에 반영해야 합니다.",
        ),
        (
            "Use the current critical-flow and dependency map and include control-plane, data-plane and operator-access failures.",
            "현재 중요 흐름과 의존성 지도를 사용하고 관리, 데이터와 운영자 접근 장애를 포함합니다.",
        ),
        (
            "Unexamined dependency failures can cascade beyond the component where the fault originates.",
            "검토하지 않은 의존성 장애가 시작된 구성 요소를 넘어 연쇄적으로 전파될 수 있습니다.",
        ),
        (
            "Prioritized failure modes have explicit effects, detection, mitigation, recovery and accepted residual risk.",
            "우선순위를 정한 장애 모드마다 영향, 탐지, 완화, 복구와 수용한 잔여 위험을 명시합니다.",
        ),
        (
            "Enumerate credible faults by flow and dependency, assess impact and likelihood and assign detection, mitigation and recovery owners with bounded follow-up.",
            "흐름과 의존성별로 현실적인 결함을 열거하고 영향과 발생 가능성을 평가합니다. 탐지, 완화와 복구 책임자 및 기한이 있는 후속 작업을 정합니다.",
        ),
        (
            "Challenge assumed independence and compare selected failure predictions with approved exercises or incident evidence; record untested modes as unverified.",
            "독립성 가정을 검토하고 선택한 장애 예측을 승인된 시험이나 장애 기록과 비교합니다. 시험하지 않은 모드는 미검증으로 기록합니다.",
        ),
        (
            "A risk workshop does not prove a failure cannot occur or authorize a chaos experiment; tests need their own scope and approval.",
            "위험 검토 회의는 장애가 불가능함을 입증하거나 장애 주입 시험을 승인하지 않습니다. 시험에는 별도의 범위와 승인이 필요합니다.",
        ),
    ),
    "ai-capacity": profile(
        "model-throughput",
        (
            "Provisioned throughput allocates model-serving capacity for a supported model and deployment type. Predictable capacity still depends on model version, utilization, request shape and deployment availability; Global does not mean a customer-managed regional failover configuration.",
            "프로비저닝된 처리량은 지원되는 모델과 배포 유형에 모델 처리 용량을 할당합니다. 예측 가능한 용량도 모델 버전, 사용률, 요청 형태와 배포 가용성에 달려 있습니다. Global은 고객이 구성한 지역 장애 조치와 같은 뜻이 아닙니다.",
        ),
        (
            "Review supported model versions, provisioned units, quota, geography policy and expected token and concurrency demand.",
            "지원 모델 버전, 프로비저닝 단위, 할당량, 지역 정책과 예상 토큰 및 동시 요청 수요를 검토합니다.",
        ),
        (
            "Serving demand and permitted processing geography may not align with the existing deployment and purchased capacity.",
            "처리 수요와 허용된 처리 위치가 기존 배포 및 구매 용량과 맞지 않을 수 있습니다.",
        ),
        (
            "The selected provisioned deployment matches approved geography and measured throughput needs with explicit headroom.",
            "선택한 프로비저닝 배포를 승인된 지역과 측정한 처리량 요구에 맞추고 여유 용량을 명시합니다.",
        ),
        (
            "Use the current deployment-type support matrix, size supported provisioned capacity and review overflow and regional contingency separately.",
            "현재 배포 유형 지원 표로 프로비저닝 용량을 산정하고 초과 처리 및 지역 비상 대책은 따로 검토합니다.",
        ),
        (
            "Inspect deployment type, model version and granted capacity; use retained load evidence to compare throughput, latency, throttling and utilization with objectives.",
            "배포 유형, 모델 버전과 할당 용량을 확인합니다. 보존된 부하 기록으로 처리량, 지연, 제한과 사용률을 목표와 비교합니다.",
        ),
        (
            "Global, Data Zone and Regional deployment types are not interchangeable. Do not promise a processing location or automatic failover from the type name alone.",
            "Global, Data Zone과 Regional 배포 유형은 서로 바꿔 쓸 수 없습니다. 유형 이름만으로 처리 위치나 자동 장애 조치를 약속하지 않습니다.",
        ),
    ),
    "ai-routing": profile(
        "model-routing",
        (
            "Global Standard is a supported pay-as-you-go deployment type with service-managed request placement. It is not the same as a separately deployed regional secondary or an application gateway's failover policy.",
            "Global Standard는 서비스가 요청 배치를 관리하는 종량제 배포 유형입니다. 별도로 배포한 지역 보조 대상이나 애플리케이션 게이트웨이의 장애 조치 정책과는 다릅니다.",
        ),
        (
            "Confirm current model and version support, quota, deployment-type availability and permitted processing geography.",
            "현재 모델과 버전 지원, 할당량, 배포 유형 가용성과 허용되는 처리 지역을 확인합니다.",
        ),
        (
            "An existing deployment type may not match the workload's required capacity or geography constraints.",
            "기존 배포 유형이 워크로드의 필요한 용량이나 지역 제약과 맞지 않을 수 있습니다.",
        ),
        (
            "The chosen Global Standard deployment is explicitly approved for workload compatibility, quota and geography.",
            "선택한 Global Standard 배포의 워크로드 호환성, 할당량과 지역 조건을 명시적으로 검토합니다.",
        ),
        (
            "Review the current deployment-type documentation, select a compatible model and version and document application routing, retries and geography constraints.",
            "현재 배포 유형 문서에서 호환되는 모델과 버전을 선택하고 애플리케이션 라우팅, 재시도와 지역 제약을 문서화합니다.",
        ),
        (
            "Read actual deployment type and model version and compare retained request metrics and quota with expected demand; inspect geography policy approval independently.",
            "실제 배포 유형과 모델 버전을 확인하고 보존된 요청 메트릭 및 할당량을 예상 수요와 비교합니다. 지역 정책 승인은 별도로 확인합니다.",
        ),
        (
            "Do not infer Regional or Data Zone processing rules from Global Standard, or assume its service routing configures customer failover.",
            "Global Standard에 Regional 또는 Data Zone의 처리 규칙을 적용하거나 서비스 라우팅이 고객 장애 조치를 구성한다고 가정하지 않습니다.",
        ),
    ),
    "ai-overflow": profile(
        "model-overflow",
        (
            "An explicit alternate pay-as-you-go deployment can absorb eligible overflow from provisioned capacity only when a gateway or client routes requests to it. Compatibility, throttling behavior, authorization and geography must be reviewed on both paths.",
            "프로비저닝 용량을 넘는 요청은 게이트웨이나 클라이언트가 명시적으로 대체 종량제 배포에 전달해야 처리할 수 있습니다. 양쪽 경로의 호환성, 제한 동작, 권한과 지역 조건을 검토해야 합니다.",
        ),
        (
            "Use compatible model versions and request semantics, separately available quota and an approved processing geography on the alternate path.",
            "대체 경로에서도 호환 모델 버전과 요청 의미, 별도 가용 할당량과 승인된 처리 지역을 사용합니다.",
        ),
        (
            "Provisioned throttling can cause request failures even if an alternate deployment exists but no route selects it.",
            "대체 배포가 있어도 선택 경로가 없으면 프로비저닝 용량 제한으로 요청이 실패할 수 있습니다.",
        ),
        (
            "A bounded explicit overflow policy selects only eligible alternate capacity and exposes route and error observations.",
            "범위가 제한된 명시적 초과 처리 정책으로 지원되는 대체 용량만 선택하고 경로와 오류를 관찰합니다.",
        ),
        (
            "Define retryable overflow conditions, compatible alternate deployments, authentication and route limits; honor server delays and an overall request deadline.",
            "재시도 가능한 초과 조건, 호환 대체 배포, 인증과 경로 한도를 정의합니다. 서버 지연 안내와 전체 요청 기한을 따릅니다.",
        ),
        (
            "Inspect the actual policy and retained route traces for primary and overflow requests, model version, errors, throttling and quota without making live model calls during catalog build.",
            "실제 정책과 보존된 경로 추적으로 주 경로 및 초과 요청, 모델 버전, 오류, 제한과 할당량을 확인합니다. 카탈로그 빌드 중 실제 모델을 호출하지 않습니다.",
        ),
        (
            "Overflow capacity is neither guaranteed nor free, and duplicate retries can amplify cost or change request semantics.",
            "초과 처리 용량은 보장되거나 무료인 것이 아닙니다. 중복 재시도는 비용을 늘리거나 요청 의미를 바꿀 수 있습니다.",
        ),
    ),
    "ai-batch": profile(
        "model-batch",
        (
            "Global Batch is asynchronous model processing for eligible workloads, not low-latency online failover. Completion windows, supported models, input validation and processing geography must fit the business job.",
            "Global Batch는 적격 워크로드를 위한 비동기 모델 처리이며 낮은 지연의 온라인 장애 조치가 아닙니다. 완료 시간, 지원 모델, 입력 검증과 처리 지역이 업무 작업에 맞아야 합니다.",
        ),
        (
            "Apply only to batch-compatible jobs that tolerate the documented asynchronous completion and data-processing constraints.",
            "문서가 정한 비동기 완료와 데이터 처리 제약을 수용하는 일괄 작업에만 적용합니다.",
        ),
        (
            "Large offline jobs can compete with online request limits or have no explicit completion and failure accounting.",
            "대규모 오프라인 작업이 온라인 요청 한도를 소모하거나 완료 및 실패 집계가 명확하지 않을 수 있습니다.",
        ),
        (
            "Eligible offline requests use a supported batch deployment with explicit job tracking and complete result reconciliation.",
            "적격 오프라인 요청을 지원되는 일괄 배포로 처리하고 작업 추적 및 전체 결과 조정을 명시합니다.",
        ),
        (
            "Select a supported model and deployment type, validate job input, define deadlines and retain identifiers for status, cancellation and result reconciliation.",
            "지원 모델과 배포 유형을 선택하고 작업 입력을 검증합니다. 기한을 정하고 상태, 취소와 결과 조정에 필요한 식별자를 보존합니다.",
        ),
        (
            "Use retained job records to compare submitted, completed and failed item counts, timing and processing-policy approval; investigate missing or duplicate results.",
            "보존된 작업 기록으로 제출, 완료와 실패 항목 수, 시각과 처리 정책 승인을 비교합니다. 누락되거나 중복된 결과를 조사합니다.",
        ),
        (
            "Global Batch does not supply an interactive latency guarantee or prove regional processing residency from the deployment resource location.",
            "Global Batch는 대화형 지연 보장을 제공하지 않으며 배포 리소스 위치만으로 지역 처리 상주성을 입증하지도 않습니다.",
        ),
    ),
    "ai-residency": profile(
        "model-geography",
        (
            "Data Zone Standard constrains service processing according to its documented data-zone model. The selected resource region, deployment type, processing geography and storage or retention behavior are separate facts that require policy review.",
            "Data Zone Standard는 문서의 데이터 영역 모델에 따라 서비스 처리를 제한합니다. 선택한 리소스 지역, 배포 유형, 처리 지역과 저장 또는 보존 동작은 서로 다른 사실이므로 정책 검토가 필요합니다.",
        ),
        (
            "Check current data-zone coverage, supported model versions, regional availability, quota and the workload's approved data-handling requirements.",
            "현재 데이터 영역 범위, 지원 모델 버전, 지역 가용성, 할당량과 승인된 데이터 처리 요구를 확인합니다.",
        ),
        (
            "A deployment resource's region alone can be mistaken for a guarantee about all request processing and retention.",
            "배포 리소스의 지역만 보고 모든 요청 처리와 보존 위치가 보장된다고 오해할 수 있습니다.",
        ),
        (
            "Deployment type and current service terms are explicitly mapped to approved geography and data-handling constraints.",
            "배포 유형과 현재 서비스 조건을 승인된 지역 및 데이터 처리 제약에 명시적으로 대응시킵니다.",
        ),
        (
            "Review current deployment-type and data-handling documentation with policy owners, select a compatible data-zone deployment and document allowed routing alternatives.",
            "정책 책임자와 현재 배포 유형 및 데이터 처리 문서를 검토하고 호환되는 데이터 영역 배포를 선택합니다. 허용되는 대체 라우팅도 문서화합니다.",
        ),
        (
            "Inspect the effective deployment type, selected zone, model version and quota, then verify policy review evidence and every configured alternate route.",
            "실제 배포 유형, 선택 영역, 모델 버전과 할당량을 확인한 뒤 정책 검토 근거와 설정된 모든 대체 경로를 검증합니다.",
        ),
        (
            "Global, Data Zone and Regional are distinct. Neither a static diagram nor an account region establishes a legal residency guarantee or authorizes a cross-zone fallback.",
            "Global, Data Zone과 Regional은 서로 다릅니다. 정적 그림이나 계정 지역으로 법적 상주성을 보장하거나 데이터 영역 밖 대체 처리를 승인할 수는 없습니다.",
        ),
    ),
}
