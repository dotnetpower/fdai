"""Bounded structural extraction for modern Office OOXML packages."""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal
from xml.etree import ElementTree

from fdai_service_contracts import (
    DocumentExtractionUnavailableError,
    ExtractionUnavailableReason,
    StructuralUnit,
)

_HEADING_STYLE = re.compile(r"heading\s*([1-9])", re.IGNORECASE)
_SLIDE_NUMBER = re.compile(r"slide(\d+)\.xml$")
_NOTES_NUMBER = re.compile(r"notesSlide(\d+)\.xml$")
_SHEET_NUMBER = re.compile(r"sheet(\d+)\.xml$")
_CELL_ADDRESS = re.compile(r"[A-Z]{1,3}[1-9]\d{0,6}")


@dataclass(frozen=True, slots=True)
class OoxmlParserBudget:
    """Resource ceilings applied before and during OOXML parsing."""

    max_input_bytes: int = 25 * 1024 * 1024
    max_members: int = 10_000
    max_expanded_bytes: int = 128 * 1024 * 1024
    max_compression_ratio: float = 100.0
    max_xml_member_bytes: int = 16 * 1024 * 1024
    max_xml_depth: int = 128
    max_xml_nodes: int = 1_000_000
    max_text_characters: int = 4_000_000
    max_units: int = 100_000

    def __post_init__(self) -> None:
        values = (
            self.max_input_bytes,
            self.max_members,
            self.max_expanded_bytes,
            self.max_xml_member_bytes,
            self.max_xml_depth,
            self.max_xml_nodes,
            self.max_text_characters,
            self.max_units,
        )
        if any(value < 1 for value in values) or self.max_compression_ratio <= 0:
            raise ValueError("OOXML parser budgets MUST be positive")


def extract_ooxml(content: bytes, *, budget: OoxmlParserBudget) -> tuple[StructuralUnit, ...]:
    """Extract cited units after enforcing package and XML resource ceilings."""
    if len(content) > budget.max_input_bytes:
        raise DocumentExtractionUnavailableError(ExtractionUnavailableReason.INPUT_BUDGET)
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = {item.filename for item in _validated_members(archive, budget)}
            if "word/document.xml" in names:
                units = _extract_docx(_xml_member_root(archive, "word/document.xml", budget))
            else:
                slide_names = sorted(
                    (name for name in names if _SLIDE_NUMBER.search(name)),
                    key=_numbered_part,
                )
                if slide_names:
                    note_names = _pptx_note_names(archive, slide_names, names, budget)
                    units = _extract_pptx(archive, slide_names, note_names, budget=budget)
                else:
                    sheet_names = sorted(
                        (
                            name
                            for name in names
                            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
                        ),
                        key=_numbered_sheet,
                    )
                    units = _extract_xlsx(
                        archive,
                        sheet_names,
                        sheet_labels=_xlsx_sheet_labels(archive, names, budget),
                        shared_strings_name=(
                            "xl/sharedStrings.xml" if "xl/sharedStrings.xml" in names else None
                        ),
                        budget=budget,
                    )
    except zipfile.BadZipFile as exc:
        raise DocumentExtractionUnavailableError(
            ExtractionUnavailableReason.MALFORMED_PACKAGE
        ) from exc
    if len(units) > budget.max_units:
        raise DocumentExtractionUnavailableError(ExtractionUnavailableReason.UNIT_BUDGET)
    if sum(len(unit.text) for unit in units) > budget.max_text_characters:
        raise DocumentExtractionUnavailableError(ExtractionUnavailableReason.TEXT_BUDGET)
    return units


def _validated_members(
    archive: zipfile.ZipFile, budget: OoxmlParserBudget
) -> tuple[zipfile.ZipInfo, ...]:
    infos = tuple(archive.infolist())
    if len(infos) > budget.max_members:
        raise DocumentExtractionUnavailableError(ExtractionUnavailableReason.PACKAGE_MEMBER_BUDGET)
    normalized_names = tuple(item.filename.casefold() for item in infos)
    if len(normalized_names) != len(set(normalized_names)):
        raise DocumentExtractionUnavailableError(ExtractionUnavailableReason.UNSAFE_PACKAGE)
    expanded = sum(item.file_size for item in infos)
    compressed = max(1, sum(item.compress_size for item in infos))
    if expanded > budget.max_expanded_bytes or expanded / compressed > budget.max_compression_ratio:
        raise DocumentExtractionUnavailableError(
            ExtractionUnavailableReason.PACKAGE_EXPANSION_BUDGET
        )
    for item in infos:
        path = Path(item.filename)
        if path.is_absolute() or ".." in path.parts or item.flag_bits & 0x1:
            raise DocumentExtractionUnavailableError(ExtractionUnavailableReason.UNSAFE_PACKAGE)
    return infos


