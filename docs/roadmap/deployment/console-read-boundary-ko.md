---
title: Console 읽기 경계
translation_of: console-read-boundary.md
translation_source_sha: 746bcf9d0fbb9bc070de99e38d1cf027f4c2c92b
translation_revised: 2026-10-01
---
# Console 읽기 경계

이 문서는 FDAI Console의 로컬 및 배포 읽기 출처 계약을 소유합니다. 출처 선언, 인증,
워크로드 근거 및 인벤토리 조회를 권위 있고 읽기 전용인 상태로 유지하며 Operator API에 실행기
신원을 부여하지 않습니다.
## 설계 개요

Console은 각 선택적 읽기 전에 서버가 소유한 선언된 출처를 확인합니다. 누락되거나 승인되지 않은
근거는 사용 불가 상태를 유지하고, 로컬 및 배포 프로파일은 같은 제한과 읽기 전용 권한을 보존합니다.

전체 출처 레지스트리는 하나의 목적별 조립 소유자에 두고, 경로 계열 조립은 다른 소유자에 둡니다.
운영 파사드는 인증, 브리지 배선 및 준비 상태를 유지합니다. 기존 가져오기, 가용성 값, 영속 출처
주장 및 실행기 없음 경계는 바뀌지 않습니다.

## 출처 선언

설정의 모델 검색은 읽기 전용 구성 조회이며 워크로드 조회나 모델 호출이 아닙니다.
HTTP 경로에서 Azure를 직접 호출하면 권한 검증과 공급자 처리가 섞이므로 IAM 조립이 기존 설정
조회에 범위가 제한된 카탈로그 읽기 모듈을 주입합니다. 구성된 구독과 모델 엔드포인트에서 계정
하나를 확인한 뒤 계정 모델, 배포 및 지역 할당량을 읽고 결과를 1분 동안 보관합니다.
명시적 새로 고침은 캐시를 건너뜁니다. 오류가 발생하면 오래된 결과를 최신으로 표시하지 않고
사용 불가로 전환합니다. 카탈로그 존재나 배포 성공은 실행, 모델 선택 또는 적용 권한을 부여하지 않습니다.

명시적으로 승인된 로컬 선택은 `scripts/deployment/local/bind-existing-model.py`를 사용합니다.
5분 이내에 관측한 성공 상태 배포 하나를 Git에서 제외된 파일에 연결하며 정확한 이전 파일과
T1 및 독립 검토자를 보존합니다. 모델을 배포하거나 호출하지 않으며 관측하지 않은 도구 또는
스키마 지원을 단정하거나 누락된 T2 검증 정족수를 활성화하지 않습니다.

읽기 데이터 소스 레지스트리는 이 배포판이 제공하지 않는 route까지 포함해 콘솔이 조회하는 모든
route를 선언합니다. 콘솔은 요청을 보내기 전에 route를 선언된 소스로 해석하므로, 선언되지 않은
route는 이 확인을 건너뛰고 실패만 가능한 요청을 보내게 되며 패널은 빈 화면에 대한 서버 제공
사유를 잃습니다. 따라서 생산자가 없는 화면은 생략하거나 합성 값으로 답하지 않고 사유와 함께
unavailable로 선언하며, 콘솔은 이렇게 선언된 unavailable을 페이지 실패가 아니라 선택적
projection으로 처리합니다. 패널은 운영자에게 보이는 메시지로 날것 전송 상태를 표시하지 않으며,
unavailable 화면은 선언된 사유 또는 자체 카탈로그 문구를 보여줍니다.

`ontology-instances` 출처는 `/ontology/instances`, `/ontology/instances/explore` 및
`/ontology/instances/states`를 묶습니다. 구성 여부는 일반 운영 읽기 모델과 독립적으로 인벤토리
계열 저장소를 따릅니다. 두 실행 환경은 같은 변경 불가 인벤토리 세대를 읽으며, 저장소를
구성하지 않으면 명시적으로 사용 불가 상태가 됩니다. 권위 있는 출처를 구성했다는 선언은
레코드의 출처를 나타낼 뿐, 각 기록이 최신임을 의미하지 않습니다. Dashboard v2와 온톨로지
인스턴스 화면은 [기록 상태 계약](../interfaces/recorded-resource-state-ko.md)을 통해 이 구분을 유지합니다.

## 워크플로 정의 및 Python 작업 기능

워크플로 빌더는 Operator 서비스가 구체화된 `state_kv` 변환 결과 대신 자체 상태에서 응답하는
두 가지 출처를 읽습니다.

| 경로 | 작업 | 출처 |
|------|------|------|
| `GET /workflows/definitions` | `workflow-definition.list` | Operator가 소유한 `workflow_definition` 및 `workflow_binding` 테이블을 직접 읽음 |
| `GET /python-tasks/capabilities` | `python-task.capabilities` | Operator 조립 구성이 연결한 Python 작업 담당 구성 요소 보고 |

정의 카탈로그는 다음 범위 규칙을 따릅니다.

- `global` 정의는 인증된 모든 principal에게, `private` 정의는 소유자에게만 표시됩니다. 팀 구성원
  출처가 연결되기 전까지 `team` 가시성은 제외됩니다.
- 업스트림 정의는 **Built-in**, 호출자 자신의 정의는 **Mine**, 그 밖에 표시되는 정의는
  **Shared**로 묶입니다. Shared 항목은 소유자 참조를 공개하지 않습니다.
- 바인딩은 호출자 자신의 자동화 설정으로 제한됩니다.
- Operator 역할은 `operator_workflow_definition_read_20260929` 서비스 마이그레이션을 통해 SELECT
  전용 권한을 받습니다. 읽기 모듈은 각 쿼리 뒤에 가시성과 소유권 검사를 다시 수행하므로, 조건절
  회귀가 생겨도 다른 principal의 레코드를 공개하지 않고 읽기가 실패합니다.

