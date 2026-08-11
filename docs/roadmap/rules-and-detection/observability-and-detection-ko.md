---
title: 관측성과 감지(Observability and Detection)
translation_of: observability-and-detection.md
translation_source_sha: e7fac3be6f1d7bb8a8ff119e4dbeb7b0751fcade
translation_revised: 2026-08-11
---

# 관측성과 감지(Observability and Detection)

FDAI가 원시 원격측정을 컨트롤 루프가 액션할 수 있는 **발견 사항** 으로 어떻게 바꾸는가:
**이벤트 상관관계**, **이상 감지**, **예측 / 예보**, **근본원인 분석(RCA)**. 이들은 AIOps
플랫폼이 제공하리라 기대되는 감지 신호이며 - **결정론 우선을 깨지 않고** 여기에 추가됩니다:
모든 신호는 기존 `trust-router → tiers → risk-gate → executor → audit` 경로를 통해 흐르는
정규화된 발견 사항을 발행하며, 사이드 채널이 아니고, 어떤 것도 리스크 게이트와 7개 안전조건
밖에서 auto-execute 하지 않습니다.

참조: 컨트롤 루프, 티어, quality 게이트는
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md);
측정과 가드 메트릭은 [goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md); 규칙/신호 소스는
[rule-catalog-collection-ko.md](rule-catalog-collection-ko.md); 모듈 배치와 DI 경계는
[project-structure-ko.md](../architecture/project-structure-ko.md); 프롬프트-인젝션 위협 모델은
[security-and-identity-ko.md](../architecture/security-and-identity-ko.md). 상관관계와 out-of-band 감지는
[phase-1-rule-catalog-t0-ko.md](../phases/phase-1-rule-catalog-t0-ko.md) 에 도입; FinOps 비용
이상과 DR RPO/RTO 예측은
[phase-3-integrated-loop-ko.md](../phases/phase-3-integrated-loop-ko.md) 에 도착. 고객-비종속;
모든 예시는 합성.

## 설계 관점 (deterministic-first, not ML-first)

- 감지는 **먼저 설명 가능하고 증거 기반**: 통계적 베이스라인, 임계, 상관관계 규칙이 대부분
 신호를 모델 호출 없이 해결. 모델(T1 유사도, T2 추론)은 fuzzy 상관관계와 신규 RCA에만 진입
 - 같은 5-10% 예산.
- 감지 신호는 액션이 아니라 **발견 사항**. 다른 이벤트처럼 라우팅되고 risk-gate 됨; 예측이나
 이상은 절대 자체로 auto-remediate 하지 않음 - 리스크 게이트와 HIL이 관장하는 shadow-mode
 발견 사항 또는 교정 PR을 발동.
- Routine monitoring은 인시던트가 아닙니다. Healthy 하트비트, 성공한 탐색,
 within-threshold 샘플은 관측 근거만 기록합니다. Detector가 범위가 제한된하고
 근거에 기반한된 발견 사항을 발행하고 `IncidentLifecycleWorkflow`가 allowed 에이전트 principal,
 상관관계 키, 사유, member-event 근거를 다시 확인한 뒤에만 인시던트가 열립니다.
- Repeated-event burst는 anomaly이며 자동 인시던트 권한이 아닙니다. Heimdall은 범위가 제한된
 anomaly를 항상 기록하지만 정규화된 Event가 `incident_correlation=correlate`를 선언하고,
 비어 있지 않은 상관관계 ID와 근거 키를 가지며, 설정된 최소 심각도를 만족할 때만
 인시던트 후보를 전달할 수 있습니다. 하나의 repeated-event burst에 속한 모든 Event는 동일한
 비어 있지 않은 상관관계 에피소드에 속해야 하며 독립 에피소드의 Event는 서로의 임계값을
 충족하거나 독립적인 누적을 방해하지 않습니다. Burst 심각도는 마지막에 도착한 Event 값이 아니라
 범위가 제한된 구간에 기록된
 값 중 가장 심각한 값입니다. 임계값을 충족한 모든 Event의 고정된 근거 키는 후보와
 결과 인시던트 구성원 집합에 포함됩니다. 인벤토리 및 발견 변경을 포함해
 `incident_correlation=none`인 Event는 인시던트를 열지 않습니다. 자동 생성 최소 기본값은
 `high`이며 분류되지 않은 burst는 `medium` anomaly로 남습니다. Anomaly publish 또는 수명 주기
 인계가 실패하면 Heimdall은 범위가 제한된 에피소드 구간을 유지하고 다음 matching Event가 도착할 때만
 재시도하며 unbounded background 재시도 루프를 만들지 않습니다. 인계는 `accepted` 또는 `held`를
 반환하며 Heimdall은 정책 보류를 성공한 인시던트 후보로 계산하지 않습니다.
 열림 인시던트에 더 심각한 recurrence가 들어오면 추가 전용 `incident.severity` 행으로 심각도를
 상향합니다. Recurrence는 심각도를 낮추지 않고 재생도 동일한 단조 증가 결과를 복원하며 커밋된
 에스컬레이션은 deduplicated A2 수명 주기 notice를 발행합니다.
 Direct 후보 텍스트와 근거 키는 512자로 제한되고 후보 하나는 근거 키를 최대 100개
 포함하며 oversized 입력은 수명 주기 또는 감사 쓰기 전에 보류됩니다.
- Heimdall은 retained repeated-event 에피소드를 global 및 리소스별로 제한합니다. 한 리소스의
 상관관계 flood는 다른 리소스의 partially accumulated 근거보다 해당 리소스의 가장 오래된
 에피소드를 먼저 축출합니다.
- 새 감지기는 **shadow 모드** 로 출시되고 shadow→강제 적용 규칙에 따라 승격; 정확도와
 false-positive 비율은 단계 0 베이스라인 대비 측정됨.

### 동결된 구성 기준선 점검

구성 드리프트는 T0(결정론적 규칙) 점검 결과입니다. 검토된 실제 스냅샷을 의도된 상태로
동결하며 이후 관측값으로 자동 교체하지 않습니다. 사람이 검토하는 DOCX와 정규 JSON 기준선은
동일한 버전, 범위, 생성 시각, 문서 다이제스트를 가집니다.
세대와 검증은 정본 JSON의 표시 가능한 모든 리소스, 속성, 근거 공백,
토폴로지 링크, exception, 알 수 없음 항목이 paired DOCX에 있는지도 확인합니다. 파일 다이제스트 일치만으로는
cross-format 동등성이 성립하지 않습니다.

