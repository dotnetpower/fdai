"""Reviewed Stencil definitions, custom Console menu/feature composition, and footprint analysis.

A Stencil is a deterministic build-time feature, menu, loop, and workload composition
(see #2524, #2525, #2526, #2527). It never mutates the fixed 15-agent pantheon, removes the
Trial watermark or hash-chained Saga audit, or grants runtime execution authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_release import parse_lifecycle_release_manifest
from pydantic import BaseModel, ConfigDict, Field, model_validator

STENCIL_DEFINITION_SCHEMA: Literal["fdai.stencil-definition.v1"] = "fdai.stencil-definition.v1"
TopologyProfile = Literal["lite-observe-alert", "standard-sre", "full-enterprise"]

_STENCIL_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}\Z", re.ASCII)
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}\Z", re.ASCII)
_SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z",
    re.ASCII,
)

LOCKED_CORE_WORKLOADS: tuple[str, ...] = (
    "core-control-plane",
    "operator-service",
)
ALL_WORKLOADS: tuple[str, ...] = (
    "core-control-plane",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
    "operator-service",
)

LOCKED_CORE_SCHEDULED_JOBS: tuple[str, ...] = (
    "analyzer",
    "inventory",
)
ALL_SCHEDULED_JOBS: tuple[str, ...] = (
    "analyzer",
    "canary",
    "cost-collector",
    "inventory",
)

LOCKED_CORE_LOOPS: tuple[str, ...] = (
    "anomaly-analyzer",
    "inventory-reconciliation",
    "notification-dispatch",
    "saga-audit",
)
ALL_LOOPS: tuple[str, ...] = (
    "anomaly-analyzer",
    "assurance-twin",
    "code-security",
    "cost-governance",
    "document-ingestion",
    "inventory-reconciliation",
    "notification-dispatch",
    "remediation-execution",
    "saga-audit",
)

LOCKED_CORE_ADDONS: tuple[str, ...] = (
    "notifications",
    "read-only-console",
)
ALL_ADDONS: tuple[str, ...] = (
    "enterprise-identity-governance",
    "governed-execution",
    "notifications",
    "policy-administration",
    "read-only-console",
)

LOCKED_CORE_PANELS: tuple[str, ...] = (
    "audit",
    "dashboard",
    "settings-general",
)


@dataclass(frozen=True, slots=True)
class ConsolePanelDescriptor:
    """Metadata and dependency contract for one selectable FDAI Console menu panel."""

    id: str
    group: str
    label: str
    label_ko: str
    locked: bool = False
    required_workloads: tuple[str, ...] = ()
    required_loops: tuple[str, ...] = ()
    required_addons: tuple[str, ...] = ()
    feature_ids: tuple[str, ...] = ()


CONSOLE_PANEL_CATALOG: tuple[ConsolePanelDescriptor, ...] = (
    # Overview
    ConsolePanelDescriptor(
        id="dashboard",
        group="overview",
        label="Overview dashboard",
        label_ko="종합 대시보드",
        locked=True,
        feature_ids=("F01.1", "F02.1", "F03.1"),
    ),
    ConsolePanelDescriptor(
        id="operating-outcomes",
        group="overview",
        label="Operating outcomes",
        label_ko="운영 성과 지표",
        feature_ids=("F03.2",),
    ),
    ConsolePanelDescriptor(
        id="control-assurance",
        group="overview",
        label="Control assurance",
        label_ko="통제 보증 현황",
        feature_ids=("F03.2", "F12.1"),
    ),
    ConsolePanelDescriptor(
        id="verticals",
        group="overview",
        label="Vertical outcomes",
        label_ko="도메인별 운영 결과",
        feature_ids=("F03.2",),
    ),
    ConsolePanelDescriptor(
        id="trust-routing",
        group="overview",
        label="Trust routing",
        label_ko="신뢰 라우팅 (T0/T1/T2)",
        feature_ids=("F05.1",),
    ),
    ConsolePanelDescriptor(
        id="llm-cost",
        group="overview",
        label="LLM token usage",
        label_ko="LLM 토큰 사용량",
        feature_ids=("F09.1",),
    ),
    ConsolePanelDescriptor(
        id="aks-commerce",
        group="overview",
        label="AKS commerce",
        label_ko="AKS 커머스 분석",
        required_loops=("cost-governance",),
        feature_ids=("F09.2",),
    ),
    ConsolePanelDescriptor(
        id="cost-governance",
        group="overview",
        label="Cost governance",
        label_ko="비용 거버넌스",
        required_loops=("cost-governance",),
        feature_ids=("F09.1", "F09.2"),
    ),
    # Operations
    ConsolePanelDescriptor(
        id="live",
        group="operations",
        label="Live operations & resource changes",
        label_ko="실시간 리소스 및 변경 감지",
        required_loops=("inventory-reconciliation",),
        feature_ids=("F02.1", "F03.1"),
    ),
    ConsolePanelDescriptor(
        id="gpu",
        group="operations",
        label="GPU monitoring",
        label_ko="GPU 모니터링",
        feature_ids=("F03.3",),
    ),
    ConsolePanelDescriptor(
        id="incidents",
        group="operations",
        label="Incidents & anomaly alerts",
        label_ko="장애 및 이상 징후 인시던트",
        required_loops=("anomaly-analyzer", "notification-dispatch"),
        feature_ids=("F04.1", "F08.1"),
    ),
    ConsolePanelDescriptor(
        id="hil-queue",
        group="operations",
        label="Human approval queue (HIL)",
        label_ko="인간 승인 대기열 (HIL)",
        required_loops=("remediation-execution",),
        required_workloads=("isolated-executor",),
        required_addons=("enterprise-identity-governance", "governed-execution"),
        feature_ids=("F06.1", "F07.1"),
    ),
    ConsolePanelDescriptor(
        id="detection-readiness",
        group="operations",
        label="Detection readiness",
        label_ko="감지 준비 상태",
        required_loops=("anomaly-analyzer", "inventory-reconciliation"),
        feature_ids=("F03.1", "F04.1"),
    ),
    ConsolePanelDescriptor(
        id="alert-quality",
        group="operations",
        label="Alert quality & noise control",
        label_ko="알림 품질 및 노이즈 제어",
        required_loops=("anomaly-analyzer", "notification-dispatch"),
        feature_ids=("F04.2", "F08.1"),
    ),
    ConsolePanelDescriptor(
        id="configuration-baselines",
        group="operations",
        label="Configuration baselines & drift",
        label_ko="구성 기준선 및 드리프트 감지",
        required_loops=("inventory-reconciliation",),
        feature_ids=("F02.1", "F02.3"),
    ),
    ConsolePanelDescriptor(
        id="processes",
        group="operations",
        label="Operational processes",
        label_ko="운영 프로세스",
        required_loops=("remediation-execution",),
        required_workloads=("isolated-executor",),
        feature_ids=("F07.1",),
    ),
    ConsolePanelDescriptor(
        id="workflow-apps",
        group="operations",
        label="Workflow applications",
        label_ko="워크플로 애플리케이션",
        required_loops=("remediation-execution",),
        required_workloads=("isolated-executor",),
        feature_ids=("F07.2",),
    ),
    ConsolePanelDescriptor(
        id="scheduler-runs",
        group="operations",
        label="Scheduler runs",
        label_ko="스케줄러 실행 이력",
        feature_ids=("F03.1",),
    ),
    ConsolePanelDescriptor(
        id="background-tasks",
        group="operations",
        label="Background tasks",
        label_ko="백그라운드 작업",
        feature_ids=("F03.1",),
    ),
    ConsolePanelDescriptor(
        id="automation-blueprints",
        group="operations",
        label="Automation blueprints",
        label_ko="자동화 블루프린트",
        required_loops=("remediation-execution",),
        feature_ids=("F07.2",),
    ),
    ConsolePanelDescriptor(
        id="scheduled-continuations",
        group="operations",
        label="Scheduled continuations",
        label_ko="예약된 후속 작업",
        feature_ids=("F07.2",),
    ),
    ConsolePanelDescriptor(
        id="conversation-delivery",
        group="operations",
        label="Notification & channel delivery",
        label_ko="알림 및 채널 전달 현황",
        required_loops=("notification-dispatch",),
        feature_ids=("F08.1",),
    ),
    # Agents
    ConsolePanelDescriptor(
        id="agents",
        group="agents",
        label="Agent fleet",
        label_ko="에이전트 플릿",
        feature_ids=("F05.2",),
    ),
    ConsolePanelDescriptor(
        id="pantheon",
        group="agents",
        label="Pantheon roles & ownership",
        label_ko="판테온 역할 및 오너십",
        feature_ids=("F01.3", "F05.2"),
    ),
    ConsolePanelDescriptor(
        id="agent-activity",
        group="agents",
        label="Agent detection & activity timeline",
        label_ko="에이전트 감지 및 활동 타임라인",
        required_loops=("anomaly-analyzer", "inventory-reconciliation"),
        feature_ids=("F05.2",),
    ),
    # Governance
    ConsolePanelDescriptor(
        id="architecture",
        group="governance",
        label="Architecture topology workbench",
        label_ko="아키텍처 토폴로지 워크벤치",
        required_loops=("inventory-reconciliation",),
        feature_ids=("F02.2",),
    ),
    ConsolePanelDescriptor(
        id="ontology",
        group="governance",
        label="Operating ontology",
        label_ko="운영 온톨로지",
        required_loops=("inventory-reconciliation",),
        feature_ids=("F02.2",),
    ),
    ConsolePanelDescriptor(
        id="handover",
        group="governance",
        label="Stewardship handover",
        label_ko="담당자 인수인계",
        feature_ids=("F01.3",),
    ),
    ConsolePanelDescriptor(
        id="rules",
        group="governance",
        label="Rule catalog (T0 detection rules)",
        label_ko="규칙 카탈로그 (T0 감지 규칙)",
        required_loops=("anomaly-analyzer",),
        feature_ids=("F04.1", "F12.1"),
    ),
    ConsolePanelDescriptor(
        id="workflow-builder",
        group="governance",
        label="Workflow builder",
        label_ko="워크플로 빌더",
        required_loops=("remediation-execution",),
        feature_ids=("F07.2",),
    ),
    ConsolePanelDescriptor(
        id="capabilities",
        group="governance",
        label="Capabilities",
        label_ko="기능 카탈로그",
        feature_ids=("F12.2",),
    ),
    ConsolePanelDescriptor(
        id="skills",
        group="governance",
        label="Skills",
        label_ko="스킬 카탈로그",
        feature_ids=("F12.2",),
    ),
    ConsolePanelDescriptor(
        id="blast-radius",
        group="governance",
        label="Blast radius limits",
        label_ko="영향 반경 제한",
        feature_ids=("F06.2",),
    ),
    ConsolePanelDescriptor(
        id="promotion-gates",
        group="governance",
        label="Autonomy promotion gates",
        label_ko="자율성 승격 게이트",
        feature_ids=("F06.3",),
    ),
    ConsolePanelDescriptor(
        id="context-selection-comparisons",
        group="governance",
        label="Context selection comparisons",
        label_ko="컨텍스트 선택 비교",
        feature_ids=("F05.1",),
    ),
    ConsolePanelDescriptor(
        id="scope",
        group="governance",
        label="Management scope",
        label_ko="관리 범위",
        feature_ids=("F01.1",),
    ),
    # Knowledge
    ConsolePanelDescriptor(
        id="knowledge",
        group="knowledge",
        label="Knowledge overview",
        label_ko="지식 개요",
        required_workloads=("document-ingestion-api", "document-processing-worker"),
        required_loops=("document-ingestion",),
        feature_ids=("F11.1",),
    ),
    ConsolePanelDescriptor(
        id="documents",
        group="knowledge",
        label="Documents ingestion",
        label_ko="문서 수집 및 처리",
        required_workloads=("document-ingestion-api", "document-processing-worker"),
        required_loops=("document-ingestion",),
        feature_ids=("F11.1",),
    ),
    ConsolePanelDescriptor(
        id="github",
        group="knowledge",
        label="GitHub knowledge source",
        label_ko="GitHub 지식 소스",
        required_workloads=("document-ingestion-api", "document-processing-worker"),
        required_loops=("document-ingestion",),
        feature_ids=("F11.2",),
    ),
    ConsolePanelDescriptor(
        id="gitlab",
        group="knowledge",
        label="GitLab knowledge source",
        label_ko="GitLab 지식 소스",
        required_workloads=("document-ingestion-api", "document-processing-worker"),
        required_loops=("document-ingestion",),
        feature_ids=("F11.2",),
    ),
    ConsolePanelDescriptor(
        id="azure-devops",
        group="knowledge",
        label="Azure DevOps knowledge source",
        label_ko="Azure DevOps 지식 소스",
        required_workloads=("document-ingestion-api", "document-processing-worker"),
        required_loops=("document-ingestion",),
        feature_ids=("F11.2",),
    ),
    # Evidence
    ConsolePanelDescriptor(
        id="audit",
        group="evidence",
        label="Hash-chained audit trail",
        label_ko="해시 체인 감사 추적",
        locked=True,
        required_loops=("saga-audit",),
        feature_ids=("F10.1",),
    ),
    ConsolePanelDescriptor(
        id="browser-evidence",
        group="evidence",
        label="Browser evidence",
        label_ko="브라우저 증적",
        feature_ids=("F10.2",),
    ),
    ConsolePanelDescriptor(
        id="forecast-learning",
        group="evidence",
        label="Forecast & learning",
        label_ko="예측 및 학습",
        feature_ids=("F03.4", "F13.1"),
    ),
    ConsolePanelDescriptor(
        id="assurance-twin",
        group="evidence",
        label="Assurance twin",
        label_ko="보증 디지털 트윈",
        required_loops=("assurance-twin",),
        feature_ids=("F12.3",),
    ),
    ConsolePanelDescriptor(
        id="code-security",
        group="evidence",
        label="Code security scans",
        label_ko="코드 보안 스캔",
        required_loops=("code-security",),
        feature_ids=("F14.1",),
    ),
    ConsolePanelDescriptor(
        id="conversation-search",
        group="evidence",
        label="Conversation search",
        label_ko="대화 이력 검색",
        feature_ids=("F08.2",),
    ),
    ConsolePanelDescriptor(
        id="conversation-assurance",
        group="evidence",
        label="Conversation assurance",
        label_ko="대화 품질 보증",
        feature_ids=("F08.3",),
    ),
    ConsolePanelDescriptor(
        id="reports",
        group="evidence",
        label="Operational reports",
        label_ko="운영 리포트",
        feature_ids=("F10.3",),
    ),
    ConsolePanelDescriptor(
        id="trace",
        group="evidence",
        label="Rule evaluation trace",
        label_ko="규칙 평가 추적",
        required_loops=("anomaly-analyzer",),
        feature_ids=("F04.1", "F10.1"),
    ),
    ConsolePanelDescriptor(
        id="rca",
        group="evidence",
        label="Root cause analysis (RCA)",
        label_ko="근본 원인 분석 (RCA)",
        required_loops=("anomaly-analyzer",),
        feature_ids=("F04.3",),
    ),
    # Labs
    ConsolePanelDescriptor(
        id="labs",
        group="labs",
        label="Labs",
        label_ko="실험실 (Labs)",
    ),
    # Settings
    ConsolePanelDescriptor(
        id="settings-general",
        group="settings",
        label="Settings: General",
        label_ko="설정: 일반",
        locked=True,
        feature_ids=("F01.1",),
    ),
    ConsolePanelDescriptor(
        id="settings-environment",
        group="settings",
        label="Settings: Environment & deployment",
        label_ko="설정: 환경 및 배포",
        feature_ids=("F01.1", "F15.1"),
    ),
    ConsolePanelDescriptor(
        id="settings-models",
        group="settings",
        label="Settings: Models",
        label_ko="설정: 모델 라우팅",
        feature_ids=("F05.1",),
    ),
    ConsolePanelDescriptor(
        id="settings-runtime",
        group="settings",
        label="Settings: Runtime policies",
        label_ko="설정: 런타임 정책",
        required_addons=("enterprise-identity-governance", "policy-administration"),
        feature_ids=("F01.2",),
    ),
    ConsolePanelDescriptor(
        id="settings-memory",
        group="settings",
        label="Settings: Operator memory",
        label_ko="설정: 운영자 메모리",
        feature_ids=("F13.1",),
    ),
    ConsolePanelDescriptor(
        id="settings-iam",
        group="settings",
        label="Settings: Identity & access",
        label_ko="설정: 신원 및 접근 제어",
        required_addons=("enterprise-identity-governance",),
        feature_ids=("F01.3",),
    ),
    ConsolePanelDescriptor(
        id="settings-integrations",
        group="settings",
        label="Settings: Notification & webhook integrations",
        label_ko="설정: 알림 및 웹훅 연동",
        required_loops=("notification-dispatch",),
        feature_ids=("F08.1",),
    ),
    ConsolePanelDescriptor(
        id="settings-diagnostics",
        group="settings",
        label="Settings: Diagnostics",
        label_ko="설정: 런타임 진단",
        feature_ids=("F15.2",),
    ),
)

PANEL_BY_ID: Mapping[str, ConsolePanelDescriptor] = {
    panel.id: panel for panel in CONSOLE_PANEL_CATALOG
}
ALL_PANEL_IDS: tuple[str, ...] = tuple(sorted(PANEL_BY_ID))

LITE_OBSERVE_ALERT_PANELS: tuple[str, ...] = tuple(
    sorted(
        {
            *LOCKED_CORE_PANELS,
            "live",
            "incidents",
            "detection-readiness",
            "alert-quality",
            "configuration-baselines",
            "conversation-delivery",
            "pantheon",
            "agent-activity",
            "rules",
            "trace",
            "settings-integrations",
        }
    )
)

STANDARD_SRE_PANELS: tuple[str, ...] = tuple(
    sorted(
        {
            *LITE_OBSERVE_ALERT_PANELS,
            "operating-outcomes",
            "trust-routing",
            "hil-queue",
            "processes",
            "scheduler-runs",
            "background-tasks",
            "agents",
            "architecture",
            "ontology",
            "handover",
            "blast-radius",
            "scope",
            "rca",
            "reports",
            "settings-environment",
            "settings-models",
            "settings-iam",
            "settings-diagnostics",
        }
    )
)


def _canonical_sorted_unique(
    values: Iterable[str], label: str, allowed: frozenset[str]
) -> tuple[str, ...]:
    items = list(values)
    if len(items) != len(set(items)):
        raise ValueError(f"{label} must not contain duplicates.")
    unknown = sorted(set(items) - allowed)
    if unknown:
        raise ValueError(f"Unknown {label}: {', '.join(unknown)}")
    return tuple(sorted(items))


class StencilDefinition(BaseModel):
    """Immutable build-time feature, menu, loop, and workload composition contract."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["fdai.stencil-definition.v1"] = STENCIL_DEFINITION_SCHEMA
    stencil_id: str = Field(min_length=1, max_length=63)
    title: str = Field(min_length=1, max_length=160)
    title_ko: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=500)
    description_ko: str = Field(min_length=1, max_length=500)
    topology_profile: TopologyProfile
    enabled_workloads: tuple[str, ...]
    enabled_scheduled_jobs: tuple[str, ...]
    enabled_loops: tuple[str, ...]
    enabled_addons: tuple[str, ...]
    enabled_panel_ids: tuple[str, ...]
    authority_granted: Literal[False] = False

    @model_validator(mode="after")
    def _validate_invariants(self) -> StencilDefinition:
        if _STENCIL_ID_RE.fullmatch(self.stencil_id) is None:
            raise ValueError("stencil_id must be lowercase ASCII kebab-case (1..63 chars).")
        if not self.title.strip() or not self.title_ko.strip():
            raise ValueError("Stencil titles must not be blank.")
        if not self.description.strip() or not self.description_ko.strip():
            raise ValueError("Stencil descriptions must not be blank.")

        workloads = _canonical_sorted_unique(
            self.enabled_workloads, "enabled_workloads", frozenset(ALL_WORKLOADS)
        )
        if tuple(self.enabled_workloads) != workloads:
            raise ValueError("enabled_workloads must be sorted in canonical order.")
        missing_workloads = sorted(set(LOCKED_CORE_WORKLOADS) - set(workloads))
        if missing_workloads:
            raise ValueError(
                f"Locked core workloads cannot be disabled: {', '.join(missing_workloads)}"
            )

        jobs = _canonical_sorted_unique(
            self.enabled_scheduled_jobs,
            "enabled_scheduled_jobs",
            frozenset(ALL_SCHEDULED_JOBS),
        )
        if tuple(self.enabled_scheduled_jobs) != jobs:
            raise ValueError("enabled_scheduled_jobs must be sorted in canonical order.")
        missing_jobs = sorted(set(LOCKED_CORE_SCHEDULED_JOBS) - set(jobs))
        if missing_jobs:
            raise ValueError(
                f"Locked core scheduled jobs cannot be disabled: {', '.join(missing_jobs)}"
            )

        loops = _canonical_sorted_unique(self.enabled_loops, "enabled_loops", frozenset(ALL_LOOPS))
        if tuple(self.enabled_loops) != loops:
            raise ValueError("enabled_loops must be sorted in canonical order.")
        missing_loops = sorted(set(LOCKED_CORE_LOOPS) - set(loops))
        if missing_loops:
            raise ValueError(
                f"Locked core agent loops cannot be disabled: {', '.join(missing_loops)}"
            )

        addons = _canonical_sorted_unique(
            self.enabled_addons, "enabled_addons", frozenset(ALL_ADDONS)
        )
        if tuple(self.enabled_addons) != addons:
            raise ValueError("enabled_addons must be sorted in canonical order.")
        missing_addons = sorted(set(LOCKED_CORE_ADDONS) - set(addons))
        if missing_addons:
            raise ValueError(f"Locked core add-ons cannot be disabled: {', '.join(missing_addons)}")

        panels = _canonical_sorted_unique(
            self.enabled_panel_ids, "enabled_panel_ids", frozenset(ALL_PANEL_IDS)
        )
        if tuple(self.enabled_panel_ids) != panels:
            raise ValueError("enabled_panel_ids must be sorted in canonical order.")
        missing_panels = sorted(set(LOCKED_CORE_PANELS) - set(panels))
        if missing_panels:
            raise ValueError(
                f"Locked safety-core Console menus cannot be disabled: {', '.join(missing_panels)}"
            )

        # Enforce panel-to-workload/loop/addon dependency closure so a selected menu
        # never ships without its backing runtime loop or service workload.
        workload_set = set(workloads)
        loop_set = set(loops)
        addon_set = set(addons)
        for panel_id in panels:
            descriptor = PANEL_BY_ID[panel_id]
            unmet_workloads = sorted(set(descriptor.required_workloads) - workload_set)
            if unmet_workloads:
                raise ValueError(
                    f"Panel {panel_id!r} requires workload(s): {', '.join(unmet_workloads)}"
                )
            unmet_loops = sorted(set(descriptor.required_loops) - loop_set)
            if unmet_loops:
                raise ValueError(
                    f"Panel {panel_id!r} requires agent loop(s): {', '.join(unmet_loops)}"
                )
            unmet_addons = sorted(set(descriptor.required_addons) - addon_set)
            if unmet_addons:
                raise ValueError(
                    f"Panel {panel_id!r} requires add-on(s): {', '.join(unmet_addons)}"
                )

        if "document-ingestion" in loop_set and not {
            "document-ingestion-api",
            "document-processing-worker",
        }.issubset(workload_set):
            raise ValueError(
                "Loop 'document-ingestion' requires 'document-ingestion-api' "
                "and 'document-processing-worker' workloads."
            )
        if {"document-ingestion-api", "document-processing-worker"} & workload_set and (
            "document-ingestion" not in loop_set
            or not {"document-ingestion-api", "document-processing-worker"}.issubset(workload_set)
        ):
            raise ValueError(
                "Document ingestion workloads require both 'document-ingestion-api' and "
                "'document-processing-worker' plus the 'document-ingestion' loop."
            )
        if "remediation-execution" in loop_set and "isolated-executor" not in workload_set:
            raise ValueError(
                "Loop 'remediation-execution' requires the 'isolated-executor' workload."
            )
        if "isolated-executor" in workload_set and "remediation-execution" not in loop_set:
            raise ValueError(
                "Workload 'isolated-executor' requires the 'remediation-execution' loop."
            )
        if "cost-collector" in jobs and "cost-governance" not in loop_set:
            raise ValueError("Scheduled job 'cost-collector' requires the 'cost-governance' loop.")
        if "cost-governance" in loop_set and "cost-collector" not in jobs:
            raise ValueError("Loop 'cost-governance' requires the 'cost-collector' scheduled job.")
        if ({"governed-execution", "policy-administration"} & addon_set) and (
            "enterprise-identity-governance" not in addon_set
        ):
            raise ValueError(
                "Add-ons 'governed-execution' and 'policy-administration' require "
                "'enterprise-identity-governance'."
            )
        if self.topology_profile == "lite-observe-alert":
            forbidden_lite_workloads = sorted(workload_set - set(LOCKED_CORE_WORKLOADS))
            if forbidden_lite_workloads:
                raise ValueError(
                    "topology_profile 'lite-observe-alert' allows only core-control-plane and "
                    f"operator-service workloads; found: {', '.join(forbidden_lite_workloads)}"
                )
            if "governed-execution" in addon_set or "remediation-execution" in loop_set:
                raise ValueError(
                    "topology_profile 'lite-observe-alert' is observation-only and "
                    "cannot enable governed execution."
                )
        return self

    @property
    def enabled_feature_ids(self) -> tuple[str, ...]:
        features: set[str] = set()
        for panel_id in self.enabled_panel_ids:
            features.update(PANEL_BY_ID[panel_id].feature_ids)
        return tuple(sorted(features))

    @property
    def digest(self) -> str:
        payload = self.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(canonical).hexdigest()


