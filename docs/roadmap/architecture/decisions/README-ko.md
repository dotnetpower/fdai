---
title: Architecture Decision Record
translation_of: README.md
translation_source_sha: c23ee5742728b61d46002b5537721f44432526b7
translation_revised: 2026-07-13
---
# Architecture Decision Record

Architecture decision record(ADR)는 FDAI의 system boundary, contract, deployment topology,
장기 운영 의무를 바꾸는 선택을 기록합니다. Register는 decision, alternative, consequence,
status, replacement history를 한 곳에서 review할 수 있게 합니다.

> **범위:** Customer의 RPO/RTO, retention 기간, region, budget, named owner 같은 환경 값은
> upstream ADR이 아니라 production evidence binding입니다. 포크는 upstream record를
> 다시 작성하지 않고 자체 ADR을 추가할 수 있습니다.

## Register

| ADR | 상태 | 결정 | 대체 대상 |
|-----|------|------|-----------|
| [ADR-0001](0001-azure-day-zero-platform-ko.md) | Accepted | Azure day-zero platform baseline | `tech-stack.md`의 lightweight OD와 deployment 초안 |

## Status vocabulary

| 상태 | 의미 |
|------|------|
| Proposed | Review 중이며 implementation authority가 아닙니다. |
| Accepted | 현재 design authority입니다. |
| Deprecated | History를 위해 유지하지만 새 작업에는 사용하지 않습니다. |
| Superseded | 지정한 ADR로 대체되었습니다. |
| Rejected | 검토했지만 선택하지 않았습니다. |

## Record contract

모든 ADR은 다음을 포함합니다.

1. **Context:** 결정을 요구하는 force와 constraint.
2. **Decision:** 선택 behavior와 boundary.
3. **Alternatives:** 검토한 주요 option과 선택하지 않은 이유.
4. **Consequences:** positive, negative, operational, security, migration effect.
5. **Status와 date:** lifecycle 상태, 결정일, replacement 관계.
6. **Evidence:** Decision이 구현된 경우 implementation과 validation link.

한 ADR은 하나의 coherent decision에 답하는 것이 좋습니다. Platform-baseline ADR은 하나의
deployment contract를 이루는 inseparable service choice를 묶을 수 있습니다. 이후 한 choice를
교체할 때는 영향 section을 명시적으로 supersede하는 새 ADR을 만듭니다.

## 변경 process

1. Proposed ADR과 Korean translation을 같은 pull request에 추가합니다.
2. 영향받는 design doc과 implementation path를 연결합니다.
3. Security, reliability, cost, migration consequence를 기록합니다.
4. Architecture owner와 변경에 필요한 specialist approval을 받습니다.
5. Implementation plan과 rollback path를 review할 수 있을 때만 accepted로 변경합니다.
6. Readiness가 변경되면 이 register와 machine-readable ARB manifest를 갱신합니다.

## 다음 단계

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 현재 ARB 결정 | [Architecture Review Board 패킷](../architecture-review-board-ko.md) |
| Azure day-zero baseline | [ADR-0001](0001-azure-day-zero-platform-ko.md) |
| Technology 선택 상세 | [Technology Stack](../tech-stack-ko.md) |
