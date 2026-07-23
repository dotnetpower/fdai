---
title: Operator Console - View Snapshot Contract
translation_of: operator-console-view-snapshot.md
translation_source_sha: 371b7f4efced57d6193e577fb68fb76940542c4c
translation_revised: 2026-07-23
---

# Operator Console - View Snapshot Contract

> [operator-console-ko.md](operator-console-ko.md) section 13.4에서 분리한 focused owner 문서입니다.

### 13.4 View snapshot - self-describing screen 계약 (web deck)

read-only 콘솔 SPA는 오퍼레이터가 지금 보는 화면을 `ViewSnapshot` 으로
캡처해 `POST /chat` 의 `view_context` 로 보냄
(`console/src/deck/context.tsx`). 스냅샷은 단순 값 다이제스트가 아니라
화면 *모델* 이라, narrator가 per-screen answerer 없이도 화면과 그 용어를
설명하고 "왜 이런 일이 생겼는가" 에 답할 수 있음:

```jsonc
{
  "routeId": "agent-activity",
  "routeLabel": "Agent activity",
  "purpose": "이 화면이 무엇을 위한 것이고 오퍼레이터가 여기서 무엇을 하는가.",
  "glossary": [
    {
      "term": "correlation id",
      "plain": "관련 step과 evidence를 묶는 investigation key이며 Incident 존재 증거는 아님",
      "tech": "correlation_id",   // 정밀 내부 토큰 (optional)
      "seeAlso": "trace",          // 심화할 route (optional)
      "match": "correlation_id"    // 이 term이 설명하는 records 컬럼 (optional)
    }
  ],
  "facts": [{ "key": "rows", "label": "표시 행", "aliases": ["visible rows", "표시 행"], "value": 5, "group": "page" }],
  "records": {
    "activity": [
      { "correlation_id": "corr-j", "detail": "...왜 이런 일이 생겼는가...", "outcome": "..." }
    ]
  },
  "capturedAt": "2026-07-06T11:12:30Z"
}
```

Interactive screen은 KPI counter만이 아니라 완전한 operator model을 publish하는
것이 좋습니다. `purpose`, `glossary`, `facts` 외에도 `records`에 다음을
포함합니다.

- `sections`: 화면에 보이는 영역과 각 영역의 의미.
- `controls`: 사용 가능한 input/command, 현재 값, option 및 enabled state. 각
  control은 operator-facing `label`과 `detail`을 포함하는 것이 좋으며, 사용할 수
  없는 control은 `disabled_reason`을 포함하는 것이 좋습니다.
- `constraints`: limit, prerequisite, safety boundary 및 operation을 사용할 수 없는
  이유.
- Domain record collection: lookup과 causal explanation에 필요한 실제 visible row.

Route는 이 계약을 `*.view.ts`에 위임할 수 있습니다. Optional `explanations` envelope는
selection, relationships, lifecycle 기준, deduplication, provenance를 표준화하며 metadata가
없으면 추측하지 않고 "선언되지 않음"으로 답합니다. Ontology와 Agent Activity가 먼저
적용하며 다른 route도 같은 envelope를 재사용합니다. Server는 크기를 제한하고 verifier는 claim에 쓰인 entry를 evidence manifest hash에 포함합니다.

#### 13.4.1 Cross-screen operational evidence

`ViewSnapshot`은 렌더링된 route에 대해서만 authoritative. Ontology route에서
`Issue` 또는 문제라는 domain noun만 있으면 current-screen reference로 유지합니다. 최근성, incident, outage,
failure 또는 cause 표현이 명시되면 server-owned `ConsoleReadModel`의
`OperationalEvidenceResolver`를 호출하며 browser operational evidence는 신뢰하지 않음.
Resolver는 최근 incident 최대 12개와 후보별 correlation audit row 최대 100개를 검색한 뒤 compact
`_operational_evidence` block을 `/chat`과 `/chat/stream` 모두에 주입.

Block은 fail-closed 상태 `matched`, `ambiguous`, `none`, `unavailable`을 가짐.
`matched`는 선택된 incident, bounded audit observation, response plan, 그리고
grounded이고 cause와 citation이 모두 있는 RCA hypothesis만 포함. Bragi는
abstained 또는 citation 없는 hypothesis에서 incident cause를 단정하면 안 됨.
`ambiguous`는 후보를 나열하고 operator 선택을 요청하며, `none`과 `unavailable`은
추측을 명시적으로 금지. 추가 system directive는 operational evidence가 있을
때만 주입되므로 일반 화면 질문은 lean prompt budget을 유지.

