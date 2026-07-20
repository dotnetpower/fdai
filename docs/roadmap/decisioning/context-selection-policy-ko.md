---
translation_of: context-selection-policy.md
translation_source_sha: 1be4cd86331250c4cb1c3b29d3a9d8025fb4d84b
translation_revised: 2026-07-21
---
# 컨텍스트 선택 정책

이 문서는 경계가 있는 working context 선택을 둘러싼 정책 경계를 소유합니다. 기존 결정론적
composer를 active 기본값으로 유지하면서, 검토된 후보를 명시적인 근거 기반 승격 전에 shadow
mode에서 측정할 수 있게 합니다.

> **범위.** 정책은 미리 추정된 entry id를 선택하고 manifest를 생성합니다. Transcript 지속성,
> summarization, retrieval, token 추정, prompt rendering, model call, answer generation은 이 경계
> 밖에 유지됩니다.
>
> **기본값.** `deterministic-tiered-v1@1.0.0`은 불변이며 authoritative합니다. 승격된 후보가
> 없으면 선택 entry와 `ContextManifest`는 이전 `compose_working_context` 동작과 byte-for-byte로
> 동일하게 유지됩니다.

## 설계 요약

`ContextSelectionInput`은 후보 entry, trust class, token budget, model capability metadata를
고정합니다. `ContextSelectionPolicy`는 정렬된 선택 entry id와 `ContextManifest`만 반환할 수
있습니다. 필수 wrapper는 정확히 같은 입력으로 정책을 두 번 실행하고 모든 invariant를 검증한
뒤, 선택된 불변 entry를 재구성합니다. 어떤 정책도 store, retriever, summarizer, renderer,
model client, tool 또는 executor를 받지 않습니다.

## 계약 경계

Core 계약은 `src/fdai/core/working_context/`에 있습니다:

| 타입 | 책임 |
|------|------|
| `ContextSelectionInput` | 불변의 사전 추정 entry, trust class, budget, model metadata |
| `ContextSelectionOutput` | 정렬된 선택 id와 기존 manifest |
| `ContextSelectionPolicy` | 순수 `select(input) -> output` Protocol |
| `DeterministicTieredPolicy` | 기존 tiered composer adapter |
| `execute_context_selection_policy` | 필수 결정론적 replay 및 invariant wrapper |

호출자가 계속 모든 I/O를 소유합니다. `assemble_turn_context`는 기존 retrieval 및
operator-memory seam으로 entry를 준비하고 하나의 입력을 고정하며, authoritative selection을
얻은 뒤 active 결과가 완료된 후 후보 평가를 예약할 수 있습니다.

## 필수 invariant

모든 active 또는 shadow 결과는 같은 validator를 통과합니다. Validator는 다음을 거부합니다:

- 누락, 불완전 또는 순서가 바뀐 pinned constraint;
- invented id, 중복 선택 id 또는 여러 manifest tier에 할당된 id;
- 선택 entry와 맞지 않거나 `history_budget`을 넘는 token 합계;
- trust-class 불일치 또는 pinned/tier 순서를 위반하는 prompt 순서;
- 불완전한 omission metadata 또는 정확히 하나의 불변 입력 entry로 해석되지 않는 id;
- 같은 frozen input의 두 번째 실행에서 달라진 output;
- 모든 policy exception.

Invariant 오류는 현재 요청을 fail closed합니다. 승격된 후보가 원인이면 policy authority가 해당
정책의 kill switch를 engage하고 이후 요청을 위해 명시된 rollback target을 복원합니다. 실패
output은 prompt rendering이나 model에 절대 도달하지 않습니다.

## Registry 및 승격

정책 identity는 불변 쌍 `(policy_id, version)`입니다. `CapabilityRuntime`은
`context_selection_policy` reference binding을 가지므로 기존 capability registry가 installation
authority로 유지됩니다. 정확한 policy ref만 등록하며 Python을 load하거나 package를 download하거나
tool 또는 execution capability를 부여하지 않습니다.