- `core/detection/configuration_drift.py`는 리소스, 토폴로지 링크, 비교 가능한 속성을 정규화하고
 `added`, `removed`, `changed`, `unchanged`, `unknown`, `unauthorized`를 보고합니다.
- 부분 스냅샷은 제거를 증명할 수 없습니다. 누락된 리소스, 링크, 속성은 신뢰할 수 있는 소스가
 완전한 증거를 제공할 때까지 차단 상태로 유지합니다.
- 설정된 기준선 버전, SHA-256 다이제스트, 범위는 서버가 소유합니다. 호출자는 도구 인자로 다른
 대상을 선택할 수 없습니다.
- 변경 불가능한 기준선 레지스트리는 여러 범위의 후보, 활성, 대체된, archived 버전을
 보관할 수 있으며 범위마다 활성 버전을 하나만 허용합니다. 활성 출처와 replay-pinned 출처는
 대화 입력이 아니라 서버 조립이 선택하고 레지스트리는 변경 API를 노출하지 않습니다.
- `delivery/azure/configuration_drift.py`는 Azure Resource Graph 조회 안에서 리소스 그룹 필터를
 적용합니다. 증거를 생성하기 전에 전체 프로바이더 리소스 id를 제거하고 구성된 범위에서 neutral
 리소스 키로 향하는 결정론적 resource-group `contains` 링크를 생성합니다.
- Knowledge 수집은 검토된 문서를 설명하고 인용합니다. 드리프트를 판정하지는 않습니다.
 Knowledge를 사용할 수 없어도 결정론적 보고서는 유지하고 인용 상태는 근거 있음으로
 표시하지 않고 차단 상태로 유지합니다. 각 인용 신원에는 정확한 기준선 버전과 전체
 DOCX SHA-256 다이제스트가 포함되므로 재사용된 파일 이름이 다른 문서를 가리킬 수 없습니다. Exact
 메타데이터 조회를 우선하고 범위가 제한된 결정론적 lexical 대체 경로는 고정된 문서 내부의 조각만
 순위화하며 관련 없는 조회에는 결과를 반환하지 않습니다. 프로바이더 exception은 exception 타입과
 pinned 기준선 신원이 포함된 구조화된 경고를 발행하지만 exception 메시지 또는 조각 내용은
 기록하지 않습니다.
- 읽기 전용 기능은 변경, 승인, 완화, unsupported-claim 개수를 보고합니다.
 구성 점검에서는 모두 0으로 유지합니다.
- 공개 `bind_configuration_drift` 조립 보조 로직은 변경할 수 없는 기능 런타임을 통해 이
 server-pinned A0 기능 하나만 설치합니다. ActionType, 실행기 신원, 예약 권한,
 caller-selected 범위를 추가하지 않습니다.
- 각 fresh 실행은 기준선 부하, 관측, 비교, Knowledge, 합계 지연 시간과 리소스 및
 발견 사항 개수를 기록합니다. 캐시된 스냅샷은 current-state 질문을 충족할 수 없으므로 현재 관측값을
 TTL 캐시로 재사용하지 않습니다. 증적은 floating-point timer 허용 오차를 넘어 단계 지연 시간 합이
 합계 경과 시간보다 큰 경우를 거부합니다.
- Pure 검토 집약기는 고정된 기준선 하나에 대한 멱등적 실행 증적 세 개를 수락합니다. 검증된
 실행 세 개만 inert weekly 예약 제안을 만들 수 있습니다. 차단된 또는 unsafe 실행이 있으면
 캠페인을 pause하고 집약기는 스케줄러 작업을 직접 생성하지 않습니다. Revisioned StateStore 어댑터는
 atomic state-and-audit 생성과 compare-and-set advance로 캠페인 진행 상황을 저장합니다.
- 캠페인 advance 전에 변경할 수 없는 StateStore 보고 원장이 캠페인과 실행 신원 아래에 전체 발견 사항,
 인용, 안전성 counter, measured performance를 기록합니다. Strict codec은 재시작 재생을 지원하고,
 중복 내용은 no-op이며, 다른 근거로 신원을 재사용하면 차단합니다.
- 준비된 캠페인은 inert 자동화 청사진을 제출합니다. shadow weekly 이벤트가 생기기 전에 독립적인
 검토와 인증된 스케줄러 명령이 계속 필요합니다. 구성 표류는 스케줄러 저장소 또는
 실행기를 직접 호출하지 않습니다.

## 1. 이벤트 상관관계(Event 상관관계)

`event-ingest` 의 한 스테이지, normalize + deduplicate 직후
([project-structure-ko.md](../architecture/project-structure-ko.md) 와
[phase-1-rule-catalog-t0-ko.md](../phases/phase-1-rule-catalog-t0-ko.md) 참조): 관련된 원시
이벤트를 하나의 **인시던트** 로 묶어 하류 티어가 폭풍이 아니라 한 가지만 추론하게 함.

- **Deterministic-first**: 범위가 제한된 **시간 구간** 내에서 공유 키(리소스 id, 배포 id,
 추적/상관관계 id, 원인 부모)로 상관 지음(규칙 사용); 퍼지 그룹화에 한해서만 **T1 임베딩
 유사도** 로 대체 경로.
- **그룹화이지 인과 아님**: 상관관계는 이벤트가 *함께 속한다* 만 단언; 공유 윈도우는 우연일 수
 있음. *원인* 배정은 RCA의 일(4절)이며 상관관계가 아님.
