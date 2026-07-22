---
translation_of: agent-stewardship-and-handover.md
translation_source_sha: 145292a5251b1df8d28378cb1916b87ba51870a9
translation_revised: 2026-07-22
title: 에이전트 스튜어드십과 인수인계
---
# 에이전트 스튜어드십과 인수인계

기존에 운영 업무를 하던 사람들을 FDAI의 15-에이전트 판테온에 매핑하는 방법을 정의한다.
FDAI가 어떤 업무를 넘겨받을 때, 각 에이전트 뒤에 에스컬레이션, 리뷰, 지식 인수인계를
책임지는 사람이 반드시 지정되도록 하기 위함이다.

이것은 [user-rbac-and-identity.md](user-rbac-and-identity-ko.md)와는 **다른 축**이다.
RBAC은 "누가 FDAI를 조작할 수 있나"(Reader / Contributor / Approver / Owner)에 답하고,
스튜어드십은 "FDAI 이전에 이 업무를 누가 소유했고, 이제 이 에이전트의 도메인을 누가
책임지나"에 답한다. 한 사람이 보통 두 모델 모두에 속하지만(Var의 steward이면서 Approver인
사람처럼), 두 모델은 독립적으로 해석되고 검증된다.

> Customer-agnostic: 아래의 모든 objectId, group id, 이름은 **placeholder**(all-zero UUID)다.
> Deployment configuration이 실제 Entra 값을 제공합니다.
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
>
> **구현 상태.** Loader/validator, coverage, escalation, change-recipient/audit-payload
> primitives, read-only console projection, handover document ingestion과 Graph person resolver는
> 배포됐습니다. Production runtime의 stewardship-map 자동 binding,
> `FDAI_STEWARDSHIP_REQUIRE_BINDINGS=1` Terraform 주입, GitHub App draft-PR 생성 및 merge 후
> notification/audit hook은 아직 composition/deployment가 소유할 후속 작업입니다.

## 1. 설계 원칙

1. **오버레이일 뿐, 재지정이 아니다.** 스튜어드십은 사람을 에이전트에 매핑하되 오직 책임과
   통보 목적이다. 판테온의 어떤 `ActionType` 역할 바인딩도 바꾸면 안 된다. fork-locked 5개
   필드(`initiators`, `judge`, `executor`, `approver`, `auditor`)는
   [agent-pantheon.md](../agents/agent-pantheon.md)가 선언한 그대로 유지된다. steward라고 해서
   executor 신원을 부여받지 않는다.
2. **에이전트당 여러 사람.** 한 역할을 여러 명이 맡을 수 있다. 모든 에이전트는 단일 소유자가
   아니라 steward **리스트**(개인 Entra OID 및/또는 Entra 그룹 objectId)에 매핑된다.
3. **maintainer 하한선.** FDAI 자체에도 지정된 소유자가 필요하다. maintainer는 최소 **1명**
   (fail-fast), **2명** 권장(warn)이다. maintainer는 live steward가 없는 에이전트의 최종
   에스컬레이션 대상이다.
4. **사람 쪽으로 실패한다.** 미매핑 에이전트, stale steward OID, maintainer 부재는 "조용히
   무소유"가 아니라 "maintainer로 에스컬레이션"으로 degrade된다.
5. **콘솔은 read-only 유지.** 스튜어드십 설정 화면은 상태를 렌더링만 한다. 편집은 다른 모든
   거버넌스 변경과 동일하게 GitHub App이 draft PR로 작성한다
   ([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)).
6. **모든 변경은 통보되고 감사되어야 한다.** Core는 recipient와 audit payload를 결정론적으로
  계산합니다. Live PR/merge integration은 이 primitive를 notification/audit adapter에 배선해야 합니다.

## 2. 개념과 용어

코드, config, 문서에서 아래 용어를 그대로 재사용한다.

