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
    "source_incomplete": (
        "원본 완전성을 확인할 수 없습니다",
        "source completeness could not be verified",
    ),
}


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


__all__ = ["source_limitation_text"]
