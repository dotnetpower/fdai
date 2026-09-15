"""Synthetic, original-free structure expectations; no publisher content or live fixtures."""

import socket
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import NoReturn

import pytest
from fdai_ingestion_api_service.cloud_knowledge import article_tree
from fdai_ingestion_api_service.cloud_knowledge.structured_normalization import reprocess_document
from fdai_service_contracts.cloud_knowledge import (
    Applicability,
    CloudSourceEvidence,
    RefreshPolicy,
    SourceCheckReceipt,
    content_digest,
)
from fdai_service_contracts.cloud_knowledge_release import CloudKnowledgeDocument
from fdai_service_contracts.cloud_knowledge_structure import (
    CloudStructuredDocument,
    structured_excerpts,
)

COLLECTED = datetime(2026, 9, 1, tzinfo=UTC)
CHECKED = COLLECTED + timedelta(days=7)
DERIVED = CHECKED + timedelta(days=2)
SOURCE_URL = "https://example.com/docs/widget"


def _snapshot(html: str) -> CloudKnowledgeDocument:
    source_hash = content_digest(html.encode("utf-8"))
    return CloudKnowledgeDocument(
        evidence=CloudSourceEvidence(
            source_id="synthetic-widget",
            source_url=SOURCE_URL,
            source_sha256=source_hash,
            normalized_sha256=content_digest(b"Legacy normalized body"),
            collected_at=COLLECTED,
            source_updated_at=COLLECTED - timedelta(days=1),
            check=SourceCheckReceipt(
                source_id="synthetic-widget",
                source_url=SOURCE_URL,
                checked_at=CHECKED,
                outcome="unchanged",
                content_sha256=source_hash,
                equivalence="strong_etag",
                etag='"synthetic-revision"',
                collector_id="synthetic-collector",
            ),
            applicability=Applicability(
                resource_type="Microsoft.Example/widgets",
                service_generation="classic",
                skus=("Example",),
            ),
            policy=RefreshPolicy(),
            license_ref="synthetic-test-data",
        ),
        title="Synthetic widget guide",
        original_text=html,
        text="Legacy normalized body",
    )


def _document(body: str) -> CloudStructuredDocument:
    return reprocess_document(_snapshot(f"<main><h1>Widget guide</h1>{body}</main>"), now=DERIVED)


def _bodies(document: CloudStructuredDocument, kind: str) -> list[str]:
    return [
        document.text[block.start : block.end] for block in document.blocks if block.kind == kind
    ]


def test_article_removes_site_controls_without_changing_source_lineage() -> None:
    html = (
        "<html><body><nav>Navigation</nav><main><h1>Widget guide</h1>"
        '<div class="metadata">Article metadata</div><p>Actual article body.</p>'
        "<template><main><h1>Sign in</h1><form>Secret prompt</form></main></template>"
        '<div class="unauthorized-message" hidden><p>Hidden login control</p></div>'
        '<div role="toolbar"><button>Copy sample</button></div>'
        '<div class="feedback-section"><form>Feedback form</form></div>'
        '<script>fetch("https://example.com/unwanted")</script><style>.x {display:none}</style>'
        '<svg role="presentation"><text>Logo text</text></svg>'
        '<span class="icon" role="presentation">Decorative icon</span>'
        "<footer>Footer text</footer></main></body></html>"
    )
    snapshot = _snapshot(html)
    before = snapshot.model_dump()
    document = reprocess_document(snapshot, now=DERIVED)
    assert document.text == "# Widget guide\n\nActual article body."
    assert document.unresolved_dependencies == ()
    assert snapshot.model_dump() == before
    assert document.evidence.model_dump(exclude={"normalized_sha256"}) == (
        snapshot.evidence.model_dump(exclude={"normalized_sha256"})
    )
    assert document.parent_normalized_sha256 == snapshot.evidence.normalized_sha256
    assert document.evidence.normalized_sha256 == content_digest(document.text.encode("utf-8"))
    assert document.normalizer_version == "2.0.0" and document.derived_at == DERIVED
    assert "original_text" not in document.model_dump()
    assert reprocess_document(snapshot, now=DERIVED) == document
    later = reprocess_document(snapshot, now=DERIVED + timedelta(days=1))
    assert later.processing_digest == document.processing_digest


