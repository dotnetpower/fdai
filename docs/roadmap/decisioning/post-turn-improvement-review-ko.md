---
title: Post-Turn 개선 검토
translation_of: post-turn-improvement-review.md
translation_source_sha: 9245794e8e688eb65e8abb92715b8d3481e6ae56
translation_revised: 2026-10-19
---

# Post-Turn 개선 검토

이 설계는 FDAI가 완료된 운영자 대화를 요청 경로 밖에서 검토하고 비활성 개선 제안을
만드는 방법을 정의합니다. 동의, 근거 제한, 에이전트 소유권, mixed-family 검토, 영속 중복
제거, 통제된 라우팅, 읽기 전용 운영을 다룹니다.

> **범위:** 검토는 운영자 기억, 런타임 스킬 또는 룰 힌트를 제안합니다. 런타임 동작을
> 변경하거나 권한을 부여하거나 자체 출력을 승인하거나 완료된 응답을 지연하지 않습니다.
## 한눈에 보는 설계

Bragi는 `object.post-turn-review`에 범위가 제한된 completed-turn 묶음 하나를 발행합니다. Learner인
Norns는 결정론적 충족 여부를 적용하고 선택적으로 서로 다른 두 모델 계열에 동일한 타입이 지정된
제안을 요청합니다. 완전한 합의가 이루어지면 대상 산출물의 소유자 subsystem에 초안을 만들
수 있습니다. 그 밖의 모든 결과는 범위가 제한된 최종 기록이 됩니다.

![한눈에 보는 설계. 주요 단계는 완료 turn 저장, Bounded non-blocking queue, Bragi가 object.post-turn-review 발행, Norns eligibility 검사, Durable terminal record, 서로 다른 두 model family, 완전한 합의와 결정론적 검사, Operator-memory draft, Runtime-skill draft, Norns RuleCandidate 경로, Read-only projection입니다.](../../diagrams/generated/fdai-roadmap-decisioning-post-turn-improvement-review-01.ko.svg)

## 입력 계약

`PostTurnReviewInput`은 대화 기록나 프로세스 스냅샷이 아니라 범위가 제한된 변환 결과입니다. 다음
항목을 포함합니다:

- 고정된 검토, operator-turn, assistant-turn, principal-scope 식별자.
- 완료 시간과 safe 근거 참조.
- 각 도구 증적의 도구 이름, 상태, 근거 참조. Raw 도구 출력은 제외합니다.
- 검증 결과, recovered-failure 상태, 선택적 repeated procedure
  지문.
- principal이 `share_with_learner: true`로 설정한 경우에만 선택적 운영자 및 assistant 본문과 명시적 교정문.
- 범위 종류와 범위 참조를 모두 아는 경우에만 선택적 operator-memory 범위.

식별자, 본문 길이, 튜플 개수, 시각, 범위 쌍은 생성 시 검증합니다. Raw 자격 증명,
hidden reasoning, unrestricted 프로세스 상태, unrestricted 도구 출력은 계약에 포함하지 않습니다.

명시적 교정문은 동의 없이 공유할 수 있는 메타데이터가 아니라 원문입니다. Bragi는 일치하는
공유 동의가 없으면 outbox 체크포인트를 만들기 전에 두 본문과 모든 교정문을 제거합니다.
Norns도 독립적으로 두 본문과 일치하는 동의 기록을 요구하고, 모든 교정문에서 민감정보를
검사합니다. 본문과 교정문을 줄바꿈으로 연결한 전체 텍스트에 UTF-8 기준 64 KiB 한도를
적용합니다. 교정문만 제공해 두 본문이 모두 있어야 한다는 조건을 우회할 수 없습니다.

Outbox 복구는 일치하는 동의 기록이 없는 기존 원문 레코드를 다시 발행하지 않고 보류합니다.
원본 레코드를 유지하고 내용을 포함하지 않는 동작 사유를 기록하며, 선택된 복구 배치의 다른
유효한 레코드는 계속 발행할 수 있습니다. 이 처리는 과거 기록의 원문을 삭제하거나 재시작 후
현재 동의를 독립적으로 다시 확인하는 기능은 아닙니다.