- **윈도우와 늦은 도착**: 상관관계 윈도우는 신호 클래스별로 설정; 열린 인시던트의 키와 매칭되는
 late/out-of-order 이벤트는 여기에 부착(또는 윈도우 이후면 linked follow-on 인시던트 오픈) -
 이벤트는 절대 조용히 드롭되지 않고,
 [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 의
 per-resource 순서 보장이 보존됨.
- **멱등 그룹화**: 인시던트 id는 상관관계 키에서 결정론적으로 파생되므로 같은 멤버 재처리는
 도착 순서와 무관하게 같은 인시던트를 산출.
- **노이즈 감소**: 한 루트 이벤트로부터의 알림 버스트는 하나의 인시던트로 접힘. 이것은 **측정된**
 노이즈-감소 비율(인시던트 ÷ 원시 알림)로 보고, 주장된 이득이 아님, 데이터 손실 없음 -
 멤버는 감사에 링크되어 남음.
- **출력**: 멤버 이벤트 id와 안정 멱등성 키를 운반하는 하나의 상관된 인시던트 이벤트;
 순서/멱등 키 보존.
- **수명 주기 경계**: 상관관계 id는 조사 키이며 인시던트가 존재한다는 증거가
 아닙니다. 수명 주기 기록은 `IncidentRegistry`가 소유합니다. Audit-only 로컬 고정본은
 감사와 추적에서 계속 볼 수 있지만 operational 인시던트 명단에서는 제외됩니다.
- **운영 작업 정책**: 정규화된 Event는 `incident_correlation`을 선언합니다. 기본
 `correlate`는 인시던트 그룹화를 유지합니다. 발견, 인벤토리, 스케줄러,
 workflow-control 생산자는 `none`을 설정하고 추적/감사용 `correlation_id`는 유지하며
 인시던트 ID는 파생하지 않습니다.
- **업스트림 구현**: `core/event_ingest/correlator.py`
 (`EventCorrelator`) 가 이벤트의 correlation-id (또는 리소스 참조) 와
 time-window 버킷 으로부터 `incident_id_for` 를 통해 인시던트 기준점 를
 결정론적으로 도출한다; 한 구간 에서 키 를 공유하는 버스트는 하나의
 인시던트로 접히고, 새 구간 는 linked follow-on 을 연다. 기준점 없는
 이벤트 또는 `incident_correlation=none` 이벤트는 `correlated=False` 로 보고됩니다
 (드롭 없음). 키 들은
 `IncidentRegistry.open` 에 공급되어 멤버십을 멱등적 하게 누적한다.

## 2. 이상 감지(Anomaly Detection)

기존 FinOps 비용-이상 훅
([phase-3-integrated-loop-ko.md](../phases/phase-3-integrated-loop-ko.md))을 **어떤 메트릭 스트림**
(성능, 신뢰성, 보안, 비용)에도 일반화.

- **방법**: 통계적 베이스라인(rolling 및/또는 seasonal, seasonality 윈도우는 구성)과 편차
 임계(예: z-score 또는 robust percentile 밴드), 신호 클래스별로 계산. 결정론적이며 설명 가능;
 베이스라인, 편차 크기, **방향**(over/under) 이 기록되어 사람이 왜 발동했는지 볼 수 있음.
- **콜드스타트**: 신뢰할 만하기에 충분한 베이스라인 히스토리가 없는 감지기는 얇은 베이스라인에
 발동하지 않고 **abstain**(shadow에 머물고 발견 사항 발행 없음); 콜드스타트 억제는 숨겨지지
 않고 메트릭으로 카운트.
- **카테고리**: 발견 사항은 룰 카탈로그와 공유되는 정본 `category` enum
 (`security | reliability | cost | config-drift`) 으로 정규화 - 성능 신호
 (지연 시간/error-rate/포화) 와 replication lag는 `reliability`, 비정상 접근 패턴은
 `security`, 지출 run-rate는 `cost` 로 매핑. 심각도는 편차 크기에서 파생.
- **변경 인지 억제**: in-flight 변경/유지 윈도우와 동시적인 이상은 발생 변경 이벤트와 상관
 지어져 억제되거나 주석 처리 - 배포가 false 긍정을 제조하지 않게 함.
- **False-positive와 false-negative 컨트롤**: debounce/settling 윈도우 + 새 감지기가 회귀시키면
 안 되는 측정된 false-positive 비율 *과* false-negative(놓친 이상) 비율 - 둘 다
 [goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md) 의 가드 메트릭에 매핑.
- **출력**: `event-ingest` 로 재진입(멱등성 키와 dedup을 위해)하는 이상 발견 사항, 이후
 다른 이벤트처럼 신뢰 라우터로.
- **업스트림 구현**: `core/detection/anomaly.py`
 (`MetricAnomalyDetector`) 가 위에 기술한 결정론적 z-score 기준선 을
 ship 한다 - cold-start abstain, flat-baseline 안전 처리, deviation
 크기 기반 심각도 - 그리고 각 발견 사항 을 `to_event` 로 shadow 모드의
 `Event(event_type="anomaly.finding")` 로 정규화하며, `detector + 메트릭
 + 구간` 로 keying 해 반복 틱 을 dedup 한다.
- **계절성(Seasonality)**: `core/detection/seasonal.py`
 (`SeasonalAnomalyDetector`) 는 주기적 형태를 가진 메트릭 을 처리해,
 정상적인 단계 별 peak(월요일 아침 트래픽 스파이크, 야간 배치 작업)이
 24x7 통합 평균 대비 발화하지 않도록 한다. 이력 를 설정된 **단계**
 (`hour_of_day`, `day_of_week`, `hour_of_week`, 또는 커스텀 함수)로
 버킷팅하고, 관측 샘플을 *같은* 단계 의 과거 샘플하고만 비교한다. base
 detector 를 감싸는 얇은 래퍼 로 - 이력 를 단계 로 필터링하고
 z-score, cold-start-abstain, flat-baseline, 이벤트 정규화 로직을 위임한다
 - 두 detector 가 어긋날 수 없다. 단계 별 cold-start 는 독립적이고(얇은
 일요일 기준선 이 월요일 데이터를 빌리지 않는다), 단계 는 발견 사항 의
 `window_bucket` 에 기록되며, 발견 사항 은 여전히 shadow 모드 이벤트다.
- **다변량 fusion**: `core/detection/composite.py`
 (`CompositeAnomalyDetector`) 은 조직의 on-call 이 손으로 읽는
 compound-degradation 신호다 - 진짜 인시던트는 *상관된* 스트림이 함께
 발화하는 것(지연 시간 up **그리고** error-rate up **그리고** 포화
 high)이지 하나의 noisy 메트릭 이 아니다. 이것은 **fuser 이지 새 기준선 이
 아니다**: 한 리소스 + 구간 에 대해 이미 생산된 per-metric
 `AnomalyFinding` 객체를 소비하고, 설정된 **정족수** 개가 발화할 때만
 `CompositeAnomalyFinding` (`event_type="anomaly.composite"`)을 raise 한다.
 정족수 미만이면 abstain(단일 noisy 스트림은 compound anomaly 가 아니다 -
 false-positive 억제); 정족수 이상이면 *amplify* 한다(심각도 가 동시 구성원
 의 breadth 와 그 root-sum-square 합성 magnitude 둘 다로 escalate 하므로,
 compound 성능 저하 이 어떤 단일 구성원 보다 상위). 중복 메트릭 은 가장
 강한 occurrence 로 collapse 되어 re-emit 된 스트림이 정족수 을 부풀릴 수
 없고, flat-baseline 구성원 는 고정 가중치 를 기여하며, fusion 은 구성원
 순서와 무관하게 결정론적이다. composite 는 여전히 risk 게이트 가 관장하는
 shadow-mode 발견 사항 이다 - 더 강하게 감지할 뿐, 행동하지 않는다.

### 운영 인사이트 recipe 카탈로그

`core/detection/insights.py`는 통계 모델이 필요하지 않은 운영 조건을 위한
결정론적 recipe 평가기를 추가합니다. 호출자는 정규화된 현재값, 이전값,
기준선 값과 샘플 개수, last-seen 시각을 제공합니다. 평가기는 열 가지
명시적 운영자(`above`, `below`, delta, 비율 변경, ratio, `absent`,
`stale`) 중 하나를 적용하고 관측값, 참조, 점수, 임계값, 설명을
`operational-insight.finding` 이벤트에 기록합니다. 불완전하거나 유한하지 않은
입력, 샘플 부족, 0으로 나누는 입력은 발견 사항을 만들지 않고 검토를 위해
보류합니다.

버전 관리되는 `rule-catalog/operational-insights/catalog.yaml` 카탈로그는 다음
50개 초기 recipe를 제공합니다.

- **인프라와 원격측정(9)**: CPU, 메모리, 디스크, 재시작, 프로세스,
 peer-hotspot, 최신성, 인제스트 양, cardinality 조건을 평가합니다.
- **변경과 애플리케이션 성능(9)**: 배포 지연 시간, 오류, 처리량, 요청
 오류, tail 지연 시간, 애플리케이션 성능 점수, 의존성 amplification, 추적
 critical 경로, 구간 오류를 평가합니다.
- **데이터와 능동 검사(9)**: slow 조회, 잠금 wait, 소비자 lag, dead-letter
 증가, synthetic 가용성과 지연 시간, 로그 양, 새 로그 pattern, rare
 오류를 평가합니다.
- **SLO, alert 품질, 소유권(8)**: fast/slow burn, 오류 예산, alert storm,
 flapping, stale evaluation, no-data, 누락된 소유권을 평가합니다.
- **비용 거버넌스(6)**: 일일 지출 변화, 예산 초과, 미할당/유휴 지출, 단위
 비용, 컨테이너 요청 낭비를 평가합니다.
- **보안, 영향, 복구 위생(9)**: critical misconfiguration, excess 권한,
 sensitive-data 증가, 런타임 threat, reachable vulnerability, 영향받은 세션,
 certificate 만료, 백업 최신성, 네트워크 retransmission을 평가합니다.

임계값과 메트릭 연결은 카탈로그 데이터로 유지되므로 환경별 조정에서
평가기 코드를 바꿀 필요가 없습니다. 모든 recipe는 기본적으로 shadow 모드를
사용하고 엔진, recipe, 리소스, 구간에서 안정 키를 만들며, trust 라우팅
전에 dedup할 수 있도록 `event-ingest`로 재진입합니다.

`core/detection/insight_source.py`의 `OperationalInsightSource`는 공유
`MetricProvider` 경계로 연결되는 런타임 브리지입니다. 리소스와 구간마다
고유 메트릭을 한 번씩 조회하고 현재값, 이전값, 과거 기준선 값을 만든 뒤 하나의
정규화된 관측으로 카탈로그를 평가합니다. 성공한 빈 조회는 `absent`의
증거가 될 수 있지만 프로바이더 오류는 메트릭을 사용 불가로 표시하고 의존하는
모든 recipe를 억제합니다. 따라서 원격측정 장애를 워크로드 장애로 오인하지
않습니다. Stale recipe는 stale 임계값의 두 배까지 범위가 제한된 조회 구간을
확장합니다. 이 범위에도 last-seen 샘플이 없으면 값을 추론하지 않고 보류합니다.

## 3. 예측 / 예보(Predictive / Forecasting)

Proactive 감지: 발생 **전에** 임계 위반을 예측 - AIOps "용량 병목과 서비스 장애 예측" 사례 -
결정론 우선으로 유지.

- **방법**: 설정된 **예보 지평** 까지 측정된 시리즈에 대한 트렌드 외삽(linear/seasonal fit),
 예상 값이 설정된 임계를 넘을 때 발견 사항 발동. 모든 예보는 그 지평과 **신뢰 구간** 을 운반;
 명시된 불확실성 있는 변환 결과 - **결정론적 진실도 아니고 LLM 신탁도 아님** - 그리고 실행
 자격을 절대 부여하지 않음.
- **대상**: 용량/쿼터 고갈, RPO 위반 방향의 replication-lag 드리프트, 예산 대비 비용 run-rate,
 인증서/시크릿 만료, 백업-보존 드리프트. RPO/RTO와 FinOps 대상은
 [phase-3-integrated-loop-ko.md](../phases/phase-3-integrated-loop-ko.md) 가 소유.
- **승격 전 backtest**: 예보기는 과거 시리즈에 대해 **backtest**(알려진 과거 위반 예측)하고
 shadow에서 정확도 바를 통과해야 shadow 모드를 떠날 수 있음.
- **드리프트**: 예보 오차는 시간에 걸쳐 추적; 측정된 저하(드리프트)는 자동으로 예보기를 shadow로
 **강등**.
- **안전**: 예측은 **발견 사항 발동**(기본 shadow 모드) 또는 proactive 교정 PR; 자체로
 auto-execute 하지 않음. 예보에 액션하는 것은 여전히 리스크 게이트를 통과하고 7개 안전조건을
 운반.
- **측정**: **lead 시간** = `actual_breach_time − finding_time` 정의(유효한 예측은
 actionable 최소 위의 긍정 lead 시간을 가짐), **정밀도/재현율** 스코어 (true
 긍정 = 예측된 위반의 실제 위반이 지평 내에 발생). 놓친 위반은 false 부정(가드 메트릭);
 나쁜 예보기는 shadow에 머무름.
- **업스트림 구현**: `core/detection/forecast.py`
 (`LinearForecastDetector`) 가 최소제곱 선형 예보기를 ship 한다 -
 cold-start 와 weak-fit(낮은 R-squared) 입력은 abstain, direction-gated
 rising/falling 위반 변환 결과, 그리고 지평으로 한계 된 긍정 lead
 시간(위반 ETA). 각 예보는 `to_event` 로 shadow 모드의
 `Event(event_type="forecast.finding")` 로 정규화되며, `detector + 메트릭
 + 구간` 로 keying 해 반복 틱 을 dedup 한다; 심각도 는 임박도
 (lead / horizon)로 스케일. anomaly 감지기와 `MetricSample` series 타입을
 공유한다 (`core/detection/series.py`).
- **예측구간 band (false-positive suppression)**:
 `core/detection/forecast_band.py` (`prediction_band`) 가 지점 예측
 에 없는 uncertainty band 를 추가한다. noisy series 는 center 줄 에서
 임계값 를 crossing 하면서도 normal variation 안에 머물 수 있다; band 는
 fitted `residual_std` **와** 변환 결과 이 미래로 얼마나 멀리 도달하는지에
 따라 넓어지며, breach 는 간격 의 pessimistic 간선(rising breach 는 lower
 간선, falling 은 upper 간선)가 구성된 확신도 수준 (`0.80`-`0.99`)
 에서 여전히 crossing 할 때만 **confident** 하다. 이것은 **suppressor 이지
 amplifier 가 아니다**: point-estimate breach 를 "not confident" 로 downgrade
 (shadow 유지 / abstain, false-positive 가드 메트릭 보호)할 수 있지만, 지점
 예측 가 예측하지 않은 breach 를 절대 manufacture 하지 않는다. perfect fit
 (`residual_std == 0`)은 band 를 지점 추정치 로 collapse 하고, 알 수 없음
 확신도 수준 은 silently 기본값 되지 않고 거부 된다.

### 예측 검증 및 결과 확정

예측 지평이 끝난 뒤 관측된 결과와 대조하기 전에는 예보를 예측 품질의 증거로 볼 수 없습니다.
FDAI는 예측 충실도와 대응 효과를 분리하여, 선제 액션이 위반을 막았을 때 유용한 예측을 false
긍정으로 잘못 평가하지 않습니다.

**변경 불가능한 예측 묶음.** 예보 발견 사항을 게시하기 전에 안정적인 `prediction_id`,
detector 및 설정 버전, 대상 리소스와 메트릭, breach 조건식, event-time feature 기준 시점,
horizon, 예상 breach 시간, 지점 추정치, uncertainty 간격, 모드를 기록합니다. 묶음은
추가 전용입니다. 이후 detector 버전은 기존 예측을 덮어쓰지 않고 새 prediction을 만듭니다.

**결과 확정.** Scorer는 `horizon_end + telemetry_grace`가 지난 후에만 prediction을
확정합니다. Grace 기간은 측정된 인제스트 delay 분포를 기준으로 설정합니다. 라벨은 처리
시간이 아니라 이벤트 시간을 사용하고 다음 규칙을 따릅니다.

| 관측된 에피소드 | Prediction 라벨 | 처리 |
|----------------|------------------|------|
| 선언된 breach가 horizon 안에 발생하고 preventive 액션이 대상을 바꾸지 않음 | true 긍정 | 발견 사항부터 breach까지 lead 시간을 측정합니다. |
| Horizon 안에 선언된 breach가 없고 텔레메트리가 완전하며 preventive 액션이 실행되지 않음 | false 긍정 | 해당 정확한 horizon의 정밀도에 반영합니다. |
| 적격한 선행 prediction 없이 선언된 breach가 발생함 | false 부정 | 발행된 예측만이 아니라 실제 breach 에피소드에서 denominator를 만듭니다. |
| Prediction 후 preventive 액션이 실행되고 breach가 발생하지 않음 | intervention-censored | 예측 정밀도에서 제외하고 응답 원장에서 액션을 평가합니다. |
| 텔레메트리가 누락되거나 stale이고, 리소스가 삭제되거나 제외된 maintenance 구간이 겹침 | unscorable | 별도로 집계하고 보고하며 true 부정으로 바꾸지 않습니다. |

선언한 horizon 뒤의 breach는 해당 horizon의 true 긍정이 아닙니다. 대신 horizon 선택의
증거로 사용하며 별도의 더 긴 horizon prediction과 매칭할 수 있습니다. 중복 관측은 안정적인
prediction 및 인시던트 키로 결합하므로 at-least-once 전달에서도 두 번 채점되지 않습니다.

**두 개의 원장.** Prediction-fidelity 원장은 예측과 결과의 결합을 저장합니다.
응답 원장은 intervention, precondition, 예상 효과, 관찰된 효과, 검증,
롤백, SLO 복구, recurrence 구간을 저장합니다. Intervention이 발생한 에피소드는 untreated
예측 라벨로 사용하지 않습니다. 안전에 중요한 액션에서는 컨트롤 그룹을 만들기 위해 입증된
대응을 보류하지 않습니다. Counterfactual 근거에는 shadow-only prediction, 자연적으로 untreated인
에피소드, 매칭된 historical 집단 또는 검토된 단계적 롤아웃을 사용합니다.

응답 원장의 첫 런타임 구획은 구현되어 있습니다. 컨트롤 루프는 독립적인 효과
관측 후 strict `ResponseOutcome` 계약을 발행하며 예상 범위, 관찰된 값, 시간 구간,
검증, 실행 모드, 롤백 결과, 대상 다이제스트 및 명시적 `scorable` 표시를 포함합니다.
기존 scheduled growth 작업은 독립 watermark로 이 기록을 소비하고 등록된 shadow challenger
모델만 갱신합니다. SLO 복구, recurrence 종결, matched 집단 및 `quasi_experimental` 또는
`interventional` 근거로의 승격은 후속 작업이며 검증된 효과 하나에서 추론하지 않습니다.

**Leakage 없는 평가.** Backtest는 rolling-origin 시간 분리를 사용하고 한 인시던트의 모든 이벤트를
하나의 분리에 넣습니다. Feature, 토폴로지, maintenance 상태, 라벨은 prediction 기준 시점 시점에 알 수
있었던 값만 읽습니다. Incumbent와 후보는 같은 고정된 재생과 같은 실제 운영 shadow 이벤트를
처리하며 후보는 실행할 수 없습니다. 대상과 horizon별로 샘플 크기와 확신도 간격을
포함해 정밀도, 재현율, resource-day당 false alert, PR-AUC, Brier 점수 또는 calibration 오류,
간격 커버리지, actionable lead-time 분포, abstention, cold-start, unscorable 비율을 보고합니다.
집계 accuracy만으로는 승격할 수 없습니다.

**에이전트 choreography.** Heimdall은 예측 발견 사항과 결정론적 결과 종결을 소유하고
Huginn은 정규화된 실제 관측을 제공합니다. Saga는 변경 불가능한 prediction 및 최종
근거를 기록하고 Norns는 종료된 case-history 집단을 off-path에서 분석해 비활성
detector/룰 후보를 제안하며 Mimir는 검토된 승격을 소유합니다.
Forseti는 발견 사항을 판단하고 Thor는 액션할 수 있지만 어느 쪽도 prediction 라벨을 수정할 수
없습니다. 이 에이전트들은 타입이 지정된 이벤트를 독립적으로 소비하고 병렬로 실행할 수 있으며 채점 경로에는
직접 에이전트 호출이 없습니다.

승격에는 사전 등록된 최소 closed/scorable 에피소드 수와 관측 일, 확신도 간격이
incumbent를 넘는 후보 개선, 가드 메트릭 무회귀, 정책 escape 0건이 필요합니다. Calibration,
재현율, 간격 커버리지 또는 actionable lead 시간이 저하되면 detector는 자동으로 shadow로
돌아갑니다. 영속 에피소드 원장, event-time 결과 결합, intervention censoring,
transactional 게시 발신함 및 기계적 틱 배선은 구현되어 있습니다. 승격은 계속
측정된 배포 근거와 권위 있는 승격 레지스트리에 의존합니다.

## 4. 근본원인 분석(Root-Cause Analysis)

RCA를 암묵적 부작용이 아니라 티어의 일급 출력으로 만듦.

| 티어 | RCA 역할 |
|------|---------|
| **T0** | 직접 원인: 매칭된 규칙/정책이 위반된 컨트롤과 교정을 명명 |
| **T1** | 상관관계 원인: (a) 인시던트를 이전 **해결된** 인시던트와 매칭하고 그 식별된 루트 원인 + 학습된 액션 재사용(출처 이력과 재검증), 또는 (b) 인시던트 자신의 상관 이벤트로부터 **결정론적 인과사슬**을 재구성 - 관련 리소스에서 범위가 제한된 구간 내 실패에 선행한 가장 가까운 변경 / 변경 을 식별("deploy 가 나갔고, 그 다음 오류 비율 가 올랐다" 사슬) |
| **T2** | 추론 원인: 신규/모호 인시던트에 대해 quality 게이트를 통과하는 **증거를 인용**(규칙, 상관 이벤트, 원격측정, 자유형식 오퍼레이터 문서) 하는 근거 있는 root-cause 가설 생산 |

- RCA 출력은 권위 있는 판정이 아니라 **인용 있는 가설**; **실행 자격은 여전히 결정론적 검증**
 (검증기 + 정책 재검사) 으로 부여, RCA 텍스트나 예보만으로 절대 아님.
- T2 RCA에 공급되는 원격측정과 상관 이벤트는 **신뢰할 수 없는 입력** 이며 프롬프트 인젝션을 운반할
 수 있음; [security-and-identity-ko.md](../architecture/security-and-identity-ko.md) 에 따라 검증기와
 정책 재검사가 어떤 모델 텍스트에 대해서도 권위.
- 이전 해결된 인시던트의 루트 원인을 T1이 재사용할 때는 이전 원인과 학습된 액션이 여전히
 **적용된다는 것을 재검증**(출처 이력과 함께) 해야 하며, 결과 액션은 리스크 게이트 전에
 what-if를 실행 - stale 학습된 액션은 절대 눈감고 재생되지 않음.
- 근거를 가질 수 없는 RCA는 **abstain** 하고 HIL로 라우팅.
- 상관된 인시던트(1절)가 RCA 입력이므로 RCA는 중복 폭풍이 아니라 하나의 인시던트를 추론.
- **업스트림 구현**: `core/rca/` 가 RCA 계약
 (`RootCauseHypothesis` + `Citation`), 결정론적 **T0** 원인
 (`t0_root_cause`, 매칭된 룰 에 확신도 1.0 으로 근거에 기반한 되고
 교정 포함), 그리고 **grounding 게이트** (`enforce_grounding`,
 ungrounded 이거나 확신도 미만인 가설 는 HIL 로 abstain) 를
 ship 한다. **T2** reasoner 는 `RcaReasoner` 프로토콜 경계 - 포크 가
 mixed-model, RAG-grounded 생산자 (via `core/quality_gate`) 를 그
 뒤에 plug 한다. 업스트림 은 `core/rca/llm.py` (`LlmRcaReasoner` + the
 `RcaModel` 경계) 를 ship 하며, 그 결정론적 파서 는 malformed 답변,
 fabricated 인용 (프롬프트 주입), ungrounded 답변을 거부한다 -
 모델은 제안하고, 파서 와 grounding 게이트 가 결정한다. Azure T2
 연결 은 `delivery/azure/llm/rca_model.py` (`AzureOpenAIRcaModel`)
 로, managed-identity 토큰 으로 Azure OpenAI 를 호출하고 업스트림
 파서 가 검증할 raw JSON 을 반환하는 `RcaModel` 어댑터다. 조립
 루트 가 이것을 `resolved-models.json` 의 `t2.rca` 기능 로
 바인드한다 (`bind_azure_llm_bindings`, 비평자 / Judge 바인딩과
 대칭) - 기능 나 프롬프트 가 없으면 `LlmBindings.rca_reasoner =
 None` 이라 T2 RCA 는 dark 상태로 남고 T0 RCA 만 동작한다.
 `__main__` 은 그 결과의 `RcaCoordinator` (그리고 `EventCorrelator`) 를
 `ControlLoop` 에 주입한다. 그 출력도
 grounding 게이트 와 risk-gate 검증기 를 통과하며, 모델의 산문
 만으로는 절대 실행하지 않는다. `RcaCoordinator`
 가 세 계층 를 모두 orchestrate 한다 - T0, **T1** correlation-reuse
 (이전 resolved 인시던트 의 원인, 현재 근거 대비 stale 이면
 abstain), 그리고 T2 (공급된 근거 밖의 인용 은 fabricated 로
 거부). 이것이 `ControlLoop` 에 배선되어, 발견 사항 마다 결정론적 T0
 `rca.hypothesis` 감사 엔트리 하나를 덧붙이기 하며, 상관된 `incident_id`
 (`EventCorrelator`, 1절) 를 실어 한 인시던트의 발견 사항 들을 묶는다 -
 "왜"이지 새로운 실행 경로가 아니다. T2 reasoner 가 배선되면, novel (T0
 no-match) 사례 는 추가로 근거에 기반한 T2 `rca.hypothesis` (또는 abstain) 를
 받으며, reasoner-gated 라 LLM 없는 배포는 T2 노이즈를 발행 하지 않는다.
- **자유형식 knowledge leg**: `core/rca/knowledge_evidence.py`
 (`KnowledgeEvidenceGatherer`) 는 Knowledge Base 인제스트 경계
 (`shared/providers/knowledge.py` `KnowledgeSource` +
 `EmbeddingKnowledgeSource` / `PgvectorKnowledgeSource`) 의 RCA 소비자다.
 바인드되면 `RcaCoordinator` 의 T2 편의 래퍼가 오퍼레이터가 인제스트한
 문서(런북, 아키텍처 노트, **리소스 플랜**)에서 인시던트 요약과 관련된
 조각 를 검색해 각각을 `CitationKind.KNOWLEDGE` 후보로 추가한다 - 즉
 오퍼레이터가 업로드한 문서가 T2 가 가설을 세울 때 실제로 참조된다.
 Fail-safe (미바인드 소스, 빈 인덱스, 프로바이더 장애는 아무것도 기여하지
 않고 게이트 는 abstain) 이며 secret-safe (인용 참조 는 조각 본문이
 아니라 opaque `knowledge:<source_ref>#<chunk_id>` 핸들). reasoner 는
 여전히 이 보증된 집합 밖의 조각 를 인용할 수 없고, grounding 게이트 +
 검증기 가 권위를 유지한다.
- **T1 인과사슬 (결정론적)**: `core/rca/causal_chain.py`
 (`CausalChainAnalyzer`, `core/rca/t1.py` 의 `t1_causal_chain` 이 구동) 은
 T1 상관관계 (b) 의 model-free 형태다. 인시던트의 상관 이벤트(각각
 시각, 범용 `resource_ref`, `is_change` 마커, 선택적 `change_kind`
 를 carry)가 주어지면, 실패에서 끝나는 가장 probable 한 **multi-hop 인과사슬**
 - `root change -> symptom -> ... -> failure` - 을 재구성한다. 단순히 가장
 가까운 선행 하나가 아니다. **루트 는 반드시 변경** 여야 한다(변경 만
 원인이 될 수 있고 symptom 은 전파만 한다). 따라서 선행 변경 가 없는 순수
 symptom 만의 구간 는 **abstain**(`None` 반환, T2 로 defer)한다. 재구성은
 **dependency-aware**: resource-dependency 그래프가 공급되면, 실패가
 의존하는 리소스(직접, 또는 범위가 제한된 깊이 내 transitive)의 변경 가 무관한
 것보다 우선하고, 그래프가 주어지면 무관한 리소스는 아예 링크 될 수 없다.
 그래프가 없으면 엔진은 permissive 하게 유지(어떤 상관 리소스든 링크 가능 -
 cross-resource 기본값). `same_resource_only` 는 모든 홉 을 실패 리소스로
 국한한다. 확신도 는 사슬 홉 들의 weakest-link 집계(각 홉 은 temporal
 proximity, 관계 강도, change-kind 로 가중)이고, 서로 다른 여러 루트
 가 실패를 비슷하게 잘 설명할 때 **ambiguity-discount** 되며, T1 band
 (`0.35`-`0.85`)로 한계 된다 - temporal antecedent 는 강한 힌트 이지
 T0-style 확실성이 아니다. strict temporal 선행성이 이벤트 집합을 DAG 로
 만들어 사슬은 결정론적(동일 이벤트는 항상 동일 사슬)이고 사슬의 모든 이벤트를
 cite 한다; grounding 게이트 와 risk-gate 검증기 를 통과한 뒤에야 무언가 act
 한다. `RcaCoordinator.analyze_t1_causal_chain` 이 근거에 기반한 진입점이다. 라이브
 배선: `ControlLoop` 이 매 매칭된 인시던트의 멤버를 `IncidentMemberSource`
 시밍(`core/rca/member_source.py`; 포크 의 어댑터가 어떤 멤버가 변경 인지
 표시)을 통해 공급하고, 이벤트당 하나의 shadow `rca.hypothesis`(계층 t1)를
 덧붙이기 한다. 설정된 `causal_chain_window` 와 선택적 resource-dependency 그래프로
 한계 된다. 가설은 transport-safe `causal_chain`(루트/실패 ID, 모호성,
 순서가 있는 홉 근거)을 보존하며 컨트롤 루프는 이를 산문으로 축약하지 않고
 추가 전용 감사 항목에 기록한다. 업스트림 참조 구현 `DeploymentHistoryMemberSource`
 (`core/rca/deployment_member_source.py`)는 실제 `DeploymentHistoryProvider`
 (예: Azure Resource Graph 어댑터)와 인시던트 레코드 조회를 선행 `is_change=True`
 이벤트로 브리지 하므로, 포크 는 소스를 직접 작성하지 않고도 change-history 기반
 라이브 사슬을 얻는다. 소스가 없으면 T1 인과사슬 RCA 는 dark 로 유지되고 T0(및
 wired 시 T2) RCA 만 실행된다(하위호환).
- **읽기 전용 콘솔 표면**: shadow `rca.hypothesis` 감사 항목은 일급
 **이력 > RCA** 오퍼레이터 콘솔 패널로 투영된다(`GET /rca?correlation=<id>`,
 순수 투영은 `delivery/operator_api/routes/rca_projection.py`). 인시던트
 `correlation_id`가 주어지면 티어별 가설, 인용, 근거 상태(기권 가설은 신뢰할 수
 있는 원인이 아니라 "근거 부족 -> HIL"로 표시), 기록된 경우 구조화된 T1 인과 체인,
 그리고 동일한 상관관계 감사
 스트림에서 조합한 연결 대응 계획(판정 / 작업 / 모드 / 롤백)을 렌더링한다.
 이 표면은 엄격히 읽기 전용이며 새로운 진실 원천을 추가하지 않는다 - 참조:
 [operator-console.md](../interfaces/operator-console-incident-roster.md#1351-rca-view-root-cause-analysis).

## 컨트롤 루프에 플러그

상관관계는 `event-ingest` 안에서 실행. 이상과 예보 감지기는 **out-of-band 생산자**
([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md) 및 phase-1
out-of-band 감지 참조) 로 발견 사항을 버스에 publish; 그 발견 사항은 멱등성 키와 dedup을
얻기 위해 **`event-ingest` 로 재진입** , 그래서 flapping 감지기가 중복 작업을 주입할 수 없음.
어떤 감지기도 새로운 자율성 표면이 아님:

```text
telemetry / metrics
 -> anomaly / forecast detectors emit findings ---.    # sections 2-3
 raw events -------------------------------------- +-> event-ingest
              (normalize + dedup + correlate) # section 1
 -> trust-router -> T0 | T1 | (T2 -> quality-gate)          # RCA per tier, section 4
 -> risk-gate -> auto -> executor -> delivery (PR) | HIL | abstain/deny -> audit
```

- **발견 사항** 은 `shared/contracts` 의 일급, 버전된 이벤트 타입이며 안정 멱등성
 키(예: `detector-id + metric + window-bucket`, 또는 인시던트 id) 를 가짐 - 반복 평가 틱이
 쌓이지 않고 dedup.
- 감지기는 설정 주도(베이스라인, 임계, 지평, 상관관계 키, 모델 바인딩이 구성, 하드코딩 아님),
 shadow-before-enforce 준수, 모든 발견 사항과 결정이 감사됨.

## AIOps 정합

일반 AIOps 모델에서 채택한 것과 의도적으로 다른 곳:

| AIOps 능력 | 우리의 자세 |
|------------|-------------|
| 인시던트 감지 & 알림 | 채택 - 상관관계 + 이상이 발견 사항 발행 |
| Root-cause analysis | 채택 - 티어별 일급 RCA (4절) |
| 이상 감지 | 채택 - 통계적, 설명 가능 (2절) |
| 예측 분석 | 채택 - 트렌드 + 임계 예보, 불확실성 있음 (3절) |
| 알림 노이즈 감소 / false 긍정 감소 | 채택 - 상관관계 + 측정된 FP 비율 |
| 수동 작업 감소 / 빠른 해결 | 채택 - 리스크 게이트된 auto-remediation |
| 감사 트레일 / 컴플라이언스 | 채택 - 추가 전용 감사가 이미 코어 |
| **주 엔진으로서의 ML/NLP** | **다름** - 결정론 우선; 모델은 5-10% 잔여 |
| **불투명 / black-box 이상 스코어링** | **다름** - 설명 가능 우선; 발견 사항이 베이스라인, 편차, 방향 기록 |
| **모델이 추천 *하고* 실행** | **다름** - 실행 자격은 모델이 아니라 결정론적 검증에서 |
| **벤더-플랫폼 락인** | **다름** - CSP-중립; 관측성 플랫폼은 원격측정 *소스* 이지 두뇌 아님 |

## 설정과 안전

- 베이스라인, 편차 임계, 예보 지평, 상관관계 키, 모델 바인딩은 **설정**; 포크는
 [project-structure-ko.md](../architecture/project-structure-ko.md) 의 DI 경계로 오버라이드, 절대 코어를
 편집하지 않음.
- 감지기는 시작 시 설정을 검증하고 **실패 시 차단** - 깨진 감지기, 부족한/콜드스타트 베이스라인,
 stale 원격측정은 false 발견 사항 발행 이나 auto-act가 아니라 감지기 **abstain** 하게 함.
- Repeated-event 인시던트 정책은 startup-bound 런타임 Settings입니다.
 `incident.auto_open.enabled`(기본 `true`), `incident.auto_open.min_severity`(기본 `high`),
 `incident.repeat_threshold`(기본 `5`, 범위 `2-100`),
 `incident.repeat_window_seconds`(기본 `300`, 범위 `10-86400`)를 사용합니다. 잘못된 값은
 시작을 실패시킵니다. 심각도는 `critical/high/medium/low/info`에서 `SEV1-SEV5`로
 결정론적으로 매핑하며 조립은 모든 후보를 고정 심각도로 바꾸지 않습니다.
- 감지 발견 사항은 **신뢰할 수 없는 입력**; 어떤 LLM 사용(퍼지 상관관계, T2 RCA)도 quality 게이트
 ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md))
 와 [security-and-identity-ko.md](../architecture/security-and-identity-ko.md) 의 프롬프트-인젝션 위협 모델을
 통과.
