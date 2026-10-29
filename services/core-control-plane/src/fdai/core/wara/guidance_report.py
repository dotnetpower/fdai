"""Public instructional reports, separate from installation assessment evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fdai_service_contracts.wara_guidance import GuidanceText, WaraGuidance

from fdai.core.reporting.models import RenderedReport, RenderedWidget


def guidance_text(value: GuidanceText, locale: Literal["en", "ko"]) -> str:
    return value.ko if locale == "ko" and value.ko is not None else value.en


def build_wara_guidance_report(
    guidance: WaraGuidance,
    *,
    locale: Literal["en", "ko"],
    generated_at: datetime,
) -> RenderedReport:
    """Render one complete source-pinned guide without an operational result."""

    if generated_at.tzinfo is None:
        raise ValueError("WARA guidance export time must be timezone-aware")
    headings = {
        "en": (
            "Why this matters",
            "Applicability",
            "Illustrative configuration",
            "Implementation",
            "Verification",
            "Cautions",
            "Public sources",
        ),
        "ko": (
            "필요한 이유",
            "적용 조건",
            "구성 예시",
            "설정 방법",
            "검증 방법",
            "주의 사항",
            "공개 출처",
        ),
    }[locale]
    widgets = [
        RenderedWidget(
            id="explanation",
            type="wara_guidance_text",
            title=headings[0],
            data={
                "body": "\n\n".join(
                    guidance_text(value, locale)
                    for value in (
                        guidance.summary,
                        guidance.rationale,
                        guidance.benefits,
                    )
                ),
            },
        ),
        RenderedWidget(
            id="applicability",
            type="wara_guidance_text",
            title=headings[1],
            data={
                "body": "\n\n".join(
                    guidance_text(value, locale) for value in guidance.applicability
                )
            },
        ),
        RenderedWidget(
            id="diagram",
            type="wara_guidance_diagram",
            title=guidance_text(guidance.diagram.title, locale),
            data={
                "diagram": guidance.diagram.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
                "locale": locale,
            },
        ),
        RenderedWidget(
            id="configuration",
            type="wara_guidance_text",
            title=headings[2],
            data={
                "body": "\n\n".join(
                    [("변경 전 예시" if locale == "ko" else "Before, illustrative")]
                    + [guidance_text(value, locale) for value in guidance.configuration.before]
                    + [("권장 구성 예시" if locale == "ko" else "Recommended, illustrative")]
                    + [guidance_text(value, locale) for value in guidance.configuration.after]
                ),
            },
        ),
    ]
    for identifier, heading, values in (
        ("implementation", headings[3], guidance.implementation_steps),
        ("verification", headings[4], guidance.verification_steps),
        ("cautions", headings[5], guidance.cautions),
    ):
        widgets.append(
            RenderedWidget(
                id=identifier,
                type="wara_guidance_text",
                title=heading,
                data={
                    "body": "\n\n".join(
                        f"{index}. {guidance_text(value, locale)}"
                        for index, value in enumerate(values, start=1)
                    )
                },
            )
        )
    widgets.append(
        RenderedWidget(
            id="sources",
            type="wara_guidance_text",
            title=headings[6],
            data={
                "body": "\n\n".join(
                    f"{guidance_text(source.label, locale)}\n{source.url}"
                    for source in guidance.sources
                )
            },
        )
    )
    return RenderedReport(
        id="wara-guidance",
        version="1.0.0",
        name=guidance_text(guidance.title, locale),
        description=(
            (
                "비활성 권고 이력입니다. 현재 권장 구성이나 실행 대상으로 사용하지 않습니다. "
                if locale == "ko"
                else "Historical disabled recommendation, not current recommended configuration. "
            )
            if guidance.lifecycle == "disabled"
            else ""
        )
        + (
            "공용 구성 예시입니다. 설치 환경의 관찰이나 충족 판정이 아닙니다."
            if locale == "ko"
            else (
                "Public instructional example, not an installation observation "
                "or satisfaction verdict."
            )
        ),
        generated_at=generated_at,
        time_range=(generated_at, generated_at),
        variables={
            "recommendation_id": guidance.recommendation_id,
            "content_digest": guidance.content_digest,
            "source_revision": guidance.source_revision,
            "source_digest": guidance.source_digest,
            "lifecycle": guidance.lifecycle,
            "locale": locale,
            "execution_authority": "false",
        },
        tags=("wara", "public-guidance", guidance.lifecycle),
        widgets=tuple(widgets),
    )


__all__ = ["build_wara_guidance_report", "guidance_text"]
