---
title: Operator Console - View Snapshot Contract
translation_of: operator-console-view-snapshot.md
translation_source_sha: 1d8cb6f5bdc9ce94bc02ef42f61a05f077458ec5
translation_revised: 2026-08-14
---

# Operator Console - 화면 스냅샷 계약

> [operator-console-ko.md](operator-console-ko.md) 섹션 13.4에서 분리한 focused 소유자 문서입니다.

### 13.4 화면 스냅샷 - self-describing 화면 계약 (web deck)

읽기 전용 콘솔 SPA는 오퍼레이터가 지금 보는 화면을 `ViewSnapshot` 으로
캡처해 `POST /chat` 의 `view_context` 로 보냄
(`console/src/deck/context.tsx`). 스냅샷은 단순 값 다이제스트가 아니라
화면 *모델* 이라, 서술기가 per-screen answerer 없이도 화면과 그 용어를
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

Interactive 화면은 KPI counter만이 아니라 완전한 운영자 모델을 publish하는
것이 좋습니다. `purpose`, `glossary`, `facts` 외에도 `records`에 다음을
포함합니다.

- `sections`: 화면에 보이는 영역과 각 영역의 의미.
- `controls`: 사용 가능한 입력/명령, 현재 값, 옵션 및 활성화된 상태. 각
  컨트롤은 operator-facing `label`과 `detail`을 포함하는 것이 좋으며, 사용할 수
  없는 컨트롤은 `disabled_reason`을 포함하는 것이 좋습니다.
- `constraints`: 한도, 선행 조건, 안전성 경계 및 연산을 사용할 수 없는
  이유.
- 도메인 기록 수집: 조회와 causal explanation에 필요한 실제 visible 행.

경로는 이 계약을 `*.view.ts`에 위임할 수 있습니다. 선택적 `explanations` 묶음은
선택, relationships, 수명 주기 기준, deduplication, 출처 이력을 표준화하며 메타데이터가
없으면 추측하지 않고 "선언되지 않음"으로 답합니다. 온톨로지와 에이전트 활동이 먼저
적용하며 다른 경로도 같은 묶음을 재사용합니다. 서버는 크기를 제한하고 검증기는 점유에 쓰인 항목을 근거 매니페스트 해시에 포함합니다.

#### 13.4.1 화면 간 operational 근거

`ViewSnapshot`은 렌더링된 경로에 대해서만 권위 있는. 온톨로지 경로에서
`Issue` 또는 문제라는 도메인 명사만 있으면 current-screen 참조로 유지합니다. 최근성, 인시던트, 장애,
실패 또는 원인 표현이 명시되면 서버가 소유한 `ConsoleReadModel`의
`OperationalEvidenceResolver`를 호출하며 브라우저 operational 근거는 신뢰하지 않음.
해석기는 최근 인시던트 최대 12개와 후보별 상관관계 감사 행 최대 100개를 검색한 뒤 간결한
`_operational_evidence` 블록을 `/chat`과 `/chat/stream` 모두에 주입.

블록은 실패 시 차단 상태 `matched`, `ambiguous`, `none`, `unavailable`을 가짐.
`matched`는 선택된 인시던트, 범위가 제한된 감사 관측, 응답 계획, 그리고
근거에 기반한이고 원인과 인용이 모두 있는 RCA 가설만 포함. Bragi는
abstained 또는 인용 없는 가설에서 인시던트 원인을 단정하면 안 됨.
`ambiguous`는 후보를 나열하고 운영자 선택을 요청하며, `none`과 `unavailable`은
추측을 명시적으로 금지. 추가 system directive는 operational 근거가 있을
때만 주입되므로 일반 화면 질문은 lean 프롬프트 예산을 유지.

다른 화면 간 질문에는 web 어댑터가 다음 권한 순서를 사용합니다.

1. 인시던트 및 root-cause 질문에는 `OperationalEvidenceResolver`를 사용합니다.
2. Azure 리소스, KPI, pending 승인, 감사, 인시던트 목록 질문에는 서버가 소유한
  인벤토리/read-model 도구를 사용합니다. 인벤토리 질문은 결정론적 `query_inventory` fast 경로를 사용하고 broad 상태는 같은 KPI 권한을
  사용하지만 모델 종합 전에 결정론적 `read-model-health` 경로를
  사용합니다. 답변은 관측된 이벤트 샘플, 승인 적체, execution-mode mix,
  근거 시간을 보고하며 모든 컴포넌트가 healthy라고 추론하지 않습니다.
