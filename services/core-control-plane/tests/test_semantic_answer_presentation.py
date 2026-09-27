"""Answer presentation keeps machine markers but reads as ordinary operator language."""

from __future__ import annotations

import pytest
from fdai_core_service.semantic_answer_presentation import (
    authority_line,
    completeness_text,
    readable_resource_status,
    readable_timestamp,
)


def test_authority_line_keeps_the_machine_marker_in_both_languages() -> None:
    assert "`execution_authority=false`" in authority_line(korean=True)
    assert "실행 권한이 없습니다" in authority_line(korean=True)
    assert authority_line(korean=False).startswith("This read-only result grants no execution")


@pytest.mark.parametrize(
    ("value", "korean", "expected"),
    [
        ("PowerState/deallocated", True, "할당 해제됨"),
        ("PowerState/running", False, "Running"),
        ("Stopped", True, "중지됨"),
        ("ProvisioningState/Unexpected", True, "ProvisioningState/Unexpected"),
        ("", False, ""),
    ],
)
def test_provider_status_reads_in_operator_words_or_stays_verbatim(
    value: str, korean: bool, expected: str
) -> None:
    assert readable_resource_status(value, korean=korean) == expected


def test_timezone_aware_instants_render_as_utc_seconds_and_other_text_is_unchanged() -> None:
    assert readable_timestamp("2026-09-27T09:25:26.128800+00:00") == "2026-09-27 09:25:26 UTC"
    assert readable_timestamp("2026-09-27T18:25:26+09:00") == "2026-09-27 09:25:26 UTC"
    assert readable_timestamp("2026-09-27T09:25:26") == "2026-09-27T09:25:26"
    assert readable_timestamp("Succeeded") == "Succeeded"


def test_completeness_is_named_in_the_answer_language() -> None:
    assert completeness_text(True, korean=True) == "완전"
    assert completeness_text(False, korean=True) == "불완전"
    assert completeness_text(False, korean=False) == "incomplete"
