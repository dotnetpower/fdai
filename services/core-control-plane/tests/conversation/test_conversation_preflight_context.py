"""A long earlier answer never stops the routing preflight for the current question."""

from __future__ import annotations

import logging

import pytest
from fdai.core.conversation.conversation_preflight_validation import bounded_context


def test_the_newest_turns_that_fit_are_kept_in_order(caplog: pytest.LogCaptureFixture) -> None:
    long_answer = "a" * 3_800
    context = ("user:first", long_answer, "user:second", "assistant:" + "b" * 300)

    with caplog.at_level(logging.INFO):
        kept = bounded_context(context)

    assert kept[-2:] == ("user:second", "assistant:" + "b" * 300)
    assert kept[0] == long_answer[: 4_000 - len(kept[-1]) - len(kept[-2])]
    assert "user:first" not in kept
    record = next(
        item for item in caplog.records if item.msg == "conversation_preflight_context_trimmed"
    )
    assert (record.context_items_kept, record.context_items_dropped) == (3, 1)


def test_short_context_passes_unchanged_without_a_trim_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        assert bounded_context(("user:hi", "assistant:hello")) == ("user:hi", "assistant:hello")
    assert not [
        item for item in caplog.records if item.msg == "conversation_preflight_context_trimmed"
    ]


def test_non_text_context_is_still_rejected() -> None:
    with pytest.raises(TypeError):
        bounded_context(("user:hi", 3))  # type: ignore[arg-type]


def test_multiline_outbound_bullet_list_is_compacted_in_preflight_context() -> None:
    rows = "\n".join(f"- `rg-{idx:02d}` - resource-group / westus3" for idx in range(41))
    outbound = (
        f"outbound:## 일치하는 리소스 41개\n\n{rows}\n\n이 결과는 실행 권한을 부여하지 않습니다."
    )
    kept = bounded_context(("inbound:리소스그룹이 몇개인가?", outbound))

    assert len(kept[1].splitlines()) == 4
    assert "rg-00" in kept[1] and "rg-01" in kept[1]
    assert "rg-20" not in kept[1]
    assert kept[1].endswith("이 결과는 실행 권한을 부여하지 않습니다.")