다른 cross-screen 질문에는 web adapter가 다음 authority 순서를 사용합니다.

1. incident 및 root-cause 질문에는 `OperationalEvidenceResolver`를 사용합니다.
2. Azure resource, KPI, pending approval, audit, incident 목록 질문에는 server-owned
  inventory/read-model tool을 사용합니다. Inventory 질문은 deterministic `query_inventory` fast path를 사용하고 broad health는 같은 KPI authority를
  사용하지만 model synthesis 전에 deterministic `read-model-health` path를
  사용합니다. 답변은 관측된 event sample, approval backlog, execution-mode mix,
  evidence time을 보고하며 모든 component가 healthy라고 추론하지 않습니다.
3. agent-owned domain에는 `PantheonChatDelegate`를 사용합니다. Bragi는 primary
  agent로 라우팅하고 bounded timeout으로 최대 3명의 matching contributor를
  호출합니다.
4. 개념 정의에는 canonical FDAI glossary를 사용합니다. 영어 concept turn은
  deterministic `concept-glossary` fast path를 사용하며, localized turn에는 같은
  선택 항목이 server-owned translation evidence로 제공됩니다.
5. 현재 화면에는 browser `ViewSnapshot`을 사용합니다.

서버는 turn을 resolve하기 전에 client가 보낸 `_operational_evidence`,
`_tool_evidence`, `_agent_evidence`를 제거합니다. Browser는 chat health, JSON,
streaming 및 action 요청에 인증된 bearer token을 보냅니다. Client session id는
길이가 제한되고 Bragi가 저장하기 전에 검증된 principal로 namespace되므로 두
사용자가 같은 id를 골라도 conversational state를 공유하지 않습니다. JSON 및
streaming response는 bounded delegation metadata를 반환하며 deck은 실제 primary
agent 이름으로 답변을 표시합니다.
Terminal claim verifier는 tool, agent 및 선택된 glossary evidence를 hashed
manifest에 포함하므로 server-grounded answer를 관련 없는 빈 화면과 비교하지
않습니다.

#### 13.4.2 Progressive answer verification

Web deck은 응답 latency와 answer trust를 분리해야 함. 하나의 assistant turn을
**provisional** answer로 즉시 stream한 뒤 검증하고, 모순되는 두 번째 답변을
추가하지 않고 같은 turn을 갱신. Server가 상태 머신을 소유하고 순서가 있는 SSE
event를 emit:

```text
evidence_resolving -> generating -> provisional -> verifying
  -> verified | consistent | corrected | unverified
```

`evidence_resolving` status에는 현재 화면 source의 bounded preview가 포함됩니다.
Server-side resolution이 끝나면 `generating` status가 해당 preview를 이번 turn에
선택된 실제 read-only tool, operational, agent 또는 glossary source로 교체합니다.
Client가 보낸 internal evidence는 두 번째 preview를 만들기 전에 제거됩니다. Deck은
text가 준비되고 최소 420 ms가 지날 때까지 retrieval trace를 유지한 다음, 같은
pending surface를 streaming answer로 전환합니다. 두 surface는 같은 폭과 정렬을
사용하며 짧은 entry motion과 staggered source row로 갑작스러운 layout jump를
줄입니다. 이 구간에 수신된 text는 adaptive visual queue로 들어가며 backlog에 따라
display frame마다 이미 pacing된 delta 1-3개를 drain합니다. 첫 paint에서 전체
buffer를 한 번에 표시하지 않습니다. Answer가 처음 표시될 때와 terminal revision이
render될 때 transcript는 preparation 중 operator가 위로 scroll했더라도 최신
content로 이동합니다. 완료된 reply는 manifest entry를 독립 source가 아니라
evidence reference로 표시합니다. Unsupported 문장을 제거하고 재검증을 통과한
bounded correction은 verified visual treatment를 사용합니다.

Reply renderer는 ATX heading, emphasis, strong text, strikethrough,
unordered/ordered list, read-only task list, blockquote, thematic break, 안전한
`http` / `https` / relative link, table, fenced code 및 chart block을 지원합니다.
닫히지 않은 code fence는 streaming 중 안정적인 plain preview로 표시하고 closing
fence가 도착한 뒤에만 highlighting합니다. 실행 가능하거나 안전하지 않은 link
scheme은 plain text로 유지합니다.

