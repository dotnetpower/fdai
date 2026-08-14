---
title: Operator Console - Incident Roster and Fix History
translation_of: operator-console-incident-roster.md
translation_source_sha: 7a9eed018d28039990b2296261d4f21e0b346a34
translation_revised: 2026-08-14
---

# Operator Console - 인시던트 명단 and Fix 이력

> [operator-console-ko.md](operator-console-ko.md) 섹션 13.5에서 분리한 focused 소유자 문서입니다.

### 13.5 인시던트 목록 및 교정 이력

읽기 전용 SPA는 일급 **실시간 > 인시던트** 패널을 제공합니다. 이 패널은
인시던트 대응을 위한 목록 중심 진입점입니다. 운영자는 상관관계 id를 미리
알지 못해도 활성 또는 해결된 인시던트를 찾고, 하나를 선택하여 교정 이력을
확인할 수 있습니다. 기존 감사 및 추적 패널은 각각 레코드 수준과 엔드투엔드
상세 분석 표면으로 유지됩니다.

API 계약은 다음과 같습니다.

| 경로 | 목적 |
|-------|------|
| `GET /incidents?status=active|resolved|all&limit=<n>&cursor=<opaque>` | 최근 활동 순으로 인시던트 요약을 반환합니다. |
| `GET /audit?correlation_id=<id>&limit=<n>&cursor=<opaque>` | 선택한 인시던트의 추가 전용 이력을 반환합니다. |
| `GET /audit/{correlation_id}/trace` | 순서가 지정된 연관 감사 활동과 기록된 파이프라인 단계를 재구성합니다. |
| `POST /chat/stream` | 레코드를 생성하지 않고 자연어에서 타입이 지정된 인시던트 초안을 만듭니다. |
| `POST /chat/action/confirm` | 타입이 지정된 초안을 확인하고 감사되는 인시던트를 생성합니다. |

인시던트 명단은 읽기 전용으로 유지됩니다. 인시던트 생성은 의미 초안 및
타입이 지정된 확인 경로를 사용하며 패널에 변경 버튼을 추가하지 않습니다. 인식된
incident-open 요청은 다음 순서로 처리됩니다.

1. 기여자 기능, 심각도, 대상 상관관계 키를 요구합니다.
2. 사람이 읽을 수 있는 요약과 10분 만료를 포함한
  `incident_confirmation_required`를 반환합니다. 이 시점에는 인시던트가 없습니다.
3. 같은 principal과 `session_id`에서 `confirm` 또는 `확인` 메시지를 보내면 audited
  인시던트를 생성하고 id와 초기 `open` 상태를 반환합니다.

Pending 제안의 `session_id`는 200자로 제한됩니다. Oversized 세션 또는
멱등성 키는 truncate하지 않고 거부하므로 서로 다른 식별자가 같은 확인으로
합쳐지지 않습니다. 운영은 제안을 Postgres에 저장하고 atomic하게 consume하므로
확인이 다른 복제본에 도착해도 처리할 수 있습니다. 저장된 기록에는 출처
프롬프트 원문이 아니라 SHA-256만 포함됩니다.

누락된 값은 `incident_details_required`, 취소는
`incident_creation_cancelled`를 반환합니다. 관련 없는 액션 명령은 기존
Bragi-to-Huginn 타입이 지정된 제안 경로를 계속 사용합니다. 허용 목록에 포함된 에이전트는
member-event 근거와 사유를 제공해 같은 built-in 작업 흐름을 사용하지만,
운영자를 impersonate하거나 인시던트 레지스트리를 우회하지 않습니다.

동일한 인증된 경로는 exact 수명 주기 명령 grammar만 받으며 free-form 상태
산문을 추측하지 않습니다.

- `transition incident <uuid> to <state>` 또는
  `incident <uuid> 상태 <state>으로 변경`
- `assign incident <uuid> to <oid>` 또는
  `incident <uuid> 담당자 <oid> 지정`

둘 다 nonblank 대화 `session_id`, 기여자 기능, 레지스트리의 저장된
expected-state 검사가 필요합니다. Illegal 간선, 알 수 없음 id, cross-replica 충돌은
정본 인시던트를 변경하지 않고 `incident_lifecycle_rejected`를 반환합니다.

