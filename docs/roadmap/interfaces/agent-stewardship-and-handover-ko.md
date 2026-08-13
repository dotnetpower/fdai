---
translation_of: agent-stewardship-and-handover.md
translation_source_sha: 4b216f3c867ca61fa024428eb0cb34d4639c6ade
translation_revised: 2026-08-13
title: 에이전트 스튜어드십과 인수인계
---
# 에이전트 스튜어드십과 인수인계

기존에 운영 업무를 하던 사람들을 FDAI의 15-에이전트 판테온에 매핑하는 방법을 정의한다.
FDAI가 어떤 업무를 넘겨받을 때, 각 에이전트 뒤에 에스컬레이션, 리뷰, 지식 인수인계를
책임지는 사람이 반드시 지정되도록 하기 위함이다.

이것은 [user-rbac-and-identity.md](user-rbac-and-identity-ko.md)와는 **다른 축**이다.
RBAC은 "누가 FDAI를 조작할 수 있나"(읽기 담당 / 기여자 / Approver / Owner)에 답하고,
스튜어드십은 "FDAI 이전에 이 업무를 누가 소유했고, 이제 이 에이전트의 도메인을 누가
책임지나"에 답한다. 한 사람이 보통 두 모델 모두에 속하지만(Var의 담당자이면서 Approver인
사람처럼), 두 모델은 독립적으로 해석되고 검증된다.

> Customer-agnostic: 아래의 모든 objectId, 그룹 id, 이름은 **자리 표시자**(all-zero UUID)다.
> 배포 구성이 실제 Entra 값을 제공합니다.
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 담당 체계 스키마, 해석기, 판테온 동등성 | implemented | `services/core-control-plane/src/fdai/core/stewardship/`; `services/core-control-plane/tests/core/stewardship/test_resolver.py`; `test_pantheon_parity.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/stewardship` (71 passed) | 스키마 v1을 계속 읽을 수 있고, 스키마 v2는 순서가 있는 임무를 보존하며, 유효하지 않거나 불완전한 매핑은 실패 시 차단됩니다. |
| 스키마 v2 마이그레이션 | implemented | `scripts/governance/migrate-stewardship-v2.py`; `services/core-control-plane/tests/core/stewardship/test_migration.py` | 마이그레이션은 검토 가능한 후보를 렌더링하고 활성 지도를 인플레이스 방식으로 수정하지 않습니다. |
| 범위, 에스컬레이션, 알림 기본 요소 | implemented | `services/core-control-plane/src/fdai/core/stewardship/coverage.py`; `escalation.py`; `notify.py`; 집중 담당 체계 테스트 모음 (71 passed) | 이 결정론적 기본 요소는 발견 사항과 수신자를 계산합니다. 런타임 스케줄링과 전달은 수명 주기 소유 문서에서 다룹니다. |
| 근거 기반 담당자 인수인계 부트스트랩 | implemented | `services/core-control-plane/src/fdai/core/stewardship/handover_bootstrap/`; 집중 담당 체계 테스트 모음 (71 passed) | 정확한 추출과 검토 보류 동작이 있습니다. 적응형 해석기는 선택적 배포 바인딩으로 남아 있습니다. |
| 일반 업스트림 인수인계 지도 | implemented | `config/agent-stewardship.yaml`; `bash scripts/governance/check-stewardship.sh` (15 agents, 2 maintainers) | 추적되는 지도는 의도적으로 자리 표시자 신원과 스키마 v1을 사용합니다. 일반 구조를 입증하지만 배포 준비 상태나 실제 백업 범위를 입증하지는 않습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-13 | implemented | 이전 출처를 재구성하지 않고 구현 원장을 도입했으며 이 문서의 범위를 스키마, 결정론적 담당 체계 기본 요소, 마이그레이션, 인수인계 부트스트랩으로 한정했습니다. | `current change`; 구현 범위 표에 나열된 담당 체계 소스와 집중 검사. | 업스트림 저장소에 테넌트 신원을 넣지 않고 배포별 스키마 v2 `primary` 및 `backup` 범위를 기록합니다. |

### 남은 작업