저장된 표시 preference가 없으면 Deck은 440 px right sidebar로 열립니다. Header
control은 같은 conversation을 유지하면서 이동 가능한 floating panel 또는 full
workspace로 전환합니다. Floating header title을 drag해 panel을 이동합니다. 왼쪽과
상단에는 12 px guard를 유지하고 오른쪽과 하단은 viewport 밖으로 이동할 수
있습니다. Sidebar의 왼쪽 separator를 pointer 또는 arrow key로 조작해 340-720 px
범위에서 resize할 수 있습니다. Right-sidebar mode는 shell body 폭을 현재 sidebar
폭만큼 줄이므로 navigation이나 page content를 덮지 않습니다. Floating과 dock
mode는 non-modal이며 focus를 가두거나 page interaction을 차단하지 않습니다. Full
workspace는 modal focus trap을 유지합니다. 선택한 mode와 sidebar 폭은 browser
local storage에 저장되므로 Deck이나 browser를 닫았다 다시 열어도 마지막 표시
형태를 복원합니다. Compact mobile viewport는 저장된 preference를 바꾸지 않고
full-screen geometry를 사용합니다.

- `verified`는 terminal answer가 server-owned operational 또는 inventory evidence에서
  render되었음을 의미.
- `consistent`는 browser의 현재 screen snapshot과 대조했지만 server projection이
  독립 검증하지 않았음을 의미.
- `corrected`는 provisional model text를 evidence result에서 만든 deterministic
  answer로 교체했음을 의미.
- `unverified`는 verification이 완료되지 않았음을 의미하며 `verified`와 같은
  trust check를 표시하면 안 됨.

Delegate된 agent의 provisional prose가 `consistent`로 유지되면 reply header는
해당 agent를 유지. Verification이 prose를 `corrected` 또는 `unverified` terminal
answer로 교체하면 header는 최종 narrator인 **Bragi**로 돌아감. 원래
`primary_agent`는 delegation 및 trace metadata에 보존하지만 verifier가 생성한
text의 작성자로 표시하지 않음.

모든 event는 단조 증가 `seq`를 가지며 answer를 바꾸는 event는 단조 증가
`revision`도 가짐. Client는 stale revision과 terminal event 이후 event를 무시.
Correction은 기존 turn id의 text를 교체해 conversation 순서와 accessibility
focus를 보존. Terminal canonical revision만 저장하거나 후속 turn history로 제공.

첫 shipped verifier는 두 번째 model call을 사용하지 않음. Cross-screen operational 및 Azure inventory
질문에서는 typed evidence state (`matched`, `ambiguous`, `none`, `unavailable`)로 terminal answer를
결정론적으로 render하므로 model prose가 선택 incident, 검색
범위, RCA cause 또는 absence claim을 바꿀 수 없음. `none`, `ambiguous`,
`unavailable`, grounded RCA가 없는 `matched`는 deterministic fast path를 사용:
server는 evidence lookup 직후 canonical answer를 stream하고 model을 호출하지 않음.
Grounded RCA가 있는 `matched`는 model prose를 provisional로 stream한 뒤 필요하면
canonical verified cause로 교체 MAY. Screen-only answer는 `consistent`로 종료.
Localized glossary answer에서는 unsupported scope-only addendum을 제거하고
deterministic verification을 다시 실행하는 bounded rewrite를 1회 적용할 수 있습니다.
그 밖의 unsupported claim은 계속 abstention으로 종료됩니다. 완전한 screen
snapshot에서 일부 claim만 mismatch이면 unsupported claim이 포함된 문장 전체를
제거하고 남은 answer를 다시 검증하는 bounded rewrite를 1회 적용할 수 있습니다.
Fact는 localized synonym을 bounded `aliases`로 publish할 수 있습니다. 중복 값은 가장 가까운 `label` 또는 alias에 bind하며 일치하지 않으면 ambiguous로 유지합니다. 이 correction은 rewrite 전후에 supported claim이 하나 이상 있어야 합니다. `0/N` 결과, truncated snapshot 또는 extraction overflow는 계속 abstention으로 종료됩니다.

Latency target은 request admission 후 첫 progress event 100 ms 이내, 일반 model
TTFT p95 2.5초 이내, evidence lookup 완료 후 fast-path terminal answer p95 500 ms
이내, provisional 완료 후 첫 verification event 100 ms 이내,
provisional-to-terminal verification p95 1초 이내. Progress는 실제 완료 check를
보고하며 가짜 percentage를 사용하지 않음.
Incremental SSE delta는 client-side delay 없이 render됩니다. 큰 single frame 또는
같은 tick의 queue burst만 paint-sized chunk와 짧은 cosmetic cadence로 묶습니다.
Deterministic fallback prose는 별도의 더 느린 typewriter cadence를 유지합니다.

