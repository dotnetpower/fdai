"""Source-limitation codes are explained in the operator's locale and stay traceable."""

from __future__ import annotations

import pytest
from fdai.core.ontology_platform.resource_health_evidence import ResourceHealthCoverageStatus
from fdai_core_service.semantic_source_limitations import (
    known_source_limitation,
    source_limitation_text,
)


def test_a_combined_resource_health_code_is_explained_in_both_locales() -> None:
    english = source_limitation_text("target_unresolved+no_record", korean=False)
    korean = source_limitation_text("target_unresolved+no_record", korean=True)

    assert "no status record" in english and "could not be resolved" in english
    assert "상태 기록이 없습니다" in korean and "확인하지 못했습니다" in korean
    # The exact code stays for traceability.
    assert english.endswith("(`target_unresolved+no_record`)")
    assert korean.endswith("(`target_unresolved+no_record`)")
    assert known_source_limitation("target_unresolved+no_record")


@pytest.mark.parametrize("status", [item.value for item in ResourceHealthCoverageStatus])
def test_every_resource_health_coverage_gap_has_an_explanation(status: str) -> None:
    if status in {"observed", "state_absent"}:
        pytest.skip("not a limitation")

    assert known_source_limitation(status)


def test_an_unknown_code_is_shown_verbatim_without_an_invented_explanation() -> None:
    assert source_limitation_text("brand_new_code", korean=False) == "`brand_new_code`"
    assert not known_source_limitation("brand_new_code+no_record")
