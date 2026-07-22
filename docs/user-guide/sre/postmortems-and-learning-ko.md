---
title: 포스트모템과 학습
description: FDAI가 증거 기반 postmortem draft를 만들고 교훈을 governed improvement candidate로 바꾸는 방법입니다.
translation_of: postmortems-and-learning.md
translation_source_sha: 14a2532379635094bcd65ac9de26a1d7983be48c
translation_revised: 2026-07-22
---

# 포스트모템과 학습

포스트모템은 audit record를 다시 쓰지 않고 impact, chronology, cause, response, recovery,
follow-up을 설명합니다. FDAI는 incident 및 audit data로 deterministic template을 만들고,
선택적으로 구성된 postmortem model을 통해 내용을 보강할 수 있습니다.

## 초안 내용

- Incident summary와 검증된 impact.
- 순서가 있는 audit timeline과 lifecycle transition.
- Grounded root cause와 contributing factor.
- 실행된 action, approval, rollback, recovery evidence.
- 잘 작동한 점, 실패한 점, 해결되지 않은 limitation.
- Owner가 지정된 corrective 및 preventive follow-up.

Optional model을 사용할 수 없어도 generator는 template-based draft를 반환합니다. 누락된
impact나 cause를 만들어내지 않습니다.

## 증거 경계 보존

Postmortem은 audit row와 citation을 참조하며 변경하지 않습니다. 사람의 편집은 machine
record와 구분됩니다. 누락된 증거는 unavailable로 표시하고 unresolved hypothesis는
hypothesis로 유지합니다.

## 학습 루프

Learning extractor는 반복되는 correlation key, root cause, 성공한 action type, override,
rollback, 사람 승인 pattern을 식별할 수 있습니다. 결과는 rule, runbook, knowledge entry의 inert
candidate가 됩니다.

Candidate는 provenance를 포함하고 schema, review, regression, shadow, promotion gate를
통과해야 합니다. Learning loop는 active catalog를 직접 편집하지 않습니다.

## 검토 워크플로

1. Incident scope, severity, verified impact를 확인합니다.
2. Audit timeline과 external evidence를 대조합니다.
3. Root cause, contributing factor, detection gap을 구분합니다.
4. 남은 영향을 포함해 rollback 및 recovery outcome을 기록합니다.
5. Follow-up owner와 측정 가능한 completion evidence를 지정합니다.
6. 재사용 가능한 교훈을 governed catalog 또는 runbook workflow로 제출합니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| Incident가 종료되는 방법 | [인시던트 관리](incident-management-ko.md) |
| RCA가 grounded 상태를 유지하는 방법 | [근본 원인 분석](root-cause-analysis-ko.md) |
| 판단을 재구성하는 방법 | [감사 로그 읽기](../guides/read-audit-log-ko.md) |
| 포스트모템 절차 | [포스트모템 workflow runbook](../../runbooks/postmortem-workflow-ko.md) |
