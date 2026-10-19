---
title: 승인된 문서 의도 변환
translation_of: document-declared-intent-projection.md
translation_source_sha: 4fe8c7704b746ca3c3dcdd82d29630b6f29b4ad4
translation_revised: 2026-10-19
---
# 승인된 문서 의도 변환

이 설계는 #2256 G02와 자식 Task #2268의 승인된 문서 의도 namespace를 소유합니다.
정규화된 통제 문서를 독립적인 정확한 변경분 승인, 영속 온톨로지 레코드, 현재 원본
접근 권한을 확인하는 조회 및 복구에 연결합니다.

> **구현 범위:** Core SDK와 형식화된 에이전트 흐름은 명시적인 기계 작성
> `BusinessService` 의도 레코드를 지원합니다. 합성 공급자/디렉터리 입력을 실제
> PostgreSQL과 책임 에이전트로 테스트합니다. 원본 업로드/Console E2E나 배포 검증은 아닙니다.
>
> **권한 경계:** 의도는 프로바이더 사실, 텔레메트리, 정책, 실행 권한이 아닙니다.
> 새 에이전트, 실행 식별자, ActionType, 권한 레지스트리, 프로바이더 변경을 추가하지
> 않습니다. 기존 수집/인덱싱 승인은 원래 의미를 유지합니다.

## 설계 한눈에 보기

비공개 namespace는 고정된 `BusinessService` 선언과 기존 보호된 ObjectSet 조회 계약을
사용합니다. 레코드를 공통 `ontology_resource` 관측 저장소에 넣지 않습니다. 권위 있는
원본은 API 소유 문서와 Var의 기존 영속 승인입니다. 새 SQL 테이블은 계보, 발행 대기함,
원본 소유 읽기 모델이며 별도 권한 레지스트리가 아닙니다.

| 단계 | 책임 에이전트 | 기존 토픽 |
|------|---------------|-----------|
| 원본과 준비 확인 | Huginn, 이후 Muninn | `object.event`, `object.context-index` |
| 후보와 독립 검증 | Norns, 이후 Mimir | `object.rule-candidate`, `object.rule` |
| 허용 판단과 감사 | Forseti, 이후 Saga | `object.verdict`, `object.audit-entry` |
| 정확한 변경분 검토와 감사 | Var, 이후 Saga | `object.approval`, `object.audit-entry` |
| 원자적 반영 | Muninn | `object.context-index` |
| 독립 재조회와 감사 | Heimdall, 이후 Saga | `object.retrieval-validation`, `object.audit-entry` |
| 원본 소유 복구 | Vidar | `object.rollback` |
| 보류된 충돌 | Forseti, 이후 Odin | `object.arbitration-request`, `object.arbitration-decision` |

메시지는 `document_intent_projection`과 내용에 고정된 불변 식별자를 사용합니다. 일반
버스와 감사 레코드에는 원문이나 제안 속성 대신 불투명 참조만 넣습니다. Thor는 이 종류를
무시합니다. Odin은 검토를 위해 보류하며 원본 소유권, 접근 권한, 정확한 승인을 우회하지
않습니다.

닫힌 정식 wire 계약은 `fdai_service_contracts.document_intent`에 있습니다.
`generate_document_intent_schemas.py`가 버전별 이벤트, 승인, 변경분 스키마를 생성하며
`--check`로 오래된 산출물을 확인합니다. 기본 런타임 검증기는 같은 형식화된 계약을 사용해
추가 필드와 실행 권한을 차단하고 단계, 소유자, 토픽, 처리 결과, 개정 번호, 정확한 변경분
승인 바인딩을 검사합니다. 기존 작업 봉투 검증은 바뀌지 않습니다.

## 허용되는 원본과 승인

첫 범위는 키가 정확히 두 개인 JSON을 담은 정규화 구조 단위 하나를 수락합니다. 키는
`kind: fdai.declared-intent.business-service.v1`과 `properties`입니다. 속성은 선언의
스칼라 `id`, `name`, `criticality`, `effective_from`, 선택적 `effective_to`, 불변
`source_ref`이며 id는 `service:`로 시작합니다. 이는 형식화된 데이터 계약이며 산문을
어휘로 해석하는 방식이 아닙니다. 임의 산문, 추가 속성, 다른 유형, 링크, 관측된 상태,
실행 권한은 수락하지 않습니다. 기존 검토 전용 증류 경로는 바뀌지 않습니다.

원본은 현재 활성화되어 사용 가능한 보호되지 않은 통제 지식이어야 합니다. 인덱스와
보존 상태가 활성 상태이고 목적은 `manual_distillation`이어야 합니다. 완전한 정규화
묶음 검증값, 원본 해시, 문서/버전, ACL, 범위, 유효 기간을 검사합니다. 목적만으로
그래프 반영 권한을 부여하지 않습니다.

