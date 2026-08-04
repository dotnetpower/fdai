---
title: Operator Console - Incident Roster and Fix History
translation_of: operator-console-incident-roster.md
translation_source_sha: d901b58529cbf081c50bb5e32ce020504358e2c6
translation_revised: 2026-08-05
---

# Operator Console - Incident Roster and Fix History

> [operator-console-ko.md](operator-console-ko.md) section 13.5에서 분리한 focused owner 문서입니다.

### 13.5 인시던트 목록 및 교정 이력

읽기 전용 SPA는 일급 **실시간 > 인시던트** 패널을 제공합니다. 이 패널은
인시던트 대응을 위한 목록 중심 진입점입니다. 운영자는 correlation id를 미리
알지 못해도 활성 또는 해결된 인시던트를 찾고, 하나를 선택하여 교정 이력을
확인할 수 있습니다. 기존 Audit 및 Trace 패널은 각각 레코드 수준과 엔드투엔드
상세 분석 surface로 유지됩니다.

API 계약은 다음과 같습니다.

| Route | 목적 |
|-------|------|
| `GET /incidents?status=active|resolved|all&limit=<n>&cursor=<opaque>` | 최근 활동 순으로 인시던트 요약을 반환합니다. |
| `GET /audit?correlation_id=<id>&limit=<n>&cursor=<opaque>` | 선택한 인시던트의 추가 전용 이력을 반환합니다. |
| `GET /audit/{correlation_id}/trace` | 순서가 지정된 연관 감사 활동과 기록된 파이프라인 단계를 재구성합니다. |
| `POST /chat/stream` | 레코드를 생성하지 않고 자연어에서 typed incident 초안을 만듭니다. |
| `POST /chat/action/confirm` | typed 초안을 확인하고 audit되는 Incident를 생성합니다. |

Incident roster는 read-only로 유지됩니다. Incident 생성은 semantic draft 및
typed confirmation route를 사용하며 panel에 mutation button을 추가하지 않습니다. 인식된
incident-open 요청은 다음 순서로 처리됩니다.

1. Contributor capability, severity, target correlation key를 요구합니다.
2. 사람이 읽을 수 있는 summary와 10분 expiry를 포함한
  `incident_confirmation_required`를 반환합니다. 이 시점에는 incident가 없습니다.
3. 같은 principal과 `session_id`에서 `confirm` 또는 `확인` 메시지를 보내면 audited
  incident를 생성하고 id와 초기 `open` 상태를 반환합니다.

Pending proposal의 `session_id`는 200자로 제한됩니다. Oversized session 또는
idempotency key는 truncate하지 않고 거부하므로 서로 다른 식별자가 같은 confirmation으로
합쳐지지 않습니다. Production은 proposal을 Postgres에 저장하고 atomic하게 consume하므로
confirmation이 다른 replica에 도착해도 처리할 수 있습니다. Persisted record에는 source
prompt 원문이 아니라 SHA-256만 포함됩니다.

누락된 값은 `incident_details_required`, 취소는
`incident_creation_cancelled`를 반환합니다. 관련 없는 action command는 기존
Bragi-to-Huginn typed proposal path를 계속 사용합니다. allowlist에 포함된 agent는
member-event evidence와 reason을 제공해 같은 built-in workflow를 사용하지만,
operator를 impersonate하거나 incident registry를 우회하지 않습니다.

동일한 authenticated route는 exact lifecycle command grammar만 받으며 free-form status
prose를 추측하지 않습니다.

- `transition incident <uuid> to <state>` 또는
  `incident <uuid> 상태 <state>으로 변경`
- `assign incident <uuid> to <oid>` 또는
  `incident <uuid> 담당자 <oid> 지정`

둘 다 nonblank conversation `session_id`, Contributor capability, registry의 persisted
expected-state check가 필요합니다. Illegal edge, unknown id, cross-replica conflict는
canonical incident를 변경하지 않고 `incident_lifecycle_rejected`를 반환합니다.