`ContextSelectionPolicyAuthority`는 process lock 아래 revision compare-and-set을 적용합니다:

1. **Disabled 설치.** 정확한 capability binding과 policy ref가 이미 active여야 합니다.
2. **Shadow 활성화.** 후보는 측정 가능해지지만 active output에는 영향을 줄 수 없습니다.
3. **명시적 승격.** Promotion은 정확한 후보 version, 하나 이상의 sample과 invariant failure 0을
   가진 timezone-aware evidence window, 그리고 현재 active policy를 rollback target으로 지정합니다.
4. **Demote 또는 kill.** 검토된 regression은 demote할 수 있습니다. Invariant 위반은 policy별 kill
   switch를 자동 engage하고 rollback합니다. stale revision은 update race에서 패배합니다.

Authority는 자동 승격하지 않습니다. 또한 tool, role, ActionType, Workflow, model permission 또는
executor identity를 넓힐 수 없습니다.

## Shadow 평가 및 근거

`ContextSelectionShadowRunner`는 제한된 수의 후보를 `asyncio.to_thread`와 후보별 timeout으로
실행합니다. Scheduling은 async composition seam에서 즉시 반환됩니다. Runner는 baseline과 같은
`ContextSelectionInput` 객체를 사용하며 후보 결과를 active prompt 경로에 교체, 변경 또는 반환하지
않습니다.

각 durable comparison은 다음을 기록합니다:

- baseline/candidate policy ref, manifest 및 token 사용량;
- input fingerprint, 선택 id overlap, omission 및 pinned preservation;
- 선택 relevance 평균과 선택적인 answer-quality evaluation linkage;
- 측정 latency와 정확한 exception, timeout 또는 invariant failure reason.

Production adapter는 기존 `StateStore` tracked-state prefix 아래에 이 record를 저장합니다. PostgreSQL
durability와 atomic create semantics를 재사용하므로 새 table이나 Alembic migration이 필요하지
않습니다. Fan-out, pending run, timeout은 모두 제한됩니다.

## Replay 및 console

`replay_approved_context_fixtures`는 approved 표시된 fixture만 실행하고 전체 ordered output과
manifest를 비교합니다. Replay는 live selection과 같은 double-execution invariant validation을
수행하므로 unreplayable policy는 offline evidence를 통과할 수 없습니다.

Console route `GET /context-selection-comparisons`는 Reader-gated `ReadPanel`입니다. Token 사용량,
overlap, omission, pinned preservation, latency, 정확한 failure를 표시합니다. SPA에는 install,
enable, promote, demote, rollback 또는 kill-switch control이 없습니다. Governance transition은
계속 server-side에 있고 소유 command path를 통해 audit됩니다.

## 실패 posture

- 누락되거나 잘못된 policy output은 prompt rendering 전에 fail closed합니다.
- Candidate exception 또는 timeout은 evidence일 뿐 active selection을 바꾸지 않습니다.
- Registry update race는 새 revision을 요구하며 last-writer-wins를 지원하지 않습니다.
- Killed policy는 별도로 구현된 reviewed recovery path 없이는 shadow에 다시 진입할 수 없습니다.
- Built-in deterministic policy는 fallback rollback target으로 유지됩니다. 이 정책이 invariant를
  위반하더라도 validation을 우회하지 않고 selection이 fail closed합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| Working-context tier와 prompt layer | [진화하는 시스템 프롬프트](prompt-composition-ko.md) |
| Conversation 지속성 및 assembly | [오퍼레이터 콘솔](../interfaces/operator-console-ko.md) |
| Module 및 DI 경계 | [프로젝트 구조](../architecture/project-structure-ko.md) |
| Shadow 및 promotion 안전 | [보안 및 ID](../architecture/security-and-identity-ko.md) |