STENCIL_PRESETS: Mapping[str, StencilDefinition] = {
    "lite-observe-alert": StencilDefinition(
        stencil_id="lite-observe-alert",
        title="Lite: Agent-Driven Observe, Drift & Alert",
        title_ko="경량 에디션: 에이전트 주도 변경·장애 감지 및 알림",
        description=(
            "Minimal Azure resource footprint. Runs Core 15-agent pantheon and Operator API only "
            "for continuous resource change/drift detection, deterministic anomaly detection, and "
            "notifications without ClamAV, document ingestion workers, or privileged execution."
        ),
        description_ko=(
            "최소한의 Azure 리소스만 생성하는 경량 버전입니다. ClamAV, 문서 수집 워커, "
            "조치 실행기 없이 Core 15-에이전트 판테온과 Operator API만으로 리소스 변경/드리프트 "
            "감지, 장애 감지, 알림 발송만 수행합니다."
        ),
        topology_profile="lite-observe-alert",
        enabled_workloads=LOCKED_CORE_WORKLOADS,
        enabled_scheduled_jobs=LOCKED_CORE_SCHEDULED_JOBS,
        enabled_loops=LOCKED_CORE_LOOPS,
        enabled_addons=LOCKED_CORE_ADDONS,
        enabled_panel_ids=LITE_OBSERVE_ALERT_PANELS,
    ),
    "standard-sre": StencilDefinition(
        stencil_id="standard-sre",
        title="Standard: SRE Detection, RCA & Governed Execution",
        title_ko="표준 에디션: SRE 감지·근본원인 분석 및 승인 기반 조치",
        description=(
            "Adds RCA, topology workbench, human approval queue (HIL), and isolated executor "
            "while omitting heavy document ingestion and FinOps/code-security extensions."
        ),
        description_ko=(
            "경량 감지·알림 기능에 더해 토폴로지 워크벤치, 근본 원인 분석(RCA), "
            "인간 승인 대기열(HIL) 및 격리된 실행기(Isolated Executor)를 포함하며, "
            "무거운 문서 수집기와 비용/코드보안 확장은 제외합니다."
        ),
        topology_profile="standard-sre",
        enabled_workloads=tuple(sorted({*LOCKED_CORE_WORKLOADS, "isolated-executor"})),
        enabled_scheduled_jobs=tuple(sorted({*LOCKED_CORE_SCHEDULED_JOBS, "canary"})),
        enabled_loops=tuple(sorted({*LOCKED_CORE_LOOPS, "remediation-execution"})),
        enabled_addons=tuple(
            sorted(
                {
                    *LOCKED_CORE_ADDONS,
                    "enterprise-identity-governance",
                    "governed-execution",
                }
            )
        ),
        enabled_panel_ids=STANDARD_SRE_PANELS,
    ),
    "full-enterprise": StencilDefinition(
        stencil_id="full-enterprise",
        title="Full: Enterprise Control Plane, Knowledge & FinOps",
        title_ko="전체 에디션: 엔터프라이즈 통합 컨트롤 플레인·지식·비용·보안",
        description=(
            "Complete FDAI distribution including all 60+ Console menus, document ingestion with "
            "ClamAV sidecar, Cost Governance, AKS Commerce, Code Security, and Assurance Twin."
        ),
        description_ko=(
            "모든 Console 메뉴, ClamAV 사이드카 기반 문서 지식 수집, 비용 거버넌스, AKS 커머스, "
            "코드 보안 스캔, 보증 디지털 트윈을 모두 포함하는 전체 엔터프라이즈 배포판입니다."
        ),
        topology_profile="full-enterprise",
        enabled_workloads=ALL_WORKLOADS,
        enabled_scheduled_jobs=ALL_SCHEDULED_JOBS,
        enabled_loops=ALL_LOOPS,
        enabled_addons=ALL_ADDONS,
        enabled_panel_ids=ALL_PANEL_IDS,
    ),
}


