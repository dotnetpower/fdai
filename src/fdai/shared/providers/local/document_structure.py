"""Bounded structural extraction for modern Office and text PDF documents."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from fdai.shared.contracts import StructuralUnit
from fdai.shared.providers.local.document_pdf import (
    extract_pdf_text,
    normalize_pdf_ocr_units,
)

_MAX_ZIP_MEMBERS = 2048
_MAX_EXPANDED_BYTES = 64 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 100
_HEADING_STYLE = re.compile(r"heading\s*([1-9])", re.IGNORECASE)
_SLIDE_NUMBER = re.compile(r"slide(\d+)\.xml$")
_NOTES_NUMBER = re.compile(r"notesSlide(\d+)\.xml$")


def extract_ooxml(content: bytes) -> tuple[StructuralUnit, ...]:
    """Extract cited structural units from one bounded OOXML package."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = {item.filename for item in validated_zip_members(archive)}
        if "word/document.xml" in names:
            return _extract_docx(_xml_root(archive.read("word/document.xml")))
        slide_names = sorted(
            (name for name in names if _SLIDE_NUMBER.search(name)),
            key=_numbered_part,
        )
        if slide_names:
            note_names = {
                _numbered_part(name): name for name in names if _NOTES_NUMBER.search(name)
            }
            return _extract_pptx(archive, slide_names, note_names)
        sheet_names = sorted(
            name
            for name in names
            if name == "xl/sharedStrings.xml"
            or (name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
        )
        return _extract_flat_sheets(archive, sheet_names)


def validated_zip_members(archive: zipfile.ZipFile) -> tuple[zipfile.ZipInfo, ...]:
    infos = tuple(archive.infolist())
    if len(infos) > _MAX_ZIP_MEMBERS:
        raise ValueError("container member count exceeds the parser budget")
    expanded = sum(item.file_size for item in infos)
    compressed = max(1, sum(item.compress_size for item in infos))
    if expanded > _MAX_EXPANDED_BYTES or expanded / compressed > _MAX_COMPRESSION_RATIO:
        raise ValueError("container expansion exceeds the parser budget")
    for item in infos:
        path = Path(item.filename)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("container contains an unsafe member path")
    return infos


def _extract_docx(root: ElementTree.Element) -> tuple[StructuralUnit, ...]:
    body = next((item for item in root.iter() if _local_name(item.tag) == "body"), None)
    if body is None:
        raise ValueError("DOCX document body is missing")
    units: list[StructuralUnit] = []
    paragraph_number = 0
    heading_counts: dict[int, int] = {}
    table_number = 0
    for child in body:
        child_name = _local_name(child.tag)
        if child_name == "p":
            paragraph_number += 1
            heading_level = _heading_level(child)
            if heading_level is not None:
                heading_counts[heading_level] = heading_counts.get(heading_level, 0) + 1
            text = _element_text(child)
            if not text:
                continue
            if heading_level is None:
                locator = f"docx/paragraph:{paragraph_number}"
            else:
                locator = f"docx/heading:{heading_level}:{heading_counts[heading_level]}"
            units.append(
                StructuralUnit(
                    unit_id=f"docx-paragraph-{paragraph_number}",
                    kind="paragraph",
                    locator=locator,
                    text=text,
                )
            )
        elif child_name == "tbl":
            table_number += 1
            for row_number, row in enumerate(_children_named(child, "tr"), start=1):
                for cell_number, cell in enumerate(_children_named(row, "tc"), start=1):
                    text = _element_text(cell)
                    if text:
                        units.append(
                            StructuralUnit(
                                unit_id=f"docx-table-{table_number}-r{row_number}-c{cell_number}",
                                kind="table",
                                locator=(
                                    f"docx/table:{table_number}/row:{row_number}/cell:{cell_number}"
                                ),
                                text=text,
                            )
                        )
    return tuple(units)


def _extract_pptx(
    archive: zipfile.ZipFile,
    slide_names: list[str],
    note_names: dict[int, str],
) -> tuple[StructuralUnit, ...]:
    units: list[StructuralUnit] = []
    for slide_number, slide_name in enumerate(slide_names, start=1):
        root = _xml_root(archive.read(slide_name))
        shape_tree = next((item for item in root.iter() if _local_name(item.tag) == "spTree"), None)
        if shape_tree is None:
            raise ValueError("PPTX slide shape tree is missing")
        shapes = tuple(
            shape
            for shape in shape_tree
            if _local_name(shape.tag) in {"sp", "graphicFrame", "pic", "cxnSp", "grpSp"}
        )
        for shape_number, shape in enumerate(shapes, start=1):
            tables = tuple(item for item in shape.iter() if _local_name(item.tag) == "tbl")
            if tables:
                for table_number, table in enumerate(tables, start=1):
                    _append_pptx_table_units(
                        units,
                        table,
                        slide_number=slide_number,
                        shape_number=shape_number,
                        table_number=table_number,
                    )
                continue
            text = _element_text(shape)
            if text:
                units.append(
                    StructuralUnit(
                        unit_id=f"pptx-slide-{slide_number}-shape-{shape_number}",
                        kind="slide",
                        locator=f"pptx/slide:{slide_number}/shape:{shape_number}",
                        text=text,
                    )
                )
        note_name = note_names.get(_numbered_part(slide_name))
        if note_name is not None:
            note_root = _xml_root(archive.read(note_name))
            note_number = 0
            for paragraph in (item for item in note_root.iter() if _local_name(item.tag) == "p"):
                text = _element_text(paragraph)
                if text:
                    note_number += 1
                    units.append(
                        StructuralUnit(
                            unit_id=f"pptx-slide-{slide_number}-notes-{note_number}",
                            kind="slide",
                            locator=f"pptx/slide:{slide_number}/notes:{note_number}",
                            text=text,
                        )
                    )
    return tuple(units)


def _append_pptx_table_units(
    units: list[StructuralUnit],
    table: ElementTree.Element,
    *,
    slide_number: int,
    shape_number: int,
    table_number: int,
) -> None:
    for row_number, row in enumerate(_children_named(table, "tr"), start=1):
        for cell_number, cell in enumerate(_children_named(row, "tc"), start=1):
            text = _element_text(cell)
            if text:
                units.append(
                    StructuralUnit(
                        unit_id=(
                            f"pptx-slide-{slide_number}-shape-{shape_number}-"
                            f"table-{table_number}-r{row_number}-c{cell_number}"
                        ),
                        kind="table",
                        locator=(
                            f"pptx/slide:{slide_number}/shape:{shape_number}/"
                            f"table:{table_number}/row:{row_number}/cell:{cell_number}"
                        ),
                        text=text,
                    )
                )


def _extract_flat_sheets(archive: zipfile.ZipFile, names: list[str]) -> tuple[StructuralUnit, ...]:
    units: list[StructuralUnit] = []
    for index, name in enumerate(names, start=1):
        text = _element_text(_xml_root(archive.read(name)))
        if text:
            units.append(
                StructuralUnit(
                    unit_id=f"sheet-{index}",
                    kind="sheet",
                    locator=name,
                    text=text,
                )
            )
    return tuple(units)


def _xml_root(xml: bytes) -> ElementTree.Element:
    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise ValueError("OOXML member contains a prohibited declaration")
    return ElementTree.fromstring(xml)  # noqa: S314


def _element_text(element: ElementTree.Element) -> str:
    if _local_name(element.tag) == "p":
        return _paragraph_text(element)
    paragraphs = tuple(item for item in element.iter() if _local_name(item.tag) == "p")
    if paragraphs:
        return " ".join(text for item in paragraphs if (text := _paragraph_text(item)))
    return _paragraph_text(element)


def _paragraph_text(element: ElementTree.Element) -> str:
    return "".join(
        item.text or "" for item in element.iter() if _local_name(item.tag) == "t"
    ).strip()


def _heading_level(paragraph: ElementTree.Element) -> int | None:
    style = next((item for item in paragraph.iter() if _local_name(item.tag) == "pStyle"), None)
    if style is None:
        return None
    value = next((raw for key, raw in style.attrib.items() if _local_name(key) == "val"), "")
    match = _HEADING_STYLE.fullmatch(value)
    return int(match.group(1)) if match is not None else None


def _children_named(element: ElementTree.Element, name: str) -> tuple[ElementTree.Element, ...]:
    return tuple(child for child in element if _local_name(child.tag) == name)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _numbered_part(name: str) -> int:
    match = _SLIDE_NUMBER.search(name) or _NOTES_NUMBER.search(name)
    if match is None:
        raise ValueError("OOXML numbered part name is malformed")
    return int(match.group(1))


__all__ = [
    "extract_ooxml",
    "extract_pdf_text",
    "normalize_pdf_ocr_units",
    "validated_zip_members",
]