`correlation_id`는 evidence를 연결하는 investigation key이며 그 자체로 Incident lifecycle
record가 존재한다는 증거가 아닙니다. Projection은 최상위 correlation이 없는
행의 `event_id`가 이미 알려진 correlation과 같거나 명시적인 인시던트 lifecycle
link가 정확히 하나의 correlation으로 확인될 때만 해당 행을 연결할 수 있습니다.
모호한 행은 연결하지 않으며 read model은 리소스 이름으로 연관 관계를 만들지
않습니다. Pending HIL 항목은 server-owned park record에서 rule severity와 category를
복원할 수 있지만 append-only audit row는 다시 쓰지 않습니다. Lifecycle 상태가
있으면 이를 authoritative하게 사용합니다. 그렇지 않으면 audit stage에서 `open`,
`in_progress`, `resolved`를 도출합니다. 교정이 deny, abstain 또는 실패했다는
사실만으로 기반 인시던트가 해결되었다고 표시하지 않습니다.
Local Operator API audit fixture는 명시적인 sample provenance를 가지며 Audit, Trace,
Agent activity에서 계속 볼 수 있습니다. Operational Incident roster에서는 제외되므로
정상 또는 within-threshold monitoring sample이 열린 Incident처럼 보이지 않습니다.

각 incident summary는 기록된 `producer_principal`, canonical action owner, stage
ownership에서 server-side로 도출한 `involved_agents`를 포함합니다. Agents surface는
이 durable incident snapshot을 먼저 hydrate한 다음 더 새로운 `/agents/stream` stage
delta를 적용합니다. 따라서 새 tab도 Incidents와 일치하면서 live stage transition을
유지합니다.

Summary title도 서버가 소유합니다. Projection은 먼저 명시적으로 기록된 `title`,
`summary` 또는 rule ID를 사용합니다. 이 field가 없으면 기록된 `signal:` 및
`resource:` correlation key에서 길이가 제한된 subject를 만듭니다. Azure resource ID는
resource type과 마지막 resource name만 제공하므로 전체 path를 노출하지 않고도 목록에
`Resource inventory change - Storage account storage-example` 같은 subject를 표시할 수
있습니다. 기록된 subject evidence가 전혀 없는 incident만 event ID로 대체되며 browser는
대체 title을 만들어내지 않습니다.

누락된 correlation은 누락 상태로 유지합니다. Projection은 빈 값과 과거의 `None` 또는
`null` 문자열 sentinel을 결측으로 처리하므로 관련 없는 audit-only row가 synthetic Incident를
구성하지 않습니다.

목록은 요약만 반환하며 모든 audit 행을 포함하지 않습니다. Cursor가 각 서버
페이지의 범위를 제한합니다. 항목을 선택하면 별도의 필터링된 GET으로 이력을
가져옵니다. 모든 route는 Reader gate를 적용하고 mutation verb에 `405`를
반환합니다. 패널은 Audit 및 Trace 링크를 제공하지만 execute, approve, rollback
버튼은 제공하지 않습니다. 이러한 작업은 remediation PR 및 ChatOps에 유지됩니다.

Incident 생성, 각 합법적 상태 변경, 요청된 roster summary는 A2 운영 알림 대상입니다.
재전송된 open과 같은 상태 transition은 두 번 알리지 않습니다. Lifecycle 메시지는
incident id, severity, 정규화된 상태를 포함하지만 자유 형식 reason text와 resource
correlation key는 제외합니다. Roster 알림은 20개 id로 제한되고 전체
`/incidents` view로 연결됩니다. Event별 `audit_id`는 channel idempotency가 이후
transition을 누락시키지 않도록 합니다. Durable sent checkpoint와 startup replay는
crash로 놓친 알림을 재시도합니다. Delivery 전에 replica는 bounded lease가 있는 atomic
claim token을 경쟁하며 하나만 전송합니다. 해당 token만 notice를 sent로 표시하거나
실패 후 release할 수 있습니다. Unresolved channel은 HIL escalation sink로 fallback합니다.

Incident alert subscription은 [channels-and-notifications-ko.md](channels-and-notifications-ko.md)의
channel-as-audience contract를 따릅니다. 설정된 A2 operations channel membership이
open, transition, roster, SLA-breach notice를 지속적으로 받는 대상을 결정합니다.
Console은 per-user direct-message subscription을 만들지 않습니다. Assignment와 external
ticket linkage는 authenticated write-direction chat/tool operation으로 유지되고 audit
history에 표시됩니다. Read-only roster는 연결된 `ticket_id`를 표시합니다.

목록은 optional canonical `vertical` filter를 허용하며 audit route는 `mode`,
`tier`, `action`, `outcome`, `vertical`, bounded `window=<n>d` filter를 cursor
pagination 전에 서버에서 적용합니다. 따라서 분석 deep link는 browser 첫 page만
filter하지 않고 전체 filtered result set을 검색합니다. Cursor는 incident status와
vertical에 binding되므로 두 filter 중 하나를 바꾸면 stale cursor가 무효화됩니다.