Screen-only provisional answer는 두 번째 model call 없이 atomic claim artifact도
생성. Deterministic extractor는 ID, number, percentage, timestamp, causal assertion,
bounded-scope claim을 인식하며, 각 claim은 source span, normalized value, support
state, 정확한 snapshot evidence reference와 matching에 사용된 fact alias를 hashed evidence entry에 기록합니다. `evidence_manifest`는 route,
capture time, completeness, source path, canonical content hash를 기록하며 전체
snapshot 복사본이 아니라 claim이 실제 사용한 entry만 포함.

Bounded-scope 추출은 `no`, `none`, `없습니다` 또는 "이 화면에 표시되지 않음"처럼
명시적인 부재 표현만 처리. `all`, `always`, `모든`, `전부` 같은 positive universal
prose는 qualitative 표현으로 유지하며 `verified`로 표시하지 않음.
Universal 단어 하나만으로 일반 화면 설명을 deterministic global-scope claim으로
바꾸지 않음.

추출된 모든 claim은 모호하지 않은 snapshot entry의 지원을 받아야 함. 모두
통과하면 answer는 `consistent` 유지 (`verified` 아님: browser snapshot은 독립된
server projection이 아니기 때문). Check 가능한 claim이 없으면
`screen_no_checkable_claims` reason과 함께 `consistent` 유지. Unsupported 또는
ambiguous claim, truncated snapshot, malformed artifact, extraction overflow가 하나라도
있으면 provisional answer 전체를 localized abstention으로 교체하고 `unverified`로
종료; 문장 일부 삭제는 금지. 최종 persistence와 grounding UI에는 terminal claim과
manifest만 저장·표시.

Frozen customer-neutral claim corpus가 이 deterministic surface를 CI에서 gate.
초기 corpus는 supported/unsupported ID, number, percentage, timestamp, causal
assertion, bounded absence, ambiguity, claim-free prose를 포함. Promotion은
unsupported-claim escape rate와 clean-answer rejection rate가 모두 정확히 `0.0`을
유지해야 하며, 빈 label set이나 반전된 label이 조용히 통과하지 않도록 metric
accounting도 독립 테스트. 이 gate는 qualitative prose의 semantic verification을
주장하지 않음: extract 가능한 structured claim이 없는 answer는
`screen_no_checkable_claims`와 함께 `consistent`로 표시하고 `verified`로 표시하지
않음.

Optional local semantic verifier는 2026-07-17 measured retention gate 실패 후 제거됨.
고정된 MIT license multilingual MiniLM ONNX model을 customer-neutral English/Korean
case 200개에서 실행. 설정 threshold `0.8`에서 contradiction set 탐지율은 `0.0%`, 전체
case의 `80.0%`는 `unknown` 반환. Clean-answer false positive와 authority change는 모두
0, warm p95 latency는 `10.05 ms`, cold start는 `1126 ms`, peak RSS는 약 `571 MiB`,
model과 tokenizer footprint는 `124498008` byte. Unknown outcome은 benefit으로 계산하지
않으므로 측정 결과는 promotion이 아니라 제거를 선택.

`local-nli` dependency group, ONNX provider, Settings toggle, request flag, response
metadata, 관련 runtime test를 함께 제거. Deterministic evidence와 atomic-claim verifier는
권위가 유지되고 변경되지 않음. 향후 proposal이 material contradiction benefit을 측정해
제시하기 전까지 qualitative prose는 verified로 표시하지 않음.

#### 13.4.2.1 결정론적 AnswerPlan

이제 모든 Command Deck turn은 prose generation 전에 typed `AnswerPlan`을 받습니다. 순수
`core/conversation/answer_plan.py` parser는 영문과 한글 요청을 definition, why, procedure,
comparison, diagnosis, status, list, summary, proposal, open question으로 분류합니다. 또한 현재
turn의 명시적 detail, format, evidence, audience modifier를 기록합니다. 같은 turn에서 명시적
modifier가 충돌하면 뒤에 나온 지시가 우선합니다. 저장된 preference는 현재 turn을 override할 수
없습니다.