- 감지기 메트릭 발행 - fire 비율, false-positive 비율, false-negative/놓친-위반 비율, abstain
 및 콜드스타트 억제 카운트, 예보 lead 시간, RCA groundedness - 를 KPI 대시보드로.

### 런타임 전달 상태

Container Apps analyzer 및 스케줄러 작업 은 정본 멱등적 Event 를 구성된 Event
Hubs ingest 토픽 에 publish 합니다. 변경을 직접 실행하지 않으며 발견 사항 과 due 작업 는
shared trust-router 및 risk-gate 로 다시 진입합니다. Publish 실패 시 scheduled 항목 은
재시도 가능한 상태를 유지하고 작업 은 non-zero 결과를 반환합니다.

Azure 리소스 생성, 갱신, 삭제 신호는 정본 Event Hubs 유입을 통해 계속
흐릅니다. Huginn은 이 실시간 발견 유입을 소유하고 정규화된 Event에 리소스 신원,
변경 종류, 범위가 제한된 속성을 보존합니다. Dedicated projector는 파티션 순서에 따라 리소스,
링크, tombstone delta를 영속 인벤토리 오버레이에 적용합니다. 인벤토리 작업은 별도로 기본 6시간마다
완전한 ARG/ARM 조정 스냅샷을 promote하고 새 세대에 포함된 오버레이 항목을
정리합니다. Heimdall은 stale 스냅샷, 커서 lag, 대체 경로 spike, 커버리지 loss를 감지합니다.
최신성 조회가 없거나 degraded 또는 stale이면 graph-dependent 액션을 사람 검토로 보냅니다.
인벤토리 기반 준비 상태 탐색은 발견 성공을 단정하지 않고 해당 최신성 상태를
보존하며 Heimdall은 관찰기로 유지됩니다. 인벤토리 작업은 10분마다 영속 시도 상태를
확인하고 due일 때만 정상 6시간 검사를 실행하며, newer 실패한/abandoned 시도는 다음 틱에 재시도합니다.
Core 런타임에는 job-start 권한을 부여하지 않습니다.

## 열림 Decisions

- [ ] 신호 클래스별 이상 방법(z-score vs robust percentile vs seasonal decomposition).
- [ ] 대상별 예보 모델 패밀리와 기본 지평(용량, lag, 비용, 만료).
- [ ] 상관관계 키 세트와 시간-윈도우 기본; 퍼지 상관관계를 T1으로 escalate하는 때.
- [ ] 콜드스타트 정책: 감지기가 발동하기 전 신호 클래스별 최소 베이스라인 히스토리.
- [ ] Backtest 주기와 예보기가 shadow를 떠나기 위해 통과해야 할 정확도 바.
- [ ] 변경 윈도우 억제: 이상이 in-flight 변경 이벤트와 어떻게 상관되는가.