3. agent-owned 도메인에는 `PantheonChatDelegate`를 사용합니다. Bragi는 기본
  에이전트로 라우팅하고 범위가 제한된 시간 초과로 최대 3명의 matching 기여자를
  호출합니다.
4. 개념 정의에는 정본 FDAI glossary를 사용합니다. 영어 개념 턴은
  결정론적 `concept-glossary` fast 경로를 사용하며, localized 턴에는 같은
  선택 항목이 서버가 소유한 translation 근거로 제공됩니다. 근거 부족 또는 신뢰도
  임계값 미달 처리에 관한 질문은 에이전트나 proposed 변경을 언급해도 이 경로를
  유지합니다. 이러한 부수 용어는 에이전트 위임이나 액션 근거를 시작하지
  않습니다.
5. 현재 화면에는 브라우저 `ViewSnapshot`을 사용합니다.

서버는 턴을 해석하기 전에 클라이언트가 보낸 `_operational_evidence`,
`_tool_evidence`, `_agent_evidence`를 제거합니다. 브라우저는 채팅 상태, JSON,
스트리밍 및 액션 요청에 인증된 bearer 토큰을 보냅니다. 클라이언트 세션 id는
길이가 제한되고 Bragi가 저장하기 전에 검증된 principal로 이름 공간되므로 두
사용자가 같은 id를 골라도 conversational 상태를 공유하지 않습니다. JSON 및
스트리밍 응답은 범위가 제한된 위임 메타데이터를 반환하며 deck은 실제 기본
에이전트 이름으로 답변을 표시합니다.
최종 점유 검증기는 도구, 에이전트 및 선택된 glossary 근거를 hashed
매니페스트에 포함하므로 server-grounded 답변을 관련 없는 빈 화면과 비교하지
않습니다.

#### 13.4.2 Progressive 답변 검증

Web deck은 응답 지연 시간과 답변 trust를 분리해야 함. 하나의 assistant 턴을
**provisional** 답변으로 즉시 스트림한 뒤 검증하고, 모순되는 두 번째 답변을
추가하지 않고 같은 턴을 갱신. 서버가 상태 머신을 소유하고 순서가 있는 SSE
이벤트를 발행:

```text
evidence_resolving -> generating -> provisional -> verifying
  -> verified | consistent | corrected | unverified
```

`evidence_resolving` 상태에는 현재 화면 출처의 범위가 제한된 미리 보기가 포함됩니다.
서버 측 해석이 끝나면 `generating` 상태가 해당 미리 보기를 이번 턴에
선택된 실제 읽기 전용 도구, operational, 에이전트 또는 glossary 출처로 교체합니다.
클라이언트가 보낸 내부 근거는 두 번째 미리 보기를 만들기 전에 제거됩니다. Deck은
텍스트가 준비되고 최소 420 ms가 지날 때까지 수집 추적을 유지한 다음, 같은
pending 표면을 스트리밍 답변으로 전환합니다. 두 표면은 같은 폭과 정렬을
사용하며 짧은 항목 motion과 staggered 출처 행으로 갑작스러운 배치 jump를
줄입니다. 이 구간에 수신된 텍스트는 adaptive visual 큐로 들어가며 적체에 따라
display 프레임마다 이미 pacing된 delta 1-3개를 배출합니다. 첫 그리기에서 전체
버퍼를 한 번에 표시하지 않습니다. Terminal-only 답변은 토큰을 최대 30개 조각으로 묶어 visual 노출을 약 300 ms로 제한하며 서버 완료 시각이 실행 시각의 기준입니다. 답변이 처음 표시될 때와 최종 개정 번호가
렌더링될 때 대화 기록은 preparation 중 운영자가 위로 scroll했더라도 최신
내용으로 이동합니다. 완료된 회신은 매니페스트 항목을 독립 출처가 아니라
근거 참조로 표시합니다. 지원하지 않는 문장을 제거하고 재검증을 통과한
범위가 제한된 correction은 검증된 visual 처리를 사용합니다.

