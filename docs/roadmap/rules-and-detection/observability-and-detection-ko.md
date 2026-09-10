---
title: 관측성과 감지(Observability and Detection)
translation_of: observability-and-detection.md
translation_source_sha: 0ffd42f0362097cfa6988971d71c071b31929f8f
translation_revised: 2026-09-11
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
- 정본 객체 타입과 개별 탐지 기록의 이름은 `Finding`이고, 컬렉션, 페이지, 탐색 레이블의 이름은
  `Findings`입니다. Finding은 인시던트 상관관계와 생애주기 게이트가 승격하기 전까지 Incident와
  독립된 기록으로 유지됩니다. 에이전트 활동은 에이전트가 Finding을 생성하거나 갱신한 사실과
  시각 및 상관관계 근거를 보여 줄 수 있지만 Finding 상태, 중복 제거, 심각도 또는 Incident 승격을
  소유하지 않습니다. 여러 영역을 아우르는 `Findings` 변환 결과가 이런 운영자 작업을 소유합니다.
  이 변환 결과가 구현되기 전에는 활동 타임라인이 아니라 각 영역의 변환 결과와 감사 기록을
  정본으로 사용합니다.
- Routine 모니터링은 인시던트가 아닙니다. Healthy 하트비트, 성공한 탐색,
  within-threshold 샘플은 관측 근거만 기록합니다. Detector가 범위를 제한하고
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
- `delivery/configuration_drift.py`는 개발 및 근거 재현을 위한
  `JsonFileConfigurationObservationSource`를 유지합니다.
  `delivery/azure/configuration_drift.py`는 서버가 소유하는 범위 하나를 위한 읽기 전용 Azure
  Resource Graph 소스를 추가합니다. 배포 구성은 엄격한 식별자 문법을 통해 최대 64개의 스칼라
  속성 경로를 선택합니다. 어댑터는 쿼리를 구성하고 선택한 값만 반환하며, 누락된 값을 알 수 없음으로
  표시합니다. 비어 있지 않은 존재 여부 토큰을 사용하므로 생략된 false 값이 명시적으로 존재하는 빈
  스칼라로 오인되지 않습니다. 프로바이더 ID를 안정적인 다이제스트 접미사로 바꾸며, 부분적이거나 너무 크거나 형식이
  잘못되었거나 범위를 벗어난 결과를 차단합니다. 토폴로지를 추론하거나 임의의 프로바이더 속성 묶음을
  수집하지 않습니다. 런타임 부트스트랩은 `FDAI_CONFIGURATION_DRIFT_ENABLED`가 명시적이고
  모든 범위, 기준선, 구독 및 속성 전제 조건이 유효할 때만 소스를 연결합니다. 보호된 Core 서비스
  전환은 Virtual Network에 통합된 배포 러너에서 범위가 제한된 보호 secret envelope로 검토된
  스냅샷을 복원하고, 정확한 정규 다이제스트와 예상 리소스 수를 확인한 뒤, 변경 불가능한 콘텐츠
  주소 기반 private Blob으로만 저장합니다.
  저장소와 서비스 계획에는 바인딩 메타데이터만 포함됩니다. Core는 Managed Identity를 통해 provider가
  허용하는 다이제스트 메타데이터까지 검증하며 해당
  Blob을 읽습니다. 적용 후 검증은 배포된 바인딩과 Blob을 독립적으로 다시 읽은 뒤 새 Azure Resource
  Graph 관측값과 비교합니다. 보존되는 증적에는 다이제스트, 완전성, 결정, 개수, 값이 0인 권한
  카운터만 포함됩니다. Container Apps 모듈은 기본적으로 구성 표류 설정을 내보내지 않습니다.
  배포 소유자가 보호된 기준선 envelope 값 두 개를 모두 제공하면 이후 모든 Core 계획은 고정된
  근거 도구 체인을 설치하고 정확한 바인딩을 보존하며, 성공한 모든 Core 적용은 독립적인 다시 읽기를
  반복합니다.
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
- 준비된 캠페인은 inert 자동화 청사진을 제출합니다. Shadow weekly 이벤트가 생기기 전에 독립적인
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
  (`security | reliability | cost | config_drift | compliance`) 으로 정규화 - 성능 신호
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
- **SLO, 경보 품질, 소유권(8)**: fast/slow burn, 오류 예산, 경보 storm,
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

