"""Explicit normalizer 2.1 structure support, without changing legacy extraction or authority."""

from __future__ import annotations

from collections import Counter
from textwrap import indent
from urllib.parse import unquote, urlsplit

from .article_tree import (
    NOTICE_TOKENS,
    OPAQUE,
    Element,
    elements,
    excluded,
    inspect_structure,
    is_notice,
    text_content,
)
from .structured_normalization import _Kind, _link_target, _Structure


def _summary(node: Element) -> Element | None:
    children = [child for child in node.children if isinstance(child, Element) or child.strip()]
    summaries = [
        child for child in children if isinstance(child, Element) and child.tag == "summary"
    ]
    if len(summaries) != 1 or children[0] is not summaries[0]:
        return None
    return summaries[0]


def _lines(value: str) -> list[Element | str]:
    result: list[Element | str] = []
    for index, line in enumerate(value.split("\n")):
        if index:
            result.append(Element("br"))
        result.append(line)
    return result


class ExtendedStructure(_Structure):
    """Preserve supported expanded structures; ambiguous identities and media still hold.

    Composite procedures remain atomic. A nested notice promotes the entire composite
    to required context, so no related excerpt can omit the captured restriction.
    """

    allow_header_only = True

    def __init__(self, scopes: tuple[Element, ...], issues: set[str], source_url: str) -> None:
        super().__init__(scopes, issues, source_url)
        self._tab_groups: dict[Element, Element] = {}
        nodes = [node for scope in scopes for node in elements(scope, controls=True)]
        self._summaries = {
            summary
            for node in nodes
            if node.tag == "details" and (summary := _summary(node)) is not None
        }
        for scope in scopes:
            for node in elements(scope):
                if not excluded(node):
                    self._conditions(node)
        identities = Counter(node.attrs["id"] for node in nodes if node.attrs.get("id"))
        duplicates = {identity for identity, count in identities.items() if count > 1}
        referenced: set[str] = set()
        for node in nodes:
            for attribute in ("aria-labelledby", "aria-describedby", "headers"):
                referenced.update(node.attrs.get(attribute, "").split())
            target = _link_target(source_url, node.attrs.get("href", ""))
            if target is not None and target.partition("#")[0] == source_url:
                referenced.add(unquote(urlsplit(target).fragment))
        if not duplicates.intersection(referenced):
            self.issues.discard("duplicate_html_id")
        for identity in duplicates:
            self.ids.pop(identity, None)  # A duplicate never selects first/last for resolution.
        for scope in scopes:
            self._bind_groups(scope, None)

    def _bind_groups(self, node: Element, group: Element | None) -> None:
        if node.tag in OPAQUE:
            return
        if "tabgroup" in node.tokens:
            group = node
        if group is not None:
            self._tab_groups[node] = group
        for child in node.children:
            if isinstance(child, Element):
                self._bind_groups(child, group)

    def text(self, node: Element) -> str:
        """Render supported composites through inert clones, preserving all legacy holds."""
        if node.attrs.get("role") == "tab":
            return self._label_text(node)
        return text_content(self._prepared(node, root=True), self.issues)

    def _label_text(self, node: Element) -> str:
        self._conditions(node)
        attrs = node.attrs.copy()
        attrs.pop("data-tab", None)
        attrs.pop("role", None)
        return text_content(
            self._prepared(Element("span", attrs, node.children), root=True), self.issues
        )

    def _conditions(self, node: Element) -> None:
        if any(key in node.attrs for key in ("data-monikers", "data-tab-condition")):
            self.issues.add("unsupported_condition")

    def inspect(self, node: Element) -> None:
        """Extend only supported tags, retaining dependency, malformed and media checks."""
        if excluded(node):
            super().inspect(node)
            return
        self._conditions(node)
        if (node.tag == "summary" and node not in self._summaries) or (
            node.tag == "details" and _summary(node) is None
        ):
            self.issues.add("unsupported_structure")
        tag = (
            "div"
            if node.tag == "details"
            else "span"
            if node.tag in {"nobr", "summary"}
            else node.tag
        )
        inspect_structure(Element(tag, node.attrs, node.children), self.issues)

    def _prepared(self, node: Element, *, root: bool = False) -> Element:
        self.inspect(node)
        if excluded(node) or node.tag in OPAQUE:
            return node
        if node.tag == "pre" and not root:
            body = text_content(node, self.issues)
            return Element("code", children=["\nCode block:\n" + indent(body, "    ") + "\n"])
        if node.tag == "table":
            return self._atomic_table(node)
        if node.tag == "details":
            summary = _summary(node)
            if summary is None:
                self.issues.add("unsupported_structure")
            else:
                label = self.text(summary).strip()
                if not label:
                    self.issues.add("empty_disclosure_label")
                disclosed = [child for child in node.children if child is not summary]
                node = Element("div", node.attrs.copy(), ["Disclosure: " + label, *disclosed])
        attrs = node.attrs.copy()
        tag = "span" if node.tag in {"nobr", "summary"} else node.tag
        prefix: list[Element | str] = []
        if is_notice(node):
            # Required-context ownership is retained on the ORIGINAL node/composite.
            # The clone only prevents the legacy renderer treating supported nesting as loss.
            tag = "div"
            attrs.pop("role", None)
            attrs["class"] = " ".join(
                token
                for token in attrs.get("class", "").split()
                if token.lower() not in NOTICE_TOKENS
            )
            for key in ("id", "data-bi-name"):
                if attrs.get(key, "").lower() in NOTICE_TOKENS:
                    attrs.pop(key)
            prefix = ["Notice: "]
        children = [
            self._prepared(child) if isinstance(child, Element) else child
            for child in node.children
        ]
        return Element(tag, attrs, prefix + children)

    def _atomic_table(self, node: Element) -> Element:
        # A complete simple table may remain INSIDE an atomic step/notice. It is never
        # split away from that context. The shared validator still rejects spans/nesting.
        local_issues: set[str] = set()
        table = ExtendedStructure((node,), local_issues, self.source_url)
        table.table(node)
        self.issues.update(local_issues)
        header = next((block.table_header for block in table.blocks if block.table_header), None)
        lines = (["Table columns: " + header] if header is not None else []) + table.parts
        return Element("div", children=[Element("p", children=_lines(line)) for line in lines])

    def visit(self, node: Element) -> None:
        """Keep disclosed bodies in a bounded labelled scope and inspect every attribute."""
        self.inspect(node)
        if excluded(node):
            super().visit(node)  # Retain media checks even when their active body is opaque.
        elif node.tag in {"details", "nobr"} and (is_notice(node) or node in self.note_targets):
            self.emit(node, "notice", self.text(node))
        elif node.tag == "details" and (summary := _summary(node)) is not None:
            label = self.text(summary).strip()
            if not label:
                self.issues.add("empty_disclosure_label")
            previous_headings, previous_tabs = self.headings.copy(), self.tabs
            self.tabs += ("Disclosure: " + label,)
            first = len(self.blocks)
            self.emit(summary, "paragraph", label)
            self.children(Element("div", children=[c for c in node.children if c is not summary]))
            if len(self.blocks) > first:
                self.owners[node] = self.blocks[first].block_id
            self.headings, self.tabs = previous_headings, previous_tabs
        elif node.tag == "nobr":
            self.children(node)
        else:
            super().visit(node)

    def panel(self, node: Element) -> None:
        """Use an exact source label from the same group, never an invented tab name."""
        if node.attrs.get("aria-label") or node.attrs.get("aria-labelledby"):
            super().panel(node)
            return
        group = self._tab_groups.get(node)
        identity, tab = node.attrs.get("id"), node.attrs.get("data-tab")
        labels = []
        if group is not None and identity and tab:
            labels = [
                candidate
                for candidate in elements(group, controls=True)
                if candidate.tag == "a"
                and self._tab_groups.get(candidate) is group
                and candidate.attrs.get("data-tab") == tab
                and candidate.attrs.get("href") == "#" + identity
            ]
        if len(labels) != 1:
            super().panel(node)
            return
        label = self._label_text(labels[0]).strip()
        first = len(self.blocks)
        super().panel(Element(node.tag, node.attrs | {"aria-label": label}, node.children))
        if len(self.blocks) > first:
            self.owners[node] = self.blocks[first].block_id

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
        """Retain nested restrictions with the entire atomic composite as required context."""
        if kind in {"paragraph", "list"} and any(is_notice(child) for child in elements(node)):
            kind = "notice"
        return super().emit(node, kind, text, table_id=table_id, header=header, context=context)