Overview audit KPI는 in-memory와 Postgres read model 모두에서 가장 최근 audit row
500개를 집계합니다. `GET /kpi`는 이 immutable sample을 inclusive `from_seq`와
`through_seq` boundary, `row_count`, `limit`를 포함하는 `audit_sample`로 반환합니다.
Overview에서 Audit로 이동하는 모든 link는 이 boundary를 전달하며 `GET /audit`는
dimension filter와 cursor pagination 전에 `from_seq`와 `through_seq`를 적용합니다.
따라서 더 최신 row가 추가된 후에도 operator는 표시된 count 또는 ratio를 만든 동일한
append-only sample을 열거할 수 있습니다. `hil_pending`은 별도의 현재 queue projection으로
유지되며 audit sample에 포함되지 않습니다. Tier key와 tier filter는 lowercase canonical
value (`t0`, `t1`, `t2`)를 사용합니다.

SPA는 incident 목록을 selection button의 semantic list로 렌더링합니다. 선택된 button은
`aria-pressed`를 노출하며 모든 button은 `aria-controls`로 incident detail region을
가리킵니다. 알 수 없는 top-level URL은
canonical `/overview`로 replace되므로 같은 화면이 typo path 아래 여러 conversation
cache를 만들지 않습니다.

명시된 child-view 및 entity identifier는 fail-closed로 처리합니다. URL이 알 수 없는
workflow, ObjectType, LinkType, ActionType, agent, audit entry, architecture view 또는
resource, incident correlation, promotion reason, IAM tab, live event를 지정하면 console은
요청 값을 보존하고 유효한 복구 link가 있는 unavailable 또는 waiting 상태를 렌더링합니다.
첫 row, default workflow, default view 또는 다른 entity의 evidence로 대체하지 않습니다.
명시적 identifier가 없는 URL에서만 문서화된 default를 선택할 수 있습니다.
ActionType directory filter는 canonical URL state (`q`, `category`, `trigger`,
`execution`)이며 operator가 action을 선택해도 유지됩니다. 따라서 새로 고침, 뒤로 가기,
공유 link가 같은 목록을 재현합니다.
Blast-radius query draft는 simulation을 실행하지 않고 `target`, `depth`, `links`를 URL에
기록합니다. `links=none`은 operator가 유효한 traversal set을 선택할 때까지 명시적으로
비어 있는 선택을 보존합니다.
Opaque entity identifier는 canonical URL 교체와 중첩 drilldown에서도 byte-for-byte로
유지됩니다. 특히 Process ID는 encoding만 하고 lowercase 또는 slug 변환하지 않으며,
workflow step link는 catalog ownership group을 보존합니다. 수동 RCA와 Trace 조회는 제출한
correlation ID를 먼저 canonical URL에 기록합니다. Input을 수정하면 이전 응답을 무효화해
다른 identifier 아래 잘못된 evidence가 나타나지 않게 합니다.

Write-direction form은 변경되지 않은 하나의 operator intent에 하나의 idempotency key를
유지합니다. 따라서 transport failure 또는 response 유실 후 재시도는 같은 key를 사용하고,
target, parameter, justification을 바꾸면 key를 교체하며 확인된 성공 후에는 폐기합니다.
Daily briefing subscription create는 이 key에서 principal-scoped stable subscription identity를
파생하고 동일한 retry에는 기존 record를 반환합니다. Access request, IAM role request,
governed Python run도 같은 규칙을 사용합니다. Document batch upload는 완료할 때까지 collection,
purpose, storage mode, consent, selected file을 잠그고 route unmount 후 새 request를 발행하지 않습니다.

Canonical source mutation과 derivative ontology projection은 서로 다른 성공 boundary를 가집니다.
Committed workflow definition 또는 binding은 즉시 ontology projection이 실패해도 source-store
결과를 반환합니다. PostgreSQL source transaction은 해당 projection recovery record를 enqueue하므로,
재시도가 committed create를 conflict로, committed delete를 not found로 잘못 보고하지 않습니다.

Agent runtime state에도 관찰된 evidence가 필요합니다. Agent state frame 또는 durable incident
projection이 작업을 귀속하기 전에는 Agents, Agent Activity, Pantheon이 `unobserved`로 표시합니다.
고정 runtime-binding map은 consumer health를 증명하지 않습니다. Headless Pantheon은 실제 health에서
파생한 `agent.runtime-state` heartbeat를 발행하고, Operator API는 live이며 error가 아닌 agent만 `idle`
또는 `watching`으로 표시합니다. Schedule 상태는 scheduler projection 전까지 unavailable입니다.

