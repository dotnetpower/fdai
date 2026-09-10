---
title: 보안과 아이덴티티
translation_of: security-and-identity.md
translation_source_sha: 2d2c9faf96f4dce9ff6a839056fe670be3b970ca
translation_revised: 2026-09-11
---

# 보안과 아이덴티티

자율성은 실행 권한을 요구하며, 그래서 아이덴티티와 안전이 가장 리스크 높은 표면입니다.
최소권한과 되돌릴 수 있음은 협상 불가입니다. 이 문서는 보안 모델의 진실 원본입니다;
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 의
컨트롤 루프와 안전 불변식,
[app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md) 의 토폴로지,
[coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)
의 코드/CI 게이트를 보완합니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 워크로드 신원과 승인 및 실행 분리 | validated | `config/independent-service-live-evidence-manifest.json`; `infra/services/`; `shared/providers/workload_identity.py`; SD-08 및 IS-09 근거 | 5개 서비스 배포 근거는 서로 다른 신원을 입증하고 전환 후 Isolated 실행기만 효과를 보유할 수 있게 합니다. |
| 실행기 안전조건과 독립 효과 종결 | in-progress | `packages/service-contracts/src/fdai_service_contracts/execution_safeguards.py`; `core/executor/{safeguards,safeguard_proofs,lock,lock_continuity,idempotency_reservation*,audit_intent,target_dispatch_fence*,safeguard_dispatch*,safeguard_evidence_lifecycle,post_release_closure*}.py`; `delivery/persistence/postgres_{resource_lock,idempotency_reservation,audit_intent,target_dispatch_fence,safeguard_dispatch,post_release_closure}.py`; 집중 안전조건, 잠금, fence, 영속성, 수명 주기, 이행 테스트; `config/constitution-traceability.json`의 `FDAI-CONST-007` 요구 사항; 이슈 `#81`, `#627`, `#628`, `#633`, `#681`; 완료된 이슈 `#620`, `#660`, `#664`, `#669`-`#672`, `#674`, `#678`-`#680`, `#692`-`#694` | 증명 묶음, 운영 잠금 근거, 최종 처리기, 소유권 연속성 모델, 예약 및 감사 저장소, 대상 전체 fence, 영속화된 디스패치 checkpoint, 원자적 해제 후 종결, 공급자 중립 수명 주기 오케스트레이터를 권한이나 효과 검증 주장 없이 구현했습니다. 실제 생성기, Isolated 실행기 검증, 통제된 효과 근거는 열린 작업으로 남아 있습니다. |
| 전역 kill switch와 break-glass 컨트롤 | implemented | `core/rbac/kill_switch_command.py`; `core/control_loop/_execution.py`; `core/conversation/_write_break_glass_tool.py`; 집중 RBAC 및 제어 루프 테스트 | 개정 번호 안전 상태, 실패 시 차단 갱신, 권한 상한, 시간 제한 활성화, 감사 및 호출 경로가 있습니다. 보존된 운영 예행 연습은 아직 필요합니다. |
| 자동화 보류 복구 승인 강화 | in-progress | `core/workflow/{recovery_admission,automation_hold}.py`; 보호 조건을 적용한 메모리 내 및 PostgreSQL 상태 어댑터; [프로세스 자동화 구현 상태](../../roadmap-implementation/decisioning/process-automation.md#implementation-status); 이슈 `#622`, `#630`, `#640` | 정확한 승인과 원자적 보류 해제 기본 연산을 구현했지만 운영 보상은 여전히 기존 해제 호출을 사용합니다. `#630`이 해당 통합, `#640`이 최종 실행 경로 fence를 담당합니다. FDAI-CONST-009는 `implemented`를 유지합니다. |
| 데이터 보호와 privacy 근거 | in-progress | [데이터 거버넌스 구현 상태](data-governance-ko.md#구현-상태); 해당 문서가 인용한 민감정보 제거 및 보존 경로; 이슈 `#371` | 주요 경계는 이제 공유 최소화와 민감정보 제거를 구현했지만 배포 privacy 승인과 보존된 운영 근거는 계속 열려 있습니다. |
| 사전 사람 권한 부여(A3-E) | in-progress | `config/constitution-traceability.json`의 `FDAI-CONST-008` 요구 사항; [에스컬레이션과 사전 권한](../decisioning/escalation-and-standing-authority-ko.md); `core/standing_authority/{lease,promotion_candidate*,shadow_cohort_runner}.py`; 완료된 이슈 `#331`, `#621`, `#629`, `#631`; 이슈 `#632` | 스키마, 평가기, 변경할 수 없는 수명 주기, 읽기 시점 fence, 효과 전체 구간 lease, 비활성 승격 후보 수명 주기, 로컬 합성 shadow 집단이 있지만 의도적으로 연결하지 않은 상태입니다. 통제된 런타임 근거와 별도 승인된 승격이 남아 있습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-09-11 | implemented | 보류된 복구 최종 처리를 현재 Process revision, 정확한 효과 주장 및 generation, 해제 증적, 완료 digest, 기존 최종 커밋 부재에 결속했습니다. 하나라도 일치하지 않으면 이제 전환을 차단합니다. | `current change`; `recovery_terminalization.py`; 집중 최종 처리 사전 조건 테스트 27개 통과. | #630에서 운영 보상을 보호된 해제 기본 연산으로 연결합니다. |
| 2026-09-10 | implemented | 정확한 매니페스트, 완전한 분모 계산, 콘텐츠에 결속된 자료 집합과 증적, 고정 로컬 제한 시간, 레지스트리 전후 무결성, 심볼릭 링크에 안전한 명시적 산출물 작성기를 갖춘 결정론적 로컬 합성 A3-E shadow 집단을 추가했습니다. 개발 근거만 기록하며 실행 또는 승격 권한을 부여하지 않습니다. | `current change`; `core/standing_authority/shadow_cohort_runner.py`; 최종 회귀 테스트 2개 전 집중 standing-authority 테스트 174개 통과 후 40개 집단 테스트 구간 재실행; Ruff, strict mypy 통과; 독립 TOCTOU 및 자료 집합 결속 문제를 수정했고 재비평에서 Medium 이상 발견된 문제가 없습니다. | #631의 로컬 구현 잔여 작업은 없습니다. #632에는 별도 승인된 통제된 런타임 근거와 독립 승격 검토가 필요합니다. |
| 2026-09-10 | implemented | 비활성 shadow 전용 A3-E 승격 후보 수명 주기를 추가했습니다. 정확한 권한 및 lease 개정, 검토자 허용 목록, 근거 요구 사항, 인증된 생성자와 검토자 분리, 콘텐츠에 결속된 취소, 결정적 거부, 2단계 감사, 변경 불가 재실행, 정적 비가져오기 검사는 실행 또는 승격 권한을 부여하지 않고 권한 있는 레지스트리를 변경하지 않습니다. | `current change`; `core/standing_authority/promotion_candidate*.py`; 집중 테스트 52개 통과; Ruff, format, strict mypy, 모든 파일 크기 제한 통과; 검토자 권한과 취소 다이제스트 결속에 대한 독립 비평 발견을 수정했으며 재비평에서 Medium 이상 발견된 문제가 없습니다. | #629의 로컬 구현 잔여 작업은 없습니다. 별도 승인된 #632 승격 전에 범위가 제한된 #631 shadow 집단을 보존합니다. |
| 2026-09-10 | implemented | 비활성 효과 전체 구간 A3-E lease와 공급자 커밋 fence 계약을 추가했습니다. 정확한 수명 주기 개정, 작업, 대상, 실행기 신원, 소스 개정, 제한된 유효 기간, fence 세대, 안정된 공급자 멱등성, checkpoint, 최종 해제, 권위 있는 재시작 조정은 모두 권한 없는 레코드로 유지됩니다. 원자적 lease 검증, fence, 멱등성, 상태 조정을 제공하지 않는 공급자는 부적합하며 운영 권한 경로는 lease를 가져오지 않습니다. | `current change`; `core/standing_authority/lease.py`; `shared/providers/standing_authority.py`; 집중 테스트 82개 통과; Ruff, format, strict mypy 통과; 수정된 정적 gate가 권한 경로 파일 208개 검사; 독립 비평에서 Medium 이상 발견된 문제가 없습니다. | #621의 로컬 구현 잔여 작업은 없습니다. #629 검토와 #631 shadow 근거를 마칠 때까지 lease를 비활성으로 유지한 뒤 #632 승격을 별도로 승인합니다. |
| 2026-09-10 | implemented | 정확한 해제 후 종결 계획, 엄격한 레코드, Core 소유 PostgreSQL 트랜잭션을 추가했습니다. 안정된 예약 시도마다 해제 전 근거, 예약, 대상 fence의 이전 상태를 잠그고, 최종 또는 격리 예약 상태, 변경 불가 감사 종결, 현재 조정 상태, 결정적 outbox, 정확한 fence 상태를 원자적으로 기록합니다. 격리는 동일 세대의 권위 있는 상태 또는 독립 검증기 근거로만 해제합니다. 동일 작업 재실행은 누락된 최종 근거를 복구하지 않고 검증하며 독립 효과 상태는 `pending`을 유지합니다. | `current change`; `post_release_closure*.py`; `postgres_post_release_closure.py`; Core 서비스 이행 파일 및 소유권 매니페스트; 집중 모델, 영속성, 이행 테스트 모음 통과; 새로운 pgvector/PostgreSQL 16 이행과 병렬 종결, 재시작 읽기, 격리 조정, outbox 중복 제거 시나리오 통과; Ruff, strict mypy 통과. | #694의 로컬 구현 잔여 작업은 없습니다. #681에서 공유 근거 수명 주기 조정기를 구현합니다. |
| 2026-09-11 | implemented | 공급자 중립 Core 안전조건 근거 수명 주기 오케스트레이터를 추가했습니다. 정확한 단계 순서를 적용합니다: 잠금 획득, 예약, 감사, fence, 묶음, 준비, 전송 중, 디스패치(같은 잠금 핸들), 관측, 해제 전 연속성 checkpoint, 해제 대기 fence. 실패 시 차단하는 사전 단계 검증은 잘못된 예약 상태, 잘못된 fence 상태, 비활성 잠금, 권한 부여 묶음을 거부합니다. 근거 충돌과 중복은 디스패치 전에 중단됩니다. 알 수 없는 대상 시스템 상태, 실패한 전송, 미확인 연속성은 대상을 격리합니다. 취소는 디스패치 없이 fence를 해제합니다. 결과는 최종 묶음 다이제스트와 최종 근거를 승인, 실행, 승격, 대상 시스템 커밋, 효과 검증 권한 없이 전달합니다. | `current change`; `safeguard_evidence_lifecycle.py`; `test_safeguard_evidence_lifecycle.py`; 전체 순서, 모든 실패 경계, 취소, 격리 경로, 경쟁, 근거 충돌, 권한 거부, 최종 형태 검증을 다루는 집중 테스트 21개; Ruff, format, strict mypy 통과. | #681 Core 오케스트레이터를 구현했습니다. #694 해제 후 원자적 종결 저장소 통합이 열려 있습니다. 실제 생성기, Isolated 실행기 검증, 통제된 효과 근거는 #627에서 계속합니다. |
| 2026-09-10 | implemented | 정확한 묶음, 디스패치 시작, 전송 및 권위 있는 대상 시스템 관측, 새로운 해제 전 잠금 연속성 checkpoint를 영속화하는 단조 안전조건 디스패치 근거 수명 주기를 추가했습니다. 엄격한 codec, compare-and-set 저장, 재시작 복구를 제공하며 권한이나 효과 검증 주장을 부여하지 않습니다. | `current change`; `safeguard_dispatch*.py`; `postgres_safeguard_dispatch.py`; 서비스 이행 파일; 집중 모델, 영속성, 이행 테스트 86개 통과, DSN 미구성으로 live PostgreSQL 테스트 1개 건너뜀; Ruff 통과. | #693의 로컬 구현 잔여 작업은 없습니다. #694에서 해제 후 원자적 종결을 완료한 뒤 #681에서 공유 조정을 구현합니다. |
| 2026-09-10 | implemented | 예약 직후이면서 감사, 묶음, 대상 시스템 작업 전에 대상별 고유 generation fence 디스패치 레코드를 추가했습니다. 정확한 레코드 CAS와 읽기는 감사 및 묶음 근거를 보존하고, 해결될 때까지 대상의 모든 변경을 차단하며, 해제 뒤에도 격리를 유지합니다. 격리 해제에는 새로운 조정 근거가 필요하고 새 generation에는 더 늦은 획득이 필요합니다. | `current change`; `target_dispatch_fence.py`; 엄격한 코덱; PostgreSQL 저장소 및 이행 파일; 로컬 모델 및 영속성 검사 18개, 이행 inventory 검사 64개, live PostgreSQL 경쟁 및 재시작 시나리오 1개 통과; Ruff, strict mypy 통과; 독립 비평에서 Medium 이상 발견된 문제가 없습니다. | #692의 잔여 작업은 없습니다. #693에서 묶음, 디스패치, 해제 전 checkpoint를 저장하고, #681 조정 전에 #694에서 해제 후 종결을 완료합니다. |
| 2026-09-10 | implemented | 운영 PostgreSQL 근거 리소스 잠금을 구현했습니다. 하나의 전용 세션이 advisory key를 획득하면서 데이터베이스 및 backend 신원을 원자적으로 확보하고, 모든 평가에서 PostgreSQL 시각과 정확한 세션 및 키를 다시 검사합니다. 상실, 대체, 잘못된 근거, 취소는 핸들을 사용할 수 없게 만들고 다른 세션을 unlock하지 않은 채 알 수 없는 해제를 기록합니다. 확인된 unlock은 최종 무권한 해제 근거를 생성하며 격리 조정 전략만 운영에 적합합니다. | `current change`; `postgres_resource_lock.py`; `resource_lock.py`; 집중 잠금 테스트; 로컬 검사 80개와 live PostgreSQL 세션 및 읽기 및 해제 및 재획득 시나리오 1개 통과; Ruff, strict mypy 통과; 독립 비평에서 Medium 이상 발견된 문제가 없습니다. | #678의 잔여 작업은 없습니다. #681에서 공유 근거 수명 주기 조정기를 구현합니다. |
| 2026-09-10 | implemented | 이행 파일이 소유하는 추가 전용 PostgreSQL 감사 의도 저장소를 구현했습니다. 원자적 삽입은 별도의 정확한 읽기 트랜잭션보다 먼저 커밋합니다. 예약 lease 안에서 다이제스트와 정식 콘텐츠가 일치할 때만 추가됨 또는 동일 중복 근거를 생성하며, 차이는 증적 없는 충돌을 반환합니다. | `current change`; `postgres_audit_intent.py`; 서비스 이행 파일 및 소유권 매니페스트; 로컬 계약 및 어댑터 검사 10개, 이행 inventory 검사 64개, live PostgreSQL 동시 추가 및 재시작 시나리오 1개 통과; Ruff, strict mypy 통과; 독립 비평에서 Medium 이상 발견된 문제가 없습니다. | #680의 잔여 작업은 없습니다. #681 조정을 시작하기 전에 #678의 PostgreSQL 근거 잠금 공급자를 완료합니다. |
| 2026-09-10 | implemented | 별도 이행 파일이 소유하는 PostgreSQL 예약 테이블과 어댑터를 구현했습니다. 원자적 삽입은 획득자를 동일 중복 및 충돌과 구분합니다. 전체 레코드 compare-and-set과 `SELECT ... FOR UPDATE` 읽기는 정확한 이전 상태를 결속합니다. 런타임 DDL과 공유 키 공간 대체 경로는 없습니다. | `current change`; `postgres_idempotency_reservation.py`; 서비스 이행 파일 및 소유권 매니페스트; 로컬 모델 및 어댑터 검사 23개, 이행 inventory 검사 64개, live PostgreSQL 경쟁 및 재시작 및 오래된 CAS 시나리오 1개 통과; Ruff, strict mypy 통과; 독립 비평에서 Medium 이상 발견된 문제가 없습니다. | #679의 잔여 작업은 없습니다. #680에서 감사 의도 저장소를, #678에서 근거 잠금 공급자를 구현합니다. |
| 2026-09-10 | implemented | 장애에 안전한 예약 모델, 영구 JSON codec, 수명 주기 전환을 기존 public facade 뒤의 개별 모듈로 분리했습니다. 직렬화 및 전환 의미는 바뀌지 않습니다. 정확한 중첩 필드, 다이제스트, 무권한 플래그, 상태, 시간 순서, 모호한 결과 격리, 권위 있는 복구 근거에 집중 분기 검사를 추가했습니다. | `current change`; `core/executor/idempotency_reservation*.py`; `test_idempotency_reservation.py`; 집중 테스트 55개 및 결합 분기 커버리지 97.36%; Ruff, strict mypy 통과. | 이 batch에 남은 구조 또는 커버리지 작업은 없습니다. 공유 근거 수명 주기 조정은 #681에서 계속합니다. |
| 2026-09-10 | in-progress | #679에 필요한 정확한 영구 JSON 코덱을 추가했습니다. 직렬화는 열거형 값과 UTC 시각을 생성합니다. 구문 분석은 정확한 중첩 키 집합을 요구하고 획득, 신원, 레코드를 복원하면서 모든 다이제스트, 무권한, 상태, 시간 순서 불변식을 다시 검사합니다. | `current change`; `core/executor/idempotency_reservation.py`; `test_idempotency_reservation.py`; 집중 테스트 18개, Ruff, strict mypy 통과; 독립 비평에서 Medium 이상 발견된 문제가 없습니다. | #679에서 PostgreSQL 테이블, 원자적 예약 및 CAS 및 읽기 어댑터, 경쟁 및 재시작 테스트, 이행 파일을 구현합니다. |
| 2026-09-10 | in-progress | 영구 운영 구현을 PostgreSQL 근거 잠금 공급자, 예약 저장소, 감사 의도 저장소, 공유 수명 주기 조정기로 분리했습니다. 특정 시점 잠금 읽기, 영구 예약, 권위 있는 감사 영속화, 실행 순서를 각각 책임 있는 패키지로 유지합니다. | `current change`; 이슈 `#678`, `#679`, `#680`, `#681`; 상위 `#627`. | #678과 #679, 그다음 #680, #681을 완료한 뒤 경로별 PR, Direct API, 도구 호출, 작업 흐름 통합 패키지를 만듭니다. |
| 2026-09-10 | implemented | 정확한 영구 예약 전환 증적을 포함하는 효과 전 감사 의도와 후보에 결속된 추가 및 읽기 결과를 정의했습니다. 성공 근거에는 영속화, 권위 있는 정확한 읽기, 예약 읽기 뒤이면서 lease 만료 전인 시각이 필요합니다. API 확인이나 호출자가 계산한 다이제스트만으로는 충분하지 않습니다. | `current change`; `core/executor/audit_intent.py`; `test_audit_intent.py`; 집중 테스트 7개, Ruff, strict mypy 통과; 독립 비평에서 Medium 이상 발견된 문제가 없습니다. | #672 계약 작업은 완료했습니다. 이후 #627 공급자 패키지에서 영구 감사 저장소와 재시작 및 부분 쓰기 근거를 구현합니다. |
| 2026-09-10 | implemented | 장애에 안전한 예약 신원, 단조 상태 기계, 원자적 예약 결과, 정확한 이전 상태를 포함하는 CAS 및 읽기 증적, 공급자 경계를 정의했습니다. 만료된 실행 중 시도는 영구 결과 불명 격리가 되며, 중단에는 디스패치가 시작되지 않았다는 권위 있는 근거가 필요합니다. 입증된 미수락 뒤의 복구에는 더 늦은 잠금 획득과 더 높은 시도가 필요합니다. | `current change`; `core/executor/idempotency_reservation.py`; `test_idempotency_reservation.py`; 집중 테스트 16개, Ruff, strict mypy 통과; 독립 비평에서 Medium 이상 발견된 문제가 없습니다. | #671 계약 작업은 완료했습니다. 이후 #627 공급자 패키지에서 재시작 및 경쟁 근거를 갖춘 영구 공급자를 구현하고, 다음으로 #672에서 권위 있는 감사 의도 근거를 정의합니다. |
| 2026-09-10 | implemented | 검토된 효과 커밋까지의 소유권 전략과 정확한 정책, 획득, 현재 소유권 평가를 포함하는 최종 무권한 증적을 정의했습니다. 디스패치, 대상 시스템 커밋, 독립 효과 검증을 별도 축으로 유지합니다. 모호한 디스패치, 알 수 없는 커밋, 상실되거나 알 수 없는 해제는 격리가 필요하며 권위 있는 취소 불가능한 미수락 근거만 격리를 해제할 수 있습니다. | `current change`; `core/executor/lock_continuity.py`; `test_lock_continuity.py`; 집중 테스트 17개, Ruff, strict mypy 통과; 독립 비평에서 Medium 이상 발견된 문제가 없습니다. | #670의 잔여 작업은 없습니다. PostgreSQL 근거 공급자와 공유 생성기 조정을 구현하기 전에 #671에서 장애에 안전한 예약을 정의합니다. |
| 2026-09-10 | implemented | 고유한 획득별 신원, 레지스트리의 정확한 보유자 읽기, 어댑터 소유 UTC 시각, 범위가 제한된 평가 유효 기간, 요청에 결속된 무권한 증적, 해제 전 취소에 안전한 비활성화를 갖춘 로컬 테스트 전용 근거 리소스 잠금을 구현했습니다. 수명이 끝난 이전 핸들은 이후 획득 중에도 부적합 상태를 유지하며 이 어댑터는 운영 준비 상태를 충족할 수 없습니다. | `current change`; `core/executor/lock.py`; `shared/providers/resource_lock.py`; `test_lock.py`; `test_resource_lock_receipt.py`; 집중 검사 65개, Ruff, strict mypy 통과; 독립 비평에서 Medium 이상 발견된 문제가 없습니다. | #674의 잔여 작업은 없습니다. PostgreSQL 근거 공급자를 구현하기 전에 #670에서 운영 효과 커밋까지의 소유권을 정의합니다. |
| 2026-09-10 | implemented | #669를 계약 및 이행 목록 경계로 완료했습니다. 공급자 또는 경로 통합을 완료했다고 주장하지 않으면서 요청 및 증적 결속, TTL, 수명이 끝나면 사용할 수 없는 핸들, 명시적 운영 경계, 단일 대상 잠금 담당 상태를 정의했습니다. | `current change`; 커밋 `f25fdbe63`, `301c7a36b`; 이슈 `#669`; 집중 검사 67개, Medium 이상 독립 비평 발견 0건. | #674에서 로컬 테스트 전용 공급자를 구현합니다. 운영 공급자와 경로 이행은 #670-#672 뒤의 #627에 유지합니다. |
| 2026-09-10 | in-progress | 정식 무권한 획득 요청, 요청에 정확히 결속된 획득 증적, 최대 5초 실시간 평가 유효 기간, 명시적 `EvidenceResourceLock` 및 보유 핸들 프로토콜, 컨텍스트 종료 후 사용할 수 없게 되는 수명 주기 보호 조건, 기존 잠금 경계를 변환하거나 대신 사용하지 않는 운영 해석기를 추가했습니다. 정식 실행기 잠금 키 도우미는 공유 공급자 계약을 사용합니다. | `current change`; `shared/providers/resource_lock.py`; `core/executor/safeguards.py`; `test_resource_lock_receipt.py`; 리소스 잠금 및 최종 처리기 결합 검사 67개, Ruff, strict mypy 통과; 독립 비평에서 Medium 이상 발견된 문제가 없습니다. | 단일 담당 목록을 구성에 적용하고, 모든 변경 경로가 기존 잠금 경계를 수락하지 않음을 입증하며, 로컬 공급자를 운영 외 근거에만 유지해 #669를 완료합니다. |
| 2026-09-10 | in-progress | #627 생성기 연결을 의존성 순서가 있는 수명 주기 및 이행, 효과 커밋까지의 소유권, 장애에 안전한 예약, 권위 있는 감사 의도 근거 차단 작업으로 분리했습니다. 수정한 그래프는 호출자가 선택한 평가 시각, 기존 운영 대체 경로, 중복 대상 잠금 획득, 만료된 실행 중 예약의 안전하지 않은 재디스패치, 디스패치 또는 대상 시스템 커밋만으로 성공을 주장하는 동작을 허용하지 않습니다. | `current change`; 이슈 `#669`, `#670`, `#671`, `#672`; 독립 설계 비평에서 Medium 이상 발견된 문제가 없습니다. | #669를 완료한 뒤 #670, #671, #672를 의존성 순서대로 완료하고 로컬 또는 PostgreSQL 공급자와 경로별 생성기 통합 하위 이슈를 만듭니다. |
| 2026-09-10 | implemented | 순수 안전조건 최종 처리기가 묶음 기록 시점의 현재 공급자 증명 잠금 소유권을 사용하게 했습니다. 최종 처리기는 정확한 과거 증적을 액션, 대상, 소스 개정, 인과 시간 순서, 구성된 검증기 및 신뢰 앵커에 결속하고, 연산 설명과 실시간 평가를 모두 재생할 수 있도록 합성 잠금 증명 다이제스트를 생성합니다. | `current change`; `core/executor/safeguard_proofs.py`; `shared/providers/resource_lock.py`; `test_safeguard_proofs.py`; `test_resource_lock_receipt.py`; 집중 검사 52개, Ruff, strict mypy 통과; 독립 비평에서 Medium 이상 발견된 문제가 없습니다. | #660의 잔여 작업은 없습니다. #627에서 실제 Core 및 작업 흐름 실행 경로가 검증된 근거를 생성하게 합니다. |
| 2026-09-10 | implemented | 정확히 검증된 과거 획득 증적을 공급자가 증명한 현재 fence 또는 세션 소유권 평가에 포함하는 무권한 리소스 잠금 근거를 추가했습니다. 정식 다이제스트, 정확한 런타임 타입, UTC 시간 범위, lease 만료, 신뢰 앵커 불일치, 독립적으로 관찰한 잠금 상실은 안전한 쪽으로 차단됩니다. | `current change`; `shared/providers/resource_lock.py`; `test_resource_lock_receipt.py`; 집중 테스트 40개, Ruff, strict mypy 통과; 독립 비평에서 Medium 이상 발견된 문제가 없습니다. | 안전조건 최종 처리기가 이 정확한 현재 평가를 요구하고 오래됨, 상실, 만료, 잘못된 검증기, 잘못된 신뢰 앵커, fence 불일치 근거를 차단할 때까지 #660을 열어 둡니다. |
| 2026-09-10 | implemented | 디스패치 전 평가에서 전체 액션 다이제스트를 고정하고 액션 맥락에 결속된 잠금, 영구 멱등성 예약, 저장된 감사 의도 증명을 검증한 뒤 #620 무권한 묶음을 생성하는 순수 Core 최종 처리기를 추가했습니다. | `current change`; `safeguards.py`; `safeguard_proofs.py`; 집중 검사 63개, Ruff, strict mypy 통과. | #627에서 실제 실행기 연산 증적과 작업 흐름 사전 묶음 결속을 연결합니다. |
| 2026-09-10 | in-progress | 실패한 동일 제안을 재사용하는 안전하지 않은 복구 계획을 액션에 결속된 승인 디스패치, 권위 있는 효과 근거, 주장 fence가 적용된 최종 처리의 범위가 제한된 담당 작업으로 교체했습니다. | `current change`; 이슈 `#652`, `#656`, `#658`; 상위 `#630`. | 해당 패키지를 순서대로 완료한 뒤 `#640`을 완료합니다. |
| 2026-09-10 | in-progress | 승인된 복구 하나를 사용하고 fence를 증가시키며 내용 주소 기반 무권한 증적과 최종 감사를 저장하는 승인 보호 원자적 보류 해제 기본 연산을 추가했습니다. | `current change`; 보호 조건을 적용한 보류 및 상태 저장소 코드; 집중 검사 63개, Ruff, strict mypy 통과. | `#630`에서 운영 보상을 새 연산에 연결한 뒤 `#640`에서 최종 실행 경로 fence를 완료합니다. |
| 2026-09-10 | in-progress | 실행기 소유 논리 대상 잠금 경계를 유지하고 의존성 순환을 제거하도록 원자적 보류 해제와 최종 정방향 디스패치 fence를 분리했습니다. | `current change`; 이슈 `#630`, `#640`. | `#630`을 완료한 뒤 `#627`, `#628` 다음에 `#640`에서 액션에 결속된 보류 해제 증적을 통합합니다. |
| 2026-09-10 | implemented | 순수 복구 승인 경계를 닫기 전에 미래 요청 시각과 프로세스 및 승인 개정 다이제스트 대체 회귀를 추가했습니다. | `current change`; `test_recovery_admission.py`; 집중 복구 승인 테스트 21개와 승인, 복구, 보상 결합 검사 46개 통과. | 이슈 `#622`의 잔여 작업은 없습니다. 이슈 `#630`에서 승인을 원자적으로 사용하고 정확한 보류 개정을 해제합니다. |
| 2026-09-10 | implemented | 보류를 해제하거나 권한을 부여하지 않고 별도 승인된 복구를 기존 작업 흐름 승인 및 의사 결정 근거 승인 계약에 결속했습니다. | `current change`; `recovery_admission.py`; `test_recovery_admission.py`; 집중 검사 45개, Ruff, strict mypy 통과. | 이슈 `#630`에서 승인을 원자적으로 사용하고 정확한 보류 개정을 해제합니다. |
| 2026-09-10 | implemented | 공급자 중립 7개 안전조건 증명 묶음을 정식 순서와 권한 및 효과 플래그의 `false` 고정 조건을 갖춘 변경 불가능한 콘텐츠 주소 기반 wire 계약으로 추가했습니다. 서비스 소유의 불일치, 최신성, 디스패치 및 효과 판정은 이 패키지 밖에 유지합니다. | `current change`; `execution_safeguards.py`; `schemas/execution-safeguard-proof-bundle/1.0.0.json`; 집중 테스트 4개, Ruff, strict mypy 통과. | 이슈 `#627`, `#628`에서 묶음을 생성하고 검증한 뒤 이슈 `#633`에서 별도 승인된 통제된 근거를 보존합니다. |
| 2026-09-10 | in-progress | P0 실행 안전성 잔여 작업 그래프를 조정했습니다. 완료된 이슈 `#331`은 A3-E 수명 주기 근거를 제공하며, 공급자 중립 안전조건, 작업 흐름, Isolated 실행기, 효과 전체 구간 lease, 비활성 승격, 로컬 shadow 코호트, 통제된 승격, 승인된 복구, 교차 경로 효과 근거는 각각 범위가 제한된 담당 이슈를 갖습니다. | `current change`; 상위 이슈 `#81`; 완료된 이슈 `#331`; 이슈 `#620`-`#622`, `#627`-`#633`. | 하위 패키지를 의존성 순서대로 완료한 뒤 헌법 상태를 변경하기 전에 별도 승인된 통제된 런타임 및 독립 효과 근거를 보존합니다. |
| 2026-08-29 | in-progress | 공유 실행기 안전조건 계약, 완료된 모델 경계 최소화 증적, 그리고 남은 운영 예행 연습, privacy, A3-E 근거를 위한 명시적 이슈 인계를 반영하도록 보안 원장을 조정했습니다. | `core/executor/safeguards.py`; `tests/core/executor/test_safeguard_contract.py`; [데이터 거버넌스 구현 상태](data-governance-ko.md#구현-상태); 이슈 `#81`, `#331`, `#371`, `#372` | 작업 흐름과 Isolated 실행기 경로에 동일한 안전조건 및 독립 효과 증적을 확장하고, 이후 통제된 운영 근거를 보존합니다. |
| 2026-08-14 | in-progress | 이전 이력을 재구성하지 않고 구현 원장을 도입했으며 보안 주장을 서비스 전환, 안전조건 구현, kill switch, privacy 및 A3-E 근거 경계에 맞췄습니다. | `current change`; 위에 인용한 배포 매니페스트, 소스, 집중 테스트 및 헌법 레지스터입니다. | 공유 안전조건 계약, 운영 예행 연습, privacy 게이트 및 사전 권한 구현을 완료합니다. |

### 남은 작업

- [x] 이슈 `#620`에서 공급자 중립 7개 안전조건 증명 묶음을 정의했습니다. 근거: `execution_safeguards.py`, 버전이 지정된 JSON Schema, 통과한 집중 계약 테스트 4개.
- [x] 이슈 `#664`에서 공급자가 증명한 과거 획득 및 현재 실시간 소유권 근거를 정의했습니다. 근거: `resource_lock.py`, `test_resource_lock_receipt.py`, 통과한 집중 테스트 40개, Ruff, strict mypy, Medium 이상 독립 비평 발견 0건.
- [x] 이슈 `#669`에서 근거가 있는 대상 잠금 수명 주기, 단일 담당 이행, 수명이 끝난 핸들 동작, 운영 대체 경로가 없는 의존성을 정의했습니다. 근거: 커밋 `f25fdbe63`, `301c7a36b`, 집중 검사 67개, Medium 이상 독립 비평 발견 0건.
- [x] 이슈 `#674`에서 정확한 획득별 신원과 운영 차단 조건을 갖춘 로컬 테스트 전용 근거 공급자를 구현했습니다. 근거: 집중 검사 65개, Ruff, strict mypy, Medium 이상 독립 비평 발견 0건.
- [x] 이슈 `#670`에서 효과 커밋까지의 소유권, 대상 시스템 fence 또는 권위 있는 조정, 영구 `outcome_unknown` 격리를 정의했습니다. 근거: `lock_continuity.py`, 집중 테스트 17개, Ruff, strict mypy, Medium 이상 독립 비평 발견 0건.
- [x] 이슈 `#671`에서 장애에 안전한 영구 멱등성 예약 및 복구 근거를 정의했습니다. 근거: `idempotency_reservation.py`, 집중 테스트 16개, Ruff, strict mypy, Medium 이상 독립 비평 발견 0건.
- [x] 이슈 `#672`에서 권위 있는 감사 의도 추가 및 읽기 근거를 정의했습니다. 근거: `audit_intent.py`, 집중 테스트 7개, Ruff, strict mypy, Medium 이상 독립 비평 발견 0건.
- [x] 이슈 `#678`에서 운영 PostgreSQL 근거 리소스 잠금을 구현했습니다. 근거: 로컬 검사 80개, live PostgreSQL 세션 및 읽기 및 해제 및 재획득 시나리오 1개, Ruff, strict mypy, Medium 이상 독립 비평 발견 0건.
- [x] 이슈 `#679`에서 영구 PostgreSQL 예약 저장소를 구현했습니다. 근거: 로컬 검사 23개, 이행 inventory 검사 64개, live PostgreSQL 경쟁 및 재시작 및 CAS 시나리오 1개, Ruff, strict mypy, Medium 이상 독립 비평 발견 0건.
- [x] 이슈 `#680`에서 영구 PostgreSQL 감사 의도 저장소를 구현했습니다. 근거: 로컬 검사 10개, 이행 inventory 검사 64개, live PostgreSQL 추가 경쟁 및 재시작 시나리오 1개, Ruff, strict mypy, Medium 이상 독립 비평 발견 0건.
- [x] 이슈 `#692`에서 대상 전체 준비 디스패치 fence를 영속화했습니다. 근거: 로컬 검사 18개, 이행 inventory 검사 64개, live PostgreSQL 경쟁 및 재시작 시나리오 1개, Ruff, strict mypy, Medium 이상 독립 비평 발견 0건.
- [x] 이슈 `#693`에서 안전조건 묶음, 디스패치, 해제 전 checkpoint를 영속화했습니다. 근거: 집중 모델, 영속성, 이행 테스트 86개 통과, DSN 미구성으로 live PostgreSQL 테스트 1개 건너뜀, Ruff 통과.
- [x] 이슈 `#694`에서 해제 후 안전조건 상태를 원자적으로 종결하거나 격리했습니다. 근거: 집중 모델, 영속성, 이행 테스트 모음 통과, 새로운 pgvector/PostgreSQL 16 이행과 live 병렬 종결, 재시작, 조정, outbox 중복 제거 시나리오 통과, Ruff, strict mypy 통과.
- [x] #692-#694 다음에 이슈 `#681`에서 공유 근거 수명 주기 조정기를 구현합니다.
- [ ] #669-#672 선행 작업을 닫은 뒤 이슈 `#627`에서 실제 Core 및 작업 흐름 실행이 공유 묶음을 생성하게 합니다.
- [x] 하위 이슈 `#660`에서 순수 전체 액션 안전조건 증명 최종 처리기가 정확한 현재 `LiveLockOwnershipAssessment`를 사용하게 합니다. 근거: 통과한 안전조건 및 리소스 잠금 집중 검사 52개, Ruff, strict mypy, Medium 이상 독립 비평 발견 0건.
- [ ] 이슈 `#628`에서 Core 검증기를 가져오지 않고 Isolated 실행기가 공유 묶음을 다시 검증하게 합니다.
- [ ] 이슈 `#633`에서 별도 승인된 통제된 교차 경로 안전조건 및 독립 효과 근거를 보존합니다.
- [x] 이슈 `#622`에서 보류를 변경하지 않고 기존 승인 및 의사 결정 근거 계약을 통해 별도 승인된 복구를 결속했습니다. 근거: `recovery_admission.py`, `test_recovery_admission.py`, 통과한 집중 검사 46개.
- [x] 승인 보호 원자적 해제 기본 연산과 무권한 증적을 구현했습니다. 근거: 통과한 집중 검사 63개.
- [ ] 이슈 `#630`에서 운영 보상을 해당 연산에 연결하고 정확한 해제 증적을 보존합니다.
- [ ] 실패한 변경 불가능 제안을 재사용하거나 효과 근거를 약화하지 않고 #652, #656, #658에서 #630 운영 경로를 완료합니다.
- [ ] 이슈 `#640`에서 각 실행 경로의 기존 논리 대상 잠금 안에서 해제 증적과 더 최신 보류가 없음을 다시 검사합니다. 이 강화 중에도 FDAI-CONST-009는 `implemented`를 유지합니다.
- [ ] 하나의 고정된 배포 개정에서 통제된 kill switch, break-glass, 롤백, 신원 재인증 및 감사 앵커 예행 연습 증적을 보존합니다. 이 작업은 이슈 `#372`에서 추적합니다.
- [ ] Privacy 검증을 주장하기 전에 데이터 거버넌스 운영 게이트를 완료합니다. 이 작업은 이슈 `#371`에서 추적합니다.
- [x] 이슈 `#621`에서 비활성 효과 전체 구간 lease와 공급자 커밋 fence를 정의했습니다. 근거: 집중 테스트 82개, Ruff, strict mypy, 권한 경로 파일 208개 정적 검사, Medium 이상 독립 비평 발견 0건.
- [x] 이슈 `#629`에서 비활성 승격 후보 수명 주기를 구현했습니다. 근거: 집중 테스트 52개, Ruff, strict mypy, 파일 크기 제한, 검토자 권한과 취소 다이제스트 결속 강화 후 Medium 이상 발견 0건.
- [x] 이슈 `#631`에서 범위가 제한된 로컬 합성 shadow 집단을 보존했습니다. 근거: 정규 매니페스트와 증적, 로컬 제한 시간 및 레지스트리 무결성 검사, 심볼릭 링크에 안전한 산출물, 집중 테스트, 강화 후 Medium 이상 발견 0건.
- [ ] 이슈 `#632`에서 별도 승인된 통제된 런타임 근거와 승격을 완료합니다. 완료된 이슈 `#331`, `#621`, `#629`, `#631`은 개발 근거로만 유지합니다.

## 심각도 어휘

- **P0 차단 요인** - auto-execution이 활성화되기 전에 해결·검증되어야 함; shadow 모드에서의
  승격을 블록.
- **P1** - 능력이 프로덕션(강제 적용 모드) 이벤트를 처리하기 전 필요.
- **P2** - 첫 강제 적용 이후 진행될 수 있는 하드닝; 소유자와 함께 열림 Decisions에서 추적.

## 실행 아이덴티티

이 섹션은 **비-사람** 실행기 아이덴티티를 관장합니다. **사람** 아이덴티티 모델 - 콘솔과
ChatOps에 로그인하는 사람, 존재하는 Entra 그룹, 콘솔이 GitHub App으로 쓰기를 위임하는 방법 -
은 [user-rbac-and-identity-ko.md](../interfaces/user-rbac-and-identity-ko.md) 에 있습니다. 승인 ≠ 실행:
사람은 아래의 실행기 아이덴티티를 절대 보유하지 않습니다.

- 실행기 는 "짧은 수명의, audience-scoped OIDC 토큰을 가져와" 만 노출하는 **`WorkloadIdentity`
  인터페이스** 를 통해 인증해야 합니다. 이것이 [워크로드 신원 계약](csp-neutrality-ko.md#4-워크로드-아이덴티티-계약--oidc-토큰)
  의 구현입니다; 구체적 발급자 (Azure 의 Managed Identity, AWS 의 IRSA, GCP 의 워크로드
  신원 Federation, 어떤 K8s 위의 SPIFFE/SPIRE) 는 그 인터페이스 뒤에 위치하지 `core/`
  에는 없습니다.
- Azure 에서는 인터페이스가 **User-assigned Managed Identity** 로 뒷받침되며, 명시적
  **액션 화이트리스트** 로 범위 지정. 광범위 상주 권한 없음.
- `DefaultAzureCredential()` (또는 유사 이름의 SDK 진입점) 은 **`core/` 에서 금지** ;
  인터페이스 뒤의 Azure 프로바이더 어댑터 내부에서만 등장.
- **버티컬별 신원은 집계 라우터 신원과 함께 프로비저닝됩니다.** Terraform은
  `id-<workload><suffix>-executor`, `-change`, `-resilience`, `-finops` 신원을 생성합니다.
  Fork-owned 정책 모듈이 버티컬 액션 whitelist를 연결합니다. 아래 [신원 대응](#identity-mapping)을
  참조하세요.
- 사람 승인 아이덴티티(HIL)는 실행 아이덴티티와 별개; 승인과 실행은 절대 동일 principal이
  아니며, 어떤 아이덴티티도 다른 도메인의 아이덴티티를 assume할 수 없음(cross-domain assumption은
  단순히 미사용이 아니라 거부됨).
- 실행 아이덴티티는 **비대화형** : 대화형/콘솔 사인인 없음, 사람 자격증명 부착 없음, 이벤트
  루프 외 사용은 비활성화.
- **credential-free 인증 선호**: 워크로드 신원 federation / OIDC 토큰 교환으로 실행기가
  장기 시크릿을 보유하지 않음. 시크릿이 불가피한 곳에서는 단명·자동 로테이트(Secrets and
  구성 참조).

### 신원 대응

P0 열림 결정 *"Executor-side 신원 대응"*을 해결합니다. 현재 Terraform 형태는
집계 action-router 신원 하나와 버티컬 신원 세 개를 유지하므로 전달 어댑터는
`core/` 변경 없이 도메인별 principal을 선택할 수 있습니다.

| 신원 | 현재 목적 | Azure 역할 전략 | 범위 |
|----------|----------|----------------|-------|
| `id-<workload><suffix>-executor` | 집계 control-loop 전송 계층과 액션 라우팅 | 업스트림은 topic-scoped Event Hubs 접근, Key Vault 시크릿 읽기 같은 런타임 platform 역할만 부여 | 리소스 또는 서비스 범위, subscription-wide 금지 |
| `id-<workload><suffix>-change` | 변경 안전성 전달 principal | fork-owned 액션 whitelist 또는 측정된 custom 역할 | 변경 안전성이 관리하는 리소스 그룹 |
| `id-<workload><suffix>-resilience` | 복원력 및 복구 전달 principal | fork-owned 액션 whitelist 또는 측정된 custom 역할 | 관리되는 복구 범위 |
| `id-<workload><suffix>-finops` | 비용 거버넌스 전달 principal | fork-owned 액션 whitelist 또는 측정된 custom 역할 | 관리되는 cost-optimization 범위 |

실행 권한 확인은 프로바이더 중립적인 참조 `identity/change`, `identity/resilience`,
`identity/finops`를 사용합니다. Terraform은 대응 UAMI를 첨부하고 클라이언트 id만 전달
조립에 노출합니다. 권한 확인 결과가 하나의 참조를 선택하면 액션과 direct-API
요청이 이를 보존하고 전달 라우터가 일치하는 `WorkloadIdentity`를 선택합니다. 알 수 없거나
연결되지 않은 참조는 집계 실행기 신원으로 대체 경로하지 않고 거부됩니다.

읽기 전용 인벤토리, 인제스트, canary와 다른 서비스 신원은 이 실행기 집합과 분리됩니다.
버티컬 신원 생성 자체는 리소스 권한을 부여하지 않으며 역할 배정은 명시적
포크 배포 정책입니다.

모든 단계에 적용되는 규칙 (MUST):

- **RG-스코프, 절대 subscription-wide 아님.** 새 RG는 포크가 명시적으로 할당 IaC에 추가할
  때만 거버넌스에 들어감 - 자동 확장 없음.
- **보완적 Azure Policy `deny`** 가 선언된 화이트리스트 밖의 MI 액션을 두 번째 방어선으로
  블록하여, 잘못 할당된 롤이 조용히 표면을 넓히지 못하게 함.
- **모든 액션 화이트리스트 변경은 거버넌스 PR** with `Justification:` 및 Managed
  신원 롤 할당을 만지는 모든 변경에 Owner-티어 정족수
  ([user-rbac-and-identity-ko.md](../interfaces/user-rbac-and-identity-ko.md)).
- **Shadow 로그 캡처** 는 shadow 모드의 실행기 MI가 발행하는 모든 액션이
  호출할 정확한 Azure resource-provider 작업을 기록하여, 단계 2 Custom 역할 파생이 결정론적
  이고 감사 가능하게 함.

전달 계층은 액션 도메인에서 버티컬 MI를 선택하며 코어 코드 변경은 필요 없습니다.

## 인가 모델(권한 확인 모델)

실행 권한 확인은
[실행 권한 부여 온톨로지](../decisioning/execution-authorization-ontology-ko.md)에 정의된
프로바이더 중립적인 기능 온톨로지와 scoped 정책 배정으로 확인합니다. 액션 승인은 실행기
접근 권한을 부여하지 않습니다. 권한이 없으면 원래 액션을 보류하고 별도의 exact-plan
`AccessGrantRequest`를 생성할 수 있습니다. 독립된 protected deployer가 승인된 권한 부여를 적용하며,
fresh effective-access 근거가 있어야 액션을 처음부터 다시 평가합니다.

- 모든 액션을 필요한 최소 롤/권한에 매핑; **기본 거부**.
- 최소권한을 관례가 아니라 기계적으로 강제: 액션 화이트리스트는 리스크 게이트에서 평가되는
  policy-as-code(OPA/Rego) 이며, 권한 있는 스코프는 상시 개방이 아니라 **just-in-time과
  time-bound** 로 부여되어 액션 윈도우 후 만료.
- 조직의 계정/아이덴티티 표준을 클라우드 인가 경로와 조화(예: Keycloak 같은 외부 IdP ↔ Entra
  ↔ Managed Identity). 이 매핑을 **P0 차단 요인** 로 취급; 종단 경로가 프로비저닝되고
  최소권한 프로브로 테스트되고 접근 재인증이 스케줄될 때만 해결됨.
- **접근 재인증**: 롤 할당은 고정 주기로 리뷰; 미사용/과광범위 부여는 취소. 재인증 결과는 감사.
- 자율 배포는 플랫폼 정책(예: Azure Policy `deny`) 을 존중해야 함; 컨트롤을 우회하는 대신
  **정책 예외 워크플로**(요청 가능, time-boxed, 감사, 소유자 승인) 제공.

## 시크릿과 설정

- 시크릿, 연결 문자열, 구독/테넌트 ID, 고객 식별자를 절대 하드코딩하지 않음. 시크릿 검사
  (예: gitleaks)이 CI에서 실행되고 긍정 발견 사항은 머지를 블록
  ([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).
- **앱은 환경변수 (또는 K8s 시크릿 마운트) 만 읽습니다.** CSP 시크릿 SDK (`SecretClient`,
  `SecretsManagerClient`, `SecretManagerServiceClient` 등) 를 호출해서는 안 됩니다; 이것이
  [시크릿 계약](csp-neutrality-ko.md#3-시크릿-계약--환경변수--k8s-secret) 의 구현입니다.
  Azure 에서 주입 레이어는 **Container Apps native 시크릿 + Key Vault 참조** ; Kubernetes
  에서는 `SecretStore` CRD 를 가진 **외부 Secrets Operator** .
- 시크릿은 `shared/providers/` 의 주입된 `SecretProvider` 로 접근하며, 가져오기 시점 전역 읽기는
  절대 금지.
- **라이프사이클**: 모든 시크릿은 소유자, 정의된 로테이션 간격, 자동 로테이션을 가짐; 손상되거나
  대체된 자료는 즉시 취소. 로테이트할 시크릿이 없도록 federated 토큰 선호.
- **실패 시 차단**: 시크릿 주입 레이어 또는 토큰 발급자가 시작 시 사용 불가하면 프로세스가
  fail fast - 캐시된 또는 임베디드 자격증명으로 대체 경로 하지 않으며 degraded 상태 로
  시작하지 않음.
- 시크릿은 로그, 감사 엔트리, 에러 메시지, 테스트 픽스처, LLM 프롬프트에 등장하면 안 됨.
- 저장소를 고객-비종속으로 유지
  ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

## 데이터 보호

- 컨트롤 플레인이 처리하는 데이터(이벤트 페이로드, 도구 출력, 감사 기록, 임베딩)를 **분류**
  하고 최소화: 포인터/id를 저장, 원시 고객 바이트나 PII는 저장 안 함.
- 전송 중(TLS)과 정지 중 암호화; 키는 시크릿/키 저장소에서 관리, 코드에 없음.
- **LLM 데이터 처리**: T2 프롬프트는 신뢰 경계를 떠나기 전에 시크릿과 PII가 redact됨; 외부
  모델 벤더에 대한 데이터 잔류지와 no-retention 조건 강제. 감출 수 없는 민감 데이터가 필요한
  프롬프트는 전송되지 않고 HIL로 라우팅됨.

## 네트워크 경계

- 실행기와 코어 엔진은 **공개 인바운드 엔드포인트 없음**; 인그레스는 이벤트 버스뿐.
  관리/API 표면은 비공개 네트워킹 뒤에 있음.
- **Egress는 allow-list 됨** - 요구된 클라우드 컨트롤 플레인과 모델 엔드포인트로; 유출과
  주입-주도 콜백을 억제하기 위해 아웃바운드는 기본 거부.
- 레이어 아이덴티티는 네트워크 경계를 넘어 공유되지 않음; 읽기 전용 콘솔과 ChatOps는 실행기
  아이덴티티를 절대 보유하지 않음
  ([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)).

## 공급망 무결성

- 의존성은 lockfile로 고정; CI는 lockfile에서만 설치하고 취약성 스캔이 high-severity 발견을
  블록.
- 룰 카탈로그와 IaC는 **protected 브랜치 + 서명 커밋/PR 리뷰** 뒤의 catalog-as-code;
  강제 적용 브랜치로의 직접 push 없음.
- 빌드 아티팩트(컨테이너 이미지)는 서명되고 출처 이력/SBOM 기록됨; 실행기는 검증된 고정
  다이제스트만 pull, 절대 변경 가능한 `latest` 태그 아님.

## 7개 안전조건 (모든 자율 상태 변경 액션)

1. **Stop-condition** - 액션을 중단시키는 정의된 halt 상태. ActionType 별로 `stop_conditions[]`
   에 선언되고 실행기 가 적용 도중·이후에 평가.
2. **Rollback 경로** - 되돌리는 테스트된 방법. 온톨로지 `ActionType.rollback_contract` 는
   `pr_revert` / `scripted` / `pitr` / `snapshot_restore` / `state_forward_only` 중 하나여야
   함; **`none` 은 유효 값 아님**. 정말로 되돌릴 수 없는 변경 은
   `ActionType.irreversible: true` 로 설정되어 risk-gate 가 HIL+정족수 라우팅; 롤백 은
   여전히 최선 노력 복구로 선언.
3. **Blast-radius 한도** - 스코프 상한(non-prod 우선, 배치 크기, 속도) + 리소스별
   직렬화로 한 리소스에 대한 동시 액션은 상호 배제. `ActionType.blast_radius.computation =
   graph_derived` 는 risk-gate 가 Resource → Resource 그래프(`contains` + 역방향
   `depends_on`, 깊이 2) 로 실제 영향 집합을 계산하게 함 - 3-값 enum 은 상한이 아니라 버킷.
4. **What-if 또는 예행 실행** - 변경 전에 성공한 버전 고정 예측 증명.
5. **Logical-target 잠금** - 영향을 받는 모든 대상의 잠금과 인과 순서. 관리 리소스 변경에는
  정확한 리소스 ID를 사용합니다.
6. **멱등성** - 전송과 재시도 전반의 안정적인 키 및 중복 억제.
7. **감사 수명 주기** - side 효과 전에 추가 전용 의도를 기록하고 이후 최종
  실행 및 결과로 닫습니다.

안전조건 중 하나라도 빠지면 액션은 미완결이며 출시할 수 없습니다. 각 안전조건은 **테스트할
수 있습니다**. Shadow-mode 테스트는 변경이 없음을 증명하고 롤백 테스트는 이전 상태
복원을 증명합니다. 속성 기반 테스트는 영향이 큰 실행에 현재 또는 상시 사람 승인이 있고,
침묵은 권한을 부여하지 않으며, 비가역 작업은 상시 권한을 사용하지 않고, 재시도는 no-op임을
단언합니다. 순수 A0 읽기는 변경 롤백, 예행 실행 및 잠금 대신 제한된 읽기 권한과 증거
계약을 따릅니다. 독립적인 효과 검증이 모든 성공 주장을 게이트합니다.

### 대상 잠금 담당 이행

변경 경로마다 근거가 있는 대상 잠금 담당자는 한 명입니다. 선택된 실행기가 근거 공급자를
필수 준비 상태로 검사할 때까지 기존 리소스 주장 fence를 유지합니다. 이행 중에 두 대상
잠금을 함께 획득하는 방식은 허용하지 않습니다.

| 경로 | 현재 대상 잠금 경계 | 이행 후 필요한 담당자 |
|------|---------------------|------------------------|
| Thor 디스패치 | 일반 실행기 호출을 감싸는 기존 대상 잠금과 별도 영구 리소스 주장 | 영구 주장은 유지합니다. 선택된 실행기가 근거 공급자 누락을 차단할 때만 중복 대상 잠금을 제거합니다. |
| PR native/manual | 멱등성 mutex 다음에 실행기 내부의 기존 대상 잠금을 획득합니다. | 선택된 PR 실행기가 게시 및 최종 저장까지 하나의 근거 대상 잠금을 소유합니다. |
| Direct API | 멱등성 mutex 다음에 실행기 내부의 기존 대상 잠금을 획득합니다. | Direct API 실행기가 공급자 커밋 연속성과 최종 저장까지 하나의 근거 대상 잠금을 소유합니다. |
| 도구 호출 | 멱등성 mutex 다음에 실행기 내부의 기존 대상 잠금을 획득합니다. | 도구 호출 실행기가 공급자 커밋 연속성과 최종 저장까지 하나의 근거 대상 잠금을 소유합니다. |
| 작업 흐름 | 선택된 실행기를 조정하며 별도 `ExecutionPath`를 정의하지 않습니다. | 선택된 실행기가 대상 잠금을 소유합니다. 작업 흐름은 변경 불가능한 사전 묶음 약속을 전달하고 대상을 다시 잠그지 않습니다. |
| Isolated 실행기 | 공유 묶음 재검증은 #628에서 열린 작업입니다. | Isolated 실행기는 디스패치 전에 누락되거나 오래된 근거 소유권을 차단하고 기존 잠금 경계를 대신 사용하지 않아야 합니다. |

### PostgreSQL 연속성 승인

효과 대상 시스템은 구성이 검토된 `EffectSinkContinuityPolicy` 하나를 제공할 때까지 운영에서
지원되지 않습니다. 정책은 fence 및 멱등 실행, 완전한 잠금 세션 원자성, 또는 영구 결과 불명
격리 및 권위 있는 조정을 포함한 취소 중 하나를 선택합니다. 일반 Direct API 또는 도구
범주는 연속성 전략이 아닙니다.

PostgreSQL 근거 공급자는 다음 경계를 따릅니다.

- 하나의 전용 연결이 전체 획득 컨텍스트에서 정확한 advisory key를 소유합니다. 다시 연결하거나
  연결을 바꾸면 새 획득이 되며 이전 획득을 계속할 수 없습니다.
- 획득은 DSN이나 기능 권한이 있는 토큰을 저장하지 않고 데이터베이스 신원, backend 프로세스
  ID, backend 세션 구분자, 요청 다이제스트, 소유자 참조 다이제스트를 결속합니다.
- `granted=true`인 `pg_locks`는 특정 시점의 기반 시스템 관찰입니다. 공급자 소유 UTC 시각과
  계약의 최대 5초가 평가 범위를 제한하지만 미래 소유권을 예측하지는 않습니다.
- 공급자는 advisory unlock의 부울 결과를 확인합니다. 연결 상실, 잠금 행 누락, 알 수 없는
  unlock 결과는 상실 또는 알 수 없는 해제 근거와 영구 대상 격리를 생성합니다.
- 대상 시스템 커밋은 격리를 해제하거나 운영 성공을 주장하지 않습니다. 선택된 대상 시스템
  정책은 안정적인 멱등성 또는 권위 있는 상태 조정을 제공해야 하며 독립 효과 검증은 별도
  최종 축으로 유지됩니다.

## 비율 Limiting과 비상 정지 (DoS와 억제)

- 이벤트 루프와 실행기는 **비율/예산 상한**(티어별, 리소스별, 전역) 을 강제; 상한 초과는
  HIL로 강등, 게이트 없는 auto-action이 되지 않음. 이것이 비용과 폭주/이벤트 홍수(DoS) 조건도
  한계.
- **전역 비상 정지** 는 모든 auto-execution을 즉시 중단하고 모든 경로를 shadow/HIL로 드롭;
  실행기 아이덴티티 없이 조작 가능. risk 게이트 는 이를 `KillSwitch.is_engaged()` 가 공급하는
  `kill_switch` 상한 축으로 실현합니다. ([execution-model-ko.md](../decisioning/execution-model-ko.md)
  2.6b). 운영 런타임은 모든 권한 결정 전에 PostgreSQL에서 상태를 읽으며 읽기에 실패하면
  engaged 상태로 처리합니다. Owner와 Break-Glass principal은 `POST /system/kill-switch`를 통해
  상태를 변경하고, 개정 번호 compare-and-set과 감사 항목이 같은 트랜잭션에 기록됩니다.
- **Break-glass** 절차는 필수 감사와 사후 리뷰 하에 범위된 비상 접근을 부여; break-glass
  사용은 알림을 발동하고 자동 만료.

## Shadow → 강제 적용 승격

- 새 능력은 **shadow 모드** 로 출시: 판정자와 로그만, 실행 없음.
- 강제 적용로의 승격은 명시적, 액션별이며 **최소 shadow 기간과 표본 크기**, 임계 위 측정 정확도,
  shadow에서 **정책 위반 escape 0** 을 게이트로 함
  ([goals-and-metrics-ko.md](goals-and-metrics-ko.md)의 메트릭).
- 회귀는 자동으로 shadow로 강등; 모든 승격과 강등은 감사 엔트리를 씀.
- Working-context 정책 후보는 액션 기능을 얻지 않고 같은 기능 권한을
  사용합니다. 비활성화된 상태로 설치되고 범위가 제한된 off-path 비교를 실행하며, 승격에는
  정확한 버전, 근거 구간, 롤백 대상이 필요합니다. 불변식 위반 시 정책별 kill
  전환이 engage됩니다. [컨텍스트 선택 정책](../decisioning/context-selection-policy-ko.md)을
  참고하세요.

## 사람 승인 무결성

- 승인과 실행은 별개 principal; **자기승인 없음**, 그리고 고-blast-radius 액션은 단일 승인자가
  아니라 **정족수(멀티 승인자)** 필요.
- 승인자는 MFA/phishing-resistant 자격증명으로 인증; 각 승인은 특정 액션 + 멱등성 키에
  바인딩되어 **다른 액션에 대해 재생될 수 없음**.
- **시간 초과는 실패 시 차단입니다**: 현재 승인 또는 유효한 기존 상시 승인이 없는 HIL 항목은
  no-op 및 감사 엔트리로 종료됩니다. 침묵은 승인을 만들지 않습니다. 상시 승인은
  [에스컬레이션 및 상시 권한](../decisioning/escalation-and-standing-authority-ko.md)의 제한된
  A3-E 계약을 통해서만 적용됩니다.

## 감사가능성(Auditability)

- 감사 저장소는 추가 전용이며 자율성의 신뢰 기반.
- **Tamper-evidence**: 엔트리는 hash-chain(각 기록이 이전을 커밋)되고 주기적으로 기준점/서명
  되어 삭제나 편집이 감지 가능; 가능한 곳에서 한 번만 쓰는/WORM 저장.
- **부인 방지**: 각 엔트리는 인증된 행위자 아이덴티티(실행기 또는 승인자)와 모드(shadow/강제 적용)
  를 기록하여 액션을 나중에 부인할 수 없음.
- 모든 액션은 다음에 링크: 트리거 이벤트, 결정한 티어, 인용된 규칙/정책, 리스크 결정(auto/HIL),
  승인자(HIL인 경우), 멱등성 키, 롤백 참조.
- **보존**: legal-hold 지원과 함께 정의된 불변 보존 윈도우; 기록은 윈도우 경과 전에 정리 불가.
- 이 저장소의 감사 데이터는 고객-비종속; 실제 환경 기록은 포크의 런타임 저장소에만 있고 여기
  커밋되지 않음.

## 위협 모델 (STRIDE)

Browser-only 근거는 실행기 신원나 호스트 파일 시스템 mount가 없는 별도의 credential-free
런타임을 사용합니다. Exact HTTPS 출처 정책, 연결별 DNS revalidation, restricted egress,
GET/헤드 interception, visual 및 텍스트 민감정보 제거, 시크릿 canary, prompt-injection 검사, 내용 해시,
추가 전용 보관 기록이 하나의 실패 시 차단 경계를 구성합니다. 브라우저 내용은 항상
신뢰할 수 없는이며 액션을 approve하거나 execute할 수 없습니다. [브라우저 근거 수집](../interfaces/browser-evidence-ko.md)을
참고하세요.

이벤트 페이로드와 도구 출력은 **신뢰할 수 없는** ; 결정론적 검증기와 정책 재검사가 권위이며,
모델이나 이벤트 텍스트가 아님.

| STRIDE | 위협 | 완화 |
|--------|------|------|
| **Spoofing** | 위조된 이벤트 / 임퍼소네이트된 승인자 | 인증된(서명된) 이벤트 소스; MFA + 액션-바인딩 승인; federated 아이덴티티 |
| **Tampering** | 변조된 규칙/IaC, 주입된 아티팩트 | 서명 커밋, protected 브랜치, 서명/고정 아티팩트 + SBOM |
| **Repudiation** | 나중에 부인된 액션 | Hash-chain된 actor-attributed 추가 전용 감사 |
| **Info 공개** | 로그 또는 LLM 프롬프트를 통한 시크릿/PII 유출 | 민감정보 제거, no-secret-in-prompt, 암호화, egress allow-list |
| **DoS** | 이벤트 홍수 / 폭주 루프 / 예산 소진 | 비율/예산 상한, HIL로 circuit-break, 비상 정지 |
| **권한 상승** | 과광범위 또는 cross-domain 액션 | Per-domain 아이덴티티, JIT time-bound 스코프, cross-assumption 거부, no 자기 승인 |
| **프롬프트 주입** | 악성 페이로드가 T2 조종 | T2는 신뢰할 수 없는 취급; 검증기 + 정책 재검사가 권위 |

## 열림 Decisions

| 우선순위 | 결정 | 소유자 | 목표 |
|----------|------|--------|------|
| ~~P0~~ | ~~Executor-side 신원 대응~~ - **해결** in [신원 대응](#identity-mapping) | - | - |
| ~~P0~~ | ~~Risk-classification 정책 (auto vs HIL) and initial 정책 승인자~~ - **해결** in [risk-classification-ko.md](../decisioning/risk-classification-ko.md) | - | - |
| P1 | 정책 예외 워크플로 소유자와 SLA | TBD | 프로덕션 전 |
| P1 | 감사 앵커 주기, WORM 바인딩 및 운영 검증 | TBD | 프로덕션 전 |
| P1 | 비상 정지와 break-glass 런북과 드릴 스케줄 | TBD | 프로덕션 전 |
| P2 | 컴플라이언스 컨트롤 매핑(MCSB / CIS / SOC 2) 과 증거 수집 | TBD | 첫 강제 적용 이후 |
| P2 | 아이덴티티별 시크릿 로테이션 간격과 federation 커버리지 | TBD | 첫 강제 적용 이후 |