### 분산 추적 연속성

예약된 분석기는 배포에서 구성한 분산 추적 토폴로지 하나를 인벤토리 Resource로
취급하지 않고 평가할 수도 있습니다. 토폴로지 대상은 안정된 일반 참조와 순서가
있는 기대 hop 이름 집합을 선언합니다. Azure 전달 어댑터는 범위가 제한된 작업
영역 기반 Application Insights 행을 읽고 시나리오 신원, 추적 신원, hop 이름,
관측 시각, 변경 불가능한 근거 참조만 정규화합니다. 배포 값과 조회 자격 증명은
리포지토리 밖에 유지합니다.
60초 detection bucket은 900초 근거 lookback과 독립적으로 유지됩니다. 따라서 반복 멱등성과
Incident 상관관계 범위를 보존하면서 문서화된 120-300초 Log Analytics ingestion 하한을
포괄합니다.

감지기는 완료된 각 시나리오 실행을 기대 토폴로지와 비교합니다.

- **연속 상태**: 추적 신원 하나가 모든 기대 hop을 순서대로 포함합니다. 실행은
  정상 관측 근거를 기록하고 발견 사항을 발행하지 않습니다.
- **컨텍스트 재생성**: 모든 기대 hop이 관측되었지만 추적 신원 하나로 전체
  토폴로지를 포괄하지 못합니다. 발견 사항은 분리된 추적 조각과 정확한 hop
  경계를 기록합니다.
- **컨텍스트 소실**: 전체 실행에서 하나 이상의 기대 hop이 없습니다. 발견 사항은
  어떤 구성 요소가 컨텍스트를 제거했다고 추측하지 않고 누락된 hop을 기록합니다.
- **알 수 없음**: 소스를 사용할 수 없거나, 결과가 잘렸거나, 보존 범위를
  벗어났거나, 완료된 실행이 없습니다. 틱은 정상 결과나 발견 사항을 만들지 않고
  보류하므로 원격측정 누락이 워크로드 장애의 증거가 되지 않습니다.

각 불연속 감지기는 shadow 모드로 시작하고 토폴로지, 시나리오, 관측 구간마다
안전하게 재시도할 수 있는(idempotent) Event 하나를 발행합니다. Event는 시나리오
상관관계 키와 범위가 제한된 변경 불가능한 근거 참조를 포함하고
`event-ingest`로 재진입합니다. 따라서 반복되는 high 심각도 발견 사항은 Heimdall의
기존 임계값과 수명 주기 검사를 통해 중복 제거된 인시던트 하나를 열 수 있습니다.
근본원인 분석은 인용된 원격측정이 해당 구분을 뒷받침할 때만 관측된 경계와 계측,
수집기, 헤더 전파 후보 원인을 구분할 수 있습니다. 감지기 자체는 서비스를
재시작하거나 게이트웨이 정책을 변경하지 않습니다. 제안된 복구 작업에는 일반
안전성 검토, 필요한 사람 승인, 7개 안전조건, 독립적인 효과 검증이 계속 적용됩니다.

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
포함해 정밀도, 재현율, resource-day당 false 경보, PR-AUC, Brier 점수 또는 calibration 오류,
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

PostgreSQL 예측 에피소드 저장소는 읽기 전용 운영 근거 snapshot을 노출합니다. 결정론적
reducer는 정밀도, 재현율, 놓친 위반율, 구간 포괄률, 양수인 평균 및 중앙값 선행 시간, 양수가
아닌 선행 시간 수, 판단 보류율, 명시적인 결과 수와 분모 공백을 보고합니다. 발견된 문제를
발행하기 전에 이미 발생한 위반은 snapshot을 실패시키거나 선행 시간을 부풀리지 않고 액션할
수 없는 근거로 보존합니다. 개입으로 검열되거나 점수화할 수 없는 결과는 계속 표시하지만
점수화 가능한 분모에는 넣지 않으며, snapshot은 실행 또는 승격 권한을 부여하지 않습니다.

## 4. 근본원인 분석(Root-Cause Analysis)

