"""Reprocess stored HTML into original-free structure without renewing source evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urljoin, urlsplit

from fdai_service_contracts.cloud_knowledge import CloudSourceEvidence, content_digest
from fdai_service_contracts.cloud_knowledge_release import CloudKnowledgeDocument
from fdai_service_contracts.cloud_knowledge_structure import (
    MAX_BLOCKS,
    CloudArticleBlock,
    CloudArticleLink,
    CloudStructuredDocument,
)

from .article_tree import (
    INLINE,
    MAX_INPUT_BYTES,
    Element,
    elements,
    excluded,
    inspect_structure,
    is_notice,
    parse_article,
    text_content,
)

_Kind = Literal["heading", "paragraph", "list", "code", "table_row", "notice"]
_HEADINGS = frozenset("h1 h2 h3 h4 h5 h6".split())


def _link_target(base: str, href: str) -> str | None:
    # Check before urljoin/urlsplit, which otherwise strip some control characters.
    if (
        not href
        or "\\" in href
        or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in href)
    ):
        return None
    try:
        target = urljoin(base, href)
        parsed = urlsplit(target)
        if (
            len(target) > 2048
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 80, 443}
        ):
            return None
    except ValueError:
        return None  # Invalid URL syntax is held by the caller, never retried or fetched.
    return target


class _Structure:
    def __init__(self, scopes: tuple[Element, ...], issues: set[str], source_url: str) -> None:
        self.issues = issues
        self.source_url = source_url
        self.parts: list[str] = []
        self.blocks: list[CloudArticleBlock] = []
        self.owners: dict[Element, str] = {}
        self.ids: dict[str, Element] = {}
        self.note_links: set[Element] = set()
        self.note_targets: set[Element] = set()
        self.required: list[str] = []
        self.headings: list[tuple[int, str]] = []
        self.tabs: tuple[str, ...] = ()
        self.cursor = 0
        self.tables = 0
        self.output_bytes = 0
        for scope in scopes:
            for node in elements(scope, controls=True):
                identity = node.attrs.get("id")
                if identity:
                    if identity in self.ids:
                        self.issues.add("duplicate_html_id")
                    self.ids[identity] = node
            for node in elements(scope):
                if node.attrs.get("role") == "doc-noteref" or "footnote-ref" in node.tokens:
                    self.note_links.add(node)
                if node.tag == "sup":
                    self.note_links.update(child for child in elements(node) if child.tag == "a")
        for anchor in self.note_links:
            target = _link_target(source_url, anchor.attrs.get("href", ""))
            if target is not None and target.partition("#")[0] == source_url:
                destination = self.ids.get(urlsplit(target).fragment)
                if destination is not None:
                    self.note_targets.add(destination)

    def emit(
        self,
        node: Element,
        kind: _Kind,
        text: str,
        *,
        table_id: str | None = None,
        header: str | None = None,
        context: tuple[str, ...] = (),
    ) -> str | None:
        if not text.strip():
            return None
        path = tuple(label for _, label in self.headings) + self.tabs
        if len(path) > 6 or any(len(label) > 256 for label in path):
            raise ValueError("article heading path exceeds the metadata limit")
        if kind == "notice" and path:
            # Required-context rendering carries the body, not its heading metadata.
            text = "Section: " + " / ".join(path) + "\n" + text
        if len(self.blocks) >= MAX_BLOCKS:
            raise ValueError("article exceeds the structural unit limit")
        self.output_bytes += len(text.encode("utf-8")) + (2 if self.blocks else 0)
        if self.output_bytes > MAX_INPUT_BYTES:
            raise ValueError("normalized article exceeds the output byte limit")
        block_id = f"block:{len(self.blocks) + 1}"
        self.blocks.append(
            CloudArticleBlock(
                block_id=block_id,
                kind=kind,
                start=self.cursor,
                end=self.cursor + len(text),
                heading_path=path,
                table_id=table_id,
                table_header=header,
                context_ids=context,
            )
        )
        self.parts.append(text)
        self.cursor += len(text) + 2
        for child in elements(node):
            self.owners[child] = block_id
        if kind == "notice":
            self.required.append(block_id)
        return block_id

    def panel(self, node: Element) -> None:
        labels = node.attrs.get("aria-labelledby", "").split()
        label = node.attrs.get("aria-label", "").strip()
        if len(labels) > 64:
            raise ValueError("article tab exceeds the label reference limit")
        if not label and labels and all(identity in self.ids for identity in labels):
            for identity in labels:
                part = text_content(self.ids[identity], self.issues).strip()
                if len(label) + len(part) + 1 > 251:
                    raise ValueError("article tab exceeds the label limit")
                label = (label + " " + part).strip()
        if not label:
            self.issues.add("unlabelled_tab")
            label = node.attrs.get("data-tab", "unresolved")
        previous_headings, previous_tabs = self.headings.copy(), self.tabs
        self.tabs += (f"Tab: {label}",)
        self.children(node)
        self.headings, self.tabs = previous_headings, previous_tabs

    def visit(self, node: Element) -> None:
        inspect_structure(node, self.issues)
        if excluded(node):
            return
        if node.attrs.get("role") == "tabpanel" or "data-tab" in node.attrs:
            self.panel(node)
        elif node.tag in _HEADINGS:
            label = text_content(node, self.issues).strip()
            if not label:
                self.issues.add("empty_heading")
                return
            level = int(node.tag[1])
            self.headings = [(depth, title) for depth, title in self.headings if depth < level]
            self.headings.append((level, label))
            self.emit(node, "heading", "#" * level + " " + label)
        elif is_notice(node) or node in self.note_targets:
            self.emit(node, "notice", text_content(node, self.issues))
        elif node.tag == "table":
            self.table(node)
        elif node.tag in {"p", "pre", "ul", "ol"}:
            kind: _Kind = (
                "code" if node.tag == "pre" else "list" if node.tag in {"ul", "ol"} else "paragraph"
            )
            self.emit(node, kind, text_content(node, self.issues))
        elif node.tag not in {"img", "source", "hr", "wbr"}:
            if node.tag in {"li", "tr", "td", "th", "thead", "tbody", "tfoot"}:
                self.issues.add("orphan_structure")
            self.children(node)

    def children(self, node: Element) -> None:
        pending: list[Element | str] = []
        first_block = len(self.blocks)

        def flush() -> None:
            if pending:
                paragraph = Element("p", children=pending.copy())
                kind: _Kind = "notice" if is_notice(paragraph) else "paragraph"
                self.emit(paragraph, kind, text_content(paragraph, self.issues))
                pending.clear()

        for child in node.children:
            if isinstance(child, str) or (
                child.tag in INLINE
                and not is_notice(child)
                and child not in self.note_targets
                and child.attrs.get("role") != "tabpanel"
                and "data-tab" not in child.attrs
            ):
                pending.append(child)
            else:
                flush()
                self.visit(child)
        flush()
        if len(self.blocks) > first_block:
            self.owners[node] = self.blocks[first_block].block_id

    def table(self, node: Element) -> None:
        all_nodes = list(elements(node))
        rows = [child for child in all_nodes if child.tag == "tr"]
        cells = [
            [
                child
                for child in row.children
                if isinstance(child, Element) and child.tag in {"th", "td"}
            ]
            for row in rows
        ]
        headers: list[list[Element]] = []
        for row_cells in cells:
            if row_cells and all(
                cell.tag == "th" and cell.attrs.get("scope") not in {"row", "rowgroup"}
                for cell in row_cells
            ):
                headers.append(row_cells)
            else:
                break
        invalid = (
            not headers
            or len(headers) == len(rows)
            or any(child.tag == "table" and child is not node for child in all_nodes)
            or any(
                "rowspan" in child.attrs or "colspan" in child.attrs or "headers" in child.attrs
                for child in all_nodes
            )
            or any(child.tag == "tfoot" for child in all_nodes)
            or any(child.attrs.get("scope") in {"rowgroup", "colgroup"} for child in all_nodes)
            or any(excluded(cell) for row_cells in cells for cell in row_cells)
            or any(is_notice(child) and child.tag != "caption" for child in all_nodes)
        )
        if headers:
            invalid = invalid or any(len(row_cells) != len(headers[0]) for row_cells in cells)
            invalid = invalid or any(
                not text_content(cell, self.issues).strip()
                for row_cells in headers
                for cell in row_cells
            )
        permitted_children: dict[str, set[str]] = {
            "table": {"caption", "thead", "tbody", "tfoot", "tr", "colgroup", "col"},
            "thead": {"tr"},
            "tbody": {"tr"},
            "tfoot": {"tr"},
            "tr": {"td", "th"},
            "colgroup": {"col"},
            "col": set(),
        }
        for part in all_nodes:
            inspect_structure(part, self.issues)
            if part.tag in permitted_children:
                permitted = permitted_children[part.tag]
                if any(
                    (isinstance(child, str) and child.strip())
                    or (
                        isinstance(child, Element)
                        and child.tag not in permitted
                        and not excluded(child)
                    )
                    for child in part.children
                ):
                    invalid = True
            if part.tag == "thead" and any(
                child.tag == "tr" and child not in rows[: len(headers)] for child in elements(part)
            ):
                invalid = True
        if invalid:
            self.issues.add("unsupported_table")
            retained = text_content(Element("div", children=node.children), self.issues)
            self.emit(node, "paragraph", retained)
            return
        header = " | ".join(
            " / ".join(text_content(row[index], self.issues).strip() for row in headers)
            for index in range(len(headers[0]))
        )
        if len(header) > 4096 or len(headers) > 64:
            raise ValueError("article table exceeds the complete header limit")
        self.tables += 1
        table_id = f"table:{self.tables}"
        path = tuple(label for _, label in self.headings) + self.tabs
        context = [
            block.block_id
            for block in self.blocks
            if block.kind in {"paragraph", "list"}
            and path[: len(block.heading_path)] == block.heading_path
        ]
        if len(context) + len(headers) > 64:
            raise ValueError("article table exceeds the required context limit")
        for child in node.children:
            if isinstance(child, Element) and child.tag == "caption":
                self.emit(child, "notice", text_content(child, self.issues))
        for index, (row, row_cells) in enumerate(zip(rows, cells, strict=True)):
            if not any(text_content(cell, self.issues).strip() for cell in row_cells):
                self.issues.add("empty_table_row")
            body = " | ".join(text_content(cell, self.issues).strip() for cell in row_cells)
            block_id = self.emit(
                row,
                "table_row",
                body,
                table_id=table_id,
                header=header,
                context=tuple(context) if index >= len(headers) else (),
            )
            if index < len(headers) and block_id is not None:
                context.append(block_id)

    def links(self) -> tuple[CloudArticleLink, ...]:
        links: list[CloudArticleLink] = []
        seen: set[tuple[str, str, str]] = set()
        notice_ids = {block.block_id for block in self.blocks if block.kind == "notice"}
        for node, block_id in self.owners.items():
            if node.tag != "a" or "href" not in node.attrs or excluded(node):
                continue
            target = _link_target(self.source_url, node.attrs["href"])
            label = text_content(node, self.issues).strip()
            if target is None or len(label) > 1024:
                self.issues.add("unsupported_link")
                continue
            identity = (block_id, label, target)
            if identity not in seen:
                if len(links) >= 16384:
                    raise ValueError("article exceeds the link limit")
                links.append(CloudArticleLink(block_id=block_id, label=label, target=target))
                seen.add(identity)
            if node in self.note_links:
                reference = urlsplit(target)
                destination = self.ids.get(reference.fragment)
                owner = self.owners.get(destination) if destination is not None else None
                if target.partition("#")[0] != self.source_url or owner is None:
                    self.issues.add("unresolved_reference")
                elif owner not in notice_ids:
                    self.issues.add("unsupported_reference_context")
                else:
                    self.required.append(owner)
        return tuple(links)


def reprocess_document(
    snapshot: CloudKnowledgeDocument, *, now: datetime
) -> CloudStructuredDocument:
    """Derive an original-free article candidate from the retained HTML only, with no I/O.

    Source clocks, raw digest, rights and applicability remain unchanged; only the
    normalized digest changes. Invalid input/metadata or exceeded budgets raise
    ValueError. Unsupported structures return explicit unresolved dependencies;
    oversized atomic blocks remain intact for the installed chunker's whole-document hold.
    """
    if len(snapshot.original_text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("source HTML exceeds the input byte limit")
    snapshot = CloudKnowledgeDocument.model_validate(snapshot.model_dump(warnings="error"))
    if now.utcoffset() is None or now < snapshot.evidence.check.checked_at:
        raise ValueError("article derivation requires an aware clock after source observations")
    scopes, issues = parse_article(snapshot.original_text)
    if not any(
        node.tag in _HEADINGS | {"p", "pre", "ul", "ol", "table", "blockquote"} or is_notice(node)
        for scope in scopes
        for node in elements(scope)
        if not excluded(node)
    ):
        raise ValueError("source article contains no structured document text")
    structure = _Structure(scopes, issues, snapshot.evidence.source_url)
    for scope in scopes:
        structure.visit(scope)
    if not any(block.kind != "heading" for block in structure.blocks):
        raise ValueError("source article contains no document text")
    links = structure.links()
    text = "\n\n".join(structure.parts)
    values = snapshot.evidence.model_dump()
    values["normalized_sha256"] = content_digest(text.encode("utf-8"))
    required = tuple(dict.fromkeys(structure.required))
    if len(required) > 64:
        raise ValueError("article exceeds the required context limit")
    return CloudStructuredDocument(
        evidence=CloudSourceEvidence.model_validate(values),
        title=snapshot.title,
        text=text,
        derived_at=now,
        parent_normalized_sha256=snapshot.evidence.normalized_sha256,
        blocks=tuple(structure.blocks),
        links=links,
        required_context_ids=required,
        unresolved_dependencies=tuple(sorted(structure.issues)),
    )