| 용어 | 의미 |
|------|------|
| **agent-steward** | 어떤 에이전트의 도메인을 책임지는 사람(또는 팀). FDAI 이전에 이 업무를 하던 사람으로, 이제 에이전트를 감독하고 그 에스컬레이션을 받는다. |
| **handover-map** | 15개 판테온 에이전트 전부를 steward에 매핑한 전체. 온보딩 인수인계의 산출물이다. |
| **maintainer** | FDAI 플랫폼 자체를 책임지는 사람. 최소 1명(hard), 권장 2명(warn). 미매핑 에이전트의 최종 에스컬레이션. |
| **responsibility (RACI-lite)** | 각 steward 항목은 `accountable` 또는 `informed`로 태깅된다. 모든 에이전트는 `accept_autonomous`가 아닌 한 최소 하나의 `accountable` steward를 가져야 한다. |
| **accept_autonomous** | 도메인 steward 없이 완전 자율로 도는 에이전트임을 명시적으로 인정하는 것. 에스컬레이션은 maintainer로 폴백한다. `reason`이 필요하다. |
| **escalation-chain** | 에이전트의 순서 있는 통보 경로: `accountable` steward -> `informed` steward -> maintainer, 홉별 timeout 적용. |
| **bus-factor** | 어떤 에이전트의 도메인을 아는 서로 다른 `accountable` 사람의 수. bus-factor 1은 추적되는 리스크(warn)다. |

### 전체 RACI가 아니라 RACI-lite

전체 RACI(Responsible / Accountable / Consulted / Informed)는 인수인계에 필요한 것보다 많고
불필요한 논쟁을 부른다. 이 모델은 태그 2개만 둔다:

- **accountable** - 에스컬레이션 hot path 위에 있음. 가장 먼저 페이징됨. 행동하거나 위임할 수
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
- HIL 요청 승인을 위해 페이징된 steward도 여전히 RBAC `Approver` capability 체크와
  no-self-approval 체크를 통과한다. steward라는 사실만으로는 승인 권한이 부여되지 않는다.

## 4. 데이터 모델

### 4.1 Config 아티팩트

`config/agent-stewardship.yaml` (fork가 실제 값 공급; upstream은 placeholder 배포):

```yaml
stewardship:
  version: 1

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
  # Entra group objectId; `kind` disambiguates. `responsibility` is
  # accountable|informed. An agent with no accountable steward MUST set
  # accept_autonomous with a reason.
  agents:
    Odin:
      stewards:
        - { kind: user,  id: "00000000-0000-0000-0000-000000000000", responsibility: accountable }
        - { kind: group, id: "00000000-0000-0000-0000-000000000000", responsibility: informed }
    Thor:
      stewards:
        - { kind: user,  id: "00000000-0000-0000-0000-000000000000", responsibility: accountable }
    Loki:
      accept_autonomous:
        reason: "Chaos proposals are always HIL; no standing domain owner."
      stewards: []
    # ... all 15: Odin, Thor, Forseti, Huginn, Heimdall, Vidar, Var, Bragi,
    #     Saga, Mimir, Muninn, Norns, Njord, Freyr, Loki
```

### 4.2 Env-var 오버라이드

fork는 YAML을 편집하지 않고 단일 슬롯만 오버라이드할 수 있다(rbac-groups 패턴과 동일):

| Env var | 효과 |
|---------|------|
| `FDAI_MAINTAINERS` | 콤마로 구분된 OID들. `maintainers` 리스트를 대체한다. |
| `FDAI_STEWARD_<AGENT>` | 콤마로 구분된 `user:<oid>` / `group:<oid>` 토큰. 해당 에이전트의 `stewards`를 대체한다. `<AGENT>`는 대문자(`FDAI_STEWARD_THOR`). |

### 4.3 에이전트 이름 정합성

`agents:` 아래 15개 키는 정확히 판테온 이름이어야 한다. `core/stewardship`은 자체 canonical
`AGENT_NAMES` 튜플을 두고, parity 테스트
(`tests/core/stewardship/test_pantheon_parity.py`)가 이를
`fdai.agents._framework.pantheon.PANTHEON_NAMES`에 고정하므로, config 스키마와 판테온은 절대
drift할 수 없다. `core/`는 `agents/`를 import하지 않으며(module-boundary 규칙), parity 테스트가
테스트 시점에 둘을 연결한다.

## 5. FDAI 유지관리자 규칙

- **하한선(fail-fast):** maintainer 0명은 startup `ValueError`다. FDAI는 스튜어드십 레이어를
  무소유 상태로 부팅하지 않는다.
- **권장(warn):** maintainer가 정확히 1명이면 `stewardship_maintainer_single` 경고를 남기고
  콘솔 배너를 띄운다. 2명 이상은 clean.
- **승계:** maintainer OID가 stale해지고(Entra에서 제거, 7.3 참조) live 수가 1로 떨어지면 경고가
  **hard 배너**로 격상되어 Owner에게 후임 지정을 요청한다. 제어 루프를 막지는 않지만 clean 검증
  상태를 막는다.