- [ ] 업스트림 지도를 고객 독립적 상태로 유지하면서, 자율 운영이 아닌 모든 에이전트에 대해 스키마 v2, 실제 `primary` 1명, 구별되는 실제 `backup` 또는 `escalation` 대상 1명을 보여 주는 관리형 배포 증적을 보존합니다.
- [ ] 적응형 해석을 운영에서 사용할 수 있다고 설명하기 전에 `HandoverInterpreter` 배포 바인딩의 집중 근거를 기록합니다.

## 1. 설계 원칙

1. **오버레이일 뿐, 재지정이 아니다.** 스튜어드십은 사람을 에이전트에 매핑하되 오직 책임과
   통보 목적이다. 판테온의 어떤 `ActionType` 역할 바인딩도 바꾸면 안 된다. fork-locked 5개
   필드(`initiators`, `judge`, `executor`, `approver`, `auditor`)는
   [agent-pantheon.md](../agents/agent-pantheon.md)가 선언한 그대로 유지된다. 담당자라고 해서
   실행기 신원을 부여받지 않는다.
2. **에이전트당 여러 사람.** 한 역할을 여러 명이 맡을 수 있다. 모든 에이전트는 단일 소유자가
   아니라 담당자 **리스트**(개인 Entra OID 및/또는 Entra 그룹 objectId)에 매핑된다.
3. **관리자 하한선.** FDAI 자체에도 지정된 소유자가 필요하다. 관리자는 최소 **1명**
   (fail-fast), **2명** 권장(warn)이다. 관리자는 실제 운영 담당자가 없는 에이전트의 최종
   에스컬레이션 대상이다.
4. **사람 쪽으로 실패한다.** 미매핑 에이전트, stale 담당자 OID, 관리자 부재는 "조용히
   무소유"가 아니라 "관리자로 에스컬레이션"으로 degrade된다.
5. **콘솔은 지도를 직접 변경하지 않는다.** 스튜어드십 변환 결과는 읽기 전용을 유지합니다.
  Guided 등록 양식은 구조화된 `handover_bootstrap` 문서를 인제스트 경계에
  제출하고, GitHub App은 다른 모든 거버넌스 변경과 동일하게 결과를 초안 PR로 작성합니다
   ([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)).
6. **모든 변경은 통보되고 감사되어야 한다.** Core는 recipient와 감사 페이로드를 결정론적으로
  계산합니다. 실제 운영 PR/병합 통합은 이 기본 요소를 알림/감사 어댑터에 배선해야 합니다.
7. **자율 운영은 담당 체계의 대안입니다.** `accept_autonomous`는 에이전트에 accountable 소유자가
  없을 때만 유효합니다. 둘을 함께 선언하면 서로 모순된 에스컬레이션 경로가 생기므로 구성이
  수락되지 않습니다.

## 2. 개념과 용어

코드, 구성, 문서에서 아래 용어를 그대로 재사용한다.

| 용어 | 의미 |
|------|------|
| **agent-steward** | 어떤 에이전트의 도메인을 책임지는 사람(또는 팀). FDAI 이전에 이 업무를 하던 사람으로, 이제 에이전트를 감독하고 그 에스컬레이션을 받는다. |
| **handover-map** | 15개 판테온 에이전트 전부를 담당자에 매핑한 전체. 온보딩 인수인계의 산출물이다. |
| **관리자** | FDAI 플랫폼 자체를 책임지는 사람. 최소 1명(hard), 권장 2명(warn). 미매핑 에이전트의 최종 에스컬레이션. |
| **responsibility (RACI-lite)** | 각 담당자 항목은 `accountable` 또는 `informed`로 태깅된다. 모든 에이전트는 `accept_autonomous`가 아닌 한 최소 하나의 `accountable` 담당자를 가져야 한다. |
| **임무** | Accountable 소유자 내부의 스키마 v2 순서입니다. `primary`, `backup`, `escalation`을 사용하며 informed 대상에는 임무가 없습니다. |
| **accept_autonomous** | 도메인 담당자 없이 완전 자율로 도는 에이전트임을 명시적으로 인정하는 것. 에스컬레이션은 관리자로 폴백한다. `reason`이 필요하다. |
| **escalation-chain** | 에이전트의 순서 있는 통보 경로: `accountable` 담당자 -> `informed` 담당자 -> 관리자, 홉별 시간 초과 적용. |
| **bus-factor** | 어떤 에이전트의 도메인을 아는 서로 다른 `accountable` 사람의 수. bus-factor 1은 추적되는 리스크(warn)다. |