Plan은 intent별 section, bounded word target, format, evidence requirement를 제공합니다. Server가
소유한 snapshot metadata로 주입되고 JSON과 SSE terminal response에 모두 반환되며 transcript에
additive하게 저장됩니다. Console은 이를 compact한 localized `Bragi / intent / detail` label로
렌더링합니다. Browser는 plan의 subject text를 버리고 prompt나 hidden reasoning을 노출하지 않습니다.

Phase B는 기존 `UserPreferenceStore` seam을 통해 명시적이고 principal 범위인 응답 preference
profile을 추가합니다. Settings에서 운영자는 기본 `brief`/`standard`/`deep` detail level을 확인하고
편집하며, 기본 응답 format을 선택하고, profile을 삭제하지 않은 채 적용을 비활성화하거나, 계정
projection과 browser-local 표시 preference를 함께 초기화할 수 있습니다. Profile은 검증된 intent별
detail 및 format map도 보관할 수 있습니다. 조회에는 인증된 principal만 사용하고 server는 client가
보낸 `_answer_plan` metadata를 폐기한 뒤 자체 plan을 구성합니다.

저장된 기본값은 현재 turn에서 충돌하는 응답 형태를 요청하지 않은 경우에만 적용됩니다. `briefly`,
`step by step`, `짧게`, `표로`와 같은 명시적 modifier가 계속 우선합니다. 일회성 modifier는 bounded
turn metadata에 기록되지만 저장 profile로 promotion되지 않습니다. 자동 preference learning은 계속
꺼져 있습니다. 향후 shadow 측정에서 현재 답변을 변경하지 않고 반복된 명시적 signal을 평가할 수
있습니다. Locale 결정 동작은 바뀌지 않습니다.

#### 13.4.2.2 Shadow Answer Planning Round

Phase C는 전용 provider seam 뒤에 read-only `AnswerPlanningRound`를 추가합니다. Eligible `why`,
`comparison`, `diagnosis` turn과 명시적인 다중 관점 요청에서 shadow로 실행합니다. Brief 요청,
definition, status, list, direct tool 결과 또는 complementary contributor가 없는 route에서는 planning
task를 만들지 않습니다. Eligible plan은 `discuss=shadow`를 전달하고 나머지는 `discuss=skip`을
유지합니다.

Round는 결정론적인 score 및 agent 이름 순서로 contributor를 최대 2명 선택하고 read-only
conversational port를 병렬 호출합니다. Contributor는 grounded fact, 보증된 evidence reference, 추천
section, caveat, confidence가 포함된 typed `AnswerContribution` record를 반환합니다. Production
pantheon adapter는 routine collection에서 Bragi, Norns, Odin을 제외합니다. Saga는 audit, history,
issue 또는 handoff 질문에만 참여합니다. Action 형태의 요청은 기존 typed-pipeline guard를 통해
abstain합니다.

Shipping limit은 contributor 2명, round 1회, `1200 ms`, estimated added token `800`으로 고정하고 nested
round는 비활성화합니다. Timeout, exception, abstention, agent mismatch 또는 token overflow는 bounded
degraded metadata가 됩니다. 지원 가능한 답변을 차단하거나 변경하지 않습니다. Phase C에서는
contributor fact가 narrator snapshot에 들어가지 않으므로 primary-only answer가 terminal answer로
유지됩니다.

JSON 및 SSE terminal response, durable turn metadata, browser transcript는 status, consulted agent,
evidence reference, 추천 section, failure kind, elapsed time, token estimate, effective budget, section
coverage, unique 또는 duplicate evidence count가 포함된 동일한 bounded shadow record를 전달합니다.
Prompt, free-form contributor reasoning 또는 hidden chain-of-thought는 전달하지 않습니다. Structured
log는 count와 latency만 emit합니다. Answer-plan coverage와 contributor utility는 deterministic answer
trust status와 분리됩니다.

Phase D selective activation과 Phase E cross-domain conflict handling은 아직 promotion하지 않습니다.
Promotion하려면 frozen bilingual evaluation set, unsupported-claim escape 및 authority violation 0건,
clean-answer regression 없음, 그리고 이 shadow baseline에서 측정한 latency, token cost, unique-evidence,
correction-rate, follow-up-rate gate를 통과해야 합니다.

#### 13.4.3 실시간 관찰 계약

읽기 전용 SPA는 현재 상태 진입점으로 **실시간 > 실시간**을 제공합니다. 이
화면은 관찰 연결 여부, 지금 주의가 필요한 제어 루프 작업, 기록된 근거의 위치라는
세 가지 제한된 질문에 답합니다. 인시던트, 승인, 감사, 추적, 에이전트 또는 통제
보증 화면을 대체하지 않습니다.