회신 렌더러는 ATX heading, emphasis, strong 텍스트, strikethrough,
unordered/ordered 목록, 읽기 전용 작업 목록, blockquote, thematic break, 안전한
`http` / `https` / relative 링크, 표, fenced 코드 및 chart 블록을 지원합니다.
닫히지 않은 코드 fence는 스트리밍 중 안정적인 plain 미리 보기로 표시하고 closing
fence가 도착한 뒤에만 highlighting합니다. 실행 가능하거나 안전하지 않은 링크
체계는 plain 텍스트로 유지합니다.

저장된 표시 선호 설정이 없으면 Deck은 440 px right sidebar로 열립니다. 헤더
컨트롤은 같은 대화를 유지하면서 이동 가능한 floating 패널 또는 full
workspace로 전환합니다. Floating 헤더 제목을 끌기해 패널을 이동합니다. 왼쪽과
상단에는 12 px 가드를 유지하고 오른쪽과 하단은 뷰포트 밖으로 이동할 수
있습니다. Sidebar의 왼쪽 구분자를 포인터 또는 arrow 키로 조작해 340-720 px
범위에서 resize할 수 있습니다. Right-sidebar 모드는 셸 본문 폭을 현재 sidebar
폭만큼 줄이므로 탐색이나 페이지 내용을 덮지 않습니다. Floating과 dock
모드는 non-modal이며 focus를 가두거나 페이지 interaction을 차단하지 않습니다. Full
workspace는 모달 focus trap을 유지합니다. 선택한 모드와 sidebar 폭은 브라우저
로컬 저장소에 저장되므로 Deck이나 브라우저를 닫았다 다시 열어도 마지막 표시
형태를 복원합니다. 간결한 mobile 뷰포트는 저장된 선호 설정을 바꾸지 않고
full-screen 형상을 사용합니다.

- `verified`는 최종 답변이 서버가 소유한 operational 또는 인벤토리 근거에서
  렌더링되었음을 의미.
- `consistent`는 브라우저의 현재 화면 스냅샷과 대조했지만 서버 변환 결과가
  독립 검증하지 않았음을 의미.
- `corrected`는 provisional 모델 텍스트를 근거 결과에서 만든 결정론적
  답변으로 교체했음을 의미.
- `unverified`는 검증이 완료되지 않았음을 의미하며 `verified`와 같은
  trust 검사를 표시하면 안 됨.

최종 회신 헤더는 항상 사람이 보는 서술기인 **Bragi**로 유지됩니다.
Delegated 에이전트는 visible 인계 및 execution-activity 행에 표시되고 원래
`primary_agent`는 위임 및 추적 메타데이터에 보존됩니다. 관측 소유권은
보이지만 전문가를 human 대화의 소유자로 표시하지 않습니다.

모든 이벤트는 단조 증가 `seq`를 가지며 답변을 바꾸는 이벤트는 단조 증가
`revision`도 가짐. 클라이언트는 stale 개정 번호와 최종 이벤트 이후 이벤트를 무시.
Correction은 기존 턴 id의 텍스트를 교체해 대화 순서와 accessibility
focus를 보존. 최종 정본 개정 번호만 저장하거나 후속 턴 이력으로 제공.

첫 shipped 검증기는 두 번째 모델 호출을 사용하지 않음. 화면 간 operational 및 Azure 인벤토리
질문에서는 타입이 지정된 근거 상태 (`matched`, `ambiguous`, `none`, `unavailable`)로 최종 답변을
결정론적으로 렌더링하므로 모델 산문이 선택 인시던트, 검색
범위, RCA 원인 또는 absence 점유를 바꿀 수 없음. `none`, `ambiguous`,
`unavailable`, 근거에 기반한 RCA가 없는 `matched`는 결정론적 fast 경로를 사용:
서버는 근거 조회 직후 정본 답변을 스트림하고 모델을 호출하지 않음.
근거에 기반한 RCA가 있는 `matched`는 모델 산문을 provisional로 스트림한 뒤 필요하면
정본 검증된 원인으로 교체 MAY. Screen-only 답변은 `consistent`로 종료.
Localized glossary 답변에서는 지원하지 않는 scope-only addendum을 제거하고
결정론적 검증을 다시 실행하는 범위가 제한된 rewrite를 1회 적용할 수 있습니다.
그 밖의 지원하지 않는 점유는 계속 abstention으로 종료됩니다. 완전한 화면
스냅샷에서 일부 점유만 mismatch이면 지원하지 않는 점유가 포함된 문장 전체를
제거하고 남은 답변을 다시 검증하는 범위가 제한된 rewrite를 1회 적용할 수 있습니다.
사실은 localized synonym을 범위가 제한된 `aliases`로 publish할 수 있습니다. 중복 값은 가장 가까운 `label` 또는 별칭에 연결하며 일치하지 않으면 모호한으로 유지합니다. 이 correction은 rewrite 전후에 supported 점유가 하나 이상 있어야 합니다. `0/N` 결과, 잘린 스냅샷 또는 추출 초과분은 계속 abstention으로 종료됩니다.