def compose_custom_stencil(
    *,
    stencil_id: str,
    title: str,
    title_ko: str,
    description: str,
    description_ko: str,
    topology_profile: TopologyProfile = "lite-observe-alert",
    requested_panel_ids: Iterable[str],
    requested_workloads: Iterable[str] = (),
    requested_scheduled_jobs: Iterable[str] = (),
    requested_loops: Iterable[str] = (),
    requested_addons: Iterable[str] = (),
    auto_resolve_dependencies: bool = True,
) -> StencilDefinition:
    """Compose a validated StencilDefinition and resolve required backing dependencies."""

    panels = set(requested_panel_ids) | set(LOCKED_CORE_PANELS)
    unknown_panels = sorted(panels - set(ALL_PANEL_IDS))
    if unknown_panels:
        raise ValueError(f"Unknown Console panel id(s): {', '.join(unknown_panels)}")

    workloads = set(requested_workloads) | set(LOCKED_CORE_WORKLOADS)
    jobs = set(requested_scheduled_jobs) | set(LOCKED_CORE_SCHEDULED_JOBS)
    loops = set(requested_loops) | set(LOCKED_CORE_LOOPS)
    addons = set(requested_addons) | set(LOCKED_CORE_ADDONS)

    if auto_resolve_dependencies:
        for panel_id in sorted(panels):
            descriptor = PANEL_BY_ID[panel_id]
            workloads.update(descriptor.required_workloads)
            loops.update(descriptor.required_loops)
            addons.update(descriptor.required_addons)
        if "document-ingestion" in loops or (
            {"document-ingestion-api", "document-processing-worker"} & workloads
        ):
            workloads.update(("document-ingestion-api", "document-processing-worker"))
            loops.add("document-ingestion")
        if "remediation-execution" in loops or "isolated-executor" in workloads:
            workloads.add("isolated-executor")
            loops.add("remediation-execution")
            addons.update(("enterprise-identity-governance", "governed-execution"))
        if "cost-collector" in jobs or "cost-governance" in loops:
            loops.add("cost-governance")
            jobs.add("cost-collector")
        if {"governed-execution", "policy-administration"} & addons:
            addons.add("enterprise-identity-governance")
        if topology_profile == "lite-observe-alert":
            if "document-ingestion" in loops:
                topology_profile = "full-enterprise"
            elif (
                len(workloads - set(LOCKED_CORE_WORKLOADS)) > 0
                or "governed-execution" in addons
                or "remediation-execution" in loops
            ):
                topology_profile = "standard-sre"

    return StencilDefinition(
        stencil_id=stencil_id,
        title=title,
        title_ko=title_ko,
        description=description,
        description_ko=description_ko,
        topology_profile=topology_profile,
        enabled_workloads=tuple(sorted(workloads)),
        enabled_scheduled_jobs=tuple(sorted(jobs)),
        enabled_loops=tuple(sorted(loops)),
        enabled_addons=tuple(sorted(addons)),
        enabled_panel_ids=tuple(sorted(panels)),
    )


