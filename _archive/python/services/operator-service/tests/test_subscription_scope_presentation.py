"""Localized Console presentation for verified subscription identity."""

from __future__ import annotations

from fdai_operator_service.families.conversation.presentation_artifact_v2 import (
    compile_presentation_artifact_v2,
)
from fdai_operator_service.families.conversation.subscription_scope_presentation import (
    subscription_scope_artifact,
)

DIGEST = "sha256:" + ("a" * 64)


def _output() -> dict[str, object]:
    return {
        "source_complete": True,
        "rows": [
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
        ],
    }


def test_subscription_scope_artifact_localizes_verified_labels() -> None:
    english = subscription_scope_artifact(
        output=_output(),
        evidence_refs=["logic-invocation:" + ("b" * 64)],
        locale="en",
        verified=True,
    )
    korean = subscription_scope_artifact(
        output=_output(),
        evidence_refs=["logic-invocation:" + ("b" * 64)],
        locale="ko",
        verified=True,
    )

    assert english is not None
    assert english["blocks"][0]["title"] == "Verified subscription identity"
    assert [item["label"] for item in english["blocks"][0]["data"]["items"]] == [
        "Name",
        "State",
        "Subscription",
        "Observed at",
        "Evidence",
    ]
    assert korean is not None
    assert korean["blocks"][0]["title"] == "검증된 구독 신원"
    assert [item["label"] for item in korean["blocks"][0]["data"]["items"]] == [
        "이름",
        "상태",
        "구독",
        "관측 시각",
        "근거",
    ]


def test_subscription_scope_artifact_rejects_incomplete_source() -> None:
    assert (
        subscription_scope_artifact(
            output={"source_complete": False, "rows": []},
            evidence_refs=["logic-invocation:" + ("b" * 64)],
            locale="en",
            verified=False,
        )
        is None
    )


def test_v2_compiler_routes_subscription_shape_to_localized_artifact() -> None:
    artifact = compile_presentation_artifact_v2(
        semantic={
            "disposition": "answered",
            "checks_completed": 1,
            "checks_total": 1,
            "evidence_refs": ["logic-invocation:" + ("b" * 64)],
        },
        technical_details={
            "presentation_context": {
                "operation": "select",
                "output_shape": "subscription_scope_identity",
            },
            "outputs": [_output()],
        },
        locale="ko",
    )

    assert artifact is not None
    assert artifact["blocks"][0]["title"] == "검증된 구독 신원"