지연 시간 대상은 요청 admission 후 첫 진행 상황 이벤트 100 ms 이내, 일반 모델
TTFT p95 2.5초 이내, 근거 조회 완료 후 fast-path 최종 답변 p95 500 ms
이내, provisional 완료 후 첫 검증 이벤트 100 ms 이내,
provisional-to-terminal 검증 p95 1초 이내. 진행 상황은 실제 완료 검사를
보고하며 가짜 비율을 사용하지 않음.
Incremental SSE delta는 클라이언트 측 delay 없이 렌더링됩니다. 큰 single 프레임 또는
같은 틱의 큐 burst만 paint-sized 조각과 짧은 cosmetic cadence로 묶습니다.
결정론적 대체 경로 산문은 별도의 더 느린 typewriter cadence를 유지합니다.

현재 화면의 설명, 묘사, 요약 또는 walkthrough를 명시적으로 요청하는 영어 또는 한국어 질문에는
최대 120단어의 간결한 운영자 walkthrough를 제공합니다. 용도, 현재 상태, 가장 중요한 visible
근거를 먼저 다루고 스냅샷에 있는 경우에만 컨트롤, 제약 또는 안전성
경계를 설명합니다. Narrator는 raw 스냅샷 필드를 반복하거나 control-loop 단계를
추측하거나 별도 예시 interpretation을 추가하지 않습니다. 감지는 제한된 줄바꿈과 "이 화면에
대해 알려줘" 같은 일반 표현을 허용하지만 명시적으로 부정된 요청에는 walkthrough directive를
활성화하지 않습니다.

Screen-only provisional 답변은 두 번째 모델 호출 없이 atomic 점유 산출물도
생성. 결정론적 추출기는 ID, number, 비율, 시각, causal assertion,
bounded-scope 점유를 인식하며, 각 점유는 출처 구간, 정규화된 값, support
상태, 정확한 스냅샷 근거 참조와 matching에 사용된 사실 별칭을 hashed 근거 항목에 기록합니다. `evidence_manifest`는 경로,
수집 시간, 완전성, 출처 경로, 정본 내용 해시를 기록하며 전체
스냅샷 복사본이 아니라 점유가 실제 사용한 항목만 포함.

Bounded-scope 추출은 `no`, `none`, `없습니다` 또는 "이 화면에 표시되지 않음"처럼
명시적인 부재 표현만 처리. `all`, `always`, `모든`, `전부` 같은 긍정 universal
산문은 qualitative 표현으로 유지하며 `verified`로 표시하지 않음.
Universal 단어 하나만으로 일반 화면 설명을 결정론적 global-scope 점유로
바꾸지 않음.

추출된 모든 점유는 모호하지 않은 스냅샷 항목의 지원을 받아야 함. 모두
통과하면 답변은 `consistent` 유지 (`verified` 아님: 브라우저 스냅샷은 독립된
서버 변환 결과가 아니기 때문). 검사 가능한 점유가 없으면
`screen_no_checkable_claims` 사유와 함께 `consistent` 유지. 지원하지 않는 또는
모호한 점유, 잘린 스냅샷, malformed 산출물, 추출 초과분이 하나라도
있으면 provisional 답변 전체를 localized abstention으로 교체하고 `unverified`로
종료; 문장 일부 삭제는 금지. 최종 영속성과 grounding UI에는 최종 점유와
매니페스트만 저장·표시.

고정된 customer-neutral 점유 말뭉치가 이 결정론적 표면을 CI에서 게이트.
초기 말뭉치는 supported/지원하지 않는 ID, number, 비율, 시각, causal
assertion, 범위가 제한된 absence, 모호함, claim-free 산문을 포함. 승격은
unsupported-claim escape 비율과 clean-answer 거절 비율이 모두 정확히 `0.0`을
유지해야 하며, 빈 라벨 집합이나 반전된 라벨이 조용히 통과하지 않도록 메트릭
accounting도 독립 테스트. 이 게이트는 qualitative 산문의 의미 검증을
주장하지 않음: extract 가능한 구조화된 점유가 없는 답변은
`screen_no_checkable_claims`와 함께 `consistent`로 표시하고 `verified`로 표시하지
않음.