@pytest.mark.parametrize("wrap", ["<article>{}</article>", '<div class="content">{}</div>'])
def test_explicit_article_and_content_scopes(wrap: str) -> None:
    html = "<nav>Outside</nav>" + wrap.format("<h1>Guide</h1><p>Retained.</p>")
    document = reprocess_document(_snapshot(html), now=DERIVED)
    assert document.text == "# Guide\n\nRetained."
    assert not document.unresolved_dependencies


@pytest.mark.parametrize("tag", ["p", "div", "h1"])
def test_content_selection_cannot_silently_drop_outside_caveat(tag: str) -> None:
    html = (
        f"<main><{tag}>Only the reviewed service generation is supported.</{tag}>"
        '<div class="content"><h1>Guide</h1><p>Configure the endpoint.</p></div></main>'
    )
    document = reprocess_document(_snapshot(html), now=DERIVED)
    assert "article_scope_omission" in document.unresolved_dependencies
    with pytest.raises(ValueError, match="unresolved"):
        structured_excerpts(document)


def test_table_rows_keep_preceding_section_applicability() -> None:
    doc = _document(
        "<h2>Ports</h2><p>Applies only to the dedicated generation.</p>"
        "<table><tr><th>Port</th><th>Protocol</th></tr>"
        "<tr><td>443</td><td>TCP</td></tr></table>"
    )
    rows = [item for item in structured_excerpts(doc) if "443 | TCP" in item.text]
    assert len(rows) == 1
    assert "Applies only to the dedicated generation." in rows[0].text


def test_publisher_page_controls_are_not_missing_article_evidence() -> None:
    html = (
        '<main><a data-page-action-item="overflow-all">Page action</a>'
        '<div data-bi-name="permission-content-unauthorized-private" hidden>'
        "<p>Authentication template.</p></div>"
        '<div class="content"><h1>Guide</h1><p>Actual guidance.</p></div>'
        '<section id="site-user-feedback-footer"><h2>Feedback</h2></section>'
        '<div id="ms--additional-resources-mobile"><h2>Site recommendations</h2></div></main>'
    )
    doc = reprocess_document(_snapshot(html), now=DERIVED)
    assert not doc.unresolved_dependencies
    assert "Authentication template" not in doc.text
    assert "Actual guidance" in doc.text


def test_top_level_content_scopes_keep_title_and_body_without_duplication() -> None:
    html = (
        '<div class="content"><h1>Guide</h1></div><nav>Outside</nav>'
        '<div class="content"><h2>Steps</h2><div class="content"><p>Once.</p></div></div>'
    )
    document = reprocess_document(_snapshot(html), now=DERIVED)
    assert document.text == "# Guide\n\n## Steps\n\nOnce."
    assert document.blocks[-1].heading_path == ("Guide", "Steps")


