"""Deterministic Office Open XML rendering for configuration baselines."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Final

from fdai.core.detection.configuration_drift import (
    ConfigurationLink,
    ConfigurationObservation,
    FrozenConfigurationBaseline,
)
from fdai.shared.providers.local.document_structure import extract_ooxml

_WORD_NS: Final[str] = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def render_configuration_baseline_docx(
    *,
    observation: ConfigurationObservation,
    version: str,
    created_at: datetime,
    source: str,
    allowed_exceptions: tuple[str, ...] = (),
    unknown_items: tuple[str, ...] = (),
) -> bytes:
    """Render one reviewable DOCX from the same observation used for JSON freeze."""

    body: list[str] = [
        _paragraph("Configuration Infrastructure Baseline", style="Title"),
        _heading("1. Document purpose and scope"),
        _paragraph(
            "This document freezes reviewed intended infrastructure state for read-only "
            f"configuration drift checks. Scope: {observation.scope}."
        ),
        _heading("2. Baseline version and creation UTC"),
        _paragraph(f"Version: {version}"),
        _paragraph(f"Created UTC: {created_at.isoformat()}"),
        _heading("3. Baseline source"),
        _paragraph(f"Azure Resource Graph actual snapshot: {observation.observed_at.isoformat()}"),
        _paragraph(f"Reviewed and frozen intended baseline: {source}"),
        _heading("4. Expected resource inventory"),
        _inventory_table(observation),
        _heading("5. Workload topology"),
        *_topology(observation.links),
        _heading("6. Network baseline"),
        _paragraph(
            "VNet, subnet, NSG custom inbound allow rules, and public-network-access values "
            "are frozen in the inventory attributes and topology relationships above."
        ),
        _heading("7. Observability baseline"),
        _paragraph(
            "Diagnostic settings, Log Analytics, and Container Insights values are frozen in "
            "the inventory attributes. Missing evidence remains unknown."
        ),
        _heading("8. Certificate baseline"),
        _paragraph(
            "Application Gateway, API Management, Key Vault, and other certificate evidence "
            "must be checked read-only. Expiry thresholds are policy inputs, not inferred values."
        ),
        _heading("9. Allowed exceptions and intended differences"),
        *_items(allowed_exceptions, empty="No allowed exceptions were recorded."),
        _heading("10. Unknown or insufficient-access items"),
        *_items(unknown_items, empty="No unknown items were recorded."),
        _heading("11. Drift decision rules"),
        _paragraph(
            "Added, removed, changed, and unchanged values are reported separately. Missing "
            "or inaccessible evidence remains unknown or unauthorized and is never healthy. "
            "The baseline is immutable and is not replaced by a later actual snapshot."
        ),
    ]
    body.append('<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr>')
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_WORD_NS}"><w:body>{"".join(body)}</w:body></w:document>'
    )
    return _package(document)


def write_configuration_baseline_docx(path: Path, content: bytes) -> None:
    """Atomically write a rendered DOCX."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_configuration_baseline_docx(
    baseline: FrozenConfigurationBaseline,
    content: bytes,
) -> None:
    """Fail when a DOCX omits any structured fact from its paired baseline."""

    visible_text = "\n".join(unit.text for unit in extract_ooxml(content))
    required = [
        f"Scope: {baseline.scope}.",
        f"Version: {baseline.version}",
        f"Created UTC: {baseline.created_at.isoformat()}",
        f"Reviewed and frozen intended baseline: {baseline.source}",
    ]
    for resource in baseline.resources:
        required.extend((resource.resource_type, resource.local_name, resource.region))
        required.extend(f"{key}={_display(value)}" for key, value in resource.attributes.items())
        required.extend(f"unknown:{item}" for item in resource.unknown_attributes)
        required.extend(f"unauthorized:{item}" for item in resource.unauthorized_attributes)
    required.extend(f"{link.source} {link.relation} {link.target}" for link in baseline.links)
    required.extend(baseline.allowed_exceptions)
    required.extend(baseline.unknown_items)
    if any(fact not in visible_text for fact in required):
        raise ValueError("configuration baseline DOCX does not match the canonical baseline")


def _inventory_table(observation: ConfigurationObservation) -> str:
    rows = [
        ("Resource type", "Local resource name", "Region", "Attributes", "Evidence gaps"),
    ]
    for resource in observation.resources:
        attributes = (
            "; ".join(f"{key}={_display(value)}" for key, value in resource.attributes.items())
            or "none"
        )
        gaps = (
            "; ".join(
                [
                    *(f"unknown:{item}" for item in sorted(resource.unknown_attributes)),
                    *(f"unauthorized:{item}" for item in sorted(resource.unauthorized_attributes)),
                ]
            )
            or "none"
        )
        rows.append(
            (
                resource.resource_type,
                resource.local_name,
                resource.region,
                attributes,
                gaps,
            )
        )
    return _table(rows)


def _topology(links: tuple[ConfigurationLink, ...]) -> list[str]:
    if not links:
        return [_paragraph("No topology relationship was observed; coverage remains unknown.")]
    return [_paragraph(f"{link.source} {link.relation} {link.target}") for link in links]


def _items(values: Iterable[str], *, empty: str) -> list[str]:
    items = tuple(values)
    return (
        [_paragraph(value, style="ListBullet") for value in items] if items else [_paragraph(empty)]
    )


def _display(value: object) -> str:
    if isinstance(value, Mapping):
        return ",".join(f"{key}:{_display(item)}" for key, item in sorted(value.items()))
    if isinstance(value, (list, tuple)):
        return ",".join(_display(item) for item in value)
    return str(value)


def _heading(text: str) -> str:
    return _paragraph(text, style="Heading1")


def _paragraph(text: str, *, style: str | None = None) -> str:
    properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{properties}<w:r><w:t>{escape(text)}</w:t></w:r></w:p>"


def _table(rows: Sequence[Sequence[str]]) -> str:
    rendered_rows = []
    for row in rows:
        cells = "".join(
            f"<w:tc><w:tcPr/><w:p><w:r><w:t>{escape(cell)}</w:t></w:r></w:p></w:tc>" for cell in row
        )
        rendered_rows.append(f"<w:tr>{cells}</w:tr>")
    return (
        f'<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/></w:tblPr>{"".join(rendered_rows)}</w:tbl>'
    )


def _package(document: str) -> bytes:
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        "</Relationships>"
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:styles xmlns:w="{_WORD_NS}">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
        '<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/></w:style>'
        '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/></w:style>'
        "</w:styles>"
    )
    members = {
        "[Content_Types].xml": content_types,
        "_rels/.rels": relationships,
        "word/document.xml": document,
        "word/_rels/document.xml.rels": document_relationships,
        "word/styles.xml": styles,
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, text in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, text.encode("utf-8"))
    return stream.getvalue()


__all__ = [
    "render_configuration_baseline_docx",
    "validate_configuration_baseline_docx",
    "write_configuration_baseline_docx",
]