- **대기열이 기본 보기입니다.** 실패, 게시된 지연 예산을 초과한 작업, 승인 대기,
  거부, 활성 작업, 최근 완료 순으로 정렬합니다. `correlation_id`가 조사 키입니다.
- **흐름은 보조 보기입니다.** 고정 슬롯 활동 화면은 처리량과 단계 진행을
  시각화하지만 우선순위를 결정하지 않습니다.
- **지연 상태는 권위 있는 값을 사용합니다.** 단계 스트림이 양수
  `latency_budget_ms`를 제공하고 관찰 경과 시간이 이를 초과할 때만 지연으로
  표시합니다. 예산이 없으면 브라우저가 임계값을 만들지 않으며 지연이라고
  단정하지 않습니다.
- **모드는 추론하지 않고 기록합니다.** 제어 루프는 실제 `Action.mode`를 단계
  프레임에 게시합니다. `execute` 단계 도달만으로 shadow mode라고 판단하지
  않습니다.
- **Observation source는 기록하며 추론하지 않습니다.** Live와 Agent Activity frame은
  top-level `source`로 `synthetic-dev`, `replay`, `runtime-observed`, `unknown`을
  전달합니다. Legacy 또는 알 수 없는 값은 `unknown`으로 normalize하며 한 browser
  connection에서 서로 다른 known value가 관찰되면 `mixed`로 렌더링합니다. Browser는 dev
  mode, authentication mode, endpoint URL에서 source를 추론하지 않습니다.
  `runtime-observed`는 producer path를 설명할 뿐 Azure health 또는 execution attestation이
  아닙니다.
- **종단 상태가 권위 있는 값입니다.** 하나의 이벤트에 대한 finding별 게이트
  프레임은 서로 다른 결정을 보고할 수 있습니다. 종단 `audit.done` 프레임은
  이벤트 수준 결과와 결정을 제공하며 모든 중간 값을 대체합니다. 브라우저는
  관찰한 모든 ActionType을 유지하고, 여러 finding이 있는 이벤트를 마지막 작업
  하나가 아니라 작업 집합으로 표시합니다.
- **재전송은 안전하게 처리합니다.** 반복된 종단 프레임은 기존 타일을 갱신하지만
  처리량, 게이트 구성, 티어 구성 또는 최근 결과를 다시 증가시키지 않습니다.
- **화면 고정은 표시에만 영향을 줍니다.** 스트림 연결은 유지되고 고정 중 수신한
  프레임 수를 표시하며, 모든 종단 결과의 기록 원본은 이력에 유지됩니다.
- **보존 범위는 제한됩니다.** 완료된 승인 타일은 일반 결과보다 오래 표시한 뒤
  60개 표시 슬롯에서 제거합니다. 전체 대기열은 승인 화면이 소유하므로 오래된
  실시간 상태가 새 이벤트 관찰을 막지 않습니다. 선택한 타일은 상세 패널이 열린
  동안에만 고정되므로 운영자가 확인 중인 근거가 사라지지 않습니다.
- **상세 이동 경로가 명시적입니다.** 상세 패널은 관찰된 단계 추적, 에이전트
  담당, 모드, 결정, 상관관계 키를 보여주고 추적, 감사, 아키텍처로 연결합니다.
  실행 또는 승인 컨트롤은 제공하지 않습니다.
- **상세 패널은 키보드 포커스를 포함합니다.** 상세 패널은 접근 가능한 모달
  대화 상자입니다. 열리면 닫기 컨트롤로 포커스가 이동하고 Tab 포커스는 패널
  안에 머뭅니다. Escape로 닫으면 패널을 연 행 또는 타일로 포커스가 돌아갑니다.

실시간 헤더는 스트림에서 확인할 수 있는 사실만 보고합니다. 연결 상태, 마지막
관찰 이벤트 경과 시간, 구성된 환경 상태, 화면 고정 또는 실시간 추적 상태입니다.
Canary 상태, kill-switch 상태, 스트림 누락 수, 측정된 가드 지표는 서버가 소유한
read model 필드가 필요합니다. 이 계약이 생기기 전까지 브라우저는 해당 값을
사용할 수 없음으로 표시해야 합니다. CFR, false-positive rate, rollback rate,
policy-violation escape는 측정 기간, 기준선, 표본 수와 함께 통제 보증 화면에
표시합니다.
