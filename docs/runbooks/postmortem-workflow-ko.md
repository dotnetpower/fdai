---
title: 포스트모템 Workflow Runbook
description: 해결된 incident를 검토하고 evidence-backed follow-up을 제출하는 템플릿입니다.
translation_of: postmortem-workflow.md
translation_source_sha: 92316b0c0ecb205a5adb30be10e5b34995f8ee30
translation_revised: 2026-07-22
---

# 포스트모템 Workflow Runbook

Service recovery를 검증한 뒤 incident를 최종 종료하기 전에 이 runbook을 사용합니다.
Incident timeline, decision, action, recovery evidence를 measurable follow-up이 있는 approved
record로 전환합니다.

> Postmortem은 evidence가 지원하는 내용을 설명합니다. Unsupported cause는 hypothesis로
> 유지하고 timeline을 깔끔하게 만들기 위해 machine record를 다시 작성하지 않습니다.

## 진입 기준과 역할

Service recovery가 observation window를 통과하고 incident owner가 authoritative audit 및
evidence reference를 식별할 수 있을 때 시작합니다.

| 역할 | 책임 |
|------|------|
| Incident owner | Impact, chronology, recovery status, closure decision을 책임집니다. |
| Facilitator | Review를 이끌고 evidence와 interpretation을 구분합니다. |
| Action owner | Due date와 measurable completion evidence가 있는 follow-up을 수락합니다. |
| Reviewer | Record가 supported, complete, 공유 가능한 상태인지 확인합니다. |

Facilitator는 review를 개인에게 책임을 돌리는 데 사용하지 않는 것이 좋습니다. 분석 단위는
system, decision context, 작동했거나 작동하지 않은 control입니다.

## 필수 입력

- **Incident record**: Scope, severity history, member, owner, state transition입니다.
- **Audit trail**: 발견된 문제, 결정, approval, action, no-op, retry, rollback입니다.
- **Evidence set**: Metric, log, trace, change, notification, cited knowledge입니다.
- **Impact record**: Affected capability, duration, population, SLO effect입니다.
- **Recovery proof**: Restored state, verification window, residual risk입니다.

Authoritative record가 있으면 chat recollection에서 시작하지 않습니다. Recollection은 context를
추가할 수 있지만 participant statement로 표시하는 것이 좋습니다.

## Review 구성

1. **Draft를 만듭니다.** Timestamp 또는 content를 변경하지 않고 incident 및 append-only
	audit record에서 initial chronology를 생성합니다.
2. **Impact를 검증합니다.** Start, detection, mitigation, recovery, end time과 affected
	capability, measured SLO effect를 확인합니다.
3. **Decision을 재구성합니다.** 각 key decision에 당시 사용할 수 있던 evidence,
	selected branch, resulting outcome을 기록합니다.
4. **Cause를 구분합니다.** Root cause, contributing condition, detection gap, response gap,
	recovery gap을 구분합니다.
5. **Claim을 test합니다.** 각 causal statement를 evidence에 연결하고 disproved되지 않은
	credible alternative를 유지합니다.
6. **Control을 평가합니다.** 작동하거나 실패한 detector, rule, approval, stop condition,
	rollback, notification, audit control을 기록합니다.
7. **Follow-up을 정의합니다.** Owner, due date, priority, measurable completion evidence가
	있는 corrective 및 preventive action을 생성합니다.
8. **Review하고 승인합니다.** Unsupported claim을 해결하고 sensitive data가 제외됐는지
	확인하며 required reviewer approval을 받습니다.
9. **연결하고 종료합니다.** Approved postmortem을 incident에 첨부하고 unresolved risk와
	action ownership이 명확한 경우에만 종료합니다.

## Timeline checkpoint

| Checkpoint | 수집할 내용 |
|------------|-------------|
| First impact | 지원되는 최초 user 또는 operation impact입니다. |
| Detection | First 발견된 문제와 durable route에 도달한 시점입니다. |
| Triage | Severity, owner, scope, first decision deadline입니다. |
| Mitigation | Proposal, 결정, approval, execution, observed effect입니다. |
| Rollback 또는 recovery | Trigger, action, verification, residual impact입니다. |
| Stable service | Recovery observation window의 시작과 종료입니다. |

## Follow-up 품질

유용한 follow-up은 control을 변경하거나 evidence gap을 해소합니다. Owner 또는 test가 없는
"더 주의하기" 같은 action은 피합니다.

| 필수 field | Evidence target 예시 |
|------------|----------------------|
| Owner와 due date | Named accountable role과 review date입니다. |
| 변경된 control | Rule, runbook, test, alert, rollback 또는 provider reference입니다. |
| Completion proof | Passing scenario, drill record 또는 measured production signal입니다. |
| Safety mode | Enforcement change 전에 확보한 shadow evidence입니다. |
| Closure condition | Action을 종료할 수 있는 objective result입니다. |

재사용 가능한 rule, runbook 또는 knowledge improvement는 normal review와 promotion path가
수락할 때까지 inert candidate로 유지됩니다.

## 중지 조건

Impact, recovery, unresolved risk, owner, required follow-up이 없으면 종료하지 않습니다.
Evidence set이 크게 변경되거나 timestamp가 충돌하거나 cited record를 검증할 수 없거나
sensitive data가 draft에 들어가면 review를 일시 중지합니다. Unsupported cause는 hypothesis로
유지합니다.

## Evidence와 완료

Approved record는 incident, evidence-set version, timeline, RCA claim, response action,
approval, rollback, recovery proof, reviewer, follow-up item을 연결하는 것이 좋습니다.
Postmortem version과 approval을 incident audit trail에 기록합니다.

Reviewed postmortem이 연결되고 적절한 owner가 residual risk를 수락하며 모든 required
follow-up에 owner, due date, evidence target이 지정되면 workflow를 완료합니다. Follow-up은
incident 종료 후 완료할 수 있습니다.

## 관련 runbook

| 다음 작업 | 문서 |
|-----------|------|
| Source evidence와 causal claim 재검사 | [RCA evidence collection](rca-evidence-collection-ko.md) |
| Frozen scenario로 detector 개선 | [Alert tuning](alert-tuning-ko.md) |
| Corrective resilience control 검증 | [Chaos game day](chaos-game-day-ko.md) |