def _extract_docx(root: ElementTree.Element) -> tuple[StructuralUnit, ...]:
    body = next((item for item in root.iter() if _local_name(item.tag) == "body"), None)
    if body is None:
        raise ValueError("DOCX document body is missing")
    units: list[StructuralUnit] = []
    paragraph_number = 0
    heading_counts: dict[int, int] = {}
    active_headings: dict[int, int] = {}
    table_number = 0
    for child in body:
        child_name = _local_name(child.tag)
        if child_name == "p":
            paragraph_number += 1
            heading_level = _heading_level(child)
            if heading_level is not None:
                heading_counts[heading_level] = heading_counts.get(heading_level, 0) + 1
                active_headings = {
                    level: ordinal
                    for level, ordinal in active_headings.items()
                    if level < heading_level
                }
                active_headings[heading_level] = heading_counts[heading_level]
            text = _element_text(child)
            if not text:
                continue
            locator = (
                f"docx/heading:{heading_level}:{heading_counts[heading_level]}"
                if heading_level is not None
                else f"docx/paragraph:{paragraph_number}{_heading_context(active_headings)}"
            )
            units.append(
                StructuralUnit(
                    unit_id=f"docx-paragraph-{paragraph_number}",
                    kind="paragraph",
                    locator=locator,
                    text=text,
                    heading_level=heading_level,
                    parent_locator=(
                        _heading_parent_locator(active_headings)
                        if heading_level is None and active_headings
                        else None
                    ),
                )
            )
        elif child_name == "tbl":
            table_number += 1
            for row_number, row in enumerate(_children_named(child, "tr"), start=1):
                row_role: Literal["header", "body"] = "header" if _docx_header_row(row) else "body"
                for cell_number, cell in enumerate(_children_named(row, "tc"), start=1):
                    text = _element_text(cell)
                    if text:
                        units.append(
                            StructuralUnit(
                                unit_id=(f"docx-table-{table_number}-r{row_number}-c{cell_number}"),
                                kind="table",
                                locator=(
                                    f"docx/table:{table_number}/row:{row_number}/cell:{cell_number}"
                                ),
                                text=text,
                                table_cell_role=row_role,
                            )
                        )
    return tuple(units)


def _extract_pptx(
    archive: zipfile.ZipFile,
    slide_names: list[str],
    note_names: dict[int, str],
    *,
    budget: OoxmlParserBudget,
) -> tuple[StructuralUnit, ...]:
    units: list[StructuralUnit] = []
    for slide_number, slide_name in enumerate(slide_names, start=1):
        root = _xml_member_root(archive, slide_name, budget)
        shape_tree = next((item for item in root.iter() if _local_name(item.tag) == "spTree"), None)
        if shape_tree is None:
            raise ValueError("PPTX slide shape tree is missing")
        shapes = tuple(
            shape
            for shape in shape_tree
            if _local_name(shape.tag) in {"sp", "graphicFrame", "pic", "cxnSp", "grpSp"}
        )
        for shape_number, shape in enumerate(shapes, start=1):
            shape_name = _shape_name(shape)
            tables = tuple(item for item in shape.iter() if _local_name(item.tag) == "tbl")
            if tables:
                for table_number, table in enumerate(tables, start=1):
                    _append_pptx_table_units(
                        units,
                        table,
                        slide_number=slide_number,
                        shape_number=shape_number,
                        table_number=table_number,
                        shape_name=shape_name,
                    )
                continue
            paragraphs = tuple(item for item in shape.iter() if _local_name(item.tag) == "p")
            texts = tuple(
                (ordinal, text)
                for ordinal, paragraph in enumerate(paragraphs, start=1)
                if (text := _paragraph_text(paragraph))
            )
            for ordinal, text in texts:
                suffix = f"/paragraph:{ordinal}" if len(texts) > 1 else ""
                units.append(
                    StructuralUnit(
                        unit_id=(
                            f"pptx-slide-{slide_number}-shape-{shape_number}-paragraph-{ordinal}"
                            if suffix
                            else f"pptx-slide-{slide_number}-shape-{shape_number}"
                        ),
                        kind="slide",
                        locator=f"pptx/slide:{slide_number}/shape:{shape_number}{suffix}",
                        text=text,
                        section_name=shape_name,
                    )
                )
        note_name = note_names.get(_numbered_part(slide_name))
        if note_name is not None:
            note_root = _xml_member_root(archive, note_name, budget)
            note_number = 0
            for paragraph in (item for item in note_root.iter() if _local_name(item.tag) == "p"):
                text = _paragraph_text(paragraph)
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
    shape_name: str | None,
) -> None:
    properties = next((item for item in table if _local_name(item.tag) == "tblPr"), None)
    first_row_header = properties is not None and _truthy_attribute(properties, "firstRow")
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
                        table_cell_role=(
                            "header" if row_number == 1 and first_row_header else "body"
                        ),
                        section_name=shape_name,
                    )
                )


