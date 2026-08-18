---
title: 구현 호환성 기록 (2026-07-06 Standard Set)
translation_of: implementation-plan.md
translation_source_sha: e5c676085e754103b9a06b171c9ba6f44db4c1de
translation_revised: 2026-08-19
---

# 구현 호환성 기록 (2026-07-06 Standard Set)

이 문서는 소스, 스키마 및 테스트에서 계속 참조하는 2026-07-06 standard-set 제안의 식별자를
보존합니다. 현재 구현 계획이 아닙니다. 현재 동작과 향후 작업은 연결된 하위 시스템 owner
문서에서 관리합니다.

> **범위:** R1, R2, R3, R4, R6 및 R7은 과거 제안 식별자입니다. 아래 reconciliation에서
> 이를 해석하는 방법을 결정합니다. M1.2 probe 목록은 focused 테스트가 배포된 카탈로그와의
> 일치를 확인하므로 실행 가능한 호환성 계약으로 유지합니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 과거 standard-set 결정 R1, R2, R3, R6 및 R7 | not-applicable | [현재 reconciliation](#현재-구현-reconciliation)과 연결된 owner 문서 | 이 제안은 채택되지 않았으며 현재 런타임 동작을 정의하지 않습니다. |
| 과거 R4 공유 projection 제안 | not-applicable | [`projection.py`](../../../services/core-control-plane/src/fdai/shared/providers/projection.py), [Assurance Twin](../operations/assurance-twin-ko.md), [Deployment Preflight](../deployment/deployment-preflight-ko.md) | 공유 프로토콜은 있지만 두 consumer는 서로 다른 현재 추상화를 유지합니다. 구현은 각 owner 문서에서 추적합니다. |
| M1.2 starter probe 호환성 집합 | implemented | [`test_probe_catalog.py`](../../../services/core-control-plane/tests/rule_catalog/test_probe_catalog.py), [`rule-catalog/probes/`](../../../rule-catalog/probes/) | focused 테스트가 아래 네 식별자와 배포된 카탈로그의 정확한 양방향 일치를 강제합니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-19 | implemented | 이전 provenance를 재구성하지 않고 구현 원장을 도입했으며, 채택되지 않은 standard-set 제안을 과거 호환성 식별자로 분류하고 테스트되는 M1.2 probe 집합을 보존했습니다. | `current change`; 위에 나열한 현재 owner 문서와 focused 카탈로그 일치 테스트입니다. | 이 과거 기록이 소유하는 구현은 없습니다. 활성 작업은 연결된 owner 문서에 남아 있습니다. |

### 남은 작업

- [x] 이 과거 기록에 남은 구현은 없습니다. 현재 owner가 활성 작업을 추적하며
  `test_probe_catalog.py`가 보존된 M1.2 호환성 집합을 강제합니다.

## 현재 구현 reconciliation

| 결정 | 현재 상태 | 현재 authority |
|------|-----------|----------------|
| R1 | 채택되지 않음 | Axis A가 기준선입니다. 독립적인 static-blast와 environment 축이 authority를 낮출 수 있습니다. [`ceiling.py`](../../../services/core-control-plane/src/fdai/core/risk_gate/ceiling.py)와 [실행 모델](../decisioning/execution-model-ko.md)이 authority를 소유합니다. |
| R2 | 채택되지 않음 | `ConversationCoordinator`는 명시적 `SystemConsoleTool` 레지스트리를 받습니다. ActionType은 write-tool 자동 projection이 아니라 discovery 근거를 제공합니다. [Operator Console](../interfaces/operator-console-ko.md)이 표면을 소유합니다. |
| R3 | 채택되지 않음 | `LlmBindings`는 역할별 프로토콜과 어댑터를 집계합니다. [Prompt Composition](../decisioning/prompt-composition-ko.md)이 현재 조립을 소유합니다. |
| R4 | 이 기록 밖에서 부분 구현 | `ScratchProjection`과 Assurance Twin consumer가 존재합니다. Deployment Preflight는 `FeasibilityProbe`와 `PreflightAnalyzer`를 유지합니다. |
| R6 | 채택되지 않음 | `operator_memory`는 독립적인 append-and-supersede 저장소로 유지됩니다. [Prompt Composition](../decisioning/prompt-composition-ko.md#operator-memory-pipeline)이 현재 계약을 소유합니다. |
| R7 | 채택되지 않음 | `ExecutionPath`는 `pr_manual`, `pr_native`, `direct_api` 및 `tool_call`을 유지하며 `require_manual_merge` 필드는 없습니다. [실행 모델](../decisioning/execution-model-ko.md)이 authority를 소유합니다. |

## 과거 standard set 식별자

이 짧은 기록은 이전 참조를 설명합니다. 위 reconciliation을 재정의하지 않습니다.

### 2.1 R1 - Axis D와 G를 Axis A에서 파생

R1은 static-blast와 environment 결과를 Axis A에서 파생하도록 제안했습니다. 이 제안은
채택되지 않았으며 현재 risk gate는 authority를 유지하거나 낮출 수만 있는 독립 축을 평가합니다.

### 2.2 R2 - ConsoleTool에서 ActionType 카탈로그 projection

R2는 ActionType에서 write tool을 자동으로 파생하도록 제안했습니다. 이 제안은 채택되지
않았으며 현재 조립은 명시적 system tool 레지스트리를 주입하고 ActionType을 별도의 discovery
및 action 근거로 사용합니다.

### 2.3 R3 - 통합 LlmBinding

R3는 모든 모델 역할에 하나의 어댑터 형태를 사용하도록 제안했습니다. 이 제안은 채택되지
않았으며 현재 조립은 역할별 프로토콜과 해석된 capability 바인딩을 유지합니다.

### 2.4 R4 - 공유 projection primitive

R4는 Assurance Twin과 Deployment Preflight에 하나의 projection 추상화를 사용하도록
제안했습니다. 공유 `ScratchProjection` 프로토콜은 있지만 현재 consumer는 별도의 동작과
소유권을 유지합니다.

### 2.5 R6 - Audit materialized view로서의 operator memory

R6는 audit log에서 operator memory를 파생하도록 제안했습니다. 이 제안은 채택되지 않았으며
operator-memory 항목은 자체 승인, 범위, 만료 및 supersession 수명 주기를 유지합니다.

### 2.6 R7 - 플래그로 표현하는 manual merge

R7은 `pr_manual`을 `pr_native`의 플래그로 대체하도록 제안했습니다. 이 제안은 채택되지
않았으며 execution path는 서로 다른 직렬화 계약 값으로 유지됩니다.

## 과거 Wave M1 호환성

현재 호환성 경계로 남은 것은 M1.2 카탈로그 집합뿐입니다. 과거 sequencing과 완료된 전달
서술은 git history에서 확인할 수 있으며 backlog가 아닙니다.

### M1.2 Starter probes

Starter probe 카탈로그에는 다음 ID가 정확히 포함됩니다:

- `vm_traffic_last_5m`
- `storage_access_log`
- `lb_backend_health`
- `blast_radius_classifier`

[`test_probe_catalog.py`](../../../services/core-control-plane/tests/rule_catalog/test_probe_catalog.py)는
양방향을 확인합니다. 위의 각 식별자에는 YAML 선언이 있고 starter 카탈로그에는 이 목록에 없는
추가 식별자가 없습니다.

## 관련 문서

| 학습 주제 | 읽기 |
|-----------|------|
| 현재 authority 계산 | [실행 모델](../decisioning/execution-model-ko.md)과 [위험 분류](../decisioning/risk-classification-ko.md) |
| 현재 운영자 tool 경계 | [Operator Console](../interfaces/operator-console-ko.md) |
| 현재 모델 조립 | [Prompt Composition](../decisioning/prompt-composition-ko.md) |
| 현재 projection consumer | [Assurance Twin](../operations/assurance-twin-ko.md)과 [Deployment Preflight](../deployment/deployment-preflight-ko.md) |
| 현재 action schema와 execution path | [Action Ontology](../decisioning/action-ontology-ko.md) |