Capabilities route는 `source=static-catalog`, `execution_eligibility=false`인 inert catalog
projection이며 side-effect class, required role, default mode를 설명합니다. Skills route도 `GET /skills`에서 installed skill과 governed bundle metadata, member order, compatibility, eligibility, reference, bounded diagnostic만 projection하고 lifecycle control을 노출하지 않습니다.
Bragi는 같은 Reader-gated disclosure를 사용합니다. Content read는 trust와 budget을 다시 확인하며
실행 결정은 composition, RBAC, verification, risk gate에 남습니다.
승인된 source evidence는 `/api/v1/skill-sources` 아래 GET route로 제공하지만 현재 SPA Skills
route는 `/skills`만 읽고 해당 route를 아직 사용하지 않습니다. 향후 read-only source view는 browse,
search, quarantine inspect, disabled update candidate 확인만 수행할 수 있습니다. Candidate approval과
source revocation은 Approver 및 Owner automation을 위한 별도 authenticated POST route입니다.
Skills panel은 lifecycle control을 제공하지 않습니다.
[skill-source-management-ko.md](skill-source-management-ko.md)를 참조하세요.

Operational read surface는 static claim 대신 payload의 provenance를 렌더링합니다.
Scheduler Runs는 ledger `source`와 `durable` flag를, LLM Cost는
`latest_occurred_at`을, Settings Models는 generated snapshot filename과 `as_of`를
표시합니다. 누락된 field는 unavailable로 렌더링하거나 contract decode를 실패시킵니다.
Browser는 route 이름, environment mode, configured default에서 durability, freshness,
provider health를 추론하지 않습니다.

정확한 entity 조회는 page limit 전에 server에서 filter합니다. 따라서 Incident correlation link,
Audit entry link, Approval search는 첫 roster page 밖에서도 false absence 없이 resolve됩니다.
Count-only role에는 Approval search를 적용하지 않아 filtered total로 숨겨진 queue content를
추론할 수 없게 합니다. 독립 source는 격리합니다. Optional principal workflow projection이
built-in workflow catalog를 숨기지 않으며, 사용하지 않는 analytics source가 다른 hub를 error
화면으로 교체하지 않습니다. Report render와 PDF failure는 선택된 operation에만 남고 catalog나
variable editor를 제거하지 않으며, route 변경 후 도착한 download는 폐기합니다.

Diagnostics는 process liveness와 authenticated KPI read path를 구분합니다. `/healthz` 성공만으로
운영 데이터가 healthy하다고 주장하지 않습니다. 마찬가지로 last-observed agent frame은 history로
유지하지만 Engaged, Watching, Idle은 agent stream이 open일 때만 current count입니다. 인증된 live 및
agent stream이 open일 때만 current count입니다. Canvas visualization은 동등한 keyboard 및
screen-reader resource selector를 제공하고 composite tab widget은 roving selection과 함께 DOM
focus를 이동합니다.


Time-bound 및 aggregate evidence는 route가 열린 동안에도 보수적으로 유지됩니다. Approval과
Operator Memory row는 reload 없이 recorded TTL boundary를 넘으면 상태가 전환됩니다.
Architecture는 server의 snapshot freshness verdict를 유지하면서 snapshot age를 계속 증가시킵니다.
누락된 tier measurement는 measured zero가 아니라 unavailable입니다. Scope eligibility는
`included` entry만 집계합니다. Multi-datasource report는 모든 source가 evidence time을 제공할 때만
aggregate time을 알 수 있고, 그 경우 가장 오래된 source time을 사용합니다. Mixed-currency LLM
cost group은 non-additive로 표시하며 단일 통화 total로 렌더링하지 않습니다.

Process 목록도 `source`, nullable `synthetic`, nullable `durable`로 같은 규칙을
따릅니다. Local seeded runtime은 `synthetic-dev/true/false`, production은
`postgres/false/true`를 보고합니다. Process status, journal, dynamic view는 server-owned로
유지되지만 현재 render가 underlying snapshot의 생성 또는 저장 방식을 지우지 않습니다.

