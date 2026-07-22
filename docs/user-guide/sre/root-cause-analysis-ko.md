---
title: 근본 원인 분석
description: FDAI가 티어별 인용 가능한 근본 원인 가설을 만들고 증거가 부족할 때 판단 보류하는 방법입니다.
translation_of: root-cause-analysis.md
translation_source_sha: 37b022db392263a2253f76fca23238acfbe7accb
translation_revised: 2026-07-22
---

# 근본 원인 분석

근본 원인 분석(Root-Cause Analysis, RCA)은 인시던트가 발생했을 수 있는 이유를
설명합니다. FDAI는 RCA를 citation, confidence, tier, 근거 확인 state가 있는 hypothesis로
저장합니다. RCA는 판단을 위한 증거이며 변경 실행 권한이 아닙니다.

## Trust tier별 RCA

| 티어 | 역할 | 일반적인 증거 |
|------|------|---------------|
| T0 | 직접적인 결정론적 원인 | 일치한 rule, 위반된 control, 선언된 수정 |
| T1 | 과거 incident 재사용 또는 결정론적 causal chain | 해결된 incident, 순서가 있는 change 및 symptom event, resource dependency |
| T2 | 신규 또는 모호한 사례의 grounded reasoning | 검증된 telemetry, event, rule, knowledge chunk, scenario evidence |

T1 reuse는 과거 원인과 learned action이 현재 증거에도 적용되는지 다시 검증합니다. T1
causal chain은 선행 change를 root로 요구합니다. Symptom만 있는 window는 원인을 만들지
않고 판단 보류합니다.

Reuse가 재검증에 실패하면 FDAI는 learned action을 replay하지 않습니다. 현재 evidence set으로
구성된 T2 reasoner를 시도하거나 사람 검토로 보류할 수 있습니다. 어느 경로든 T1 reject 이유를
기록하므로 similarity hit가 stale scope, 변경된 dependency, 대체된 수정을 숨길 수
없습니다.

## 근거 확인 gate

모든 citation은 reasoner에 제공된 evidence set에서 나와야 합니다. Malformed response,
fabricated citation, unsupported claim, 설정 threshold 미만 confidence는 판단 보류
hypothesis가 되어 사람 검토로 이동합니다.

Telemetry와 operator document는 untrusted input입니다. Model text는 policy, what-if 결과,
deterministic verifier를 덮어쓸 수 없습니다.

Confidence는 reasoner의 self-reported confidence가 아니라 verifier, cross-check, 근거 확인
signal에서 계산됩니다. T2 quality gate는 독립적인 cross-check, deterministic verification,
supplied evidence allowlist 안에서 resolve되는 citation을 요구합니다. Rubric 또는 cross-check는
eligibility를 낮출 수만 있고 근거 없는 candidate를 구제할 수 없습니다.

| RCA outcome | 저장 결과 | 대응 경로 |
|-------------|-----------|-----------|
| Grounded 및 configured threshold 이상 | Citation이 있는 hypothesis | Typed proposal의 근거로 사용 가능 |
| Ambiguous alternative | Confidence가 제한된 hypothesis | 사람 검토 |
| Stale T1 reuse | Provenance가 있는 rejected reuse | Current-evidence T2 또는 사람 검토 |
| Malformed 또는 fabricated citation | 판단 보류 hypothesis | Action 없음, audit 및 검토 |

## Causal chain

Structured T1 chain은 root 및 failure event ID와 ordered hop을 보존합니다. 각 hop은 cause
및 effect reference, lead time, relationship, confidence를 기록합니다. Resource dependency
data가 있으면 관련 경로를 강화하고 무관한 연결을 차단합니다.

시간 순서만으로 확실한 원인이 되지 않습니다. Confidence는 제한되며 여러 root가 비슷하게
failure를 설명하면 낮아지고, 가장 약한 supported link를 기준으로 결정됩니다.

## RCA dossier 읽기

다음 요소를 함께 확인하세요.

1. Incident 및 correlation ID.
2. Tier, outcome, confidence, 근거 확인 state.
3. Citation과 evidence freshness.
4. Alternative 또는 ambiguous hypothesis.
5. 존재하는 경우 structured causal hop.
6. 연결된 response plan, 결정, mode, rollback reference.

Chain data나 evidence가 없으면 unavailable로 표시합니다. Browser는 audit record보다 더
확신도 높은 설명을 재구성하지 않습니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 증거 범위를 제한하는 방법 | [분류와 조사](triage-and-investigation-ko.md) |
| Mitigation을 제안하는 방법 | [대응 계획과 완화](response-plans-and-mitigation-ko.md) |
| 판단을 감사하는 방법 | [감사 로그 읽기](../guides/read-audit-log-ko.md) |
| 상세 RCA 계약 | [관측성과 감지](../../roadmap/rules-and-detection/observability-and-detection-ko.md) |