### 전체 RACI가 아니라 RACI-lite

전체 RACI(Responsible / Accountable / Consulted / Informed)는 인수인계에 필요한 것보다 많고
불필요한 논쟁을 부른다. 이 모델은 태그 2개만 둔다:

- **accountable** - 에스컬레이션 hot 경로 위에 있음. 가장 먼저 페이징됨. 행동하거나 위임할 수
  있는 사람이어야 한다.
- **informed** - 인지 목적으로 통보됨(변경 통보, 사후). 첫 에스컬레이션 홉에는 없다.

"Responsible"은 에이전트 자체로 수렴하고(FDAI가 업무를 수행), "Consulted"는 `informed`로
수렴한다.

## 3. RBAC 및 notifications와의 관계

```text
                 who may operate FDAI            who owns the work
                 (user-rbac-and-identity)        (this doc)
 human  ------>  Role: Reader/Contributor/    +   Steward-of: {agents...}
                 Approver/Owner/BreakGlass         responsibility: accountable|informed
                        |                                   |
                        v                                   v
                 capability gate                    escalation + change-notify
                 (core/rbac)                         (core/stewardship -> core/notifications)
```

- **RBAC은 행동을 게이트한다**(이 사람이 애초에 HIL 요청을 승인할 수 있나?).
- **스튜어드십은 통보를 라우팅한다**(*이* 에이전트에 대해 어떤 사람이 먼저 페이징되나?).
- HIL 요청 승인을 위해 페이징된 담당자도 여전히 RBAC `Approver` 기능 체크와
  no-self-approval 체크를 통과한다. 담당자라는 사실만으로는 승인 권한이 부여되지 않는다.

## 4. 데이터 모델

### 4.1 구성 아티팩트

`config/agent-stewardship.yaml`에서 새 배포 지도는 버전 2를 사용합니다. Tracked 업스트림
호환성 지도는 배포가 실제로 서로 다른 백업을 공급할 때까지 버전 1을 유지합니다.

```yaml
stewardship:
  version: 2

  # FDAI platform owners. Min 1 (fail-fast), rec 2 (warn on 1).
  maintainers:
    - oid: "00000000-0000-0000-0000-000000000000"   # Entra user objectId
    - oid: "00000000-0000-0000-0000-000000000000"

  # Optional per-person notification channel binding (person OID -> channel-id
  # known to notifications-matrix.yaml). Missing entries fall back to the
  # agent's category route in the matrix.
  channels:
    "00000000-0000-0000-0000-000000000000": teams-hil-prd

  # Escalation timing (seconds per hop before advancing to the next tier).
  escalation:
    hop_timeout_seconds: 900        # accountable -> informed -> maintainer

  # All 15 pantheon agents MUST appear. A subject is a personal OID or an
  # Accountable entries declare duty: primary|backup|escalation.
  # Informed entries have no duty.
  agents:
    Odin:
      stewards:
        - { kind: user,  id: "00000000-0000-0000-0000-000000000000", responsibility: accountable, duty: primary }
        - { kind: user,  id: "00000000-0000-0000-0000-000000000001", responsibility: accountable, duty: backup }
        - { kind: group, id: "00000000-0000-0000-0000-000000000000", responsibility: informed }
    Thor:
      stewards:
        - { kind: user,  id: "00000000-0000-0000-0000-000000000000", responsibility: accountable, duty: primary }
        - { kind: user,  id: "00000000-0000-0000-0000-000000000001", responsibility: accountable, duty: escalation }
    Loki:
      accept_autonomous:
        reason: "Chaos proposals are always HIL; no standing domain owner."
      stewards: []
    # ... all 15: Odin, Thor, Forseti, Huginn, Heimdall, Vidar, Var, Bragi,
    #     Saga, Mimir, Muninn, Norns, Njord, Freyr, Loki
```

### 4.2 Env-var 오버라이드

포크는 YAML을 편집하지 않고 단일 슬롯만 오버라이드할 수 있다(rbac-groups 패턴과 동일):

| Env var | 효과 |
|---------|------|
| `FDAI_MAINTAINERS` | 콤마로 구분된 OID들. `maintainers` 리스트를 대체한다. |
| `FDAI_STEWARD_<AGENT>` | v2에서는 콤마로 구분된 `kind:<oid>:responsibility:duty` 토큰입니다. v1에서는 responsibility를 생략할 수 있고 임무는 사용하지 않습니다. |