선택적 로컬 의미 검증기는 2026-07-17 measured 보존 게이트 실패 후 제거됨.
고정된 MIT license 다국어 MiniLM ONNX 모델을 customer-neutral English/Korean
사례 200개에서 실행. 설정 임계값 `0.8`에서 contradiction 집합 탐지율은 `0.0%`, 전체
사례의 `80.0%`는 `unknown` 반환. Clean-answer false 긍정과 권한 변경은 모두
0, warm p95 지연 시간은 `10.05 ms`, cold 시작은 `1126 ms`, peak RSS는 약 `571 MiB`,
모델과 토크나이저 footprint는 `124498008` 바이트. 알 수 없음 결과는 benefit으로 계산하지
않으므로 측정 결과는 승격이 아니라 제거를 선택.

`local-nli` 의존성 그룹, ONNX 프로바이더, Settings 토글, 요청 플래그, 응답
메타데이터, 관련 런타임 테스트를 함께 제거. 결정론적 근거와 atomic-claim 검증기는
권위가 유지되고 변경되지 않음. 향후 제안이 자료 contradiction benefit을 측정해
제시하기 전까지 qualitative 산문은 검증된으로 표시하지 않음.

#### 13.4.2.1 결정론적 AnswerPlan

이제 모든 Command Deck 턴은 산문 세대 전에 타입이 지정된 `AnswerPlan`을 받습니다. 순수
`core/conversation/answer_plan.py` 파서는 영문과 한글 요청을 정의, why, procedure,
비교, diagnosis, 상태, 목록, 요약, 제안, 열림 질문으로 분류합니다. 또한 현재
턴의 명시적 상세, format, 근거, 대상 modifier를 기록합니다. 같은 턴에서 명시적
modifier가 충돌하면 뒤에 나온 지시가 우선합니다. 저장된 선호 설정은 현재 턴을 재정의할 수
없습니다.

계획은 의도별 섹션, 범위가 제한된 word 대상, format, 근거 요구사항을 제공합니다. 서버가
소유한 스냅샷 메타데이터로 주입되고 JSON과 SSE 최종 응답에 모두 반환되며 대화 기록에
가산하게 저장됩니다. Console은 이를 간결한한 localized `Bragi / intent / detail` 라벨로
렌더링합니다. 브라우저는 계획의 대상 텍스트를 버리고 프롬프트나 hidden reasoning을 노출하지 않습니다.

단계 B는 기존 `UserPreferenceStore` 경계를 통해 명시적이고 principal 범위인 응답 선호 설정
프로파일을 추가합니다. Settings에서 운영자는 기본 `brief`/`standard`/`deep` 상세 수준을 확인하고
편집하며, 기본 응답 format을 선택하고, 프로파일을 삭제하지 않은 채 적용을 비활성화하거나, 계정
변환 결과와 browser-local 표시 선호 설정을 함께 초기화할 수 있습니다. 프로파일은 검증된 의도별
상세 및 format 지도도 보관할 수 있습니다. 조회에는 인증된 principal만 사용하고 서버는 클라이언트가
보낸 `_answer_plan` 메타데이터를 폐기한 뒤 자체 계획을 구성합니다.

저장된 기본값은 현재 턴에서 충돌하는 응답 형태를 요청하지 않은 경우에만 적용됩니다. `briefly`,
`step by step`, `짧게`, `표로`와 같은 명시적 modifier가 계속 우선합니다. 일회성 modifier는 범위가 제한된
턴 메타데이터에 기록되지만 저장 프로파일로 승격되지 않습니다. 자동 선호 설정 learning은 계속
꺼져 있습니다. 향후 shadow 측정에서 현재 답변을 변경하지 않고 반복된 명시적 신호를 평가할 수
있습니다. 로케일 결정 동작은 바뀌지 않습니다.

#### 13.4.2.2 Shadow 답변 계획 수립 라운드