- **최종 에스컬레이션:** live steward가 0명으로 해석되는 에이전트는 에스컬레이션을 maintainer
  집합으로 라우팅한다.

## 6. 런타임 효과: 통보와 에스컬레이션 (결정 B)

스튜어드십은 [channels-and-notifications](channels-and-notifications-ko.md)에 연결되어, 에이전트의
도메인 steward가 그 에이전트 이벤트에 대해 먼저 통보받도록 한다.

### 6.1 에스컬레이션 체인

사람이 필요한 에이전트 이벤트(HIL 요청, degraded 상태, 워크플로우 변경 요청)에 대해
`core/stewardship`은 순서 있는 수신자 리스트를 만든다:

1. 에이전트의 `accountable` steward,
2. 그다음 `informed` steward,
3. 그다음 maintainer 집합.

각 홉은 `hop_timeout_seconds` 예산을 갖는다. 확인 응답이 없으면 다음 tier가 통보된다. 이는
notifications matrix의 `on_all_fail: hil_escalate` 시맨틱(메시지는 절대 드롭되지 않음)을 재사용하고
사람-tier 순서를 얹은 것이다.

### 6.2 사람 -> 채널 브릿지

notifications matrix는 **channel-id**로 라우팅하지만 steward는 **사람**이다. 브릿지는 순서대로
해석한다:

1. `agent-stewardship.yaml`의 명시적 `channels[<oid>]` 바인딩,
2. 없으면 `notifications-matrix.yaml`의 에이전트 카테고리 route(그 사람은 도메인 채널로 도달됨).

`kind: group` steward는 항상 matrix 카테고리 route로 해석된다(그룹은 단일 개인 채널이 없다).

### 6.3 그룹 책임 담당자

`kind: group` steward는 "이 Entra 그룹에 속한 누구든 steward"를 뜻한다. resolver는 주입된
`GroupMembershipProvider`(fork에서는 Graph 기반, 테스트에서는 static)를 통해 그룹 멤버로 확장한다.
확장은 best-effort다: provider가 사용 불가면 그룹을 하나의 불투명한 `accountable` 단위로 취급해
도메인 채널로 라우팅하고 경고를 남긴다. 제어 루프는 Graph에서 절대 블록되지 않는다.

## 7. 검증 게이트 (검증 표면)

인수인계 정확성은 안전과 관련되므로 검증을 계층화한다.

### 7.1 Loader fail-fast (`load_stewardship_from_mapping`)

Hard 에러(`StewardshipValidationError` 발생, 레이어의 clean 부팅 차단):

- maintainer 1명 미만,
- `agents:` 블록이 15개 판테온 이름 중 하나라도 누락하거나 알 수 없는 에이전트를 지정,
- `accountable` steward도 없고 `accept_autonomous`도 없는 에이전트,
- `reason` 없는 `accept_autonomous`,
- 잘못된 subject(`kind`가 {user, group}에 없거나 id가 UUID 형태가 아님),
- `FDAI_STEWARDSHIP_REQUIRE_BINDINGS=1`일 때 steward나 maintainer id가 all-zero placeholder로
  남아 있습니다. Stewardship map을 binding하는 모든 deployed environment는 이 flag를 명시적으로
  설정해야 하며 fork 여부와 관계없습니다.

### 7.2 Non-blocking 발견 (warn, coverage 리포트에 노출)

- maintainer가 정확히 1명(`maintainer_single`),
- bus-factor(서로 다른 accountable 사람)가 1인 에이전트(`bus_factor_one`),
- `N`개 초과 에이전트에 `accountable`인 사람(`over_assigned`, 기본 N=5, 설정 가능),
- `accept_autonomous`에 의존하는 에이전트(`autonomous_no_steward`, 정보성).

### 7.3 Stale-OID 감지

주입된 `IdentityDirectory`(fork에서는 Graph 기반, 테스트에서는 static)에게 각
maintainer/steward OID가 여전히 활성 계정으로 해석되는지 확인한다. 없는 OID는 `stale_oid` 발견을
만들고 그 사람은 live 에스컬레이션에서 제거된다(다음 tier / maintainer로 폴백). 이는 hot path
바깥(스케줄)에서 실행되며 제어 루프에서 절대 인라인으로 돌지 않는다.

### 7.4 CI 게이트 (`scripts/governance/check-stewardship.sh`)

`scripts/verify.sh`와 CI에서 실행:

- YAML이 파싱되고 15개 에이전트 이름이 모두 존재하며 정확히 표기됨(작은 Python shim으로
  `PANTHEON_NAMES`와 비교),
