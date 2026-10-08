"""Explain typed source-limitation codes in the operator's locale.

The machine code stays visible for traceability; a known code also gets a short explanation.
"""

from __future__ import annotations

_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "inventory_projection_unavailable": (
        "인벤토리 그래프를 사용할 수 없습니다",
        "the inventory graph is unavailable",
    ),
    "inventory_generation_transition": (
        "인벤토리 스냅샷이 교체되는 중입니다",
        "the inventory snapshot is being replaced",
    ),
    "inventory_projection_incomplete": (
        "현재 인벤토리 스냅샷이 완전하지 않습니다",
        "the current inventory snapshot is incomplete",
    ),
    "inventory_projection_inconsistent": (
        "인벤토리 그래프와 매니페스트가 일치하지 않습니다",
        "the inventory graph and its manifest disagree",
    ),
    "inventory_storage_pressure": (
        "저장소 압박으로 완전성이 필요한 작업이 보류되었습니다",
        "storage pressure is holding completeness-dependent work",
    ),
    "inventory_correction_pending": (
        "인벤토리 보정이 아직 끝나지 않았습니다",
        "an inventory correction is still pending",
    ),
    "inventory_observation_pending": (
        "최근 관측된 리소스 변경이 아직 그래프에 반영되지 않았습니다",
        "recently observed resource changes are not yet applied to the graph",
    ),
    "inventory_relationship_reconciliation_pending": (
        "리소스 관계 재조정이 아직 끝나지 않았습니다",
        "resource relationship reconciliation is still pending",
    ),
    "inventory_relationship_incomplete": (
        "일부 리소스 관계를 확인할 수 없습니다",
        "some resource relationships could not be verified",
    ),
    "graph_completeness_unverified": (
        "그래프 완전성을 확인할 수 없습니다",
        "graph completeness could not be verified",
    ),
    "resource_change_coverage_unverified": (
        "리소스 변경 수집 범위를 확인하지 못했습니다",
        "resource change collection coverage is unverified",
    ),
    "change_activity_incomplete": (
        "변경 활동 기록이 완전하지 않습니다",
        "change activity records are incomplete",
    ),
    "resource_state_evidence_incomplete": (
        "리소스 상태 근거가 완전하지 않습니다",
        "resource state evidence is incomplete",
    ),
    "provider_operational_state_not_exposed": (
        "일부 리소스는 공급자가 운영 상태를 제공하지 않아 상태 조건에 맞는지 확인할 수 없습니다",
        "the provider does not expose an operational state for some resources, so whether they "
        "match the state condition cannot be verified",
    ),
    "resource_state_not_reported": (
        "일부 리소스가 운영 상태를 보고하지 않았습니다",
        "some resources reported no operational state",
    ),
    "resource_state_stale": (
        "일부 리소스의 상태 관측이 오래되었습니다",
        "some resource state observations are stale",
    ),
    "resource_state_conflicting": (
        "일부 리소스의 상태 관측이 서로 충돌합니다",
        "some resource state observations conflict",
    ),
    "source_observed_at_unavailable": (
        "원본 관측 시각을 확인할 수 없습니다",
        "the source observation time is unavailable",
    ),
    "inventory_scope_incomplete": (
        "인벤토리 범위가 완전하지 않습니다",
        "the inventory scope is incomplete",
    ),
    "resource_scope_incomplete": (
        "조회한 리소스 범위가 완전하지 않아 표시되지 않은 리소스가 있을 수 있습니다",
        "the queried resource scope is incomplete, so some resources may be missing",
    ),
    "dependency_not_completed": (
        "선행 조회 단계가 완료되지 않았습니다",
        "a prerequisite query step did not complete",
    ),
    "source_incomplete": (
        "원본 완전성을 확인할 수 없습니다",
        "source completeness could not be verified",
    ),
}


def known_source_limitation(code: str) -> bool:
    """Return whether every part of a limitation code has a reviewed explanation."""

    parts = tuple(part for part in code.split("+") if part)
    return bool(parts) and all(part in _DESCRIPTIONS for part in parts)


def source_limitation_text(code: str, *, korean: bool) -> str:
    """Return localized explanations for known codes followed by the exact code."""

    safe_code = code.replace("`", "'").replace("\r", " ").replace("\n", " ")[:256]
    descriptions = tuple(
        dict.fromkeys(
            _DESCRIPTIONS[part][0 if korean else 1]
            for part in safe_code.split("+")
            if part in _DESCRIPTIONS
        )
    )
    if not descriptions:
        return f"`{safe_code}`"
    separator = "; " if not korean else ", "
    return f"{separator.join(descriptions)} (`{safe_code}`)"


__all__ = ["known_source_limitation", "source_limitation_text"]