## 소유권 및 전송 계층

Bragi는 계속 `object.post-turn-review`의 single 쓰기 담당입니다. Typed publisher는 이미 검증되고
동의가 확인된 `PostTurnReviewInput`만 받습니다. Operator API는 범위가 제한된 큐에 제출하고 해당
큐는 Operator 소유 요청을 발행합니다. Core ingress가 Bragi 경계를 호출하며, Operator는
검토자를 만들거나 자신을 Bragi 또는 Norns로 표시하지 않습니다.

Norns는 `object.post-turn-review`의 consent-filtered `post_turn_review` 묶음을 구독합니다.
`producer_principal`이 `Bragi`가 아닌 묶음을 차단하고 검토 대응을 엄격하게 parse한 뒤
주입된 조정기를 off 경로에서 호출합니다. Norns는 새 owned 토픽이나 실행 권한을
얻지 않습니다.

Azure 전송 계층은 모든 Pantheon logical 객체 토픽을 `MultiplexedEventBus`를 통해 구성된
physical 객체 토픽으로 보냅니다. 따라서 headless 런타임과 Operator API는 같은
logical-to-physical 대응을 사용합니다. Process-local 전송 계층도 Azure 근거를 만들지 않고
같은 logical 계약을 유지합니다.
Production Operator 구성은 이제 최종 answered semantic turn을 범위가 제한된 asynchronous
post-turn 큐에 제공하며, 이 큐는 turn projection을 차단하지 않고 Operator 소유
`operator.post-turn-review.requests` 묶음을 구성된 semantic transport로 발행합니다.
Core는 이 요청 토픽을 런타임 논리 토픽 집합에 등록하므로, 존재하지 않는 원시 hub가 아니라 semantic
physical Event Hub에서 다중화된 요청을 받습니다. Core는 이 요청을 소비하고 검증한 뒤 Bragi의 typed publisher를 호출하므로 Bragi만
`object.post-turn-review`를 씁니다.

## 반복 질의 관측

Core는 사람이 요청하고 실행이 완료된 온톨로지 질의의 기술 상세에 타입이 지정된 `PostTurnProcedureReceipt`를
추가합니다. 지문은 정확한 온톨로지 및 의미 카탈로그 버전, 용도, 순서가 있는 DAG, 정본 함수,
JSON 인자의 자료형과 구조를 연결합니다. 인자 값, 질문 원문, principal 신원과 노드의 임시
이름은 제외합니다. 자연어 질문의 의미가 아니라 실행된 형태를 비교합니다. 워크로드, 불완전한
실행 및 근거, 형태 깊이 한도 초과에는 지문 대신 명시적인 사용 불가 사유를 제공합니다.

Operator는 증적을 인증된 principal, 턴, 버전, 계획, 완료된 검사와 실행 다이제스트에 대조하고,
검증되지 않은 지문이나 반복 횟수 힌트는 무시합니다. 기존의 현재 학습 공유 설정으로 큐 제출을
제어합니다. Bragi는 타입이 지정된 메타데이터를 보존하지만 일치하는 본문 동의가 없으면 원문은
제거합니다. 선택적 관측 메타데이터 때문에 기존 답변이 전송 한도를 넘으면 Core는 해당
메타데이터만 제외하고 내용을 포함하지 않는 사유를 기록한 뒤 변환 결과 식별자를 다시
계산합니다. 답변을 자르거나 메타데이터를 원문 검토의 적격 입력으로 취급하지 않습니다.