단계 C는 전용 프로바이더 경계 뒤에 읽기 전용 `AnswerPlanningRound`를 추가합니다. 조건을 충족한 `why`,
`comparison`, `diagnosis` 턴과 명시적인 다중 관점 요청에서 shadow로 실행합니다. Brief 요청,
정의, 상태, 목록, direct 도구 결과 또는 complementary 기여자가 없는 경로에서는 계획 수립
작업을 만들지 않습니다. 조건을 충족한 계획은 `discuss=shadow`를 전달하고 나머지는 `discuss=skip`을
유지합니다.

라운드는 결정론적인 점수 및 에이전트 이름 순서로 기여자를 최대 2명 선택하고 읽기 전용
conversational 포트를 병렬 호출합니다. 기여자는 근거에 기반한 사실, 보증된 근거 참조, 추천
섹션, caveat, 확신도가 포함된 타입이 지정된 `AnswerContribution` 기록을 반환합니다. 운영
pantheon 어댑터는 routine 수집에서 Bragi, Norns, Odin을 제외합니다. Saga는 감사, 이력,
issue 또는 인계 질문에만 참여합니다. 액션 형태의 요청은 기존 typed-pipeline 가드를 통해
abstain합니다.

Shipping 한도는 기여자 2명, 라운드 1회, `1200 ms`, estimated added 토큰 `800`으로 고정하고 중첩된
라운드는 비활성화합니다. 시간 초과, exception, abstention, 에이전트 mismatch 또는 토큰 초과분은 범위가 제한된
degraded 메타데이터가 됩니다. 지원 가능한 답변을 차단하거나 변경하지 않습니다. 단계 C에서는
기여자 사실이 서술기 스냅샷에 들어가지 않으므로 primary-only 답변이 최종 답변으로
유지됩니다.

JSON 및 SSE 최종 응답, 영속 턴 메타데이터, 브라우저 대화 기록은 상태, consulted 에이전트,
근거 참조, 추천 섹션, 실패 종류, 경과 시간, 토큰 추정치, effective 예산, 섹션
커버리지, unique 또는 중복 근거 개수가 포함된 동일한 범위가 제한된 shadow 기록을 전달합니다.
프롬프트, free-form 기여자 reasoning 또는 hidden 추론 과정은 전달하지 않습니다. 구조화된
로그는 개수와 지연 시간만 발행합니다. Answer-plan 커버리지와 기여자 유틸리티는 결정론적 답변
trust 상태와 분리됩니다.

단계 D selective activation과 단계 E cross-domain 충돌 처리는 아직 승격하지 않습니다.
승격하려면 고정된 bilingual evaluation 집합, unsupported-claim escape 및 권한 violation 0건,
clean-answer 회귀 없음, 그리고 이 shadow 기준선에서 측정한 지연 시간, 토큰 비용, unique-evidence,
correction-rate, follow-up-rate 게이트를 통과해야 합니다.

순수 `answer_planning_qualification` 평가기는 버전이 고정된 변경할 수 없는 배치를 입력받아 내용
주소가 지정된 준비 상태 증적을 반환합니다. 기본 검토 하한은 100개 사례이며 English와 Korean
사례가 각각 50개 이상이어야 합니다. Unsupported-claim escape, 권한 violation, clean-answer
회귀는 모두 0이어야 합니다. 계획 수립 p95는 `1200 ms` 이내여야 하고 어떤 사례도 추가 토큰
`800`개를 초과할 수 없습니다. 사례의 절반 이상에서 unique 근거가 늘어나야 하며 correction 및
후속 조치 비율은 primary-only 기준선보다 나빠지지 않아야 합니다. 증적은 별도 검토를 위한
준비 상태만 보고합니다. 계획 수립을 활성화하거나 최종 답변 또는 승격 상태를 변경할 수
없습니다.

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
  프레임에 게시합니다. `execute` 단계 도달만으로 shadow 모드라고 판단하지
  않습니다.
- **관측 출처는 기록하며 추론하지 않습니다.** 실제 운영과 에이전트 활동 프레임은
  top-level `source`로 `synthetic-dev`, `replay`, `runtime-observed`, `unknown`을
  전달합니다. 이전 방식 또는 알 수 없는 값은 `unknown`으로 normalize하며 한 브라우저
  연결에서 서로 다른 known 값이 관찰되면 `mixed`로 렌더링합니다. 브라우저는 dev
  모드, authentication 모드, 엔드포인트 URL에서 출처를 추론하지 않습니다.
  `runtime-observed`는 생산자 경로를 설명할 뿐 Azure 상태 또는 실행 증명이
  아닙니다.