`correlation_id`는 근거를 연결하는 조사 키이며 그 자체로 인시던트 수명 주기
기록이 존재한다는 증거가 아닙니다. 변환 결과는 최상위 상관관계가 없는
행의 `event_id`가 이미 알려진 상관관계와 같거나 명시적인 인시던트 수명 주기
링크가 정확히 하나의 상관관계로 확인될 때만 해당 행을 연결할 수 있습니다.
모호한 행은 연결하지 않으며 읽기 모델은 리소스 이름으로 연관 관계를 만들지
않습니다. Pending HIL 항목은 서버가 소유한 보류 기록에서 룰 심각도와 category를
복원할 수 있지만 추가 전용 감사 행은 다시 쓰지 않습니다. 수명 주기 상태가
있으면 이를 권위 있는하게 사용합니다. 그렇지 않으면 감사 단계에서 `open`,
`in_progress`, `resolved`를 도출합니다. 교정이 거부, abstain 또는 실패했다는
사실만으로 기반 인시던트가 해결되었다고 표시하지 않습니다.
로컬 Operator API 감사 고정본은 명시적인 샘플 출처 이력을 가지며 감사, 추적,
에이전트 활동에서 계속 볼 수 있습니다. Operational 인시던트 명단에서는 제외되므로
정상 또는 within-threshold 모니터링 샘플이 열린 인시던트처럼 보이지 않습니다.

각 인시던트 요약은 기록된 `producer_principal`, 정본 액션 소유자, 단계
소유권에서 서버 측으로 도출한 `involved_agents`를 포함합니다. 에이전트 표면은
이 영속 인시던트 스냅샷을 먼저 hydrate한 다음 더 새로운 `/agents/stream` 단계
delta를 적용합니다. 따라서 새 탭도 Incidents와 일치하면서 실제 운영 단계 전이를
유지합니다.

요약 제목도 서버가 소유합니다. 변환 결과는 먼저 명시적으로 기록된 `title`,
`summary` 또는 룰 ID를 사용합니다. 이 필드가 없으면 기록된 `signal:` 및
`resource:` 상관관계 키에서 길이가 제한된 대상을 만듭니다. Azure 리소스 ID는
리소스 타입과 마지막 리소스 이름만 제공하므로 전체 경로를 노출하지 않고도 목록에
`Resource inventory change - Storage account storage-example` 같은 대상을 표시할 수
있습니다. 기록된 대상 근거가 전혀 없는 인시던트만 이벤트 ID로 대체되며 브라우저는
대체 제목을 만들어내지 않습니다.

#### Azure SRE Agent 선택적 차용

FDAI는 Azure SRE Agent 문서에 나타난 운영자 중심 강점을 차용하되 실행 모델은 차용하지 않습니다.

