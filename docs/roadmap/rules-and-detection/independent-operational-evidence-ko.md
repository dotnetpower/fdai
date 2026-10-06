---
translation_of: independent-operational-evidence.md
translation_source_sha: 1f748bc60fffbb6d61c3dc503cd4f9b420ddcd07
translation_revised: 2026-10-05
---
# 독립 운영 근거 발급

이 설계는 통제된 테스트 맥락, 예측 개입 이력, 사례 이력 재사용에 쓰이는 의사결정 근거를 FDAI가 출처를
인증해 독립적으로 발급하는 방법을 정의합니다. 별도의 읽기 전용 검증기 워크로드가 자체 신원으로 권한 있는
각 출처를 읽고 본문을 담지 않은 증명을 발급하며, 기존 경계 소유자는 변경되지 않은 검증 증적 조회 경로로
이 증명을 계속 사용합니다.

> **상태:** 일부 구현되었습니다. 소유자가 2026-09-28에 [#1022](https://github.com/dotnetpower/fdai/issues/1022)
> 종료 조건 1에 대한 설계 검토를 마쳤으며, 내용은 [검토 결정](#검토-결정)에 있습니다.
> 검증기 엔진, 발급 경로, 고정된 신뢰 레지스트리와 사례 범위 권한 부여 레지스트리, 삽입 전용 증명 저장소,
> Operator 인증 증적, 세 가지 테스트 맥락 재확인, 연결되지 않은 사례 이력
> 재확인 모듈, 모든 소비 소유자의 유형별 기록, Settings 준비 상태 관측, 선택형 배포 검증기 워크로드 렌더러,
> 검토된 독립 실행형 배포 입력이 구현되어 로컬 검사를 통과합니다. [구현 참고 사항](#구현-참고-사항)을
> 확인하세요. 연결된 배포 검증기 시작은 아직
> 관측되지 않았으며, 출처 재확인이 연결되지 않은 예측 목적은 `unavailable` 상태를 유지합니다.
>
> **에이전트 경계:** 판테온은 정확히 15개 에이전트로 유지합니다. 이 설계는 에이전트나 토픽을 추가하지 않고,
> 어떤 에이전트의 `owns`나 `subscribes`도 바꾸지 않으며, 실행 권한이나 승격 권한을 부여하지 않습니다.

## 설계 요약
대화 모델 호출 수, 토큰 사용량, 로컬 호출별 시간은 진단 메타데이터입니다. 검증 증적을
발급하거나 출처 재확인을 대체하거나 운영 근거를 입증하거나 사람의 인가를 증명할 수
없습니다. 숫자 사용량 계측을 추가해도 이 검증기 경계는 바뀌지 않습니다.

여덟 개 판단 영역에 걸친 목적 id 열한 개는 이미 정확한 `DecisionEvidenceAdmission`(다섯 가지 독립 증명을
거친 뒤에만 생기는, 권한 없는 단기 적격성 기록)을 요구하지만 이를 발급하는 곳이 없습니다. 자체 워크로드
신원을 가진 비에이전트 검증기가 이 공백을 메웁니다. 검증기는 형식이 정해진 위치 지정자가 가리키는 권한
있는 출처를 읽고, 소비자의 digest를 다시 계산하고, 완전성, 충돌 부재, 최신성, principal 권한을 증명한 뒤
자신만 쓸 수 있는 저장소에 검증 증적이나 유형이 지정된 거부 기록을 씁니다. 소유자는 변경되지 않은 `admit`
메서드로 검증 증적을 읽고 모든 거부 유형을 명시적으로 기록하며, `unavailable`일 때만 현재의 일반 보류를
유지합니다.
의미 결과 핸들 참조는 Operator/Core 의미 전송의 본문 없는 대화 연속성 레코드입니다. 운영 근거를
수락하거나 검증기 재확인을 충족하거나 실행 권한을 부여하지 않습니다.
봉인된 Core 전용 행 신원은 후속 읽기의 재인가 피연산자일 뿐이며, 검증기 출처 산출물, 수락 기록 또는
증명 자료가 아닙니다.
기준선 평가 터미널 기록도 같은 근거 경계를 사용합니다. Rule별 결과와 세대별 완료 계약은 Forseti 평가
증적과 Saga 감사 기록을 참조할 수 있지만, 계약 자체는 독립 운영 근거를 발급하거나 검증기를 배포하거나
실제 공급자 상태를 증명하지 않습니다.
Resource Health 서술 주장은 타입이 지정된 읽기 증적에 붙는 답변 검증 동반 자료입니다.
표현 전에 서술을 보존하거나 거부할 수 있지만, 독립 운영 근거 검증기의 수락 기록이 아니며
거버넌스가 적용되는 어떤 의사결정 출처도 충족할 수 없습니다.
Forseti는 Var와 HIL 재개 경로가 원래 정족수와 유효 정족수를 기록할 수 있도록 고정된 단독
운영자 승인 프로필 개정을 Verdict에 실어 보낼 수 있습니다. 이 프로필 메타데이터는 승인 문맥일
뿐입니다. 검증기 출처 산출물, `DecisionEvidenceAdmission`, 실제 프로바이더 상태의 증명이 아닙니다.
재정의 승격 중 기록된 운영자 증언 게이트 스냅샷도 레지스트리 문맥입니다. 이 검증기 경계 아래에서
별도의 gate-evidence 저장소가 스냅샷을 검증하기 전에는 독립 운영 근거가 되지 않습니다.

## 현재 상태와 공백

Core 경로는 `services/core-control-plane/src/fdai/` 기준이며, 그 밖의 경로는 리포지토리 루트 기준입니다. 이
섹션은 검토 당시 설계가 메우려던 공백을 기록하며, 현재 구현된 내용은 [구현 참고 사항](#구현-참고-사항)에서
설명합니다.

- **소비자는 이미 있습니다.** 아래의 모든 경계는 `shared/providers/decision_evidence_verifier.py`의
  `assess_decision_evidence_admission`을 호출합니다. 검증 증적이 없으면 `context_admission_required` 같은 일반
  사유로 보류하므로 충돌과 장애를 구분하지 못합니다.
- **운영 근거를 발급하는 곳이 없습니다.** `StateStoreDecisionEvidenceAdmissionProvider`,
  `AzureBlobDecisionEvidenceAdmissionProvider`, `AzureManagedIdentityDecisionEvidenceVerifier`는 보존된 기록이나
  미리 만든 증명을 읽기만 합니다. 유일한 발급 경로는 `config/decision-evidence-deployment-policy.json`으로
  `deployment-apply`에 묶여 있고 증명을 직접 만들므로 이런 출처를 인증할 수 없습니다.
- **게이트는 두 신원만 봅니다.** `DecisionEvidenceReadinessGate`는 `source_identity`나 `producer_id`와 같은
  검증기만 거부하고 검토자나 실행기는 보지 못하며, 보존된 검증 증적의 바인딩 철회도 다시 확인하지 않습니다.
- **Core는 자신을 검증할 수 없습니다.** Core 앱은 실행기 Managed Identity(`infra/main.tf`의
  `module "identity"`)로 실행되므로, 프로세스 내부 검증기는 생산자 및 실행기와 신원을 공유하게 됩니다.

## 검증기 워크로드와 신원 분리

검증기는 전용 사용자 할당 Managed Identity를 사용하는 내부 전용 결정론적 서비스입니다. 모델을 호출하지
않으며 에이전트도 아닙니다. 인벤토리 프로젝터처럼 자신의 비에이전트 영속 출력인 운영 증명 저장소만
소유합니다. 어떤 토픽도 게시하거나 구독하지 않고 판단, 승인, 실행, 승격을 하지 않으며, 검증하는 어떤
출처에도 쓰기 역할을 갖지 않습니다.

| 역할 | 현재 신원 | 분리 규칙 | 강제 방식 |
|------|-----------|-----------|-----------|
| 출처 | Operator API 신원(명령 발신함), Core 런타임 신원(StateStore 개정과 해시 체인 `audit_log`), 인벤토리 신원(저널과 incarnation 원장), Azure 플랫폼(메트릭, Resource Graph, Activity Log), 고정된 operating-intent 출처 | 각 출처를 자체 읽기 전용 역할로 읽고, 출처 쓰기 역할은 절대 갖지 않음 | 레지스트리 출처 앵커를 시작 시와 발급마다 비교하고 역할을 재조회 |
| 생산자 | 요청 경계를 호스팅하는 Core 런타임 신원 | 레지스트리가 해당 목적에 등록했고 호출자 신원이 그 앵커와 일치할 때만 주장된 생산자를 수용함. 생산자 선택은 어떤 권한도 부여하지 않음 | 근거 증적의 `producer_id`는 `verifier_id`와 다르며, 호출자 토큰은 검증 후 폐기 |
| 검토자 | Var가 전달하는, 인증된 사람 Approver 또는 Owner | 워크로드는 검토자가 될 수 없고, 검토자 subject는 요청자 subject와 달라야 함 | 표시 문자열이 아닌 Operator 기록의 subject id를 사용 |
| 실행기 | 모든 실행기 계열 신원: Core 런타임(실행기) 신원, 격리 실행기, 개발 운영 게이트웨이 실행기, 수직 영역 효과 실행기(`infra/main.tf`의 `effect_executor_principal_ids`), 배포 러너 | 리소스 쓰기 역할, 실행기 자격 증명, DSN의 정확한 시크릿 읽기와 정확한 레지스트리 pull을 제외한 Azure 데이터 플레인 역할 없음 | 사전 점검에서 모든 실행기 계열 신원으로 앵커 집합을 만들고, 검증기는 같은 신원이 있으면 시작을 거부하며 자신의 역할 할당을 다시 읽어 vault 전체, 리소스 그룹 전체, 구독 전체, 다른 시크릿, 쓰기, 관련 없는 데이터 플레인 역할을 거부 |

검증기는 토큰을 보존하지 않고 출처를 인증합니다.

- **워크로드 토큰.** 수명이 짧은 Managed Identity 토큰은 범위가 제한된 한 번의 읽기 동안에만 메모리에
  머물며 증명, 기록, 로그, 메트릭, 오류, 응답에 남지 않습니다. `AzureManagedIdentityDecisionEvidenceVerifier`와 같은 방식입니다.
- **출처 산출물.** 검증기가 출처 소유자만 쓸 수 있는 저장소에서 자체 신원으로 산출물을 읽고, 그 digest나
  체인(예: `delivery/persistence/postgres.py`의 해시 체인 `audit_log`)을 검증한 뒤에만 산출물로 인정합니다.
  생산자 외부에서 비롯된 사실은 다른 신원이 쓰는 출처로도 교차 확인합니다. Core 상태 복사, 호출자 신원
  해싱, `deployment-apply` 근거 재사용은 인증으로 인정하지 않습니다.
- **사람 principal.** 검증기는 나중에 사람을 다시 인증하지 않습니다. 대신
  `services/operator-service/src/fdai_operator_service/auth.py`의 `OperatorAuthenticator`가 토큰을 검증할 때
  보존하게 될 본문 없는 인증 증적을 읽습니다. 여기에는 발급자, 대상, 테넌트 digest, subject, principal 종류,
  초과(overage) 없음 표시가 붙은 정확한 그룹 id, 토큰 식별자 digest, 발급 및 만료 시각, 확인된 역할, 역할 매핑
  개정이 담깁니다. 토큰은 보관하지 않고, 로컬 CLI 세션의 증적은 `local-loopback`이며, 이 증적은 선행 조건입니다.
  검증에 성공하면 요청에 사용권 표시용 표식도 남기지만, 이 표식은 증적에 필드를 더하지 않고
  권한도 부여하지 않습니다.

## 발급 경로와 증명 형식

1. **요청.** 경계 소유자는 `admit`에 전달하는 것과 같은 조회 튜플
   `(evidence_digest, scope_digest, purpose_id, source_revision)`과 좌표만 담은 출처 위치 지정자를 새
   `OperationalEvidenceIssuer` 공급자 주입 지점으로 한 번의 제한된 호출에 담아 보냅니다. 이는 에이전트
   호출이 아니라 공급자 호출입니다.
2. **재조회.** 검증기는 고정된 신뢰 레지스트리에서 목적을 확인하고, 주장된 생산자를 검사하고, 선언된 모든
   출처를 읽은 뒤 소비자 자신의 순수 정규화 함수로 근거 digest를 다시 계산합니다. digest가 다르면 이를
   보정하지 않고 `evidence_mismatch`로 처리합니다.
3. **발급 또는 거부.** `DecisionCriticalEvidenceReceipt`, 증명 다섯 개, `DecisionEvidenceVerificationBundle`을
   만들어 `core/readiness/decision_evidence.py`의 `DecisionEvidenceReadinessGate`로 평가한 뒤, 검증 증적 또는
   실패한 유형을 담은 거부 기록을 생성 전용으로 씁니다. 본문 없는 응답에는 상태와 그 기록의 digest만 담습니다.
4. **수용.** 소유자는 변경되지 않은 `admit`을 호출하고, 운영 검증 증적 공급자는
   `parse_decision_evidence_record`로 기록을 검증하며 바인딩과 분리 앵커를 다시 확인합니다. 검증 증적이
   없으면 `outcome`은 이번 시도의 응답이 지목한 거부 기록만 받아들이며, 같은 조회의 이전 거부 기록을 포함한
   그 밖의 모든 경우는 `unavailable`입니다.

요청은 소비자의 5초 기한 안에서 제안된 2초 제한을 사용하며, 시간 초과, `429`, `503`은 재시도 없이
`unavailable`로 끝납니다. 진행 중인 중복 요청만 병합합니다. 현재 검증 증적은 재사용할 수 있지만 거부 기록은
재사용하지 않으므로, 새 시도마다 새 결과를 받습니다.

각 소유자는 이미 쓰는 기록에 유형을 남기고 거부 기록 digest를 인용합니다. Forseti의 보류 사유, Thor의
디스패치 보류, Mimir의 전이 거부 감사, Heimdall의 채점 제외(새 `ForecastOutcome` 마이너 버전), T1 사유 코드,
Pattern 읽기 상태가 여기에 해당합니다. `conflicting`은 항상 자율성을 낮추는 명시적 충돌로 소유자에게
전달되며, `unavailable`만 현재의 일반 사유를 유지합니다.

| 근거 증적 필드 | 검증기가 도출하는 값 |
|----------------|----------------------|
| `authority_class`, `method_*`, `freshness_policy_*` | 요청이 아니라 해당 목적의 고정된 레지스트리 항목 |
| `source_identity`, `producer_id`, `producer_version` | `operator-service.test-context-outbox` 같은 논리적 출처 id와 등록된 생산자 |
| `evidence_digest`, `scope_digest`, `source_revision` | 다시 계산한 뒤에만 수용하는 소비자의 정확한 조회 값 |
| `authentication_evidence_digest` | 출처 산출물 신원, 작성자 앵커 바인딩, 사람 인증 증적, 일치한 권한 부여 개정 |
| `completeness_evidence_digest` | 필수 구성 요소, 체크포인트, 워터마크, 종료 커서, 검증된 체인 경계 |
| `conflict_evidence_digest` | 비교한 출처와 그 일치 여부. 불일치가 하나라도 있으면 근거 증적은 `conflicting`이 됨 |
| `provenance_digest` | 위치 지정자 digest, 출처 기록 참조, 출처 개정, 두 레지스트리 개정 |
| `event_at`, `evidence_cutoff`, `fresh_until` | 출처 이벤트 시각, 각 영역 표에 적힌 기준 시점, 기준 시점에 레지스트리 상한을 더한 값 |
| `completeness_basis_points`, `conflict_status`, `synthetic` | 발급하는 모든 검증 증적에서 `10000`, `clear`, `false` |

각 증명의 `subject_digest`는 `expected_verification_subjects`를 통해 해당 근거 증적 필드와 같습니다. 묶음의
`valid_until`은 `fresh_until`, 바인딩의 `valid_until`, 영역별 상한 중 가장 이른 값이므로,
`_validate_relations`가 요구하는 대로 보존된 검증 증적의 유효 구간은 묶음의 유효 구간과 같습니다. 실패한
유형은 발급된 근거 증적이 아니라 거부 기록을 남깁니다.

운영 증명 저장소는 두 환경 모두에서 삽입 전용 PostgreSQL 테이블 집합이며, `deployment-apply` 컨테이너와
Core 상태 저장소와 분리됩니다.

- **배치.** 인증 증적, 재확인 기록, 묶음, `<registry-pins>/<lookup>/<reverse-time>-<receipt>` 키를 쓰는
  발급 기록, 같은 키 형태의 거부 기록을 각각 별도 테이블에 둡니다. 발급마다 키가 다르므로 변경 불가능한
  기록을 덮어쓰지 않고도 만료 후 같은 조회를 다시 발급할 수 있습니다.
- **거부 기록.** 거부 기록에는 본문이 없으며 시도 id, 조회 digest, 목적, 유형,
  `LiveEvidenceClaimRejectionReason`, `DecisionEvidenceReadinessReason`, 또는 재확인의 고정 코드 집합에서 나온
  사유 코드, 충돌 근거 digest, 고정값, 검증기 id와 버전, 기록 시각, 해당 시도에만 적용되는 고정 60초
  `valid_until`을 담습니다.
- **고정값과 읽기.** `<registry-pins>`는 기록의 근거가 된 신뢰 레지스트리와 권한 부여 레지스트리 개정을 나타냅니다.
  소비자는 현재 고정값이나 철회 개정이 폐기하지 않은 이전 고정값 아래에서 조회마다 최신 기록을 최대 두 개만
  읽으며, 어느 기록도 다른 기록의 유효 기간을 늘리지 않습니다.
- **작성자.** 쓰기는 검증기의 데이터베이스 역할만 할 수 있으며, 이 역할은 `UPDATE`나 `DELETE` 없이
  `INSERT`만 가집니다. 소비자 역할은 `SELECT`만 가지고, 배포 러너와 마이그레이션 역할에는 런타임 데이터
  역할이 없으며, 기록은 변경할 수 없습니다. 준비 상태 점검은 테이블 권한과 역할 멤버십을 다시 읽고, 다른
  역할이 쓸 수 있으면 `self_verified`를 보고합니다.
- **로컬 환경.** 작성자 역할과 읽기 역할을 분리한 같은 삽입 전용 테이블을 루프백 PostgreSQL에서
  실행합니다. 로컬 검증기는 실제 로컬 출처를 읽으며, 공급자 기반 목적은 사용할 수 없는 상태로 남습니다.

## 신뢰 레지스트리와 목적 매핑

고정되고 검토된 신뢰 레지스트리가 목적별 근거 계약을 정의합니다. 업스트림 파일(제안:
`config/operational-evidence-trust-registry.json`)에는 논리 식별자만 두고, 배포 구성이 신뢰 앵커를 워크로드
principal과 증명 저장소 주소에 바인딩합니다. 이런 값은 리포지토리에 절대 들어가지 않습니다.

| 항목 필드 | 의미 |
|-----------|------|
| `purpose_id`, `authority_class`, `method_*` | 목적 id 열한 개 중 하나와 그 재조회 계약. 어떤 목적도 다른 목적을 대신하지 못함 |
| `producers`, `sources` | 등록된 요청 경계, 권한 있는 출처와 교차 확인 출처, 각각의 앵커 |
| `freshness_policy` | 정책 id, 버전, 상한. 이 정책의 digest가 최신성 정책 증명의 대상 |
| `verifiers` | 하나 이상의 바인딩. 각 바인딩에는 `verifier_id`, `verifier_version`, `trust_anchor_id`, `valid_from`, `valid_until`, `revoked`가 있으며, 교체 시 기존 바인딩 옆에 새 바인딩을 추가함 |
| `separation` | 검증기와 달라야 하는 출처, 생산자, 검토자, 모든 실행기 계열 앵커 |
| `evidence_class` | 배포 환경에서는 `live`이며, 로컬 환경 밖에서는 `local-loopback` 앵커를 거부 |

- **검토와 적재.** 개정은 내용 주소로 식별하며, 검토 후
  [operating-intent 출처](../architecture/operating-intent-source-ko.md)처럼 대역 외에서 고정합니다. 작성자와
  검토자는 서로 다른 사람이어야 하며, 전체 권한 개발 프로필의 단일 Owner만 둘을 겸하고 개발 전용으로 기록합니다.
  검증기와 모든 소비자는 같은 고정값을 적재하며, digest 불일치, 알 수 없는 필드, 중복 키, 누락된 앵커가 있거나
  검증기 신뢰 앵커가 생산자, 출처, 분리 앵커로도 쓰이면 해당 목적을 사용할 수 없습니다. 따라서 신원 분리 검사는
  검증기 바인딩만 쓰는 앵커만 건너뜁니다.
- **교체와 철회.** 적재기는 각 개정을 이름표가 아니라 내용으로 분류합니다. 바인딩, 권한 부여, 목적, 사례 범위에
  대한 제거, 축소, 유효 기간 단축, `revoked` 표시가 하나라도 있으면 철회 개정이며, 작성자는 항목을 삭제하지 않고
  철회합니다. 철회 개정은 이전 고정값 아래에서 사용 중인 검증 증적을 폐기하고(경계가 다시 요청함), 일치했던
  바인딩이나 권한 부여를 철회한 계보를 끝냅니다. 대체할 검증기 버전 옆에 새 버전을 추가하는 것 같은 그 밖의 변경은
  일상적 교체이며 이전 기록을 만료될 때까지 유효하게 둡니다. `admit`은 매번 바인딩을 다시 확인하며, 검증기를 0으로
  축소하면 새 발급이 멈춥니다.
- **기능 상태.** 각 목적은 기존 기능 및 설정 화면에서 `available`, `enabled`, `mode`와 선행 조건을
  보고합니다. 레지스트리, 검증기 바인딩, 작성자 재조회, 선언된 모든 출처가 바인딩되고 정상일 때만
  `available`이며, 사용 가능 여부는 어떤 권한도 부여하지 않습니다.

## Principal-사례 범위와 목적 바인딩

권한 부여는 digest 간의 일치가 아니라 명시적으로 검토된 기록입니다. 배포가 소유하는 사례 범위 권한 부여
레지스트리는 신뢰 레지스트리처럼 고정되고 철회되며, 세 부분으로 구성됩니다.

- **사례 범위.** 불투명한 각 `access_scope_digest`와 그 리소스 선택자, 허용 목적, 현재 검토된 테스트 맥락
  `policy_revision`입니다.
- **Principal 권한 부여.** 그룹 또는 앱 역할 선택자(표시 이름이나 이메일은 쓰지 않음), 사례 범위, 작업
  (`test-context.propose`, `test-context.review`, `test-context.revoke`, `case-history.read`), 목적, 유효
  기간, 검토자, 철회 상태입니다.
- **재사용 권한 부여.** 불변 사례를 지정된 대상 범위의 이벤트에 재사용할 수 있는 사례 범위입니다.

검증기는 subject, principal 종류, 정확한 그룹을 Operator 인증 증적에서만 가져오고, `principal_groups`가 다른
맥락은 거부하며, 정확한 사례 범위, 작업, 목적에 대한 현재 권한 부여를 요구합니다. 일치하는 권한 부여가
철회되었거나 만료되었으면 거부하며, 겹치는 권한 부여로 범위가 넓어지지는 않습니다.
`principal_scope_digest`, `access_scope_digest`를 비롯한 모든 digest는 불투명한 값이며, 값이 같다고 권한이
생기지 않습니다. 대상은 검토된 운영 범위에서 해당 사례 범위에 속해야 하고, 명령의 `policy_revision`은 범위에
고정된 개정과 같아야 합니다. 이 권한 부여의 읽기 전용 Operator 투영이
[#1023](https://github.com/dotnetpower/fdai/issues/1023)에 필요한 서버 소유 선택지를 제공하며, 브라우저 입력은
범위를 선택하지 못합니다.

## 출처별 설계

각 하위 절은 소비자, 정확한 조회(범위 값은 `sha256:` 접두사를 유지), 다섯 가지 재조회 증명을 정리합니다.
최신성 상한은 검토를 위한 제안값입니다.

### Operator 테스트 맥락 명령

소비자: Var와 Mimir가 사용하는 `core/operational_context/test_context_commands.py`의
`TestContextCommandHandler.validate`입니다. 조회: `content_digest(TestContextCommand)`, 요청 범위,
`operator-test-context-command`, 요청 `policy_revision`.

| 증명 | 재조회 대상 |
|------|-------------|
| 인증 | 테스트 맥락 명령 행으로 제한한 뷰로 읽은, 멱등성 키에 해당하는 Operator 발신함 기록. `principal_kind=human`, `principal_id`와 같은 `scope.subject_id`, `accepted_at` 시점에 유효한 인증 증적 |
| 근거 | `services/operator-service/src/fdai_operator_service/test_context_runtime.py`의 `command_from_record`와 같은 규칙으로 다시 만든 명령이 조회와 일치하고, 권한 부여가 해당 작업을 허용하며, 대상이 범위 안에 있음 |
| 완전성 | 키마다 기록이 정확히 하나이고, `request_digest`가 일치하며, 권한 부여와 범위 개정이 완전하고, 거부된 전달 상태가 없음 |
| 충돌 | 같은 키에 다른 digest를 가진 두 번째 기록이 없고, 철회된 권한 부여나 대체된 정책 개정이 없음 |
| 최신성 정책 | `accepted_at`부터 600초. 더 오래된 명령은 다시 제출해야 함 |

### 테스트 맥락 전이

소비자: `core/operational_context/test_context_lifecycle.py`의 `GovernedTestContextStore._record`이며, Mimir는
compare-and-set(CAS) 쓰기 전에 발급을 요청합니다. 조회: 진술 digest와 이전 digest를 묶은 digest, 진술 범위,
`test-context-transition`, 진술 `policy_revision`.

| 증명 | 재조회 대상 |
|------|-------------|
| 인증 | 전이를 일으킨 Operator 명령과, 검토나 철회라면 원래 제안 명령. 각 행위자는 자신의 작업에 대한 권한 부여를 가지며, 검토자 subject는 요청자 subject와 다름 |
| 근거 | 명령과 이전 개정으로 다시 만든 진술과 전이 digest가 조회와 일치함 |
| 완전성 | 범위와 대상의 전체 `test-context-target:v1` 이력을 저장소 자체의 체인 규칙으로 검증하고, 각 개정을 원자적 감사 항목 및 인증된 Operator 명령과 대응시킴 |
| 충돌 | 같은 신호에 겹치는 검토 완료 진술이 없고, 두 번 읽는 사이 저장소 개정이 바뀌지 않았으며, 같은 키를 두고 경쟁하는 명령이 없음 |
| 최신성 정책 | 저장소를 읽은 시점부터 120초. 검토는 진술의 `effective_to`로도 제한됨 |

### 현재 테스트 맥락

소비자: `agents/_framework/forseti_judgment.py`에서 `evaluate_test_context`를 사용하는 Forseti와
`TestContextDispatchGuard.current`를 사용하는 Thor입니다. 조회: 진술 digest, 범위, `operational-test-context`,
진술 `policy_revision`. 두 소비자 모두 최신 읽기 확인을 유지하므로 이후의 철회가 판단과 디스패치를 보류시킵니다.
철회로 아래 계보가 폐기되면 맥락은 보류됩니다. 수명 주기가 두 번째 검토를 허용하지 않으므로, 다시 증명하려면
맥락을 철회한 뒤 새로 제안해야 합니다.

| 증명 | 재조회 대상 |
|------|-------------|
| 인증 | 현재 바인딩에서 출처로부터 다시 검증함: 검토 완료 개정의 체인과 원자적 감사 항목, 두 수명 주기 명령. 인용된 `test-context-transition` 검증 증적은 계보이며, 고정값 이력에서 그 바인딩과 그것이 일치시킨 모든 권한 부여가 `verified_at`부터 현재 고정값까지 존재하고 철회되지 않았을 때만 인정됨 |
| 근거 | 맥락의 현재 개정이 진술과 같고, `reviewed` 상태이며, 평가 시점을 포함하고, 대상이 여전히 범위 안에 있음 |
| 완전성 | 대상의 전체 이력에 이후 개정이나 미래 시각으로 기록된 개정이 없음 |
| 충돌 | 대상과 신호에 대해 활성 검토 완료 진술이 정확히 하나임 |
| 최신성 정책 | 저장소를 읽은 시점부터 300초이며 `effective_to`로 제한됨 |

### 테스트 관측

소비자: 검토된 예상 범위 안에 이미 들어온 신호에 한해 `evaluate_test_context`를 사용하는 Forseti입니다.
조회: `observation_context_digest`, 범위, `operational-test-observation`, 진술 `policy_revision`.

| 증명 | 재조회 대상 |
|------|-------------|
| 인증 | 검증기 자체 읽기 신원으로 수행한 공급자 재조회. 이벤트 페이로드의 값은 신뢰하지 않음 |
| 근거 | 정확한 대상, 메트릭, 차원, 집계, `observed_at`에 대한 공급자 표본이 `observed_value`와 같음. 검토된 운영 범위의 모든 운영 환경 의존성이 바인딩된 상태 출처에서 정상일 때만 `service_impact=none`이며, `protected_signal`은 현재 정책 개정에서 가져옴 |
| 완전성 | 대상이 범위 안에 있고, 단일 시계열이 정확한 구간에 표본을 가지며, 매핑되지 않은 의존성이 없고(`OperatingScopeCoverage.complete`), 모든 의존성에 상태 관측이 있음 |
| 충돌 | 충돌하는 표본, 시계열, 상태 출처가 없음 |
| 최신성 정책 | 공급자를 읽은 시점부터 300초 |

**출처 바인딩.** `core/operational_evidence/readback/test_observation.py`는 검증기 쪽
`OperationalTestObservationReadback`을 제공합니다. 검증기 workload는 배포 환경에서만 이 목적을 바인딩하며, 배포
구성은 세 가지 출처 계약을 모두 제공해야 합니다. Log Analytics workspace, 검토된 KQL metric template, 검토된 운영
범위 관측 행입니다. `delivery/azure/operational_evidence_readbacks.py`는 검증기 소유 Azure Monitor Logs metric
provider를 정확한 구간 표본 reader로 감싸고, 검토된 운영 범위 reader와 결합합니다. 배포된 검증기 신원은 구성된
resource group 범위에서 `Monitoring Reader`를 가져야 하며, own-role 재조회는 이 역할이 생산자, 검토자, 실행기 신원과
분리되어 있음을 확인한 뒤에만 목적을 available로 만듭니다. metric 구성 누락, 범위 행 누락, 배포 환경의 local-loopback
출처, 충돌하는 표본, 불완전한 의존성 상태, protected signal은 모두 유형화된 거부로 fail-closed 처리됩니다.

### 출처별 예측 이력

소비자: `delivery/persistence/state_store_forecast_context.py`에 있는 Heimdall의
`StateStoreForecastContextProvider._require_admission`입니다. 출처별 조회: 출처별 이력 digest, 접근 범위,
`forecast-history-<kind>`, 출처별 이력 `source_revision`.

| 종류 | 권한 있는 출처 | 독립 교차 확인 | 완전성 요건 |
|------|----------------|----------------|-------------|
| `actions` | Thor가 소유한 ActionRun 기록과 해시 체인 감사 항목 | 대상에 대해 실행기 신원이 수행한 Activity Log 작업 | 사전 조회 구간(lookback) 이전부터 horizon 종료와 grace 이후까지 이어지는 검증된 감사 구간 |
| `changes` | `delivery/forecast_change_history.py`의 계약으로 읽는 인벤토리 관측 저널 | 검증기 신원으로 읽은 Resource Graph 변경 기록과 Activity Log 기록 | 긍정적 시작 체크포인트, 종료 커서, horizon 종료를 넘는 워터마크, 보존 기간 안의 공급자 이력 |
| `resource_lifecycle` | `core/ontology_platform/operational_history_lifecycle.py`의 확정 tombstone incarnation 원장 | 구간 양 끝의 공급자 존재 및 삭제 기록 | 확립된 초기 상태와 구간 전체를 덮는 incarnation 경계 |
| `excluded_windows` | 개정 이력이 있는 `ChangeWindow` 이력 | 각 구간을 선언한 고정된 operating-intent 출처 개정 | 전체 구간을 덮는 개정 이력 |

모든 종류에서 근거 증명은 다시 계산한 출처별 이력 digest이고, 충돌 증명은 교차 확인 출처와의 불일치나 같은
시각의 충돌 기록을 다루며, 최신성은 출처 워터마크부터 3,600초이되 출처별 이력의 `valid_until`을 넘지
않습니다. 범위 소속은 `FDAI_FORECAST_TARGETS_JSON`이 아니라 검토된 운영 범위에서 가져옵니다. 원본 이력
생산은 계속 [#1021](https://github.com/dotnetpower/fdai/issues/1021) 범위이며, 구현되지 않은 출처에는 발급하지
않습니다.

**설계 참고: `forecast-history-actions`.** 작업 생산자는 기존 Thor/Saga StateStore 감사 체인을 읽지만 Thor,
Saga, 검토자, 실행자가 되지 않습니다. 고정 매개변수 `SECURITY DEFINER` 함수는 요청 구간의 각
`thor.action-run-save` 행에 대한 해시 앵커를 반환하고, 대상이 검토된 대상과 정확히 일치할 때만 연결된 ActionRun
페이로드를 노출합니다. 출처 어댑터는 출처 기록을 만들기 전에 연속된 시퀀스 번호, `previous_hash`와 `entry_hash`
일치, 워터마크까지 다시 계산한 감사 해시를 요구합니다. 검토된 매핑은 `succeeded`, `failed` 같은 최종 ActionRun
상태를 예측 작업 상태로 변환할 수 있습니다. 간격, 해시 불일치, 대기 중인 최종 상태, 매핑되지 않은 상태, 오래된
관측 범위, 결과 제한, 대상 불일치는 출처별 검증 증적이 발급되기 전에 불완전하거나 충돌하는 출처 관측으로 차단됩니다.

**비평.** ActionRun 페이로드를 `state_kv`에서 직접 읽으면 Core 상태가 과도하게 노출되고 최신 값만 증명합니다. 대상
행만 읽으면 부재가 완전하다는 점을 증명하지 못합니다. 수정된 reader는 해시 앵커와 페이로드 공개를 분리합니다. 모든
작업 저장 행은 시퀀스와 해시 연속성에 기여하고, 정확한 대상의 행만 기록 생성에 필요한 상태 페이로드를 반환합니다.
이 방식은 실행 권한을 부여하지 않고 Thor 또는 Saga 소유권도 바꾸지 않습니다.

**수정.** 첫 구현은 `forecast-history-actions`를 `fdai.thor_saga_state_store.action_audit` 출처와
`forecast-action-audit-chain.v1` 개정에 바인딩하고, 검증기 역할에는 함수 `EXECUTE`만 부여합니다. Activity Log는
교차 확인 준비 상태로 남습니다. `forecast-history-excluded_windows`는 revision이 있는 `ChangeWindow` 이력 생산자가
생길 때까지 계속 사용할 수 없습니다.

**설계 참고: `forecast-history-excluded_windows`.** 기존 operating-intent 출처가 계속 `ChangeWindow` 객체의 유일한
권한 있는 출처입니다. 이 경로는 성공적으로 admission을 기록할 때마다 인정된 모든 `ChangeWindow` 객체에 대해
append-only 이력 행을 기록합니다. 키는 출처 개정과 window id에서 결정적으로 만듭니다. 각 행에는 window id, 범위나
대상 참조, 상태, 구간 종류, 유효 구간, 출처 개정, 문서 digest, 기록 시각, 같은 window의 직전 보존 개정을 가리키는
supersedes 참조, 그리고 전체 인정 출처 문서의 워터마크가 들어갑니다. 별도의 출처별 관측 범위 행은 출처 개정, 문서
digest, 검증 시각, 객체 수, 워터마크를 기록합니다. 따라서 forecast 생산자는 보존된 행이 부분적인 현재 graph 읽기가
아니라 완전한 인정 출처에서 왔음을 증명할 수 있습니다.

**비평.** `OntologyChangeWindowEvidenceProvider.is_active`나 최신 ontology 객체 revision을 재사용하면 여전히 이력을
꾸며 내게 됩니다. 현재 활성 여부만 답할 수 있고 forecast lookback 전체에서 철회, 대체, 부재가 어땠는지 증명할 수
없기 때문입니다. 새 소유자를 만들어 이력을 쓰면 권한이 바뀝니다. 안전한 이음매는 기존 operating-intent admission
경로입니다. 이 경로는 이미 고정된 출처, 출처 digest, rollout 세대, 소유 객체 집합을 검증했습니다. 이력 writer는
권한에 대해 읽기 전용입니다. admission 경로가 성공한 뒤 근거를 기록하며, 이력 보존 실패가 `ChangeWindow` 권한을 더
허용적으로 만들지는 않습니다.

**수정.** `forecast-history-excluded_windows`는 출처 ID `fdai.operating_intent.change_window_history`와 개정
`forecast-change-window-history.v1`에 바인딩됩니다. 출처 어댑터는 append-only 보존 이력을 읽고, 정확한
operating-intent 출처 개정과 일치하는 관측 범위 워터마크를 요구하며, 초기 상태가 있는 included/excluded 상태 체인을
도출합니다. 관측 범위 누락, 대체 관계 충돌, 같은 시각의 상태 충돌, 오래된 워터마크, 불완전한 페이지는 fail-closed로
처리됩니다. 이 네 번째 출처별 이력이 인정되면 `forecast-context`는 같은 범위, 대상, 구간에 대한 네 개의 출처별
검증 증적을 모두 요구하는 기존 집계 규칙을 통해 바인딩될 수 있습니다.

### 예측 맥락 집계

소비자: 보존에 쓰는 `StateStoreForecastContextProvider._retain`과 채점에 쓰는
`core/detection/forecast_context.py`의 `ContextualForecastObservationProvider._join_context`입니다.
조회: 집계 digest, 범위, `forecast-context`, 집계 `source_revision`.

| 증명 | 재조회 대상 |
|------|-------------|
| 인증 | 같은 범위, 대상, 구간에 대해 이 바인딩으로 발급된 현재 출처별 검증 증적 네 개. 집계는 이를 대신하지 못함 |
| 근거 | `_retain`과 같은 집계 규칙으로 다시 만든 집계가 조회와 일치함 |
| 완전성 | 네 종류가 모두 있고 완전하며, 정정은 정확한 현재 선행 개정을 지정함 |
| 충돌 | 출처별 이력 사이에 신원이나 구간 불일치가 없음 |
| 최신성 정책 | 가장 오래된 출처별 기준 시점부터 3,600초이며, 어떤 출처별 검증 증적의 유효 기간도 넘지 않음 |

### 사례 이력 읽기

소비자: `query.operating_patterns`를 처리하는 `core/ontology_platform/pattern_queries.py`의
`OperatingPatternQuery._read`입니다. 조회: 인자와 `FunctionInvocationContext`의 digest, principal 범위와 사례
범위와 목적의 digest, `case-history-read`, 활성 온톨로지 릴리스 digest.
조회가 릴리스 digest를 묶으므로 운영 근거 밖의 온톨로지 함수 소스 수정을 포함한 모든 릴리스 변경은 새 조회를
시작하고, 이전 릴리스에서 발급한 증적은 다시 쓰지 않습니다. 같은 변경에서 원본에 묶인 의미 보증 코퍼스도 다시
생성합니다. 소스에서 파생되는 `query.resource_health_inventory` FunctionType을 수정하는 것도 이러한 릴리스 변경입니다.
변환 전용 온톨로지 어휘는 릴리스 digest나 운영 근거 조회 권한을 바꾸지 않고도 해당 corpus
매니페스트의 원본 다이제스트를 갱신할 수 있습니다.

| 증명 | 재조회 대상 |
|------|-------------|
| 인증 | `principal_ref`를 전달한 요청의 Operator 인증 증적. 명령 증적과 같은 방식으로 보존됨 |
| 근거 | 증적의 subject와 그룹, 사례 범위, `case-history.read`, 목적에 대한 현재의 명시적 권한 부여와, 기록된 목적이 일치하는 사례 범위 |
| 완전성 | 고정된 권한 부여 레지스트리 개정 전체와 알려진 사례 범위 정의 |
| 충돌 | 철회되었거나 만료되었거나 서로 모순되는 일치 권한 부여가 없고, 증적과 다른 `principal_groups`가 없음 |
| 최신성 정책 | 권한 부여를 읽은 시점부터 60초 |

### 현재 사례 재사용

소비자: Forseti 판단의 T1(가벼운 유사성 재사용) 계층인 `core/tiers/t1_lightweight/contextual_reuse.py`의
`contextual_reuse_reasons`이며, `delivery/azure/operational_evidence.py`의 `AzureCurrentReuseVerifier`가 검증
결과를 공급합니다. 조회: `current_reuse_evidence_digest`, `current_reuse_scope_digest`, `current-case-reuse`,
사례 `graph_digest`. Thor는 여전히 다시 검증합니다.

| 증명 | 재조회 대상 |
|------|-------------|
| 인증 | 검증기 신원으로 읽은 현재 인벤토리 스냅숏과 Muninn의 현재 사례 개정 |
| 근거 | 다시 계산한 fingerprint, 리소스 유형, 토폴로지 역할, 그래프 및 소유자 digest, 일곱 가지 안전 결과와 각 결과를 뒷받침하는 보존된 증적 참조, 그리고 사례 범위와 이벤트의 대상 범위를 모두 덮는 재사용 권한 부여 |
| 완전성 | 대상에 대한 완전한 현재 그래프 세대와 모든 안전 결과에 대해 읽을 수 있는 증적 |
| 충돌 | 세대, 사례 개정, 증적 사이에 불일치가 없음 |
| 최신성 정책 | 스냅숏 관측 시점부터 300초이며, 현재의 5분 스냅숏 한도와 같음 |

**출처 바인딩.** `core/operational_evidence/readback/current_case_reuse.py`는 검증기 쪽 readback을 정의하고,
`delivery/azure/operational_evidence.py`는 실시간 T1(가벼운 유사성 재사용) 경로에 쓰는
`AzureCurrentReuseVerifier`를 정의합니다. 검증기는 이제 `current-case-reuse` 증적을 요청하기 전에 조회 가능한 출처
행을 보존합니다. 이 행에는 다시 계산한 검증 결과, 현재 인벤토리 세대, Muninn 사례 참조, 일곱 가지 결정적 안전 증적
참조, 사례와 대상 권한 부여 좌표가 포함됩니다. 검증기는 넓은 `state_kv` 접근 대신 고정 매개변수 함수로 이 행을
읽습니다. 출처 행 누락, 잘못된 안전 증적, 세대 충돌, 사례 개정 불일치, 실패한 안전성 검토, 권한 부여 불일치는 모두
유형화된 거부로 fail-closed 처리됩니다. Thor는 재사용된 사례가 실행 경로에 쓰이기 전에 여전히 다시 검증합니다.

## 실패 시 차단하는 거부 매트릭스

| 유형 | 탐지 방식 | 기록되는 결과 |
|------|-----------|---------------|
| 오래됨(stale) | 검증기 사전 점검 `stale`, 소비자 `not_current`, 경계의 시간 구간 | 거부 기록 `stale`. 소유자는 해당 유형으로 보류하거나 평가에서 제외 |
| 철회됨(revoked) | 발급 시 권한 부여나 바인딩 철회, 내용으로 분류한 철회 개정, `admit`마다 수행하는 바인딩 재확인, 소비자의 최신 출처 읽기 | 거부 기록 `revoked` 또는 경계가 다시 요청하는 폐기된 검증 증적. 철회된 근거는 만료 전이라도 아무것도 수용하게 하지 못함 |
| 충돌(conflicting) | 출처와 교차 확인 출처 사이의 충돌 증명 | 충돌 근거 digest가 있는 거부 기록 `conflicting`. 소유자는 자율성을 낮추는 명시적 충돌을 기록하며 충돌을 평균 내지 않음 |
| 부분(partial) | 10,000 basis point 미만의 완전성, 누락된 체크포인트, 잘린 페이지, 매핑되지 않은 의존성 | 거부 기록 `partial`. 빈 결과는 부재를 증명하지 못함 |
| 합성 근거의 실운영 사용(synthetic-live) | `synthetic=true`, 고정 앵커 밖의 출처, 배포 환경의 `local-loopback` 앵커나 증적 | 거부 기록 `synthetic_live` |
| 범위 이탈(cross-scope) | 권한 부여 누락, 범위 밖 대상, 그룹 불일치, 범위나 목적 불일치 | 거부 기록 `cross_scope`. digest 일치가 권한 부여를 대신하지 못함 |
| 재생 대체(replay-substituted) | 정확한 조회, 근거 증적에 묶인 증명, 선행 digest, 목적별 저장소, 최신 출처 재확인 | 거부 기록 `replay_substituted`. 오래되었거나 다른 곳의 기록, `deployment-apply` 기록은 다른 입력을 수용하게 하지 못함 |
| 자체 검증(self-verified) | 출처, 생산자, 검토자, 실행기 계열 앵커와 같은 검증기 앵커, 또는 다른 principal이 쓸 수 있는 증명 저장소 | 검증기는 시작이나 발급을 거부하며, 기능 상태는 장애가 아니라 `self_verified`를 표시. 이 유형은 기능 상태에만 존재하며 거부 기록을 쓰지 않고, 소유자는 일반 보류를 유지함 |
| 사용 불가(unavailable) | 검증기, 출처, 저장소, 레지스트리 누락, 시간 초과, `429`, `503` | 기록 없음. 소유자는 현재의 일반 사유를 유지하고, 기능 상태는 누락된 의존성을 표시 |

## 판테온 소유권과 토픽

| 목적 | 출처 소유자 | 책임 있는 소비 에이전트 |
|------|-------------|--------------------------|
| `operator-test-context-command` | Operator 서비스 발신함(비에이전트) | 검토는 Var, 전이는 Mimir |
| `test-context-transition` | Operator 명령과 Mimir의 통제 저장소 | Mimir |
| `operational-test-context` | Mimir의 통제 저장소 | 판단은 Forseti, 디스패치 재확인은 Thor |
| `operational-test-observation` | 텔레메트리 공급자와 검토된 운영 범위 | Forseti |
| `forecast-history-*` | Thor, 인벤토리 저널, incarnation 원장, operating-intent 출처 | Heimdall |
| `forecast-context` | 수용된 출처별 이력 네 개 | Heimdall |
| `case-history-read` | 권한 부여 레지스트리와 Muninn 사례 메타데이터 | 읽기 함수를 호출하는 Bragi(`composition/semantic_query_invocation_context.py`의 `caller_agent="Bragi"`). 사례 소유자는 계속 Muninn |
| `current-case-reuse` | 인벤토리 그래프, Muninn 사례, 안전 증적 | Forseti이며 Thor가 다시 검증 |

검증기는 모든 목적에 대해 발급하지만 판테온에 합류하거나, 소유 객체를 게시하거나, 판단, 승인, 실행,
승격을 하지 않습니다. 토픽을 추가하거나 소유자를 바꾸지도 않습니다. Var는 계속 `object.approval`, Mimir는
`object.policy`, Forseti는 `object.verdict`, Thor는 `object.action-run`, Heimdall은 `object.forecast-outcome`을
게시합니다. 소비자는 전이 감사의 `admission_ref`처럼 이미 소유한 기록에 검증 증적과 거부 기록 digest를
인용합니다. 책임은 경계별로 유지합니다. 위의 각 소비 판단에는 이미 담당 에이전트가 있으며, 이는 현재 주입된
검증기 공급자를 관리하는 방식과 같습니다. Saga는 이 판단들을 나중에 감사하고, Saga를 잃으면 시스템 전체가
shadow로 내려가지만 발급 장애는 해당 목적만 `unavailable`로 만들므로 Saga는 책임 담당자가 아닙니다.

## 로컬 검증 가능성과 연결 환경 인계

로컬 결정론적 검사는 실제 모델, Azure 서비스, 원격 데이터베이스 없이 실행합니다.

- **Digest 일치와 정확한 출처.** 검증기와 각 소비자는 목적마다 하나의 정규화 함수를 공유합니다. Operator 발신함
  행, 감사 항목이 있는 `test-context-target:v1` 기록, 저널 페이지, incarnation 행, `ChangeWindow` 개정, 메트릭
  응답, 권한 부여 개정과 같은 형태의 가짜 객체로 각 유형이 정확히 기록되는지 확인합니다.
- **전송, 작성자, 레지스트리.** 기한, `429`와 `503`을 `unavailable`로 보고하는 단일 시도, 진행 중인 요청의 병합,
  `outcome`이 거부하는 이전 거부 기록, 위조된 응답 본문 이후의 재조회를 검사합니다. 루프백 PostgreSQL의 작성자
  역할과 읽기 역할로 Core가 두 기록 모두 만들 수 없고 재생이 멱등임을 증명합니다. 이름표 없는 제거나 축소도
  기록을 폐기하고, 일상적 교체는 폐기하지 않음을 확인합니다.
- **회귀 기준선.** `core/readiness/test_decision_evidence.py` 같은 기존 의사결정 근거 테스트,
  `services/core-control-plane/tests/` 아래 각 소비자의 집중 테스트, semantic 인증 증적 참조를 기본적으로
  꺼 두는 Operator 조립 테스트가 계속 통과합니다. 이 Operator 테스트 모듈은 선택적 PDF 렌더러 버전 범위
  같은 서비스 배포판 구성도 검사하며, 이 검사는 근거 권한을 갖지 않습니다.

이 검사는 동작 방식만 검증하며 운영 자격 검증으로 인정하지 않습니다. 연결 환경 인계는 별도의 명시적 승인
후에만, 선택한 비운영 대상에서, 같은 소스 개정으로 실행합니다.

| 단계 | 필요한 관측 근거 |
|------|------------------|
| 신원 | 검증기 principal이 모든 출처, 생산자, 실행기 계열 principal과 다르고, 자신의 역할 할당이 정확한 DSN 시크릿 읽기, 정확한 레지스트리 pull, 승인된 읽기 범위로 제한되며, 작성자 재조회에 검증기 데이터베이스 역할만 나타남 |
| 레지스트리 | 두 레지스트리 digest가 검증기와 모든 소비자에서 고정값과 일치함 |
| 긍정 발급 | 목적마다 실제 출처로 검증 증적 하나를 발급하고, 해당 경계가 이를 소비하며, 소유자 감사에 근거 증적과 묶음 digest가 남음 |
| 부정 훈련 | 전용 테스트 범위에서 자체 검증을 제외한 각 거부 유형이 예상한 거부 기록과 그에 맞는 소유자 사유를 만들고, 자체 검증 훈련은 기능 상태 `self_verified`를 확인하며, 중지된 검증기는 `unavailable`만 내며 다른 유형의 훈련을 통과하지 못함 |
| 중지 조건 | 신원 누락, `429`나 `503`, 기한 초과, 충돌 근거가 있으면 실행을 멈추고 누락된 단계를 기록함 |
| 기록 | 배포된 SHA, 레지스트리 digest, 범위 digest, 시각, 증적 참조. 독립 운영 자격 검증은 계속 [#1026](https://github.com/dotnetpower/fdai/issues/1026) 범위 |

## 구현 참고 사항

Core 경로는 `services/core-control-plane/src/fdai/` 기준 상대 경로입니다. 각 항목은 현재 설계가 구현된 방식을
기록하며, 남은 작업은 [구현 원장](../../roadmap-implementation/rules-and-detection/independent-operational-evidence.md)에서
추적합니다.

- **계약.** `fdai_service_contracts.operational_evidence`는 조회, 좌표만 담는 위치 정보, 본문이 없는 요청과 응답,
  고정 60초 기간을 가진 거부 기록을 정의합니다. `fdai_service_contracts.operator_authentication`은 토큰이 없는
  Operator 인증 증적을 정의합니다.
- **경로와 소유자.** `shared/providers/operational_evidence_issuer.py`는 `OperationalEvidenceIssuer`와 시도 범위
  결과 조회기를 선언합니다. `core/operational_evidence/owner_outcome.py`는 동일한 진행 중 요청을 병합하고, 해당
  시도가 지목한 기록을 다시 읽은 뒤에만 거부를 받아들입니다. 모든 소비 소유자는 `admit` 전에 발급을 요청하며,
  증명된 유형은 일반 사유만 대체하고 거부 기록 digest를 인용합니다. Var와 Mimir는
  `OperationalEvidenceRejectedError`로 거부하고, Mimir는 `context_digest`가 없는 `test_context.transition_refused`
  감사 항목도 추가합니다. Forseti의 보류는 `evidence_rejection_ref`를 담고, Thor의 디스패치 보류는 `ActionRun`
  결과와 `evidence_rejection_ref`를 설정합니다. Heimdall은 점수 산정과 조각 보존 중 어느 쪽이 거부되었든
  `ForecastOutcome` 스키마 `1.2.0`의 `operational_evidence_*` 유형과 `operational-evidence-rejection:` 근거 참조로
  점수 산정을 제외합니다. T1 사유 코드와 Pattern 읽기의 거부도 유형을 밝히고 기록을 인용합니다.
- **Forseti 판단 표.** Forseti는 규칙 및 위험 결과를 주입 가능한 digest가 찍힌 판단 표에서
  읽고, 결정론적 결정마다 표 digest와 안정적인 결정 키를 기록합니다. `auto` 결정은 상한일 뿐입니다.
  거버넌스가 적용된 되돌릴 수 있는 `ActionType` 의미가 없거나, 작업을 알 수 없거나, 필요한 정족수가
  `>= 2`이거나, 일치한 규칙이 retired 또는 revoked이면 Forseti는 사람 승인(`hil`)으로 낮춥니다.
- **검증기.** `core/operational_evidence/issuance.py`와 `proofs.py`는 레지스트리 항목과 자체 재확인으로 근거 증적, 다섯 증명,
  묶음을 만들고 `DecisionEvidenceReadinessGate`로 평가한 뒤 발급 기록 하나 또는 거부 기록 하나를 작성합니다.
  `separation.py`는 독립 principal과 같은 검증기 principal을 거부하며, `delivery/operational_evidence_server.py`는
  루프백 및 배포 엔드포인트를 제공합니다. 배포 시작 경로에는 `ready`를 보고하거나 발급하기 전에 명시적인 실행기 계열 앵커,
  등록된 생산자 토큰 인증기, 자체 역할 재확인이 필요합니다. `deployment_preflight.py`는 실행기 계열 앵커 집합을 만들고,
  `operational_evidence_caller_auth.py`는 수명이 짧은 호출자 토큰을 검증한 뒤 폐기하며,
  `own_role_readback.py`는 부분 재확인, 해석할 수 없는 역할 정의, 신원 불일치, vault 전체 시크릿 접근, 다른 시크릿 접근, 정확히 렌더링된 읽기 범위를 벗어난 쓰기/데이터 플레인 역할을 거부합니다.
  Terraform은 내부 ingress만 렌더링합니다. AKS 독립 실행형 렌더러는 배포 소유 레지스트리 고정값, 앵커,
  호출자 토큰 검증 데이터, 작성자 멤버십 정책, 역할 재확인 범위, 전용 검증기 신원이 있을 때만 같은 검증기를
  별도 내부 워크로드로 렌더링할 수 있습니다. 독립 실행형 배포 CLI는 이 입력을 기본적으로 끈 상태로 두며,
  비공개 검토 JSON 파일에서만 받습니다. 알 수 없는 필드, 누락된 고정값, 자리 표시자, 시크릿 키 자료,
  GUID가 아닌 principal, `fdai_operational_evidence_verifier` 이외의 검증기 데이터베이스 역할을 거부합니다.
  이를 선택해도 Terraform 신원 플래그와 애플리케이션 워크로드 바인딩만 설정합니다. 루트 Terraform 단계는 사용 설정된 경우에만 그 신원을 만들고, 이미지
  pull과 정확한 상태 저장소 DSN 시크릿만 부여하며, 같은 구성에서 만든 Managed Identity 역할 할당에
  `principal_type = "ServicePrincipal"`을 사용합니다. 현재 호출자 인증기는 배포가 제공한 JWKS 스냅샷을 사용합니다. 알 수 없는
  `kid`는 나중에 제한된 JWKS 갱신 provider가 추가될 때까지 명확한 인증 거부입니다. 워크로드는 자신의 검증기 버전에
  해당하는 정확한 바인딩으로만 발급하므로, 일상적 교체 후에도 이전 워크로드와 이미 보관된 발급 기록은 만료될 때까지 유효하고, 철회 개정은 이를 폐기합니다. 재실행된
  시도는 동시에 실행된 작성자가 먼저 삽입한 경우에도 저장된 결과를 반환하며, 다른 조회에 다시 사용된 시도 ID는
  `unavailable`입니다.
- **실행 환경.** `resolve_execution_venue`가 해석한 `FDAI_EXECUTION_VENUE`가 기준입니다. 앵커 문서가 다른 실행
  환경을 지정하거나 키를 반복하면 모든 목적이 사용할 수 없는 상태가 되고 검증기 워크로드가 멈춥니다. 로컬 워크로드는
  루프백 호출자만 받습니다. 배포 워크로드는 루프백이 아닌 엔드포인트에 바인딩할 수 있지만 호출자 인증기, 실행기 앵커
  사전 점검, 작성자 재확인, 자체 역할 재확인이 모두 통과한 뒤에만 시작합니다.
- **레지스트리.** `config/operational-evidence-trust-registry.json`은 검토된 업스트림 레지스트리입니다.
  `trust_registry.py`, `grant_registry.py`, 각각의 `*_loader.py` 모듈, `revision_history.py`는 고정된 개정을 엄격하게 읽고, 각 개정을 내용으로
  분류하며, 철회 개정 이후 이전 고정값을 폐기하고, 일치한 바인딩이나 권한 부여가 철회될 때만 계보를 끝냅니다.
  아직 유효 기간이 시작되지 않은 일치 권한 부여는 권한을 주지도 거부하지도 않으며, 철회되었거나 만료된 일치 항목만
  거부합니다. 검증기 신뢰 앵커가 생산자, 출처, 분리 앵커로도 쓰이는 목적은 `verifier_anchor_not_exclusive`를
  보고합니다. 업스트림 `forecast-context` 항목은 이제 검증기 신뢰 앵커가 아니라 Core가 소유한 예측 맥락 보존 출처와
  Core가 소유한 조각 검증 증적 인덱스를 가리킵니다. 따라서 레지스트리는 그 결함 없이 적재되지만, 원본 예측 출처가
  생길 때까지 재확인은 연결하지 않습니다. 권한 부여 레지스트리, 고정값, 앵커 바인딩은 배포가 제공합니다.
- **증명 저장소와 출처.** core-control-plane 서비스 마이그레이션 `core_operational_evidence_20260928`은 삽입 전용
  테이블 다섯 개, 검증기 역할과 읽기 역할, 변경 방지 트리거를 만듭니다. 또한 Operator 신원만 테스트 맥락 명령 행을
  삽입하게 하고, 그 요청 필드와 증적을 변경할 수 없게 하며, 그 행과 Mimir 이력, 감사 행 위에 읽기 전용 보안 장벽
  뷰를 정의합니다. 후속 마이그레이션 `core_operational_evidence_source_functions_20260929`는 이 뷰에 대한 검증기의
  `SELECT` 권한을 회수하고, `search_path`가 고정되고 동적 SQL이 없는 고정 매개변수 `SECURITY DEFINER` SQL 함수
  네 개에 대한 `EXECUTE` 권한만 부여합니다. 각 함수는 정의자 권한 안에서 먼저 걸러 내므로 호출자가 넣은 조건은
  반환된 행만 보게 되고, 플래너 추정치나 `EXPLAIN ANALYZE` 행 수로 다른 `state_kv` 키를 알아낼 수 없습니다. 이
  마이그레이션의 downgrade는 뷰 권한을 복원합니다. 첫 마이그레이션은 검증기 역할에 직접 부여된 `TEMPORARY` 권한을
  회수하며, Core가 임시 테이블을 사용하므로 PostgreSQL 기본 `PUBLIC` 권한은 남아 있습니다. Operator는 증적을 멱등
  요청 digest 안이 아니라 그 옆에 보관합니다. 의미 요청은 Bragi 호출 맥락에 증적 digest 참조만 전달합니다. 검증기는 나중에 그 참조로 본문 없는 증적을 읽으며 토큰 자료를 받지 않습니다.
- **재확인.**  `operator-test-context-command`, `test-context-transition`, `operational-test-context`는 실제 출처를
  읽습니다. 현재 맥락은 인용한 전이 발급 기록의 조회가 그 맥락과 직전 기록으로 다시 만든 조회와 같을 때만 인정되며,
  다른 발급 기록을 인용하면 `replay_substituted`입니다. `admit`은 보관된 기록마다 정확한 검증기 바인딩과 현재 앵커
  기준의 그 바인딩 준비 상태를 다시 확인합니다. `forecast-history-actions`, `forecast-history-changes`,
  `forecast-history-excluded_windows`, `forecast-history-resource_lifecycle` 목적은 이제
  `operational_state_transition*`의 실제 파생 출처 행을 읽고, `forecast-context`는 네 개의 출처별 이력에
  바인딩됩니다. `operational-test-observation`은 배포된 검증기 workload가 `Monitoring Reader`, Log Analytics metric
  template, 검토된 운영 범위 관측 행을 모두 가질 때 바인딩됩니다. `current-case-reuse`는 근거 발급 전에 인벤토리
  세대, Muninn 사례 참조, 안전 증적, 권한 부여 좌표를 보존하는 현재 재사용 출처 행을 통해 바인딩됩니다.
  사례 이력에는 이제 삽입 전용 Operator semantic 인증 증적 스키마, `operator-core-request` `1.9.0` 증적 참조,
  Core에서 Bragi로 이어지는 참조 전파, 연결된 정확한 재확인 모듈이 있습니다. Operator 설정
  `FDAI_SEMANTIC_AUTHENTICATION_RECEIPT_REF_ENABLED`는 기본적으로 꺼져 있으며, `operator-core-request` `1.9.0`을
  수용하는 Core가 배포된 뒤에만 켤 수 있습니다. 이 설정을 켜면 Operator가 참조를 보내기 전에 본문 없는 증적을
  기록하므로 Core는 해소할 수 없는 참조를 받지 않습니다.
- **공유 권한 부여 검증.** 사례 범위 권한 부여 레지스트리 로더와 권한 부여 모델은 공유 서비스 계약 SDK에 포함되며 Core가 이를 다시 내보냅니다. Operator의 테스트 컨텍스트 선택 변환은 별도 권한 부여 검증기를 두지 않고 같은 로더를 콘텐츠 고정값과 함께 사용합니다.
- **기능 상태와 인계.** `delivery/operational_evidence_readiness.py`는 목적마다 Settings 행 하나를 추가합니다. 런타임
  Settings 구체화는 모든 실패를 관측되지 않음으로 처리하는 제한된 읽기로 검증기 준비 상태 엔드포인트를 한 번
  관측하고, 형식이 지정된 `OperationalEvidenceVerifierReadiness` 스냅샷을 프로젝션에 전달합니다. 행은 스냅샷이
  120초 이내이고, 이 검증기와 같은 레지스트리 고정값을 가리키며, 검증기만 쓸 수 있는 증명 저장소를 보고하고,
  목적을 연결했고, 자신의 검증기 버전에 활성 바인딩이 있으며, 제한된 탐침 읽기 뒤에 목적이 선언한 모든 출처를
  정상으로 보고할 때만 `available`입니다. 충족하지 못한 전제 조건은 각각 이름이 표시되고, 구성만으로는 행을 사용 가능하게 만들 수 없으며, 사용 가능 여부는
  권한을 부여하지 않습니다.
  `delivery/operational_evidence_handoff_cli.py`는 자동화할 수 있는 연결 환경 인계 단계를 실행하며 남은 훈련을
  나열합니다. 별도의 연결 환경 승인을 받은 뒤 워크로드의 배포 제공 환경을 적재한 상태에서 조정자는 다음 명령을
  실행합니다.

  ```bash
  FDAI_OPERATIONAL_EVIDENCE_HANDOFF_AUTHORIZED=1 \
    .venv/bin/python -m fdai.delivery.operational_evidence_handoff_cli run \
    --venue connected \
    --root /app
  ```

  이 명령은 본문 없는 인계 증적을 만들고 신원, 레지스트리, 작성자 재확인, 준비 상태, 긍정 발급, 부정 훈련,
  중지 조건 관측 중 처음 누락된 단계에서 멈춥니다. 독립 운영 자격 검증은 아니며, 그 범위는 #1026에 남아
  있습니다.

## 목표가 아닌 것

- 새 에이전트나 토픽, `owns`, `subscribes`, 역할 바인딩 변경이 없고, 실행 권한이나 승격 권한도 부여하지 않습니다.
- `deployment-apply` 정책, 그 워크플로 증명, 그 컨테이너를 재사용하지 않습니다.
- 소비자는 기존 자체 검토 거부를 포함해 계속 차단 상태를 유지하며, 보류 사유에 유형만 추가됩니다.
- 범위 밖: 원본 이력(#1021), Console 워크플로(#1023), Pattern-T1 수용(#1024), P0-P6 자격 검증(#1026).
  테넌트 값, 비밀, 실제 Azure, 모델, 배포 활동도 포함하지 않습니다.

## 검토 결정

소유자는 2026-09-28에 #1022 종료 조건 1에 대해 다음과 같이 결정했습니다.

1. **증명 진위.** 쓰기 독점과 불변성을 기준으로 삼습니다. 분리 서명은 두지 않으며 증명 계약 버전도
   바꾸지 않습니다.
2. **사람 인증.** Operator 인증 증적만으로 사람 principal을 확인합니다. ID 공급자 로그인 기록 교차 확인은
   하지 않습니다.
3. **책임.** 경계별 책임을 적용하며 단일 책임 담당자는 두지 않습니다.
4. **증명 저장소.** 두 환경 모두 삽입 전용 PostgreSQL 테이블을 사용합니다.
5. **최신성 상한.** 60초부터 3,600초까지인 영역별 상한을 제안한 값 그대로 확정합니다.
6. **교차 확인 비용.** 5초 이력 기한을 유지합니다. 기한 안에 끝나지 않은 교차 확인은 `unavailable`이 되며,
   기한 변경은 승인하지 않습니다.

## 관련 문서

| 학습할 내용 | 문서 |
|-------------|------|
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/rules-and-detection/independent-operational-evidence.md) |
| 소비자, 맥락 계약, 예측 근거 수용 | [예측 학습 및 케이스 히스토리](prediction-learning-and-case-history-ko.md) |
| 의사결정 핵심 근거 규칙 | [FDAI 헌법](../architecture/fdai-constitution-ko.md) |
| 에이전트 소유권 및 토픽 | [에이전트 판테온](../agents/agent-pantheon-ko.md) |
| 고정된 배포 소유 출처 | [배포 소유 Operating-Intent 출처](../architecture/operating-intent-source-ko.md) |
| 공유 Workflow 검증 계약 | [프로세스 자동화](../decisioning/process-automation-ko.md#71-공유-검증-소유자-설계) |