- **종단 상태가 권위 있는 값입니다.** 하나의 이벤트에 대한 발견 사항별 게이트
  프레임은 서로 다른 결정을 보고할 수 있습니다. 종단 `audit.done` 프레임은
  이벤트 수준 결과와 결정을 제공하며 모든 중간 값을 대체합니다. 브라우저는
  관찰한 모든 ActionType을 유지하고, 여러 발견 사항이 있는 이벤트를 마지막 작업
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
  대화 상자입니다. 열리면 닫기 컨트롤로 포커스가 이동하고 탭 포커스는 패널
  안에 머뭅니다. Escape로 닫으면 패널을 연 행 또는 타일로 포커스가 돌아갑니다.

실시간 헤더는 스트림에서 확인할 수 있는 사실만 보고합니다. 연결 상태, 마지막
관찰 이벤트 경과 시간, 구성된 환경 상태, 화면 고정 또는 실시간 추적 상태입니다.
Canary 상태, 비상 정지 상태, 스트림 누락 수, 측정된 가드 지표는 서버가 소유한
읽기 모델 필드가 필요합니다. 이 계약이 생기기 전까지 브라우저는 해당 값을
사용할 수 없음으로 표시해야 합니다. CFR, false-positive 비율, 롤백 비율,
policy-violation escape는 측정 기간, 기준선, 표본 수와 함께 통제 보증 화면에
표시합니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| ViewSnapshot 계약 및 결정론적 화면 답변 | implemented | `console/src/deck/context.tsx`; `console/src/deck/answerer.ts`; `console/src/deck/answerer.test.ts`; `console/src/routes/view-contract.test.ts` | Focused Console 테스트는 범위가 제한된 fact와 record, 경로 계약, 지원하지 않는 필드 및 결정론적 fallback을 다룹니다. |
| 답변 계획 및 qualification | implemented | `services/core-control-plane/src/fdai/core/conversation/answer_plan.py`; `answer_planning.py`; `answer_planning_qualification.py`; focused conversation 테스트 | 범위가 제한된 계획, shadow 레코드, 변경할 수 없는 qualification batch 및 readiness-only 증적이 activation 권한 없이 존재합니다. |
| Shadow contributor 수집 | in-progress | Answer-planning source 및 최종 메타데이터 경로 | Phase C shadow 레코드는 있습니다. 문서에 적힌 Phase D 선택적 activation과 Phase E conflict 처리는 승격되지 않았습니다. |
| Live 관찰 presentation | implemented | Console Live 모델, 경로 및 focused 테스트; [Live 관찰 계약](#1343-live-관찰-계약) | Queue 및 Flow presentation, source와 mode 처리, 재생 중복 제거, freeze, 보존 및 상세 이동 동작이 브라우저에 구현됐습니다. |
| 관리되는 화면 간 런타임 증적 | in-progress | Console live E2E harness 및 경로 테스트 | Focused 테스트는 계약을 입증하지만 이 owner 문서는 snapshot hydration, 관찰 작업, 최종 검증 및 navigation을 묶는 현재 인증 증적을 보존하지 않습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-14 | in-progress | 구현 ledger를 도입했으며 이전 출처 이력은 재구성하지 않았습니다. | `current change`; 구현 범위 표에 나열된 ViewSnapshot, planning, Live 및 focused 테스트 근거입니다. | 승격 전에 관리되는 화면 간 및 shadow qualification 근거를 보존해야 합니다. |

### 남은 작업

- [ ] 표시된 snapshot 다이제스트, 서버 근거, branch 수명 주기, 최종 검증, stale 전이 및 경로 이동을 묶는 인증된 화면 간 증적 하나를 보존합니다.
- [ ] 고정된 bilingual answer-planning qualification 집합을 실행하고 선택적 activation 검토 전에 지원하지 않는 단정 및 권한 escape가 0건인 변경할 수 없는 증적을 보존합니다.
- [ ] 상충하는 contributor가 두 근거 집합을 보존하고 기본 검증 답변을 바꾸거나 권한을 부여할 수 없음을 입증하는 Phase E conflict 사례를 추가하고 보존합니다.
- [ ] 표준 full stack에서 Live 재연결, 재생, freeze, stuck-budget, source 혼합, 최종 교체 및 keyboard-contained 상세 이동 근거를 보존합니다.
