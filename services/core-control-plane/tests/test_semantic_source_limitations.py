"""Typed source-limitation codes keep their code and gain a localized explanation."""

from __future__ import annotations

from fdai_core_service.semantic_source_limitations import source_limitation_text


def test_known_codes_are_explained_in_order_with_the_exact_code() -> None:
    code = "inventory_generation_transition+inventory_observation_pending"

    assert source_limitation_text(code, korean=False) == (
        "the inventory snapshot is being replaced; recently observed resource changes are "
        f"not yet applied to the graph (`{code}`)"
    )
    assert source_limitation_text(code, korean=True).startswith(
        "인벤토리 스냅샷이 교체되는 중입니다, 최근 관측된 리소스 변경이"
    )


def test_unknown_codes_stay_visible_without_invented_meaning() -> None:
    assert source_limitation_text("resource_scope_incomplete", korean=True) == (
        "`resource_scope_incomplete`"
    )


def test_code_cannot_break_out_of_inline_code() -> None:
    assert source_limitation_text("bad`code\nx", korean=False) == "`bad'code x`"
