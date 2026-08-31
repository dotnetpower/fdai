---
title: 시작과 라이프사이클(Startup and Lifecycle)
translation_of: startup-and-lifecycle.md
translation_source_sha: 3d68cbdf2fc399a3047daa8cc5d87cc334eeffc0
translation_revised: 2026-08-31
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
> `core` 컨테이너를 배포합니다. 보호된 배포는 모델 해석기와 제안 전용 주간 수명 주기
> 조정기를 실행합니다. 수집기 작업은 구성 가능한 배포 일정을 사용하고, 발견 활성화는
> 실패 시 차단되는 런타임 결정입니다. 사람 승인 콜백 초기화는 결정론적 로컬 근거로
> 구현되었으며, 통제된 배포 근거는 별도로 남아 있습니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 시작 준비 상태 조정 | `implemented` | [`runtime/readiness.py`](../../../services/core-control-plane/src/fdai/runtime/readiness.py), [`runtime/bootstrap_incidents.py`](../../../services/core-control-plane/src/fdai/runtime/bootstrap_incidents.py), [`core/readiness/coordinator.py`](../../../services/core-control-plane/src/fdai/core/readiness/coordinator.py) 및 준비 상태 집중 테스트 | 조정기는 전체 실행 및 탐색별 예산에서 하나의 근거 수명과 새로 고침 선행 시간을 계산합니다. 런타임 새로 고침은 범위가 제한되고 정확한 만료 시점에 처리를 닫으며 Thor에 실제 fail-closed 권한 상한을 제공합니다. PostgreSQL 상태 재구성은 process-critical로 유지하고 영속 A2 알림 replay는 격리합니다. |
| T2 교차 검사 시작 증명 재사용 | `implemented` | [`delivery/startup_model_probe.py`](../../../services/core-control-plane/src/fdai/delivery/startup_model_probe.py) 및 [`tests/delivery/test_startup_probe.py`](../../../services/core-control-plane/tests/delivery/test_startup_probe.py) | 프로세스에서 처음 성공한 증명은 구성된 샘플을 사용합니다. 이후 새로 고침은 추가 T2 요청 없이 이를 재사용하며 실패는 계속 재시도할 수 있습니다. |
| 수집기 일정 및 통제된 발견 활성화 | `implemented` | [`rule_watcher_job.tf`](../../../infra/modules/compute/container-apps/rule_watcher_job.tf), [`rule_collector_job_cli.py`](../../../services/core-control-plane/src/fdai/delivery/rule_collector_job_cli.py), [`core/readiness/discovery_activation.py`](../../../services/core-control-plane/src/fdai/core/readiness/discovery_activation.py), [`runtime/discovery_activation.py`](../../../services/core-control-plane/src/fdai/runtime/discovery_activation.py) 및 집중 수집기/활성화/Norns/런타임/인프라 검사 | 구성 가능한 작업은 실행 권한이 없는 인벤토리 신원을 사용하고, 검증된 출처 증적만 기록합니다. 런타임 조립은 정책과 최신 선행 조건이 모두 통과할 때까지 Norns 게시를 차단합니다. |
| 사람 승인 초기화 | `implemented` | `fdai_operator_service/families/iam/hil_callback*.py`, `scripts/operations/run-hil-bootstrap-canary.py`, 집중 Operator 콜백, PostgreSQL, Kafka, 워크플로, 거버넌스 및 카나리 테스트 | Teams 콜백은 구성된 승인 봇에 발급된 API 대상 Entra 토큰, 매핑된 행위자, 구성된 그룹 연결 팀/채널 대상을 요구합니다. Slack A1은 워크스페이스와 Entra 매핑으로 독립 운영할 수 있습니다. 서명 시각은 `decided_at`을 고정하고 정확한 재시도는 첫 감사 시각을 보존합니다. 워크플로 승인은 범위가 제한된 만료가 필요하며 Operator는 브로커가 수락한 뒤에만 전달 완료로 표시합니다. |
| 부트스트랩 및 수명 주기 자동화 | `in-progress` | [`llm_resolver_cli.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/llm_resolver_cli.py), `.github/workflows/deploy-dev.yml`, `.github/workflows/model-lifecycle-reconcile.yml` 및 집중 수명 주기 테스트 | 보호된 모델 해석, 제안 전용 조정, 수집기 일정, 통제된 발견 활성화 및 로컬 사람 승인 초기화가 구현됐습니다. 통제된 런타임 증적은 별도로 남아 있습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-13 | `implemented` | 성공한 각 T2 교차 검사 시작 증명을 프로세스의 후속 준비 상태 새로 고침에서 재사용하여 5분마다 다시 샘플링하지 않도록 했습니다. 실패 및 동시 시도는 안전하게 재시도됩니다. | 현재 변경의 `startup_model_probe.py` 및 `test_startup_probe.py`, 시작 탐색 집중 테스트: `18 passed` | 관리되는 배포 런타임 계측 근거를 수집하고 아래의 더 넓은 수명 주기 작업 흐름을 완료합니다. |
| 2026-08-19 | `implemented` | 보호된 Terraform 계획 전에 결정론적 실제 모델 해석을 실행하고, 정확한 매니페스트와 다이제스트를 적용까지 봉인했으며, 공급자 실패 시 판단을 보류하는 주간 초안 PR 조정기를 추가했습니다. | `current change`; 집중 수명 주기, 보호된 계획 검증기, Operator 서술기, Terraform 및 CI 보안 계약. | 통제된 조정기 실행을 보존하고 독립적인 수집기 및 사람 승인 workflow를 완료합니다. |
| 2026-08-19 | `implemented` | 검증된 수집기를 구성 가능한 Container Apps Job으로 예약하고, 기본적으로 닫힌 발견 활성화 집약기를 Norns의 비활성 후보 게시 경계에 연결했습니다. 근거가 누락되거나 오래되거나 실패하거나 중복되거나 사용할 수 없으면 정제된 사유 코드와 함께 게이트를 닫으며, 정책 비활성화는 카탈로그를 바꾸지 않습니다. | `current change`; 집중 준비 상태 활성화, 수집기 Job/CLI, 런타임 설정, 수집/감시, Norns, 시작 연결 및 인프라 검사. | 통제된 수집기 및 활성화 전이 증적을 보존하고 독립적인 사람 승인 작업 흐름을 완료합니다. |
| 2026-08-25 | `implemented` | 증가한 배포 감사 체인이 범위가 제한된 시작 탐색을 초과한 뒤 PostgreSQL 상태 도달 가능성과 전체 감사 체인 검증을 분리했습니다. 상태 접근과 감사 추가는 계속 프로세스 준비 상태를 차단하며, 완료되지 않은 체인 증명은 `autonomous-action`을 `shadow`로 강제하고 확인된 불일치는 준비 상태를 차단합니다. | `current change`; 시작 탐색, 집약기, 런타임 조립 및 집중 준비 상태 테스트: `43 passed`; Ruff와 영문/한글 문서 검사를 통과했습니다. | 모델 용량 변경 전에 대규모 감사 체인을 사용하는 정상 배포 Core 증적을 보존하고 영속 계측 쓰기 한 건을 증명합니다. |
| 2026-08-25 | `implemented` | 사용할 수 없는 알림 route 뒤에서 보호된 revision 두 개가 멈춘 뒤 영속 A2 incident 알림 replay를 readiness-critical bootstrap 순서에서 분리했습니다. Incident 상태는 계속 준비 상태 전에 재구성합니다. 격리된 worker는 전송 checkpoint를 유지하고 transient 전달 실패를 재시도하며 권한을 부여할 수 없습니다. | 실패한 보호 적용 `32833058288`; `current change`; 집중 bootstrap 테스트 59개와 strict mypy 통과. | 정확한 수정 Core 이미지를 빌드하고 배포한 뒤 정상 시작, replay 및 peer-isolation 근거를 보존합니다. |
| 2026-08-25 | `implemented` | 완료되지 않은 전체 감사 체인 증명 뒤에 5분의 프로세스 로컬 대기 시간을 추가했습니다. 시간 초과나 취소가 발생하면 즉시 과거 체인 스캔을 다시 시작하지 않고 자율 권한을 낮춥니다. 확인된 불일치는 계속 준비 상태를 차단하며, 이후의 제한된 재시도로 복구할 수 있습니다. | 실패한 보호 적용 `32846624686`; 준비 상태 확인 구간에서 PostgreSQL CPU 98.5~100%; `current change`; 집중 시작 탐색 테스트. | 제한된 재시도 동작을 배포하고 계량 검증 전에 정상 또는 저하된 관찰 모드 Core 근거를 보존합니다. |
| 2026-08-25 | `implemented` | 가장 이른 근거 만료 전에 주기적 준비 상태 새로 고침을 시작하고 조정기가 만든 실패 근거를 현재 및 다음 범위가 제한된 실행까지 유지했습니다. 새로 고침이 기존 만료 시점에 도달하면 보호된 처리를 계속 닫으므로 오래된 근거를 수락하거나 권한을 높이지 않고 가용성을 개선합니다. | 실패한 보호 적용 `32846624686`, 배포 보고서의 `degraded`, `postgres.state=passed` 및 살아 있는 replica에서 만료된 감사 시간 초과, `current change`, 집중 조정기 및 런타임 타이밍 테스트 | 정확히 수정된 Core 이미지를 배포하고 정상 또는 degraded-shadow revision과 peer 격리 근거를 보존합니다. |
| 2026-08-25 | `implemented` | 내장 탐색과 조정기 실패 근거 수명을 시작 예산 아래 통합하고, 최소 새로 고침 지연과 범위가 제한된 일시적 실패 재시도를 추가했으며, 정제된 탐색 id로 만료 전이를 관찰할 수 있게 했습니다. 이제 Thor는 새 자동 전달 전과 사람 승인 뒤에 실제 상한을 읽으므로 저하되거나 오래된 보고서가 시작 시점의 enforcement를 유지할 수 없습니다. | `current change`; 집중 준비 상태, 탐색, Thor 내구 및 bootstrap 검사 94개 통과, strict mypy, Ruff, Pantheon 레이아웃 및 에이전트 import gate 통과. | 정확한 수정 Core 이미지를 배포하고 degraded-shadow 전달, 만료 복구 및 peer 격리 근거를 보존합니다. |
| 2026-08-31 | `implemented` | 로컬 사람 승인 초기화를 완료했습니다. Operator는 별도 Teams 팀/채널 슬롯을 사용하고 Teams SSO OBO 및 독립 구성된 Slack 권한을 검증하며, 결정을 원래 문맥과 서명 시각에 바인딩하고, 첫 감사 시각을 보존하고, 제안 우선 영속화를 복구하고, 전달 완료 표시에 앞서 영속 보낼 편지함에서 게시합니다. 워크플로 승인 슬롯은 이제 범위가 제한된 콜백 문맥을 운반하며 시간 초과가 없으면 거부합니다. | `current change`, 집중 콜백, PostgreSQL IAM, Kafka, 조립, 워크플로, 거버넌스 및 카나리 검사, `uv run python scripts/operations/run-hil-bootstrap-canary.py`는 Teams 수락, Slack 거절, 시간 초과 시 차단, 감사 단계 6개, 잔존 레코드 0개, 실제 네트워크 호출 0개를 반환했습니다. | 런타임 검증을 주장하기 전에 통제된 배포 Teams 콜백, 브로커 수락 및 신뢰할 수 있는 거버넌스 App 증적을 보존합니다. |
| 2026-08-31 | `implemented` | 사람 승인 전달 고리를 닫았습니다. 이제 Teams 카드 클릭은 Operator Bot 액티비티 수신기에 도달하며, 수신기는 공유 결정 서비스가 실행되기 전에 Bot Framework 서비스 토큰과 구성된 테넌트, 팀, 채널, 그리고 위임 OBO 행위자 토큰을 검증합니다. Operator는 애플리케이션 lifecycle에 리스 펜싱 재구동 작업자도 소유하므로, 브로커 실패나 영속 보낼 편지함 기록 직후의 크래시를 HTTP 콜백 재시도 없이 재구동하고 브로커 수락 뒤에만 전달로 표시합니다. Core는 워크플로 승인 슬롯을 재개 코디네이터가 아니라 정족수 소유자로 라우팅합니다. | `current change`, 집중 Operator IAM, Teams 수신기, 보낼 편지함 재구동, PostgreSQL, 조립, Core chatops 및 교차 서비스 라우팅 검사, `uv run python scripts/operations/run-hil-bootstrap-canary.py`는 `mode=local_dry_run_no_network`, `live_teams_proof=false`, 실제 네트워크 호출 0개를 반환했습니다. | 런타임 검증을 주장하기 전에 통제된 배포 Teams 콜백 증적과 브로커 수락 증적을 보존합니다. |

### 남은 작업

- [x] 집중 콜백, 권한, 시간 초과, 중복, 감사, 거버넌스 및 카나리 검사로 결정론적 로컬
   사람 승인 초기화를 완료합니다.
- [x] 카드 클릭과 실패한 브로커 게시가 모두 운영자 개입 없이 완료되도록, 저장소 소유 Teams
   Bot 액티비티 수신기와 리스 펜싱 결정 보낼 편지함 재구동 작업자를 조립합니다.
- [ ] 사람 승인 행을 `validated`로 변경하기 전에 고정된 개정 번호에서 통제된 배포 Teams
   콜백 증적과 신뢰할 수 있는 거버넌스 App의 차단 후 통과 증적을 하나씩 보존합니다. 로컬
   카나리는 명시적인 네트워크 없는 예행이며 이 증적을 대체할 수 없습니다.
- [ ] 후보별로 성공한 T2 시작 샘플 세트가 한 번만 실행되고, 해당 프로세스의 이후 5분 준비
   상태 새로 고침에서는 T2 호출이 추가되지 않음을 보여 주는 관리되는 배포 런타임 계측을 기록합니다.
- [ ] 기존 대규모 감사 체인이 강제 적용 권한을 부여하지 않고 healthy 또는 degraded-shadow
   개정 번호를 만드는 배포 Core 준비 상태 보고를 보존한 다음, 프로비저닝된 모델 용량을
   변경하기 전에 영속 계측 쓰기 한 건을 독립적으로 검증합니다.

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
| 상태와 정책 | PostgreSQL 연결 및 상태 읽기, 감사 추가, 전체 감사 hash-chain 검증, 비상 정지 읽기, 카탈로그 부하, OPA compile |
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

근거 수명은 최소 5분이며, 그보다 길면 최대 전체 실행 시간과 탐색 시간 제한 하나를 더한 값의 두
배입니다. 새로 고침은 같은 전체 실행 및 탐색 예산만큼 가장 이른 만료 전에 시작하여 최대 실행 뒤에도
탐색 시간 제한 하나만큼 최신성을 남깁니다. 이미 기한이 지난 작업은 hot loop를 막기 위해 최소 1초를
기다리고, 일시적 실패는 15초 이내에 재시도합니다. 기존 만료 시점에는 처리를 닫고 완전한 보고서가
근거를 교체할 때까지 만료된 탐색 id만 포함하는 정제된 경고 하나를 내보냅니다. 성공한 T2 교차 검사,
감사 내구성 및 전체 체인 증명은 작업을 반복하지 않고 새 근거 시각을 받습니다. 완료되지 않은 전체
체인 증명은 PostgreSQL 포화를 피하도록 다음 스캔 전에 5분 동안 기다립니다. 확인된 불일치는 계속
차단되며 복구는 배포 권한을 높이지 않습니다.

### 실패와 권한 규칙

- **Process-critical**: 잘못된 구성, 토큰/시크릿 실패, PostgreSQL 상태 접근 실패, 감사 추가 실패, 확인된 감사 hash-chain 불일치, 정책 compile 실패 또는 필수 Kafka 실패는 `/ready`를 닫습니다.
- **Authority-critical**: 완료되지 않은 전체 감사 hash-chain 검증, 읽을 수 없는 비상 정지, 누락된 T2 검증 또는 사용 불가 승인은 shadow나 사람 승인을 강제합니다. Core는 관찰과 복구를 위해 계속 사용할 수 있지만 검증되지 않은 자동 액션을 활성화하지 않습니다.
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

`/live`는 프로세스 생존을 별도로 보고합니다. `blocked`이면 `/ready`는 `503`을 반환하고 보호되는
작업은 중지 상태를 유지합니다. `degraded` 보고는 `/ready`를 열 수 있지만 감사 체인 증명을 사용할
수 없으면 `autonomous-action`을 `shadow`로 낮춥니다. Thor는 자동 전달 전과 사람 승인 직후 실행기
I/O 전에 실제 상한을 읽습니다. 누락되거나 오래되거나 차단되거나 새로 고침에 실패한 보고서는 시작
시점의 enforcement를 유지하지 않고 shadow를 강제합니다. 주기적 새로 고침은 process-critical
의존성이 차단되면 보호되는 작업을 중지하고 권한 승격 없이 복구 후 다시 시작합니다.

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
`tools/seed_p1_manifest.yaml`을 함께 제공합니다. 포크는 이를 고객별 값 없이 그대로 사용하거나
포크 소유 오버레이/시드를 추가할 수 있습니다. 루트 Terraform 변수
`rule_watcher_cron_expression`은 출처, 테넌트, 엔드포인트, 구독 또는 고객 값을 포함하지 않고
배포 일정을 연결합니다. 작업은 검증과 함께 감시기를 실행하고 파서/스키마 검증 및 정확한 출처
검증을 통과한 뒤에만 영속 성공 증적을 기록합니다. 증적에는 확인된 개정 번호, 내용 해시,
라이선스, 재배포 방식, 검증된 규칙 수 및 검증 시각이 포함됩니다. 이 증적이 없는 가져온
스냅샷은 성공한 수집이 아니며 다시 시도할 대상으로 남습니다.

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
   (`fdai.change.events`, `fdai.dr.events`, `fdai.finops.events`, 그리고 그들의 `<topic>.dlq`
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

> **현재 경계**: Operator 콜백은 API 대상 Entra 검증기를 통해 Teams SSO OBO와 Slack
> 브라우저 토큰을 검증하고, 현재 Approver 권한을 다시 해석하며, 별도로 구성된 그룹 연결
> 팀과 채널에서 Teams 대상을 파생하고, BreakGlass 분리를 보존하며, 2단계 감사 레코드를
> 기록합니다. 로컬 카나리는 결정론적이며 공급자를 호출하지 않습니다. 테넌트 값,
> Conditional Access, 공급자 자격 증명 및 통제된 런타임 증적은 배포 입력으로 남습니다.

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
5. Core와 Operator에 같은 `FDAI_TEAMS_APPROVAL_TEAM_ID` 및
   `FDAI_TEAMS_APPROVAL_CHANNEL_ID`를 제공하고 Core에 `FDAI_TEAMS_APPROVAL_ACTIVITY_URL`과
   채널 주체 매핑을 제공합니다. 5개 Entra 그룹 id는 역할
   슬롯에만 사용합니다. Teams는 구성된 봇에 발급되고 콜백 행위자 및 해당 팀/채널 대상에
   바인딩된 API 대상 OBO 토큰만 수락합니다. Operator의 영속 보낼 편지함이 브로커 수락을
   받은 뒤 실행기는 형식화된 결정만 받습니다.
6. **Slack 워크스페이스 프로비저닝** (P1 A1 채널): FDAI Slack 앱 설치, `chat:write`
   부여, 필수 Slack userId ↔ Entra OID 매핑 저장소 채움; 매핑이 비어 있지 않을 때까지 Slack
   어댑터는 A1 트래픽 거부
   ([channels-and-notifications-ko.md#7-channel-specific-notes](../interfaces/channels-and-notifications-ko.md#7-channel-specific-notes)).
7. `config/notifications-matrix.yaml`의 A1 기본 및 대체 경로 변경을 재정의와 같은 검토
   엄격도로 커밋합니다. 거버넌스 CI는 서로 다른 권한 보유 검토자 2명을 요구하고 제안자,
   공동 작성자 또는 커미터의 승인을 차단합니다.
8. 카드 클릭이 완료될 수 있도록 Teams Bot 수신기 입력을 제공합니다.
   `FDAI_TEAMS_TENANT_ID`, `FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON`, `FDAI_TEAMS_JWKS_URL`을 넣고,
   Operator 경로 `POST /hil/teams-activity`를 봇 메시징 endpoint로 등록합니다.
   입력이 모두 갖춰질 때까지 Teams A1은 닫혀 있습니다.
9. `uv run python scripts/operations/run-hil-bootstrap-canary.py`를 실행합니다. 범위가 제한된
   로컬 카나리는 조립된 Teams 액티비티 수신기, 서명된 내부 콜백, 공유 결정 서비스, 영속 보낼
   편지함, 리스 펜싱 재구동 작업자를 in-process 가짜 구현으로 구동합니다. 결과는
   `mode=local_dry_run_no_network`와 `live_teams_proof=false`이며, 이는 조립 예행이지 실제
   Teams, Entra 또는 브로커 증적이 아닙니다.

## 자율 발견 루프 시동

[자율 규칙 발견 루프](../rules-and-detection/rule-catalog-collection-ko.md#autonomous-rule-discovery)는
**첫날에 비활성화됩니다**. `discovery.enabled`는 기본값이 `false`인 감사 가능한 런타임 정책
설정이고, `discovery.shadow_decision_threshold`는 구성된 최소 결정 수입니다. 이 선호 설정을
활성화하는 것만으로 루프가 활성화되지는 않습니다. 순수 활성화 집약기는 다음의 최신 근거가 모두
존재할 때까지 루프를 비활성 상태로 유지합니다.

1. 실행 중인 판테온이 최소 **`N` shadow 결정**을 관측하여 관찰 단계에 실제 기준선을
   제공합니다. `N`은 설정할 수 있으며, 권장값은 아직 결정되지 않았지만 수천 단위가
   적절합니다. 프로세스를 다시 시작하면 이 보수적인 카운터가 초기화되므로 임계값을 다시
   관측할 때까지 게이트가 닫힙니다.
2. 최소 하나의 컬렉터가 성공 실행(배선 + 출처 이력 증명).
3. Mixed-model 교차 검사 대상과 결정론적 검증기가 건강.
4. Post-deploy smoke 테스트가 green
   ([operating-and-verification-ko.md](operating-and-verification-ko.md#post-deploy-smoke-테스트-계약)).

집약기는 결정, 구성된 임계값, 근거 시각 및 정제된 사유 코드를 포함하는 바이트 안정 보고서 하나를
기록합니다. 누락되거나 만료되거나 실패한 근거는 구체적인 사유 코드를 만들며 루프를 일부만
활성화할 수 없습니다. 런타임은 최신 보고서를 로컬에 유지하고, 조정기는 결정, 사유 집합 또는
구성된 임계값이 바뀌는 의미 있는 전이만 저장하고 감사합니다. 따라서 재생과 재시작에서 활성화
기록이 중복되지 않습니다.

런타임은 이 결정을 Norns의 `RuleCandidate` 게시 경계에만 주입합니다. Norns는 비활성 상태에서도
범위가 제한된 오프패스 패턴을 계속 축적할 수 있지만, 게이트가 활성화되기 전에는 후보를 Mimir에
게시할 수 없습니다. 게시 후에도 후보는 기존 품질, 승인, 회귀 및 shadow 우선 승격 게이트가
수락할 때까지 비활성 상태입니다. 활성화와 정책 비활성화 모두 카탈로그 항목을 편집하거나
승격하거나 제거하지 않습니다.

루프 비활성화는 코드 변경이 아니라 **정책 토글**입니다. 다음 평가가 게시 게이트를 닫고,
반복되는 재정의 신호는 이후 활성화를 위해 계속 축적됩니다.

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
- [x] 예행 실행 HIL 절차: `scripts/operations/run-hil-bootstrap-canary.py`가 범위가 제한된
      합성 페이로드로 조립된 Teams 액티비티 수신기, 서명된 내부 콜백, 공유 결정 서비스, 영속
      보낼 편지함, 리스 펜싱 재구동 작업자를 구동하고, 종단 결과, 감사 개수, 잔존 레코드 없는
      정리 및 자신의 `local_dry_run_no_network` 모드를 보고합니다.
