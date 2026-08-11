---
translation_of: service-decomposition-execution-plan.md
translation_source_sha: 15d7f2486a6ea5cebda906ff66ce07d9317849c1
translation_revised: 2026-08-11
---
# 서비스 분해 실행 계획

이 문서는 FDAI를 독립 배포 가능한 5개 런타임 서비스로 전환하는 구현 진행 상태를 추적합니다.
이 문서를 리팩터링의 지속 가능한 진행 기록으로 사용하며, 상세 설계는 각 아키텍처 문서에서
관리합니다.

> **목표:** 5개 서비스가 각각 독립 항목 지점, 상태 검사, 신원, 타입이 지정된 전송 계층을
> 갖추어야 프로그램을 완료합니다. 실행기 게이트를 충족하지 못하면 목표를 다시 4개로 줄이지 않고
> 전체 완료를 차단합니다.
>
> **안전:** 검사된 항목은 exit 근거가 존재한다는 의미입니다. 계획 문구, 패키지 이동 또는
> 단위 테스트 통과만으로 프로세스 경계의 권한 전환 준비를 증명할 수 없습니다.

## 설계 개요

FDAI는 이 프로그램을 5개 런타임 서비스로 완료합니다. 처음 4개 역할은 이미 존재하지만 내부
패키지와 배포 경계를 계속 강화해야 합니다. 다섯 번째 서비스는 Thor 소유 실행을
Core에서 분리하여 Isolated 실행기만 mutation-capable 워크로드 신원을 보유하게 합니다.

| # | 런타임 서비스 | 목표 responsibility | Ingress | 실행기 권한 |
|---|-----------------|---------------------|---------|--------------------|
| 1 | Core 컨트롤 평면 | 에이전트 런타임, decisioning, 승인 결합, 감사 의도, 복구 coordination | 내부 이벤트 버스 | 전환 후 없음 |
| 2 | Operator 서비스 | 인증된 조회, 대화, 변환 결과, 통제된 요청 제출 | 외부 HTTPS와 이벤트 버스 | 없음 |
| 3 | 문서 인제스트 API | 인증된 업로드 intake와 API 소유 문서 전이 | 외부 HTTPS와 이벤트 버스 | 없음 |
| 4 | 문서 처리 워커 | 영속 점검, 추출, 인덱싱, 점유, 조정 | 내부 이벤트 버스와 탐색 | 없음 |
| 5 | Isolated 실행기 | Thor 소유 명령 검증, 대상 잠금, 프로바이더 효과, 롤백 시도, 실행 증적 | 내부 이벤트 버스와 탐색 | 유일한 보유자 |

온톨로지, Rule 카탈로그, Rego 빌드 파이프라인, Console, scheduled 작업, 15개 에이전트는 이 프로그램에서
별도 서비스가 되지 않습니다. 각 소유 런타임 서비스 안에서 계약, 패키지, static 클라이언트,
작업 또는 독립 실행 가능한 이벤트 구독자로 유지합니다.

## 상태 요약

| 상태 | 개수 | 의미 |
|------|------|------|
| 완료 | 10 | SD-00부터 SD-09까지 exit 근거와 focused 검증을 기록했습니다. |
| 진행 중 | 0 | 활성 service-decomposition 작업 패키지가 없습니다. |
| 계획됨 | 0 | 계획 상태의 service-decomposition 작업 패키지가 없습니다. |
| 차단됨 | 0 | 현재 차단된 작업 패키지가 없습니다. |

마지막 업데이트: 2026-08-10.

## 실행 checklist

| 완료 | ID | 작업 패키지 | 의존성 | 병렬 레인 | Exit 근거 |
|------|----|--------------|------------|-----------|---------------|
| [x] | SD-00 | 정본 문서와 머신 매니페스트에서 5개 서비스 토폴로지, 소유자, 계약, 쓰기 담당, 신원, 기준선 테스트, 롤백 단위를 고정합니다. | 없음 | 직렬 | 검토된 토폴로지와 소유권 기록, 기준선 검사 증적 |
| [x] | SD-01 | JSON, SSE, authentication, 이력 행동을 변경하지 않고 Operator 경로 계열을 전송 계층, 애플리케이션, 변환 결과, 어댑터, 스트리밍, 영속성 패키지로 분해합니다. | SD-00 | A | 고정된 경로 계약과 package-boundary 검사 |
| [x] | SD-02 | Core 조립, Thor 실행, Saga 감사 의도와 종결, Vidar 복구를 명시적으로 주입된 포트 뒤로 분리합니다. | SD-00 | A | 권한 회귀와 import-boundary 증적 |
| [x] | SD-03 | 인제스트 API와 워커 신원, 데이터베이스 권한 부여, 점유, 중복/reorder 행동, 재시작 복구, 탐색, co-host 롤백을 강화합니다. | SD-00 | A | 역할 테스트와 15분 이내 롤백 예행 연습 |
| [x] | SD-04 | 정본 온톨로지 release 배포, exact 참조 pinning, N/N-1 호환성, projection-writer 소유권, mismatch 거절, 재생, 롤백을 추가합니다. | SD-00 | B | 서비스 간 온톨로지 호환성과 의미 회귀 증적 |
| [x] | SD-05 | 정본 AST analysis부터 카탈로그 빌드, 의미 검증, 온톨로지/vector 세대, incremental 동등성, exact applicability, evaluation, 통제된 feedback까지 Rego knowledge 경로를 구축합니다. | SD-04 | B | Query-to-exact-Rego 계약 테스트와 세대 롤백 증적 |
| [x] | SD-06 | 정본 변경 계보, 프로바이더 어댑터, 결정 추적, 전달/결과 결합, 복원력 커버리지, 후보 전용 learning, 읽기 전용 Operator 변환 결과를 추가합니다. | SD-02, SD-04, SD-05 | C | 재생 가능한 계보와 권한 non-escalation 증적 |
| [x] | SD-07 | 효과 권한 없이 Isolated 실행기 명령과 증적 계약, 영속 시도 mechanics, 그림자 소비자, 상태, 텔레메트리, 신원, Container App을 구현합니다. | SD-02, SD-04 | C | 중복, reorder, 재시작, 기한, 잠금, 그림자 증적 |
| [x] | SD-08 | 변경 권한을 Isolated 실행기로 전환하고 Core에서 실행기 역할을 제거하며 독립적인 효과를 검증하고 프로세스 내 토폴로지 복귀를 예행 연습합니다. | SD-07 | 직렬 | Effective-access 증명, exact-topology smoke, timed 롤백 증적 |
| [x] | SD-09 | 만료된 호환성 경로를 제거하고 경계를 강제 적용하며 정본 문서를 업데이트하고 centralized stable-batch 검증을 실행한 뒤 잔여 작업을 종료합니다. | SD-01부터 SD-08 | 직렬 | Exact 커밋 범위의 green 검증 증적 |

## 독립 서비스 추출

완료한 SD 프로그램은 배포된 프로세스 5개와 상태, 전송 계층, 신원 경계를 증명합니다. 이제 IS
프로그램은 이 5개 역할을 독립적으로 빌드하고 release할 수 있게 만듭니다. 완료하려면 Python
분포, 이미지, Terraform 루트, 이행 가지 및 독립 업그레이드/롤백 증명이 각각 5개여야
합니다. 서비스는 다른 분포에서 versioned shared 계약, 프로바이더 프로토콜 및 텔레메트리
기본 요소만 가져오기할 수 있으며 다른 서비스 구현 가져오기는 지원하지 않습니다.

### 최종 리포지토리 레이아웃

IS 프로그램은 리포지토리 소유권이 런타임 소유권과 일치해야 완료됩니다. 각 서비스는 하나의 서비스
루트 아래에서 구현, 단위 테스트, 빌드 정의 및 Python 분포를 소유합니다.
리포지토리 루트에는 서비스 간 통합 테스트와 workspace orchestration만 남고 두 번째
애플리케이션 패키지는 남지 않습니다.

```text
fdai/
├── services/
│ ├── core-control-plane/
│ │ ├── docker/Dockerfile
│ │ ├── services/core-control-plane/src/fdai/
│ │ ├── src/fdai_core_service/
│ │ ├── services/core-control-plane/tests/
│ │ └── pyproject.toml
│ ├── operator-service/
│ │ ├── docker/Dockerfile
│ │ ├── src/fdai_operator_service/
│ │ ├── services/core-control-plane/tests/
│ │ └── pyproject.toml
│ ├── document-ingestion-api/src/fdai_ingestion_api_service/
│ ├── document-processing-worker/src/fdai_document_worker_service/
│ └── isolated-executor/src/fdai_executor_service/
├── packages/
│ └── service-contracts/
│  ├── src/fdai_service_contracts/
│  ├── services/core-control-plane/tests/
│  └── pyproject.toml
├── services/core-control-plane/tests/
│ └── integration/
└── pyproject.toml
```

- **서비스 루트:** `services/<service>/`는 5개 런타임 서비스의 유일한 구현 및 unit-test
 소유자입니다. 서비스별 Dockerfile은 해당 서비스 분포만 빌드합니다.
- **Shared 패키지:** `packages/service-contracts/`에는 versioned wire 계약, 프로바이더 프로토콜 및
 텔레메트리 기본 요소만 둡니다. Business logic, 조립, 데이터 접근 또는 다른 서비스의 어댑터는
 포함하지 않습니다.
- **루트 workspace:** 루트 `pyproject.toml`은 workspace 구성원과 개발 tooling을 조정합니다.
 `package = false`로 설정되며 monolithic FDAI 애플리케이션 분포를 publish하거나
 install하지 않습니다.
- **서비스 간 테스트:** 루트 `tests/integration/`은 wire 호환성과 deployed 작업 흐름을
 검증합니다. 단위 테스트와 컴포넌트 테스트는 소유 서비스로 이동합니다.
- **폐기할 호환성 트리:** 최상위 `src/fdai/`, shared multi-target 서비스 Dockerfile, 이전 방식
 서비스 항목 지점 및 중복 계약 정의는 이행 전용 산출물입니다. IS-08에서 먼저 로컬로
 제거한 뒤, 최종 service-owned 출처를 사용해 IS-07의 이미지 기반 N/N-1 롤백을 증명합니다.
 Checked-in 이전 방식 출처 트리 대신 Git 이력과 변경 불가능한 이전 이미지를 롤백 방식으로
 사용합니다.

| 완료 | ID | 작업 패키지 | 의존성 | Exit 근거 |
|------|----|--------------|------------|---------------|
| [x] | IS-00 | 현재 implementation-import debt와 정확한 패키지, 이미지, 상태, 이행, 롤백 목표를 고정합니다. | 없음 | 머신 매니페스트와 non-growth 게이트 |
| [x] | IS-01 | 서비스 구현이 없는 versioned shared 계약 SDK를 추출합니다. | IS-00 | 소비자 5개가 같은 SDK를 install하고 validate한 증적 |
| [x] | IS-02 | 독립 실행 가능한 서비스 분포와 조립 루트 5개를 추가합니다. | IS-01 | 독립 휠 및 cold-start 증적 5개 |
| [x] | IS-03 | 서비스 간 구현 가져오기를 모두 제거합니다. | IS-01, IS-02 | 가져오기 개수 0과 enforced 경계 게이트 |
| [x] | IS-04 | 영속 쓰기 담당 권한 부여와 이행 가지를 서비스별로 분리합니다. | IS-02 | 이행 헤드 5개와 쓰기 담당 overlap 0 |
| [x] | IS-05 | 최소 서비스 이미지 5개를 빌드, 검사, attest, publish합니다. | IS-02, IS-03 | 변경할 수 없는 이미지, SBOM, 시작 증적 5개 |
| [x] | IS-06 | Shared platform에서 서비스 Terraform 루트, 상태 및 배포 작업 흐름을 분리합니다. | IS-04, IS-05 | 로컬 루트 5개, 격리된 백엔드 계약, 상태 소유권 검사 및 peer-isolation mechanics 통과 |
| [x] | IS-07 | 각 서비스의 N/N-1 계약과 독립 업그레이드/롤백을 증명합니다. | IS-03, IS-06, IS-08 | 로컬 N -> N-1 -> N 산출물 전이 5개와 peer-stable focused 증적 10개 통과 |
| [x] | IS-08 | 구현, 단위 테스트, 빌드 정의 및 분포를 5개 서비스 루트 아래로 이동하고 최상위 monolith 출처, 중복 계약, co-host, 프로세스 내 권한, shared-image 및 shared-migration 호환성 경로를 제거합니다. | IS-03, IS-05 | 최종 리포지토리 레이아웃이 문서의 트리와 일치하고 최상위 운영 출처 및 토폴로지 호환성 경로 수가 0 |
| [x] | IS-09 | 최종 리포지토리 레이아웃을 강제 적용하고 독립 critique-and-hardening 라운드를 10회 이상 실행한 뒤 프로그램을 종료합니다. | IS-07, IS-08 | 배치 및 가져오기 게이트 통과, Medium 이상 잔여 0, 보류한 원격 검증 통과 |