선택한 인시던트 상세는 요약과 근거 계층을 분리합니다. 교정 타임라인보다 먼저 alert lifecycle,
agent work state, pending user input, server-owned incident 및 ticket ID, disposition, verdict,
vertical, mode, timestamp, history count를 표시합니다. Compact response-routing section은 기록된
severity, involved agent, governed human-ownership mapping, autonomy mode 순서로 표시합니다. 누락된
값은 unavailable로 렌더링하며 browser가 impact, 사람, ownership, recovery를 추론하지 않습니다.
상세는 History > Reports의 correlation 범위 **Incident RCA Dossier**로 연결됩니다.

조치 이력은 각 audit row를 사람이 읽을 수 있는 이벤트로 표시합니다. 먼저 기록된
`summary`, `detail`, `reason` 텍스트를 사용하고, 값이 없으면 알려진 lifecycle, 알림,
사람 승인, audit event kind에 대한 결정론적 템플릿을 사용합니다. 담당 에이전트는 기록된
`producer_principal`, Pantheon actor 또는 canonical stage-owner mapping에서 가져옵니다.
에이전트가 아닌 runtime은 에이전트로 귀속하지 않고 담당 서비스로 표시합니다. 각 row는
정확한 machine `action_kind`를 보조 텍스트로 유지하고 기록된 핵심 사실을 최대 5개까지
표시합니다. Incidents에서는 raw entry JSON을 생략하며 correlation 범위 Audit link가 전체
레코드 화면으로 유지됩니다.

Overview는 autonomy measurement가 없거나 malformed여도 모든 필수 분석 section을
계속 표시합니다. Section을 제거하거나 0으로 추정하지 않고 명시적 unavailable
상태를 렌더링합니다. Evidence가 있으면 success surface는 해결 event당 cost,
mixed-model disagreement, verifier failure, shadow divergence, measurement window,
sample size, confidence, named source를 포함합니다. **이력 > 리포트**는 선언형
reporting catalog와 server-owned widget evidence를 렌더링합니다.
Synthetic measurement는 분석 shape를 설명할 수 있지만 operational health를 결정하거나,
attention count를 늘리거나, failed-guard drilldown을 만들 수 없습니다. Overview와
Control Assurance는 synthetic guard를 operational posture에서 unknown으로 처리하면서
source, window, sample size, confidence, source timestamp를 계속 표시합니다. 이벤트가
0건인 영역은 해결률을 0%로 추정하지 않고 unavailable로 렌더링합니다. Overview는 필수
audit KPI와 독립적인 optional cost, promotion, autonomy projection을 동시에 불러오며,
문서화된 unavailable status만 해당 optional projection을 degrade합니다. 분석 tab과
comparison link는 현재 query를 보존합니다. 실패 guard와 T2 leading indicator는 canonical
`guard`, `indicator` filter를 추가하며 알 수 없는 filter 값은 다른 row를 선택하지 않고
unavailable로 렌더링합니다.

계약 규칙 (`console/src/routes/view-contract.test.ts` 가 강제):

- **snapshot을 publish하는 모든 route는 `purpose` 와 `glossary` 를 반드시
  선언**하며, 공유 카탈로그 `console/src/deck/glossary.ts` 에서 조합해 한
  용어가 모든 화면에서 동일한 의미를 갖게 함. 이를 빠뜨린 채 snapshot을
  publish하는 route는 빌드를 실패시킴 - under-described 화면이 조용히
  들어올 수 없음.
- **인과 필드는 `records` 에 유지**. `detail`, `summary`, `reason`, `tier`,
  `outcome` 을 투영에서 버리지 않으므로, "왜 시작됐는가" 는 기록된 audit
  서사(그리고 순서대로의 hand-off 체인)를 인용해 답함.
- narrator는 **screen-agnostic** 체인(causal -> glossary / value-chip ->
  route enhancer -> generic record search)으로 질문을 해석; 새 화면은
  코드 추가가 아니라 어휘 선언만으로 설명 가능해짐. 오프라인 결정론
  answerer(`console/src/deck/answerer.ts`)와 서버 narrator(`chat.py`)가
  동일한 `purpose`/`glossary` 에 grounding.
- CLI REPL과 live cockpit은 동일한 self-describing snapshot을 `POST /chat`을
  통해 server narrator에 전달합니다. CLI에는 model client, intent router,
  cloud credential flow 또는 console-tool 구현이 없습니다.

#### 13.5.1 RCA 뷰 (근본 원인 분석)

