---
title: Architecture Decision Record
translation_of: README.md
translation_source_sha: 816a5a7b117d380c640d930fc05de8458b562fa0
translation_revised: 2026-10-02
---
# 아키텍처 결정 기록

아키텍처 결정 기록(ADR)은 FDAI의 시스템 경계, 계약, 배포 토폴로지,
장기 운영 의무를 바꾸는 선택을 기록합니다. 이 목록에서 결정, 대안, 영향,
상태, 대체 이력을 한 곳에서 검토할 수 있습니다.

> **범위:** 고객의 RPO/RTO, 보존 기간, 지역, 예산, 지정된 담당자 같은 환경 값은
> 업스트림 ADR이 아니라 운영 근거로 연결해 관리합니다. 포크는 업스트림 기록을
> 다시 작성하지 않고 자체 ADR을 추가할 수 있습니다.

## Register

| ADR | 상태 | 결정 | 대체 대상 |
|-----|------|------|-----------|
| [ADR-0001](0001-azure-day-zero-platform-ko.md) | Accepted | Azure day-zero platform 기준선 | `tech-stack.md`의 lightweight OD와 배포 초안 |
| [ADR-0002](0002-independent-runtime-axes-ko.md) | Accepted | 독립적인 런타임, 신원, 자율성, 포크 축 | 로컬 shadow-only 및 production-fork 결합 |
| [ADR-0003](0003-hub-managed-lifecycle-and-operator-governance-ko.md) | Accepted | 세 번째 설치 경로인 Hub 관리형 수명 주기와 단독 운영자 거버넌스 | 두 가지 설치 경로 규칙과 2인 전용 상시 권한 |
| [ADR-0004](0004-local-isolated-executor-principal-ko.md) | Proposed | 개발 권한을 위한 로컬 격리 executor 주체 | 개발 프로파일의 배포 전용 executor 신원 |

## 상태 vocabulary

| 상태 | 의미 |
|------|------|
| Proposed | 검토 중이며 구현 권한이 아닙니다. |
| Accepted | 현재 설계의 기준이 됩니다. |
| Deprecated | 이력을 위해 유지하지만 새 작업에는 사용하지 않습니다. |
| 대체된 | 지정한 ADR로 대체되었습니다. |
| Rejected | 검토했지만 선택하지 않았습니다. |

## 기록 계약

모든 ADR은 다음을 포함합니다.

1. **맥락:** 결정이 필요한 배경과 제약.
2. **결정:** 선택한 동작과 그 경계.
3. **대안:** 검토한 주요 선택지와 선택하지 않은 이유.
4. **영향:** 긍정적 영향, 부정적 영향, 운영, 보안, 이행에 미치는 영향.
5. **상태와 날짜:** 수명 주기 상태, 결정일, 대체 관계.
6. **근거:** 결정이 구현된 경우 구현과 검증 링크.

하나의 ADR은 서로 일관된 하나의 결정을 다루는 것이 좋습니다. 플랫폼 기준선 ADR은 하나의
배포 계약을 이루며 분리할 수 없는 여러 서비스 선택을 묶을 수 있습니다. 이후 그중 하나를
교체할 때는 해당 섹션을 대체한다는 점을 명시한 새 ADR을 만듭니다.

## 변경 프로세스

1. 제안 상태의 ADR과 한국어 번역을 같은 PR에 추가합니다.
2. 영향을 받는 설계 문서와 구현 경로를 연결합니다.
3. 보안, 신뢰성, 비용, 이행에 미치는 영향을 기록합니다.
4. 아키텍처 소유자와 변경에 필요한 전문가 승인을 받습니다.
5. 구현 계획과 롤백 경로를 검토할 수 있을 때만 accepted로 변경합니다.
6. 준비 상태가 변경되면 이 목록과 기계가 읽을 수 있는 ARB 매니페스트를 갱신합니다.

## 다음 단계

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 현재 ARB 결정 | [Architecture Review Board 패킷](../architecture-review-board-ko.md) |
| Azure day-zero 기준선 | [ADR-0001](0001-azure-day-zero-platform-ko.md) |
| 런타임 및 사용자 지정 축 | [ADR-0002](0002-independent-runtime-axes-ko.md) |
| Hub 관리형 수명 주기와 운영자 거버넌스 | [ADR-0003](0003-hub-managed-lifecycle-and-operator-governance-ko.md) |
| 로컬 격리 executor 주체 | [ADR-0004](0004-local-isolated-executor-principal-ko.md) |
| 기술 선택 상세 | [Technology Stack](../tech-stack-ko.md) |