머신 정본은 `config/independent-services.json`입니다. 각 이행 wave는 같은 focused
커밋에서 상태와 근거를 업데이트합니다. Shared Event Hubs, PostgreSQL hosting, ACR, Key Vault,
networking 및 observability는 platform 리소스로 유지하지만 logical 소유권, 자격 증명, 스키마,
이행 이력, 배포 상태 및 롤백은 서비스별로 분리합니다.

IS-06과 IS-07은 로컬 executable 근거로 종료하여 배포 환경을 기다리지 않고 구현을
진행합니다. Exact 원격 계획/적용, peer-drift 및 rolling 증적은 IS-09가 소유하는 별도 program-final
검증 게이트입니다. 최종 검증이 실패하면 관련 패키지를 다시 열고 프로그램 종료를
차단합니다. 로컬 근거는 실제 운영 배포 결과를 주장하지 않습니다.

승인된 IS-00 AST 기준선은 `fdai.core`를 가져오기하는 Operator 파일 140개, 인제스트 파일 5개,
isolated 실행기 파일 2개입니다. 이 값은 허용된 대상 의존성이 아니라 이행 debt입니다.
Non-growth 게이트는 증가를 차단하고 이후 작업 패키지는 모든 개수를 0으로 줄입니다.

IS-01/02는 구현이 없는 계약 휠 1개와 고유 콘솔 항목 지점을 가진 서비스 휠
5개를 생성했습니다. 첫 조립 루트는 행동을 변경하지 않기 위해 기존 FDAI 구현을
의도적으로 lazy 가져옵니다. 래퍼 가져오기 5개는 명시적인 IS-03 debt이며 최종 출처 independence
근거가 아닙니다.

IS-03은 래퍼와 5개 서비스 분포의 모든 서비스 간 구현 가져오기를 제거했습니다.
로컬 IS-08에서 Core는 서비스 루트 아래의 `src/fdai`와 `src/fdai_core_service`를 물리적으로 소유합니다.
나머지 서비스 4개는 service-local 구현과 계약 SDK만 포함합니다. 각 서비스는 테스트와
`docker/Dockerfile`을 소유하고, 루트 workspace는 패키지를 만들지 않는 orchestration 전용이며,
`tests/integration`에는 서비스 간 검사만 남습니다. 루트 및 shared multi-target Dockerfile, 이전 방식
항목 지점, 중복 계약과 범용 인제스트 co-host 경계는 제거되었습니다.

로컬 완료 근거에는 독립 빌드 휠 6개, nonroot 서비스 이미지 5개, 이미지 상태 검사 5개,
104개 표와 11개 전이를 포함하는 검증된 이행 가지 5개, 로컬에서 validate한 Terraform
루트 5개, 서비스 간 구현 가져오기 0, 그리고 독립 critique-and-hardening 108회와 Medium 이상
로컬 잔여 0이 포함됩니다. IS-06과 IS-07은 로컬 기준으로 완료됐습니다. Exact 원격
계획/적용과 rolling 확인은 IS-09로 보류하며 최종 service-owned
입력을 사용하고 monolith를 롤백 출처로 복원하지 않습니다. IS-09는 deployable 분포
`0.1.2` 이미지를 N-1, 분포 `0.1.3`을 N으로 고정하고 기존 contract-set `1.0.0`/`1.1.0` 매트릭스를 유지합니다.

Protected 서비스 배포는 변경할 수 없는 산출물 출처 이력과 execution-control 출처 이력을
분리합니다. 대상 `commit_sha`는 protected `main`의 어떤 ancestor도 될 수 있으므로 증명된
N-1 이미지를 롤백 예행 연습에 사용할 수 있습니다. 작업 흐름 자체, 모든 배포 컨트롤
스크립트, Terraform 루트, 서비스 이행 및 peer-state 입력은 항상 현재 protected `main`에서
가져오고, exact 계획/적용 재생은 두 실행 사이의 컨트롤 변경을 거부합니다. 이미지 빌드와 계획은
실행기 자리 5개에서 병렬 실행할 수 있지만 evidence-bearing 적용은 각 서비스 증적이 나머지
peer 상태 4개가 그대로였음을 증명할 수 있도록 직렬 실행합니다.

## 병렬 실행 규칙

- **레인 A:** SD-00 후 owned 경로가 겹치지 않으면 Operator, Core 경계, 인제스트 작업을
 별도 워크트리에서 실행할 수 있습니다.
- **레인 B:** 온톨로지 경계 강화는 패키지 작업과 겹쳐 실행할 수 있습니다. Rego
 세대는 정본 온톨로지 release와 의미 검증을 기다립니다.
- **레인 C:** 변경 계보와 실행기 그림자 구현은 shared 계약, pantheon 역할 파일,
 조립, infrastructure 신원 파일을 하나의 serial 통합 소유자가 관리할 때만
 겹쳐 실행할 수 있습니다.
- **Serial 결합:** Shared 계약, 쓰기 담당 전환, 운영 조립, 신원 전환,
 롤백 예행 연습, stable-batch 검증은 경쟁 세션에서 실행하지 않습니다.

## 병렬 세션 충돌 방지

2개 이상의 writing 세션이 활성 상태일 때 각 동시 세션은 편집 전에 작업 패키지,
가지 또는 워크트리, owned 경로, 해제 조건을 예약합니다. 두 번째 세션은 현재 예약과 대상
워크트리의 dirty 및 미병합 경로를 먼저 확인합니다. 서로 다른 가지를 사용하더라도 owned 경로가
하나라도 겹치면 인계를 기다립니다. 단일 interactive 쓰기 담당 또는 serial 통합 소유자는
기본적으로 기본 `main` 워크트리에서 작업합니다.

- **독점 경로:** 세션은 예약한 경로만 편집합니다. 다른 세션 예약에 포함된 dirty,
 untracked, renamed 또는 미병합 파일은 정리, format, 충돌 해석 또는 부수적인
 refactoring 대상으로 사용하지 않습니다.
- **통합 소유자:** 한 명의 serial 통합 소유자가 이 계획 문서 쌍,
 `config/service-decomposition.json`, 패키지 간 shared 계약, pantheon 역할 파일,
 운영 조립, 신원 전환을 관리합니다. 패키지 전용 infrastructure는
 인계 전까지 해당 패키지 소유자가 관리합니다.
- **인계:** Owner는 focused 커밋, 검증 증적, 잔여 작업을 기록한 후에만 경로
 예약을 해제합니다. 통합 소유자가 cherry-pick, 병합, 상태 변경, 의존성 해제를
 수행하며 워커 세션은 이 결합과 경쟁하지 않습니다.
- **검증 격리:** 워커는 자신이 커밋한 차이 또는 예약한 워크트리만 검증합니다.
 다른 세션의 dirty 트리에서 changed-file 선택자를 실행하지 않습니다.
- **Persistent 워크트리:** 동시 구현 워커는
 `/home/moonchoi/dev/fdai-worktrees/` 아래의 경로를 사용합니다. 과거 등록만으로 활성
 세션이라고 판단하거나 새 워크트리를 만들지 않습니다. 호스트 재시작이나 정리로 인계
 근거 통합 전에 워크트리가 제거될 수 있으므로 새 동시 예약에 `/tmp`를 사용할 수
 없습니다.

| 예약 | 현재 소유자 | 예약 경로 | 해제 조건 |
|------|------------|-----------|-----------|
| SD-01 completed 경로 종결 | `main`의 통합 소유자가 관리하며 retired 워커 헤드는 `refs/archive/worktrees/20260811/` 아래에 보존합니다. | 예약된 출처 경로가 없습니다. Formal 검토에서 `e141ab07e`이 해당 행동을 애플리케이션 소유자로 이동했음을 확인하여 stale `chat_route_common.py` 산출물을 통합 대상에서 제외했습니다. Exact non-integrated 상태는 `refs/archive/worktrees/20260811-reviewed/sd01-route-closure`에 보존합니다. | Transport-only 경로 소유권, 애플리케이션 수명 주기 소유권, 변경되지 않은 wire 행동, reverse 가져오기 0이 focused 검증과 독립 검토를 통과한 후 완료하고 해제했습니다. |
| SD-03 completed effective 접근과 롤백 | `main`의 통합 소유자가 관리하며 이전 워커 헤드는 `refs/archive/worktrees/20260811/` 아래에 보존합니다. | 예약된 출처 경로가 없습니다. | 실제 운영 effective-access 증명과 2초 롤백 예행 연습을 수락하고 구현 예약을 해제했습니다. |
| SD-06 completed 계보 | `main`의 통합 소유자가 관리하며 이전 워커 헤드는 `refs/archive/worktrees/20260811/` 아래에 보존합니다. | `d4e430d60` 후 모든 SD-06 구현 경로를 해제했습니다. | 정본 계보, 프로바이더 호환성, 결정/복원력 추적, 후보 전용 learning, 범위가 제한된 Operator 변환 결과 및 비평 라운드 14회가 focused 검증을 통과하고 Medium 이상 잔여가 없음을 증명합니다. 실행 및 승격 권한은 0을 유지합니다. |
| SD-07 completed 그림자 실행기 | `main`의 통합 소유자가 관리하며 이전 워커 헤드는 `refs/archive/worktrees/20260811/` 아래에 보존합니다. | `aa89b0bf1` 후 모든 SD-07 구현 및 image-admission 경로를 해제했습니다. | Exact protected 적용, healthy 그림자 개정 번호, canary, 변경할 수 없는 증적, digest-bound 이미지 admission, 비평 라운드 11회 및 focused 검증이 통과했고 효과 권한은 0을 유지합니다. |
| SD-08 완료 권한 전환 | `main`의 통합 소유자가 관리하며 이전 워커 헤드는 `refs/archive/worktrees/20260811/` 아래에 보존합니다. | Closing 커밋 후 예약된 출처 경로가 없습니다. | Exact 전환/롤백 계획, 독립적인 효과, 연속 오프셋, healthy 서비스 5개, no-op convergence, 정리 및 timed 증적을 수락했습니다. |
| Serial 통합 | 통합 소유자 | 이 계획 문서 쌍, 머신 상태 매니페스트, 패키지 간 계약, 운영 조립, pantheon 역할, 실행기 신원 전환 | Focused 패키지 인계를 수락하고 의존성 상태를 업데이트 |

## 진행 상태 업데이트 계약

작업 패키지의 상태를 바꾸는 focused 커밋에서 이 문서를 함께 업데이트합니다. 각 상태 전환에서
다음을 수행합니다.

1. 상태 요약 개수와 `마지막 업데이트` 날짜를 변경합니다.
2. Exit 근거가 존재할 때만 항목을 검사합니다.
3. 근거 로그에 커밋과 focused 검사 증적을 추가합니다.
4. 차단 요인을 소유 게이트와 다음 disconfirming 검사와 함께 기록합니다.
5. 의존성 또는 잔여 권한 전환이 열려 있으면 상위 항목을 완료하지 않습니다.

## 근거 로그