| 확인한 방식 | FDAI 차용 방식 | 유지하는 경계 |
|-------------|----------------|---------------|
| [풍부한 Incident 카드](https://learn.microsoft.com/azure/sre-agent/incident-platforms#rich-incident-cards) | 운영자가 읽을 수 있는 제목, 설명, 원본 플랫폼과 ID, 심각도, 원본 상태와 시각, 대응 계획 참조, 서버 소유 신뢰 marker가 있는 원본 상세 링크를 표시합니다. `title_source`를 추가하고 식별자 fallback을 대상 제목처럼 표시하는 대신 `제목 사용 불가`로 표시합니다. | 정본 수명 주기 상태를 원본 플랫폼 상태와 분리하고 모든 표시 필드를 기록된 근거로 유지합니다. |
| [조사 thread 및 세션 insight](https://learn.microsoft.com/azure/sre-agent/review-agent-insights) | 근거 참조, 명시적 공백, 평가, 비활성 학습 후보와 함께 범위가 제한된 `initial`, `progress`, `issue`, `success`, `resolved` milestone을 투영합니다. | 대화 transcript는 근거가 아닙니다. 자체 평가가 아니라 독립적 효과 검증이 복구를 종결하거나 학습을 승격합니다. |
| [대응 계획](https://learn.microsoft.com/azure/sre-agent/response-plan) | 활성화 전에 과거 일치 항목을 미리 보고, 계획 개정을 고정하고, 활성 상태를 노출하며, 명시적 cooldown 및 중복 제거 키에 따라 반복 경보를 병합합니다. | 계획은 조사만 라우팅합니다. 형식화된 `ActionType`, 위험, 승인, 실행자, 롤백, 감사 게이트가 모든 상태 변경을 계속 결정합니다. |
| [Incident 가치 추적](https://learn.microsoft.com/azure/sre-agent/track-incident-value) | 정확한 구간, 분모, Incident drill-down과 함께 에이전트 완화, 에이전트 지원, 사람 완화, 대기, 완화 시간 cohort를 측정합니다. | 권위 있는 종결 상태와 독립적으로 검증된 결과 근거가 없으면 집계 결과도 성공을 주장하지 않습니다. |

> FDAI는 Azure SRE Agent 실행 모드의 임의 Azure CLI 쓰기, 기본 자율 대응 계획 또는 permission-as-authority 동작을 차용하지 않습니다. 7가지 보호 장치와 분리된 판단자, 승인자, 실행자, 관찰자, 감사자 역할이 계속 권위 있습니다.

누락된 상관관계는 누락 상태로 유지합니다. 변환 결과는 빈 값과 과거의 `None` 또는
`null` 문자열 sentinel을 결측으로 처리하므로 관련 없는 audit-only 행이 synthetic 인시던트를
구성하지 않습니다.

목록은 요약만 반환하며 모든 감사 행을 포함하지 않습니다. 커서가 각 서버
페이지의 범위를 제한합니다. 항목을 선택하면 별도의 필터링된 GET으로 이력을
가져옵니다. 모든 경로는 읽기 담당 게이트를 적용하고 변경 동사에 `405`를
반환합니다. 패널은 감사 및 추적 링크를 제공하지만 execute, approve, 롤백
버튼은 제공하지 않습니다. 이러한 작업은 교정 PR 및 ChatOps에 유지됩니다.

인시던트 생성, 각 합법적 상태 변경, 요청된 명단 요약은 A2 운영 알림 대상입니다.
재전송된 열림과 같은 상태 전이는 두 번 알리지 않습니다. 수명 주기 메시지는
인시던트 id, 심각도, 정규화된 상태를 포함하지만 자유 형식 사유 텍스트와 리소스
상관관계 키는 제외합니다. 명단 알림은 20개 id로 제한되고 전체
`/incidents` 화면으로 연결됩니다. Event별 `audit_id`는 채널 멱등성이 이후
전이를 누락시키지 않도록 합니다. 영속 sent 체크포인트와 시작 재생은
비정상 종료로 놓친 알림을 재시도합니다. 전달 전에 복제본은 범위가 제한된 임차 기간이 있는 atomic
점유 토큰을 경쟁하며 하나만 전송합니다. 해당 토큰만 notice를 sent로 표시하거나
실패 후 release할 수 있습니다. 해결되지 않은 채널은 HIL 에스컬레이션 싱크로 대체 경로합니다.

인시던트 경보 구독은 [channels-and-notifications-ko.md](channels-and-notifications-ko.md)의
channel-as-audience 계약을 따릅니다. 설정된 A2 operations 채널 구성원이
열림, 전이, 명단, SLA-breach notice를 지속적으로 받는 대상을 결정합니다.
Console은 per-user direct-message 구독을 만들지 않습니다. 배정과 외부
티켓 연결은 인증된 write-direction 채팅/도구 연산으로 유지되고 감사
이력에 표시됩니다. 읽기 전용 명단은 연결된 `ticket_id`를 표시합니다.

목록은 선택적 정본 `vertical` 필터를 허용하며 감사 경로는 `mode`,
`tier`, `action`, `outcome`, `vertical`, 범위가 제한된 `window=<n>d` 필터를 커서
페이지 나누기 전에 서버에서 적용합니다. 따라서 분석 deep 링크는 브라우저 첫 페이지만
필터하지 않고 전체 filtered 결과 집합을 검색합니다. 커서는 인시던트 상태와
버티컬에 연결되므로 두 필터 중 하나를 바꾸면 stale 커서가 무효화됩니다.

개요 감사 KPI는 in-memory와 Postgres 읽기 모델 모두에서 가장 최근 감사 행
500개를 집계합니다. `GET /kpi`는 이 변경할 수 없는 샘플을 inclusive `from_seq`와
`through_seq` 경계, `row_count`, `limit`를 포함하는 `audit_sample`로 반환합니다.
개요에서 감사로 이동하는 모든 링크는 이 경계를 전달하며 `GET /audit`는
dimension 필터와 커서 페이지 나누기 전에 `from_seq`와 `through_seq`를 적용합니다.
따라서 더 최신 행이 추가된 후에도 운영자는 표시된 개수 또는 ratio를 만든 동일한
추가 전용 샘플을 열거할 수 있습니다. `hil_pending`은 별도의 현재 큐 변환 결과로
유지되며 감사 샘플에 포함되지 않습니다. Tier 키와 계층 필터는 lowercase 정본
값 (`t0`, `t1`, `t2`)를 사용합니다.

SPA는 인시던트 목록을 선택 버튼의 의미 목록으로 렌더링합니다. 선택된 버튼은
`aria-pressed`를 노출하며 모든 버튼은 `aria-controls`로 인시던트 상세 지역을
가리킵니다. 알 수 없는 top-level URL은
정본 `/overview`로 replace되므로 같은 화면이 typo 경로 아래 여러 대화
캐시를 만들지 않습니다.

명시된 child-view 및 개체 식별자는 실패 시 차단으로 처리합니다. URL이 알 수 없는
작업 흐름, ObjectType, LinkType, ActionType, 에이전트, 감사 항목, 아키텍처 화면 또는
리소스, 인시던트 상관관계, 승격 사유, IAM 탭, 실제 운영 이벤트를 지정하면 콘솔은
요청 값을 보존하고 유효한 복구 링크가 있는 사용 불가 또는 waiting 상태를 렌더링합니다.
첫 행, 기본값 작업 흐름, 기본값 화면 또는 다른 개체의 근거로 대체하지 않습니다.
명시적 식별자가 없는 URL에서만 문서화된 기본값을 선택할 수 있습니다.
ActionType 디렉터리 필터는 정본 URL 상태 (`q`, `category`, `trigger`,
`execution`)이며 운영자가 액션을 선택해도 유지됩니다. 따라서 새로 고침, 뒤로 가기,
공유 링크가 같은 목록을 재현합니다.
Blast-radius 조회 초안은 시뮬레이션을 실행하지 않고 `target`, `depth`, `links`를 URL에
기록합니다. `links=none`은 운영자가 유효한 탐색 집합을 선택할 때까지 명시적으로
비어 있는 선택을 보존합니다.
Opaque 개체 식별자는 정본 URL 교체와 중첩 drilldown에서도 byte-for-byte로
유지됩니다. 특히 프로세스 ID는 인코딩만 하고 lowercase 또는 slug 변환하지 않으며,
작업 흐름 단계 링크는 카탈로그 소유권 그룹을 보존합니다. 수동 RCA와 추적 조회는 제출한
상관관계 ID를 먼저 정본 URL에 기록합니다. 입력을 수정하면 이전 응답을 무효화해
다른 식별자 아래 잘못된 근거가 나타나지 않게 합니다.

Write-direction 양식은 변경되지 않은 하나의 운영자 의도에 하나의 멱등성 키를
유지합니다. 따라서 전송 계층 실패 또는 응답 유실 후 재시도는 같은 키를 사용하고,
대상, 매개변수, justification을 바꾸면 키를 교체하며 확인된 성공 후에는 폐기합니다.
Daily briefing 구독 생성은 이 키에서 principal 범위로 한정된 고정된 구독 신원을
파생하고 동일한 재시도에는 기존 기록을 반환합니다. 접근 요청, IAM 역할 요청,
통제된 Python 실행도 같은 규칙을 사용합니다. 문서 배치 업로드는 완료할 때까지 수집,
용도, 저장소 모드, consent, 선택된 파일을 잠그고 경로 unmount 후 새 요청을 발행하지 않습니다.

정본 출처 변경과 derivative 온톨로지 변환 결과는 서로 다른 성공 경계를 가집니다.
Committed 작업 흐름 정의 또는 연결은 즉시 온톨로지 변환 결과가 실패해도 source-store
결과를 반환합니다. PostgreSQL 출처 트랜잭션은 해당 변환 결과 복구 기록을 큐에 추가하므로,
재시도가 committed 생성을 충돌로, committed 삭제를 not found로 잘못 보고하지 않습니다.

에이전트 런타임 상태에도 관찰된 근거가 필요합니다. 에이전트 상태 프레임 또는 영속 인시던트
변환 결과가 작업을 귀속하기 전에는 에이전트, 에이전트 활동, Pantheon이 `unobserved`로 표시합니다.
고정 runtime-binding 지도는 소비자 상태를 증명하지 않습니다. Headless Pantheon은 실제 상태에서
파생한 `agent.runtime-state` 하트비트를 발행하고, Operator API는 실제 운영이며 오류가 아닌 에이전트만 `idle`
또는 `watching`으로 표시합니다. 예약 상태는 스케줄러 변환 결과 전까지 사용 불가입니다.

Capabilities 경로는 `source=static-catalog`, `execution_eligibility=false`인 inert 카탈로그
변환 결과이며 side-effect 등급, 필수 역할, 기본값 모드를 설명합니다. Skills 경로도 `GET /skills`에서 installed 스킬과 통제된 번들 메타데이터, 구성원 순서, 호환성, 충족 여부, 참조, 범위가 제한된 진단만 변환 결과하고 수명 주기 컨트롤을 노출하지 않습니다.
Bragi는 같은 Reader-gated 공개를 사용합니다. 내용 읽기는 trust와 예산을 다시 확인하며
실행 결정은 조립, RBAC, 검증, risk 게이트에 남습니다.
승인된 출처 근거는 `/api/v1/skill-sources` 아래 GET 경로로 제공하지만 현재 SPA Skills
경로는 `/skills`만 읽고 해당 경로를 아직 사용하지 않습니다. 향후 읽기 전용 출처 화면은 browse,
검색, 격리 구역 inspect, 비활성화된 갱신 후보 확인만 수행할 수 있습니다. 후보 승인과
출처 철회는 Approver 및 Owner 자동화를 위한 별도 인증된 게시 경로입니다.
Skills 패널은 수명 주기 컨트롤을 제공하지 않습니다.
[skill-source-management-ko.md](skill-source-management-ko.md)를 참조하세요.

Operational 읽기 표면은 static 점유 대신 페이로드의 출처 이력을 렌더링합니다.
스케줄러 Runs는 원장 `source`와 `durable` 플래그를, LLM 비용은
`latest_occurred_at`을, Settings Models는 생성된 스냅샷 파일 이름과 `as_of`를
표시합니다. 누락된 필드는 사용 불가로 렌더링하거나 계약 decode를 실패시킵니다.
브라우저는 경로 이름, 환경 모드, 구성된 기본값에서 내구성, 최신성,
프로바이더 상태를 추론하지 않습니다.

정확한 개체 조회는 페이지 한도 전에 서버에서 필터링합니다. 따라서 인시던트 상관관계 링크,
감사 항목 링크, Approval 검색은 첫 명단 페이지 밖에서도 false absence 없이 해석됩니다.
Count-only 역할에는 Approval 검색을 적용하지 않아 filtered 합계로 숨겨진 큐 내용을
추론할 수 없게 합니다. Exact Incident 결과는 analytical snapshot이 현재 roster snapshot과
일치할 때만 visible roster에 합칩니다. Concurrent snapshot 변경은 서로 다른 근거 revision을
섞지 않고 사용 불가 상태로 유지합니다. 독립 출처는 격리합니다. 선택적 principal 작업 흐름 변환 결과가
built-in 작업 흐름 카탈로그를 숨기지 않으며, 사용하지 않는 analytics 출처가 다른 허브를 오류
화면으로 교체하지 않습니다. 보고 렌더링과 PDF 실패는 선택된 연산에만 남고 카탈로그나
variable editor를 제거하지 않으며, 경로 변경 후 도착한 download는 폐기합니다.

진단은 프로세스 생존과 인증된 KPI 읽기 경로를 구분합니다. `/healthz` 성공만으로
운영 데이터가 healthy하다고 주장하지 않습니다. 마찬가지로 last-observed 에이전트 프레임은 이력으로
유지하지만 Engaged, Watching, Idle은 에이전트 스트림이 열림일 때만 현재 개수입니다. 인증된 실제 운영 및
에이전트 스트림이 열림일 때만 현재 개수입니다. 캔버스 visualization은 동등한 keyboard 및 screen-reader
리소스 선택자를 제공하고 composite 탭 위젯은 roving 선택과 함께 DOM focus를 이동합니다.


Time-bound 및 집계 근거는 경로가 열린 동안에도 보수적으로 유지됩니다. Approval과
Operator Memory 행은 reload 없이 기록된 TTL 경계를 넘으면 상태가 전환됩니다.
아키텍처는 서버의 스냅샷 최신성 판정을 유지하면서 스냅샷 age를 계속 증가시킵니다.
누락된 계층 측정은 measured zero가 아니라 사용 불가입니다. 범위 충족 여부는
`included` 항목만 집계합니다. Multi-datasource 보고는 모든 출처가 근거 시간을 제공할 때만
집계 시간을 알 수 있고, 그 경우 가장 오래된 출처 시간을 사용합니다. Mixed-currency LLM
비용 그룹은 비가산으로 표시하며 단일 통화 합계로 렌더링하지 않습니다.
범위는 기록된 각 구독 아래에 명시적 모니터링 및 액션 항목을 그룹하며
inherited 권한을 계산하지 않고 각 수준을 아키텍처로 연결합니다.

프로세스 목록도 `source`, nullable `synthetic`, nullable `durable`로 같은 규칙을
따릅니다. 로컬 seeded 런타임은 `synthetic-dev/true/false`, 운영은
`postgres/false/true`를 보고합니다. 프로세스 상태, 저널, dynamic 화면은 서버가 소유한으로
유지되지만 현재 렌더링이 underlying 스냅샷의 생성 또는 저장 방식을 지우지 않습니다.

선택한 인시던트 상세는 요약과 근거 계층을 분리합니다. 교정 타임라인보다 먼저 경보 수명 주기,
에이전트 작업 상태, pending user 입력, 서버가 소유한 인시던트 및 티켓 ID, 처리 결과, 판정,
버티컬, 모드, 시각, 이력 개수를 표시합니다. 간결한 response-routing 섹션은 기록된
심각도, involved 에이전트, 통제된 human-ownership 대응, 자율성 모드 순서로 표시합니다. 누락된
값은 사용 불가로 렌더링하며 브라우저가 영향, 사람, 소유권, 복구를 추론하지 않습니다.
상세는 이력 > Reports의 상관관계 범위 **인시던트 RCA Dossier**로 연결됩니다.

조치 이력은 각 감사 행을 사람이 읽을 수 있는 이벤트로 표시합니다. 먼저 기록된
`summary`, `detail`, `reason` 텍스트를 사용하고, 값이 없으면 알려진 수명 주기, 알림,
사람 승인, 감사 이벤트 종류에 대한 결정론적 템플릿을 사용합니다. 담당 에이전트는 기록된
`producer_principal`, Pantheon 행위자 또는 정본 stage-owner 대응에서 가져옵니다.
에이전트가 아닌 런타임은 에이전트로 귀속하지 않고 담당 서비스로 표시합니다. 각 행은
정확한 머신 `action_kind`를 보조 텍스트로 유지하고 기록된 핵심 사실을 최대 5개까지
표시합니다. Incidents에서는 raw 항목 JSON을 생략하며 상관관계 범위 감사 링크가 전체
레코드 화면으로 유지됩니다.

개요는 자율성 측정이 없거나 malformed여도 모든 필수 분석 섹션을
계속 표시합니다. 섹션을 제거하거나 0으로 추정하지 않고 명시적 사용 불가
상태를 렌더링합니다. 근거가 있으면 성공 표면은 해결 이벤트당 비용,
mixed-model disagreement, 검증기 실패, shadow divergence, 측정 구간,
샘플 크기, 확신도, named 출처를 포함합니다. **이력 > 리포트**는 선언형
reporting 카탈로그와 서버가 소유한 위젯 근거를 렌더링합니다.
Synthetic 측정은 분석 형태를 설명할 수 있지만 operational 상태를 결정하거나,
attention 개수를 늘리거나, failed-guard drilldown을 만들 수 없습니다. 개요와
컨트롤 Assurance는 synthetic 가드를 operational 자세에서 알 수 없음으로 처리하면서
출처, 구간, 샘플 크기, 확신도, 출처 시각을 계속 표시합니다. 이벤트가
0건인 영역은 해결률을 0%로 추정하지 않고 사용 불가로 렌더링합니다. 개요는 필수
감사 KPI와 독립적인 선택적 비용, 승격, 자율성 변환 결과를 동시에 불러오며,
문서화된 사용 불가 상태만 해당 선택적 변환 결과를 degrade합니다. 분석 탭과
비교 링크는 현재 조회를 보존합니다. 실패 가드와 T2 leading indicator는 정본
`guard`, `indicator` 필터를 추가하며 알 수 없는 필터 값은 다른 행을 선택하지 않고
사용 불가로 렌더링합니다.

계약 규칙 (`console/src/routes/view-contract.test.ts` 가 강제):

- **스냅샷을 publish하는 모든 경로는 `purpose` 와 `glossary` 를 반드시
  선언**하며, 공유 카탈로그 `console/src/deck/glossary.ts` 에서 조합해 한
  용어가 모든 화면에서 동일한 의미를 갖게 함. 이를 빠뜨린 채 스냅샷을
  publish하는 경로는 빌드를 실패시킴 - under-described 화면이 조용히
  들어올 수 없음.
- **인과 필드는 `records` 에 유지**. `detail`, `summary`, `reason`, `tier`,
  `outcome` 을 투영에서 버리지 않으므로, "왜 시작됐는가" 는 기록된 감사
  서사(그리고 순서대로의 hand-off 체인)를 인용해 답함.
- 서술기는 **screen-agnostic** 체인(causal -> glossary / value-chip ->
  경로 enhancer -> 범용 기록 검색)으로 질문을 해석; 새 화면은
  코드 추가가 아니라 어휘 선언만으로 설명 가능해짐. 오프라인 결정론
  answerer(`console/src/deck/answerer.ts`)와 서버 서술기(`chat.py`)가
  동일한 `purpose`/`glossary` 에 grounding.
- CLI REPL과 실제 운영 cockpit은 동일한 self-describing 스냅샷을 `POST /chat`을
  통해 서버 서술기에 전달합니다. CLI에는 모델 클라이언트, 의도 라우터,
  cloud 자격 증명 흐름 또는 console-tool 구현이 없습니다.

#### 13.5.1 RCA 뷰 (근본 원인 분석)

읽기 전용 SPA는 일급 **이력 > RCA** 패널을 노출합니다. 인시던트
`correlation_id`(보통 인시던트 목록에서 딥링크, `#/rca?correlation=<id>`)가
주어지면, 컨트롤 루프가 이미 감사 원장에 추가한 티어별 근거 근본 원인
가설과 연결된 대응 계획을 렌더링합니다. 인시던트 목록(13.5)과 짝을 이루는
"왜 발생했고, 계획은 무엇이었나" 표면입니다.

API 계약은 단일 GET 경로입니다:

| 경로 | 목적 |
|-------|------|
| `GET /rca?correlation=<id>` | 단일 상관관계 id에 대한 인시던트별 RCA 뷰를 반환. |

상관관계에 감사 행이 없으면 경로는 `404`를 반환합니다. 알 수 없음 상관관계를
정상 빈 RCA dossier로 바꾸지 않습니다. 그렇게 하면 누락된 근거를 완료된
분석처럼 표시하게 되기 때문입니다.

이 투영은 기존 감사 데이터를 조합하며 새로운 진실 원천을 도입하지 않습니다.
컨트롤 루프는 각 가설을 shadow `rca.hypothesis` 감사 항목으로 기록합니다(참조:
[observability-and-detection.md](../rules-and-detection/observability-and-detection.md)
섹션 4). 패널은 상관관계된 감사 행을 읽어 다음을 투영합니다:

- **근본 원인 가설**, 최신순, 각각 `RcaTier`(`t0` 직접 / `t1` 상관 /
  `t2` 추론), 신뢰도, 원인 텍스트, 이유, shadow-vs-enforce 모드,
  그리고 근거 `citations`(`rule` / `event` / `telemetry` / `incident` /
  `change` / `scenario` / `knowledge`) 포함.
- **근거 상태.** 근거 없는 / 기권한 가설(`outcome == "abstained"`,
  `grounded == false`)은 신뢰할 수 있는 원인이 아니라 "근거 부족 -> HIL"로
  명시적으로 표시됩니다.
- 동일한 상관관계 감사 스트림에서 조합한 **대응 계획**: 판정
  (`auto` / `hil` / `deny` / `abstain`), 전달된 작업 종류, 그 모드,
  롤백 참조.
- **구조화된 T1 인과 체인.** T1 가설은 루트/실패 이벤트 ID, 모호성,
  순서가 있는 홉을 포함하는 `causal_chain`을 전달할 수 있습니다. 각 홉은
  원인/효과 이벤트 및 리소스 참조, 선행 시간(초), 관계, 신뢰도를 보존합니다.
  malformed 또는 누락된 체인 데이터는 브라우저에서 부분 재구성하지 않고
  사용할 수 없음으로 렌더링합니다.

리포트 카탈로그는 `incident-rca-dossier`를 포함합니다. 필수
`correlation_id` 변수가 가설, 인용, causal 홉, 대응, 시간 순서 위젯을 단일
인시던트로 한정합니다. 선택적 PDF delivery는 독립 Operator Service가 소유하고 redacted된 서버 소유
report 묶음만 배치하며 기록되지 않은 섹션을 사용 불가로 유지하고 새 RCA를 수행하지 않습니다.
`pdf-report` extra가 없으면 이 format은 제공되지 않습니다.

RCA 가설은 "왜"를 답할 뿐 "실행"하지 않습니다: 실행 자격은 여전히 리스크
게이트 + 검증기에 있습니다. 경로는 읽기 담당 게이트가 적용되고, 변경 동사에는
`405`를 반환하며, 감사 / 추적로의 링크는 제공하지만 실행 / 승인 / 롤백
버튼은 없습니다. 투영은 순수 함수
(`services/operator-service/src/fdai_operator_service/`)이며
`services/operator-service/tests/`로 커버됩니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| Incident 수명 주기, roster 변환 결과 및 Console 보기 | implemented | `services/core-control-plane/src/fdai/core/incident/`; `services/core-control-plane/tests/core/incident/`; `console/src/routes/incidents.tsx`; focused Console incident 테스트 | Incident 상태, 상관관계, 수명 주기, roster, attention 및 범위가 제한된 presentation에 focused 검사가 있습니다. |
| 운영자가 읽을 수 있는 identity 및 단계별 조사 | implemented | `incident_projection.py`; `projection_logic.py`; `postgres.py`; `incidents.tsx`; `incidents.detail-sections.tsx`; `incidents.milestones.ts`; focused Operator 테스트(`31 passed`), Console 테스트(`66 passed`), typecheck, strict mypy, Ruff, Pylance 및 catalog parity | 제목 출처, 신뢰된 원본 context, 계획 미리 보기, 범위가 제한된 근거 milestone, 독립적으로 검증된 결과 cohort를 실행 권한 없이 구현했습니다. |
| RCA 계약, 변환 결과 및 읽기 전용 경로 | implemented | `services/core-control-plane/src/fdai/core/rca/`; `services/core-control-plane/tests/core/rca/`; `services/operator-service/src/fdai_operator_service/rca_projection.py`; `services/operator-service/tests/test_operator_service_composition.py`; `console/src/routes/rca.test.ts` | 경로는 알 수 없는 상관관계를 구분하고 기록된 가설과 대응 근거를 변환하며 액션 권한을 노출하지 않습니다. |
| RCA 보고 카탈로그 및 데이터 원본 | implemented | `rule-catalog/reports/incident-rca-dossier.yaml`; `services/core-control-plane/src/fdai/core/reporting/datasources/audit_rca.py`; reporting 테스트 | 선언형 dossier와 범위가 제한된 감사 변환 결과가 있습니다. |
| RCA PDF format 및 다운로드 컨트롤 | implemented | `fdai_operator_service/reporting/pdf_format.py`; Operator report 경로; Console Reports 컨트롤; focused PDF 및 경로 테스트 | Opt-in 어댑터는 기존 redacted report 묶음만 렌더링하고 package extra가 없으면 제공되지 않습니다. |
| 관리되는 인증된 런타임 근거 | in-progress | Console incident 및 RCA 보기; Operator 읽기 경로 | Focused 검사는 구현을 입증하지만 이 owner 문서는 현재 관리되는 Browser Entra roster-to-RCA 증적을 보존하지 않습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-14 | in-progress | 구현 ledger를 도입하고 RCA PDF 주장을 대상 상태로 수정했으며 이전 출처 이력은 재구성하지 않았습니다. | `current change`; 구현 범위 표에 나열된 현재 incident, RCA, reporting, Operator 및 Console 근거입니다. | 선택적 PDF delivery를 구현하고 관리되는 roster-to-RCA 런타임 근거를 보존해야 합니다. |
| 2026-08-14 | in-progress | 현재 Microsoft Learn Azure SRE Agent 지침과 비교하여 풍부한 Incident identity, 단계별 조사, 대응 계획 미리 보기, 근거 기반 결과 분석 방식만 수락했습니다. | `current change`; [선택적 차용 계약](#azure-sre-agent-선택적-차용) 및 구현 범위 표의 현재 Operator/Console 경로입니다. | FDAI 실행 권한을 넓히지 않고 범위가 제한된 운영자 중심 공백 네 가지를 구현하고 검증해야 합니다. |
| 2026-08-14 | implemented | FDAI 권한 경계를 유지하면서 서버 소유 제목 출처, 신뢰된 원본 및 고정 계획 context, 범위가 제한된 감사 milestone, 정확한 drill-down이 있는 같은 스냅샷 결과 cohort를 추가했습니다. | `current change`; `incident_projection.py`, `incidents.detail-sections.tsx` 및 작업 소유 Operator, service-contract, Console, catalog, focused 테스트 경로입니다. Operator `31 passed`, Console `66 passed`, typecheck, strict mypy, Ruff, Pylance 및 catalog parity를 통과했으며 비평 15회 후 Low finding만 남았습니다. | 관리되는 런타임 근거를 별도로 보존해야 합니다. |
| 2026-08-14 | implemented | 다른 분석 또는 실행 경로를 만들지 않고 기존 Incident RCA dossier에 선택적 PDF delivery를 추가했습니다. | `current change`; service-local PDF encoder, package extra, GET-only 경로, Console 컨트롤, 페이지 나누기, escape, source 다이제스트, 사용 불가 섹션, 분석 부재 및 no-network 회귀 검사입니다. | 하나의 exact-revision 인증된 roster-to-RCA-to-report 증적을 보존해야 합니다. |

### 남은 작업

- [x] 기록된 제목, 요약, 룰, signal, 정리된 resource 대상을 우선하고 식별자 fallback을 사용 불가로 표시하는 범위가 제한된 `title_source` 계약과 focused projection, decoder, render 테스트를 추가합니다.
- [x] 정본 수명 주기 상태를 대체하지 않고 원본 플랫폼 identity, 설명, 상태, 시각, 원본 링크, 고정된 대응 계획 개정, 과거 일치 미리 보기, cooldown 및 중복 제거 근거를 투영합니다.
- [x] 정확한 근거 참조, 사용 불가 공백, 평가 receipt, 비활성 학습 후보가 있는 순서가 지정된 조사 milestone을 렌더링하고 transcript 텍스트가 근거를 만들거나 복구를 종결하거나 학습을 승격할 수 없음을 입증합니다.
- [x] 정확한 출처, 구간, 분모, 종결 상태 규칙, 독립적 결과 검증, Incident drill-down과 함께 에이전트 완화, 지원, 사람 완화, 대기, 완화 시간 cohort를 게시합니다.
- [ ] Incident, 상관관계, 가설, 인용, 대응 계획, 감사 행 및 사용 불가 동작을 하나의 source 개정에 묶는 인증된 roster-to-RCA 증적 하나를 보존합니다.
- [x] 기존 보고 묶음만 렌더링하고 extra를 사용할 수 없을 때 등록되지 않는 선택적 PDF `FormatEncoder`와 GET-only 다운로드 경로를 구현하고 focused 테스트를 추가합니다.
- [x] 고정 참조 페이지 수를 문서화하지 않고 PDF 페이지 나누기, escape, source 다이제스트, 사용 불가 섹션, 새 분석 부재 및 no-network 회귀 검사를 추가합니다.