def evaluate_stencil_footprint(stencil: StencilDefinition) -> dict[str, Any]:
    """Compute resource savings, omitted components, RBAC posture, and build commands."""

    omitted_workloads = tuple(sorted(set(ALL_WORKLOADS) - set(stencil.enabled_workloads)))
    omitted_jobs = tuple(sorted(set(ALL_SCHEDULED_JOBS) - set(stencil.enabled_scheduled_jobs)))
    omitted_panels = tuple(sorted(set(ALL_PANEL_IDS) - set(stencil.enabled_panel_ids)))
    includes_clamav = "document-ingestion-api" in stencil.enabled_workloads
    includes_executor = "isolated-executor" in stencil.enabled_workloads

    active_groups = tuple(
        sorted({PANEL_BY_ID[panel_id].group for panel_id in stencil.enabled_panel_ids})
    )
    rbac_roles = ["Reader", "Monitoring Reader", "Log Analytics Reader"]
    if "cost-governance" in stencil.enabled_loops:
        rbac_roles.append("Cost Management Reader")
    if includes_executor and "governed-execution" in stencil.enabled_addons:
        rbac_roles.append("Scoped Executor Action Role (privileged mutation)")

    panel_csv = ",".join(stencil.enabled_panel_ids)
    return {
        "stencil_id": stencil.stencil_id,
        "stencil_digest": stencil.digest,
        "topology_profile": stencil.topology_profile,
        "workload_count": len(stencil.enabled_workloads),
        "total_workloads": len(ALL_WORKLOADS),
        "omitted_workloads": list(omitted_workloads),
        "scheduled_job_count": len(stencil.enabled_scheduled_jobs),
        "omitted_scheduled_jobs": list(omitted_jobs),
        "includes_clamav_sidecar": includes_clamav,
        "includes_privileged_executor": includes_executor,
        "enabled_panel_count": len(stencil.enabled_panel_ids),
        "total_panel_count": len(ALL_PANEL_IDS),
        "omitted_panel_count": len(omitted_panels),
        "active_navigation_groups": list(active_groups),
        "enabled_feature_ids": list(stencil.enabled_feature_ids),
        "azure_rbac_posture": (
            "read-only-observation" if not includes_executor else "governed-execution"
        ),
        "required_azure_roles": rbac_roles,
        "terraform_flags": {
            "enable_document_ingestion_workloads": includes_clamav,
            "enable_isolated_executor": includes_executor,
            "product_profile_mode": "observation-first",
        },
        "console_build_command": (
            f"FDAI_STENCIL_ENABLED_PANELS='{panel_csv}' npm --prefix console run build"
        ),
    }