| 날짜 | 작업 패키지 | 상태 | 커밋 또는 증적 | 근거와 잔여 작업 |
|------|--------------|------|-------------------|--------------------------|
| 2026-08-07 | SD-00 | 완료 | `config/service-decomposition.json` at `95bd58718` | 5개 서비스 목표와 work-package DAG를 승인했습니다. 기준선 묶음은 918 passed와 PostgreSQL 전용 건너뜀 2건을 기록했으며 실제 운영 검사는 SD-03과 SD-05가 소유합니다. |
| 2026-08-07 | SD-01 | 진행 중 | 시작 `ccfa3c3dd` | 첫 Operator 구획으로 claims-family 패키지 이동을 시작했습니다. |
| 2026-08-07 | SD-02 | 진행 중 | 시작 `ccfa3c3dd` | Thor 실행 포트와 증적 계약 분리를 시작했습니다. |
| 2026-08-07 | SD-03 | 진행 중 | 시작 `ccfa3c3dd` | 인제스트 신원과 storage-role 검증을 시작했습니다. |
| 2026-08-07 | SD-04 | 진행 중 | 시작 `ccfa3c3dd` | 서비스 간 온톨로지 release 호환성 게이트를 시작했습니다. |
| 2026-08-07 | SD-02 | 완료 | `2a82507cb`, `7e15ba084`, `7a48288cb` | Shared 실행 인스턴스, 영속 Saga 감사 준비 상태, Vidar 복구 준비 상태, normal 전달, HIL 재개를 명시적 조립 근거로 고정했고 union 테스트 122개가 통과했습니다. |
| 2026-08-07 | SD-04 | 완료 | `f5cf51e3a`, `91c88f2a3`, `a5350296e`, `b24c2d90d`, `07161a96c` | Exact release 참조, 가산 N/N-1 호환성, revision-fenced 변환 결과 쓰기 담당, 프로바이더 I/O 전 mismatch 거절, replay-stable atomic 세대 롤백이 focused union 테스트 142개를 통과했습니다. `FDAI_DATABASE_URL`이 설정되지 않아 PostgreSQL 실제 운영 사례 8개는 건너뜀 상태이며, 기준선은 이 실제 운영 세대 증적을 SD-05에 할당합니다. |
| 2026-08-07 | SD-05 | 완료 | `1c9ce4e94`부터 `d211570c6`, `b24c2d90d`, `4f01a02e8` | 정본 AST 매니페스트, promoted 표면, held-out evaluation, concept-first exact Rule 참조, atomic 세대, 롤백 및 통제된 feedback을 완료했습니다. Focused 경로 테스트 105개와 수명 주기 테스트 43개가 통과했고 PostgreSQL 세대 및 동등성 테스트 12개가 건너뜀 없이 실행됐습니다. 수집은 `execution_authority: false`를 유지하며 SD-06 의존성을 시작할 수 있습니다. |
| 2026-08-07 | SD-06 | 진행 중 | 시작 `74694b6ca` | Persistent core-only 워커가 변경할 수 없는 정본 변경 계보 구획을 소유합니다. Shared 계약을 추가하거나 Operator, 인제스트, 실행기, 조립, infrastructure 경로를 변경하지 않고 기존 `ChangeRecord`, `ChangeAssessment`, `DecisionCase`, `ResponseOutcome` 신원을 재사용합니다. |
| 2026-08-07 | SD-06 | 진행 중 | `3fcf91880` | 첫 정본 계보 구획이 `ChangeRecord`, `ChangeAssessment`, 선택한 `DecisionCase` 옵션, `Action`, `ResponseOutcome`을 하나의 변경 불가능하고 replay-stable한 기록으로 연결합니다. 상관관계, 대상, ActionType, 다이제스트, 신원, causal-order 불일치를 차단하고 근거 참조를 canonicalize하며 실행 및 승격 권한을 0으로 고정합니다. Ruff, strict mypy 및 focused 테스트 7개가 워커와 `main`에서 각각 통과했습니다. 프로바이더, 복원력, candidate-learning, 읽기 전용 Operator 결합은 남아 있습니다. |
| 2026-08-07 | SD-06 | 진행 중 | `9f1c3be30`, `b2fd7401b`, `bcf9c701f` | 변경 불가능한 복원력 및 결정 추적이 실행 모드, 영향 범위, 롤백 계약, 효과 시각, 복구 결과, 목표 점수, protected 목표, 제약, 승인 요구사항, 선택된 효과, reasoning 증적을 계보 신원에 결합합니다. 잘못된 관측 구간과 모호한 점수 신원은 실패 시 차단합니다. 추적 값과 경계 테스트를 책임별로 분리했으며 출처 파일은 260줄과 196줄입니다. Ruff, strict mypy 및 focused 패키지 테스트 11개가 워커와 `main`에서 통과했습니다. 프로바이더, candidate-learning, 읽기 전용 Operator 결합은 남아 있습니다. |
| 2026-08-07 | SD-06 | 진행 중 | `c64834b3a`, `52dbb2ba3` | 결정론적 계보 learning 변환 결과는 inert하며 별도로 sealed된 operational 사례를 요구하고 `operational_reuse_eligible: false`를 보고하며 실행 및 승격 권한을 0으로 고정합니다. 공개 GitHub 및 Azure DevOps `ChangeFeed.recent()` 출력이 mock 전송 계층을 통해 정본 계보와 후보 추출을 모두 통과했으므로 중복 코어 어댑터를 추가하지 않았습니다. Ruff, strict mypy 및 focused 패키지 테스트 16개가 `main`에서 통과했습니다. Core-only 예약은 해제했으며 읽기 전용 Operator 변환 결과는 SD-01 경로 인계를 기다립니다. |
| 2026-08-07 | SD-06 | 진행 중 | 변환 결과 시작 `2ecd7a36c` | SD-01 기능 패키지가 통합됐습니다. 새 persistent 워커는 pure `projections/change_lineage` 패키지와 focused 테스트만 소유합니다. HTTP 경로를 register하거나 앱, 영속성, 조립, 코어, SD-01 경로 예약을 변경할 수 없습니다. Projected 후보가 sealed 사례 없이 reusable해지거나 0이 아닌 권한을 노출하거나 unbounded 출처 데이터를 유출하거나 Starlette/routes를 가져오기하면 이 구획을 반증합니다. |
| 2026-08-07 | SD-06 | 진행 중 | `e76874409`, 변환 결과 인계 | 고정된 요약 및 상세 화면이 정본 계보를 후보 봉인과 권한 0에 결합하고 oversized 신원을 거부하며 display 사유와 근거를 명시적으로 제한하고 raw 프로바이더 내용을 생략합니다. 변환 결과 테스트 4개, Operator 경계 게이트, Ruff, strict mypy가 통과했습니다. 결합된 계보/변환 결과 union 테스트 20개가 통과했습니다. 구현 예약은 해제했습니다. 다음 반증 검사는 SD-01 conversation-persistence 인계 후 충돌 없는 module-map 소유권 및 HTTP 등록 검토입니다. |
| 2026-08-07 | SD-06 | 진행 중 | 강화 시작 `96c959429` | Persistent isolated 워커가 해제된 SD-06 출처와 focused-test 경로만 소유하고 비평 라운드를 10회 이상 수행합니다. 재현 가능한 각 Medium 이상 defect는 focused fix, 테스트, 커밋 하나로 처리하며 검증된 false 긍정 라운드는 운영 편집 없이 기록합니다. 최종 완료는 독립 Low-only 잔여 검토를 요구합니다. |
| 2026-08-07 | SD-06 | 진행 중 | 강화 라운드 9 범위 | GitHub `ChangeFeed.recent()`는 aware 정규화된 배포 시각과 naive 조회 한계를 비교할 때 `TypeError`를 발생시켰고 Azure DevOps peer는 같은 한계를 UTC로 정규화합니다. 소유되지 않은 GitHub 어댑터 파일을 재현된 동등성 fix에 한해 이 워커에 추가하며 다른 프로바이더 경로는 읽기 전용으로 유지합니다. |
| 2026-08-07 | SD-06 | 완료 | `f83c82f62`부터 `d4e430d60`, Low-only 검토 | 비평 라운드 14회에서 재현 가능한 계보/후보 다이제스트 위조, causal 시각 누락, 평가 근거 손실, outcome-effect 불일치, selected-option 충돌, 복원력 시각 우회, 변환 결과 신원/개수/사유 메타데이터 공백 및 GitHub naive-window 실패를 수정했습니다. Impossible-state 또는 의도된 never-raising 권한 점유 2건은 false 긍정으로 기각했습니다. 최종 독립 검토는 Medium 이상 잔여가 없음을 확인했습니다. Exact `main`에서 Ruff, strict mypy, Operator 경계 게이트 및 focused 계보/변환 결과/프로바이더 테스트 43개가 통과했습니다. Low 잔여는 malformed GitHub 시각의 실패 시 차단 silent 건너뜀, authorized 상세 변환 결과의 내용 다이제스트 노출 및 400줄 참고용을 1줄 넘는 계보 모델입니다. |
| 2026-08-07 | SD-01 | 진행 중 | `f220eb06f`, `2739e2be6`, `7c18ed513`, `0ab723835`, `64955ba87` | 스트림 메트릭, 최종 변환 결과, post-generation orchestration, 애플리케이션 기능 소유권, 인증된 요청 preparation을 명시적 애플리케이션 또는 변환 결과 패키지 뒤로 이동했습니다. 최신 request-preparation union 테스트 192개가 통과했고 애플리케이션/변환 결과 reverse 가져오기 개수는 0이며 scoped 경계 게이트는 green입니다. JSON, SSE, authentication, 취소, 이력 wire 행동은 경로가 계속 소유합니다. Remaining 경로 계열과 최종 호환성 분류가 남아 있어 SD-01은 계속 진행 중입니다. |
| 2026-08-07 | SD-01 | 진행 중 | `2111617b8` | Trajectory 상세, 결정론적 화면 답변, 민감정보가 제거된 모델 추적, 응답 리소스 맥락을 호환성 심 없이 pure 대화 변환 결과로 이동했습니다. Main 통합 union 테스트 258개가 통과했고 애플리케이션/projection-to-route 가져오기는 0을 유지했으며 scoped 경계와 translation 게이트가 통과했습니다. |
| 2026-08-07 | SD-01 | 진행 중 | `bbb5ac552` | 답변 계획 수립, 최종 quality 검토, content-policy 복구, busy-input steer 또는 interrupt coordination을 호환성 심 없이 명시적 애플리케이션 패키지로 이동했습니다. Main 수명 주기 union 테스트 131개가 통과했고 애플리케이션/projection-to-route 가져오기는 0을 유지했으며 채팅 경로 파일은 25개에서 17개로 줄었습니다. |
| 2026-08-07 | SD-01 | 진행 중 | `2ecd7a36c` | 에이전트 위임, runtime-skill 공개, 구성 표류, 공개 웹 근거, request-time 기능 가시성, 토폴로지 의도를 애플리케이션 또는 어댑터 경계 뒤로 이동했습니다. Main 기능 union 테스트 110개가 통과했고 reverse 가져오기는 0을 유지했으며 프로바이더 범위는 서버가 소유한 상태를 유지하고 채팅 경로 파일은 17개에서 11개로 줄었습니다. |
| 2026-08-07 | SD-01 | 진행 중 | `10d7ae266` | principal 범위 대화 기록과 이미지 수명 주기 영속성을 `persistence.conversation` 뒤로 이동했고 exact 문서 근거는 pure 대화 변환 결과로 이동했습니다. 워커 인계의 focused 테스트 438개가 통과했습니다. Main 영속성 union 테스트 155개, reverse 가져오기 0, scoped 경계 및 translation 게이트가 통과했고 채팅 경로 파일 8개가 남았습니다. 최종 response-tail과 route-common coordination 및 route-family 분류가 남아 있어 SD-01은 계속 진행 중입니다. |
| 2026-08-07 | SD-01 | 진행 중 | `e141ab07e` | Policy와 응답 완료를 명시적 애플리케이션 소유자 뒤로 이동했고 채팅 계열은 여섯 파일의 structural 인벤토리에 도달했습니다. Main union 테스트 235개, Ruff, strict mypy, structural 경계 게이트 및 translation 게이트가 통과했고 reverse 가져오기는 0을 유지했습니다. 독립 검토에서는 `chat.py`와 `chat_stream.py`가 여전히 계획 수립, 근거, 영속성 및 metering을 조정하므로 High 잔여가 남았다고 확인했습니다. 이는 부분 structural 종결이며 SD-01 완료가 아닙니다. |
| 2026-08-07 | SD-01 | 진행 중 | Reservation 인계 | 활성 reservation을 `/home/moonchoi/dev/fdai-worktrees/sd01-turn-execution`으로 이동했습니다. 이전 `/home/moonchoi/dev/fdai-worktrees/sd01-route-closure` 워크트리에는 삭제된 historical 블롭과 내용이 다른 untracked worker-local `chat_route_common.py` 산출물이 있으므로 읽기 전용으로 유지합니다. 이 워크트리는 활성 reservation이 아니며 부수적으로 정리하거나 병합해서는 안 됩니다. |
| 2026-08-11 | 워크트리 retirement 검토 | 완료 | `refs/archive/worktrees/20260811-reviewed/` | 최종 서비스 경계를 기준으로 검토한 결과 남은 dirty 산출물 2개를 모두 통합 대상에서 제외했습니다. 실행기 `uv.lock` delta는 현재 `0.1.3` 서비스 매니페스트와 잠금에 이미 존재하는 `aiokafka`, `psycopg` 의존성을 중복했고, 경로 산출물은 메타데이터, metering, 근거 보조 로직이 애플리케이션 소유자로 이동한 후 삭제된 Starlette-aware 호환성 모듈을 복원합니다. Exact non-integrated 상태는 보관 참조로 복구할 수 있으며 체크아웃은 제거했습니다. |
| 2026-08-07 | SD-06 | 진행 중 | `226e1058a` | 정본 모듈 인벤토리가 `projections/change_lineage`를 실행, 승격, 프로바이더 I/O 또는 영속성 권한이 없는 범위가 제한된 읽기 전용 request-local 변환 결과로 소유합니다. Exact Operator 패키지 및 경로 인벤토리 테스트 10개와 bilingual 지도, translation, punctuation 게이트가 통과했습니다. SD-06에는 예약된 비평 캠페인과 이후 상태 종료만 남아 있습니다. |
| 2026-08-07 | 병렬 세션 | 진행 중 | Persistent 워크트리 이행 | 활성 SD-03과 retained SD-07 워커를 `/home/moonchoi/dev/fdai-worktrees/`로 이동했습니다. 모든 새 워커는 이 persistent 루트를 사용하며 temporary 워크트리 경로는 더 이상 유효한 예약이 아닙니다. |
| 2026-08-07 | SD-07 | 진행 중 | `work/sd07-shadow-executor`의 시작 `03f6ef265` | `/tmp/fdai-sd07`에서 명령/증적 전송 계층과 영속 shadow-attempt mechanics를 시작했습니다. 효과 권한, 운영 조립, pantheon 역할, 신원 전환은 serial 통합 예약으로 유지합니다. |
| 2026-08-07 | SD-07 | 진행 중 | `3b84ee15a`, `800eee04b` | Versioned 명령/증적 스키마, 영속 중복/reorder/재시작/기한 종결, poison-record DLQ, at-least-once 증적 publish, supervised 상태 및 효과 없는 텔레메트리가 `main`의 focused union 테스트 55개를 통과했습니다. Logical-target 잠금 근거, 운영 조립, 워크로드 신원, Container App 배포는 남아 있으며 효과 권한은 SD-08 전까지 사용할 수 없습니다. |
| 2026-08-07 | SD-07 | 진행 중 | `9ff088aec` | 기존 `ResourceLock` 경계가 같은 대상의 그림자 명령을 직렬화하고 다른 대상은 겹쳐 처리하며 exact 대상 신원을 사용하고 핸들러 실패 후 잠금을 해제합니다. 워커에서 focused union 테스트 59개가 통과했고 잠금 인계를 통합했습니다. 운영 조립, 워크로드 신원, Container App 배포 및 실제 운영 그림자 smoke는 남아 있습니다. |
| 2026-08-07 | SD-07 | 진행 중 | Serial 시작 `b813a227f` | 패키지된 그림자 entrypoint와 명시적 deployed-process 표시를 통합했습니다. Serial IaC는 예약된 isolated-Executor 모듈과 SD-07 전용 루트 블록만 소유하며 SD-03 인제스트 Terraform은 변경하지 않습니다. |
| 2026-08-07 | SD-07 | 진행 중 | `0c52be49d` | 명시적 선택 내부 Container App IaC, 효과 권한이 없는 전용 UAMI, operational 명령/DLQ/증적 개체, Key Vault-backed 영속 상태, distributed 잠금 DSN 및 내부 탐색을 구현했습니다. 루트 Terraform validate, 모듈 shadow-boundary 테스트 1/1, 권한 테스트 3/3이 통과했고 SD-03 경로 변경은 없습니다. 실제 운영 실행기 계획/적용, exact-topology smoke 및 timed 롤백은 남아 있습니다. |
| 2026-08-07 | SD-07 | 차단됨 | `f3eb25593`, 실제 운영 게이트 | Private-runner 작업 흐름이 `deploy_isolated_executor`를 노출하고 plan-only 기본값과 design-mocks exclusivity를 보존하며 적용 후 앱 개정 번호를 검증합니다. 작업 흐름 테스트 24개가 통과했습니다. 상태 커밋 직전 측정에서 shared 큐 pending 커밋 575개와 `origin/main`보다 50 커밋 앞선 로컬 `main`을 기록했으므로 실제 운영 전달은 통합 검증기를 기다립니다. 다음 반증 검사는 SD-07 커밋의 exact 검증 증적과 성공한 push이며 그 후에만 plan-only 작업 흐름을 실행합니다. |
| 2026-08-07 | SD-06 | 완료 | `3d601afbe`, Low 잔여 후속 조치 | 잘못된 GitHub 배포 시각은 계속 실패 시 차단하며 이제 프로바이더, 기록 타입, 사유 필드만 포함하는 민감정보가 제거된 구조화된 경고 하나를 기록합니다. 프로바이더 행 값, 저장소 신원 및 커밋 참조는 로그에 남기지 않습니다. GitHub change-feed 테스트 9개, Ruff 및 strict mypy가 통과했습니다. 남은 Low 잔여는 authorized 상세 변환 결과의 내용 다이제스트와 400줄 참고용을 1줄 넘는 계보 모델입니다. |
| 2026-08-07 | SD-06 | 완료 | `7dca0e720`, `fe1664664`, `e70273d45`, 최종 Low-only 후속 조치 | 정본 신원 직렬화를 focused 모듈로 이동하고 exact 다이제스트 스냅샷을 추가해 집계 계보 모델을 401줄에서 340줄로 줄였습니다. 요약/상세 direct construction은 forged 계보, 후보, 평가 및 대상 다이제스트 형태를 차단하며 범위가 제한된 근거는 정본 평가 참조를 항상 보존합니다. Exact `main`에서 focused 계보/변환 결과/GitHub 테스트 46개, Ruff, strict mypy, Operator 경계 게이트, signed framework 무결성 및 editor 진단이 통과했습니다. 독립 검토는 Medium 이상 또는 재현 가능한 Low defect가 없음을 확인했습니다. Coarse 시계를 위한 non-decreasing equal 시각은 계속 유효하고 긴 프로바이더 신원은 코어에서 유효하지만 Operator 변환 결과는 display 한계를 넘으면 거부하며 authorized content-digest 가시성은 HTTP, 영속성, 프로바이더 I/O, 실행 또는 승격 경로가 없는 의도된 Low 재생 참조로 유지합니다. |
| 2026-08-07 | SD-01 | 완료 | `e141ab07e`, `d741d40e4`, `2de2c15f1`, `2c9bbd89f`, 최종 독립 검토 | `e141ab07e`에서 부분 structural 종결을 수립하고 `d741d40e4`에서 타입이 지정된 JSON 실행, `2de2c15f1`에서 타입이 지정된 SSE 실행, `2c9bbd89f`에서 structural 경계와 문서를 고정했습니다. SSE 통합 후 main union 테스트 283개와 focused structural 종결 테스트 114개가 통과했습니다. 정확한 경로 인벤토리는 `chat.py`, `chat_registration.py`, `chat_stream.py`, `chat_stream_protocol.py`, `chat_stream_request.py`, `chat_verification.py`이며 `chat.py`는 259 LOC, `chat_stream.py`는 211 LOC입니다. 애플리케이션, 변환 결과, 영속성의 routes reverse 가져오기는 0이고 `turn_execution`의 Starlette, routes, 구체적인 어댑터 가져오기도 0입니다. Ruff와 strict mypy가 green이며 translation은 175/175를 통과했습니다. JSON/SSE 전송 계층, authentication, 요청 파싱, 상태 대응, 프레임 순서, 취소는 경로가 소유하고 계획 수립, 근거, 세대, 검증, 영속성, metering 수명 주기 coordination은 애플리케이션이 소유합니다. Wire, 재생, 중단, 이력 행동을 보존했습니다. 최종 독립 검토는 Medium 이상 발견 사항 0건과 Low 잔여 1건을 확인했습니다. 구현이 없는 `routes/chat_verification.py` 호환성 파사드는 카탈로그/source-path 호환성을 위해 남아 있으며 SD-09 정리 후보이고 완료 차단 요인이 아닙니다. |
| 2026-08-07 | SD-01 | 완료 | 강화 라운드 1-13, Low-only 검토 | 독립 비평 라운드 12회에서 JSON/SSE 전송 계층 동등성, 경로 인벤토리, 수명 주기 정렬과 취소, 영속성과 재생, principal 격리, 신원 경계, 민감정보 제거 및 출처 이력을 검토했습니다. 재현 가능한 Medium 발견 사항 1건은 임의 document-resolver `RuntimeError` 상세가 JSON과 SSE HTTP 응답에 모두 노출되는 문제였습니다. Shared request-preparation 및 JSON 수명 주기 경계는 이제 원래 exception을 내부 원인으로 보존하면서 고정된 사용 불가 상세만 제공합니다. 전체 chat-route 테스트 82개, exact 민감정보 제거 회귀 2개, Ruff, formatting 및 운영 구획 strict mypy가 통과했습니다. 라운드 13 독립 검토는 현재 호출 경로를 기준으로 불완전한 SSE 상태 지도, double 정리, 영속성 전 완료 및 중복 계획 수립 발견 사항을 반증했습니다. Medium 이상 잔여는 없습니다. 구현이 없는 `routes/chat_verification.py` 파사드는 의도된 Low SD-09 정리 후보로 유지합니다. |
| 2026-08-07 | SD-07 | 진행 중 | 실제 운영 실행 `31177967045`, 이미지 admission 복구 시작 | Terraform 적용과 convergence는 성공했지만 reused ACR `v0.1.163` 이미지에 구성된 `fdai-isolated-executor` 명령이 없어 isolated 실행기 개정 번호가 unhealthy 상태에 머물렀습니다. Log Analytics는 프로세스 시작 전 반복된 OCI `ContainerCreateFailure`를 증명했고 이미지 pull, Core 상태 및 Operator API 상태는 성공했습니다. Persistent 복구 워커는 image-admission 구획만 소유합니다. 다음 반증 검사는 Terraform 전에 isolated 항목 지점을 통과하는 exact 현재 이미지와 healthy에 도달한 배포 개정 번호입니다. |
| 2026-08-07 | SD-03 | 완료 | `480d11686`, `5c034fc65`, 실제 운영 effective-access 증적 | Focused Terraform 사례 7개가 통과했고 split-to-cohost-to-split 예행 연습은 900초 예산 중 2초에 완료됐습니다. VNet 실행기는 inherited Azure RBAC의 exact 일치와 non-privileged PostgreSQL 런타임 역할을 확인했습니다. 실제 운영 인제스트 API와 워커 개정 번호도 healthy입니다. |
| 2026-08-07 | SD-07 | 진행 중 | 계획 `31179749690`, 적용 `31180087754` | Exact protected 계획은 `0 add / 9 in-place change / 0 destroy`였고 적용은 exact-plan 검증, convergence, 이행 2개, healthy 런타임 개정 번호 5개, API 상태, canary 및 변경할 수 없는 증적을 완료했습니다. Isolated 신원은 ACR pull, 명령 수신, 증적/DLQ 전송 및 state-secret 읽기 역할만 가지며 효과 권한은 0입니다. 기존 프로세스 내 Core 경로는 SD-08 롤백 산출물로 유지합니다. Image-admission 비평 인계와 SD-08 timed authority-cutover 롤백은 계속 열려 있습니다. |
| 2026-08-07 | SD-07 | 완료 | `c8a32ae77`부터 `aa89b0bf1`, 라운드 1-11 | 최종 이미지는 uid 65532에서 isolated 항목 지점을 검증합니다. Protected 계획은 ACR 다이제스트가 일치하는 attested GHCR 대상만 수락하고 명시적 authorized 승격을 요구하며 strict runtime-image 메타데이터를 보존하고 모든 외부 이미지 연산에 한계를 적용합니다. Exact main union에서 검증기, 작업 흐름, 이미지, 전송 계층 및 CLI 테스트 72개와 Ruff, strict mypy, YAML, translation, punctuation, whitespace 검사가 통과했습니다. 독립 검토에서 재현 가능한 Medium 이상 잔여는 없었고 malformed 레지스트리 응답과 사용 불가 pre-promoted 이미지는 실패 시 차단합니다. 실제 운영 실행 `31180087754`는 효과 권한 0을 유지하며 상태, canary 및 변경할 수 없는 적용 증적을 완료했습니다. SD-08은 dependency-ready이며 serial 상태를 유지합니다. |
| 2026-08-07 | SD-08 | 진행 중 | Identity-boundary 발견 시작 | 하나의 Event Hubs 역할만 단순히 이동할 수 있다는 첫 가설은 반증됐습니다. 현재 집계 신원은 Core 전송 계층과 시작 의존성도 소유하며 Core는 집계 신원과 버티컬 신원 3개를 직접 첨부합니다. Serial 워커는 먼저 design 및 토폴로지 테스트에서 필요한 Core 전송 계층/읽기 신원을 mutation-capable 실행기 신원과 분리합니다. 이후 exact 전환 계획과 롤백 증적 전까지 효과 권한은 0을 유지합니다. |
| 2026-08-08 | SD-08 | 진행 중 | Implementation-ready focused 증적 | 가산 실행기 증적 `1.1.0`, 원격 direct-API 명령/증적 상관관계, 효과 이전 감사 의도, 고정된 Core 증적 소비자 그룹, duplicate-safe isolated 전달, 명시적 default-off Terraform 전환, 게이트웨이 principal transfer, reversible NSG 탐색 및 protected 작업 흐름 검증을 구현했습니다. Focused 테스트 126개, strict mypy, Ruff, Terraform validate, 루트 토폴로지 사례 6개, 모듈 사례 2개가 통과했습니다. Protected 계획을 수락하고 적용하기 전까지 실제 운영 효과 권한은 변경되지 않습니다. |
| 2026-08-08 | SD-08 | 완료 | 계획 `31207740363`, `31211368557`, `31214493667`; 적용 `31209982126`, `31211927016`, `31214900219` | 첫 isolated 증명은 오프셋 `[0,1]`, 프로바이더 쓰기 1회, ARM present/absent 관측, 정리 및 142초 증적을 기록했습니다. Rollback 계획은 `0 add / 3 change / 0 destroy`였고 로컬 전송 계층은 쓰기 1회와 정리를 450초에 증명했습니다. 최종 전환 계획은 `0 add / 4 in-place change / 0 destroy`였으며 replacement와 role-assignment 변경은 0이었습니다. 최종 isolated 전송 계층은 오프셋 `[3,4]`로 이어졌고 프로바이더 쓰기 정확히 1회, 독립적인 ARM 관측과 정리를 436초에 통과했으며 개정 번호 5개가 모두 healthy 상태를 유지하고 canary와 no-change convergence를 완료했습니다. |
| 2026-08-08 | SD-09 | 완료 | Closing 검증 증적 | 기능 카탈로그를 owned 검증 패키지로 옮긴 뒤 오래된 `routes.chat_verification` source-path 파사드를 제거했습니다. 검토된 boundary-docstring 범위 22개를 모두 강제 적용으로 전환했고 기능 카탈로그, Operator 배치 및 경계 모음의 focused 테스트 30개가 경계 공백 보고 0건으로 통과했습니다. Centralized 검증은 push 전에 테스트 15076개, environment-dependent 건너뜀 15개, 출처 파일 1904개 대상 strict mypy 및 모든 저장소 게이트를 통과했습니다. |
| 2026-08-09 | IS-06 | 로컬 완료 | 로컬 배포 증적 | Terraform 루트와 백엔드 계약 5개, state-migration 소유권 계약 5개, protected 계획/적용 가드 및 의미 four-peer 격리 mechanics가 focused 배포 테스트 113개를 통과했습니다. Exact 원격 증적은 IS-09 program-final 게이트로 보류하며 이 전환의 근거로 주장하지 않습니다. |
| 2026-08-09 | IS-07 | 로컬 완료 | 로컬 전이 근거 | `0.1.3 -> 0.1.2 -> 0.1.3` 휠 전이 5개, nonroot 서비스 이미지 10개 및 peer-stable focused 이행/롤백 증적 10개가 오프셋 보존, peer 재시작 0, 중복 최종 효과 0으로 통과했습니다. 원격 rolling 확인은 IS-09로 보류합니다. |
| 2026-08-09 | IS-09 | 로컬 검토 완료 | 라운드 11-14, `07db3e5d8` | 독립 라운드 4회에서 protected deploy 출처 이력, 의미 peer-state 격리, 7개 루트 표류 detection 및 N/N-1 근거 무결성을 검토했습니다. Program-final 상태를 completed로 설정해도 accepted 증적 개수가 불완전할 수 있는 재현 가능한 Medium 발견 사항 1건을 수정하여 계획/적용 5개와 업그레이드/롤백 5개 증적을 모두 요구합니다. Focused 매니페스트와 호환성 검사가 통과했고 Medium 이상 로컬 잔여는 0건입니다. 보류된 원격 5+5 검증이 통과할 때까지 IS-09는 진행 중으로 유지합니다. |
| 2026-08-09 | IS-09 | 강화 계속 | 라운드 15-28 | 독립 검토 10회에서 protected deploy, 계획 봉인, peer 격리, 롤백, 실제 운영 호환성, 이행, supply 체인, 표류, Terraform 소유권 및 최종 종결을 검토했습니다. 실제 운영 실행을 통해 범위가 제한된 병렬 실행기 자리, 원격 셸 expansion, 명시적 등록 성공 및 final-path 이미지 shebang을 추가로 강화했습니다. Core 실행 `31274885226`은 broken 이미지가 실패 시 차단하고 이전 healthy 개정 번호를 복원함을 증명했으며, 수정된 Core 이미지는 로컬 빌드와 가져오기를 통과했습니다. Medium 이상 로컬 잔여는 0건이고 원격 5+5 검증은 계속 필요합니다. |
| 2026-08-09 | IS-09 | 실제 운영 근거 강화 | 라운드 29 | `observed:false` 내용을 다시 해시한 실제 운영 근거 산출물은 더 이상 통과하지 않습니다. 검증은 각 관측의 종류와 서비스를 연결하고 실제 관찰된 결과가 true인 경우에만 내용 기반 주소를 가진 참조가 실제 운영 이행 또는 롤백 증적을 충족하도록 요구합니다. |
| 2026-08-09 | IS-09 | 워커 전환 복구 | 라운드 30 | 실행 `31276433851`은 실제 운영 이전 방식 ClamAV sidecar에 탐색이 없어 변경 전에 실패했습니다. Initial 전환은 롤백용 exact 빈 탐색 계약만 스냅샷하고 exact 복원을 검증합니다. Normal 스냅샷과 모든 새 워커 개정 번호는 계속 시작, 생존, 준비 상태 TCP 탐색을 요구합니다. |
| 2026-08-09 | IS-09 | 런타임 의존성과 이행 준비 상태 | 라운드 31 | 실제 운영 개정 번호에서 인제스트 API의 `aiohttp` 누락과 미적용 Operator/실행기 역할 가지가 드러났습니다. 인제스트 분포는 비동기 Azure 전송 계층 의존성을 소유하고, protected 서비스 적용은 검증된 Key Vault 참조에서 admin DSN을 읽어 마스킹한 뒤 트래픽 전에 exact service-owned 이행 가지를 적용합니다. |
| 2026-08-09 | IS-09 | Exact 시크릿 롤백 | 라운드 32 | Operator와 실행기 복구 개정 번호는 healthy였지만 post-apply `database-dsn` 별칭이 이전 방식 이름과 함께 남아 검증이 실패했습니다. Rollback은 변경할 수 없는 스냅샷에 없는 시크릿 이름만 제거하고 이전 Key Vault 참조를 복원한 뒤 exact equality를 검증합니다. |
| 2026-08-09 | IS-09 | Enforced 데이터베이스 principal | 라운드 33 | 계획은 `fdai_operator`, `fdai_executor` 등 서비스 역할을 선언하지만 일부 DSN 시크릿은 admin principal로 인증했습니다. 서비스 모듈 5개는 PostgreSQL `PGOPTIONS=-c role=<declared role>`을 설정해 준비 상태와 권한 부여가 intended `current_user`를 평가하도록 합니다. |
| 2026-08-09 | IS-09 | Historical 롤백 출처 이력 | 라운드 34 | Privileged 작업 흐름 가드가 historical 이미지 출처에 byte-identical 배포 컨트롤을 요구해 컨트롤 강화가 한 번이라도 적용되면 N-1 롤백을 영구 차단했습니다. 이제 historical 산출물 개정 번호는 protected-main ancestry와 증명을 요구하고 실행 작업 흐름과 컨트롤은 현재 protected `main`에 고정합니다. |
| 2026-08-09 | IS-09 | 현재 배포 출처 | 라운드 35 | 실제 운영 preflight에서 `commit_sha`가 이미지 개정 번호와 historical Terraform을 함께 선택해 롤백 중 이후 역할 및 복구 강화를 조용히 제거할 수 있음을 발견했습니다. 이제 이 값은 변경할 수 없는 이미지 출처 이력만 연결하고 Terraform 루트, 이행, 이전 방식 상태 연산 및 peer 수집은 모두 현재 protected `main`을 사용합니다. 취소한 Operator 실행은 백엔드 검증 중 중단됐고 모든 변경 단계는 건너뜀됐습니다. |
| 2026-08-09 | IS-09 | 완전한 계획 오래됨 fence | 라운드 36 | Successful 계획 이후 이행 의존성 fix가 반영됐지만 적용 출처 이력은 작업 흐름과 보조 로직 스크립트만 비교했습니다. 이제 exact 적용은 작업 흐름, 배포 보조 로직, 모든 서비스 Terraform 루트와 shared 모듈, 서비스 이행, 루트 project 의존성 또는 의미 `uv.lock` 그래프 변경을 거부합니다. 루트 release 버전만 변경되고 나머지가 동일한 경우에는 계획을 무효화하지 않습니다. 영향받은 계획은 적용 전에 모두 폐기했습니다. |
| 2026-08-09 | IS-09 | Initial 이행 도입 | 라운드 37 | Core 적용 실행 `31281314437`은 서비스 이행 기준선이 각인되지 않아 스냅샷 또는 Terraform 변경 전에 실패했습니다. 이제 initial 전환은 exact 이전 방식 헤드와 owned-schema 지문을 관측하고 commit-pinned 롤백 참조가 포함된 도입 및 스키마 근거를 저장하며 exact 기준선만 멱등적하게 각인한 뒤 서비스 가지를 업그레이드합니다. Standard 적용은 기준선을 생성하지 않습니다. |
| 2026-08-09 | IS-09 | 도입 근거 스키마 동등성 | 라운드 38 | 공개 adoption-evidence 스키마는 이전 방식 개정 번호 79개를 요구했지만 검증된 도입 매니페스트는 모두 정본 81개를 요구했습니다. 이제 스키마가 실제 운영 인벤토리와 일치하며 회귀 테스트가 정본 이행 그래프에서 필수 헤드와 개정 번호 개수를 모두 도출합니다. |
| 2026-08-09 | IS-09 | 도입 재시도 및 근거 내구성 | 라운드 39 | Initial 전환이 서비스 이행 가지를 업그레이드한 뒤 후속 단계에서 중단되면 재시도가 변경된 스키마를 대상으로 기준선 근거를 다시 생성하여 스스로 차단할 수 있었습니다. 이제 prepare와 각인은 exact 서비스 계보가 기준선을 포함할 때만 no-op으로 처리하고 다른 기존 계보는 모두 차단하며, 후속 이행 단계가 실패해도 portable 도입 및 스키마 근거를 90일 동안 보존합니다. |
| 2026-08-09 | IS-09 | Legacy-head 도입 선행 조건 | 라운드 40 | Core 적용 실행 `31284637886`은 실제 운영 이전 방식 계보가 `20260806_0077`이고 도입은 `20260808_0079`를 요구하여 스냅샷 또는 Terraform 변경 전에 실패했습니다. 이제 initial 전환은 가산 ontology-direction 이행으로 이전 방식 Alembic 계보를 먼저 전진시킨 뒤 스키마 근거 관측, 서비스 기준선 각인 및 서비스 가지 업그레이드를 수행합니다. 이전 방식 이행 파일과 `alembic.ini`도 exact 계획/적용 출처 이력 입력에 포함됩니다. |
| 2026-08-09 | IS-09 | 이전 방식 이행 working 디렉터리 | 라운드 41 | Core 적용 실행 `31286708624`는 Alembic이 relative `script_location`을 protected 체크아웃 밖에서 해석하여 스냅샷 또는 Terraform 변경 전에 실패했습니다. 이제 이전 방식 업그레이드는 exact protected 통제 수단 체크아웃을 루트로 하는 subshell에서 실행하므로 `alembic.ini`와 tracked 이행 디렉터리가 동일한 sealed 출처에서 해석됩니다. |
| 2026-08-09 | IS-09 | Release-safe 계획 출처 이력 | 라운드 42 | Automatic release 커밋이 루트 패키지 버전만 변경해 의존성과 배포 컨트롤이 동일한데도 protected 계획을 반복해서 무효화했습니다. 이제 적용은 strict 컨트롤을 byte-for-byte로 비교하고 `pyproject.toml`과 `uv.lock`에서는 루트 FDAI release 버전만 제거한 뒤 의미 내용을 비교합니다. 의존성, 잠금 그래프, 이행, 작업 흐름, 보조 로직 또는 Terraform 변경은 계속 계획을 무효화합니다. |
| 2026-08-09 | IS-09 | 서비스 이행 개정 번호 용량 | 라운드 43 | Core 적용 실행 `31294369918`은 adopted 서비스 기준선까지 진행했지만 Alembic이 서비스 버전 열을 32자로 생성했고 다음 가지 개정 번호 id가 더 길어서 Terraform 변경 전에 실패했습니다. 이제 기준선 각인과 모든 서비스 업그레이드는 가지 이력을 기록하기 전에 service-owned 버전 열만 128자로 확장하며 이전 방식 Alembic 표는 변경하지 않습니다. |
| 2026-08-09 | IS-09 | 범위가 제한된 slow 개정 번호 준비 상태 | 라운드 44 | Core 적용 실행 `31295906457`은 이행과 Terraform 적용을 완료했지만 새 digest-pinned 개정 번호가 기존 nominal 3분 polling 구간보다 오래 걸렸습니다. Automatic 롤백이 이전 이미지를 복원하고 검증한 뒤 해당 개정 번호는 healthy로 관측되었습니다. 이제 post-apply 상태는 롤백 전에 기존 900초 배포 증명 예산까지 기다리며 unhealthy 또는 inactive 개정 번호는 계속 실패 시 차단 처리합니다. |
| 2026-08-09 | IS-09 | No-ingress 개정 번호 activation | 라운드 45 | Core 적용 실행 `31297621282`은 900초 예산 전체를 기다렸지만 내부 no-ingress 서비스에는 트래픽 전환이 없어 새 개정 번호가 healthy 상태이면서도 복제본 0의 stopped 및 inactive 상태로 유지되었습니다. 이제 검증은 최신 개정 번호가 스냅샷과 다르고 exact protected 이미지를 실행하는지 확인한 뒤 범위가 제한된 Container Apps 개정 번호 activation을 한 번 수행하고 기존 상태 및 롤백 검사를 계속합니다. |
| 2026-08-09 | IS-09 | Core 런타임 데이터베이스 역할 | 라운드 46 | Activation-aware Core 실행 `31299720389`은 exact 이미지를 시작했지만 PostgreSQL 역할 `fdai_core`가 없어 반복적으로 exit 코드 1이 발생한 사실을 Log Analytics에서 확인했습니다. 이제 Core 이행 가지는 해당 non-login 역할을 만들고 Core-owned 표 34개와 감사 순서에만 권한을 부여하며 schema-wide 및 기본값 권한은 허용하지 않습니다. |
| 2026-08-09 | IS-09 | 알림 의존성 성능 저하 | 라운드 47 | Core-role 실행 `31301828821`은 데이터베이스 시작을 통과했지만 A2 operational-alert 채널 누락이 전체 Core 프로세스를 중단한 사실을 Log Analytics에서 확인했습니다. 이제 런타임은 사용 불가 경로를 보고하고 unrelated 읽기, 거부, 큐 및 그림자 경로를 유지합니다. 해당 알림 경로가 필요한 액션은 usable 전달 채널이 없으므로 전달 성공을 주장할 수 없습니다. |
| 2026-08-09 | IS-09 | 완전한 컨테이너 카탈로그 선택 | 라운드 48 | Corrected-image Core 실행 `31311862255`은 역할과 알림 시작을 통과했지만 카탈로그 발견이 불완전한 virtual-environment `rule-catalog`를 선택하여 chaos 시나리오 스키마를 찾지 못한 사실을 Log Analytics에서 확인했습니다. 이제 런타임 카탈로그 해석은 package-parent 개발 대체 경로보다 완전한 `/app/rule-catalog` 페이로드를 먼저 검사하며 symptom-index 시작은 import-time 기본값 대신 resolved chaos 카탈로그를 명시적으로 받습니다. |
| 2026-08-09 | IS-09 | 프로비저닝된 시작 탐색 토픽 | 라운드 49 | Catalog-corrected Core 실행 `31316016509`은 상태 서버까지 도달했지만 기본 초기화 엔드포인트를 사용했고 전용 `runtime.startup.probe` 개체는 operational 이름 공간에 속해 있어 준비된이 되지 못했습니다. 가득 찬 기본 이름 공간을 재사용하는 범위가 제한된 중간 수정을 시험했지만 성공적인 round-trip을 확립하지 못했습니다. |
| 2026-08-10 | IS-09 | 시작 탐색 소비자 준비 상태 | 라운드 51 | 실제 운영 Core 로그에서 고유 Event Hubs 소비자 그룹이 결합하는 데 약 3초가 필요했지만 독립적인 서비스는 구성된 settle 예산을 누락하여 런타임 기본값 0.5초 뒤에 publish했습니다. 따라서 소비자가 synthetic 기록 이후 최신 오프셋에서 시작했고 왕복은 시간 초과됐습니다. 이제 서비스는 순서 검증 및 재시도 headroom과 함께 12초 settle 예산, 30초 탐색 기한 및 75초 단계 기한을 주입합니다. Exact 왕복을 관측하지 못하면 탐색은 계속 실패 시 차단합니다. |
| 2026-08-09 | IS-09 | Operational 시작 탐색 연결 | 라운드 50 | 정본 Core 적용 `31318043097`은 기본 governed-ingress 토픽을 공유하면 synthetic 소비자가 시간 초과하고 automatic 롤백이 올바르게 시작됨을 증명했습니다. 이제 독립 Core 계약은 기존 operational 초기화 엔드포인트와 전용 시작 토픽을 받아 synthetic 범위, 신원 격리 및 두 이름 공간의 개체 제한을 보존합니다. |
| 2026-08-09 | IS-09 | No-ingress 상태 근거 | 라운드 51 | 같은 적용에서 Azure가 내부 no-ingress Core 앱에 `healthState`를 보고하지 않는다는 사실도 확인했습니다. 이제 상태 및 롤백 검증은 유입이 비활성화된이고 exact 개정 번호가 활성, `Running`, 복제본 1개 이상일 때만 absent 상태를 수락합니다. Ingress-enabled 앱은 계속 `Healthy`를 요구합니다. |
| 2026-08-09 | IS-09 | 매니페스트 맥락 sanitization | 라운드 52 | Final-evidence 검토에서 deployment-context 거절이 원격 집계에는 적용되지만 independent-service 매니페스트 입력에는 적용되지 않는 문제를 확인했습니다. 이제 검증은 release 또는 분포 필드를 읽기 전에 두 입력 모두에 같은 재귀 식별자, 엔드포인트 및 deployment-key 거절을 적용합니다. |
| 2026-08-09 | IS-09 | Serial 전이 windows | 라운드 53 | Temporal 비평에서 global 직렬화가 적용 구간만 다루고 protected 계획은 포함하지 않으며, 단계 정렬도 첫 복원 전에 모든 롤백 완료를 명시적으로 요구하지 않는 문제를 확인했습니다. 이제 검증기는 겹치는 모든 계획/적용 구간을 거부하고 완전한 initial, 롤백, 복원 단계 결합을 요구합니다. |
| 2026-08-10 | IS-09 | 정본 N 출처 연결 | 라운드 54 | Supply-chain 비평에서 N-1은 매니페스트 출처에 연결되지만 N은 작업 흐름 헤드가 자체 출처와 일치하기만 하면 임의 출처 개정 번호를 수락하는 문제를 확인했습니다. 이제 전이 매니페스트는 exact N 출처를 기록하며 최종 근거는 해당 개정 번호에서 시작하지 않은 N release, 이미지 집합 또는 단계 체인을 거부합니다. |
| 2026-08-10 | IS-09 | Closed 로컬 근거 스키마 | 라운드 55 | Evidence-boundary 비평에서 로컬 전이 서비스와 산출물이 일부 필드만 검사하여 인식되지 않은 필드를 포함할 수 있는 문제를 확인했습니다. 이제 검사기는 로컬 N -> N-1 -> N 근거를 수락하기 전에 exact top-level, 서비스 및 산출물 키 집합을 요구합니다. |
| 2026-08-10 | IS-09 | 완전한 원격 개수 결합 | 라운드 56 | Program-final 비평에서 통합 게이트가 5/5 대상 2개는 다시 검사하지만 계획 15개, 적용 15개 및 peer 증적 30개는 중첩된 검증기에만 의존하는 문제를 확인했습니다. 이제 완료 결합은 실제 운영 호환성 근거를 부하하기 전에 derived 개수 5개를 모두 독립적으로 요구합니다. |
| 2026-08-10 | IS-09 | Exact document-service 신원 선택 | 라운드 57 | 인제스트 API 실행 `31348846570`은 새 개정 번호까지 도달했지만 Container App이 exact user-assigned 클라이언트 id를 선언했는데도 Azure SDK 클라이언트가 선택자 없는 Managed Identity 자격 증명을 사용하여 비정상 종료 루프에 진입했습니다. 이제 API와 워커는 `FDAI_MI_CLIENT_ID`를 요구하고 모든 Azure 어댑터 자격 증명을 해당 exact 클라이언트 id로 생성합니다. 신원 선택이 없으면 프로바이더 탐색 전에 실패합니다. |
| 2026-08-10 | IS-09 | Corrected 정본 N 이미지 출처 | 라운드 58 | Supply-chain 실행 `31349808536`은 identity-corrected 출처에서 이미지 5개를 모두 성공적으로 빌드, 검사 및 attest했습니다. 이제 머신 전이 계약은 해당 출처를 N으로 고정하므로 이후 계획, 복원 및 최종 근거에서 이전 crash-looping 문서 이미지와 corrected peer를 섞을 수 없습니다. |
| 2026-08-10 | IS-09 | Key Vault 시크릿 정규화 가드 | 라운드 59 | 전환 이후 Operator 계획에서 변경되지 않은 Key Vault 참조 옆의 비어 있거나 생략된 `secret[*].value`에만 AzureRM 새로 고침 표류가 나타났습니다. 이제 protected 계획 가드는 이 exact 프로바이더 정규화 형태만 허용합니다. 비어 있지 않은 값, 변경된 시크릿 메타데이터 또는 추가 표류는 계속 차단합니다. |
| 2026-08-10 | IS-09 | Encoded 맥락 거절 | 라운드 60 | Customer-agnostic 근거 검토에서 percent-encoded Azure 경로와 간결한 GUID 값이 리터럴 식별자 검사를 우회할 수 있는 문제를 확인했습니다. 이제 검증은 근거 필드를 읽기 전에 범위가 제한된 URL 디코딩을 수행하고 exact 간결한 GUID 값을 거부합니다. |
| 2026-08-10 | IS-09 | Exact 원격 매니페스트 스키마 | 라운드 61 | Manifest-shape 검토에서 원격 검증기가 정본 전이 키와 서비스 커버리지를 outer 검사기에 의존하는 문제를 확인했습니다. 이제 검증기는 exact 전이 스키마와 unique 정본 서비스 선언 5개를 독립적으로 요구합니다. |
| 2026-08-10 | IS-09 | 완료 의존성 결합 | 라운드 62 | Work-package 검토에서 program-final 경로가 원격 완료는 검사하지만 IS-09 의존성 2개를 독립적으로 결합하지 않는 문제를 확인했습니다. 이제 IS-09 완료는 IS-07과 IS-08이 completed 상태를 유지해야 합니다. |