기능 보고는 `available: false`, `unavailable_reasons` 및 모든 작업의 비활성화 상태를 HTTP `200`으로
반환합니다. 독립 Operator는 Python 작업 검증기, VM 작업 실행기, 아티팩트 저장소, 작성기, 실행
제출기 또는 일정 저장소를 연결하지 않습니다. Operator는 VM Run Command 신원을 보유하지 않으며,
Core의 `FDAI_VM_TASK_ENABLED` 실행기 연결이 있어도 이 작성 작업은 사용할 수 없습니다.
Console은 Python 작업 작성 컨트롤을 숨기고 보고된 사유를 상태 메시지로 알립니다.

변환 결과 생산자 대신 직접 읽기를 선택한 이유는 두 가지입니다.

- 정의와 바인딩은 리포지토리 카탈로그가 아니라 principal이 소유한 영속 레코드입니다. 공유 변환
  결과는 principal별 키 공간, 모든 쓰기에 대한 새로 고침 및 별도의 격리 증명이 필요합니다. 요청
  시점의 읽기는 사용자 컨텍스트 및 대화 보증 읽기처럼 인증된 principal과 현재 저장소 상태에
  결속됩니다.
- 경로를 제공하는 조립 구성에서 도출한 기능 보고는 Operator가 제공하지 않는 작업을 광고할 수
  없습니다.

저장소에 연결할 수 없거나, 권한이 없거나, 레코드가 잘못되었거나, principal 범위 밖의 레코드가
있거나, 정의 또는 바인딩이 200개를 넘으면 명시적인 사유와 함께 HTTP `503`을 반환합니다. 저장소가
비어 있으면 출처가 명시된 빈 카탈로그를 반환합니다. 로컬 및 배포 조립은 같은 읽기 모듈을
사용하며, 로컬 준비와 배포는 같은 Operator 서비스 마이그레이션을 적용합니다. 아직 이 테이블을
채우는 런타임 writer는 없습니다. 정의 및 바인딩 경로는 아무도 소비하지 않는 비활성 shadow
제안을 대기열에 넣고, 기본 제공 정의는 시드되지 않습니다.
[#1655](https://github.com/dotnetpower/fdai/issues/1655)가 writer를 연결하기 전까지 카탈로그는 저장소에
이미 있는 레코드만 나열하며, 서비스 분리 이후 생성된 데이터베이스에는 그런 레코드가 없습니다.

## 로컬 인증

정본 로컬 Operator API는 `FDAI_OPERATOR_API_LOCAL_ENTRA=1`을 사용하고 배포와 route-owned 런타임
보조 로직을 공유합니다. 브라우저가 API 토큰을 얻고 API는 배포와 동일하게 JWT 및 App 역할을
검증합니다. 서버의 Azure CLI 토큰은 Resource Graph, Microsoft Graph, 모델 발견 및 Event Hubs
같은 Azure 어댑터로 제한됩니다. 표준 준비는 비공개 Vite 값이 오래되어도 이 Browser Entra
모드를 선택합니다. 명시적 CLI-principal 디버그 대안이 필요할 때만
`prepare-operator-service-env.sh --auth-mode azure-cli`를 사용합니다. 이 대안의 역할 상한은
`Contributor`로 고정되므로 `Approver` 또는 `Owner`가 필요한 승인 상세를 열 수 없습니다.
생성된 API 환경은 `FDAI_OPERATOR_API_LOCAL_AZURE_CLI`와
`FDAI_OPERATOR_API_LOCAL_AZURE_CLI_CONFIRM`을 함께 설정합니다. 두 값 중 하나만 사용해 API를
직접 시작하면 구성 검증에서 실패합니다. 브라우저도
`VITE_LOCAL_AZURE_CLI_AUTH`와 `VITE_LOCAL_AZURE_CLI_AUTH_CONFIRM`에 같은 쌍 규칙을 적용합니다.
두 값이 일치하지 않으면 principal을 조용히 바꾸지 않고 Console 시작을 중단합니다.

비용 거버넌스의 로컬 검토도 인증을 유지합니다. 명시적인
`FDAI_COST_GOVERNANCE_AUTHENTICATED_REVIEW_ACCESS` 프로필은 검증된 principal에 공개 제어를 적용한
집계 검토를 허용하지만 JWT 검증, 역할 확인, 원시 신원 억제, 패키지 활성화 또는 작업 권한을
우회하지 않습니다. 소유자 gate가 적용된 설정 경로만 exact-revision 활성화 선호를 변경할 수
있습니다.

헤더 계정 패널은 표시에 MSAL 표시 이름과 사용자 이름을 사용하고 검증된 FDAI 역할에는
`GET /iam/self`를 사용합니다. 다른 계정을 선택하면 로그인 힌트 없이 Entra 계정 선택기를
시작합니다. 리디렉션은 일반 시작 과정으로 돌아오며, 운영자 셸을 표시하기 전에 토큰을 얻고
`GET /iam/self`를 다시 확인합니다. 이 흐름은 구성된 테넌트 안에서 유지됩니다. 콘솔과 API가
하나의 구성된 발급자를 사용하므로 디렉터리 전환은 지원되지 않습니다.

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
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/deployment/console-read-boundary.md) |
| 나머지 로컬 및 배포 런타임 동등성 | [런타임 동등성](dev-and-deploy-parity-ko.md) |
| Console 권한과 읽기 화면 | [Operator Console](../interfaces/operator-console-ko.md) |
| 사람 신원과 App 역할 | [사용자 RBAC 및 신원](../interfaces/user-rbac-and-identity-ko.md) |