### 4.3 호환성과 마이그레이션

로더는 버전 1과 2를 허용합니다. v1에서는 첫 accountable 대상을 기본, 이후 대상을
백업으로 유도합니다. 런타임 동작은 유지하지만 `duty_derived`와 두 번째 대상이 없을 때
`backup_missing` 발견 사항을 냅니다. 버전 2는 임무를 명시해야 하며, non-autonomous 에이전트에
기본과 서로 다른 백업 또는 에스컬레이션 대상이 없으면 거부합니다.

`uv run python scripts/governance/migrate-stewardship-v2.py`를 실행하면 후보를 stdout으로
렌더링하며 `--output <new-path>`도 사용할 수 있습니다. 입력 파일은 직접 편집하지 않습니다. 한
accountable 대상만 있는 에이전트가 있으면 사람을 임의로 선택하지 않고 해당 에이전트를 나열한 뒤
중지합니다.

### 4.4 에이전트 이름 정합성

`agents:` 아래 15개 키는 정확히 판테온 이름이어야 한다. `core/stewardship`은 자체 정본
`AGENT_NAMES` 튜플을 두고, 동등성 테스트
(`services/core-control-plane/tests/core/stewardship/test_pantheon_parity.py`)가 이를
`fdai.agents._framework.pantheon.PANTHEON_NAMES`에 고정하므로, 구성 스키마와 판테온은 절대
표류할 수 없다. `core/`는 `agents/`를 가져오기하지 않으며(module-boundary 규칙), 동등성 테스트가
테스트 시점에 둘을 연결한다.

## 5. FDAI 유지관리자 규칙

- **하한선(fail-fast):** 관리자 0명은 시작 `ValueError`다. FDAI는 스튜어드십 레이어를
  무소유 상태로 부팅하지 않는다.
- **권장(warn):** 관리자가 정확히 1명이면 `stewardship_maintainer_single` 경고를 남기고
  콘솔 배너를 띄운다. 2명 이상은 clean.
- **승계:** 관리자 OID가 stale해지고(Entra에서 제거, 7.3 참조) 실제 운영 수가 1로 떨어지면 경고가
  **hard 배너**로 격상되어 Owner에게 후임 지정을 요청한다. 제어 루프를 막지는 않지만 clean 검증
  상태를 막는다.
- **최종 에스컬레이션:** 실제 운영 담당자가 0명으로 해석되는 에이전트는 에스컬레이션을 관리자
  집합으로 라우팅한다.

## 6. 런타임 효과: 통보와 에스컬레이션 (결정 B)

스튜어드십은 [channels-and-notifications](channels-and-notifications-ko.md)에 연결되어, 에이전트의
도메인 담당자가 그 에이전트 이벤트에 대해 먼저 통보받도록 한다.

### 6.1 에스컬레이션 체인

사람이 필요한 에이전트 이벤트(HIL 요청, degraded 상태, 워크플로우 변경 요청)에 대해
`core/stewardship`은 순서 있는 수신자 리스트를 만든다:

1. 에이전트의 기본 accountable 담당자,
2. 그다음 백업 accountable 담당자,
3. 그다음 도메인 에스컬레이션 담당자,
4. 그다음 informed 담당자,
5. 그다음 관리자 집합.

계획은 각 person 계층의 `hop_timeout_seconds` 힌트를 포함합니다. 담당 체계는 recipient 정렬을
소유하지만 human non-response timer를 소유하지 않습니다. 채널 전달 실패는 notifications
매트릭스의 `on_all_fail: hil_escalate`를 사용합니다. 전달 성공 후 human 결정이 없을 때의
처리는 별도 [에스컬레이션 및 상시 권한](../decisioning/escalation-and-standing-authority-ko.md)
supervisor가 소유합니다. 주기적 shadow 틱은 recipient 단계 구조를 진행하지 않고 due 관측만
기록합니다.

### 6.2 사람 -> 채널 브릿지

notifications 매트릭스는 **channel-id**로 라우팅하지만 담당자는 **사람**이다. 브릿지는 순서대로
해석한다:

1. `agent-stewardship.yaml`의 명시적 `channels[<oid>]` 바인딩,
2. 없으면 `notifications-matrix.yaml`의 에이전트 카테고리 경로(그 사람은 도메인 채널로 도달됨).

`kind: group` 담당자는 항상 매트릭스 카테고리 경로로 해석된다(그룹은 단일 개인 채널이 없다).

### 6.3 그룹 책임 담당자

`kind: group` 담당자는 "이 Entra 그룹에 속한 누구든 담당자"를 뜻한다. 해석기는 주입된
`GroupMembershipProvider`(포크에서는 Graph 기반, 테스트에서는 static)를 통해 그룹 멤버로 확장한다.
확장은 최선 노력다: 프로바이더가 사용 불가면 그룹을 하나의 불투명한 `accountable` 단위로 취급해
도메인 채널로 라우팅하고 경고를 남긴다. 제어 루프는 Graph에서 절대 블록되지 않는다.

## 7. 검증 게이트 (검증 표면)

인수인계 정확성은 안전과 관련되므로 검증을 계층화한다.

### 7.1 로더 fail-fast (`load_stewardship_from_mapping`)

Hard 에러(`StewardshipValidationError` 발생, 레이어의 clean 부팅 차단):

- `1` 또는 `2`가 아닌 스키마 `version`,
- 관리자 1명 미만,
- 중복 real 관리자 OID 또는 중복 담당자 대상,
- `agents:` 블록이 15개 판테온 이름 중 하나라도 누락하거나 알 수 없는 에이전트를 지정,
- `accountable` 담당자도 없고 `accept_autonomous`도 없는 에이전트,
- `reason` 없는 `accept_autonomous`,
- 잘못된 대상(`kind`가 {user, 그룹}에 없거나 id가 UUID 형태가 아님),
- v2에서 valid 임무가 없는 accountable 대상, 임무가 있는 informed 대상, 또는 기본과
  서로 다른 백업/에스컬레이션 커버리지가 없는 non-autonomous 에이전트,
- UUID가 아닌 personal-channel 키, malformed 환경 토큰, forbidden pantheon 역할 필드,
- `FDAI_STEWARDSHIP_REQUIRE_BINDINGS=1`일 때 담당자나 관리자 id가 all-zero 자리 표시자로
  남아 있습니다. 담당 체계 지도를 연결하는 모든 deployed 환경은 이 플래그를 명시적으로
  설정해야 하며 포크 여부와 관계없습니다.

### 7.2 Non-blocking 발견 (warn, 커버리지 리포트에 노출)

- 관리자가 정확히 1명(`maintainer_single`),
- bus-factor(서로 다른 accountable 사람)가 1인 에이전트(`bus_factor_one`),
- 임무가 유도되는 v1 에이전트(`duty_derived`, 정보성),
- 유도된 백업이 없는 v1 에이전트(`backup_missing`),
- `N`개 초과 에이전트에 `accountable`인 사람(`over_assigned`, 기본 N=5, 설정 가능),
- `accept_autonomous`에 의존하는 에이전트(`autonomous_no_steward`, 정보성).

### 7.3 Stale-OID 감지

주입된 `IdentityDirectory`(포크에서는 Graph 기반, 테스트에서는 static)에게 각
관리자/담당자 OID가 여전히 활성 계정으로 해석되는지 확인한다. 없는 OID는 `stale_oid` 발견을
만들고 그 사람은 실제 운영 에스컬레이션에서 제거된다(다음 계층 / 관리자로 폴백). 이는 hot 경로
바깥(스케줄)에서 실행되며 제어 루프에서 절대 인라인으로 돌지 않습니다. 운영은
transition-only 발견 사항과 별도의 last-success 하트비트를 저장합니다. 읽기 전용 `/stewardship`
응답은 하트비트가 만료되지 않고 동일한 상태 개정 번호를 가리킬 때만 stale 발견 사항을
병합합니다.

### 7.4 CI 게이트 (`scripts/governance/check-stewardship.sh`)

`scripts/verify.sh`와 CI에서 실행:

- YAML이 파싱되고 15개 에이전트 이름이 모두 존재하며 정확히 표기됨(작은 Python 심으로
  `PANTHEON_NAMES`와 비교),