def _extract_xlsx(
    archive: zipfile.ZipFile,
    sheet_names: list[str],
    *,
    sheet_labels: dict[int, str],
    shared_strings_name: str | None,
    budget: OoxmlParserBudget,
) -> tuple[StructuralUnit, ...]:
    shared_strings = (
        tuple(
            _element_text(item)
            for item in _xml_member_root(archive, shared_strings_name, budget)
            if _local_name(item.tag) == "si"
        )
        if shared_strings_name is not None
        else ()
    )
    units: list[StructuralUnit] = []
    seen: set[tuple[int, str]] = set()
    for name in sheet_names:
        sheet_number = _numbered_sheet(name)
        root = _xml_member_root(archive, name, budget)
        cells = tuple(item for item in root.iter() if _local_name(item.tag) == "c")
        if not cells:
            text = _element_text(root)
            if text:
                units.append(
                    StructuralUnit(
                        unit_id=f"sheet-{sheet_number}", kind="sheet", locator=name, text=text
                    )
                )
            continue
        for cell in cells:
            address = cell.attrib.get("r", "")
            identity = (sheet_number, address)
            if _CELL_ADDRESS.fullmatch(address) is None:
                raise ValueError("XLSX cell address is missing or malformed")
            if identity in seen:
                raise ValueError("XLSX cell addresses MUST be unique within a sheet")
            seen.add(identity)
            text = _xlsx_cell_text(cell, shared_strings)
            if text:
                units.append(
                    StructuralUnit(
                        unit_id=f"xlsx-sheet-{sheet_number}-cell-{address}",
                        kind="sheet",
                        locator=f"xlsx/sheet:{sheet_number}/cell:{address}",
                        text=text,
                        section_name=sheet_labels.get(sheet_number),
                    )
                )
    return tuple(units)


def _xlsx_cell_text(cell: ElementTree.Element, shared_strings: tuple[str, ...]) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return _element_text(cell)
    value = next((item.text or "" for item in cell if _local_name(item.tag) == "v"), "").strip()
    if cell_type != "s":
        return value
    try:
        return shared_strings[int(value)]
    except (ValueError, IndexError) as exc:
        raise ValueError("XLSX shared string reference is invalid") from exc


def _pptx_note_names(
    archive: zipfile.ZipFile,
    slide_names: list[str],
    names: set[str],
    budget: OoxmlParserBudget,
) -> dict[int, str]:
    fallback = {_numbered_part(name): name for name in names if _NOTES_NUMBER.search(name)}
    resolved: dict[int, str] = {}
    for slide_name in slide_names:
        slide_number = _numbered_part(slide_name)
        slide_path = PurePosixPath(slide_name)
        relation_name = str(slide_path.parent / "_rels" / f"{slide_path.name}.rels")
        if relation_name not in names:
            if slide_number in fallback:
                resolved[slide_number] = fallback[slide_number]
            continue
        root = _xml_member_root(archive, relation_name, budget)
        target = next(
            (
                item.attrib.get("Target", "")
                for item in root
                if _local_name(item.tag) == "Relationship"
                and item.attrib.get("Type", "").endswith("/notesSlide")
            ),
            "",
        )
        normalized = posixpath.normpath(posixpath.join(str(slide_path.parent), target))
        if normalized in names:
            resolved[slide_number] = normalized
    return resolved


def _xlsx_sheet_labels(
    archive: zipfile.ZipFile,
    names: set[str],
    budget: OoxmlParserBudget,
) -> dict[int, str]:
    workbook_name = "xl/workbook.xml"
    relations_name = "xl/_rels/workbook.xml.rels"
    if workbook_name not in names or relations_name not in names:
        return {}
    relations = {
        item.attrib.get("Id", ""): item.attrib.get("Target", "")
        for item in _xml_member_root(archive, relations_name, budget)
        if _local_name(item.tag) == "Relationship"
    }
    labels: dict[int, str] = {}
    for sheet in (
        item
        for item in _xml_member_root(archive, workbook_name, budget).iter()
        if _local_name(item.tag) == "sheet"
    ):
        relation_id = next(
            (value for key, value in sheet.attrib.items() if _local_name(key) == "id"), ""
        )
        target = relations.get(relation_id, "")
        match = _SHEET_NUMBER.search(target)
        name = sheet.attrib.get("name", "").strip()
        if match is not None and name:
            labels[int(match.group(1))] = name[:256]
    return labels