| 2026-08-10 | IS-09 | Trusted GitHub 근거 연결 | 라운드 63 | Final-proof 비평에서 tracked JSON의 internally consistent 실행 id, 시각, 산출물 다이제스트 및 peer 상태가 여전히 self-asserted인 문제를 확인했습니다. 이제 dedicated 읽기 전용 작업 흐름이 모든 실행을 GitHub API와 대조하고 각 계획 메타데이터와 peer 증적 산출물을 download하여 검사하며 deployment-input 동등성과 이미지 증명을 다시 검사한 뒤 집계에 서명합니다. Program-final 완료는 해당 exact 서명자와 출처 개정 번호에 대한 portable 번들 검증을 요구합니다. |

| 2026-08-10 | IS-09 | 복구 개정 번호 메타데이터 가드 | 라운드 64 | 검증된 Core 롤백이 Terraform 상태 외부에서 Azure의 computed 최신 개정 번호 이름과 개정 번호 접미사를 변경하여 런타임 및 권한 필드가 그대로인데도 다음 standard 계획이 차단됐습니다. 이제 가드는 computed 식별자 2개만 수락하며 컨테이너, 신원, 시크릿, platform 또는 권한 표류는 계속 부적격입니다. |
| 2026-08-10 | IS-09 | Observable sidecar 계약 정규화 | 라운드 65 | 워커 적용 `31352359688`은 exact 검토된 이미지와 healthy 개정 번호를 배포했지만 post-apply 검증은 비어 있는 `args`, `env`, `volume_mounts` 및 `ephemeral_storage` 같은 Terraform 컨테이너 필드를 해당 기본값을 생략하고 CPU와 기억을 `resources` 아래에 중첩하는 Azure Resource Manager 개정 번호 형태와 비교했습니다. 이제 sealed sidecar 다이제스트는 ARM에서 관찰 가능한 exact 이름, CPU 및 기억 계약을 포함합니다. 변경할 수 없는 이미지와 탐색 다이제스트는 계속 분리되며 검토된 Terraform 계획은 관찰할 수 없는 필드를 계속 보호합니다. 알 수 없거나 비어 있지 않은 지원하지 않는 런타임 필드는 계속 실패 시 차단으로 처리합니다. |
| 2026-08-10 | IS-09 | 도입 and compatibility-proof separation | 라운드 66 | 근거 검토에서 positional `initial` N 단계가 one-time `initial-cutover` 배포 모드를 사용하도록 잘못 요구하는 문제를 확인했습니다. One-time 상태 및 스키마 도입은 preparatory 서비스 전이이며 corrected 이미지 출처마다 반복할 수 없습니다. 이제 최종 원격 N -> N-1 -> N 호환성 증명은 서비스 5개가 모두 adopted 상태가 된 이후에만 시작하고 모든 단계에 standard protected 계획을 요구합니다. 이를 통해 repeated 도입을 방지하면서 fresh 개정 번호, 롤백 및 peer-isolation 근거를 유지합니다. |
| 2026-08-10 | IS-09 | 영속 원격 도입 선행 조건 | 라운드 67 | Program-final 검토에서 one-time 도입 근거가 90일 작업 흐름 산출물에만 남고 최종 attested 집계에 결합되지 않는 문제를 확인했습니다. 이제 집계는 도입 실행 5개, 산출물 다이제스트, 관찰된 이전 방식 헤드 및 개정 번호 개수, 스키마 지문, owned-table 개수, 검증 시간, commit-pinned 롤백 참조를 기록합니다. GitHub 연결기는 최종 증명 전에 각 실행, 성공한 이행 및 artifact-upload 단계, API 산출물 다이제스트와 download한 JSON 기록 2개를 검증합니다. 이후 상태 또는 peer 검사가 실패해도 완료된 도입은 지워지지 않지만 도입 단계가 누락되거나 실패하면 종결이 차단됩니다. |
| 2026-08-10 | IS-09 | Genuine kind-specific 실제 운영 observations | 라운드 68 | 안전성 비평에서 live-evidence 빌더가 범용 전이 메타데이터를 `observed=true`인 종류 7개로 다시 표시하는 문제를 확인했습니다. 이제 successful 적용은 이미지 증명, 서비스 이행, exact 상태 및 신원 검증과 four-peer 격리가 성공한 뒤에만 별도 산출물을 seal합니다. Health, 신원, 이미지, state-offset, 스키마, 출처 및 토폴로지 기록은 서로 다른 근거를 포함합니다. 최종 집계는 exact 내용과 산출물 다이제스트를 저장하고 GitHub 연결기는 증명 전에 successful 단계와 download한 산출물을 검사합니다. 빌더는 해당 관찰된 기록만 복사하며 누락되거나 relabel된 내용 및 `observed=false` 내용을 거부합니다. |
| 2026-08-10 | IS-09 | 결정론적 실제 운영 호환성 연결 | 라운드 67 | Completion-path 검토에서 schema-valid 실제 운영 증적과 관측 매니페스트를 trusted 원격 집계와 독립적으로 작성할 수 있는 문제를 확인했습니다. 이제 program-final 검사기는 exact 롤백/복원 실행, 계획, 맥락, peer-receipt, 출처 및 serial peer-version coordinate에서 이행/롤백 증적 10개와 관측 기록 35개를 모두 도출하고 호환성 검증 전에 byte-equivalent JSON 값을 요구합니다. Self-asserted 실제 운영 기록은 더 이상 IS-09를 완료할 수 없습니다. |
| 2026-08-10 | IS-09 | 계획별 fresh protected 개정 번호 | 라운드 68 | Core 적용 `31353853013`에서 외부 검증된 롤백 이후 Terraform 구성은 N을 유지하지만 Azure 최신 활성 개정 번호는 restored 이미지로 남을 수 있음을 확인했습니다. 이 상태의 fresh 계획은 변경 없이 적용되었고 상태 검증은 old 이미지를 올바르게 거부했습니다. 이제 shared Container App 모듈은 범위가 제한된 plan-time 개정 번호 접미사를 모든 saved 계획에 seal하고 가드는 exact 이미지 변경 옆에서 해당 구문만 허용합니다. 따라서 모든 protected 적용은 컨테이너, 신원, 시크릿, platform 또는 권한 검사를 약화하지 않고 새로 검증 가능한 개정 번호를 생성합니다. |
| 2026-08-10 | IS-09 | 범위가 제한된 direct peer-state 수집 | 라운드 69 | 원격 operability 검토에서 각 근거 실행이 isolated 백엔드 상태를 읽기 위해 full Terraform peer 루트 4개를 두 번씩 initialize하여 30-run serial 증명이 수 시간의 프로바이더 및 백엔드 delay에 취약한 문제를 확인했습니다. 이제 peer 수집은 이미 인증된된 실행기 신원과 60초 stop 조건으로 exact 허용 목록에 있는 백엔드 블롭을 Azure CLI를 통해 각각 download합니다. 기존 정본 상태 변환 결과와 before/after 다이제스트 검증기는 변경하지 않습니다. |
| 2026-08-10 | IS-09 | 도입 관측과 완료 분리 | 라운드 70 | 도입 재생 검토에서 Core의 영속 스키마 관측은 이후 이행 실패 전에 업로드되었고, 후속 protected 실행은 동일 이행을 완료했지만 one-time 산출물을 다시 생성하지 않은 사실을 확인했습니다. 도입 이후 `initial-cutover` 재생은 올바르게 차단됩니다. 이제 원격 근거는 exact 산출물 실행과 exact later 완료 실행을 별도로 연결하고 두 실행의 GitHub 작업 흐름 단계를 모두 검증하며, original 변경할 수 없는 스키마 및 롤백 기록과 결합된 protected-main 이행 성공만 허용합니다. |
| 2026-08-10 | IS-09 | 분리 도입 통제 수단 동등성 | 라운드 71 | 후속 조치 비평에서 분리 완료 실행과 산출물 실행은 각각 GitHub에 연결되지만 집계의 배포 통제 수단과 비교되지 않는 문제를 확인했습니다. 이제 증명 검증기는 완료 작업 흐름 헤드, 산출물 작업 흐름 헤드 및 산출물 rollback-reference 통제 수단 커밋이 집계 통제 수단과 deployment-input-equivalent 상태를 유지하도록 요구합니다. 이를 통해 release-only 커밋은 허용하면서 materially different 이행, 작업 흐름, infrastructure 또는 의존성 통제 수단을 조합한 도입 증명은 거부합니다. |
| 2026-08-10 | IS-09 | Historical 도입 ancestry correction | 라운드 72 | Executable 검토에서 final-control 동등성을 요구하면 이후 롤아웃 강화가 배포 입력을 변경했기 때문에 valid one-time 도입도 거부됨을 확인했습니다. 이제 도입 근거는 cited 개정 번호 3개가 모두 최종 protected-main 통제 수단 커밋의 ancestor일 것을 요구합니다. Exact GitHub 실행, successful 단계, 산출물 다이제스트, 스키마 지문 및 rollback-reference 연결은 계속 필수이며 historical 통제 수단과 최종 통제 수단이 equivalent라는 잘못된 주장만 제거합니다. 최종 전이 계획은 계속 deployment-input 동등성을 요구합니다. |
| 2026-08-10 | IS-09 | Observable sidecar 탐색 정규화 | 라운드 73 | 워커 적용 `31361034521`은 healthy N 개정 번호에 도달했지만 검증이 빈 헤더 및 경로와 zero delay 같은 Terraform 프로바이더 기본값을 해시했고 Azure Resource Manager는 해당 기본값을 생략했습니다. 이제 계획 봉인은 ARM이 생략하는 exact 기본값 값만 제거하고 hashing 전에 알 수 없음 탐색 필드를 거부합니다. Non-default 임계값, delay, 간격, 시간 초과, 전송 계층 및 포트는 계속 seal되며 관찰된 개정 번호와 정확히 일치해야 합니다. |
| 2026-08-10 | IS-09 | 범위가 제한된 롤백 개정 번호 접미사 | 라운드 74 | 동일한 워커 실패에서 verbose automatic 롤백 접미사가 가장 긴 서비스 이름에 대한 Azure Container App combined 54-character revision-name 한도를 초과하여 복구를 시작할 수 없는 문제를 확인했습니다. 이제 롤백 접미사는 lowercase `r` 접두사와 unique 작업 흐름 실행 id로 구성됩니다. 모든 정본 서비스 이름에 맞으면서 결정론적하고 collision-resistant하며, 롤백은 계속 exact captured 개정 번호만 copy하고 restored 이미지와 sidecar 계약을 검증합니다. |
| 2026-08-10 | IS-09 | Corrected N-1 산출물 재구축 | 라운드 75 | 실제 운영 롤백에서 original 0.1.2 문서 이미지가 연결된 user-assigned 신원을 선택할 수 없어 protected 토폴로지에서 준비된 상태가 될 수 없음을 확인했습니다. 이제 dedicated artifact-only 출처가 현재 신원, 탐색 및 복구 강화가 적용된 서비스 코드에서 분포 5개의 0.1.2 산출물을 다시 빌드합니다. 출처는 temporary이며 즉시 0.1.3 개발 줄을 복원하는 커밋이 이어집니다. 최종 근거는 broken 이미지를 relabel하지 않고 exact 0.1.2 출처, supply-chain 실행, 이미지 다이제스트 및 증명을 고정합니다. |
| 2026-08-10 | IS-09 | N-1 재정의 retirement | 라운드 76 | Supply-chain 실행 `31367288968`은 tracked 재정의가 활성인 exact 출처 `352c8d1e661a6a53f0958767550fd57c2b975706`에서 성공했으므로 변경할 수 없는 산출물은 계속 0.1.2입니다. 이후 실행 `31367329056`은 automatic release 커밋에 속하며 재정의 출처 이후 실패했습니다. 이제 `main`에서 재정의는 inactive이며 이후 모든 이미지 빌드는 committed 0.1.3 서비스 및 lockfile 버전을 사용합니다. 이를 통해 patched N-1과 최종 N에 서로 다른하고 attributable한 출처 개정 번호를 만들고 향후 0.1.2 산출물이 실수로 publish되는 것을 방지합니다. |
| 2026-08-10 | IS-09 | Corrected 원격 release 연결 | 라운드 77 | release 계약은 이제 원격 N-1을 corrected 출처 `352c8d1e661a6a53f0958767550fd57c2b975706`에 연결하고 historical local-focused N-1 출처 `9f1234f93d356dedbddcb3b88aa7bc4da38b2dc2`는 별도 필드에 유지합니다. Corrected 0.1.2 SBOM 5개가 intended 서비스 패키지 버전을 보고하며 출처 이력, SBOM 및 Core resolved-model 증명이 exact 출처와 protected supply-chain 서명자에 대해 verify되었습니다. |
| 2026-08-10 | IS-09 | Per-run 배포 통제 수단 | 라운드 78 | Final-proof 비평에서 initial N 실행과 corrected 롤백 실행이 서로 다른 protected-main 개정 번호를 사용하므로 집계 통제 수단 SHA 하나만 강제하면 valid 근거를 거부하거나 이력을 잘못 표현하는 문제를 확인했습니다. 이제 원격 근거는 각 계획/적용 쌍에 plan-sealed 통제 수단을 기록하고 적용 통제 수단이 해당 계획과 일치하도록 요구합니다. GitHub 연결기는 API-bound 작업 흐름 헤드와 artifact-bound 통제 수단 개정 번호 각각이 집계 통제 수단과 deployment-input-equivalent임을 증명합니다. Final-evidence 동등성은 artifact-only image-build 재정의 보조 로직만 제외하며 모든 service-deploy 계획/적용 입력은 계속 strict하게 검사합니다. |
| 2026-08-10 | IS-09 | Controls-verifier 커버리지 | 라운드 79 | 후속 조치 비평에서 unique 전이 작업 흐름 헤드와 plan-sealed 통제 수단 개정 번호가 모두 동등성 검증기에 도달하는 executable 검사를 추가했습니다. 이 검사는 단계별 서로 다른 통제 수단과 중복 제거도 검증합니다. One-time 도입은 도입 이후 롤아웃 강화가 배포 입력을 의도적으로 변경했으므로 ancestry-bound 상태를 유지합니다. Exact 실행, successful 단계, 산출물 및 롤백 통제 수단은 계속 독립적으로 연결됩니다. High 및 Medium 심각도 잔여는 0건입니다. |
| 2026-08-10 | IS-09 | Evidence-only 비교기 separation | 라운드 80 | Executable 검토에서 service-deploy 비교기에 exception을 추가하면 비교기 자체가 historical initial 통제 수단과 달라져 동등성 주장이 self-defeating 상태가 되고 적용 경계도 약해지는 문제를 확인했습니다. Service-deploy 비교기를 byte-for-byte strict 양식으로 복원했습니다. 별도 final-evidence 비교기는 supply-chain 보조 로직만 제외하고 루트 release 버전만 normalize하며 그 밖의 작업 흐름, 보조 로직, Terraform, 이행, 의존성 또는 잠금 변경을 모두 거부합니다. Focused 테스트가 두 경계를 증명하며 High 및 Medium 심각도 잔여는 계속 0건입니다. |
| 2026-08-10 | IS-09 | 증명 작업 흐름 가져오기 경로 | 라운드 81 | Clean 실행기 실행에서 `remote-evidence-attest.yml`의 plain Python 항목 지점 2개가 저장소 루트를 모듈 검색 경로에서 찾지 못해 검증 전에 `ModuleNotFoundError`로 실패하는 문제를 재현했습니다. 이제 exact protected 체크아웃을 job-level Python 경로로 사용하며 작업 흐름 계약 테스트가 이 연결을 고정합니다. 집계 및 GitHub 연결기 동작은 변경하지 않았고 저장소 가져오기가 없으면 증명 전에 계속 실패합니다. |
| 2026-08-10 | IS-09 | 복구 이미지 상태 alignment | 라운드 82 | Fresh 인제스트 계획 `31376583061`은 out-of-band automatic 복구가 실제 운영 이미지와 computed 개정 번호 메타데이터를 변경했지만 Terraform 상태는 복구 전 이미지를 유지하여 실패 시 차단했습니다. 이제 계획 가드는 관찰된 이미지가 이미 attested된 planned-before 이미지와 같고 나머지 차이가 computed 개정 번호 이름, FQDN 및 접미사뿐인 경우에만 이 형태를 허용합니다. 다른 이미지 또는 런타임, 신원, 시크릿, platform, 권한 변경은 계속 차단합니다. |
| 2026-08-10 | IS-09 | 최종 근거 계약 강화 | 라운드 83-84 | 라운드 83은 closed 공개 매니페스트 변환 결과를 원격 deployment-context 검사와 분리하여 범용 로컬 근거 키가 집계 생성을 차단하지 않도록 했습니다. 라운드 84는 한 서비스의 initial N 계획과 restored N 계획이 변경할 수 없는 맥락을 의도적으로 공유하지만 fresh 개정 번호 접미사로 서로 다른 계획 다이제스트를 생성함을 증명했습니다. 이제 검증기는 동일한 서비스와 release에서만 맥락 재사용을 허용하며 서비스 간 또는 cross-release 재사용, stale 적용 연결 및 중복 계획 다이제스트는 계속 차단합니다. Focused 회귀가 통과했고 High 또는 Medium 심각도 잔여는 0건입니다. |
| 2026-08-10 | IS-09 | 산출물 redirect 자격 증명 경계 | 라운드 85 | 실제 운영 GitHub 검증에서 API bearer 토큰이 산출물 redirect를 따라 GitHub Actions 블롭 저장소로 전달될 때 401이 발생하는 문제를 재현했습니다. 이제 downloader는 정확한 HTTPS Actions 산출물 호스트 pattern만 허용하고 signed redirect를 따르기 전에 API 권한 확인을 제거합니다. 신뢰할 수 없는 redirect 출처는 실패 시 차단하며 focused 테스트에서 High 및 Medium 심각도 잔여는 0건을 유지합니다. |
| 2026-08-10 | IS-09 | Privileged 작업 흐름 가드 호환성 | 라운드 86 | Central 검증은 처음에 portable `diff --brief` exact-source 비교를 거부했습니다. 계약이 GNU 차이에서 지원하지 않는 `diff --quiet`만 인식했기 때문입니다. 이제 계약은 protected 작업 흐름 경로, 출처, ancestry 및 operand 검사를 유지하면서 portable exact-comparison 플래그를 허용합니다. Focused 검증이 통과했고 High 또는 Medium 심각도 잔여는 0건입니다. |
| 2026-08-10 | IS-09 | Program-final 원격 증명 | 라운드 87 | Fresh initial N 적용 5개, corrected N-1 롤백 적용 5개 및 restored N 적용 5개가 직렬로 완료되어 protected 계획 15개, protected 적용 15개, peer-isolation 증적 30개 및 genuine kind-specific 실제 운영 관측을 확보했습니다. GitHub 실행 `31385698545`가 모든 실행과 산출물을 연결하고 이미지 증명과 통제 수단 동등성을 검증한 뒤 exact 근거 출처 `a721d1ae587af73b8f32986fe3b54acaae400b63`를 attest했습니다. Portable 번들이 protected 서명자에 대해 verify되었고 accepted 원격 근거는 5/5이며 IS-09는 completed 상태이고 High 또는 Medium 심각도 잔여는 0건입니다. |
| 2026-08-10 | IS-09 | Strict 완료 검사기 typing | 라운드 88 | 최종 focused 검증에서 dynamically loaded live-evidence 빌더가 런타임 검증으로 exact 튜플 형태를 이미 요구하지만 completion-checker 경계에서는 `Any`를 반환하는 문제를 확인했습니다. 이제 검사기는 검증된 return 계약만 cast하며 strict mypy가 통과하고 High 또는 Medium 심각도 잔여는 계속 0건입니다. |
| 2026-08-10 | IS-09 | 완료 후 decomposition assurance | 라운드 89-108 | 독립 검토 라운드 20회에서 physical 소유권, 금지된 구현 가져오기, 신원과 쓰기 담당 격리, 타입이 지정된 전송 계층, 재시작 및 멱등성 행동, 상태 경계, 이행, Terraform 루트 5개, N/N-1 정렬, 롤백, peer 격리 및 증명된 완료 근거를 다시 확인했습니다. 의심된 실행기 defect 5건을 다음 근거로 반증했습니다. Core 클라이언트 인스턴스 id는 로컬 asyncio 작업 라벨에만 사용됩니다. 생성되는 모든 그림자 증적은 영속 감사 참조를 포함하며 enforce-mode `1.0.0` 증적은 효과 없이 거부만 할 수 있습니다. `/live`는 프로세스 생존을 보고하고 `/ready`는 최신 receipt-outbox 게시를 포함합니다. 호환성 매니페스트는 Core 롤백 전에 실행기 N-1을 요구하고 실행기 이행 전에 Core N을 요구합니다. 도입 근거는 이후 작업 흐름 상태 검사가 실패한 경우에도 정확히 성공한 산출물 단계와 이행 단계를 별도로 연결합니다. Independent-service 및 focused 호환성 게이트 통과 후 계약, 근거, 서비스 focused 테스트 351개가 통과했습니다. 재현 가능한 Medium 이상 잔여는 없습니다. 문서 서비스 구현 양쪽을 함께 사용하는 인제스트 service-local 테스트 모듈 2개는 Low test-ownership 정리로 남습니다. 이 테스트는 운영 분포에 포함되지 않고 런타임 의존성을 만들지 않습니다. |

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 승격, 소유권, 롤백 게이트 | [서비스 승격과 데이터 소유권](service-graduation-and-ownership-ko.md) |
| 저장소 패키지 경계 | [프로젝트 구조](project-structure-ko.md) |
| Azure 런타임과 신원 배포 | [배포 및 온보딩](../deployment/deploy-and-onboard-ko.md) |
| Operating 온톨로지 release 경계 | [운영 온톨로지 플랫폼](operating-ontology-platform-ko.md) |
| Operator 패키지 소유권 | [Operator Console 모듈 지도](../interfaces/operator-console-module-map-ko.md) |
