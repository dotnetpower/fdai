---
title: Console 읽기 경계
translation_of: console-read-boundary.md
translation_source_sha: 3aa1de477173f436e24ff903912c06c688c7d08e
translation_revised: 2026-08-18
---
# Console 읽기 경계

이 문서는 FDAI Console의 로컬 및 배포 읽기 출처 계약을 소유합니다. 출처 선언, 인증,
워크로드 근거 및 인벤토리 조회를 권위 있고 읽기 전용인 상태로 유지하며 Operator API에 실행기
신원을 부여하지 않습니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 읽기 데이터 소스 선언 완전성 | validated | `fdai_operator_service/composition.py`, `console/src/routes/dashboard.loading.ts`, 각 집중 테스트(`49 passed`, `3 passed`), 그리고 Overview 6개 화면 인증 실행에서 오류 알림 0건과 실패만 가능한 요청 0건 | 콘솔이 조회하는 모든 읽기 route는 이 배포판이 제공하지 않는 route까지 포함해 `/system/data-sources`에 선언됩니다. 생산자가 없는 측정 화면은 값을 합성하지 않고 unavailable로 선언합니다. |
| 카탈로그 기반 참조 projection | validated | `test_materialize_authoritative_catalogs.py`, 인증된 Workflow builder 및 Agent oversight 로드 | 검토된 ActionType, Workflow 및 담당 체계 선언이 런타임 또는 액션 근거를 만들지 않고 읽기 projection에 도달합니다. |
| 사용 불가 화면 표현 | validated | 집중 Operator 및 Console 검사와 영향받는 패널의 인증 통과 | 제공되지 않는 route는 서버가 소유한 사유를 유지하며 패널은 날것 전송 상태나 존재하지 않는 구성 심볼을 노출하지 않습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 잔여 작업 |
|------|------|------|------|-----------|
| 2026-08-18 | validated | 이 focused owner가 Console 읽기 경계를 소유하도록 채택하고 현재 범위, 잔여 작업 및 규범적 읽기 계약을 초대형 동등성 문서에서 옮겼습니다. | `current change`; 이전 구현 전환 6개는 `dev-and-deploy-parity-ko.md`에 변경 없이 남아 있으며 focused 문서, 번역, route 및 크기 게이트가 통과합니다. | Operator API 권한을 넓히지 않고 아래의 관측 가능한 항목을 완료합니다. |

### 잔여 작업

- [ ] onboarding 프로브, configuration baseline 및 conversation delivery 기능을 서비스 경계
  안에서 재구축할지 결정합니다. 분리 이전 route는 Core provider를 직접 import했으며 독립 서비스
  경계가 이를 더 이상 허용하지 않습니다.
- [ ] `operator-projection:workflow:promotion-gate.list` projection을 구현하거나 폐기합니다.
  workflow family가 이를 읽어 `/kpi/promotion-gates`가 `503`을 반환하지만 이 배포판의 어떤
  구성 요소도 이 projection을 기록하지 않습니다.

## 설계 개요

Console은 각 선택적 읽기 전에 서버가 소유한 선언된 출처를 확인합니다. 누락되거나 승인되지 않은
근거는 사용 불가 상태를 유지하고, 로컬 및 배포 프로파일은 같은 제한과 읽기 전용 권한을 보존합니다.

## 출처 선언

읽기 데이터 소스 레지스트리는 이 배포판이 제공하지 않는 route까지 포함해 콘솔이 조회하는 모든
route를 선언합니다. 콘솔은 요청을 보내기 전에 route를 선언된 소스로 해석하므로, 선언되지 않은
route는 이 확인을 건너뛰고 실패만 가능한 요청을 보내게 되며 패널은 빈 화면에 대한 서버 제공
사유를 잃습니다. 따라서 생산자가 없는 화면은 생략하거나 합성 값으로 답하지 않고 사유와 함께
unavailable로 선언하며, 콘솔은 이렇게 선언된 unavailable을 페이지 실패가 아니라 선택적
projection으로 처리합니다. 패널은 운영자에게 보이는 메시지로 날것 전송 상태를 표시하지 않으며,
unavailable 화면은 선언된 사유 또는 자체 카탈로그 문구를 보여줍니다.

## 로컬 인증