- 파일이 어떤 ActionType 역할 필드도 선언하려 하지 않음(grep 가드: 스튜어드십 파일은
  `executor:`/`judge:`/`approver:`/`initiators:`/`auditor:` 키를 포함하면 안 됨 - 이들은
  fork-locked 온톨로지에만 존재),
- 자리 표시자 정책: tracked 업스트림 구성은 all-zero 값을 사용하고 deployed 환경은
  `FDAI_STEWARDSHIP_REQUIRE_BINDINGS=1`을 통해 non-placeholder 연결을 요구합니다.

## 8. 워크플로우 변경 통보와 감사

"정의된 워크플로우"란 업무가 흐르는 방식을 인코딩한 모든 거버넌스 아티팩트다:
`rule-catalog/workflows/*.yaml`, `config/agent-stewardship.yaml`,
`config/notifications-matrix.yaml`. 누군가 이 중 하나를 변경하려 할 때:

아래 수명 주기는 구현되었습니다. 인제스트 게이트웨이는 근거에 기반한 인계 초안을 멱등적
거버넌스 PR로 변환합니다. Signed GitHub 웹훅은 changed 파일과 merged YAML을 다시 읽고 코어
recipient 및 감사 기본 요소로 수명 주기를 완료합니다.

1. **초안 PR.** 변경은 GitHub App이 초안 PR로 작성한다(콘솔은 직접 mutate하지 않음). 표준
   CODEOWNERS + no-self-approval + 정족수가 적용된다.
2. **이해관계자 통보.** `core/stewardship`은 영향받는 에이전트를 계산하고(워크플로우 파일은 그것이
   참조하는 에이전트, 스튜어드십 파일은 담당자가 바뀐 에이전트) 그들의 `accountable` +
   `informed` 담당자와 관리자에게 통보한다: "사람 X가 워크플로우 Y 변경을 요청함".
3. **감사.** Saga 추가 전용 `AuditEntry`가 행위자 신원, 아티팩트, before -> after 요약, 상관관계
   id, 타임스탬프, 승인 결정을 기록한다. 감사 항목은 L0 English이며 절대 억제되지 않는다.

이로써 루프가 닫힌다: 어떤 에이전트를 책임지는 바로 그 사람들이 그 에이전트를 지배하는
워크플로우가 바뀌려 할 때 통보받고, 변경은 영구히 기록된다.

## 9. Console 에이전트 oversight 표면

거버넌스 > 에이전트 oversight 경로는 읽기 전용 변환 결과와 통제된 제안 양식을 함께
제공합니다.

- **현재 담당 체계** - `GET /stewardship`에서 15개 에이전트, accountable 소유자, 알림 contact,
  백업 커버리지, 자율 상태, FDAI 관리자 개수, 검증 발견 사항을 표시합니다.
- **프로젝션 검증** - 브라우저는 지원되는 정수 스키마 버전, 음수가 아닌 정수 개수, 양수 시간 초과와
  배정 한도만 허용합니다. 고정 Pantheon 지도에서 집계 개수를 다시 계산하고,
  관리자 하한과 비어 있지 않은 exact 대상 참조를 요구합니다. 중복된 실제 관리자와
  중복된 exact 담당자 대상을 거부합니다. 불일치하면 상태를 추정해 표시하지 않고
  차단합니다. 버전 2 non-autonomous 변환 결과에는 기본과 서로 다른 백업 또는 에스컬레이션
  커버리지도 필요합니다.
- **발견 사항 검증** - 커버리지 발견 사항은 고정 코드와 심각도 용어를 사용하고, 에이전트가 있으면 고정
  Pantheon 에이전트만 참조합니다. 경고 발견 사항이 없을 때만 clean 상태로 계산합니다. 각 코드는
  심각도와 단일 에이전트 또는 전체 지도 범위도 고정합니다. 알 수 없거나 모순된 발견 사항은
  실패 시 차단으로 차단합니다.
- **담당자 등록** - 기여자, Approver, Owner는 정본 에이전트, 사람 또는 그룹의 display 이름이나
  이메일, 대상 종류, responsibility로 하나 이상의 행을 추가할 수 있습니다. 브라우저는 명시적인
  `agent`, `subject`, `identity`, `responsibility` tag를 생성하고 `handover_bootstrap` 텍스트 문서로
  제출합니다. 읽기 담당에게는 locked 안내를 표시합니다.