- 파일이 어떤 ActionType 역할 필드도 선언하려 하지 않음(grep 가드: 스튜어드십 파일은
  `executor:`/`judge:`/`approver:`/`initiators:`/`auditor:` 키를 포함하면 안 됨 - 이들은
  fork-locked 온톨로지에만 존재),
- placeholder 정책: tracked upstream config는 all-zero value를 사용하고 deployed environment는
  `FDAI_STEWARDSHIP_REQUIRE_BINDINGS=1`을 통해 non-placeholder binding을 요구합니다.

## 8. 워크플로우 변경 통보와 감사 (integration target)

"정의된 워크플로우"란 업무가 흐르는 방식을 인코딩한 모든 거버넌스 아티팩트다:
`rule-catalog/workflows/*.yaml`, `config/agent-stewardship.yaml`,
`config/notifications-matrix.yaml`. 누군가 이 중 하나를 변경하려 할 때:

아래 lifecycle은 target contract입니다. `core/stewardship/notify.py`의 recipient/audit payload
primitive는 구현됐지만 GitHub App과 merge hook은 아직 배선되지 않았습니다.

1. **Draft PR.** 변경은 GitHub App이 draft PR로 작성한다(콘솔은 직접 mutate하지 않음). 표준
   CODEOWNERS + no-self-approval + quorum이 적용된다.
2. **이해관계자 통보.** `core/stewardship`은 영향받는 에이전트를 계산하고(워크플로우 파일은 그것이
   참조하는 에이전트, 스튜어드십 파일은 steward가 바뀐 에이전트) 그들의 `accountable` +
   `informed` steward와 maintainer에게 통보한다: "사람 X가 워크플로우 Y 변경을 요청함".
3. **감사.** Saga append-only `AuditEntry`가 actor OID, 아티팩트, before -> after 요약, correlation
   id, 타임스탬프, 승인 결정을 기록한다. 감사 항목은 L0 English이며 절대 억제되지 않는다.

이로써 루프가 닫힌다: 어떤 에이전트를 책임지는 바로 그 사람들이 그 에이전트를 지배하는
워크플로우가 바뀌려 할 때 통보받고, 변경은 영구히 기록된다.

## 9. 콘솔 설정 표면

콘솔(`console/src/routes/handover.tsx`)의 read-only Handover 뷰는 두 section을 표시합니다:

- **Handover map** - 15개 에이전트 카드. 각각 steward(Graph로 해석된 표시명), responsibility 태그,
  bus-factor, 검증 배지(clean / warn / fail)를 표시.
- **Maintainers** - min-1/rec-2 상태 배너와 함께 maintainer 리스트.

현재 콘솔은 "Propose a change" 안내와 파일 경로를 보여주지만 mutation 버튼이나 GitHub App
호출을 제공하지 않습니다. Owner는 `config/agent-stewardship.yaml`을 편집해 draft PR을 엽니다.
Loader는 maintainer 1명 미만을 거부하고 console은 2명 미만에 권장 배너를 표시합니다.

## 10. 보안과 안전

- 스튜어드십은 executor Managed Identity를 보유하거나 부여하지 않는다.
- 매핑 변경은 콘솔 버튼이 아니라 거버넌스 PR(author != approver, 감사됨)이다.
- steward OID는 라우팅과 감사에 쓰이는 유일한 신원이다. UPN/email은 정보성이며 절대 권위 있는
  값이 아니다(`Principal`과 동일 규칙).
- customer 식별 값은 이 repo에 들어오지 않는다. fork가 실제 OID, group id, channel id를 config나
  env로 공급한다.

## 11. 담당자 인수인계 부트스트랩 (문서 수집)