`DocumentIntentRuntime.submit`은 인증된 요청자와 정확한 추가/갱신 개정 번호를 고정합니다.
`review_diff`는 독립적으로 권한을 확인한 검토자에게 전체 불변 변경분을 제공합니다.
별도의 비작업 `document.review-intent-diff` Var 티켓이 해당 다이제스트를 고정합니다.
현재 검토 역할과 원본 접근 권한이 필요하며 업로더와 요청자는 승인할 수 없습니다.
수집 승인, 승인을 주장하는 메시지, 인수인계 증적은 Var의 영속 최종 레코드를 대체하지
않습니다.

## 원자적 영속화, 재생, 복구

Core 마이그레이션은 `document_intent_projection`, `document_intent_transition`,
`document_intent_resource`를 소유합니다. Core는 API 소유 `document_version`의 제한된
보안 정의자 메타데이터 함수를 사용하며 원문 SELECT 권한은 받지 않습니다. Operator는
비공개 테이블을 읽지 못합니다. 변경분/묶음 식별자와 전환 본문은 불변입니다.

한 트랜잭션에서 현재 원본 메타데이터, 정확한 영속 승인, 비공개 대상, 원본 소유 계보를
잠급니다. 원본/ACL 개정 번호, release, 대상 개정 번호, 독립 검토자, 후보, 결정,
Saga 감사를 검사합니다. 이전 상태, 새 개정 번호, 게시 의도를 레코드와 함께 커밋합니다.
다른 소유자, 오래된 입력, 누락된 단계, 변경된 재생은 부분 쓰기 없이 보류합니다.
동일한 재생은 개정 번호를 올리지 않습니다. 다시 시작하면 재승인하거나 재적용하지 않고
보존된 내용 고정 이벤트를 다시 발행합니다.

Heimdall은 커밋된 저장소를 독립적으로 열어 결과와 승인된 변경분을 비교합니다. 감사된
불일치는 Vidar로 전달됩니다. 복구는 개정 번호를 단조 증가시키면서 정확한 이전 상태를
복원하거나 정확히 새로 만든 레코드만 제거합니다. 대상이 더 바뀌면 Odin 검토를 위해
보류하며 관련 없는 쓰기는 유지합니다. 내용을 복원해도 철회된 원본 접근 권한은 복원하지
않습니다. 철회 알림은 적용된 패킷을 다시 관측하고 같은 감사 흐름으로 사용을 종료할 수
있습니다.

## 현재 권한을 확인하는 조회와 남은 연결

`document_intent_gateway`는 서버에서 인증한 principal을 실제 PostgreSQL 원본
메타데이터와 현재 디렉터리 읽기 경로에 연결합니다. 실행 전후에 모든 기여 원본을 다시
검사하며 Owner도 원본 ACL을 우회하지 않습니다. 첫 namespace는 활성 레코드를 최대
64개 지원합니다. 한도를 넘거나 불완전하거나 바뀌거나 만료되거나 접근할 수 없는 집합은
일부 개수를 조용히 반환하지 않고 사용 불가 또는 차단 결과를 냅니다. 세대 이름은
`document-intent:`로 시작합니다. 비공개 어댑터는 쓰기를 차단합니다. 다시 시작한 읽기
경로는 보존된 승인이나 결과를 믿지 않고 권한을 다시 확인합니다.

명령 경계는 이미 통제된 `DocumentEnvelope`에서 시작합니다. 수집 API/워커의 자동 연결,
보호된 검토 UI, 공통 그래프/조회 매니페스트 노출, 이 비공개 namespace 밖의 원본 권한
기반 캐시 재사용은 구현하지 않았습니다. 원본 파일 업로드가 일반 Console이나 대화에서
조회된다고 주장하지 않습니다. 배포, 실제 코퍼스/모델 근거, 실제 관찰 기간, 승격은
별도 조건으로 남습니다.
PostgreSQL 테스트는 실제 기본 검증기와 로컬 브로커를 사용하는
`PantheonRuntime.build(document_intent=...)`를 실행합니다. 일반 프로세스 bootstrap은
이 선택적 바인딩을 공급하지 않으므로 설치 기능이 활성화되었다는 근거는 아닙니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 더 넓은 제안 수명 주기 | [문서 온톨로지 증류](document-ontology-distillation-ko.md) |
| 기존 원본 책임 | [문서 수집 에이전트 책임](../interfaces/document-ingestion-agent-ownership-ko.md) |
| 근거와 남은 작업 | [구현 원장](../../roadmap-implementation/rules-and-detection/document-declared-intent-projection.md) |
