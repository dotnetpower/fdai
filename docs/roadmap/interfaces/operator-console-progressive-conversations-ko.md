---
title: Operator Console Progressive Conversations
translation_of: operator-console-progressive-conversations.md
translation_source_sha: 2b01148f9c732f62a5781a572da6e2eef9078996
translation_revised: 2026-08-05
---
# Operator Console Progressive Conversations

이 문서는 progressive Operator Console conversation의 channel-neutral branch lifecycle, ordered
reduction, verified revision 및 bounded progress contract를 소유합니다.

## Branch contract

Deterministic scope 및 authority routing 이후 coordinator는 조건을 충족한 독립 read branch를 동시에
시작할 수 있습니다. Branch는 immutable evidence operation이며 nested narrator session이나 direct agent
call이 아닙니다. Presentation translator가 conversational identity를 유지합니다. 책임 tool 또는 agent가
branch evidence를 소유하고 deterministic verification이 confirmed answer segment를 소유합니다.

| Field | Contract |
|-------|----------|
| `branch_id` | Request 안에서 stable하며 request id와 canonical branch kind에서 파생됩니다. |
| `branch_kind` | `tool`, `operational`, `agent`, `public_web`과 같은 allowlisted read source 하나입니다. |
| `parent_branch_id` | Optional dependency reference이며 independent top-level branch는 `null`을 사용합니다. |
| `status` | Monotonic `pending`, `running` 이후 `completed`, `unavailable`, `failed`, `timed_out`, `cancelled` 중 하나입니다. |
| `summary` | Bounded redacted progress 또는 terminal summary이며 evidence authority가 아닙니다. |
| `started_at`, `completed_at`, `duration_ms` | Optional observed timing이며 completion은 start보다 앞설 수 없습니다. |
| `evidence_refs` | Terminal branch state에서만 emit되는 bounded canonical reference입니다. |

Server는 request `seq` 순서로 branch lifecycle frame을 emit합니다. Completion 순서는 달라질 수 있지만
join은 immutable result를 canonical branch-kind 순서로 merge합니다. 거부된 untrusted input은 traceback
없이 `unavailable`이 됩니다. Unexpected exception은 warning evidence와 함께 `failed`로 유지됩니다.
성공한 sibling은 계속 사용할 수 있습니다. Authoritative conflict는 양쪽 evidence set을 보존하고 answer를
unverified로 표시합니다. Concurrent branch는 shared context를 쓰지 않습니다.

First wave는 조건을 충족한 tool, operational, explicitly selected agent, read-investigation agent 및
deterministic public-web read에 bounded task group 하나를 사용합니다. 이전 authority result에 따라
eligibility가 달라지는 작업은 bounded follow-up wave에서 실행됩니다. JSON과 SSE는 같은 merge helper를
사용합니다.

## Confirmed revision

Draft `token` frame은 provisional narration으로 유지됩니다. `confirmed` frame은 deterministic verifier를
통과한 evidence에서 렌더링한 complete segment만 포함합니다. Monotonic segment index, answer revision,
evidence reference 및 이후 verified correction을 위한 replacement range를 포함합니다. Confirmed segment는
running branch를 인용하지 않습니다. Terminal `done` frame은 canonical이며 conversation history에 저장되는
유일한 answer입니다. 중단된 stream은 partial로 유지되고 draft text는 confirmed content가 되지 않습니다.

Web reducer는 rendering 전에 branch kind, monotonic status, timing, evidence-reference 및 text bound를
검증합니다. 각 branch를 numbered investigation stage와 expandable bounded evidence로 렌더링합니다.
Observed command와 output detail은 기본적으로 접혀 있습니다. Queued token paint와 correction revision이
모두 drain된 후에만 confirmed content를 적용합니다.

Token 및 confirmed frame은 current canonical revision과 일치해야 합니다. Superseded 또는 unannounced
revision의 frame은 sequence position만 소비하고 text append, canonical content 교체, confirmation
callback 호출 또는 confirmation metric 증가를 수행할 수 없습니다. Confirmed revision은 strictly
advance합니다. `seq` 누락은 이후 `done`이 도착해도 turn을 partial로 만듭니다.

## Channel reduction

Web, Teams 및 Slack은 같은 ordered event reduction을 사용합니다.

- **Web**은 in-progress answer 옆에 compact branch summary를 유지합니다. 상세 및 canonical redacted
  command/output evidence는 펼칠 때까지 접혀 있습니다.
- **Teams 및 Slack**은 originating thread에 response 하나를 게시하고 monotonic edit를 적용합니다. Final
  edit에는 canonical verified answer와 bounded folded branch summary가 포함됩니다.
- **Capability fallback**은 vendor가 edit을 지원하지 않을 때 complete terminal response 하나를
  전송합니다. Precomputed chunk를 streaming이라고 설명하지 않으며 answer authority를 변경하지 않습니다.

## Cancellation, bound 및 replay

Stream close, operator interruption 또는 request deadline은 모든 child branch를 cancel하고 await합니다.
Optional progress observer가 실패해도 cancellation이 authoritative이며 observer error는 branch를 failed로
바꾸지 않고 log됩니다.

Per-branch deadline, queue capacity, branch count, event size, activity count, text byte 및 vendor payload는
bounded 상태를 유지합니다. Command/output evidence에는 `redacted=true`가 필요합니다. Summary는
credential, tenant identifier, customer resource identifier 또는 raw untrusted web content를 노출하지
않습니다. Durable replay는 completed read를 다시 실행하거나 provider message를 중복하지 않고 canonical
terminal answer와 revision state를 저장합니다.

## Metric

Progress metric은 aggregate count와 latency만 유지합니다. Time to first progress/confirmed content,
branch kind, outcome, duration, correction, truncation, terminal completion, replay, queue saturation,
sequence gap, suppressed retry 및 ambiguous channel update를 기록합니다. Prompt, answer, branch id, channel
id, principal id 또는 resource identifier는 보관하지 않습니다.

Failed 및 timed-out read는 turn 안에서 retry하지 않습니다. Metric은 bounded stream queue가 event를
accept한 후에만 기록합니다. Cancellation-only lifecycle frame은 first evidence progress가 아닙니다.
Idempotent terminal replay는 evidence retrieval, narration 및 post-turn review를 건너뛰면서 observed
time-to-first-confirmed latency와 replay count를 기록합니다. Server는 누락된 client frame을 관찰할 수
없으므로 browser가 sequence gap과 partial terminal을 계산합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| Evidence authority, replay 및 stream recovery | [Console evidence and resilience](console-evidence-and-resilience-ko.md) |
| Cross-screen evidence authority | [Operator Console view snapshot](operator-console-view-snapshot-ko.md) |
| Conversation module ownership | [Operator Console module map](operator-console-module-map-ko.md) |