def test_table_headers_breaks_links_and_cross_section_notices_travel_together() -> None:
    document = _document(
        "<h2>Values</h2><table><thead><tr><th>SKU</th><th>Protocol and port</th></tr></thead>"
        '<tbody><tr><td><a href="../plans#example">Example plan</a>*</td>'
        "<td>TCP<br>443</td></tr></tbody></table><h2>Restrictions</h2>"
        '<div class="NOTE"><p>Do not apply these values to another generation.</p></div>'
        "<p><sup>*</sup> The marked plan requires a separate endpoint.</p>"
        '<aside role="note"><p>Region support must be checked independently.</p></aside>'
    )
    assert not document.unresolved_dependencies
    rows = [block for block in document.blocks if block.kind == "table_row"]
    assert len(rows) == 2 and rows[0].table_id == rows[1].table_id
    assert all(block.table_header == "SKU | Protocol and port" for block in rows)
    assert rows[1].heading_path == ("Widget guide", "Values")
    assert rows[1].context_ids == (rows[0].block_id,)
    assert document.text[rows[1].start : rows[1].end] == "Example plan* | TCP\n443"
    notices = tuple(block.block_id for block in document.blocks if block.kind == "notice")
    assert len(notices) == 3 and document.required_context_ids == notices
    assert len(document.links) == 1
    link = document.links[0]
    assert (link.block_id, link.label, link.target) == (
        rows[1].block_id,
        "Example plan",
        "https://example.com/plans#example",
    )
    excerpt = next(
        item for item in structured_excerpts(document) if item.block_id == rows[1].block_id
    )
    assert "Table columns: SKU | Protocol and port" in excerpt.text
    assert all(text in excerpt.text for text in _bodies(document, "notice"))
    assert "Example plan <https://example.com/plans#example>" in excerpt.text


def test_multirow_headers_caption_and_header_links_are_complete() -> None:
    document = _document(
        "<table><caption>Measured units</caption><thead><tr><th>Plan</th><th>Capacity</th></tr>"
        '<tr><th>Generation</th><th><a href="/units">Requests per minute</a></th></tr></thead>'
        "<tbody><tr><td>Example</td><td>12</td></tr></tbody></table>"
    )
    assert not document.unresolved_dependencies
    row = document.blocks[-1]
    assert row.table_header == "Plan / Generation | Capacity / Requests per minute"
    excerpt = structured_excerpts(document)[-1]
    assert "Measured units" in excerpt.text and "<https://example.com/units>" in excerpt.text
    assert len(row.context_ids) == 2


def test_hidden_tabs_retain_explicit_labels_and_do_not_leak_tab_headings() -> None:
    document = _document(
        '<h2>Configure</h2><ul role="tablist"><li><a id="tab-a" role="tab" href="#panel-a">'
        'Shell</a></li><li><button id="tab-b" role="tab">Template</button></li></ul>'
        '<section id="panel-a" role="tabpanel" aria-labelledby="tab-a">'
        "<p>Shell steps.</p></section>"
        '<section id="panel-b" role="tabpanel" aria-labelledby="tab-b" hidden aria-hidden="true" '
        'style="display:none"><h3>Hidden detail</h3><p>Template steps.</p></section>'
        '<p aria-hidden="true">Real hidden documentation remains.</p>'
        "<h2>Next</h2><p>After tabs.</p>"
    )
    assert not document.unresolved_dependencies
    paragraphs = [block for block in document.blocks if block.kind == "paragraph"]
    assert paragraphs[0].heading_path == ("Widget guide", "Configure", "Tab: Shell")
    assert paragraphs[1].heading_path == (
        "Widget guide",
        "Configure",
        "Hidden detail",
        "Tab: Template",
    )
    assert paragraphs[2].heading_path == ("Widget guide", "Configure")
    assert paragraphs[-1].heading_path == ("Widget guide", "Next")
    assert not document.links and "Real hidden documentation remains." in document.text
    assert "Section: Widget guide / Configure / Hidden detail / Tab: Template" in (
        next(
            item.text
            for item in structured_excerpts(document)
            if item.block_id == paragraphs[1].block_id
        )
    )


def test_ordered_steps_nested_lists_and_code_are_atomic_not_duplicated() -> None:
    document = _document(
        '<ol start="3"><li><p>First step.</p><ul><li><p>Nested detail.</p></li></ul></li>'
        '<li value="7"><p>Second step.</p><p>Continuation.</p></li></ol>'
        "<pre><code>  check_status()\n    keep_indent(&quot;x&quot;)\n</code></pre>"
    )
    assert not document.unresolved_dependencies
    assert document.text.count("First step.") == document.text.count("Nested detail.") == 1
    lists = _bodies(document, "list")
    assert len(lists) == 1 and "3. First step." in lists[0] and "7. Second step." in lists[0]
    assert "  - Nested detail." in lists[0] and "Continuation." in lists[0]
    assert _bodies(document, "code") == ['  check_status()\n    keep_indent("x")\n']


