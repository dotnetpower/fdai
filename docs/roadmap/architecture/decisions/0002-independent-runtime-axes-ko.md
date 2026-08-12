---
title: ADR-0002 Independent Runtime and Customization Axes
translation_of: 0002-independent-runtime-axes.md
translation_source_sha: f19def30ae7a8f18549ffadaa6ea6d22bbeae168
translation_revised: 2026-08-12
---
# ADR-0002: 독립적인 런타임 및 Customization 축

이 기록은 FDAI가 어디서 실행되는지, 어떤 근거를 읽는지, 누가 동작할 수 있는지,
액션을 실행할 수 있는지, 다운스트림 분포를 어떻게 customize하는지를 결정하는
구성 축을 분리합니다. `local`, `dev`, `shadow`, `fork`가 서로의 별칭이 되는 것을
방지합니다.

## 상태

**Accepted:** 2026-07-20.

## 맥락

이전 design 텍스트는 여러 독립 관심사를 결합했습니다. 로컬 개발이 테스트 가짜 또는
shadow-only 행동을 의미하는 경우가 있었습니다. 다운스트림 포크도 운영 또는 customer
환경처럼 설명되는 경우가 많았습니다. Authentication 플래그는 브라우저 운영자, Azure 데이터
접근, privileged 실행기도 혼합했습니다.

이러한 shortcut은 production-parity debugging을 불가능하게 만들고 권한 확인 defect를
숨깁니다. 또한 포크가 실제 의미인 기능 제한 또는 확장 분포가 아니라 실행 위치나
운영 상태처럼 보이게 합니다.

## 결정

FDAI는 다음 축을 독립 구성으로 취급합니다.

| 축 | 대표 값 | 권한 |
|----|---------|-----------|
| 실행 위치 | `FDAI_EXECUTION_VENUE`를 통한 `local`, `deployed` | 프로세스 launcher |
| 배포 환경 | `dev`, `staging`, `production` | 배포 구성 |
| 근거 프로파일 | `authoritative`, `fixture` | 조립 루트 |
| 액션 수명 주기 | `shadow`, `enforce` | ActionType 및 작업 흐름별 승격 레지스트리 |
| 사용자 신원 | Entra principal 및 App 역할 | 브라우저 토큰 및 RBAC 정책 |
| 실행기 신원 | managed 워크로드 신원 | deployed 실행기 경계 |
| 권한 확인 정책 | Signed scoped 정책 번들 및 effective-access 근거 | execution-authorization 해석기 |
| 분포 | `upstream`, `fork` | 출처 및 customization 경계 |
| Operational 안전성 프로파일 | `mscp-operational-v1` | Versioned 코어 정책, 실행 권한 아님 |

어떤 축의 값도 다른 축의 값을 선택하지 않습니다. 특히 다음 계약을 적용합니다.

- 로컬 실행은 shadow 모드, 테스트 고정본, anonymous 권한 확인 또는 local-only business logic을
  강제하지 않습니다.
- 개발 배포는 운영과 같은 risk, 승인, blast-radius, 롤백, 감사 게이트를
  통과할 때 promoted 액션을 강제 적용 모드로 실행할 수 있습니다.
- 운영 배포도 어떤 액션이든 shadow 모드로 유지할 수 있습니다.
- 근거 프로파일은 출처 한계 및 잘림 사유를 타입이 지정된 값으로 보존합니다. 실행
  venue 또는 환경 변경으로 부분이나 사용 불가 근거가 완전한 근거로 바뀔 수 없습니다.
- 대화 경로 완료는 근거 권한이 아닙니다. 결정론적 assurance는 venue,
  환경 또는 답변 출처와 무관하게 비어 있지 않은 최종 근거 매니페스트를 요구합니다.
- Chat-policy 승격은 통계적으로 양수인 measured gain을 요구합니다. Venue, 환경 또는
  배포 기본값은 동점을 승격 근거로 바꿀 수 없습니다.
- 하나의 변경할 수 없는 read-investigation 의도 spec이 계획 ID, 도구 및 조회 구간을 소유합니다. 카탈로그
  ID와 계획 ID는 이 spec과 정확히 일치해야 하며 venue 또는 환경이 요청 시점에 누락 의미 규칙을 공급할 수 없습니다.
- 포크는 모든 환경에 배포가 없거나 여러 개 있을 수 있습니다. 업스트림도 직접
  deploy할 수 있습니다.
- 포크 detection은 업스트림 framework 표면을 보호합니다. 런타임 행동, 자율성, 신원,
  환경을 변경하지 않습니다.
- 권한 확인 정책과 effective-access 근거는 배포 입력입니다. 환경과 포크
  상태는 권한 부여 자세를 선택하거나 신원의 접근 권한을 암시하지 않습니다.
- Operational 안전성 프로파일은 실행 위치, 환경, 근거, 수명 주기, 신원 및
  분포와 독립적입니다. 프로파일 검사는 기존 자율성 결정을 유지하거나 낮출 수만
  있습니다.

### Interactive 로컬 프로파일

기본 interactive 로컬 프로파일은 production-parity control-plane 클라이언트 및 런타임입니다.

- 브라우저는 배포와 같은 Entra JWT 및 App 역할 검사를 사용합니다.
- Azure CLI 자격 증명은 개발 데이터 평면을 읽는 로컬 Azure 프로바이더 어댑터로 제한합니다.
  브라우저 principal 또는 실행기 신원을 대체하지 않습니다.
- 동일한 에이전트 pantheon, 카탈로그, 승격 레지스트리, risk 게이트, 프로세스 저널, 단계 이벤트를
  로컬에서도 실행합니다.