- **검토 결과** - 처리된 초안은 대응, 해결되지 않은 신원, unmapped 에이전트 개수, 생성된 YAML,
  거버넌스 전달이 활성화된일 때 멱등적 초안 PR 링크를 표시합니다.

SPA는 Git 자격 증명을 보유하지 않고 `config/agent-stewardship.yaml`을 직접 쓰지 않습니다.
인제스트 서비스가 신원을 해석하고 코어 해석기로 가산 후보를 validate한 다음 Owner가
검토할 초안 PR을 생성합니다. 로더는 관리자 1명 미만을 거부하고 콘솔은 2명 미만에 권장
배너를 표시합니다.

## 10. 보안과 안전

- 스튜어드십은 실행기 Managed Identity를 보유하거나 부여하지 않는다.
- Console 버튼은 제안을 제출할 수 있지만 지도 변경에는 감사되는 거버넌스 PR
  (작성자 != 승인자)과 병합이 계속 필요합니다.
- 담당자 OID는 라우팅과 감사에 쓰이는 유일한 신원이다. UPN/이메일은 정보성이며 절대 권위 있는
  값이 아니다(`Principal`과 동일 규칙).
- customer 식별 값은 이 repo에 들어오지 않는다. 포크가 실제 OID, 그룹 id, 채널 id를 구성나
  env로 공급한다.

## 11. 담당자 인수인계 부트스트랩 (문서 수집)

