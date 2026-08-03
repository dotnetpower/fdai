"""Structured text extraction tests for document ontology input."""

from __future__ import annotations

from dataclasses import replace

import pytest

from fdai.shared.providers.local.document_limits import (
    DEFAULT_DOCUMENT_PARSER_POLICY,
    DocumentParserPolicy,
)
from fdai.shared.providers.local.document_text import extract_structured_text


def test_markdown_preserves_blocks_and_discards_markup_only_units() -> None:
    content = b"""---
title: ignored
---
# Recovery

If the primary fails, restore the latest verified snapshot
before accepting writes.

- Stop traffic.
- Restore state.

| Signal | Limit |
| --- | --- |
| lag | 250 ms |

{{< note >}}
Operator review is required.
{{< /note >}}

```shell
restore --verify
```
"""

    units = extract_structured_text(content, source_name="runbook.md")

    assert [unit.locator for unit in units] == [
        "markdown/heading:1:1/lines:4-4",
        "markdown/paragraph:1/lines:6-7",
        "markdown/list-item:1/lines:9-9",
        "markdown/list-item:2/lines:10-10",
        "markdown/table:1/row:1/cell:1/lines:12-12",
        "markdown/table:1/row:1/cell:2/lines:12-12",
        "markdown/table:1/row:2/cell:1/lines:14-14",
        "markdown/table:1/row:2/cell:2/lines:14-14",
        "markdown/paragraph:2/lines:17-17",
        "markdown/code:1/lines:20-22",
    ]
    assert units[1].text == (
        "If the primary fails, restore the latest verified snapshot before accepting writes."
    )
    assert all("{{" not in unit.text and "title: ignored" not in unit.text for unit in units)


def test_sgml_preserves_paragraph_title_table_and_code_ranges() -> None:
    content = b"""<chapter>
<title>Backup and Restore</title>
<para>The server must be stopped
before a physical restore.</para>
<table><row><entry>Mode</entry><entry>safe</entry></row></table>
<programlisting>restore --verify</programlisting>
</chapter>
"""

    units = extract_structured_text(content, source_name="operations.sgml")

    assert [unit.locator for unit in units] == [
        "sgml/title:1/lines:2-2",
        "sgml/para:1/lines:3-4",
        "sgml/entry:1/lines:5-5",
        "sgml/entry:2/lines:5-5",
        "sgml/programlisting:1/lines:6-6",
    ]
    assert units[1].text == "The server must be stopped before a physical restore."


def test_plain_text_keeps_original_line_locators() -> None:
    units = extract_structured_text(b"first\n\nthird\n", source_name="notes.txt")

    assert [unit.locator for unit in units] == ["line:1", "line:3"]


@pytest.mark.parametrize("max_input_bytes", [0, 1.5, True])
def test_document_parser_policy_rejects_invalid_integer_limits(
    max_input_bytes: object,
) -> None:
    with pytest.raises(ValueError, match="integer limits MUST be positive"):
        DocumentParserPolicy(max_input_bytes=max_input_bytes)  # type: ignore[arg-type]


@pytest.mark.parametrize("compression_ratio", [0.99, float("inf"), float("nan")])
def test_document_parser_policy_rejects_invalid_compression_ratio(
    compression_ratio: float,
) -> None:
    with pytest.raises(ValueError, match="compression ratio MUST be finite"):
        DocumentParserPolicy(max_ooxml_compression_ratio=compression_ratio)


def test_markdown_rejects_excessive_token_count_and_nesting() -> None:
    token_policy = replace(DEFAULT_DOCUMENT_PARSER_POLICY, max_markdown_tokens=2)
    with pytest.raises(ValueError, match="Markdown token count exceeds the parser budget"):
        extract_structured_text(
            b"# heading\n\nparagraph\n",
            source_name="runbook.md",
            policy=token_policy,
        )

    nesting_policy = replace(DEFAULT_DOCUMENT_PARSER_POLICY, max_markdown_nesting=2)
    with pytest.raises(ValueError, match="Markdown nesting exceeds the parser budget"):
        extract_structured_text(
            b"> > > deeply nested\n",
            source_name="runbook.md",
            policy=nesting_policy,
        )


def test_sgml_rejects_excessive_nesting_and_unclosed_blocks() -> None:
    nesting_policy = replace(DEFAULT_DOCUMENT_PARSER_POLICY, max_sgml_nesting=2)
    with pytest.raises(ValueError, match="SGML nesting exceeds the parser budget"):
        extract_structured_text(
            b"<para><para><para>deep</para></para></para>",
            source_name="manual.sgml",
            policy=nesting_policy,
        )
    with pytest.raises(ValueError, match="unclosed structural block"):
        extract_structured_text(
            b"<chapter><para>private source fragment",
            source_name="manual.sgml",
        )

    with pytest.raises(ValueError, match="SGML nesting exceeds the parser budget"):
        extract_structured_text(
            b"<div><div><div><para>deep</para></div></div></div>",
            source_name="manual.sgml",
            policy=nesting_policy,
        )