읽기 전용 SPA는 일급 **History > RCA** 패널을 노출합니다. 인시던트
`correlation_id`(보통 인시던트 목록에서 딥링크, `#/rca?correlation=<id>`)가
주어지면, 컨트롤 루프가 이미 audit 원장에 추가한 티어별 근거 근본 원인
가설과 연결된 대응 계획을 렌더링합니다. 인시던트 목록(13.5)과 짝을 이루는
"왜 발생했고, 계획은 무엇이었나" 표면입니다.

API 계약은 단일 GET route입니다:

| Route | 목적 |
|-------|------|
| `GET /rca?correlation=<id>` | 단일 correlation id에 대한 인시던트별 RCA 뷰를 반환. |

Correlation에 audit row가 없으면 route는 `404`를 반환합니다. Unknown correlation을
정상 empty RCA dossier로 바꾸지 않습니다. 그렇게 하면 누락된 evidence를 완료된
분석처럼 표시하게 되기 때문입니다.

이 투영은 기존 audit 데이터를 조합하며 새로운 진실 원천을 도입하지 않습니다.
컨트롤 루프는 각 가설을 shadow `rca.hypothesis` audit 항목으로 기록합니다(참조:
[observability-and-detection.md](../rules-and-detection/observability-and-detection.md)
섹션 4). 패널은 상관관계된 audit 행을 읽어 다음을 투영합니다:

- **근본 원인 가설**, 최신순, 각각 `RcaTier`(`t0` 직접 / `t1` 상관 /
  `t2` 추론), 신뢰도, 원인 텍스트, 이유, shadow-vs-enforce 모드,
  그리고 근거 `citations`(`rule` / `event` / `telemetry` / `incident` /
  `change` / `scenario` / `knowledge`) 포함.
- **근거 상태.** 근거 없는 / 기권한 가설(`outcome == "abstained"`,
  `grounded == false`)은 신뢰할 수 있는 원인이 아니라 "근거 부족 -> HIL"로
  명시적으로 표시됩니다.
- 동일한 상관관계 audit 스트림에서 조합한 **대응 계획**: 판정
  (`auto` / `hil` / `deny` / `abstain`), 전달된 작업 종류, 그 모드,
  롤백 참조.
- **구조화된 T1 인과 체인.** T1 가설은 root/failure 이벤트 ID, 모호성,
  순서가 있는 hop을 포함하는 `causal_chain`을 전달할 수 있습니다. 각 hop은
  cause/effect 이벤트 및 리소스 참조, 선행 시간(초), 관계, 신뢰도를 보존합니다.
  malformed 또는 누락된 chain 데이터는 브라우저에서 부분 재구성하지 않고
  사용할 수 없음으로 렌더링합니다.

리포트 카탈로그는 `incident-rca-dossier`를 포함합니다. 필수
`correlation_id` 변수가 가설, 인용, causal hop, 대응, chronology 위젯을 단일
인시던트로 한정합니다. 선택적 `pdf-report` extra가 설치되면 Reports가 인증된
GET-only **PDF 다운로드** 컨트롤을 노출합니다. PDF는 표지, at-a-glance 페이지,
목차, section 페이지, running header/footer, source SHA-256을 갖춘 FDAI 소유 A4
레이아웃을 사용합니다. RCA 전용 renderer는 단색 Calm Slate steel-blue 표지, executive
summary, 근거 완성도, 측정된 영향, chronology, 인과/대안 가설, 대응/복구,
control gap, 교정/예방 조치, 제한사항, audit 부록을 제공합니다. Card는 색상 상단선이나
좌측선 대신 균일한 neutral hairline을 사용합니다. 서버 소유 report envelope을
렌더링할 뿐 새 RCA를 수행하지 않으며, 기록되지 않은 section은 명시적으로 사용할
수 없음으로 표시합니다. Print-native chronology table과 SVG causal diagram은
browser Grid/Flex pagination 결함을 피하고, content-driven chapter group은 reference
report를 9페이지로 유지합니다.

RCA 가설은 "왜"를 답할 뿐 "실행"하지 않습니다: 실행 자격은 여전히 리스크
게이트 + 검증기에 있습니다. Route는 Reader 게이트가 적용되고, 변경 동사에는
`405`를 반환하며, Audit / Trace로의 링크는 제공하지만 실행 / 승인 / 롤백
버튼은 없습니다. 투영은 순수 함수
(`src/fdai/delivery/operator_api/routes/rca_projection.py`)이며
`tests/delivery/operator_api/test_rca.py`로 커버됩니다.
