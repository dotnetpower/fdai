---
title: 감사 로그 읽기(Read the audit log)
description: 모든 자율 결정에 대해 append-only 감사 로그가 기록하는 것과, 증상에서 root 이벤트로 거슬러 추적하는 법.
translation_of: read-audit-log.md
translation_source_sha: 34c1da56451cbe35cff23769e75cf2d4b0aeec1c
translation_revised: 2026-07-07
---

# 감사 로그 읽기(Read the audit log)

감사 로그는 AIOpsPilot이 무엇을 했는지에 대한 단일 진실 소스입니다. append-only,
immutable 이며, 제어 평면이 내리는 모든 자율 결정을 포함합니다 - 거부, 타임아웃,
no-op로 끝난 것까지 전부. 이 가이드는 각 항목이 무엇을 담는지, 증상에서 root 이벤트
로 거슬러 걷는 법을 다룹니다.

## 항목이 담는 것

모든 항목은 하나의 결정에 대한 전체 라이프사이클을 기록합니다. 최소:

- **이벤트 id** - 소스 이벤트의 안정적, idempotency-safe 식별자. 같은 이벤트로부터
  나온 여러 결정은 이 id를 공유합니다.
- **티어** - T0 / T1 / T2 - 결정이 결정론적으로 돌았는지 추론 티어까지 갔는지
  즉시 알 수 있습니다.
- **규칙 · 정책 · 모델 참조** - T0/T1은 규칙 id, T2는 모델 식별자와 인용된
  grounding 문서.
- **판정** - AUTO / HIL / DENY와 그것을 만든 분류.
- **액터 정체성** - 누가/무엇이 변경을 실행했나. AUTO는 executor의 user-assigned
  Managed Identity, HIL은 승인 사용자.
- **타임스탬프** - RFC 3339, UTC.
- **Shadow vs enforce 모드** - 모든 항목은 그 시점의 능력이 shadow 였는지 표시.
  Shadow 항목은 *would-have-been* 액션을 함께 실습니다.
- **롤백 참조** - 액션과 연결된 롤백 계획의 id, 또는 롤백이 없는 액션은 `none`.

## 인시던트 추적

증상(메트릭 스파이크, 알림, 예상 밖 변경된 리소스)에서 시작해 거슬러 걷습니다:

1. 감사 로그에서 리소스를 찾습니다. 모든 mutation은 AIOpsPilot 발원이든 out-of-band
   변경이든 항목으로 나타납니다.
2. 그 리소스의 최신 항목을 읽습니다. mutation을 만든 이벤트 id와 결정 체인을
   줍니다.
3. 이벤트 id로 거슬러 갑니다. 그 id를 가진 모든 이벤트는 관련 결정입니다 - 같은
   정규화된 이벤트가 T0 결정, T1 escalation, HIL 요청을 낳았을 수 있고, 모두 id
   를 공유합니다.
4. Shadow 항목과 상호 참조합니다. 실행되지 않은 액션도 shadow 모드로 would-have-been
   결정과 함께 나타나므로, AIOpsPilot이 제안한 것과 사람이 실제로 한 것을 비교
   할 수 있습니다.

## Replay와 사후 분석

감사 로그는 **judge-only replay**를 위해 설계됐습니다: 이벤트를 제어 평면에
replay 하고 다시 계산되는 결정을 볼 수 있습니다 - 기초 액션을 재실행하지 않고.
이게 지난 달 히스토리에 대해 제안된 규칙 변경을 diff 해 승격 전에 미리 보는 방식
입니다.

## 감사 로그에 *없는* 것

감사 로그는 결정과 액터 참조를 기록합니다 - 시크릿, 토큰, 고객 식별자, 사용자
데이터 페이로드는 절대 기록하지 않습니다. 진단 데이터가 필요하면 관측 스택(로그,
메트릭, 트레이스)이 올바른 곳입니다. 각 감사 항목은 그 관측으로 되돌아가는 상관
관계 id를 담습니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 여기서 읽게 될 HIL 항목을 쓰는 운영자 상호작용 | [approve-change-ko.md](approve-change-ko.md) |
| `would-have-been` 결정이 담기는 이유 | [../concepts/shadow-then-enforce-ko.md](../concepts/shadow-then-enforce-ko.md) |
| 계속 나쁘게 감사되는 규칙을 좁히기 | [override-a-rule-ko.md](override-a-rule-ko.md) |
| 감사 로그의 스토리지와 보존 설계 | [../../roadmap/observability-and-detection-ko.md](../../roadmap/observability-and-detection-ko.md) |
