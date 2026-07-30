---
title: 오퍼레이터 콘솔 공개 웹 근거
translation_of: operator-console-web-evidence.md
translation_source_sha: 42206ada02c1122137d6c1b13e70cb91b424ed3d
translation_revised: 2026-07-30
---

# 오퍼레이터 콘솔 공개 웹 근거

이 Tier B companion 문서는 오퍼레이터 콘솔의 공개 웹 검색 routing, retrieval, 대안 탐색,
안전 경계 및 회귀 coverage를 소유합니다.

## 공개 웹 근거

공개 웹 근거는 배포 수준의 read-only capability입니다. 배포에서
`FDAI_WEB_SEARCH_ENABLED`를 활성화하고 승인된 domain allowlist를 구성하기 전에는 사용할 수
없습니다.

- **대상 판별:** `search`, `find`, `look up`, `검색해줘`, `찾아봐`, `구글링해줘` 같은 명시적인
  operator 요청은 특정 subject noun 없이도 공개 웹 검색을 선택합니다. 이 high-confidence pattern은
  T0 fast path입니다. T0가 대상 open, list, comparison, proposal 또는 status 질문에 `none`을 반환하면
  검색 가능한 model이 `web` / `local` / `none`, confidence, reason code 및 normalized query를 strict
  JSON으로 반환합니다. Low-confidence, malformed 또는 unavailable classification은 `none`을 유지합니다.
  Current-screen, audit, inventory, catalog 및 sensitive-data 경계는 semantic fallback 전에 적용됩니다.
  `AKS에`처럼 ASCII resource token 뒤에 한국어 조사가 붙은 경우와 `중지된 db` 같은 database status
  filter를 포함한 deterministic local inventory intent는 operator가 web search를 명시적으로 요청하지
  않는 한 semantic public-web plan보다 우선합니다. Coordinator는 local tool branch만 실행합니다. Scope-only next turn은 최신 user inventory question만 재사용하고 server provider scope만 변경하며 typed facet과 projection을 유지하고 client tool evidence는 무시하며 최신 turn이 inventory가 아니면 unresolved 상태를 유지합니다. Cluster inventory만 연결된 상태의 AKS 앱
  배포 질문은 partial로 유지하고 관찰된 cluster resource와 Kubernetes workload evidence 누락을 함께
  표시합니다.
  Deterministic evidence fast path는 contributor prose를 사용하지 않으므로 shadow answer-planning
  round를 시작하지 않습니다. 따라서 verification과 terminal delivery는 관련 없는 agent bridge를
  기다리지 않습니다.
  현재 화면에 명시적으로 빈 projection을 포함한 turn의 facts 또는 records projection이 있으면
  Bragi는 data question을 해당 화면 범위에 결정론적으로 유지합니다. 이 scope는 behavior, tool,
  incident, agent, concept 및 web resolver보다 먼저 선택합니다. Specialist delegation, semantic web
  classification 및 shadow contributor planning은 생략합니다. 요청한 field가 없으면 일반 model
  knowledge로 채우지 않고 부재를 알립니다.
  `bragi-screen-t0` renderer는 지원하는 fact, record, latest audit, action summary 및 promotion row
  질문을 narrator model 호출 없이 답합니다. JSON과 SSE는 동일한 renderer와 verifier를 사용합니다.
  Incidents route에서 prompt가 단일 selected incident를 title, correlation id 또는 "이 인시던트" 같은
  표현으로 참조하면 fuzzy recent window 대신 direct correlation-filtered read를 사용합니다. Lifecycle
  incident id가 없는 projection은 `INC-<correlation>` lookup hint를 파생하지만 server result만
  evidence로 사용합니다. Coordinator는 해당 turn에서 관련 없는 inventory, agent 또는 public-web
  branch를 시작하지 않습니다. `query_inventory` 같은 명시적 canonical tool command는 tool authority를
  유지합니다.
  Agent를 지정한 turn과 server-owned agent evidence가 있는 turn은 speculative semantic public-web
  fallback을 건너뜁니다. 명시적 또는 planned web-search request는 selected agent의 response ownership을
  바꾸지 않고 agent branch와 함께 bounded public-web branch를 추가할 수 있습니다.
  Semantic classification을 실행하면 progress에 선택된 classifier deployment를 route source로
  표시합니다. 완료된 reply는 generation model, response owner, contributor, 명시적인 agent-to-Bragi
  handoff, verification result 및 기록된 모든 evidence reference를 유지합니다. Unverified evidence도
  숨기지 않고 attention state로 확인할 수 있습니다.
  Incomplete로 표시된 evidence manifest도 attention 상태를 사용하고 retained source와 declared
  manifest source 수를 함께 보여주며, 접힌 source summary에 일부 근거임을 표시합니다.
  Browser는 고정 Pantheon 이름만 delegation attribution으로 허용합니다. Replay 전에 primary,
  contributor 및 handoff identity는 64자, contributor는 8개, trace reference는 256자, handoff reason은
  128자로 제한합니다.
  Cross-process failure는 잘못된 attribution 없이 attention 상태 handoff로 표시합니다. 초기 timeout
  이후 bounded background probe가 core bridge의 준비를 감지하면 자동으로 복구합니다.
- **검색:** 대상 turn은 검색 가능한 Azure Responses model candidate로 route됩니다. Provider는
  multilingual public-search 요청을 bounded English query로 변환합니다. Search provider는 해당 query와
  domain allowlist만 받고 정제된 evidence snapshot을 반환합니다. Bragi는 source URL과 함께 답변하며
  검색을 사용할 수 없을 때 대체 내용을 만들어 내지 않습니다. Bragi answer-generation system prompt는
  search-intent authority가 아닙니다.
- **대안 탐색:** Classifier가 comparison subject와 2-8개 capability를 식별하고 coordinator는 subject
  이름을 제외한 capability-based query를 결정론적으로 다시 구성합니다. Alternative search는 medium
  context를 사용하고 서로 다른 direct product를 최소 3개 요청하여 결정론적 filtering 후 2개를
  유지할 여유를 확보합니다. 결과에서 self reference,
  generic vendor homepage, conceptual framework 또는 strategy guide, editorial 또는 blog page, generic
  documentation index, 동일 product identity의 중복 page를 제외합니다. 서로 다른 product source가
  2개 미만이면 search를 unavailable로 처리합니다. Bragi는
  citation으로 확인된 capability overlap만 비교하고 unsupported criterion은 unknown으로 표시하며,
  functional equivalence 또는 winner를 주장하지 않고 partial comparison임을 밝힙니다.
- **안전 경계:** 민감한 identifier가 있으면 provider 호출 전에 검색을 차단합니다. Web snippet은
  계속 untrusted data로 취급되며 execution eligibility를 부여하거나 action의 rule-catalog evidence
  요구를 충족할 수 없습니다.
- **회귀 rubric:** 고정된 영어 및 한국어 10개 corpus가 명시적, 구어체, 최신성, 웹 context, local
  scope 및 no-search intent를 확인합니다. 각 case는 structured route와 provider-call behavior가 모두
  예상 결과와 일치할 때만 통과합니다. 별도의 live held-out check는 T0 pattern set에 없는 영어,
  스페인어, 프랑스어 및 일본어 prompt로 semantic classification과 query normalization을 측정합니다.
  Alternative discovery는 goal, subject, capability, candidate count와 diversity, self exclusion, direct
  page 및 conceptual-content exclusion에 대한 관측 가능한 relevance check 10개를 추가합니다.
