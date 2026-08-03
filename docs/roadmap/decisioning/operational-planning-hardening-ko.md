---
title: 운영 계획 하드닝 근거
translation_of: operational-planning-hardening.md
translation_source_sha: b16cd234f8d35c52d17e5aabee5f8b46e6fbbf7e
translation_revised: 2026-08-03
---
# 운영 계획 하드닝 근거

이 문서는 운영 계획의 구현 및 적대적 검토 근거를 기록합니다. 구현된 shadow 동작과 enforcement
승격 전에 필요한 release evidence를 구분합니다.

> **범위:** 검토 대상은 typed logic asset, 결정론적 선택, specialist evidence, sandbox 및 twin
> simulation, durable Process 기록, execution handoff, Planning Room, runtime availability, bounded
> input입니다.
>
> **결과:** 12개의 독립적인 검토 라운드 이후 알려진 Medium, High 또는 Critical 결함은 없습니다.
> 남은 항목은 Low release-readiness gap이며 planning이 shadow mode에 머물기 때문에 authority를
> 높일 수 없습니다.

## 한눈에 보는 설계

캠페인은 구현된 contract에서 재현되는 finding만 인정했습니다. 확인된 Medium 이상 finding에는
focused regression test와 별도 hardening commit을 추가했습니다. Proposal evidence를 execution
authority로 오해한 finding은 불필요한 code를 추가하지 않고 기각했습니다.

## 구현 근거

| Capability | 근거 |
|------------|------|
| Logic identity 및 authorization | Canonical release가 typed function을 고정하고 invocation은 agent, role, purpose, input schema, artifact digest, deterministic seed를 검사합니다. |
| Decision planning | Hard constraint가 Pareto pruning 및 기존 weighted arbitration보다 먼저 적용됩니다. No-action baseline과 rejected reason은 immutable 상태를 유지합니다. |
| Agent collaboration | 기존 specialist topic이 optional Forseti coordinator에 evidence를 제공합니다. Direct agent call, 새 agent 또는 shared mutable workflow state를 추가하지 않았습니다. |
| Simulation | 검토된 programmatic pipeline과 active/challenger twin model이 typed receipt를 생성합니다. 누락, malformed, stale 또는 divergent evidence는 plan을 보류합니다. |
| Durability | 기존 Workflow 및 Process snapshot과 append-only child event가 idempotent replay로 planning phase를 기록합니다. |
| Execution handoff | 선택한 option은 exact target 및 release identity를 가진 proposal-only MutationPlan으로 compile됩니다. Risk, approval, execution, recovery, audit은 분리되어 있습니다. |
| Effect closure | 성공을 닫기 전에 selected option, MutationPlan, ResponseOutcome prediction id가 하나의 exact chain을 구성합니다. |
| Product surface | 기존 Process route가 strict read-only Planning Room projection을 제공합니다. Mutation route 또는 executor identity를 추가하지 않습니다. |
| Runtime operation | Startup은 하나의 immutable capability status에서 availability, enablement, shadow mode, reason, 누락 prerequisite를 기록합니다. |

## 검토 라운드

| 라운드 | 초점 | 결과 |
|-------:|------|------|
| 1 | Agent authority 및 separation of duties | Authority bypass가 없습니다. MutationPlan compilation은 proposal-only artifact이므로 action execution이라는 주장을 기각했습니다. |
| 2 | Deterministic replay | Candidate, effect, receipt 순서를 고정해 동등한 input이 byte-identical case와 plan을 생성합니다. |
| 3 | Constitutional constraint | 누락, stale, conflict 또는 review-required context가 ineligible이 되어 arbitration에 도달하지 못함을 확인했습니다. |
| 4 | Fan-out 및 candidate enumeration | Specialist domain set을 제한하고 hard cap 초과 candidate는 truncation하지 않고 실패하도록 확인했습니다. |
| 5 | Compute sandbox isolation | Reviewed source digest, generated client, capability token, tool allowlist, timeout, byte ceiling, credential 없음, 일반 network 없음을 확인했습니다. |
| 6 | Twin evidence 및 model replay | 동등한 active/challenger input이 하나의 stable simulation receipt를 만들도록 effect ordering을 수정했습니다. |
| 7 | Process durability 및 concurrency | PostgreSQL child-event replay를 atomic idempotency conflict 처리와 하나의 outbox winner로 수정했습니다. |
| 8 | Execution 및 outcome lineage | Closure를 exact selected plan, ActionType, MutationPlan, prediction id에 결속했습니다. |
| 9 | Planning Room security 및 responsive layout | Strict decoding, correlation check, read-only routing, action control 없음 여부를 확인하고 좁은 화면의 cell wrapping을 추가했습니다. |
| 10 | Frozen scenario truthfulness | Manifest를 partial로 낮추고 두 release-evidence proxy를 명시했습니다. |
| 11 | Runtime observability 및 degradation | Structured capability status를 추가했습니다. 누락된 optional evidence binding은 표시되며 관련 없는 agent work를 차단하지 않습니다. |
| 12 | Target binding 및 adversarial bound | Plan을 frozen target에 결속하고 objective, effect, constraint, simulation, text, 전체 nested evidence manifest에 artifact 생성 전 limit을 적용했습니다. |

## Live shadow 증명

2026-08-03에 generic non-production Azure Container App을 대상으로 read-only observation을
수행했습니다. Allowlist에 포함된 state field만 canonicalize했으며 resource name, account identifier,
endpoint, identity, secret reference 또는 raw deployment payload는 repository에 포함하지 않았습니다.

관측 대상에는 current revision과 ready revision이 충돌하는 evidence가 있었습니다. 따라서 운영 계획은
`held_no_eligible_option` 사유의 `ineligible` assessment를 생성했고 selected option과 execution attempt는
없었습니다. 두 번째 read는 같은 allowlisted state digest를 생성했습니다. 이 증명은 fail-closed live
evidence 처리와 Azure mutation 0건을 보여 주며 성공적인 enforcement drill을 주장하지 않습니다.

## 잔여 위험

Frozen scenario manifest는 두 개의 명시적 proxy 때문에 `partial` 상태를 유지합니다.

- **Partial execution recovery:** Contract test는 mismatched outcome을 verified rollback으로 닫지만,
  전용 non-production partial-execution drill은 release evidence로 남아 있습니다.
- **Standing emergency authority:** A0 proposal-only 동작을 검증했습니다. Standing emergency authority의
  명시적 non-applicability evidence는 release evidence로 남아 있습니다.

두 gap은 execution을 활성화할 수 없으므로 제공되는 shadow capability에서는 Low입니다. Verified
scenario evidence로 교체되기 전까지 향후 enforcement promotion을 차단합니다. Capability status,
shadow mode, 기존 risk path, policy escape 0건 요구 사항은 계속 authority를 가집니다.

## 검증

Focused validation은 전체 operational-planning subsystem, frozen manifest, runtime bootstrap status,
strict Python typing, Console model test, 전체 Console typecheck 및 build, translation freshness,
punctuation, diff hygiene를 포함했습니다. 중앙 integration validation은 `main` 병합 전에 전체 구현 및
hardening 범위를 통과했습니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 운영 계획 설계 | [운영 계획](operational-planning-ko.md) |
| Agent ownership 및 arbitration | [Agent Pantheon](../agents/agent-pantheon-ko.md) |
| 읽기 전용 graph simulation | [Assurance Twin](../operations/assurance-twin-ko.md) |
