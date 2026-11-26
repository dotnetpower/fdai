"""Localized verified and unavailable subscription answer tests."""

from __future__ import annotations

from fdai_core_service.semantic_subscription_scope_answer import render_subscription_scope_answer

DIGEST = "sha256:" + ("a" * 64)


def _outputs(*, complete: bool = True) -> list[dict[str, object]]:
    return [
        {
            "source_complete": complete,
            "rows": (
                [
                    {
                        "values": {
                            "display_name": "Example subscription",
                            "state": "Enabled",
                            "masked_subscription_id": "0000...0000",
                            "observed_at": "2026-09-05T12:00:00+00:00",
                            "evidence_digest": DIGEST,
                            "execution_authority": False,
                        }
                    }
                ]
                if complete
                else []
            ),
        }
    ]


def test_answer_renders_verified_english_and_korean_facts() -> None:
    english = render_subscription_scope_answer(
        _outputs(),
        korean=False,
        output_shape="subscription_scope_identity",
    )
    korean = render_subscription_scope_answer(
        _outputs(),
        korean=True,
        output_shape="subscription_scope_identity",
    )

    assert english is not None
    assert "Current Azure subscription" in english
    assert "Example subscription" in english
    assert "0000...0000" in english
    assert "no action ran" in english
    assert korean is not None
    assert "현재 Azure 구독" in korean
    assert "관측 시각" in korean
    assert "실행 작업도 발생하지 않았습니다" in korean


def test_answer_fails_closed_when_provider_evidence_is_unavailable() -> None:
    answer = render_subscription_scope_answer(
        _outputs(complete=False),
        korean=False,
        output_shape="subscription_scope_identity",
    )

    assert answer is not None
    assert "unavailable" in answer
    assert "Example subscription" not in answer