티어 계약, 결정론적 인과사슬, 근거가 있는 reasoning, knowledge 근거 및 읽기 전용 프로젝션은
[근본원인 분석](root-cause-analysis-ko.md)에서 소유합니다.

## 컨트롤 루프에 플러그

상관관계는 `event-ingest` 안에서 실행. 이상과 예보 감지기는 **out-of-band 생산자**
([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md) 및 phase-1
out-of-band 감지 참조) 로 발견 사항을 버스에 publish; 그 발견 사항은 멱등성 키와 dedup을
얻기 위해 **`event-ingest` 로 재진입** , 그래서 flapping 감지기가 중복 작업을 주입할 수 없음.
어떤 감지기도 새로운 자율성 표면이 아님:

```text
telemetry / metrics
  -> anomaly / forecast detectors emit findings ---.               # sections 2-3
  raw events -------------------------------------- +-> event-ingest
                                                       (normalize + dedup + correlate)   # section 1
  -> trust-router -> T0 | T1 | (T2 -> quality-gate)                                       # RCA per tier, section 4
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

- 저장소가 관리하는 `config/detection-governance-policy.json`은 감지기 방식, 콜드 스타트
  하한, 예측 대상 계열과 기간, 정확한 상관관계 키와 창, 백테스트 승격 임계값, 변경 창 처리
  방식을 고정합니다. Core는 `core/detection/governance_policy.py`를 통해 필드가 정확한지
  검증하며 정책을 로드하므로 알 수 없는 방식, 중복 신원, 완화된 정책 이탈 0건 가드 또는
  잘못된 경계값이 있으면 시작을 실패 처리합니다. 현재 실행 가능한 연결은 예측 대상 섹션을
  강제합니다. 각 `FDAI_FORECAST_TARGETS_JSON` 항목은 관리되는 `target_kind`를 지정하며, 시작
  과정은 정책과 다른 기간 또는 신뢰수준과 정책을 완화하는 샘플 또는 적합도 하한을 거부합니다.
  이상 감지, 상관관계, 승격, 변경 창 섹션은 기존 고정 evaluator를 위한 검토된 구성
  계약입니다. 이 범위는 해당 섹션의 별도 런타임 재정의 연결을 구현했다고 주장하지 않습니다.
- 베이스라인, 편차 임계, 예보 지평, 상관관계 키, 모델 바인딩은 **설정**; 포크는
  [project-structure-ko.md](../architecture/project-structure-ko.md) 의 DI 경계로 오버라이드, 절대 코어를
  편집하지 않음.
- 감지기는 시작 시 설정을 검증하고 **실패 시 차단** - 깨진 감지기, 부족한/콜드스타트 베이스라인,
  stale 원격측정은 false 발견 사항 발행 이나 auto-act가 아니라 감지기 **abstain** 하게 함.
- Repeated-event 인시던트 정책은 startup-bound 런타임 Settings입니다.
  `incident.auto_open.enabled`(기본 `true`), `incident.auto_open.min_severity`(기본 `high`),
  `incident.repeat_threshold`(기본 `5`, 범위 `2-100`),
  `incident.repeat_window_seconds`(기본 `300`, 범위 `10-86400`),
  `incident.security_high_threshold`(기본 `5`, 범위 `1-100`),
  `incident.security_window_events`(기본 `100`, 범위 `1-10000`),
  `incident.alert_rate_per_hour`(기본 `5`, 범위 `1-1000`)를 사용합니다. 잘못된 값은 시작을
  실패시킵니다. 심각도는 `critical/high/medium/low/info`에서 `SEV1-SEV5`로
  결정론적으로 매핑하며 조립은 모든 후보를 고정 심각도로 바꾸지 않습니다.
- 감지 발견 사항은 **신뢰할 수 없는 입력**; 어떤 LLM 사용(퍼지 상관관계, T2 RCA)도 quality 게이트
  ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md))
  와 [security-and-identity-ko.md](../architecture/security-and-identity-ko.md) 의 프롬프트-인젝션 위협 모델을
  통과.
- 감지기 메트릭 발행 - fire 비율, false-positive 비율, false-negative/놓친-위반 비율, abstain
  및 콜드스타트 억제 카운트, 예보 lead 시간, RCA groundedness - 를 KPI 대시보드로.

### 런타임 전달 상태

스케줄러 전달 경로는 정본 멱등 Event를 구성된 Event Hubs 유입 토픽에 게시합니다.
분석기 Terraform 작업은 `fdai.delivery.analyzer_tick_cli`를 호출하며, 이 진입점은 구성된 대상
목록과 영속 인벤토리 projection에서 대상을 해석하고 조립된 `MetricProvider`로 참조 분석기를
실행한 뒤 리소스, 신호, tick 창에서 파생된
키로 발견 건마다 정본 Event 하나를 게시합니다. 인벤토리 기반 해석은 읽기 전용이며 실패 시
`fdai-incident-evidence-query` 유지관리 진입점은 service 소유 store를 통해 영속 Incident audit를
읽고 범위가 제한된 correlation prefix 하나에 대한 transition 수, 고유 Incident 수, 최대 member 수,
kind 집계만 반환합니다. Incident ID, member ID, payload 또는 database 구성은 반환하지 않습니다. 인벤토리 기반 해석은 읽기 전용이며 실패 시
`fdai-forecast-evidence-query` 유지관리 진입점은 명시적 episode 분모와 평가 가능한 분모가 없을 때
`null` rate를 포함하는 repeatable-read forecast health snapshot을 반환합니다. 이 snapshot은 근거
전용이며 promotion 권한을 부여하지 않습니다. 인벤토리 기반 해석은 읽기 전용이며 실패 시
차단됩니다. 검토된 분석기 매핑이 없는 리소스 유형은 건너뛰고, stale, 충돌, 부분, 합성 관측
상태 사실은 안정된 사유와 함께 건너뛰며, projection을 읽지 못하면 구성된 목록만으로 축소하지
않고 예외를 올려 작업이 재시도합니다. Resolver는 이전 flat metadata 형식과 현재 속성별 collection
형식에서 canonical generic `state` 사실만 허용하며 다른 속성별 사실로 대체하지 않습니다. Generic
`state` 사실이 없는 metadata collection은 신원 및 유형 전용 열거 경로를 따릅니다. 이 읽기 전용
선택은 상태를 주장하거나 권한을 부여하지 않습니다. 존재하는 generic `state`에는 admission이 계속
필요하며 형식이 잘못되면 사용할 수 없습니다. 상태 사실 없이 투영된 리소스도 같은 열거 경로를
따릅니다. 발견된 대상 수는 상한이 있고 순서는 결정론적입니다. 이 작업들은 변경을 실행하지
않으며, 발견된 문제와 예정 작업은 공유 trust router 및 안전성 검토에 다시 진입합니다.
게시 실패 시 예약 항목은 재시도 가능 상태로 유지되고 작업 결과는 0이 아닌 값입니다.
추적 상태와 재시도에도 유지되는 명시적 실행 신원 또는 Container Apps 작업 실행 신원이 구성된
경우 완료된 각 실행은 대상 해석 수, 발견된 문제의 발행, 추적 연속성 결과, 준비 상태를 포함한
내용 다이제스트 기반 `runtime:analyzer-tick-receipt:` 레코드 하나도 보존합니다. 같은 내용의
재시도는 no-op입니다. 안정적인 작업 실행 ID는 상위 신원이고 각 직렬 실행은 안정적인 tick
순번을 가지며 보고서 다이제스트는 시도 신원입니다. 내용이 달라진 재시도는 이전 실패와 복구
근거가 충돌하지 않도록 별도의 내용 기반 시도로 보존하고, 이후의 동일한 tick도 첫 tick
증적으로 축약하지 않습니다. 각 증적은 항상 `execution_authority: false`를 포함합니다. 안정적인
실행 신원이 없는 로컬 실행은 운영 증적을 만들지 않습니다.
보호된 분리 서비스 배포는 다이제스트로 고정된 GHCR OCI 대상을 통해 provenance, SBOM, Core
모델 자료 증명을 검증합니다. 따라서 비공개 배포 runner가 관련 없는 공개 Blob DNS에 의존하지
않습니다.
보호된 `plan-observability-*` 및 `apply-observability-*` 요청 계열은 analyzer Container Apps
Job의 광범위한 선행 조건 그래프가 아니라 state 전용 Terraform updater 하나만 대상으로 합니다.
Updater는 digest로 고정된 ACR image와 고정된 Job/container 이름 하나만 허용합니다. Apply는 해당
image를 갱신하고 권위 있는 readback을 검증하며, 검증이 실패하면 이전 digest를 복원합니다. 원래
Container Apps Job 리소스가 선언적 소유자로 유지되므로 updater는 다른 Job 속성을 소유하지 않고
같은 구성 image로 수렴합니다.

Azure 리소스 생성, 갱신, 삭제 신호는 정본 Event Hubs 유입을 통해 계속
흐릅니다. Huginn은 이 실시간 발견 유입을 소유하고 정규화된 Event에 리소스 신원,
변경 종류, 범위가 제한된 속성을 보존합니다. 전용 projector는 partition 순서에 따라 리소스,
링크, tombstone delta를 durable inventory overlay에 적용합니다. 완전한 ARG/ARM
reconciliation은 별도의 범위가 제한된 완전성 증명으로 유지하지만, 목표 정책은 고정된 6시간
최신성 cadence 대신 이를 적응형으로 실행합니다. Durable lag, 변경량, 최대 노후 시간, 요청 예산,
공급자 throttling, 범위가 제한된 backoff, circuit 상태가 다음 작업을 결정합니다. Heimdall은
stale snapshot, cursor lag, 대체 경로 spike, 범위 loss, 공급자 압력을 감지합니다. 최신성 조회가
없거나 degraded 또는 stale이면 graph-dependent 작업을 사람 검토로 보냅니다. Inventory 기반
준비 상태 probe는 발견 성공을 단정하지 않고 해당 최신성 상태를 보존하며 Heimdall은 관찰기로
유지됩니다. 진행 시 다시 설정되는 무진행 마감과 절대 상한은 계속 batch를 내는 느린 원본을
종료하지 않으면서 멈춘 원본을 실패시킵니다. 전체 수집, 보존, rollup, archive 계약은
[지속형 운영 인스턴스 그래프](../architecture/continuous-operational-instance-graph-ko.md)에 정의됩니다.
## 확정된 결정

| 결정 | 관리되는 기본값 |
|------|------------------|
| 신호 클래스별 이상 방식 | 정상성이 있는 안정성 및 보안 활동 신호는 z-score를 사용합니다. 주기적인 안정성 및 비용 신호는 명시적인 위상을 가진 seasonal z-score를 사용합니다. |
| 예측 계열과 기간 | 현재 대상은 모두 구현된 선형 추세 계열을 사용합니다. 용량은 24시간, 복제 지연은 1시간, 비용은 7일, 만료는 30일을 사용합니다. |
| 상관관계 | 정확한 `correlation_id` 및 `resource_ref` 키를 T1보다 먼저 사용합니다. 일반 창은 60초, 추적 및 반복 창은 300초이며, fuzzy T1에는 `0.85` 이상의 유사도와 공유 근거 필드 2개가 필요합니다. |
| 콜드 스타트 | 정상성이 있는 클래스에는 기준선 샘플 30개, 계절 클래스에는 같은 위상의 샘플 10개가 필요합니다. 예측에는 샘플 5개와 `R-squared >= 0.5`가 필요합니다. |
| 백테스트 및 승격 | 최소 14일의 관찰 모드와 점수화 가능한 에피소드 30개를 확보한 뒤 매주 평가합니다. 정밀도와 재현율은 각각 `0.8` 이상이어야 하고, 90% 구간 포괄률은 `[0.85, 0.95]`, 중앙값 선행 시간은 300초 이상, 판단 보류율은 `0.2` 이하, 정책 이탈은 0건이어야 합니다. |
| 변경 창 | 완전한 근거가 있는 정확한 범위의 활성 창은 발견된 문제에 주석을 남기고 Incident 승격을 보류합니다. 누락되거나 오래되었거나 불완전하거나 일치하지 않는 창 근거는 발견된 문제를 억제할 수 없습니다. |

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/rules-and-detection/observability-and-detection.md) |