맵을 수동으로 채우는 대신, 오퍼레이터는 기존 운영 문서(RACI 매트릭스, 온콜 스케줄, 조직도,
런북, 인수인계 메모)를 업로드하고 FDAI가 이를 검토용 **초안** steward 맵으로 파싱하게 할 수
있다([issue #23](https://github.com/dotnetpower/fdai/issues/23)). 이는 위의 결정론적 코어 위에
얹은 더 크고 분리 가능한 기능이며, 아무것도 적용하지 않고 코어를 막지도 않는다.

`src/fdai/core/stewardship/handover_bootstrap/` 아래에 결정론 우선, 근거 기반, 기권형
파이프라인으로 구현되어 있다:

1. **결정론적 추출** (`extractor.py` + `agent_domains.py`). 각 문서 라인을 에이전트별
   도메인 키워드 카탈로그(handover 스킬의 "누가 X를 소유했나" 질문, 판테온 에이전트마다 1개)에
   대조한다. 도메인 키워드 + 사람/팀 + 책임 마커를 맞춘 라인은 **모델 없이** 근거를 갖춘
   `ExtractedMapping`을 산출한다. 이것이 결정론 우선 단계다.
2. **모델 해석** (`interpreter.py`). 구조가 해결하지 못한 것은 T2 `HandoverInterpreter` 시임에
   넘길 수 있다. 업스트림은 `AbstainingInterpreter`(아무것도 제안하지 않음)를 기본 제공하므로
   LLM이 없는 배포는 절대 추측하지 않는다. fork는 mixed-model 근거 기반 구현을 바인딩한다
   (`core/rca` reasoner 시임과 대칭). 근거 없는 모델 제안은 오케스트레이터가 폐기한다.
3. **신원 해석** (`people.py`). 언급된 각 이름/팀을 async `PersonDirectory` seam으로
  Entra objectId에 해석합니다. Production은 정확한 active user/group display-name match가
  한 건일 때만 수락하고 0건 또는 모호한 결과에는 abstain하는 `GraphPersonDirectory`를
  bind합니다. 해석되지 않은 이름은 id로 **추측하지 않고 플래그**합니다. Local 기본값인
  `NullPersonDirectory`는 아무것도 해석하지 않습니다.
4. **신뢰도 플로어 + 초안 조립** (`bootstrap.py`). 플로어 이상의 근거 매핑은 초안이 되고,
   플로어 미만은 사람 검토용으로 따로 두며, 미해결 인물과 확실한 소유자가 없는 에이전트를
   표면화하고, 플로어를 넘긴 것이 없으면 기권한다. 출력은 `StewardMapDraft`다.

Document ingestion gateway는 `handover_bootstrap`을 명시적 `DocumentPurpose`로 받습니다.
Quarantine, protection check, extraction이 끝나면 `DocumentIngestionWorker`가 안전한
`DocumentEnvelope`를 해당 purpose에 주입된 `DocumentReadyConsumer`로 전달합니다. Upstream
local과 production composition은 `HandoverBootstrapConsumer`를 bind하고 인증된
`GET /ingestion/uploads/{upload_id}/handover-draft`로 제공합니다. Console은 processing state를
polling하고 검토용 draft JSON summary와 YAML을 렌더링합니다. Map을 적용하거나 privileged
mutation path를 만들지 않습니다. Local development는 draft를 memory에 저장하고 production은
`PostgresStateStore`를 사용하므로 worker 또는 gateway restart 후에도 review artifact가
유지됩니다.

Production Graph call은 gateway managed identity와
`https://graph.microsoft.com/.default` scope를 사용합니다. Exact lookup에 필요한 Microsoft
Graph application permission인 `User.Read.All`과 `Group.Read.All`만 할당하고 정기적으로
검토하는 것이 좋습니다. Adapter는 name, object id, token, provider response body를 log하지
않습니다. `FDAI_GRAPH_BASE_URL`은 test 또는 sovereign-cloud용 optional override이며 기본값은
public Graph v1.0 endpoint입니다.

모든 emit된 매핑은 소스 스팬(`SourceSpan`)을 인용하므로 근거 없는 것은 없다. `draft_yaml.py`는
초안을 `stewardship:` 형태의 YAML로 렌더링하며, 이는 동일한 resolver와 fail-fast 게이트를 통해
**`load_stewardship_from_mapping`으로 round-trip**된다(인라인 인용 주석 + 미해결 인물용
플레이스홀더 id 포함). 딜리버리 계층은 그 YAML을 사람이 검토·머지하는 거버넌스 draft PR로
노출한다. 콘솔은 읽기 전용을 유지하며 어떤 맵도 자율 적용되지 않는다.

남은 fork binding은 deterministic extractor가 해석하지 못한 구조를 grounded T2로 해석하는
`HandoverInterpreter`입니다. Upstream production은 mixed-model binding을 명시적으로 공급하지
않으면 abstaining implementation을 유지하며 deterministic extraction과 Graph resolution은 계속
실행됩니다. 모든 seam은 async로 주입되고 `core/`는 cloud SDK나 HTTP client를 갖지 않습니다.

## 12. 범위 밖 (별도 추적)

- 비-Azure 신원 공급자(TBD,
  [Implementation Focus](../../../.github/copilot-instructions.md#implementation-focus-must) 참조).
