---
title: 운영 계획 하드닝 근거
translation_of: operational-planning-hardening.md
translation_source_sha: 5fab35c025e280f1be1d8bacffcb16f76e9c9fc1
translation_revised: 2026-08-14
---
# 운영 계획 하드닝 근거

이 문서는 운영 계획의 구현 및 적대적 검토 근거를 기록합니다. 구현된 shadow 동작과 적용
승격 전에 필요한 release 근거를 구분합니다.

> **범위:** 검토 대상은 타입이 지정된 logic asset, 결정론적 선택, 전문가 근거, 샌드박스 및 twin
> 시뮬레이션, 영속 프로세스 기록, 실행 인계, 계획 수립 Room, 런타임 가용성, 범위가 제한된
> 입력입니다.
>
> **결과:** 12개의 독립적인 검토 라운드 이후 알려진 Medium, High 또는 Critical 결함은 없습니다.
> 남은 항목은 Low release-readiness 공백이며 계획 수립이 shadow 모드에 머물기 때문에 권한을
> 높일 수 없습니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 계획, 시뮬레이션, 내구성 및 인계 동작 | implemented | [구현 근거](#구현-근거), [검토 라운드](#검토-라운드) | 12개 적대적 검토 라운드는 실행 권한을 부여하지 않는 집중 구현 및 회귀 근거를 보존합니다. |
| 고정 시나리오 범위 | in-progress | [잔여 위험](#잔여-위험) | 부분 실행 복구가 명시적인 release 근거 대체 항목을 사용하므로 매니페스트는 `partial`로 남아 있습니다. |
| 실패 시 차단되는 실제 shadow 관찰 | validated | [실제 운영 shadow 증명](#실제-운영-shadow-증명) | 보존된 2026-08-03 관찰은 변경 0건인 부적격 결과를 재현했습니다. 이는 적용 모드를 검증하지 않습니다. |
| 적용 모드 준비 상태 | not-started | [잔여 위험](#잔여-위험) | Protected-runner 복구, 운영 그래프 Dynamic 근거 및 운영 실행기 연결은 미완료입니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-14 | in-progress | 이전 출처 이력을 재구성하지 않고 구현 원장을 도입하고 검증된 shadow 근거와 적용 모드 준비 상태를 분리했습니다. | `current change`; 이 문서의 검토 라운드, 실제 shadow 증명 및 잔여 위험 근거입니다. | 아래의 세 release 근거 종료 조건을 완료해야 합니다. |

### 남은 작업

- [ ] Protected-runner 부분 실행 복구 훈련을 완료하고 인증된 보상, 독립 종결, 롤백 및
    정리 증적을 보존합니다.
- [ ] 운영 그래프 Dynamic 근거를 하나의 정확한 온톨로지 release에 연결하고 완전한 비합성
    계획 증적을 보존합니다.
- [ ] 운영 `ops.scale-out` 실행기를 연결하고 승격 검토 전에 14일 동안 정책 이탈 0건과
    검증된 롤백 순서를 포함한 100개 실제 shadow 샘플을 보존합니다.

## 한눈에 보는 설계

캠페인은 구현된 계약에서 재현되는 발견 사항만 인정했습니다. 확인된 Medium 이상 발견 사항에는
focused 회귀 테스트와 별도 강화 커밋을 추가했습니다. 제안 근거를 실행
권한으로 오해한 발견 사항은 불필요한 코드를 추가하지 않고 기각했습니다.

## 구현 근거

| 기능 | 근거 |
|------------|------|
| Logic 신원 및 권한 확인 | 정본 release가 타입이 지정된 함수를 고정하고 호출은 에이전트, 역할, 용도, 입력 스키마, 산출물 다이제스트, 결정론적 시드를 검사합니다. |
| 결정 계획 수립 | Hard 제약이 Pareto pruning 및 기존 weighted 중재보다 먼저 적용됩니다. No-action 기준선과 rejected 사유는 변경할 수 없는 상태를 유지합니다. |
| 에이전트 collaboration | 기존 전문가 토픽이 선택적 Forseti 조정기에 근거를 제공합니다. Direct 에이전트 호출, 새 에이전트 또는 shared 변경 가능한 작업 흐름 상태를 추가하지 않았습니다. |
| 시뮬레이션 | 검토된 programmatic 파이프라인과 활성/challenger twin 모델이 타입이 지정된 증적을 생성합니다. 누락, malformed, stale 또는 divergent 근거는 계획을 보류합니다. |
| 내구성 | 기존 작업 흐름 및 프로세스 스냅샷과 추가 전용 하위 이벤트가 멱등적 재생으로 계획 수립 단계를 기록합니다. |
| 실행 인계 | 선택한 옵션은 exact 대상 및 release 신원을 가진 proposal-only MutationPlan으로 compile됩니다. Risk, 승인, 실행, 복구, 감사는 분리되어 있습니다. |
| 효과 종결 | 성공을 닫기 전에 선택된 옵션, MutationPlan, ResponseOutcome prediction id가 하나의 exact 체인을 구성합니다. |
| Product 표면 | 기존 프로세스 경로가 strict 읽기 전용 계획 수립 Room 변환 결과를 제공합니다. 변경 경로 또는 실행기 신원을 추가하지 않습니다. |
| 런타임 연산 | 시작은 하나의 변경할 수 없는 기능 상태에서 가용성, 활성화, shadow 모드, 사유, 누락 선행 조건을 기록합니다. |

## 검토 라운드

| 라운드 | 초점 | 결과 |
|-------:|------|------|
| 1 | 에이전트 권한 및 separation of duties | 권한 bypass가 없습니다. MutationPlan compilation은 proposal-only 산출물이므로 액션 실행이라는 주장을 기각했습니다. |
| 2 | 결정론적 재생 | 후보, 효과, 증적 순서를 고정해 동등한 입력이 byte-identical 사례와 계획을 생성합니다. |
| 3 | Constitutional 제약 | 누락, stale, 충돌 또는 review-required 맥락이 ineligible이 되어 중재에 도달하지 못함을 확인했습니다. |
| 4 | 동시 확산 및 후보 enumeration | 전문가 도메인 집합을 제한하고 hard 상한 초과 후보는 잘림하지 않고 실패하도록 확인했습니다. |
| 5 | Compute 샌드박스 격리 | 검토된 출처 다이제스트, 생성된 클라이언트, 기능 토큰, 도구 허용 목록, 시간 초과, 바이트 상한, 자격 증명 없음, 일반 네트워크 없음을 확인했습니다. |
| 6 | Twin 근거 및 모델 재생 | 동등한 활성/challenger 입력이 하나의 고정된 시뮬레이션 증적을 만들도록 효과 정렬을 수정했습니다. |
| 7 | 프로세스 내구성 및 동시성 | PostgreSQL child-event 재생을 atomic 멱등성 충돌 처리와 하나의 발신함 winner로 수정했습니다. |
| 8 | 실행 및 결과 계보 | 종결을 exact 선택된 계획, ActionType, MutationPlan, prediction id에 결속했습니다. |
| 9 | 계획 수립 Room security 및 responsive 배치 | Strict 디코딩, 상관관계 검사, 읽기 전용 라우팅, 액션 컨트롤 없음 여부를 확인하고 좁은 화면의 cell wrapping을 추가했습니다. |
| 10 | 고정된 시나리오 truthfulness | 매니페스트를 부분으로 낮추고 두 release-evidence proxy를 명시했습니다. |
| 11 | 런타임 observability 및 성능 저하 | 구조화된 기능 상태를 추가했습니다. 누락된 선택적 근거 연결은 표시되며 관련 없는 에이전트 작업을 차단하지 않습니다. |
| 12 | 대상 연결 및 adversarial 한계 | 계획을 고정된 대상에 결속하고 목표, 효과, 제약, 시뮬레이션, 텍스트, 전체 중첩된 근거 매니페스트에 산출물 생성 전 한도를 적용했습니다. |

## 실제 운영 shadow 증명

2026-08-03에 범용 non-production Azure Container App을 대상으로 읽기 전용 관측을
수행했습니다. 허용 목록에 포함된 상태 필드만 canonicalize했으며 리소스 이름, 계정 식별자,
엔드포인트, 신원, 시크릿 참조 또는 raw 배포 페이로드는 저장소에 포함하지 않았습니다.

관측 대상에는 현재 개정 번호와 준비된 개정 번호가 충돌하는 근거가 있었습니다. 따라서 운영 계획은
`held_no_eligible_option` 사유의 `ineligible` 평가를 생성했고 선택된 옵션과 실행 시도는
없었습니다. 두 번째 읽기는 같은 허용 목록에 있는 상태 다이제스트를 생성했습니다. 이 증명은 실패 시 차단 실제 운영
근거 처리와 Azure 변경 0건을 보여 주며 성공적인 적용 훈련을 주장하지 않습니다.

## 잔여 위험

고정된 시나리오 매니페스트는 하나의 명시적 proxy 때문에 `partial` 상태를 유지합니다.

- **부분 실행 복구:** 계약 테스트는 mismatched 결과를 검증된 롤백으로 닫지만,
  전용 non-production partial-execution 훈련은 release 근거로 남아 있습니다. 범위가 제한된
  계약과 protected-runner 명령은
  [OHL Scale-Out 근거 Runbook](../../runbooks/ohl-scale-out-evidence-ko.md)에 준비되어 있습니다.

A0 planning 및 제공되는 irreversible `ops.scale-out` ActionType이 이제 명시적인 A3-E
non-applicability 근거를 제공합니다. 남은 완료 gate에는 protected-runner live drill,
production graph Dynamic evidence binding 및 production `ops.scale-out` executor binding이
필요합니다. Provider-side Azure CLI drill만으로는 FDAI end-to-end 실행 근거가 되지 않습니다.

이 공백은 실행을 활성화할 수 없으므로 제공되는 shadow 기능에서는 Low입니다. 검증된 시나리오
근거로 교체되기 전까지 향후 적용 승격을 차단합니다. 기능 상태, shadow 모드, 기존 risk 경로,
고정된 observation 및 recurrence window, 정책 escape 0건 요구 사항은 계속 권한을 가집니다.

## 검증

Focused 검증 범위에는 operational-planning subsystem, 고정된 매니페스트 및 Lane F config
schema, scale-out planning, twin 및 outcome 계약, protected-runner command 계약, translation
최신성, punctuation 및 차이 hygiene가 포함됩니다. 중앙 통합 검증은 merge boundary의
정본으로 유지됩니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 운영 계획 설계 | [운영 계획](operational-planning-ko.md) |
| 에이전트 소유권 및 중재 | [에이전트 Pantheon](../agents/agent-pantheon-ko.md) |
| 읽기 전용 그래프 시뮬레이션 | [Assurance Twin](../operations/assurance-twin-ko.md) |
