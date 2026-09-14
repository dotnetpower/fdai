"""Bounded inert official-document normalization; never execute or follow content."""

from html.parser import HTMLParser


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.article_depth: int | None = None
        self.ignored = 0
        self.parts: list[str] = []
        self.has_article = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "hr", "img", "meta", "link", "input", "source", "wbr"}:
            if tag in {"br", "hr"} and self.article_depth is not None:
                self.parts.append("\n")
            return
        self.depth += 1
        if self.depth > 128:
            raise ValueError("source HTML nesting exceeds the parser limit")
        if tag in {"script", "style", "nav", "footer", "noscript", "iframe", "svg"}:
            self.ignored += 1
        if tag in {"article", "main"} and self.article_depth is None:
            self.article_depth = self.depth
            self.has_article = True
        if self.article_depth is None or self.ignored:
            return
        if tag in {"p", "div", "section", "ul", "ol", "table", "tr", "pre", "blockquote"}:
            self.parts.append("\n")
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in {"th", "td"}:
            self.parts.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"br", "hr", "img", "meta", "link", "input", "source", "wbr"}:
            return
        if self.article_depth is not None and not self.ignored:
            if tag in {"p", "div", "tr", "li", "pre", "h1", "h2", "h3", "h4", "h5", "h6"}:
                self.parts.append("\n")
        if tag in {"script", "style", "nav", "footer", "noscript", "iframe", "svg"}:
            self.ignored = max(0, self.ignored - 1)
        if self.article_depth == self.depth:
            self.article_depth = None
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data: str) -> None:
        if self.article_depth is not None and not self.ignored:
            self.parts.append(data)


def normalize_source(content: bytes, media_type: str, *, max_bytes: int) -> tuple[str, str]:
    """Decode exact UTF-8 and retain article headings/tables, rejecting login/error pages.

    HTML requires an explicit main/article region. No rendering engine, script,
    embedded URL fetch, attachment extraction, or model invocation occurs here.
    """
    if not content or len(content) > max_bytes:
        raise ValueError("source content exceeds the bounded input policy")
    original = content.decode("utf-8", errors="strict")
    if "\x00" in original:
        raise ValueError("source content contains binary data")
    media = media_type.partition(";")[0].strip().lower()
    if media == "text/html":
        parser = _ArticleParser()
        parser.feed(original)
        parser.close()
        if not parser.has_article:
            raise ValueError("source HTML has no explicit article region")
        normalized = "\n".join(line.strip() for line in "".join(parser.parts).splitlines()).strip()
    elif media in {"text/plain", "text/markdown"}:
        normalized = original.strip()
    else:
        raise ValueError("source media type is not an approved document format")
    if not normalized or len(normalized.encode()) > max_bytes:
        raise ValueError("normalized source is empty or exceeds the input policy")
    return original, normalized
