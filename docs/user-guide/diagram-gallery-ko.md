---
title: 다이어그램 갤러리
description: FDAI가 지원하는 아키텍처, 프로세스, 타임라인, 좌표, 방사형, 그리드 및 가중 흐름 다이어그램의 인터랙티브 예제입니다.
sidebar:
  order: 3
translation_of: diagram-gallery.md
translation_source_sha: d1b1599cbeb29f11b4d2462e73804f3ba2b4d2ec
translation_revised: 2026-08-11
---

# 다이어그램 갤러리

FDAI는 하나의 영한 YAML 계약을 접근 가능한 SVG, PNG, 매니페스트 및 인터랙티브 viewer
asset으로 컴파일합니다. 새 아키텍처 또는 운영 보기를 작성하기 전에 이 갤러리에서 적합한
다이어그램 유형을 선택하세요.

## 한눈에 보는 설계

컴파일러는 검증된 FDAI 종류를 통해 Mermaid 11 다이어그램 유형을 지원합니다. 구조형
다이어그램은 결정론적 그래프 배치를 사용합니다. 타임라인, 좌표, 방사형, 그리드 및 가중
흐름 다이어그램은 장식용 별칭이 아니라 전용 데이터 필드와 배치 전략을 사용합니다.

| 유형 | FDAI 종류 |
|------|-----------|
| 아키텍처 및 흐름 | `context`, `container`, `component`, `deployment`, `network`, `architecture`, `c4-*`, `data-flow`, `flowchart`, `graph`, `conceptual-flow` |
| 상호작용 및 프로세스 | `sequence`, `railroad`, `swimlane`, `user-journey`, `kanban`, `block`, `cynefin` |
| 상태 및 의미 구조 | `state`, `decision-tree`, `requirement`, `domain`, `entity-relationship`, `class-diagram`, `mindmap`, `ishikawa`, `tree-view` |
| 시간 | `timeline`, `gantt`, `git-graph`, `event-modeling` |
| 차트 | `pie`, `radar`, `quadrant`, `xy-chart`, `wardley`, `venn`, `sankey`, `packet` |

## 개념 아키텍처

번호가 있는 단계, 의미 색상, 중첩 설명 영역, 피드백 루프 및 영구 저장소를 표현하려면
개념 흐름을 사용하세요.

<fdai-architecture-diagram manifest="../../diagrams/generated/fdai-conceptual-control-loop.manifest.json" locale="ko" style="display:block">
  <img src="../../diagrams/generated/fdai-conceptual-control-loop.ko.svg" alt="통제된 자동화 경로가 언어 이해, 온톨로지, 정책, 작업 선택, 실행, 피드백 및 데이터 저장소를 연결합니다." loading="eager" style="display:block;width:100%;height:auto" />
</fdai-architecture-diagram>

## 타임라인 및 Gantt

병렬 작업 흐름의 기간, 의존 관계, 상태 및 진행률을 표시하려면 Gantt를 사용하세요.

<fdai-architecture-diagram manifest="../../diagrams/generated/fdai-delivery-roadmap.manifest.json" locale="ko" style="display:block">
  <img src="../../diagrams/generated/fdai-delivery-roadmap.ko.svg" alt="세 작업 흐름이 하나의 전달 축에 완료, 진행 중, 계획, 중요 및 마일스톤 작업을 표시합니다." loading="lazy" style="display:block;width:100%;height:auto" />
</fdai-architecture-diagram>

## 방사형 차트

Pie는 구성을 전달하고 radar는 정규화된 여러 차원을 비교합니다.

<fdai-architecture-diagram manifest="../../diagrams/generated/fdai-decision-mix.manifest.json" locale="ko" style="display:block">
  <img src="../../diagrams/generated/fdai-decision-mix.ko.svg" alt="원형 차트가 결정 작업을 규칙, 검증된 재사용 및 근거 기반 추론으로 구분합니다." loading="lazy" style="display:block;width:100%;height:auto" />
</fdai-architecture-diagram>

<fdai-architecture-diagram manifest="../../diagrams/generated/fdai-assurance-radar.manifest.json" locale="ko" style="display:block">
  <img src="../../diagrams/generated/fdai-assurance-radar.ko.svg" alt="방사형 프로필이 근거, 안전, 복구, 관찰 가능성 및 replay 준비도를 비교합니다." loading="lazy" style="display:block;width:100%;height:auto" />
</fdai-architecture-diagram>

## 좌표 및 그리드 보기

Quadrant는 정규화된 축에 기능을 배치하고 Kanban은 작업을 안정적인 프로세스 열로
그룹화합니다.

<fdai-architecture-diagram manifest="../../diagrams/generated/fdai-capability-quadrant.manifest.json" locale="ko" style="display:block">
  <img src="../../diagrams/generated/fdai-capability-quadrant.ko.svg" alt="기능을 근거 신뢰도와 변경 영향에 따라 배치합니다." loading="lazy" style="display:block;width:100%;height:auto" />
</fdai-architecture-diagram>

<fdai-architecture-diagram manifest="../../diagrams/generated/fdai-governance-kanban.manifest.json" locale="ko" style="display:block">
  <img src="../../diagrams/generated/fdai-governance-kanban.ko.svg" alt="후보, 검증 및 준비 열에 통제된 기능 작업을 배치합니다." loading="lazy" style="display:block;width:100%;height:auto" />
</fdai-architecture-diagram>

## 가중 근거 흐름

Sankey 방식의 가중 연결선은 상대적 기여도를 보여 주면서 기반 이벤트, 읽기, 승인,
변경 및 감사 의미를 유지합니다.

<fdai-architecture-diagram manifest="../../diagrams/generated/fdai-evidence-sankey.manifest.json" locale="ko" style="display:block">
  <img src="../../diagrams/generated/fdai-evidence-sankey.ko.svg" alt="가중 근거 연결선이 검증된 결정, 통제된 작업 및 감사 기록으로 이어집니다." loading="lazy" style="display:block;width:100%;height:auto" />
</fdai-architecture-diagram>

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| FDAI 권한 및 배포 경계 | [FDAI 아키텍처](architecture-ko.md) |
| 다이어그램 컴파일러 작성 계약 | [아키텍처 Diagram 컴파일러](../../tools/architecture-diagrams/README.md) |
