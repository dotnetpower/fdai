"""Bounded, inert HTML article trees; neither parsing nor text rendering performs I/O."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from textwrap import indent

MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_DEPTH = 128
MAX_NODES = 50_000
MAX_ATTRIBUTES = 64
MAX_ATTRIBUTE_BYTES = 8192
VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
OPAQUE = frozenset(
    "head script style template noscript iframe svg object embed canvas audio video".split()
)
MEDIA = frozenset("img picture source iframe svg object embed canvas audio video math".split())
INLINE = frozenset(
    "a span strong em b i u s small kbd code samp var mark abbr dfn cite q sub sup time "
    "data bdi bdo del ins br wbr img".split()
)
FLOW = frozenset(
    "html body main article div section header aside p pre blockquote ul ol li table tr "
    "thead tbody tfoot th td caption h1 h2 h3 h4 h5 h6 hr".split()
)
CONTROLS = frozenset("nav footer form button input select textarea option dialog".split())
CONTROL_ROLES = frozenset("navigation contentinfo toolbar button tab tablist dialog banner".split())
CONTROL_TOKENS = frozenset(
    "toolbar code-header code-actions copy copy-button copy-code code-copy signin sign-in "
    "login login-prompt feedback feedback-section metadata contributors breadcrumbs "
    "breadcrumb page-actions unauthorized-message authorized-message authorization-message "
    "permission-content-unauthorized permission-content-authorized ask-learn download-pdf".split()
)
NOTICE_TOKENS = frozenset(
    "note tip warning caution important danger alert admonition footnote footnotes "
    "footnote-definition".split()
)


@dataclass(eq=False, slots=True)
class Element:
    """An inert element with ordered text/element children, never browser execution state."""

    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Element | str] = field(default_factory=list)

    @property
    def tokens(self) -> set[str]:
        """Return exact structural class, id, and telemetry-role tokens."""
        return set(self.attrs.get("class", "").lower().split()) | {
            self.attrs.get("id", "").lower(),
            self.attrs.get("data-bi-name", "").lower(),
        }


def excluded(node: Element) -> bool:
    """Remove known active/chrome roles, not arbitrary hidden documentation."""
    return (
        node.tag in OPAQUE | CONTROLS | {"link", "meta", "base"}
        or node.attrs.get("role", "").lower() in CONTROL_ROLES
        or bool(node.tokens & CONTROL_TOKENS)
        or (
            node.tag in INLINE
            and node.attrs.get("role") in {"presentation", "none"}
            and bool(node.tokens & {"icon", "logo", "badge"})
        )
    )


def elements(node: Element, *, controls: bool = False) -> Iterator[Element]:
    """Walk source order, pruning opaque bodies and optionally site controls."""
    yield node
    if node.tag in OPAQUE or (not controls and excluded(node)):
        return
    for child in node.children:
        if isinstance(child, Element):
            yield from elements(child, controls=controls)


class _TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("body")
        self.stack = [self.root]
        self.issues: set[str] = set()
        self.nodes = 0
        self.text_bytes = 0

    def _issue(self, reason: str) -> None:
        """Malformed inactive chrome cannot qualify or disqualify an unrelated article."""
        if any(
            node.tag in {"main", "article"} or "content" in node.attrs.get("class", "").split()
            for node in self.stack
        ):
            if not any(excluded(node) for node in self.stack[1:]):
                self.issues.add(reason)

    def _count(self) -> None:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise ValueError("source HTML exceeds the node limit")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._count()
        if len(self.stack) > MAX_DEPTH:
            raise ValueError("source HTML exceeds the nesting limit")
        if len(tag) > 128 or len(attrs) > MAX_ATTRIBUTES:
            raise ValueError("source HTML exceeds the attribute limit")
        values: dict[str, str] = {}
        attribute_bytes = 0
        for key, value in attrs:
            value = value or ""
            size = len(value.encode("utf-8"))
            if len(key) > 128 or size > MAX_ATTRIBUTE_BYTES:
                raise ValueError("source HTML exceeds the attribute byte limit")
            attribute_bytes += len(key.encode("utf-8")) + size
            if key in values:
                self._issue("malformed_structure")
            values[key] = value
        if attribute_bytes > 32 * 1024:
            raise ValueError("source HTML exceeds the aggregate attribute limit")
        node = Element(tag, values)
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self._issue("malformed_structure")
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        position = next(
            (index for index in range(len(self.stack) - 1, 0, -1) if self.stack[index].tag == tag),
            None,
        )
        if position is None or position != len(self.stack) - 1:
            self._issue("malformed_structure")
        if position is not None:
            del self.stack[position:]

    def handle_data(self, data: str) -> None:
        self._count()  # Text nodes, including whitespace, also consume the node budget.
        self.text_bytes += len(data.encode("utf-8"))
        if self.text_bytes > MAX_INPUT_BYTES:
            raise ValueError("source HTML exceeds the decoded text limit")
        self.stack[-1].children.append(data)

    def handle_comment(self, data: str) -> None:
        self._count()
        if data.lstrip().startswith("#include"):
            self.stack[-1].children.append(Element("include"))

    def handle_decl(self, decl: str) -> None:
        self._count()

    def unknown_decl(self, data: str) -> None:
        self._count()
        self.issues.add("unsupported_declaration")

    def handle_pi(self, data: str) -> None:
        self._count()
        self.issues.add("unsupported_declaration")


def _regions(node: Element, *, content: bool = False) -> list[Element]:
    if excluded(node):
        return []
    selected = (
        "content" in node.attrs.get("class", "").split()
        if content
        else node.tag in {"main", "article"}
    )
    if selected:
        return [node]
    return [
        region
        for child in node.children
        if isinstance(child, Element)
        for region in _regions(child, content=content)
    ]


def _auth_form(node: Element) -> bool:
    style = node.attrs.get("style", "").lower().replace(" ", "")
    if (
        "hidden" in node.attrs
        or "hidden" in node.tokens
        or node.attrs.get("aria-hidden", "").lower() == "true"
        or "display:none" in style
    ):
        return False
    if node.tag == "form" or (
        node.tag == "input" and node.attrs.get("type", "").lower() == "password"
    ):
        return True
    if excluded(node):
        return False
    return any(_auth_form(child) for child in node.children if isinstance(child, Element))


def parse_article(original: str) -> tuple[tuple[Element, ...], set[str]]:
    """Select explicit main/article or top-level content scopes; reject missing/login regions.

    Budget violations raise ValueError. Unsupported/malformed structure is retained
    with hold reasons, never silently repaired into an eligible generation.
    """
    if not original or len(original.encode("utf-8")) > MAX_INPUT_BYTES or "\x00" in original:
        raise ValueError("source HTML is empty, binary, or exceeds the input byte limit")
    parser = _TreeParser()
    try:
        parser.feed(original)
        parser.close()
    except AssertionError as exc:
        raise ValueError("source HTML contains an unsupported declaration") from exc
    if len(parser.stack) != 1:
        parser._issue("malformed_structure")
    scopes = _regions(parser.root)
    if len(scopes) > 1:
        parser.issues.add("ambiguous_article")
    scopes = scopes or _regions(parser.root, content=True)
    if not scopes:
        raise ValueError("source HTML has no explicit article region")
    for scope in scopes:
        headings = [node for node in elements(scope) if node.tag in {"h1", "h2", "h3"}]
        heading_text = (
            text_content(headings[0], set()).strip().casefold() if len(headings) == 1 else ""
        )
        login_title = heading_text in {
            "sign in",
            "log in",
            "login",
            "authentication required",
            "access denied",
            "login required",
            "sign in to continue",
            "please sign in",
        }
        if _auth_form(scope) or login_title:
            raise ValueError("source HTML is an authentication page, not an article")
    selected = [part for scope in scopes for part in (_regions(scope, content=True) or [scope])]
    return tuple(selected), parser.issues


def is_notice(node: Element) -> bool:
    """Recognize explicit admonitions and structural footnotes without inferring prose meaning."""
    first = next(
        (child for child in node.children if not isinstance(child, str) or child.strip()), None
    )
    return (
        node.tag == "blockquote"
        or bool(node.tokens & NOTICE_TOKENS)
        or node.attrs.get("role")
        in {
            "note",
            "alert",
            "doc-footnote",
            "doc-endnote",
            "doc-endnotes",
        }
        or (node.tag == "p" and isinstance(first, Element) and first.tag == "sup")
        or (
            node.tag == "p"
            and isinstance(first, str)
            and re.match(r"^\*+(?:\s|:)", first.lstrip()) is not None
        )
    )


def inspect_structure(node: Element, issues: set[str]) -> None:
    """Record unrepresentable dependencies without fetching or interpreting their content."""
    if excluded(node) and node.tag not in MEDIA:
        return
    presentation = node.attrs.get("role") in {"presentation", "none"}
    if node.tag in MEDIA and presentation:
        return
    if node.tag in MEDIA and not presentation:
        issues.add("unsupported_media")
    if node.tag not in INLINE | FLOW | VOID | OPAQUE | CONTROLS | {"colgroup"}:
        issues.add("unsupported_structure")
    if any(key in node.attrs for key in ("data-include", "data-include-src", "aria-describedby")):
        issues.add("unresolved_dependency")
    if "data-moniker" in node.attrs:
        issues.add("unsupported_condition")
    if node.tokens & {"mermaid", "diagram", "language-mermaid", "lang-mermaid"}:
        issues.add("unsupported_diagram")
    if node.tag in {"del", "ins", "s"}:
        issues.add("unsupported_revision")
    if node.tag in INLINE | {"p", "pre", "h1", "h2", "h3", "h4", "h5", "h6"} and any(
        isinstance(child, Element) and child.tag in FLOW - {"hr"} for child in node.children
    ):
        issues.add("malformed_structure")


def _number(value: str, default: int, issues: set[str]) -> int:
    if not re.fullmatch(r"-?[0-9]{1,8}", value):
        issues.add("unsupported_list")
        return default
    return int(value)


def _list_text(node: Element, issues: set[str]) -> str:
    items = [
        child
        for child in node.children
        if isinstance(child, Element) and child.tag == "li" and not excluded(child)
    ]
    if node.tag == "ol" and node.attrs.get("type", "1") != "1":
        issues.add("unsupported_list")
    step = -1 if "reversed" in node.attrs else 1
    number = _number(node.attrs.get("start", str(len(items) if step == -1 else 1)), 1, issues)
    lines = []
    for item in node.children:
        if isinstance(item, Element) and excluded(item):
            continue
        if isinstance(item, str) or item.tag != "li":
            extra = item.strip() if isinstance(item, str) else text_content(item, issues).strip()
            if extra:
                issues.add("unsupported_list")
                lines.append(extra)
            continue
        if "value" in item.attrs:
            number = _number(item.attrs["value"], number, issues)
        if is_notice(item) and not is_notice(node):
            issues.add("nested_notice")
        body = text_content(item, issues).strip()
        if not body:
            issues.add("unsupported_list")
        marker = f"{number}. " if node.tag == "ol" else "- "
        lines.append(marker + body)
        number += step
    if not items:
        issues.add("unsupported_list")
    return "\n".join(lines)


def text_content(node: Element, issues: set[str], *, preformatted: bool = False) -> str:
    """Render atomic content once, retaining inline text, explicit breaks, and list ordering.

    Callers select the root; control children are omitted. Code whitespace is
    preserved. A table inside an atomic composite is held instead of losing its relationship.
    """
    inspect_structure(node, issues)
    if node.attrs.get("role") == "tabpanel" or "data-tab" in node.attrs:
        issues.add("nested_tab")
    if node.tag in OPAQUE or node.tag in MEDIA:
        return ""
    if node.tag in {"br", "hr"}:
        return "\n"
    if node.tag == "wbr":
        return ""
    if node.tag in {"ul", "ol"}:
        return _list_text(node, issues)
    if node.tag == "table":
        issues.add("nested_table")
    if node.tag == "tr":
        return " | ".join(
            text_content(child, issues).strip()
            for child in node.children
            if isinstance(child, Element) and child.tag in {"td", "th"}
        )
    preformatted = preformatted or node.tag in {"pre", "code"}
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            if not preformatted and "[!INCLUDE" in child.upper():
                issues.add("unresolved_dependency")
            parts.append(child if preformatted else re.sub(r"\s+", " ", child))
            continue
        inspect_structure(child, issues)
        if excluded(child):
            parts.append(" ")
            continue
        if is_notice(child) and not is_notice(node):
            issues.add("nested_notice")
        if child.tag == "pre" and not preformatted:
            issues.add("nested_code")
        value = text_content(child, issues, preformatted=preformatted)
        if child.tag in {"ul", "ol"} and node.tag == "li":
            value = indent(value, "  ")
        if child.tag in FLOW and not preformatted:
            value = "\n" + value + "\n"
        parts.append(value)
    result = "".join(parts)
    return result if preformatted or node.tag not in FLOW else result.strip()