def test_unicode_offsets_cover_exact_blocks_and_canonical_separators() -> None:
    document = _document("<h2>조건</h2><p>가나다 &amp; abc<br>다음 줄.</p><p>끝.</p>")
    cursor = 0
    for block in document.blocks:
        assert block.start == cursor
        body = document.text[block.start : block.end]
        assert body.strip() and block.end - block.start == len(body)
        if block is not document.blocks[-1]:
            assert document.text[block.end : block.end + 2] == "\n\n"
        cursor = block.end + 2
    assert document.blocks[-1].end == len(document.text)
    assert "가나다 & abc\n다음 줄." in document.text
    assert len(document.text.encode("utf-8")) > len(document.text)


def test_large_paragraph_is_not_split_to_evade_the_excerpt_budget() -> None:
    paragraph = "Atomic material. " * 600
    document = _document(f"<p>{paragraph}</p>")
    assert _bodies(document, "paragraph") == [paragraph.strip()]
    assert not document.unresolved_dependencies
    with pytest.raises(ValueError, match="byte limit"):
        structured_excerpts(document)


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "data:text/html,example",
        "file:///example",
        "ftp://example.com/file",
        "https://user@example.com/secret",
        "https://example.com:444/path",
        "http://[invalid",
        "https://example.com\\other",
        "java&#10;script:alert(1)",
        "&#9;https://example.com/path",
    ],
)
def test_malicious_links_keep_labels_but_cannot_become_fetch_targets(href: str) -> None:
    document = _document(f'<p>Read <a href="{href}">source label</a>.</p>')
    assert "source label" in document.text and not document.links
    assert "unsupported_link" in document.unresolved_dependencies
    with pytest.raises(ValueError, match="dependencies"):
        structured_excerpts(document)


def test_links_images_includes_and_scripts_never_perform_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("normalization attempted I/O")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    document = _document(
        '<p><a href="//example.com/reference">Reference</a></p>'
        '<img src="https://example.com/diagram.png" alt="Diagram">'
        '<div data-include="https://example.com/required">Stored placeholder.</div>'
        '<script>fetch("https://example.com/execute")</script>'
    )
    assert document.links[0].target == "https://example.com/reference"
    assert {"unsupported_media", "unresolved_dependency"} <= set(document.unresolved_dependencies)


@pytest.mark.parametrize(
    "table",
    [
        "<table></table>",
        "<table><tr><td>No header</td></tr></table>",
        "<table><tr><th></th></tr><tr><td>Value</td></tr></table>",
        '<table><tr><th colspan="2">Header</th></tr><tr><td>A</td><td>B</td></tr></table>',
        '<table><tr><th>Header</th></tr><tr><td rowspan="2">Value</td></tr></table>',
        "<table><tr><th>Header</th></tr><tr><td>A</td><td>B</td></tr></table>",
        "<table><tr><th>Header</th></tr><tr><td><table><tr><th>Inner</th></tr>"
        "<tr><td>Nested value</td></tr></table></td></tr></table>",
    ],
)
def test_unsupported_tables_hold_instead_of_inventing_headers(table: str) -> None:
    document = _document("<p>Scope remains represented.</p>" + table)
    assert "unsupported_table" in document.unresolved_dependencies
    assert not _bodies(document, "table_row")
    with pytest.raises(ValueError, match="dependencies"):
        structured_excerpts(document)


