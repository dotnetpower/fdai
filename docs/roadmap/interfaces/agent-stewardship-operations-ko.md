---
translation_of: agent-stewardship-operations.md
translation_source_sha: 0ef7e2f3d514f04cc59a9310d5c72ac7420433df
translation_revised: 2026-09-15
title: 에이전트 운영 책임 수명 주기
---
# 에이전트 운영 책임 수명 주기

이 문서는 FDAI 운영 책임(`stewardship`)의 구현된 런타임 및 거버넌스 수명 주기를 정의합니다.
인수인계 맵 스키마와 담당 체계 개념은
[에이전트 운영 책임과 담당자 인수인계](agent-stewardship-and-handover-ko.md)를 참조하세요.

> Console의 담당 체계 변환 결과는 읽기 전용입니다. 안내형 양식은 인수인계 문서를 수집
> 경계에 제출합니다. 담당 체계 변경은 초안 PR로 만들고 Git 호스트에서 검토한 뒤 서명된
> 웹후크로 병합을 관찰합니다. 담당 체계는 RBAC 기능을 부여하거나 Thor의 실행기 신원을
> 받지 않습니다. 업로드 형식 검색, 통제된 미리 보기, 커넥터와 취소 재조정은 수집 서비스가
> 소유하며 웹후크에 문서 읽기, 커넥터, 담당 체계 변경 권한을 부여하지 않습니다. 로컬 또는
> Azure OCR 준비 상태는 지원 이미지 형식만 바꾸며 인수인계, RBAC 역할, 책임 담당자를
> 변경하지 않습니다.
> **현재 근거:** 2026-09-15 소스 체크포인트는 범위별 Console 담당 체계, Core 목표/검토자/
> 원본 허용/검색, 비공개 의미 패키지 보존, 격리 IAM 복구를 포함합니다. 잔여 구현 이후 [최종 검토 12회](../../internals/handover-lifecycle-hardening-20260914.md#final-integrated-critique-after-remaining-source-implementation)를 완료했으며 미해결로 확인된 Medium/High 소스 문제는 없습니다.
> [PR #1014](https://github.com/dotnetpower/fdai/pull/1014)는 검토된 헤드 `8c1d9977c`를 `953a17de4`로 병합해 #946 전달을 완료했습니다. 정확한 헤드의 CI `34925881557`과 병합 후 CI `34926168342`가 통과했습니다.
> [#1017 로컬 UI 근거](../../internals/handover-ui-evidence-20260915.md)는 평가 기준 50개를 기록하고 실제 스크린 리더 검사를 `needs-human`으로 남깁니다. 최종 점수는 없습니다. 준비도는 `shadow`, `operationally_ready=false`이며 [#458](https://github.com/dotnetpower/fdai/issues/458)은 열린 상태입니다.

[운영 검증 가이드](../../user-guide/guides/validate-ownership-handover-ko.md)는 실제 음성, 현재
신원, 공급자, 복구, 코호트, 정확한 계획의 근거를 구분합니다. #1017은
[PR #1031](https://github.com/dotnetpower/fdai/pull/1031)의 `33c76944cec4489b51bc3bb90820cc273159d99d` 병합으로
전달을 완료했고 정확한 헤드의 CI `34933740673`과 병합 후 main CI `34934077457`이 성공했습니다.
이 결과로 #458이 완료되지는 않습니다.

클라우드 참조 수집과 서명 반입은 같은 수집 호스트를 사용하지만 담당자 변경 권한을
공유하지 않습니다. 인수인계 초안을 만들거나 담당자를 바꾸지 않으며, [별도 수명 주기](cloud-resource-knowledge-lifecycle-ko.md)의
출처/신뢰 정책과 기존 독립 문서 승인 절차를 따릅니다.

## 설계 개요

공유 수집 호스트는 AKS에서 자기 서비스에 명시된 투영 워크로드 신원을 선택합니다. 바뀌는
것은 Azure 토큰 획득 방식뿐입니다. 운영 소유권 웹후크는 계속 Git 서명을 검증하고, 인계는
검토 전용으로 유지되며, 서비스 자격 증명은 소유자를 바꾸거나 RBAC 권한을 부여하지 않습니다.

수명 주기에는 서로 독립적인 안전 경계 네 가지가 있습니다.

1. **시작 준비 상태:** 운영에서 같은 인수인계 맵을 읽고 자리 표시자 신원을 차단합니다.
2. **예약 상태 검사:** 컨트롤 루프의 주요 처리 경로 밖에서 활성 Entra 사용자를 확인하고
   상태가 바뀔 때만 감사 기록을 남깁니다.
3. **초안 전달:** 근거에 기반한 인수인계 문서를 멱등적인 거버넌스 PR 하나로 변환합니다.
4. **병합 관찰:** GitHub 서명을 검증하고 변경 파일과 병합 내용을 다시 읽은 뒤 병합 감사를
   기록하고 새 책임 담당자에게 알립니다.

![설계 개요. 주요 단계는 Terraform bindings, Production startup validation, GET /stewardship, Scheduled Entra liveness check, Guided registration form, Grounded handover upload, Durable handover draft, Idempotent draft governance PR, Git review and approval, Signed merge webhook, GitHub files and merged YAML re-read, Append-only Saga audit입니다.](../../diagrams/generated/fdai-roadmap-interfaces-agent-stewardship-operations-01.ko.svg)

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 시작 바인딩과 읽기 전용 변환 결과 | implemented | `services/operator-service/src/fdai_operator_service/`; `services/operator-service/tests/test_operator_operations_family.py`; `tests/integration/infra/test_operator_api_stewardship.py`; 집중 Operator 및 Terraform 테스트 (15 passed) | 경로와 배포 바인딩이 있습니다. 소스 배선만으로 실제 배포 준비 상태가 입증되지는 않습니다. |
| Terraform 바인딩 완전성 검사 | implemented | `infra/production-gates.tf`; `tests/integration/infra/test_operator_api_stewardship.py`; `tests/integration/infra/test_core_stewardship_gitops.py`; [독립 배포](../deployment/installable-deployment-cli-ko.md) | 운영 구성은 신원과 GitOps 자격 증명을 배포 소유로 유지하면서 유지관리자와 자율 운영이 아닌 모든 에이전트 바인딩을 요구합니다. 과거 워크플로 근거는 현재 테넌트 배포 경로가 아닙니다. |
| 안내형 등록과 근거 기반 영속 초안 | implemented | `console/src/routes/handover-editor.tsx`; `services/document-processing-worker/src/fdai_document_worker_service/handover.py`; 집중 콘솔 테스트 (21 passed); 집중 수집 전달 테스트 (9 passed) | SPA는 관리형 업로드를 제출하고 워커는 검토 전용 초안을 저장합니다. 어느 효과도 활성 지도를 변경하지 않습니다. |
| 멱등적 초안 거버넌스 PR 전달 | implemented | [`governance.py`](../../../services/core-control-plane/src/fdai/core/stewardship/governance.py); [`stewardship_governance.py`](../../../services/core-control-plane/src/fdai/runtime/stewardship_governance.py); 집중 담당 체계 및 런타임 테스트 | 런타임은 영속 `handover_draft:*` 레코드를 읽고, 신원 재정의를 허용하지 않은 상태에서 각 완전한 후보를 검증한 다음 구성된 `RemediationPrPublisher`를 통해 게시합니다. PR 참조 또는 차단 결과는 Saga 감사와 함께 원자적으로 기록합니다. 내용 기반 증적을 사용하므로 재시작과 재처리가 안전합니다. 관리형 배포 증적은 별도 근거로 남습니다. |
| 서명된 병합 수신과 후속 담당 체계 효과 | implemented | `services/document-ingestion-api/src/fdai_ingestion_api_service/adapters/stewardship.py`; `services/core-control-plane/src/fdai/runtime/stewardship_merge_effects.py`; 집중 병합 및 소유권 조정 테스트 | 서명된 수신 경로는 비활성 근거를 저장합니다. Core는 병합된 맵을 검증하고 수신자를 계산하며 다이제스트가 일치하는 제안만 알림 및 Saga 감사와 함께 진행합니다. 부여 병합은 재처리해도 같은 shadow IAM 요청을 게시하고 제거 병합은 재부여를 요청하지 않습니다. |
| 예약 실행되는 영속 신원 상태 검사 | implemented | `services/core-control-plane/src/fdai/runtime/stewardship_identity_health.py`; `services/operator-service/src/fdai_operator_service/ownership_projection.py`; Core 서비스 Terraform | 준비 상태 이후 실행되는 Core 워커가 사용자 주체를 중복 제거하고, 전이 시에만 상태를 감사하며 만료 시간이 있는 성공 관찰을 기록합니다. Graph 장애 시 마지막 성공 상태를 보존하고 리비전이 일치하며 만료되지 않은 결과만 읽기 전용 Operator 변환 결과에 반영합니다. |
| 갱신 가능한 GitHub App 인증 | implemented | `packages/github-app-auth`; Core 및 수집 GitHub 어댑터; 집중 인증, 배포 및 Terraform 검사 | 장기 실행 서비스는 Key Vault 기반 private key로 저장소 범위 installation token을 발급하고 비동기 잠금 아래 캐시한 뒤 만료 전에 갱신합니다. 정적 토큰은 범위가 제한된 호환 입력이며 배포 목표가 아닙니다. |
| 검토 전용 이전 임무 제거 | implemented | [회수 조정기](../../../services/core-control-plane/src/fdai/core/human_assignment/revocation_ownership.py); [회수 의도](../../../services/core-control-plane/src/fdai/core/human_assignment/revocation_intent.py); [실행 체크포인트](../../internals/handover-lifecycle-hardening-20260914.md#execution-source-critique-checkpoint) | 요청/결과 `1.1.0`이 원래 사례와 대체 사례 리비전을 고정합니다. 새 독립 검토와 원래 사례 CAS 보류가 결과보다 먼저이며 독립 관찰한 IAM 회수와 원자적 종료가 이전 임무 PR보다 먼저입니다. 소스 연결로 적용 모드를 승격하지 않습니다. |
| H10 범위별 검토와 Console | implemented | [범위별 요청 처리](../../../services/core-control-plane/src/fdai/core/human_assignment/scoped_duty_requests.py); [Console 작업 공간](../../../console/src/routes/scoped-duty-workspace.tsx); [UI 체크포인트](../../internals/handover-lifecycle-hardening-20260914.md#h10-console-implementation-and-focused-critique-evidence): 단위 95개와 Playwright 6개 통과 | 현재 그룹/일정/범위 근거, Owner 2인 검토, 불변 자료/병합 관찰, 기존 사례 대체, 수동 GET이 실제 매핑 검토 경로에 연결되었습니다. 합성 API 검사는 전체 WCAG/평가표나 실제 범위의 근거가 아니며 IAM, 역할, ACL을 부여하지 않습니다. |
| 격리 멤버십 실행과 새 역방향 복구 | implemented | [Core 런타임](../../../services/core-control-plane/src/fdai/runtime/human_access_runtime.py); [격리 실행기](../../../services/isolated-executor/src/fdai_executor_service/human_access.py); [역방향 복구](../../../services/core-control-plane/src/fdai/runtime/human_access_recovery.py); [종료](../../../services/core-control-plane/src/fdai/delivery/human_access_closure.py); [체크포인트](../../internals/handover-lifecycle-hardening-20260914.md#execution-source-critique-checkpoint): 집중 132개와 별도의 실제 SQL/고정 에이전트 21개 통과 | 공유 SDK, 원래 HIL/준비, 같은 사람/그룹 잠금, 영속 의도/결과, 독립 Heimdall 결과가 연결되었습니다. Vidar가 제안/완료하고 Var가 새로 승인하며 Thor만 전달합니다. 역방향 복구 후 Core는 degraded입니다. 공급자/Owner 관찰은 합성이며 수는 겹칩니다. 기존 Core는 적용 모드를 차단하고 격리 적용은 별도 요건을 따릅니다. |
| 범위가 제한된 인수인계 준비도 보고서 | implemented | [준비도 모델](../../../services/core-control-plane/src/fdai/core/human_assignment/readiness.py); [재조정 워커](../../../services/core-control-plane/src/fdai/runtime/human_assignment_reconciliation.py); [기록된 근거](../../internals/handover-lifecycle-hardening-20260914.md) | 워커는 표본/전체/잘못된 기록/부분 결과, 결과 간격, 경고, 소스 완료로 비어 있는 공백 목록, 외부 차단 요인을 보고합니다. Owner 조회는 `shadow`, `operationally_ready=false`이며 보고가 경고 전달, 공급자 점검, 복구 변경, 승격을 수행하지 않습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-21 | implemented | Ingestion API의 fallback Pantheon transport를 정본 `fdai.pantheon.objects` Event Bus 토픽에 맞췄습니다. Terraform이 계속 명명 권위를 가지며, 이 변경은 담당 체계 해석, 알림 순서, RBAC, 승인 또는 실행 권한을 바꾸지 않습니다. | `current change`; ingestion composition 기본값, Event Bus 명명 계약 및 집중 독립 서비스 검사. | 배포 명명 소유 문서가 추적하는 보호된 Event Bus 이행 및 post-apply transport 증적을 보존합니다. |
| 2026-08-18 | in-progress | stewardship webhook과 저장소 handover intake를 구성하는 ingestion API composition이 개별 파서 대신 공유 계약으로 실행 장소를 해석하도록 했습니다. 장소가 선택하는 자격 증명이나 엔드포인트가 다른 서비스와 어긋날 수 없습니다. stewardship 수명주기 동작은 바뀌지 않았습니다. | `current change`, `services/document-ingestion-api/tests`가 다른 독립 서비스 suite와 함께 focused 874건 통과(스킵 1건), venue 게이트가 소스 트리 6개에서 OK 보고 | 아래의 미연결 병합 후 소유권 효과와 예약 신원 상태 점검은 계속 열려 있습니다. |
| 2026-08-13 | in-progress | 이전 출처를 재구성하지 않고 구현 원장을 도입했으며, 시작, 초안 생성, 서명된 병합 수신, 미구현 운영 효과를 구분하도록 수명 주기 주장을 바로잡았습니다. | `current change`; 구현 범위 표에 나열된 소스와 집중 검사. | 거버넌스 PR 게시, 병합 후 효과, 예약 실행되는 신원 상태 검사를 완료한 뒤 런타임 근거를 보존합니다. |
| 2026-08-16 | in-progress | 내용 기반 키, 검토 전용 렌더링, 닫힘 실패 초안 검증을 갖춘 인수인계 산출물에서 `RemediationPrPublisher`로 이어지는 멱등 경로를 조립했습니다. | `pytest services/core-control-plane/tests/core/stewardship/test_governance.py`가 모호한 전송 실패 이후 초안 PR 하나를 재사용하는 재시도와 PR 본문의 제한된 경고 렌더링을 포함해 집중 테스트 9개를 통과했습니다. | 운영 조립에 서비스를 연결하고 병합 후 소유권 효과와 예약 신원 상태 검사를 완료해야 합니다. |
| 2026-09-05 | in-progress | 영속 인수인계 초안을 처리하는 운영 런타임 워커를 추가했습니다. 잘못된 후보가 이후 레코드를 차단하지 않으며, 추적된 YAML을 검증할 때 런타임 신원 재정의를 무시하고, 이전 직렬화 초안과 호환되며, 내용 기반 증적과 Saga 감사를 한 번만 기록합니다. | `current change`; `stewardship_governance.py`; 집중 담당 체계, 런타임 거버넌스, 부트스트랩 테스트 149개와 Ruff, strict mypy 통과. | 실제 초안 PR 증적을 보존한 후 병합 결과와 예약 신원 상태 검사를 완료합니다. |
| 2026-09-05 | implemented | 서명된 병합 근거를 영향받는 소유자 알림, 일치하는 배정 결과, 재처리해도 동일한 shadow IAM 요청, 예약 Entra 생존 관찰과 연결했습니다. 소유권, IAM, 승인, 실행 권한은 계속 분리됩니다. | `current change`; 집중 Core 및 Operator 테스트; Core 서비스 Terraform 검증. | 관리형 배포, 재시작, 알림, Graph 복구, 승격 근거를 보존합니다. |
| 2026-09-06 | implemented | 보호된 플랫폼 워크플로를 배포 소유의 담당 체계 활성화 플래그, GitOps 대상, GitHub 자격 증명 및 병합 웹후크 시크릿에 연결했습니다. 명시적 저장소 변수를 활성화하기 전에는 비활성 상태를 유지합니다. | `current change`; `deploy-dev.yml`; 집중 Core 담당 체계 GitOps 워크플로 테스트. | 공급자 호스팅 GitHub App 토큰, 웹후크 시크릿 및 ChatOps 채널 시크릿을 구성한 뒤 관리형 계획, 적용 및 종단 간 초안 증적을 보존합니다. |
| 2026-09-06 | implemented | 정적 installation token 목표 설계를 Core 게시와 수집 병합 검증이 공유하는 갱신 가능한 GitHub App 자격 증명 임대로 교체했습니다. | `current change`; GitHub App 공급자, 어댑터, 서비스 materializer, guard 및 세 Terraform root; 집중 테스트 516개 통과. | 공급자 호스팅 App을 구성하고 설치한 뒤 자격 증명을 노출하지 않는 토큰 갱신 및 종단 간 초안/병합 근거를 보존합니다. |
| 2026-09-14 | implemented | 별도로 검토한 역순 제거 수명 주기와 범위가 제한된 읽기 전용 준비도 보고를 연결했습니다. 어느 쪽도 적용 모드를 활성화하거나 운영 준비 완료를 입증하지 않습니다. | `current change`; 위의 회수 및 준비도 소스; 주 구현 세션에서 실제 SQL 역할 테스트를 포함한 집중 작업 테스트 451개 통과를 보고했습니다. | H10 등 소스 공백은 열려 있습니다. #458의 공급자, 신원, GitHub App, 독립 IAM 결과, 대상 잠금, 훈련 근거와 알림, 문서, 배포, 코호트 근거는 별도 차단 요인입니다. |

2026-09-15 정정은 [영문 구현 이력](agent-stewardship-operations.md#implementation-history)에서
소스 완료와 릴리스 준비도를 구분합니다. 위의 기존 행은 그대로 보존한 과거 근거이며 현재
공백 목록이 아닙니다. 새 이력 행은 한국어 문서에 복사하지 않습니다.

### 남은 작업

- [x] 인수인계 산출물에서 `RemediationPrPublisher`로 이어지는 멱등 경로를 조립하고, 재시도가 `config/agent-stewardship.yaml`의 초안 PR 하나를 재사용함을 입증하는 집중 테스트를 통과시킵니다.
- [x] 저장된 인수인계 초안이 구성된 GitOps 게시기에 도달하도록 `StewardshipGovernanceService`를 운영 조립에 연결하고, 런타임 신원 재정의와 독립적으로 추적된 YAML을 검증하며, 반환된 PR 참조와 재처리 플래그를 내용 기반 증적에 저장합니다.
- [ ] 저장된 인수인계 초안 하나가 검토 전용 PR 하나를 열고, 재시작 후에도 두 번째 Saga 감사를 만들지 않고 같은 PR을 재사용함을 보여 주는 관리형 배포 증적을 보존합니다.
- [x] 병합된 담당 체계 YAML을 해석기로 검증하고, 영향받는 소유자를 계산하며, 배정 제안 다이제스트를 결합하고, Saga 감사, 재처리 안전 IAM 요청 게시, 수신자 알림을 입증하는 집중 테스트를 통과시킵니다.
- [x] 예약 실행되는 신원 상태 모니터를 구현하고, `stewardship_health:current` 및 `stewardship_health:last_success`에서 전이 시에만 수행되는 감사, 리비전이 일치하는 성공 관찰, 만료, Graph 실패 보존, 읽기 전용 변환 결과 동작을 입증하는 테스트를 보존합니다.
- [x] 갱신 가능한 GitHub App installation-token 공급자를 Core와 문서 수집에 연결하고, 동시 갱신과 만료 복구를 입증하며 App private-key 참조만 Key Vault에 보존합니다.
- [ ] 어떤 행이든 `validated`로 올리기 전에 실제 시작 바인딩, 안내형 제안 및 검토된 병합, 알림 전달, 감사 종료, 유효하지 않음에서 정상으로의 신원 복구를 보여 주는 배포 증적과 운영 훈련을 보존합니다.
- [x] **소스 작업 H10:** [범위별 요청](../../../services/core-control-plane/src/fdai/core/human_assignment/scoped_duty_requests.py)과 [실제 Console 작업 공간](../../../console/src/routes/scoped-duty-workspace.tsx)은 정확한 그룹/일정 주체, 현재 범위/유효 구간, 정적 대체 담당자, 검토된 사례 대체, 읽기 결과를 구현합니다. 기록된 단위 95개/Playwright 6개 검사는 한정된 합성 근거입니다.
- [x] **인수인계 소스 범위:** [Core 연결](../../../services/core-control-plane/src/fdai/runtime/core_handover.py), [의미 패키지 보존](../../../services/core-control-plane/src/fdai/rule_catalog/pipeline/distill/handover_retention.py), [실행 연결](../../../services/core-control-plane/src/fdai/runtime/human_access_runtime.py)로 [소스 체크리스트](human-agent-assignment-implementation-plan-ko.md#현재-변경의-근거와-남은-범위)를 완료했습니다. 근거는 준비도 출력이 아니라 보존된 체크포인트입니다.
- [x] **최종 소스 비판 검토:** 잔여 소스 구현 이후 서로 다른 통합 검토 12회를 완료했습니다. [FI-01부터 FI-12](../../internals/handover-lifecycle-hardening-20260914.md#final-integrated-critique-after-remaining-source-implementation)에 미해결로 확인된 Medium/High 소스 문제는 없습니다.
- [x] **#946 게시 근거:** 검토된 영문/한국어, 정본 생성, 정상 훅과 보호된 #1014 전달을 완료했으며 정확한 헤드와 병합 후 CI가 통과했습니다. #1017은 자체 후속 전달을 추적합니다.
- [x] **로컬 UI 근거:** [#1017](../../internals/handover-ui-evidence-20260915.md)은 서로 다른 합성 브라우저 시나리오 28개, 단위 검사 127개, 집중 비판 10회와 최종 검토 10회, 모든 평가 기준 ID를 기록합니다. 실제 보조 기술 출력은 측정하지 않았습니다.
- [ ] **사람 확인과 운영 근거:** 실제 스크린 리더 안내와 별도로 통제되는 #458/Teams/문서/배포/코호트/훈련 증적을 [현행 독립 경로](../deployment/installable-deployment-cli-ko.md)로 보존합니다. 소스 검토는 전체 WCAG/UI 점수, 운영 수락이나 승격을 허가하지 않습니다.

근거에 기반한 T2 `HandoverInterpreter`는 선택적인 배포 연결로 남습니다. 결정론적
추출기와 정확한 Graph 확인은 이 연결 없이 동작하며 기본 해석기는 추측하는 대신
검토 대상으로 보류합니다.

## 수명 주기 계약

### 운영 시작

Operator API는 경로를 구성하기 전에 담당 체계 맵을 읽습니다. 운영 구성 함수와 같은 환경
매핑을 해석기에 전달하므로 배포 재정의와
`FDAI_STEWARDSHIP_REQUIRE_BINDINGS`가 변환 결과를 제공하는 프로세스에서 분리되지 않습니다.

`enable_operator_api=true`인 배포는 다음 값을 제공합니다.

- 실제 유지관리자 OID 최소 1개, 권장 2개
- 자율 운영이 아닌 모든 Pantheon 에이전트의 책임 담당 연결
- 예약 생존 검사를 위한 `FDAI_IAM_DIRECTORY_PROVIDER=entra`
- 60초 이상의 생존 간격

Terraform은 적용 전에 완전성을 확인합니다. 해석기는 이행 중 스키마 v1과 새 맵의 v2를
허용합니다. 시작 시 서로 다른 실제 유지관리자와 담당 주체, UUID 형식의 개인 채널 키,
정확한 환경 토큰 형식, 금지된 역할의 부재, 자리 표시자 정책, 에이전트 일치, 책임과 임무 값,
자율 사유, v2 주 담당 및 별도의 백업/에스컬레이션 담당 범위를 확인합니다. 버전 1은 계속
동작하지만 추론한 임무와 백업 누락을 점검 결과로 표시합니다.

### 예약 신원 상태 검사

`StewardshipIdentityHealthWorker`는 운영 사용자 디렉터리를 Core `IdentityDirectory` 프로토콜에
연결합니다. 유지관리자와 사용자 담당자의 OID를 주요 처리 경로 밖에서 검사합니다.

모니터는 `stewardship_health:current`에 리비전이 있는 상태 전환 스냅샷을 저장합니다.

- 현재 오래된 신원 점검 결과
- 전환 시각
- 단조 증가 리비전
- 감사 상관관계에 사용하는 결정론적 지문

검사를 성공할 때마다 관찰 시각, 만료 시각, 일치하는 전환 리비전으로
`stewardship_health:last_success`를 교체합니다. 결과가 같으면 성공 관찰만 갱신하고 감사 기록을
만들지 않습니다. 정상에서 오래됨 또는 그 반대로 바뀌면 전환 스냅샷을 원자적으로 갱신하고
`stewardship.identity_health_transition`을 추가합니다. Graph 실패는 오류 유형만 기록하고
다음 주기에 재시도합니다. 하트비트를 갱신하거나 모든 신원을 오래됨으로 표시하거나 컨트롤
루프를 중지하지 않습니다. 첫 검사는 이름이 지정된 Core 백그라운드 작업에서 시작하므로
Graph 지연이 Operator API 시작을 늦추지 않습니다. 두 스냅샷이 유효하고 리비전이 일치하며
하트비트가 만료되지 않았을 때만 Operator API가 오래된 신원 점검 결과를 읽기 전용 화면에
반영합니다. 상태가 없거나 형식/리비전이 맞지 않거나 만료되면 기본 맵을 숨기지 않고
`identity_health.status=unavailable`로 표시합니다.

### 초안 PR 생성

수집 워커가 `HandoverDraftArtifact`를 저장하면 선택적 `StewardshipGovernanceService`가
같은 Core 해석기로 렌더링된 YAML을 검증하고 `RemediationPrPublisher`로 초안 PR을 게시합니다.

인수인계 Console 양식은 할당마다 정본 에이전트 이름, 책임, 주체 유형, 표시 이름 또는
이메일을 담은 명시적 구조화 줄 하나를 만듭니다. 결정론적 추출기는 고정 에이전트 이름 15개
중 하나만 허용합니다. 게시 후에는 PR 참조, URL, 재생 플래그를 저장하므로 인증된 제출자가
재시도해도 같은 멱등 제안을 열 수 있습니다.

Slack과 Teams는 정확한 `/handover` 첨부 지시문과 Contributor 역할 하한을 통해서만 같은
경로에 들어갑니다. [conversation-attachments-ko.md](conversation-attachments-ko.md)를 참조하세요.

PR 후보는 현재 검증된 맵에 추가하는 변경입니다. 근거에 기반한 매핑은 주체를 추가하거나
태그를 바꾸지만 기존 담당자, 유지관리자, 채널, 임계값은 보존합니다. 서비스는 매핑되지 않은
초안 에이전트를 자율 운영으로 바꾸거나 담당자를 자동 제거하지 않습니다. 제거는 사람이
검토된 PR에서 명시적으로 수행해야 합니다.

제안 계약은 다음과 같이 고정됩니다.

| 필드 | 값 |
|-------|-------|
| 대상 경로 | `config/agent-stewardship.yaml` |
| 모드 | `shadow` |
| Labels | `shadow`, `governance`, `stewardship` |
| 멱등성 키 | `handover:<upload_id>` |
| Rollback | 병합된 구성 커밋 revert |
| Actor | 인증된 upload-session `actor_id` |

게시기는 쓰기 전에 Git 호스트에서 기존 브랜치를 찾습니다. 게시 후 서비스는 영속 제안 상태를
점유하고 `stewardship.change.requested`를 같은 트랜잭션에 추가합니다. 첫 점유만 운영 알림을
보냅니다. 원격 PR 생성 후 로컬 점유 전에 프로세스가 멈추면 재시도가 기존 PR을 찾아 중복 없이
누락된 로컬 상태를 복구합니다. 로컬 상태가 있으면 원격 호출 전에 상관관계 ID로 증적을
확인하므로 첫 PR이 닫힌 뒤에도 업로드 재처리로 다른 PR을 만들지 않습니다.

승인된 사용자 할당의 권한 부여 사례도 같은 게시기를 사용하지만 더 엄격한 입력 검사를 적용합니다.
이 전역 맵에는 `scope:platform` 임무만 표현할 수 있으며 렌더링된 후보는 자율 운영이 아닌
모든 에이전트에 스키마 v2의 주 담당 및 백업/에스컬레이션 범위를 갖춰야 합니다. 제안 상태는
할당 사례 ID, PR 참조, 정본 후보 다이제스트를 연결합니다. 서명 병합은 병합 다이제스트가
제안과 일치할 때만 사례의 담당 체계 결과를 기록합니다. 일부 맵이나 불일치 병합은 보류하며
IAM 적용을 시작하지 못합니다. 일치하는 증적을 저장하면 거버넌스 서비스가 멱등적인
`human.assignment.iam_apply_requested` 하나를 형식화된 입력에 게시합니다. 수집 게이트웨이는
Graph 쓰기 신원을 받지 않습니다. 저장소, Event Hubs, 모델, 담당 체계 어댑터는 정확히 연결된
동일한 `FDAI_MI_CLIENT_ID`를 사용하며 주변 자격 증명이나 시스템 할당 principal로 대체하지 않습니다.

제거에는 요청 및 결과 전송 `1.1.0`, 고정된 원래 사례와 대체 사례의 리비전, 새 독립 제거
검토를 갖춘 `revocation` 의도를 사용합니다. 기존 부여 승인으로 제거를 승인할 수 없습니다.
Core는 결과 처리 전에 맵을 바꾸지 않고 원래 사례에 영속 CAS 보류를 설정합니다. 순서는
`approved -> iam_applying -> iam_revoked -> ownership_pr_open -> revoked`입니다.
독립적으로 기록된 IAM 회수 증적과 봉인된 검토가 있어야 검토 전용 이전 임무 PR을 만들 수
있습니다. 렌더링은 정확한 이전 임무, 고정된 활성 대체 사례, 현재 맵 항목을 다시 읽고
관련 없는 에이전트, 유지관리자, 채널, 역할을 보존합니다. 정확한 서명 병합은 재부여 요청
없이 원래 보류를 종료합니다. 현재 소스 경로에는 격리 실행, 정확한 현재 승인, 대상 잠금,
독립 결과, 원자적 종료가 포함됩니다. 실제 SQL과 고정 에이전트 검사는 합성 공급자/Owner
관찰을 사용합니다. 열린 #458의 실제 결과, 권한, 훈련, 승격은 별도 근거입니다.

### 범위별 담당 체계 검토

H10은 개인 IAM 할당이나 전역 v2 맵 편집이 아니라 별도의 담당 체계 전용 범위별 임무 사례를
사용합니다. 현재 그룹/일정 확인, 정확한 범위와 유효 기간, 정적 대체 담당자, 독립 Owner 두 명,
불변 자료, 현재 사람 병합 관찰로 만료 시간이 있는 범위별 결과를 결정합니다. 실제
`/agent-oversight/mapping-reviews` 작업 공간은 기존 API 6개를 사용하며 HTTP202는 수동 GET까지
`awaiting_core`입니다. 검토된 사례 대체 후 장애가 발생해도 이전 임무를 되살리지 않습니다.
단위 95개와 실제 경로/컴포넌트 Playwright 6개 검사가 기록되어 있지만 전체 WCAG/평가표나
실제 범위의 근거는 아닙니다. 그룹 선언은 IAM, 역할, 문서 ACL을 부여하지 않습니다.

### 통제된 멤버십과 복구

[실행 계획](human-agent-assignment-implementation-plan-ko.md#묶음-5---통제된-entra-멤버십-적용)은
공유 SDK와 불변 Core 자료를 전용 격리 Graph 쓰기 경로에 연결합니다. Core에는 변경 신원이
없습니다. Var는 원래 5분 HIL 구간을 유지하며 Reader/Contributor 접근에는 현재 적격 Owner
한 명, Approver/Owner 접근에는 서로 다른 현재 적격 Owner 두 명을 요구합니다. 요청자/대상을
제외하고 기존 역할/ActionType 승인 정책을 적용합니다. 원래 사례 검토는 실행 승인이 아닙니다.
Muninn의 준비는 `r -> r+1`로 진행하지만 승인된 `expected_revision=r`, Action 바이트, 만료는
바꾸지 않습니다.

Thor만 공통 안전장치 7개와 양방향에서 같은 정규화된 사람/그룹 잠금을 통해 전달합니다.
현재 비상 정지/성능 저하 제한, 승인, 원본, 승격 검사는 필수입니다. 영속 Executor 의도/이전
상태/결과는 독립 성공 근거가 아닙니다. Heimdall 관찰, Forseti 판정, Saga 봉인, 공통 원자적
잠금 해제 후 종료가 Core 사례 결과보다 먼저입니다. 새 `recovery_of`는 기존 ActionType을
재사용하여 정확한 소유 변경의 이전 상태/현재 계보에 연결합니다. Vidar는 소유 토픽으로
제안과 완료를 처리하고 Var는 새 승인과 기존 허용 목록을 요구하며 Thor만 전달합니다.
독립적으로 관찰한 역방향 종료 후에도 Core는 `degraded`이며 임무나 목표 권한을 복원하지
않습니다. `ALREADY_APPLIED` 역변경, 불확실한 변경 재시도, 참조만으로 롤백 성공을 선언하는
행위는 허용하지 않습니다. 기존 Core 어댑터는 적용 모드를 계속 차단하고 격리 적용은 별도
승격을 요구합니다. 모든 장소에 같은 원본/구성 규칙을 적용하고 로컬 권한 전환은 허용하지
않으며 shadow는 변경하지 않습니다.

### 읽기 전용 인수인계 준비도

기존의 범위가 제한된 재조정 워커는 표본별 개수, 전체 개수, 잘못된 기록 수, 부분 조회 여부,
경고 관찰, 소스 공백, 외부 차단 요인도 기록합니다. 평균 결과 증적 간격은 결과가 두 개 있는
사례만 사용하고 해당 사례가 없으면 `null`입니다. 전체 모집단이나 제품 전체의 지연 시간을
입증하지 않습니다. 잘못된 행도 집계에서 숨기지 않습니다.

Owner 전용 `GET /handover/readiness`는 보고서를 10분간 읽을 수 있습니다. 만료되거나 미래
시각이거나 형식이 잘못된 보고서는 사용할 수 없습니다. 모든 보고서는 `shadow` 및 운영
준비 미완료를 유지합니다. 보고는 경고 전달, 공급자 점검, 복구 변경, 승격을 수행하지
않습니다. `source_gaps=[]`는 한정된 소스 요건의 완료이지 릴리스 승인 결정이 아닙니다.
`operationally_ready=false`와 외부 차단 요인은 남습니다. 연결된 Mimir 비공개 패키지 보존도
배포된 원본 정책이나 법적 보존/원본 가용성을 모를 때의 내용 삭제 권한을 입증하지 않습니다.
보고서나 실제 SQL 역할 테스트만으로 배포 환경의 실제 디렉터리, 코호트, 문서 원본 상태를
검증하지 않습니다. [현재 변경 경계](human-agent-assignment-implementation-plan-ko.md#현재-변경의-근거와-남은-범위)를 참조하세요.

### 병합 관찰

거버넌스가 활성화된 경우에만 수집 게이트웨이가
`POST /ingestion/webhooks/github/stewardship`을 등록합니다. 경로는 최대 1 MiB를 허용하고 콘솔
Entra 흐름 대신 HMAC 인증을 사용합니다.

어댑터는 다음 순서로 검사합니다.

1. `X-Hub-Signature-256`을 상수 시간으로 비교합니다.
2. `pull_request` 전달 ID와 구성된 `owner/repository`를 요구합니다.
3. `action=closed`, `merged=true`, PR 번호, 병합 커밋 SHA를 요구합니다.
4. 파일 100개 단위의 제한된 페이지로 변경 파일을 최대 3000개 조회하고
  `config/agent-stewardship.yaml`을 요구합니다.
5. 병합 커밋에서 파일을 다시 가져와 공백으로 줄바꿈된 GitHub의 base64 UTF-8 내용을
   디코딩합니다.
6. 병합 맵을 검증하고 이전/현재 맵에서 영향받는 에이전트를 계산합니다.
7. 추가 전용 병합 감사와 함께 `stewardship_governance:merge:<delivery_id>`를 점유합니다.
8. 병합 맵의 영향받는 담당자와 FDAI 유지관리자에게 알립니다.

GitHub 로그인은 `github:<login>`처럼 공급자를 명시한 감사 신원으로 기록하며 Entra OID로
표현하지 않습니다. 중복 전달은 두 번째 감사나 알림 없이 성공을 반환합니다.

## 영향받는 소유자 계산

차이는 결정론적으로 계산합니다.

- 변경된 에이전트 블록은 해당 에이전트에만 영향을 줍니다.
- 유지관리자, 개인 채널, 에스컬레이션 시간 초과, 담당 범위 임계값은 모든 에스컬레이션
  체인을 바꿀 수 있으므로 에이전트 15개 전체에 영향을 줍니다.
- 워크플로 문서는 기존의 재귀적인 Pantheon 이름 추출을 계속 사용합니다.
- 알 수 없는 에이전트 이름은 해석기가 먼저 차단하므로 차이 계산에 도달하지 않습니다.

요청 알림은 현재 활성 맵을 사용합니다. 병합 알림은 새 책임 담당자가 인수인계 결과를 받도록
병합된 맵을 사용합니다.

## 배포 구성

문서 인제스트, Operator API, ChatOps를 활성화한 후에만
`enable_stewardship_governance=true`를 설정하세요. Terraform은 다음 배포 소유 값을
요구합니다.

| 입력 | 런타임 연결 | 저장 위치 |
|-------|-----------------|---------|
| `stewardship_maintainers` | `FDAI_MAINTAINERS` | non-secret 환경 구성 |
| `stewardship_agent_bindings` | `FDAI_STEWARD_<AGENT>` | non-secret 환경 구성 |
| `gitops_owner`, `gitops_repo` | `FDAI_GITOPS_OWNER`, `FDAI_GITOPS_REPO` | non-secret 환경 구성 |
| `github_app_client_id`, `github_app_installation_id` | `FDAI_GITHUB_APP_CLIENT_ID`, `FDAI_GITHUB_APP_INSTALLATION_ID` | 비밀이 아닌 환경 구성 |
| `github_app_private_key` | `FDAI_GITHUB_APP_PRIVATE_KEY` | Key Vault 참조 only |
| `gitops_token` | `FDAI_GITOPS_TOKEN` | Key Vault 참조 only; 범위가 제한된 호환 경로 |
| 거버넌스 워커 제어 | `FDAI_STEWARDSHIP_GOVERNANCE_ENABLED`, `FDAI_STEWARDSHIP_GOVERNANCE_INTERVAL_SECONDS`, `FDAI_STEWARDSHIP_GOVERNANCE_BATCH_LIMIT` | 비밀이 아닌 환경 구성 |
| 영속 거버넌스 증적 | `FDAI_STATE_STORE_DSN` | Key Vault 참조 only |
| `github_webhook_secret` | `FDAI_GITHUB_WEBHOOK_SECRET` | Key Vault 참조 only |
| `chatops_webhook_url` | `FDAI_CHATOPS_WEBHOOK_URL` | Key Vault 참조 only |

GitHub App에는 어댑터에 필요한 저장소 내용, 풀 리퀘스트, 메타데이터, 이슈 레이블 권한만
부여하는 것이 좋습니다. Core와 문서 수집은 Key Vault 기반 App 개인 키로 저장소 범위의
설치 토큰을 발급합니다. 공급자는 수명이 짧은 RS256 App JWT를 서명하고 동시 갱신을
직렬화하며 검증된 만료 이후에는 토큰을 캐시하지 않고 1시간 설치 토큰 임대가 끝나기 전에
갱신합니다. 토큰과 JWT는 로그에 기록하지 않습니다. 정적 `gitops_token`은 상호 배타적인 호환
입력으로만 허용합니다. 풀 리퀘스트 이벤트용 GitHub 웹후크는 게시된 수집 게이트웨이 경로를
가리키도록 구성하세요.

검토된 활성화, 저장소/App 연결, 보호된 비밀 참조는 선택한 독립 배포의 비공개 구성으로
제공하세요. `fdaictl provision azure`가 정확한 계획에 대한 사람 승인과 전용 관리 호스트
신원을 조정하며 GitHub Actions는 테넌트 계획/적용 전송 경로가 아닙니다. 과거 근거의
워크플로 변수로 현재 배포가 구성되지는 않습니다. 현재 App, 서명 웹후크, 독립적으로 승인한
채널의 선행 조건을 검증하기 전에는 거버넌스를 비활성 상태로 유지하세요. 정적 개인 토큰으로
대체하거나 비밀 값을 채팅, CLI 인자, 소스 관리, 공개 이슈 근거에 넣지 마세요.

## 실패 및 복구

| 실패 | 동작 | 복구 |
|---------|------|------|
| 자리 표시자 또는 누락된 담당자 | Terraform 계획 또는 프로세스 시작 실패 | 실제 배포 연결을 제공하고 재시작합니다. |
| Graph 사용 불가 | 현재 담당 체계는 유지하며 오래된 신원 결과를 만들어내지 않음 | 다음 모니터 주기에 재시도합니다. |
| GitHub 게시 중단 | 워커가 같은 업로드 ID로 재시도 | 원격 멱등성 조회로 기존 PR을 복구합니다. |
| 알림 전달 실패 | 라우터가 대체 경로를 시도한 후 HIL 에스컬레이션을 저장 | 채널을 복구하고 감사 근거에서 재생합니다. |
| 잘못된 웹후크 서명 | GitHub I/O 전에 요청 차단 | GitHub 웹후크 시크릿을 수정합니다. |
| GitHub App 토큰 발급 또는 갱신 실패 | 초안 게시와 병합 재조회가 쓰기나 성공 증적 없이 차단됩니다. | App 설치 또는 개인 키 연결을 복구하고 같은 멱등성 키로 재시도합니다. |
| 관련 없는 PR 병합 | 상태 변경 없이 전달 확인 | 조치가 필요하지 않습니다. |
| 중복 병합 전달 | 영속 점유가 변경 없음 반환 | 중복 감사나 알림을 만들지 않습니다. |

## 검증

배포 전에 집중 담당 체계 검사를 실행하세요.

```bash
bash scripts/governance/check-stewardship.sh
uv run pytest services/core-control-plane/tests/core/stewardship services/core-control-plane/tests/delivery/stewardship \
 services/core-control-plane/tests/delivery/ingestion_gateway/test_handover.py -q --no-cov
terraform -chdir=infra validate
```

별도로 승인된 배포 후 선택한 훈련의 범위와 기한 안에서 다음을 관찰하세요. 현재 신원,
정확한 승인, 역방향 복구/재시작/장애 훈련, 독립 코호트는
[근거 절차](../../user-guide/guides/validate-ownership-handover-ko.md)를 따릅니다.

1. `GET /stewardship`이 15개 에이전트와 예상 커버리지 발견 사항을 반환합니다.
2. `stewardship_health:current`가 존재하고 `stewardship_health:last_success`가 동일 개정 번호와
  만료되지 않은 `expires_at`을 가집니다.
3. 합성 인수인계 업로드가 초안 PR 하나와 요청 감사 하나를 생성합니다.
4. 업로드 재처리가 동일한 PR 참조를 반환합니다.
5. 검토된 테스트 변경 병합이 병합 감사 하나와 운영 알림 하나를 생성합니다.
6. 같은 GitHub 전달 ID를 다시 보내도 두 번째 기록을 생성하지 않습니다.
7. 승인된 제한 시간의 실제 토큰 갱신 관찰에서 자격 증명 값 없이 갱신과 동시 사용 근거를
   보존합니다. 주입된 시계 검사는 로컬 공급자 동작만 입증합니다. 배포 시계를 바꾸거나
   합성 갱신을 실제 관찰이라고 주장하지 마세요.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 남은 음성과 운영 근거 | [검증 가이드](../../user-guide/guides/validate-ownership-handover-ko.md) |
| 소유권 스키마 및 인계 개념 | [agent-stewardship-and-handover-ko.md](agent-stewardship-and-handover-ko.md) |
| 알림 경로 및 대체 경로 | [channels-and-notifications-ko.md](channels-and-notifications-ko.md) |
| 사람 권한 확인 | [user-rbac-and-identity-ko.md](user-rbac-and-identity-ko.md) |
| Azure 배포 입력 | [../deployment/deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md) |
