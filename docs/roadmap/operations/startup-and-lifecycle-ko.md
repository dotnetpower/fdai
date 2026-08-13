---
title: 시작과 라이프사이클(Startup and Lifecycle)
translation_of: startup-and-lifecycle.md
translation_source_sha: d063264266cf68e275cbfeb3ef47ff9150b4ad98
translation_revised: 2026-08-13
---

# 시작과 라이프사이클(시작 and 수명 주기)

FDAI가 새로 프로비저닝된 Azure 구독에서 **콜드로 시작해 정상 상태에 도달** 하는 방법.
답변: 시스템은 언제 "시작"하는가? 첫날 카탈로그에 무엇이 있는가? 자율 발견 루프는 언제
시작하는가? shadow → 강제 적용 라이프사이클은 어떻게 시퀀싱되는가?

[deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md) (프로비저닝 처리) 와
[operating-and-verification-ko.md](operating-and-verification-ko.md) (지속 관측 처리) 보완.
설계 불변식은
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 에서.

Azure 초점: 비-Azure 프로바이더는 TBD
([Always-On 룰](../../../.github/copilot-instructions.md#always-on-rules-must)).
아래 타임라인 제안은 방향성이지 하드 규칙 아님; **게이트는 하드**.

> **구현 상태**: 현재 참조 Terraform은 KEDA 규모 룰 없이 `min_replicas = 1`인 단일
> `core` 컨테이너를 배포합니다. 범용 룰 카탈로그와 모델 해석기 CLI는 존재하지만 아래
> 자동 수집기/발견 시작, 종단 간 HIL 초기화 및 모델 수명 주기 조정은
> 완전한 런타임 작업 흐름으로 연결되지 않았습니다. 이 문서는 현재 초기화 계약과 목표
> 수명 주기를 함께 표시합니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 시작 준비 상태 조정 | `implemented` | [`runtime/readiness.py`](../../../services/core-control-plane/src/fdai/runtime/readiness.py), [`core/readiness/coordinator.py`](../../../services/core-control-plane/src/fdai/core/readiness/coordinator.py) 및 준비 상태 집중 테스트 | 런타임은 순서가 지정된 단계를 평가하고 정제된 보고서를 저장하며, 결과 결정에 따라 처리를 게이팅합니다. |
| T2 교차 검사 시작 증명 재사용 | `implemented` | [`delivery/startup_model_probe.py`](../../../services/core-control-plane/src/fdai/delivery/startup_model_probe.py) 및 [`tests/delivery/test_startup_probe.py`](../../../services/core-control-plane/tests/delivery/test_startup_probe.py) | 프로세스에서 처음 성공한 증명은 구성된 샘플을 사용합니다. 이후 새로 고침은 추가 T2 요청 없이 이를 재사용하며 실패는 계속 재시도할 수 있습니다. |
| 부트스트랩 및 수명 주기 자동화 | `in-progress` | [`rule-catalog/catalog/`](../../../rule-catalog/catalog/), [`llm_resolver_cli.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/llm_resolver_cli.py), [Teams](../../../services/core-control-plane/src/fdai/delivery/notifications/teams.py) 및 [Slack](../../../services/core-control-plane/src/fdai/delivery/notifications/slack.py) 어댑터 | 자동 수집기 및 발견 시작, 종단 간 사람 승인 초기화, 모델 수명 주기 조정은 아직 완료되지 않았습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-13 | `implemented` | 성공한 각 T2 교차 검사 시작 증명을 프로세스의 후속 준비 상태 새로 고침에서 재사용하여 5분마다 다시 샘플링하지 않도록 했습니다. 실패 및 동시 시도는 안전하게 재시도됩니다. | 현재 변경의 `startup_model_probe.py` 및 `test_startup_probe.py`, 시작 탐색 집중 테스트: `18 passed` | 관리되는 배포 런타임 계측 근거를 수집하고 아래의 더 넓은 수명 주기 작업 흐름을 완료합니다. |

### 남은 작업

- [ ] 자동 수집기 및 발견 시작, 종단 간 사람 승인 초기화, 모델 수명 주기 조정을 완료하고
   이 원장에 집중 작업 흐름 테스트를 인용합니다.
- [ ] 후보별로 성공한 T2 시작 샘플 세트가 한 번만 실행되고, 해당 프로세스의 이후 5분 준비
   상태 새로 고침에서는 T2 호출이 추가되지 않음을 보여 주는 관리되는 배포 런타임 계측을 기록합니다.

## 콜드 스타트 (scale-to-zero 세부사항)

현재 코어 엔진은 **하나의 Container App과 하나의 `core` 컨테이너**로 실행됩니다. Trust
라우터, 실행기, 감사 쓰기 담당은 현재 같은 Python 프로세스 안에 있고 localhost sidecar IPC는
없습니다. Day-zero `min_replicas` 기본값은 1이며 Event Hubs lag KEDA 룰은 없습니다. 포크가
lag 기반 규모 룰을 추가한 뒤에만 `min_replicas = 0`으로 낮춰 scale-to-zero를 사용할 수
있습니다. 현재 "시작"은 다음과 같습니다:

1. Container App 개정 번호가 `core` 복제본을 시작하고 최소 한 복제본을 유지합니다.
2. Core 프로세스가 구성을 로드하고 상태, 감사, event-bus 어댑터 및 룰 카탈로그를 구성합니다.
3. HTTP 시작/준비 상태 탐색이 `/ready`를 확인한 뒤 복제본이 traffic-ready가 됩니다.
4. 소비자가 이벤트를 `event-ingest → correlation → trust-router → tier → risk-gate → audit`
   프로세스 내 경로로 처리합니다.

향후 scale-to-zero를 활성화한 배포의 콜드 스타트에는 다음 규칙이 적용됩니다:

- **콜드-스타트 메트릭**: 콜드 경로의 첫 이벤트는 복제본이 warm 되는 동안 T0 지연 예산을
  초과할 수 있음. 이 지연은 T0 warm 지연 백분위가 오염되지 않도록 별도 **콜드-스타트 메트릭**
  으로 기록되어야 함. 콜드 vs warm은 KPI 대시보드에 나란히 보고
  ([goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md)).
- **콜드-스타트 데드라인**: 설정된 데드라인 초과는 이벤트를 HIL로 강등, 게이트 없는 auto-action
  이 되지 않음
  ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)).
- **콜드-스타트 순서**: 콜드 시작된 복제본은 리소스별 순서 / 멱등성 보장을 존중해야 함;
  올라오는 복제본이 "같은 이벤트 두 번 = 하나의 효과" 불변식을 위반할 수 없음.
- **향후 sidecar 준비 상태 게이팅**: Sidecar 토폴로지를 실제로 추가하는 경우 주 컨테이너는
   모든 sidecar의 준비 상태가 green일 때까지 이벤트를 받지 않는 것이 좋습니다. 현재 단일
   컨테이너 토폴로지에는 적용되지 않습니다.

**TBD**: 구체적 콜드-스타트 데드라인과 정확한 콜드-스타트-메트릭 이름/정의.

## 시작 환경 Preflight

`/ready`가 열리기 전에 런타임은 의존성별 시작 preflight를 평가하는 것이 좋습니다. 이는
프로비저닝 중심 배포 preflight 및 활성 post-deploy smoke 테스트와 구분됩니다.

> **구현 상태**: Headless 런타임은 이제 Pantheon 또는 이벤트 소비자를 시작하기 전에 하나의
> 결정론적 `StartupReadinessReport`를 조립합니다. 표준 탐색 인벤토리는 로드된
> 구성/카탈로그/정책, 시크릿 주입, 워크로드 신원, 상태, 감사, 비상 정지, Kafka
> 왕복, 임베딩 및 바인딩된 모든 T2 교차 검증 후보를 검사합니다. 포크는 동일한
> injected 탐색 경계로 활성화된 선택적 대상을 등록합니다.

### 단계와 결정

| 단계 | 검사 | 변경 정책 |
|------|------|-----------|
| Static 부하 | release 매니페스트, 구성 해시, 카탈로그 버전, 모델 연결, 이행 expectation | 네트워크와 변경 없음 |
| 필수 도달 가능성 | 신원 토큰, 비공개 DNS, TLS, PostgreSQL, Kafka, 카탈로그와 정책 엔진 | 범위가 제한된 읽기 전용 |
| 기능 예열 | 활성화된 각 모델, 임베딩, 검색, 알림 및 텔레메트리 어댑터 | 명시적 비용 한도가 있는 최소 요청 |
| 활성 smoke | Kafka 탐색 토픽 왕복, 데이터베이스 탐색 트랜잭션, canary, 사람 승인 dry 실행 | 전용 synthetic 범위만 사용 |

Kafka 왕복은 operational Event Hubs 이름 공간의 전용 `runtime.startup.probe` 개체를
사용합니다. Core 신원은 해당 개체에만 topic-scoped 데이터 Owner 권한을 가지며, 런타임
조립은 준비 상태를 operational 버스로 전달합니다. 따라서 탐색 트래픽은 가득 찬 기본
이름 공간의 용량을 사용하거나 통제된 이벤트 토픽과 섞이지 않습니다.

보고는 세 가지 결정을 사용합니다. `blocked`는 `/ready`를 닫습니다. `degraded`는 관찰 또는 읽기 전용
작업을 열 수 있지만 사용 불가 기능의 권한을 낮춥니다. `ready`는 낮은 권한 상한 없이 필수
검사가 통과했음을 뜻합니다. 결과는 검사 id, 의존성 또는 기능, 필수/선택적 분류,
결정, 지연 시간, 근거 시간, 정제된 실패 등급 및 다음 재시도를 기록합니다.

### 필수 탐색 인벤토리

| 영역 | 시작 근거 |
|------|------------------|
| release와 구성 | 이미지 다이제스트, release 버전, 구성 해시, 카탈로그 버전, `resolved-models.json` 스키마와 최신성 |
| 호스트 trust | 설정된 토큰/TLS 허용 범위 이내의 시계 skew, certificate 체인과 만료, proxy와 custom CA 구성 |
| 신원과 시크릿 | audience-scoped 토큰 획득, 필수 역할 관찰, native 시크릿/참조 주입 |
| 상태와 정책 | PostgreSQL 연결, 이행 헤드, 전체 감사 hash-chain 검증, 비상 정지 읽기, 카탈로그 부하, OPA compile |
| Event 경로 | Kafka DNS/TCP/TLS/auth, 필수 토픽, 소비자 그룹, DLQ 및 Diagnostic Settings forwarder 상태 |
| 모델 기능 | 배포 준비 상태, auth, 할당량 headroom, feature 플래그, mixed-publisher 불변식, 검증기와 grounding 가용성 |
| 선택적 어댑터 | 웹 검색, 알림, 사람 승인 채널, OTLP 내보내기 및 포크가 등록한 프로바이더 |

단일 `internet_available` 결정은 사용하지 않습니다. 활성화된 각 대상을 DNS, TCP, TLS,
authentication 및 하나의 범위가 제한된 프로토콜 연산으로 검사합니다. 패키지와 이미지 레지스트리는
build-time 근거로 유지합니다. 비공개 엔드포인트는 런타임 서브넷에서 검사합니다.

### 모델 지연 시간과 복구

각 모델 후보는 시작 증명을 실제로 수집할 때 최소 두 개의 범위가 제한된 샘플을 받습니다. T2
교차 검사 후보가 성공하면 같은 런타임 프로세스의 이후 준비 상태 새로 고침은 해당 구조화된 출력
증명을 재사용하고, 추가 모델 요청 없이 보고서 타임스탬프를 새로 발급합니다. 실패하거나 일부만
완료된 T2 증명은 캐시하지 않으며 계속 재시도할 수 있습니다. 스트리밍은 첫 토큰까지의 시간
(TTFT), 총 지연 시간, 출력 토큰 비율, 샘플 수 및 정제된 실패 분류를 기록합니다. 임베딩은 지연
시간과 벡터 형태를 증명하고, 구조화된 출력 및 도구 호출 후보는 해당 기능을 증명합니다. 탐색은
최소 프롬프트와 제한된 출력을 사용하고 관련 없는 도구 비용과 오류 텍스트 저장을 피합니다.

Narrator 대상은 TTFT p95 2.5초 이내로 유지합니다
([operator-console-view-snapshot-ko.md](../interfaces/operator-console-view-snapshot-ko.md)). 시작
샘플은 최소 샘플 개수 전에는 percentile을 주장하지 않습니다. 대상 miss는 `degraded`,
기한 전 valid first 토큰 부재는 사용 불가입니다. T2는 계속 mixed-model과 검증기 게이트를
요구하며 기한 miss는 사례를 사람 승인으로 낮춥니다.

근거는 설정된 간격 이후 만료됩니다. 주기적 탐색은 보고서를 새로 고치고 전이만 덧붙입니다.
T2 교차 검사와 감사 내구성 탐색은 성공한 프로세스 로컬 증명을 재사용합니다. 준비 상태 결과는
모델 요청이나 감사 추가를 반복하지 않고 새로운 근거 시각과 만료 시각을 받습니다. 실패한 증명은
계속 재시도할 수 있습니다. 복구는 `ready`를 복원할 수 있지만 배포의 승격 상태보다 권한을 높일
수 없습니다.

### 실패와 권한 규칙

- **Process-critical**: 잘못된 구성, 토큰/시크릿 실패, PostgreSQL/감사 실패, 감사 hash-chain 불일치, 정책 compile 실패 또는 필수 Kafka 실패는 `/ready`를 닫습니다.
- **Authority-critical**: 읽을 수 없는 비상 정지, 누락된 T2 검증 또는 사용 불가 승인은 shadow나 사람 승인을 강제합니다. 검증되지 않은 자동 액션을 활성화하지 않습니다.
- **선택적 기능**: 서술기, 검색, 알림 또는 텔레메트리 실패는 결정론적 대체 경로 또는 비활성화된 상태와 함께 `degraded`로 보고하며 healthy로 가장하지 않습니다.
- **탐색 안전성**: 검사는 범위가 제한된, safe to 재시도, 정제된이며 전용 synthetic 리소스 외에는 읽기 전용입니다. 부분 필수 탐색은 `ready`가 아니라 `blocked`가 됩니다.

### 제공되는 런타임 경계

프로바이더 중립적인 계약과 집약기는 `core/readiness` 아래에 있습니다. 탐색 구현은
`delivery` 아래에 있고, `runtime/readiness.py`가 순서가 있는 네 단계를 조립합니다. 한 단계 안에서는
범위가 제한된 동시성을 사용하지만 현재 단계가 끝나기 전에는 다음 단계를 시작하지 않습니다.
조정기는 탐색별/단계별 기한, 재시도, 전체 시작 비용 한도 및 활성화된 모델 후보별
최소 두 샘플을 적용합니다.
각 탐색 시도에는 탐색 id와 기한에서 파생된 synthetic 상관관계 id가 할당됩니다.
조정기는 시도 이후 호출자의 기존 상관관계 맥락을 복원합니다. 따라서 모델 예열
비용을 추적할 수 있으며 탐색 근거를 운영자 이벤트로 표시하지 않습니다.

런타임은 정제된 근거만 `runtime:startup-readiness:latest`에 저장합니다. 결정이 변경되면 감사
기록을 덧붙이기하고 JSON 스키마로 검증된 `readiness_transition` 이벤트를 publish합니다. 프로바이더 오류
텍스트, 자격 증명, 엔드포인트 값, 배포 이름 및 customer 식별자는 보고와 전이 페이로드에
포함되지 않습니다.

`/live`는 프로세스 생존을 별도로 보고합니다. `blocked`이면 `/ready`는 `503`을 반환하며 코어
소비자, 발견, canary, 사람 승인, 보존, runtime-state 및 Pantheon 작업은 중지 상태를
유지합니다. 주기적 새로 고침은 process-critical 의존성이 차단된이 되면 실행 중인 작업을
취소하고 복구 후 다시 시작합니다. 복구는 조립에서 받은 배포 상한을
재사용하며 권한을 승격할 수 없습니다.

범위가 제한된 실행기는 `FDAI_STARTUP_MAX_CONCURRENCY`, `FDAI_STARTUP_KAFKA_SETTLE_SECONDS`,
`FDAI_STARTUP_PROBE_TIMEOUT_SECONDS`, `FDAI_STARTUP_PHASE_TIMEOUT_SECONDS`, `FDAI_STARTUP_PROBE_RETRIES`,
`FDAI_STARTUP_COST_LIMIT_USD`, `FDAI_STARTUP_MODEL_SAMPLE_COUNT` 및
`FDAI_STARTUP_REFRESH_SECONDS`로 조정할 수 있습니다. 활성화된 선택적 어댑터는 blanket connectivity
플래그를 추가하지 말고 `StartupProbeSpec`과 `StartupProbe`를 등록하는 것이 좋습니다. Azure 참조
프로파일은 Event Hubs consumer-group 결합에 12초, 탐색마다 30초, 단계마다 75초를 허용하여 기본
시도 2회가 완료될 범위가 제한된 headroom을 확보합니다. 이 값은 배포 기본값이며 프로바이더 중립적인
런타임 기본값을 변경하지 않습니다.

### 지속적인 monitored-target 준비 상태

Analyzer Container Apps 작업은 shadow 모드에서 기본 1분마다 실행됩니다. 명시적 대상이 있으면
이를 사용하고, 그렇지 않으면 영속 인벤토리에서 지원 리소스를 읽습니다. 각 AKS 대상에
대해 정제된 6개 `detection.readiness.observed` 기록을 일반 raw 이벤트 토픽으로 발행합니다.
이후 Huginn, Heimdall, Muninn, Forseti, Saga가 각각 정규화, 축약, 영속 스냅샷, 권한 상한,
감사를 담당합니다. 콘솔은 Muninn 스냅샷을 읽으며 Azure를 탐색하거나 판정을 다시 계산하지
않습니다.

`analyzer_tick_cron_expression`을 명시적으로 빈 값으로 설정하면 작업이 비활성화됩니다. 텔레메트리
또는 이전 파이프라인 스냅샷이 누락되면 `ready`가 아니라 `partial`이 됩니다. 완전한 스냅샷도
준비 상태 작업 흐름의 초기 `shadow` 상한 아래에 유지되며 액션을 승격할 수 없습니다.

### 실제 운영 검증 근거

2026-07-23에 VNet-integrated 자체 호스팅 실행기가 기존 개발 의존성에 범위가 제한된 검사를
실행했습니다. Terraform은 데이터 리소스를 교체하지 않고 두 Event Hubs 샤드와 기존 public-mode
PostgreSQL 서버에 비공개 엔드포인트 및 linked 비공개 DNS를 추가했으며 Event Hubs 공개 접근을
비활성화했습니다. 마지막 exact 대상 계획은 변경 사항이 없다고 보고했습니다. 실행기 VNet에서
PostgreSQL, Event Hubs 및 구성된 모델 엔드포인트는 모두 비공개 주소로만 해석되었고 TCP를
수락했습니다. Event Hubs와 모델 엔드포인트는 일반 TLS를 완료했으며 PostgreSQL은 protocol-aware TLS
handshake를 완료했습니다. 최소 managed-identity 모델 연산은 `401`을 반환했으므로 탐색은
healthy 기능 근거를 기록하지 않고 모델 경로를 degraded로 분류했습니다. 통제된 refused
대상은 정제된 `ConnectionRefusedError` 등급과 함께 `blocked`로 축소되었습니다. 검증 후
임시 접근을 제거하고 실행기 산출물을 삭제했으며 데이터베이스와 실행기를 이전
stopped/deallocated 상태로 되돌렸습니다.

## 초기 규칙 카탈로그 상태

상류 리포는 **고객 특이 규칙 없음**. 포크 배포의 첫날 카탈로그는 두 소스에서 채워짐 - 순서:

1. **부트스트랩 시드 세트** (포크 책임) - `content_hash` 와 버전으로 고정된 초기 카탈로그
   스냅샷, 포크가 자체 catalog-as-code 리포에 커밋.
2. **자율 컬렉터** (상류) - 첫 성공 컬렉터 실행 후, 상류 소스가
   [rule-catalog-collection-ko.md](../rules-and-detection/rule-catalog-collection-ko.md) 에 따라 설정된 주기로 수집.

현재 업스트림은 `rule-catalog/catalog/`, 범용 profiles, 출처 매니페스트 및
`tools/seed_p1_manifest.yaml`을 함께 제공합니다. 포크는 이를 customer-specific 값 없이 그대로
사용하거나 fork-owned 오버레이/시드를 추가할 수 있습니다. Collector 예약은 배포가 별도로
연결해야 합니다.

첫날 카탈로그에 적용되는 규칙:

- 모든 규칙은 심각도와 무관하게 **`effect: audit` (shadow)** 기본이어야 함. 강제 적용으로 시작하는
  규칙을 출시할 방법 없음; 첫날에 강제 적용으로 랜딩할 규칙은 승격 게이트 실패
  ([rule-governance-ko.md](../rules-and-detection/rule-governance-ko.md)).
- 모든 규칙은 시드 규칙 포함해서 근거에 기반한 **`provenance`** (출처 URL + resolved 개정 번호 +
  내용 해시 + license + `redistribution` 플래그) 를 운반해야 함. 출처 이력 없는 규칙은
  스키마 검증 실패.
- **LLM-생성 후보** 는 자율 발견 루프가 활성화되고 그 quality 게이트가 사용 가능해지기 전에는
  카탈로그에 진입하지 않음.

**TBD**: 첫날 시드 세트에 어떤 소스가 실리고 정확한 규칙 id - 단계 1의 "소스별 초기 대상 세트
열거"와 동일한 열림 항목
([phase-1-rule-catalog-t0-ko.md](../phases/phase-1-rule-catalog-t0-ko.md)).

## 이벤트 소스 부트스트랩

이벤트가 판단되기 전에 유입은 Azure 신호에 부착되어야 함:

1. **Diagnostic Settings** - 대상 구독과 각 in-scope 리소스 그룹에서, Activity Log(과 리소스별
   로그)을 **Event Hubs Kafka 토픽** 으로 forward 하는 Diagnostic Settings 활성화 - 이것이
   CSP-중립 이벤트 버스 계약
   ([csp-neutrality-ko.md § 이벤트버스 계약](../architecture/csp-neutrality-ko.md#1-이벤트버스-계약--kafka-와이어-프로토콜)).
2. **Kafka 토픽 + 컨슈머 그룹** - Event Hubs 네임스페이스에 첫날 토픽들을 생성
   (`aw.change.events`, `aw.dr.events`, `aw.finops.events`, 그리고 그들의 `<topic>.dlq`
   형제) 하고 `event-ingest` 를 위한 컨슈머 그룹 등록.
3. **멱등성 prime** - event-ingest 레이어가 처음 수신 시 모든 들어오는 이벤트에
   **멱등성 키** 를 스탬프하여 리플레이가 종단 no-op.
4. **DLQ 도달 가능성 검증** - dead-letter 목적지 (Kafka `<topic>.dlq`) 가 어디에서든
   강제 적용이 활성화되기 전에 실행됨 (poison-pill 프로브).

구체적 이벤트 타입과 필터 표현식은 **TBD** 이며
[deploy-and-onboard-ko.md#event-source-subscription](../deployment/deploy-and-onboard-ko.md#event-source-subscription)
에 캡처.

## 모델 프로비저닝 부트스트랩

T2가 실행되기 전에 기능→배포 매핑을 해결해야 합니다. 해석기 CLI와 스키마는
구현되어 있지만 현재 `deploy-dev.yml`은 `terraform apply` 전에 해석기를 자동 실행하지
않습니다. CI는 저장소 variable `RESOLVED_MODELS_JSON`을 `resolved-models.json`으로
materialize하고 런타임/Operator API는 구성된 파일 시스템 경로를 읽습니다.

1. **해석기가 `rule-catalog/llm-registry.yaml` 에서 실행** - 기능별 선호를 읽고,
   대상 리전의 Azure OpenAI / Foundry 카탈로그를 쿼리, `capacity_tpm` 상한과 함께 기능당
   하나의 배포 프로비저닝.
2. **Mixed-model 불변식 검증** - `t2.reasoner.primary.publisher` 는 `t2.reasoner.보조.
   발행기` 와 달라야 함, 아니면 부트스트랩 중단 (조용한 same-vendor 대체 경로 없음). 포크의
   `llm.mixed_model_mode` (`azure-foundry` / `external` / `hil-only`) 가 전략 선택.
3. **`resolved-models.json`을 protected 배포 산출물로 제공** - 기능 →
   `{deployment, family, version, publisher}`를 기록합니다. 현재 Terraform은 이 매니페스트를 Key
   Vault 시크릿으로 저장하지 않으며 경로/CI variable이 배포 경계입니다.
4. **주간 조정기는 후속 increment로 연기** -
   [dev-and-deploy-parity-ko.md](../deployment/dev-and-deploy-parity-ko.md)의 W-I가 완료되기
   전에는 명시적인 레지스트리 PR로 모델 변경을 검토합니다. 조정기는 새 계열과 폐기
   공지를 감시하고 초안 PR을 열지만 실제 운영 대응을 자동 교체하지 않습니다.

전체 설계: [llm-strategy-ko.md § 모델 프로비저닝 and 수명 주기](../architecture/llm-strategy-ko.md#model-provisioning-and-lifecycle).

## Shadow-First 롤아웃 레시피

모든 새 배포는 전체 footprint에 대해 **shadow-only 모드** 로 랜딩. 승격은 액션별, 규칙별,
도메인별 - 절대 글로벌 flip 아님. 제안된 마일스톤 (모든 타임라인은 **방향성** ; 게이트는 하드):

| 마일스톤 | 초점 | 진행 게이트 |
|----------|------|-------------|
| **D+0 → D+7** | 루프가 shadow에서 종단 실행 검증: 이벤트 랜딩 → 티어 결정 → 감사 기록 | 조용한 드롭 0, 미인증 액션 0, canary green |
| **D+7 → D+14** | 규칙별 shadow 정확도 + false-positive 비율 측정; 저위험 승격 후보 식별 | [goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md) 에 따른 shadow 표본 크기와 정확도 임계 |
| **D+14 → D+30** | 소수의 첫 저위험 규칙 배치를 `remediate` (PR-only) 로 승격, 모호한 것은 HIL | shadow 윈도우 내 정책 위반 escape 0 |
| **D+30 →** | 지속적 승격 사이클, 한 번에 한 규칙, 각각 enforce-promotion 승인 게이트에 따라 | 회귀 스위트 green, 측정된 정확도 안정 |

전 구간 적용되는 규칙:

- 어떤 회귀는 승격된 규칙을 **자동으로 shadow로 강등** - 강등은 승격 승인자를 절대 필요로 하지
  않아 안전 방향 저하는 항상 빠름
  ([rule-governance-ko.md](../rules-and-detection/rule-governance-ko.md#effects-mode)).
- 강제 적용 승격은 제안한 운영자와 **별도 승인** 필요
  ([security-and-identity-ko.md](../architecture/security-and-identity-ko.md)).
- 비상 정지는 D+7 종료 전에 도달 가능성 검증.

## 사람 승인 담당자 부트스트랩

> **현재 경계**: 역할/그룹 해석기와 Teams/Slack 전달 어댑터는 구현되어 있지만 Teams SSO
> OBO 승인 콜백, group-connected 대상 derivation, 거버넌스 PR 정족수 CI 및 예행 실행 HIL
> 초기화 작업 흐름은 아직 종단 간으로 연결되지 않았습니다. BreakGlass 역할은 런타임 HIL
> 승인 기능을 갖지 않습니다. 아래 단계는 포크 배포 목표입니다.

어떤 enforce-mode 규칙도 승격되기 전에 승인자 그룹이 프로비저닝되어야 함. 승인자가 없으면
고위험 발견 사항은 대체 경로 채널을 통해 큐잉되고 알림; **절대 auto-execute 안 함**. Entra 그룹
모델은 [user-rbac-and-identity-ko.md](../interfaces/user-rbac-and-identity-ko.md) 에 정의.

단계 (포크 책임):

1. HIL A1 트래픽과 다이제스트를 위해 `aw-approvers` 로 백업된 Teams **그룹-연결 팀** 생성;
   멤버십은 이후 Entra 그룹을 자동 추종
   ([channels-and-notifications-ko.md#51-audience-derivation-channel-as-audience](../interfaces/channels-and-notifications-ko.md#51-audience-derivation-channel-as-audience)).
2. 5개 Entra 보안 그룹 (`aw-readers`, `aw-contributors`, `aw-approvers`, `aw-owners`,
   `aw-break-glass`) 프로비저닝, 구성 자리에 objectId 주입
   ([user-rbac-and-identity-ko.md#42-security-groups-slots](../interfaces/user-rbac-and-identity-ko.md#42-security-groups-slots)).
3. `aw-approvers`/`aw-owners` 에 Conditional 접근 적용: phishing-resistant MFA 필수,
   이전 방식 auth 블록; `aw-owners` 에 compliant-device 추가
   ([user-rbac-and-identity-ko.md#43-conditional-access](../interfaces/user-rbac-and-identity-ko.md#43-conditional-access)).
4. 강제 적용 승격, 예외, 재정의에 **quorum-2** 규칙을 유지하는 데 필요한 최소 멤버 수로
   `aw-approvers` 채움
   ([user-rbac-and-identity-ko.md#51-codeowners-single-approver-group-path-based-reviewer-count](../interfaces/user-rbac-and-identity-ko.md#51-codeowners-single-approver-group-path-based-reviewer-count)).
5. 실행기의 Chat 어댑터 구성에 승인자 그룹 id 등록하여 Adaptive 카드 승인이 롤 점유를
   검증할 수 있게 함.
6. **Slack 워크스페이스 프로비저닝** (P1 A1 채널): FDAI Slack 앱 설치, `chat:write`
   부여, 필수 Slack userId ↔ Entra OID 매핑 저장소 채움; 매핑이 비어 있지 않을 때까지 Slack
   어댑터는 A1 트래픽 거부
   ([channels-and-notifications-ko.md#7-channel-specific-notes](../interfaces/channels-and-notifications-ko.md#7-channel-specific-notes)).
7. `rule-catalog/channel-routing/` 구성 (기본/대체 경로 채널, 다이제스트 스케줄, 오디언스)
   를 규칙과 같은 리뷰 엄격도로 커밋; A1 라우팅을 만지는 모든 변경은 Owner-티어 리뷰어 필요.
8. 카나리 경로를 통해 **예행 실행 HIL** 실행하여 승인이 랜딩하고 `justification` 이 요구되고
   시간 초과가 실패 시 차단이고 모든 승인이 `correlation_id` 있는 감사 엔트리를 씀을 확인.

## 자율 발견 루프 시동

[자율 규칙 발견 루프](../rules-and-detection/rule-catalog-collection-ko.md#autonomous-rule-discovery) 는
**첫날에 비활성**. 다음 모두 이전에 실행되어선 안 됨:

> 현재 업스트림에는 이 모든 조건을 평가해 루프를 자동 활성화하는 시작 조정기가
> 없습니다. 아래 조건은 향후 activation 게이트 계약입니다.

1. 감사 로그가 최소 **`N` shadow 결정** 을 축적하여 observe 스테이지에 실제 베이스라인 제공.
   `N` 은 설정 가능; **TBD** - 낮은 수천대 권장.
2. 최소 하나의 컬렉터가 성공 실행(배선 + 출처 이력 증명).
3. Mixed-model 교차 검사 대상과 결정론적 검증기가 건강.
4. Post-deploy smoke 테스트가 green
   ([operating-and-verification-ko.md](operating-and-verification-ko.md#post-deploy-smoke-테스트-계약)).

활성화되면 루프는 설정된 주기로 실행. 루프의 후보 규칙은 전체 quality 게이트를 통과할 때까지
inert - 루프는 카탈로그를 직접 변형할 수 없음.

루프 비활성화는 **정책 토글** ,  코드 변경 아님; 반복되는 재정의 신호는 다음 활성화를 위해
감사 로그에 계속 축적됨.

## 라이프사이클 상태

모든 아티팩트는 정의된, 감사 가능한 상태를 진행. 전이가 유일한 이동 방법; 각 전이는 버전되고
감사됨.

- **Rule / rule-set** - `draft → audit(shadow) ⇄ enforce(deny/remediate) → deprecated`,
  `disabled` 은 어떤 활성 상태에서도 도달 가능
  ([rule-governance-ko.md#lifecycle-and-versioning](../rules-and-detection/rule-governance-ko.md#lifecycle-and-versioning)).
- **배정** - 스코프, `effect`, `enforcement` 플래그에 바인딩. Effects는 승격 게이트 하에
  전이; 회귀는 자동 강등.
- **Exemption** - `active → expired` (time-boxed; auto-renew 없음)
  ([rule-governance-ko.md#exemptions](../rules-and-detection/rule-governance-ko.md#exemptions)).
- **재정의** - `active → removed`; 수명이 긴 가능(강제 만료 없음), 스코프는 resource-group-
  equivalent 이하이어야 함
  ([rule-governance-ko.md#overrides](../rules-and-detection/rule-governance-ko.md#overrides)).
- **액션** - `proposed → risk-gated → executed | rejected → rolled-back (해당 시)`. 모든
  상태가 멱등성 키를 운반하여 리플레이는 no-op.

## 열림 Decisions

- [ ] 콜드-스타트 데드라인 값과 정확한 콜드-스타트-메트릭 이름.
- [ ] 첫날 시드 규칙 세트(어떤 소스, 어떤 규칙 id) - 단계 1과 교차 링크.
- [ ] Discovery-루프 시동 임계 `N` (shadow-decision 카운트) 과 그 회귀-안전 근거.
- [ ] Kafka 토픽 레이아웃 + Diagnostic-Settings 포워더 필터 형상과 소스별 속도 상한.
- [ ] 부트스트랩 런북: 포크가 D+0에 도달하기 위한 정확한 명령 시퀀스 (
      [operating-and-verification-ko.md](operating-and-verification-ko.md#runbook-set) 소유).
- [ ] 예행 실행 HIL 절차: 카나리 페이로드, 예상 타이밍, 정리.