def _shape_name(shape: ElementTree.Element) -> str | None:
    value = next(
        (
            item.attrib.get("name", "").strip()
            for item in shape.iter()
            if _local_name(item.tag) == "cNvPr"
        ),
        "",
    )
    return value[:256] or None


class _DepthLimitedTreeBuilder(ElementTree.TreeBuilder):
    def __init__(self, *, max_depth: int, max_nodes: int) -> None:
        super().__init__()
        self._max_depth = max_depth
        self._max_nodes = max_nodes
        self._depth = 0
        self._nodes = 0

    def start(self, tag: str, attrs: dict[str, str]) -> ElementTree.Element:
        self._depth += 1
        self._nodes += 1
        if self._depth > self._max_depth:
            raise DocumentExtractionUnavailableError(ExtractionUnavailableReason.XML_DEPTH_BUDGET)
        if self._nodes > self._max_nodes:
            raise DocumentExtractionUnavailableError(ExtractionUnavailableReason.XML_NODE_BUDGET)
        return super().start(tag, attrs)

    def end(self, tag: str) -> ElementTree.Element:
        element = super().end(tag)
        self._depth -= 1
        return element


def _xml_member_root(
    archive: zipfile.ZipFile, name: str, budget: OoxmlParserBudget
) -> ElementTree.Element:
    info = archive.getinfo(name)
    if info.file_size > budget.max_xml_member_bytes:
        raise DocumentExtractionUnavailableError(ExtractionUnavailableReason.XML_MEMBER_BUDGET)
    with archive.open(info) as member:
        content = member.read(budget.max_xml_member_bytes + 1)
    if len(content) > budget.max_xml_member_bytes:
        raise DocumentExtractionUnavailableError(ExtractionUnavailableReason.XML_MEMBER_BUDGET)
    upper = content.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise DocumentExtractionUnavailableError(ExtractionUnavailableReason.UNSAFE_PACKAGE)
    parser = ElementTree.XMLParser(  # noqa: S314 - declarations rejected; depth bounded
        target=_DepthLimitedTreeBuilder(
            max_depth=budget.max_xml_depth,
            max_nodes=budget.max_xml_nodes,
        )
    )
    parser.feed(content)
    return parser.close()


def _element_text(element: ElementTree.Element) -> str:
    if _local_name(element.tag) == "p":
        return _paragraph_text(element)
    paragraphs = tuple(item for item in element.iter() if _local_name(item.tag) == "p")
    if paragraphs:
        return " ".join(text for item in paragraphs if (text := _paragraph_text(item)))
    return _paragraph_text(element)


def _paragraph_text(element: ElementTree.Element) -> str:
    return "".join(
        item.text or "" for item in element.iter() if _local_name(item.tag) in {"t", "v"}
    ).strip()


def _heading_level(paragraph: ElementTree.Element) -> int | None:
    style = next((item for item in paragraph.iter() if _local_name(item.tag) == "pStyle"), None)
    if style is None:
        return None
    value = next((raw for key, raw in style.attrib.items() if _local_name(key) == "val"), "")
    match = _HEADING_STYLE.fullmatch(value)
    return int(match.group(1)) if match is not None else None


def _heading_context(active: dict[int, int]) -> str:
    if not active:
        return ""
    return "/context:" + "/".join(
        f"heading:{level}:{ordinal}" for level, ordinal in sorted(active.items())
    )


def _heading_parent_locator(active: dict[int, int]) -> str:
    level = max(active)
    return f"docx/heading:{level}:{active[level]}"


def _docx_header_row(row: ElementTree.Element) -> bool:
    return any(_local_name(item.tag) == "tblHeader" for item in row.iter())


def _truthy_attribute(element: ElementTree.Element, name: str) -> bool:
    value = next((raw for key, raw in element.attrib.items() if _local_name(key) == name), "")
    return value.lower() in {"1", "true", "on"}


def _children_named(element: ElementTree.Element, name: str) -> tuple[ElementTree.Element, ...]:
    return tuple(child for child in element if _local_name(child.tag) == name)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _numbered_part(name: str) -> int:
    match = _SLIDE_NUMBER.search(name) or _NOTES_NUMBER.search(name)
    if match is None:
        raise ValueError("OOXML numbered part name is malformed")
    return int(match.group(1))


def _numbered_sheet(name: str) -> int:
    match = _SHEET_NUMBER.search(name)
    if match is None:
        raise ValueError("OOXML sheet name is malformed")
    return int(match.group(1))