- 독립 패키지로 구성된 백엔드 서비스 5개를 별도 로컬 프로세스로 실행합니다. 상태 저장 서비스는
  Docker PostgreSQL의 역할 범위 DSN을 사용하고, 서비스 간 이벤트는 Docker Redpanda를 사용하며,
  문서 검사는 Docker ClamAV를 사용합니다. Azure CLI는 권위 있는 Azure 읽기 및 모델 adapter로만
  제한됩니다.
- Interactive 읽기 조사는 로컬과 deployed 환경에서 같은 execution-mode 정책을
  사용합니다. 측정된 프로바이더 지연 시간은 선택 모드를 바꿀 수 있지만 실행 venue 자체는 바꿀 수
  없습니다.
- Pantheon 시작은 기본 활성 상태입니다. `FDAI_START_PANTHEON`이 없으면 모든 에이전트를
  활성화하고 명시적인 false 값만 비활성화합니다. Event Hubs 구성은 Azure 전송 계층을
  선택하며 런타임 존재 여부를 결정하지 않습니다. Event Hubs가 없으면 로컬 프로세스 내
  EventBus가 에이전트 메시지와 상태를 전달하고 Azure 근거는 사용 불가 상태를 유지합니다.
- Privileged 실행은 Thor의 deployed managed 신원 뒤에 유지합니다. 로컬 프로세스는
  통제된 명령을 개발 이벤트 버스로 publish하며 developer 토큰으로 실행하지 않습니다.
- 로컬 격리 실행기는 managed resource identity 없이 영속 shadow receipt를 소비하고 기록합니다.
  Authority cutover를 설정하면 시작 단계에서 거부합니다. Azure 배포는 서비스 소유 Azure Database
  for PostgreSQL DSN, Event Hubs 및 연결된 managed identity를 사용합니다.
- 권위 있는 프로바이더가 없으면 사용 불가로 표시하거나 실패 시 차단합니다. 고정본을 선택하지
  않습니다.

Automated 테스트와 명시적인 mock 애플리케이션은 `fixture` 근거 프로파일을 선택할 수 있습니다.
Offline interactive 작업은 저장소 카탈로그 및 참조 화면으로 제한하며 런타임 점유를
만들지 않습니다.

### Shadow 및 승격

Shadow-first는 development-environment 정책이 아니라 기능 수명 주기 불변식입니다. 새
ActionType과 작업 흐름은 모든 위치에서 shadow로 시작합니다. 승격 근거를 통과한 후 모든
실행 위치는 같은 권위 있는 수명 주기 상태를 관찰합니다. 로컬 플래그는 액션을 promote할 수
없으며 로컬 실행은 risk 또는 승인 결정을 낮출 수 없습니다.

### 포크 경계

포크는 다운스트림 분포 customization 경계입니다. 다음 작업을 할 수 있습니다.

- 업스트림 프로바이더 프로토콜에 다른 구현을 연결합니다.
- 지원되는 경계를 통해 기능, 카탈로그, 정책, 표현 오버레이를 추가하거나 제거합니다.
- 업스트림 안전성 불변식을 유지하면서 더 좁거나 넓은 product 프로파일을 패키지합니다.

배포 값, 환경 이름, 테넌트 식별자, 시크릿, 런타임 승격 상태는 배포
구성입니다. 포크가 소유한 배포 저장소에서 제공할 수 있지만 이러한 값이
포크를 정의하지 않으며 포크도 운영을 의미하지 않습니다.

## 검토한 대안

| 대안 | 선택하지 않은 이유 |
|------|---------------------|
| 로컬을 shadow-only로 유지 | promoted 행동 및 RBAC의 종단 간 debugging을 막습니다. |
| 로컬 프로세스에 실행기 권한 부여 | 운영자와 실행기 신원을 합칩니다. |
| 모든 customer 배포를 포크로 취급 | 출처 분포를 tenancy 및 환경과 결합합니다. |
| Instruction만으로 축 보존 | 산문은 충돌하는 편집을 결정적으로 차단할 수 없습니다. |

## Consequence

- 로컬 시작은 기본적으로 실제 Entra, Azure data-plane 연결, 전용 개발 소비자
  신원이 필요합니다.
- 동일한 입력과 승격 상태에 대해 로컬 및 deployed 결정 스냅샷을 비교할 수 있습니다.
- 테스트 고정본에는 명시적인 pytest 또는 mock 프로파일이 필요합니다.
- Documentation 및 구성 키는 자신이 제어하는 축을 이름에 나타내야 합니다.
- Instruction 및 design-document 라우팅에는 기계가 읽는 매니페스트와 edit-time 게이트가
  필요합니다.
- 기존 `production fork`, `dev-mode fake`, 로컬 shadow-only 표현을 이행해야 합니다.

## 근거

- [애플리케이션 형태](../../../../.github/instructions/app-shape.instructions.md)
- [Dev/Deploy 동등성](../../deployment/dev-and-deploy-parity-ko.md)
- [User RBAC 및 신원](../../interfaces/user-rbac-and-identity-ko.md)
- [Operator-Initiated SRE 및 ARB](../../operations/operator-initiated-sre-and-arb-ko.md)
- [다운스트림 포크 Guide](../../fork-and-sequencing/downstream-fork-guide-ko.md)
- [`design-routes.json`](../../../../scripts/lib/design-routes.json)

## 다음 단계

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| Azure platform 기준선 | [ADR-0001](0001-azure-day-zero-platform-ko.md) |
| 런타임 조립 경계 | [Project Structure](../project-structure-ko.md) |
| ADR 프로세스 | [아키텍처 결정 기록](README-ko.md) |