@pytest.mark.parametrize(
    "body, reason",
    [
        (
            "<p>Keep<custom-inline> unknown text </custom-inline>intact.</p>",
            "unsupported_structure",
        ),
        ("<widget><p>Keep unknown block content.</p></widget>", "unsupported_structure"),
        ("<p>Keep <b>malformed</p></b>", "malformed_structure"),
        ("<p>Keep <div>invalid nesting</div> intact.</p>", "malformed_structure"),
        ('<div class="mermaid">Keep diagram source.</div>', "unsupported_diagram"),
        ('<section role="tabpanel" hidden><p>Keep unnamed tab.</p></section>', "unlabelled_tab"),
        (
            "<ol><li>Keep nested table.<table><tr><th>H</th></tr>"
            "<tr><td>V</td></tr></table></li></ol>",
            "nested_table",
        ),
        ('<ol><li class="note">Keep the step restriction.</li></ol>', "nested_notice"),
        ("<ol><li>Keep the code.<pre>  nested_code()</pre></li></ol>", "nested_code"),
    ],
)
def test_unknown_and_malformed_structures_retain_text_and_hold(body: str, reason: str) -> None:
    document = _document(body)
    assert "Keep" in document.text and reason in document.unresolved_dependencies
    if "custom-inline" in body:
        assert "Keep unknown text intact." in document.text
    with pytest.raises(ValueError, match="dependencies"):
        structured_excerpts(document)


def test_explicit_footnote_reference_is_required_or_unresolved() -> None:
    document = _document(
        '<p>Value<a role="doc-noteref" href="#footnote">1</a></p><h2>Elsewhere</h2>'
        '<p id="footnote" role="doc-footnote">Only for the declared generation.</p>'
    )
    assert not document.unresolved_dependencies
    assert document.blocks[-1].block_id in document.required_context_ids
    missing = _document('<p>Value<a role="doc-noteref" href="#missing">1</a></p>')
    assert "unresolved_reference" in missing.unresolved_dependencies


def test_superscript_reference_binds_plain_footnote_and_keeps_its_section() -> None:
    document = _document(
        '<p>Value<sup><a href="#footnote">1</a></sup></p><h2>Restricted scope</h2>'
        '<p id="footnote">Only use the declared generation.</p>'
    )
    assert not document.unresolved_dependencies
    assert document.blocks[-1].kind == "notice"
    assert "Section: Widget guide / Restricted scope" in structured_excerpts(document)[0].text


def test_badge_text_does_not_make_an_unknown_image_decorative() -> None:
    document = _document(
        '<p>Diagram dependency.</p><img class="badge" alt="Logo" src="/figure.svg">'
    )
    assert "unsupported_media" in document.unresolved_dependencies


@pytest.mark.parametrize(
    "html",
    [
        "<html><body>Plain login shell.</body></html>",
        "<main>Sign in to continue.</main>",
        "<main><h1>Sign in</h1><p>Authentication required.</p>"
        "<form><input type=password></form></main>",
        "<main><h1>Sign in</h1><p>Please continue.</p></main>",
        "<main><nav>Only navigation</nav><p> \n </p></main>",
        "<main><h1>Only a title</h1><template><p>Not a body.</p></template></main>",
    ],
)
def test_no_article_or_authentication_shell_is_rejected(html: str) -> None:
    with pytest.raises(ValueError, match="article|authentication|document text"):
        reprocess_document(_snapshot(html), now=DERIVED)