Norns는 기존 영속 StateStore에서 `(현재 - UTC 7일, 현재]` 안의 서로 다른 정본 principal
범위를 집계합니다. 기본 임계값은 5이며 생성자에서 2부터 20까지의 정수를 지정할 수 있습니다.
저장된 임계값과 런타임 설정이 다르면 근거를 초기화하지 않고 차단합니다. 리비전으로 보호되는
레코드 하나에 형태를 최대 128개 보관합니다. 수락한 관측을 갱신할 때 만료된 형태를 정리하지만,
예약된 물리 삭제를 검증한 것은 아닙니다. 용량 소진이나 손상된 상태는 빈 수집 결과가 아니라
명시적인 오류로 처리합니다.

조건을 충족한 집단은 먼저 불변의 대기 신호가 됩니다. Norns는 기존 학습 원장에 비활성 후보를
기록한 뒤 원본 신호의 처리를 확인합니다. 재시작, 복제본 경쟁이나 체크포인트 실패 후에도
같은 식별자로 재현할 수 있습니다. 신호는 새 토픽이나 활성화된 Rule이 아니라 기존 Mimir
입력인 `object.rule-candidate`에서 `source_signal=console.recurrent_query`를 사용합니다.
개수는 관측한 임계값 집단의 수이며 전체 질의나 전체 principal 수가 아닙니다. principal
신원이나 인자 값을 게시하지 않고, 버전 다이제스트와 정본 도구 이름 및 범위가 제한된 근거
참조를 전달합니다.

기존 세 관점 합의, 비율 제한, 현재 발견 활성화 상한, Mimir 검토와 shadow 승격은 그대로
적용합니다. Norns 상태는 수집 사용 가능 여부, 게시 활성화와 비활성 모드를 구분합니다.
영속 저장소가 없으면 사용 불가로 유지합니다. 로컬 구성 요소 및 격리 PostgreSQL 검사로 배포
환경 전송, 운영 정책, 실제 Rule 생성이나 운영 안정화를 검증했다고 주장하지 않습니다.

## 충족 여부

`PostTurnEligibilityPolicy`는 모델 호출 전에 저렴한 결정론적 신호를 평가합니다:

| 신호 | 대상 조건 |
|--------|----------|
| Complex procedure | Tool-receipt 개수가 구성된 최소에 도달합니다. |
| 명시적 correction | 범위가 제한된 correction이 하나 이상 있습니다. |
| Recovered 실패 | Failure-to-success 전이가 기록됩니다. |
| Repeated procedure | 고정된 지문이 구성된 repetition 임계값에 도달합니다. |

동의가 없으면 `opted_out`, 주입 표시가 있으면 `unsafe_content`가 됩니다. Qualifying 신호가
없는 safe 턴은 `ineligible`이 됩니다. 이 결과는 검토자를 호출하지 않고 저장합니다.

## 검토 및 검증

Azure 어댑터는 카탈로그 프롬프트를 받고 strict JSON 객체 하나를 반환합니다. Temperature zero,
범위가 제한된 완료 예산, audience-scoped 워크로드 신원을 사용하며 도구 접근은 없습니다.

`ConsensusPostTurnReviewer`는 신원과 계열이 서로 다른 모델 두 개 이상의 완전한 합의만
허용합니다. 이후 다음 항목을 검사합니다:

- 모든 제안 근거 참조가 supplied 근거의 subset입니다.
- 제안 텍스트에 주입 표시나 secret-like 내용이 없습니다.
- Operator-memory 범위가 supplied 범위와 정확히 일치합니다.
- Runtime-skill Markdown이 parse되고 매니페스트 이름이 제안 이름과 일치합니다.

모델 연결 누락, one-family 해석, 모델 abstention, disagreement, 지원하지 않는 근거,
unsafe 내용 또는 스키마 실패는 `NoImprovement`를 만듭니다. 런타임은 agreement 요구사항을
모델 하나로 낮추지 않습니다.

## 통제된 라우팅

Accepted 제안은 기존 소유자 작업 흐름 뒤에 남습니다:

| 제안 | Owner 경로 | 초기 상태 |
|----------|-----------|----------|
| `OperatorMemoryCandidate` | `OperatorMemoryProposalWorkshop` | `draft` |
| `SkillProposalDraft` | `SkillWorkshop` | `draft` |
| `RuleCandidateHint` | Norns `submit_rule_hint`, 이후 Mimir 거버넌스 | inert 힌트/후보 |

런타임 authorizer는 검토와 구체화를 허용하지 않습니다. 별도로 인증된 human 경로가
초안을 검토해야 합니다. Operator 기억은 계속 서로 다른 승인자를 요구합니다. Runtime-skill
승격은 발행기 trust를 다시 확인하고 비활성화된 상태로 install합니다. Rule 후보는 계속
Mimir quality 및 승격 게이트를 통과해야 합니다.

## 내구성 및 멱등성

PostgreSQL은 검토 원장, 제안 점유, operator-memory 초안, runtime-skill 초안을 저장합니다.
고정된 검토 id는 재전달 후 중복 모델 호출을 차단합니다. principal 범위, 제안 종류,
procedure 지문, 근거 다이제스트로 만든 제안 키는 복제본 두 개가 같은 초안을 만드는
것을 차단합니다.

검토 상태는 `pending`에서 다음 최종 값 중 하나로 이동합니다:

- `ineligible`
- `abstained`
- `duplicate`
- `routed`
- `failed`

Compare-and-swap 전이는 첫 최종 결과를 보존합니다. 검토자 및 라우터 exception은 범위가 제한된
`failed` 사유가 되며 원래 대화 결과에는 영향을 주지 않습니다.

## 읽기 전용 운영

운영 패널 `post-turn-reviews`는 영속 저장소를 읽습니다. 검토, operator-memory 초안,
스킬 초안의 범위가 제한된 행 목록과 다음 whole-store 집계 개수를 반환합니다:

- 충족 여부, abstention, 중복 suppression, 라우팅, 실패.
- 제안 종류 및 owner-workflow 상태.
- 독립적으로 검토된 기억과 스킬 초안의 운영자 acceptance.

변환 결과는 제안 본문을 제외하며 approve, materialize, promote, execute 경로를 추가하지
않습니다. 사용할 수 없는 로컬 또는 deployed 데이터 출처는 사용 불가 또는 빈으로 남고 synthetic
검토 기록으로 대체되지 않습니다.

## 실패 행동

- 큐 포화는 응답을 바꾸지 않고 검토 작업을 폐기하며 큐 메트릭을 기록합니다.
- 재시도는 범위를 제한하며 asynchronous intake 실패에만 적용합니다.
- 검토자 연결이 없으면 `reviewer_unavailable`을 기록합니다.
- 잘못된 또는 non-Bragi 묶음은 Norns 경계에서 실패 시 차단합니다.
- 데이터베이스 충돌은 winning 검토 또는 제안 점유를 보존합니다.
- 읽기 변환 결과 실패는 제안 상태를 바꾸지 않습니다.

## 검증

Focused 커버리지는 충족 여부 신호, 입력 한계, consent, exact 합의, 주입 및 시크릿 canary,
소유자 라우팅, non-blocking 큐 행동, physical-topic multiplexing, restart-safe PostgreSQL 상태,
cross-replica 제안 점유, 읽기 전용 변환 결과, agent-role 배치를 포함합니다. 저장소 게이트는
`scripts/verify.sh`입니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|------------|------|
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/decisioning/post-turn-improvement-review.md) |
| Pantheon 소유권 및 토픽 | [에이전트 Pantheon](../agents/agent-pantheon-ko.md) |
| Operator 기억 및 런타임 스킬 | [프롬프트 조립](prompt-composition-ko.md) |
| Consent 및 대화 영속성 | [Operator Console](../interfaces/operator-console-ko.md) |
| 로컬 및 deployed 프로바이더 동등성 | [런타임 동등성](../deployment/dev-and-deploy-parity-ko.md) |
