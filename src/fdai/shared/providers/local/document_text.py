"""Bounded structural extraction for Markdown, SGML, and plain text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal

from markdown_it import MarkdownIt
from markdown_it.token import Token

from fdai.shared.contracts import StructuralUnit
from fdai.shared.providers.local.document_limits import (
    DEFAULT_DOCUMENT_PARSER_POLICY,
    DocumentParserPolicy,
)

_MARKDOWN_EXTENSIONS = frozenset({".md", ".markdown"})
_SGML_EXTENSIONS = frozenset({".sgml", ".html", ".htm"})
_SHORTCODE = re.compile(r"^\s*\{\{[%<].*[>%]\}\}\s*$")
_INLINE_SHORTCODE = re.compile(r"\{\{[%<].*?[>%]\}\}")


def extract_structured_text(
    content: bytes,
    *,
    source_name: str,
    policy: DocumentParserPolicy = DEFAULT_DOCUMENT_PARSER_POLICY,
) -> tuple[StructuralUnit, ...]:
    """Extract bounded source-aware units from one UTF-8 text document."""
    if len(content) > policy.max_input_bytes:
        raise ValueError("text input bytes exceed the parser budget")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("text content is not valid UTF-8") from exc
    suffix = Path(source_name).suffix.lower()
    if suffix in _MARKDOWN_EXTENSIONS:
        units = _extract_markdown(text, policy=policy)
    elif suffix in _SGML_EXTENSIONS:
        units = _extract_sgml(text, policy=policy)
    else:
        units = _extract_lines(text)
    _validate_budget(units, policy=policy)
    return units


def _extract_lines(text: str) -> tuple[StructuralUnit, ...]:
    return tuple(
        StructuralUnit(
            unit_id=f"line-{line_number}",
            kind="text",
            locator=f"line:{line_number}",
            text=line,
        )
        for line_number, line in enumerate(text.splitlines(), start=1)
        if line
    )


def _extract_markdown(
    text: str,
    *,
    policy: DocumentParserPolicy,
) -> tuple[StructuralUnit, ...]:
    parser = MarkdownIt("commonmark", options_update={"html": False, "linkify": False})
    parser.enable("table")
    tokens = parser.parse(text)
    if len(tokens) > policy.max_markdown_tokens:
        raise ValueError("Markdown token count exceeds the parser budget")
    if max((token.level for token in tokens), default=0) > policy.max_markdown_nesting:
        raise ValueError("Markdown nesting exceeds the parser budget")
    source_lines = text.splitlines()
    frontmatter_end = _frontmatter_end(text)
    units: list[StructuralUnit] = []
    heading_counts: dict[int, int] = {}
    paragraph_number = 0
    list_item_number = 0
    code_number = 0
    table_number = 0
    table_row = 0
    table_cell = 0
    active_list_item: int | None = None
    active_table = False
    active_heading: tuple[int, int] | None = None

    for index, token in enumerate(tokens):
        if token.map is not None and token.map[0] < frontmatter_end:
            continue
        if token.type == "list_item_open":
            list_item_number += 1
            active_list_item = list_item_number
        elif token.type == "list_item_close":
            active_list_item = None
        elif token.type == "heading_open":
            level = int(token.tag[1:])
            heading_counts[level] = heading_counts.get(level, 0) + 1
            active_heading = (level, heading_counts[level])
        elif token.type == "heading_close":
            active_heading = None
        elif token.type == "table_open":
            table_number += 1
            table_row = 0
            active_table = True
        elif token.type == "table_close":
            active_table = False
        elif token.type == "tr_open" and active_table:
            table_row += 1
            table_cell = 0
        elif token.type in {"th_open", "td_open"} and active_table:
            table_cell += 1
        elif token.type in {"fence", "code_block"}:
            code_number += 1
            _append_unit(
                units,
                token,
                unit_id=f"markdown-code-{code_number}",
                kind="text",
                locator=f"markdown/code:{code_number}",
                text=token.content,
                source_lines=source_lines,
            )
        elif token.type == "inline":
            clean = _clean_markdown_text(token.content)
            if not clean:
                continue
            if active_table:
                _append_unit(
                    units,
                    token,
                    unit_id=f"markdown-table-{table_number}-r{table_row}-c{table_cell}",
                    kind="table",
                    locator=(f"markdown/table:{table_number}/row:{table_row}/cell:{table_cell}"),
                    text=clean,
                    source_lines=source_lines,
                )
            elif active_heading is not None:
                level, ordinal = active_heading
                _append_unit(
                    units,
                    token,
                    unit_id=f"markdown-heading-{level}-{ordinal}",
                    kind="paragraph",
                    locator=f"markdown/heading:{level}:{ordinal}",
                    text=clean,
                    source_lines=source_lines,
                )
            else:
                if active_list_item is not None:
                    locator = f"markdown/list-item:{active_list_item}"
                    unit_id = f"markdown-list-item-{active_list_item}"
                else:
                    paragraph_number += 1
                    locator = f"markdown/paragraph:{paragraph_number}"
                    unit_id = f"markdown-paragraph-{paragraph_number}"
                _append_unit(
                    units,
                    token,
                    unit_id=unit_id,
                    kind="paragraph",
                    locator=locator,
                    text=clean,
                    source_lines=source_lines,
                )
        elif token.type == "html_block":
            continue
        elif index >= len(tokens):
            raise AssertionError("unreachable token index")
    return tuple(units)


def _append_unit(
    units: list[StructuralUnit],
    token: Token,
    *,
    unit_id: str,
    kind: Literal["text", "paragraph", "table"],
    locator: str,
    text: str,
    source_lines: list[str],
) -> None:
    normalized = " ".join(text.split())
    if not normalized or _SHORTCODE.fullmatch(normalized):
        return
    start, end = token.map or (0, 0)
    content_lines = [
        index
        for index in range(start, min(end, len(source_lines)))
        if source_lines[index].strip() and not _SHORTCODE.fullmatch(source_lines[index])
    ]
    if content_lines:
        start, end = content_lines[0], content_lines[-1] + 1
    source_locator = f"{locator}/lines:{start + 1}-{max(start + 1, end)}"
    source_unit_id = f"{unit_id}-lines-{start + 1}-{max(start + 1, end)}"
    units.append(
        StructuralUnit(
            unit_id=source_unit_id,
            kind=kind,
            locator=source_locator,
            text=normalized,
        )
    )


def _clean_markdown_text(text: str) -> str:
    without_shortcodes = _INLINE_SHORTCODE.sub(" ", text)
    return " ".join(without_shortcodes.split())


def _frontmatter_end(text: str) -> int:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return 0
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return index + 1
    return 0


@dataclass(slots=True)
class _SgmlCapture:
    tag: str
    ordinal: int
    start_line: int
    parts: list[str] = field(default_factory=list)


class _SgmlParser(HTMLParser):
    _BLOCK_TAGS = frozenset(
        {"title", "para", "listitem", "entry", "programlisting", "screen", "synopsis"}
    )

    def __init__(self, *, max_nesting: int) -> None:
        super().__init__(convert_charrefs=True)
        self.units: list[StructuralUnit] = []
        self._captures: list[_SgmlCapture] = []
        self._counts: dict[str, int] = {}
        self._max_nesting = max_nesting

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag not in self._BLOCK_TAGS:
            return
        if len(self._captures) >= self._max_nesting:
            raise ValueError("SGML nesting exceeds the parser budget")
        ordinal = self._counts.get(tag, 0) + 1
        self._counts[tag] = ordinal
        self._captures.append(_SgmlCapture(tag, ordinal, self.getpos()[0]))

    def handle_endtag(self, tag: str) -> None:
        if not self._captures or self._captures[-1].tag != tag:
            return
        capture = self._captures.pop()
        text = " ".join("".join(capture.parts).split())
        if not text:
            return
        end_line = self.getpos()[0]
        kind: Literal["text", "paragraph", "table"] = "table" if tag == "entry" else "paragraph"
        if tag in {"programlisting", "screen", "synopsis"}:
            kind = "text"
        self.units.append(
            StructuralUnit(
                unit_id=f"sgml-{tag}-{capture.ordinal}",
                kind=kind,
                locator=f"sgml/{tag}:{capture.ordinal}/lines:{capture.start_line}-{end_line}",
                text=text,
            )
        )

    def handle_data(self, data: str) -> None:
        if self._captures:
            self._captures[-1].parts.append(data)


def _extract_sgml(
    text: str,
    *,
    policy: DocumentParserPolicy,
) -> tuple[StructuralUnit, ...]:
    parser = _SgmlParser(max_nesting=policy.max_sgml_nesting)
    parser.feed(text)
    parser.close()
    if parser._captures:
        raise ValueError("SGML source contains an unclosed structural block")
    return tuple(parser.units)


def _validate_budget(
    units: tuple[StructuralUnit, ...],
    *,
    policy: DocumentParserPolicy,
) -> None:
    if len(units) > policy.max_units:
        raise ValueError("text structural unit count exceeds the parser budget")
    if sum(len(unit.text) for unit in units) > policy.max_text_characters:
        raise ValueError("text extracted characters exceed the parser budget")


__all__ = ["extract_structured_text"]