def test_parser_limits_include_text_attributes_depth_and_input_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert article_tree.MAX_DEPTH == 128 and article_tree.MAX_NODES == 50_000
    assert article_tree.MAX_INPUT_BYTES == 8 * 1024 * 1024
    with pytest.raises(ValueError, match="nesting"):
        article_tree.parse_article("<main>" + "<div>" * 128 + "x" + "</div>" * 128 + "</main>")
    with pytest.raises(ValueError, match="attribute byte"):
        article_tree.parse_article('<main><p title="' + "a" * 8193 + '">Text.</p></main>')
    with pytest.raises(ValueError, match="attribute limit"):
        article_tree.parse_article(
            "<main " + " ".join(f'a{i}="x"' for i in range(65)) + ">x</main>"
        )
    with pytest.raises(ValueError, match="input byte"):
        article_tree.parse_article("가" * (article_tree.MAX_INPUT_BYTES // 3 + 1))
    monkeypatch.setattr(article_tree, "MAX_NODES", 6)
    with pytest.raises(ValueError, match="node limit"):
        article_tree.parse_article("<main><p>a<b>b</b>c<em>d</em>e</p></main>")


def test_context_and_unit_limits_never_silently_truncate(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="required context limit"):
        _document('<aside role="note"><p>Restriction.</p></aside>' * 65)
    monkeypatch.setattr(
        "fdai_ingestion_api_service.cloud_knowledge.structured_normalization.MAX_BLOCKS", 2
    )
    with pytest.raises(ValueError, match="structural unit limit"):
        _document("<p>One.</p><p>Two.</p>")


@pytest.mark.parametrize("now", [datetime(2026, 9, 15), COLLECTED - timedelta(seconds=1)])
def test_derivation_clock_cannot_rewrite_or_precede_source_evidence(now: datetime) -> None:
    with pytest.raises(ValueError, match="clock"):
        reprocess_document(_snapshot("<main><p>Body.</p></main>"), now=now)


def test_snapshot_hashes_are_revalidated_before_derivation() -> None:
    snapshot = _snapshot("<main><p>Body.</p></main>")
    tampered = snapshot.model_copy(update={"original_text": "<main><p>Other.</p></main>"})
    with pytest.raises(ValueError, match="hash"):
        reprocess_document(tampered, now=DERIVED)


def test_extended_disclosure_and_nobr_preserve_body_and_source_dates() -> None:
    snapshot = _snapshot(
        "<main><h1>Guide</h1><details><summary>Dedicated generation</summary>"
        "<p>Use <nobr>12 units</nobr> only.</p></details><p>Outside.</p></main>"
    )
    legacy = reprocess_document(snapshot, now=DERIVED)
    assert "unsupported_structure" in legacy.unresolved_dependencies
    expanded = reprocess_document(snapshot, now=DERIVED, normalizer_version="2.1.0")
    assert not expanded.unresolved_dependencies
    assert expanded.normalizer_version == "2.1.0"
    assert expanded.evidence.model_dump(exclude={"normalized_sha256"}) == (
        snapshot.evidence.model_dump(exclude={"normalized_sha256"})
    )
    assert expanded.text.count("Use 12 units only.") == 1
    excerpts = structured_excerpts(expanded)
    body = next(item for item in excerpts if "Use 12 units" in item.text)
    assert "Disclosure: Dedicated generation" in body.text
    assert "Disclosure:" not in excerpts[-1].text


def test_extended_tab_labels_use_exact_same_group_source_link() -> None:
    snapshot = _snapshot(
        '<main><h1>Guide</h1><div class="tabGroup"><ul role="tablist">'
        '<li role="presentation"><a data-tab="script" href="#panel-a">Shell</a></li></ul>'
        '<section id="panel-a" role="tabpanel" data-tab="script" hidden>'
        "<p>Keep hidden instructions.</p></section></div><p>Outside.</p></main>"
    )
    legacy = reprocess_document(snapshot, now=DERIVED)
    assert "unlabelled_tab" in legacy.unresolved_dependencies
    expanded = reprocess_document(snapshot, now=DERIVED, normalizer_version="2.1.0")
    assert not expanded.unresolved_dependencies
    assert expanded.blocks[1].heading_path == ("Guide", "Tab: Shell")
    assert expanded.blocks[-1].heading_path == ("Guide",)
    assert expanded.text.count("Keep hidden instructions.") == 1


@pytest.mark.parametrize("referenced", [False, True])
def test_extended_duplicate_ids_do_not_choose_a_reference_target(referenced: bool) -> None:
    link = '<p><a role="doc-noteref" href="#repeat">Note</a></p>' if referenced else ""
    snapshot = _snapshot(
        '<main><h1>Guide</h1><p id="repeat">First.</p><p id="repeat">Second.</p>' + link + "</main>"
    )
    expanded = reprocess_document(snapshot, now=DERIVED, normalizer_version="2.1.0")
    assert ("duplicate_html_id" in expanded.unresolved_dependencies) is referenced
    assert "First." in expanded.text and "Second." in expanded.text
    if referenced:
        with pytest.raises(ValueError, match="unresolved"):
            structured_excerpts(expanded)
    else:
        assert structured_excerpts(expanded)


def test_extended_header_only_table_preserves_captured_absence_not_resource_absence() -> None:
    snapshot = _snapshot(
        "<main><h1>Guide</h1><table><thead><tr><th>Name</th><th>Value</th></tr>"
        "</thead></table><p>Other source evidence.</p></main>"
    )
    legacy = reprocess_document(snapshot, now=DERIVED)
    assert "unsupported_table" in legacy.unresolved_dependencies
    expanded = reprocess_document(snapshot, now=DERIVED, normalizer_version="2.1.0")
    assert not expanded.unresolved_dependencies
    row = next(b for b in expanded.blocks if b.kind == "table_row")
    assert row.table_header == "Name | Value"
    assert "No data rows in captured table." in expanded.text
    assert structured_excerpts(expanded)


def test_extended_nested_code_notice_and_table_keep_atomic_context() -> None:
    snapshot = _snapshot(
        "<main><h1>Guide</h1><ol><li>Before.<pre><code>  exact_code()\n</code></pre>"
        '<div class="note"><p>Only this generation.</p></div>'
        "<table><tr><th>Limit</th></tr><tr><td>12</td></tr></table>After.</li></ol>"
        "<p>Related guidance.</p></main>"
    )
    expanded = reprocess_document(snapshot, now=DERIVED, normalizer_version="2.1.0")
    assert not expanded.unresolved_dependencies
    assert expanded.text.count("exact_code()") == 1
    assert "Code block:" in expanded.text and "      exact_code()" in expanded.text
    assert "Table columns: Limit" in expanded.text
    assert "Only this generation." in structured_excerpts(expanded)[-1].text


@pytest.mark.parametrize(
    "body,reason",
    [
        ("<details><p>No source summary.</p></details>", "unsupported_structure"),
        (
            '<section role="tabpanel" data-tab="guess"><p>Unknown label.</p></section>',
            "unlabelled_tab",
        ),
        ('<img alt="Useful image" src="/diagram.png"><p>Body.</p>', "unsupported_media"),
        ("<p><custom-inline>Unknown structure.</custom-inline></p>", "unsupported_structure"),
        (
            '<table><tr><th colspan="2">H</th></tr><tr><td>A</td><td>B</td></tr></table>',
            "unsupported_table",
        ),
    ],
)
def test_extended_normalizer_retains_unproven_dependency_holds(body: str, reason: str) -> None:
    expanded = reprocess_document(
        _snapshot(f"<main><h1>Guide</h1>{body}</main>"), now=DERIVED, normalizer_version="2.1.0"
    )
    assert reason in expanded.unresolved_dependencies
    with pytest.raises(ValueError, match="unresolved"):
        structured_excerpts(expanded)


@pytest.mark.parametrize("tag", ["details", "nobr"])
def test_extended_elements_do_not_discard_required_dependency_attributes(tag: str) -> None:
    body = "<summary>Scope</summary><p>Body.</p>" if tag == "details" else "Body."
    doc = reprocess_document(
        _snapshot(f'<main><h1>Guide</h1><{tag} data-include="/required">{body}</{tag}></main>'),
        now=DERIVED,
        normalizer_version="2.1.0",
    )
    assert "unresolved_dependency" in doc.unresolved_dependencies


def test_extended_tab_group_never_borrows_another_group_label() -> None:
    html = (
        '<main><h1>Guide</h1><div class="tabGroup"><ul role="tablist">'
        '<li><a data-tab="shell" href="#panel">Not this group</a></li></ul></div>'
        '<div class="tabGroup"><section id="panel" role="tabpanel" data-tab="shell">'
        "<p>Unlabelled body.</p></section></div></main>"
    )
    doc = reprocess_document(_snapshot(html), now=DERIVED, normalizer_version="2.1.0")
    assert "unlabelled_tab" in doc.unresolved_dependencies


def test_extended_disclosure_cannot_hide_unrepresented_view_conditions() -> None:
    doc = reprocess_document(
        _snapshot(
            '<main><h1>Guide</h1><details data-monikers="only-one-view">'
            "<summary>Scope</summary><p>Body.</p></details></main>"
        ),
        now=DERIVED,
        normalizer_version="2.1.0",
    )
    assert "unsupported_condition" in doc.unresolved_dependencies


@pytest.mark.parametrize("nested", [False, True])
def test_extended_table_uses_the_selected_inline_normalizer(nested: bool) -> None:
    table = "<table><tr><th>Limit</th></tr><tr><td><nobr>12 units</nobr></td></tr></table>"
    body = f"<ol><li>Respect this table.{table}</li></ol>" if nested else table
    snapshot = _snapshot(f"<main><h1>Guide</h1>{body}</main>")
    legacy = reprocess_document(snapshot, now=DERIVED)
    assert "unsupported_structure" in legacy.unresolved_dependencies
    doc = reprocess_document(snapshot, now=DERIVED, normalizer_version="2.1.0")
    assert not doc.unresolved_dependencies
    assert any("12 units" in excerpt.text for excerpt in structured_excerpts(doc))


@pytest.mark.parametrize(
    "body",
    [
        '<ol><li>Step.<pre><code data-monikers="restricted">run()</code></pre></li></ol>',
        '<table data-tab-condition="restricted"><tr><th>Limit</th></tr>'
        "<tr><td>12</td></tr></table>",
    ],
)
def test_extended_composites_keep_descendant_view_conditions(body: str) -> None:
    doc = reprocess_document(
        _snapshot(f"<main><h1>Guide</h1>{body}</main>"), now=DERIVED, normalizer_version="2.1.0"
    )
    assert "unsupported_condition" in doc.unresolved_dependencies


@pytest.mark.parametrize(
    "body",
    [
        "<p>Before.<summary>Orphan summary.</summary>After.</p>",
        "<details><p>Body before summary.</p><summary>Late.</summary></details>",
        "<details><summary>First.</summary><summary>Second.</summary><p>Body.</p></details>",
    ],
)
def test_extended_summary_is_only_supported_in_its_explicit_disclosure(body: str) -> None:
    doc = reprocess_document(
        _snapshot(f"<main><h1>Guide</h1>{body}</main>"), now=DERIVED, normalizer_version="2.1.0"
    )
    assert "unsupported_structure" in doc.unresolved_dependencies


@pytest.mark.parametrize("tag", ["details", "nobr"])
def test_extended_elements_retain_explicit_notice_ownership(tag: str) -> None:
    content = (
        "<summary>Restriction</summary><p>Dedicated generation only.</p>"
        if tag == "details"
        else "Dedicated generation only."
    )
    doc = reprocess_document(
        _snapshot(
            f'<main><h1>Guide</h1><{tag} role="note">{content}</{tag}>'
            "<p>Follow the procedure.</p></main>"
        ),
        now=DERIVED,
        normalizer_version="2.1.0",
    )
    assert not doc.unresolved_dependencies
    assert doc.required_context_ids
    assert "Dedicated generation only." in structured_excerpts(doc)[-1].text