정본 로컬 Operator API는 `FDAI_OPERATOR_API_LOCAL_ENTRA=1`을 사용하고 배포와 route-owned 런타임
보조 로직을 공유합니다. 브라우저가 API 토큰을 얻고 API는 배포와 동일하게 JWT 및 App 역할을
검증합니다. 서버의 Azure CLI 토큰은 Resource Graph, Microsoft Graph, 모델 발견 및 Event Hubs
같은 Azure 어댑터로 제한됩니다. `FDAI_OPERATOR_API_LOCAL_AZURE_CLI=1`과
`VITE_LOCAL_AZURE_CLI_AUTH=1` 조합은 고정 역할 상한을 사용하는 명시적 CLI-principal debug
대안입니다.

## 워크로드 근거

로컬 Kubernetes 워크로드 근거는 명시적 선택이며 서버가 소유합니다. `FDAI_LOCAL_KUBECONFIG`,
`FDAI_LOCAL_KUBERNETES_CONTEXT` 및 `FDAI_LOCAL_KUBERNETES_CLUSTER_NAME`을 함께 설정하면 하나의
고정된 읽기 전용 `kubectl` 조회를 연결합니다. 배포 또는 Pod 근거가 AKS 답변의 커버리지를
완료하려면 클러스터 이름이 Azure 인벤토리 결과와 일치해야 합니다. 세 값이 모두 없으면 워크로드
커버리지는 명시적으로 사용 불가 상태를 유지하며, 일부만 설정된 연결은 암묵적 현재 맥락을
사용하는 대신 시작에 실패합니다.

## 인벤토리 조회

로컬 및 deployed 인벤토리 변환 결과는 같은 두 조회 모드를 사용합니다. `scope=<view-id>`는
결정론적 named 아키텍처 화면을 선택합니다. 이 모드와 함께 사용할 수 없는 rooted 모드는
`root=<resource-id>`, `depth=1..8`, `limit=1..1000`으로 하나의 양방향 neighborhood를 반환합니다.
알 수 없는 루트는 `404`를 반환하고 상한에 도달하면 `truncated=true`로 표시합니다. 로컬 Azure
CLI 프로바이더는 권위 있는 cached 스냅샷에 동일한 제한을 적용하며 deployed PostgreSQL
프로바이더는 활성 스냅샷과 real-time 오버레이 내부에 적용합니다. 어느 프로파일도 rooted 요청을
완전한 인벤토리로 확장하지 않습니다. Deployed 프로바이더는 유효 그래프를 하나의
repeatable-read, 읽기 전용 트랜잭션에서 읽으며, 두 프로파일 모두 같은 깊이의 frontier 리소스를
결정론적 순서로 round-robin 확장합니다. Named-view 요청은 기존 3-argument 프로바이더 호출
계약을 유지하며 rooted 요청만 확장 키워드를 요구합니다. Relationship-filter 개수와 텍스트
length는 프로바이더 전달 전에 제한합니다. 읽기 경로는 malformed 리소스, 알 수 없음 또는
dangling 관계, 중복 리소스 id, 잘못된 잘림 메타데이터 및 oversized 프로바이더 출력을
차단합니다. 두 프로파일은 중첩된 AKS `powerState.code`를 포함한 관찰된 operational 상태를
프로비저닝 상태로 대체하지 않고 보존합니다. 로컬 캐시 묶음 v13은 스냅샷을 만든 Azure CLI/ARG
명령의 strict 민감정보가 제거된 증적을 기록합니다. 이전 묶음은 프로바이더 실행 상세를 노출하기
전에 새로 고침합니다. Command Deck 인벤토리 턴은 해당 스냅샷에 IQL을 적용하며 질문마다
프로바이더 명령을 다시 실행했다고 주장하지 않습니다.

Rooted 출력은 요청된 리소스 상한과 이에 대응하는 간선 상한을 사용하고, named 화면은 기존
5,000-resource 및 40,000-link 응답 상한을 유지합니다. 두 프로파일은 리소스, adjacent-edge,
internal-edge 및 출처 상한으로 구성된 같은 잘림 사유 vocabulary를 노출합니다. 읽기 경로는 알 수
없는 사유와 non-truncated 페이로드에 붙은 사유를 차단합니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 나머지 로컬 및 배포 런타임 동등성 | [런타임 동등성](dev-and-deploy-parity-ko.md) |
| Console 권한과 읽기 화면 | [Operator Console](../interfaces/operator-console-ko.md) |
| 사람 신원과 App 역할 | [사용자 RBAC 및 신원](../interfaces/user-rbac-and-identity-ko.md) |
