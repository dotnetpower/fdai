---
title: Architecture Decision Record
translation_of: README.md
translation_source_sha: 563911d49fa23aeb4bc84878a1e767ab84822540
translation_revised: 2026-08-11
---
# 아키텍처 결정 기록

아키텍처 결정 기록(ADR)는 FDAI의 system 경계, 계약, 배포 토폴로지,
장기 운영 의무를 바꾸는 선택을 기록합니다. Register는 결정, alternative, consequence,
상태, replacement 이력을 한 곳에서 검토할 수 있게 합니다.

> **범위:** Customer의 RPO/RTO, 보존 기간, 지역, 예산, named 소유자 같은 환경 값은
> upstream ADR이 아니라 운영 근거 연결입니다. 포크는 upstream 기록을
> 다시 작성하지 않고 자체 ADR을 추가할 수 있습니다.

## Register

| ADR | 상태 | 결정 | 대체 대상 |
|-----|------|------|-----------|
| [ADR-0001](0001-azure-day-zero-platform-ko.md) | Accepted | Azure day-zero platform 기준선 | `tech-stack.md`의 lightweight OD와 배포 초안 |
| [ADR-0002](0002-independent-runtime-axes-ko.md) | Accepted | 독립적인 런타임, 신원, 자율성, 포크 축 | 로컬 shadow-only 및 production-fork 결합 |

## 상태 vocabulary

| 상태 | 의미 |
|------|------|
| Proposed | 검토 중이며 구현 권한이 아닙니다. |
| Accepted | 현재 design 권한입니다. |
| Deprecated | 이력을 위해 유지하지만 새 작업에는 사용하지 않습니다. |
| 대체된 | 지정한 ADR로 대체되었습니다. |
| Rejected | 검토했지만 선택하지 않았습니다. |

## 기록 계약

모든 ADR은 다음을 포함합니다.

1. **맥락:** 결정을 요구하는 force와 제약.
2. **결정:** 선택 행동과 경계.
3. **Alternatives:** 검토한 주요 옵션과 선택하지 않은 이유.
4. **Consequences:** 긍정, 부정, operational, security, 이행 효과.
5. **상태와 date:** 수명 주기 상태, 결정일, replacement 관계.
6. **근거:** 결정이 구현된 경우 구현과 검증 링크.

한 ADR은 하나의 coherent 결정에 답하는 것이 좋습니다. Platform-baseline ADR은 하나의
배포 계약을 이루는 inseparable 서비스 choice를 묶을 수 있습니다. 이후 한 choice를
교체할 때는 영향 섹션을 명시적으로 대체하는 새 ADR을 만듭니다.

## 변경 프로세스

1. Proposed ADR과 Korean translation을 같은 pull 요청에 추가합니다.
2. 영향받는 design doc과 구현 경로를 연결합니다.
3. Security, reliability, 비용, 이행 consequence를 기록합니다.
4. 아키텍처 소유자와 변경에 필요한 전문가 승인을 받습니다.
5. 구현 계획과 롤백 경로를 검토할 수 있을 때만 accepted로 변경합니다.
6. 준비 상태가 변경되면 이 register와 기계가 읽는 ARB 매니페스트를 갱신합니다.

## 다음 단계

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 현재 ARB 결정 | [아키텍처 검토 Board 패킷](../architecture-review-board-ko.md) |
| Azure day-zero 기준선 | [ADR-0001](0001-azure-day-zero-platform-ko.md) |
| 런타임 및 customization 축 | [ADR-0002](0002-independent-runtime-axes-ko.md) |
| Technology 선택 상세 | [Technology Stack](../tech-stack-ko.md) |
