"""Public guide exports contain original diagrams, readable text and no installation facts."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from fdai.core.wara.guidance_report import build_wara_guidance_report
from fdai.delivery.wara_guidance_presentation import (
    guidance_diagram_geometry,
    guidance_text_pages,
)
from fdai.delivery.wara_office_formats import PptxFormatEncoder
from fdai_service_contracts.wara_guidance import packaged_wara_guidance
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE


@pytest.mark.parametrize(
    "needle",
    [
        "Use virtual network links to link global Private DNS Zones",
        "Use maintenance configurations for the Dedicated",
        "Deploy AOAI Service in multiple regions",
    ],
)
@pytest.mark.parametrize("locale", ["en", "ko"])
def test_benchmark_export_draws_real_vector_diagrams_with_complete_text(needle, locale) -> None:
    catalog = packaged_wara_guidance()
    framework = json.loads(
        (
            Path(__file__).resolve().parents[4] / "rule-catalog/collected/wara-aprl/azure-wara.json"
        ).read_text()
    )
    identity = next(
        control["id"]
        for area in framework["areas"]
        for control in area["controls"]
        if control["title"].startswith(needle)
    )
    guide = catalog.resolve(identity)
    assert guide is not None
    report = build_wara_guidance_report(
        guide, locale=locale, generated_at=datetime(2026, 10, 30, tzinfo=UTC)
    )
    deck = Presentation(BytesIO(PptxFormatEncoder().encode(report)))
    assert (
        deck.slide_width * 9 == deck.slide_height * 16
        or abs(deck.slide_width / deck.slide_height - 16 / 9) < 0.001
    )
    nodes = [
        shape
        for slide in deck.slides
        for shape in slide.shapes
        if shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE
    ]
    connectors = [
        shape
        for slide in deck.slides
        for shape in slide.shapes
        if shape.shape_type == MSO_SHAPE_TYPE.LINE
    ]
    assert len(nodes) == len(guide.diagram.nodes)
    assert len(connectors) >= len(guide.diagram.edges)
    assert sum(
        bool(connector._element.xpath(".//a:tailEnd[@type='triangle']")) for connector in connectors
    ) == len(guide.diagram.edges)
    assert len(deck.slides) >= 9
    text = "\n".join(
        shape.text for slide in deck.slides for shape in slide.shapes if shape.has_text_frame
    )
    assert guide.content_digest in text
    assert guide.recommendation_id in text
    assert all(source.url in text for source in guide.sources)
    assert all(
        (node.label.ko if locale == "ko" and node.label.ko else node.label.en) in text
        for node in guide.diagram.nodes
    )
    assert "scope_digest" not in report.variables
    assert "satisfaction" not in report.variables
    assert report.variables["execution_authority"] == "false"
    for slide in deck.slides:
        for shape in slide.shapes:
            assert 0 <= shape.left < deck.slide_width
            assert 0 <= shape.top < deck.slide_height
            assert shape.left + shape.width <= deck.slide_width
            assert shape.top + shape.height <= deck.slide_height


def test_public_guidance_does_not_replace_disabled_history_with_current_advice() -> None:
    guide = next(
        entry for entry in packaged_wara_guidance().entries if entry.lifecycle == "disabled"
    )
    report = build_wara_guidance_report(
        guide, locale="en", generated_at=datetime(2026, 10, 30, tzinfo=UTC)
    )
    assert "disabled" in report.tags
    assert report.variables["lifecycle"] == "disabled"
    assert report.variables["execution_authority"] == "false"


def test_public_export_does_not_hide_unavailable_widgets() -> None:
    guide = packaged_wara_guidance().entries[0]
    report = build_wara_guidance_report(
        guide, locale="en", generated_at=datetime(2026, 10, 30, tzinfo=UTC)
    )
    failed = replace(report.widgets[0], error="source_unavailable")
    with pytest.raises(ValueError, match="widget error"):
        PptxFormatEncoder().encode(replace(report, widgets=(failed,)))


def test_all_456_presentation_diagrams_keep_connectors_out_of_other_nodes() -> None:
    for guide in packaged_wara_guidance().entries:
        positions, routes = guidance_diagram_geometry(guide.diagram)
        assert len(routes) == len(guide.diagram.edges)
        for edge, points in zip(guide.diagram.edges, routes, strict=True):
            for start, end in zip(points[:-1], points[1:], strict=True):
                assert start[0] == end[0] or start[1] == end[1]
                for identity, (left, top) in positions.items():
                    if identity in {edge.from_, edge.to}:
                        continue
                    right, bottom = left + 3.65, top + 1.15
                    if start[1] == end[1]:
                        enters = (
                            top < start[1] < bottom
                            and min(start[0], end[0]) < right
                            and max(start[0], end[0]) > left
                        )
                    else:
                        enters = (
                            left < start[0] < right
                            and min(start[1], end[1]) < bottom
                            and max(start[1], end[1]) > top
                        )
                    assert not enters, (guide.recommendation_id, identity, edge)


def test_korean_prose_reserves_full_width_glyph_rows_instead_of_clipping() -> None:
    line = "검토한 구성과 현재 관찰을 구분하고 명시적인 조건을 확인합니다. " * 2
    text = "\n".join([line] * 13)
    pages = guidance_text_pages(text)
    assert len(pages) >= 2
    assert "".join("".join(page) for page in pages).replace(" ", "") == text.replace(
        "\n", ""
    ).replace(" ", "")