def build_stencil_release_manifest(
    stencil: StencilDefinition,
    *,
    release_version: str,
    source_commit: str,
    platform_tag: Literal["linux-x86_64", "linux-aarch64"] = "linux-x86_64",
    component_digests: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Generate a valid fdai.application-release.v2 manifest for the Stencil's components."""

    if _SEMVER_RE.fullmatch(release_version) is None or len(release_version) > 64:
        raise ValueError("release_version must be canonical SemVer (at most 64 chars).")
    if _COMMIT_SHA_RE.fullmatch(source_commit) is None:
        raise ValueError("source_commit must be a 40-character lowercase hex SHA.")

    required_components = list(stencil.enabled_workloads)
    if "document-ingestion-api" in stencil.enabled_workloads:
        required_components.append("clamav")
    required_components.append("pgvector")

    components: dict[str, dict[str, str]] = {}
    for index, name in enumerate(sorted(set(required_components)), start=1):
        provided = (component_digests or {}).get(name)
        if provided is not None:
            if not re.fullmatch(r"sha256:[0-9a-f]{64}\Z", provided):
                raise ValueError(f"Invalid digest for component {name!r}.")
            digest = provided
        else:
            seed = f"{stencil.digest}:{release_version}:{source_commit}:{name}:{index}".encode()
            digest = "sha256:" + hashlib.sha256(seed).hexdigest()
        components[name] = {"image_digest": digest}

    manifest: dict[str, Any] = {
        "schema_version": "fdai.application-release.v2",
        "product": "fdai",
        "release_version": release_version,
        "source_commit": source_commit,
        "platform_tag": platform_tag,
        "components": components,
    }
    # Round C05 hardening: verify generated manifest with the canonical lifecycle release parser.
    parse_lifecycle_release_manifest(canonical_bytes(manifest))
    return manifest


class StencilComposeRequest(BaseModel):
    """Operator request to compose and validate a custom Stencil and its Release manifest draft."""

    model_config = ConfigDict(extra="forbid", strict=True)

    stencil_id: str = Field(default="custom-observe-alert", min_length=1, max_length=63)
    title: str = Field(default="Custom Observe & Alert Edition", min_length=1, max_length=160)
    title_ko: str = Field(default="맞춤형 감지 및 알림 에디션", min_length=1, max_length=160)
    description: str = Field(
        default="Operator-selected custom Console menus, agent loops, and minimal workloads.",
        min_length=1,
        max_length=500,
    )
    description_ko: str = Field(
        default="관리자가 직접 선택한 Console 메뉴, 에이전트 루프 및 최소 워크로드 구성입니다.",
        min_length=1,
        max_length=500,
    )
    topology_profile: TopologyProfile = "lite-observe-alert"
    requested_panel_ids: tuple[str, ...] = LITE_OBSERVE_ALERT_PANELS
    requested_workloads: tuple[str, ...] = LOCKED_CORE_WORKLOADS
    requested_scheduled_jobs: tuple[str, ...] = LOCKED_CORE_SCHEDULED_JOBS
    requested_loops: tuple[str, ...] = LOCKED_CORE_LOOPS
    requested_addons: tuple[str, ...] = LOCKED_CORE_ADDONS
    auto_resolve_dependencies: bool = True
    release_version: str = Field(default="1.7.0", min_length=1, max_length=64)
    source_commit: str = Field(default="a" * 40, min_length=40, max_length=40)


def stencil_catalog_payload() -> dict[str, Any]:
    """Return all Stencil presets, Console panel metadata, and selectable runtime axes."""

    return {
        "presets": [
            {
                "stencil": preset.model_dump(mode="json"),
                "footprint": evaluate_stencil_footprint(preset),
            }
            for preset in STENCIL_PRESETS.values()
        ],
        "panels": [
            {
                "id": panel.id,
                "group": panel.group,
                "label": panel.label,
                "label_ko": panel.label_ko,
                "locked": panel.locked,
                "required_workloads": list(panel.required_workloads),
                "required_loops": list(panel.required_loops),
                "required_addons": list(panel.required_addons),
                "feature_ids": list(panel.feature_ids),
            }
            for panel in CONSOLE_PANEL_CATALOG
        ],
        "workloads": list(ALL_WORKLOADS),
        "locked_workloads": list(LOCKED_CORE_WORKLOADS),
        "scheduled_jobs": list(ALL_SCHEDULED_JOBS),
        "locked_scheduled_jobs": list(LOCKED_CORE_SCHEDULED_JOBS),
        "loops": list(ALL_LOOPS),
        "locked_loops": list(LOCKED_CORE_LOOPS),
        "addons": list(ALL_ADDONS),
        "locked_addons": list(LOCKED_CORE_ADDONS),
        "locked_panels": list(LOCKED_CORE_PANELS),
    }


def compose_stencil_response(request: StencilComposeRequest) -> dict[str, Any]:
    """Compose a custom Stencil, evaluate its footprint, and emit a release manifest draft."""

    stencil = compose_custom_stencil(
        stencil_id=request.stencil_id,
        title=request.title,
        title_ko=request.title_ko,
        description=request.description,
        description_ko=request.description_ko,
        topology_profile=request.topology_profile,
        requested_panel_ids=request.requested_panel_ids,
        requested_workloads=request.requested_workloads,
        requested_scheduled_jobs=request.requested_scheduled_jobs,
        requested_loops=request.requested_loops,
        requested_addons=request.requested_addons,
        auto_resolve_dependencies=request.auto_resolve_dependencies,
    )
    footprint = evaluate_stencil_footprint(stencil)
    manifest = build_stencil_release_manifest(
        stencil,
        release_version=request.release_version,
        source_commit=request.source_commit,
    )
    return {
        "stencil": stencil.model_dump(mode="json"),
        "footprint": footprint,
        "release_manifest": manifest,
    }


__all__ = [
    "ALL_ADDONS",
    "ALL_LOOPS",
    "ALL_PANEL_IDS",
    "ALL_SCHEDULED_JOBS",
    "ALL_WORKLOADS",
    "CONSOLE_PANEL_CATALOG",
    "LITE_OBSERVE_ALERT_PANELS",
    "LOCKED_CORE_ADDONS",
    "LOCKED_CORE_LOOPS",
    "LOCKED_CORE_PANELS",
    "LOCKED_CORE_SCHEDULED_JOBS",
    "LOCKED_CORE_WORKLOADS",
    "PANEL_BY_ID",
    "STANDARD_SRE_PANELS",
    "STENCIL_DEFINITION_SCHEMA",
    "STENCIL_PRESETS",
    "ConsolePanelDescriptor",
    "StencilComposeRequest",
    "StencilDefinition",
    "TopologyProfile",
    "build_stencil_release_manifest",
    "compose_custom_stencil",
    "compose_stencil_response",
    "evaluate_stencil_footprint",
    "stencil_catalog_payload",
]