맵을 수동으로 채우는 대신, 오퍼레이터는 기존 운영 문서(RACI 매트릭스, 온콜 스케줄, 조직도,
런북, 인수인계 메모)를 업로드하고 FDAI가 이를 검토용 **초안** 담당자 맵으로 파싱하게 할 수
있다([issue #23](https://github.com/dotnetpower/fdai/issues/23)). 이는 위의 결정론적 코어 위에
얹은 더 크고 분리 가능한 기능이며, 아무것도 적용하지 않고 코어를 막지도 않는다.

`services/core-control-plane/src/fdai/core/stewardship/handover_bootstrap/` 아래에 결정론 우선, 근거 기반, 기권형
파이프라인으로 구현되어 있다:

1. **결정론적 추출** (`extractor.py` + `agent_domains.py`). 각 문서 라인을 에이전트별
   도메인 키워드 카탈로그(인계 스킬의 "누가 X를 소유했나" 질문, 판테온 에이전트마다 1개)에
   대조한다. 도메인 키워드 + 사람/팀 + 책임 마커를 맞춘 라인은 **모델 없이** 근거를 갖춘
  `ExtractedMapping`을 산출합니다. 등록 양식은
  `Agent: <name>; responsibility: <value>; subject: <kind>; identity: <display name>` 구조화된
  양식을 사용합니다. 이 필드들은 권위 있는하므로 신원 텍스트가 다른 에이전트를 추가하거나
  responsibility를 바꿀 수 없고 malformed 또는 알 수 없음 구조화된 배정은 무시됩니다. 이것이
  결정론 우선 단계입니다.
2. **모델 해석** (`interpreter.py`). 구조가 해결하지 못한 것은 T2 `HandoverInterpreter` 시임에
   넘길 수 있다. 업스트림은 `AbstainingInterpreter`(아무것도 제안하지 않음)를 기본 제공하므로
   LLM이 없는 배포는 절대 추측하지 않는다. 포크는 mixed-model 근거 기반 구현을 바인딩한다
   (`core/rca` reasoner 시임과 대칭). 근거 없는 모델 제안은 오케스트레이터가 폐기한다.
3. **신원 해석** (`people.py`). 언급된 각 이름/팀을 비동기 `PersonDirectory` 경계로
  Entra objectId에 해석합니다. 운영은 정확한 활성 user/그룹 display-name 일치가
  한 건일 때만 수락하고 0건 또는 모호한 결과에는 abstain하는 `GraphPersonDirectory`를
  연결합니다. 해석되지 않은 이름은 id로 **추측하지 않고 플래그**합니다. 로컬 기본값인
  `NullPersonDirectory`는 아무것도 해석하지 않습니다.
4. **신뢰도 플로어 + 초안 조립** (`bootstrap.py`). 플로어 이상의 근거 매핑은 초안이 되고,
   플로어 미만은 사람 검토용으로 따로 두며, 미해결 인물과 확실한 소유자가 없는 에이전트를
   표면화하고, 플로어를 넘긴 것이 없으면 기권한다. 출력은 `StewardMapDraft`다.

문서 인제스트 게이트웨이는 `handover_bootstrap`을 명시적 `DocumentPurpose`로 받습니다.
격리 구역, protection 검사, 추출이 끝나면 `DocumentIngestionWorker`가 안전한
`DocumentEnvelope`를 해당 용도에 주입된 `DocumentReadyConsumer`로 전달합니다. 업스트림
로컬과 운영 조립은 `HandoverBootstrapConsumer`를 연결하고 인증된
`GET /ingestion/uploads/{upload_id}/handover-draft`로 제공합니다. Console은 처리 상태를
polling하고 검토용 초안 요약, YAML, 저장된 거버넌스 PR 증적을 렌더링합니다. 지도를
적용하거나 privileged 변경 경로를 만들지 않습니다. 로컬 개발은 초안을 기억에 저장하고 운영은
`PostgresStateStore`를 사용하므로 워커 또는 게이트웨이 재시작 후에도 검토 산출물이
유지됩니다.
독립 로컬 ingestion service는 source와 derived 문서 object를 private filesystem root에
저장하고 loopback Redpanda로 lifecycle record를 교환합니다. 이 adapter는 저장소와 transport만
바꾸며 동일한 `HandoverBootstrapConsumer`가 accountable handover 경계로 유지됩니다.

인계 출처가 이미지이면 선택적 문서 Intelligence OCR도 동일한 agent-owned 인제스트
경로 안에 유지됩니다. `FDAI_OCR_OPERATION_TIMEOUT_SECONDS`는 제출, polling 및 poll delay
전체를 한계합니다. 시간 초과 또는 중복 페이지 위치 지정자는 추출을 실패시키고 초안 근거를
만들지 않습니다.

운영 Graph 호출은 게이트웨이 managed 신원과
`https://graph.microsoft.com/.default` 범위를 사용합니다. Exact 조회에 필요한 Microsoft
Graph 애플리케이션 권한인 `User.Read.All`과 `Group.Read.All`만 할당하고 정기적으로
검토하는 것이 좋습니다. 어댑터는 이름, 객체 id, 토큰, 프로바이더 응답 본문을 로그하지
않습니다. `FDAI_GRAPH_BASE_URL`은 테스트 또는 sovereign-cloud용 선택적 재정의이며 기본값은
공개 Graph v1.0 엔드포인트입니다.

모든 발행된 매핑은 소스 스팬(`SourceSpan`)을 인용하므로 근거 없는 것은 없다. `draft_yaml.py`는
초안을 `stewardship:` 형태의 YAML로 렌더링하며, 이는 동일한 해석기와 fail-fast 게이트를 통해
**`load_stewardship_from_mapping`으로 round-trip**된다(인라인 인용 주석 + 미해결 인물용
플레이스홀더 id 포함). 담당 체계 거버넌스가 활성화된이면 전달 계층은 그 YAML을
멱등적 거버넌스 초안 PR 하나로 publish합니다. 사람이 검토하고 병합하면 signed 병합
웹훅이 병합 감사를 작성하고 affected 소유자에게 알립니다. Console은 출처 제안을
제출할 수 있지만 resulting 지도를 적용할 수 없으며 어떤 지도도 자율 적용하지 않습니다. 전체
상태, 실패, 배포 계약은
[agent-stewardship-operations-ko.md](agent-stewardship-operations-ko.md)를 참조하세요.

남은 포크 연결은 결정론적 추출기가 해석하지 못한 구조를 근거에 기반한 T2로 해석하는
`HandoverInterpreter`입니다. 업스트림 운영은 mixed-model 연결을 명시적으로 공급하지
않으면 abstaining 구현을 유지하며 결정론적 추출과 Graph 해석은 계속
실행됩니다. 모든 경계는 비동기로 주입되고 `core/`는 cloud SDK나 HTTP 클라이언트를 갖지 않습니다.

## 12. 범위 밖 (별도 추적)

- 비-Azure 신원 공급자(TBD,
  [구현 Focus](../../../.github/copilot-instructions.md#implementation-focus-must) 참조).
