import assert from "node:assert/strict";
import { test } from "node:test";

import { renderLibraryPage } from "../share-pages.mjs";

const template = `<!doctype html><html><head>
<meta name="description" content="{{META_DESCRIPTION}}">
{{SOCIAL_META}}
<title>{{DOCUMENT_TITLE}}</title>
</head><body data-manual-id="{{MANUAL_ID}}"></body></html>`;
const catalog = {
  manuals: [{
    id: "target-architecture",
    title: "FDAI Target Architecture",
    description: "에이전트 기반 운영 제어 영역과 Azure 배치",
    coverImage: "assets/target-architecture.jpeg",
  }],
};

test("manual share page exposes crawler-readable Open Graph metadata", () => {
  const html = renderLibraryPage(
    template,
    catalog,
    "https://manuals.example.com/fdai",
    "target-architecture",
  );

  assert.match(html, /<meta property="og:title" content="FDAI Target Architecture">/);
  assert.match(html, /<meta property="og:description" content="에이전트 기반 운영 제어 영역과 Azure 배치">/);
  assert.match(html, /<meta property="og:image" content="https:\/\/manuals\.example\.com\/fdai\/assets\/target-architecture\.jpeg">/);
  assert.match(html, /<meta property="og:url" content="https:\/\/manuals\.example\.com\/fdai\/target-architecture\.html">/);
  assert.match(html, /<meta name="twitter:card" content="summary_large_image">/);
  assert.match(html, /<link rel="canonical" href="https:\/\/manuals\.example\.com\/fdai\/target-architecture\.html">/);
  assert.match(html, /<body data-manual-id="target-architecture">/);
  assert.doesNotMatch(html, /\{\{[A-Z_]+\}\}/);
});

test("share metadata escapes catalog text and rejects unknown manuals", () => {
  const unsafeCatalog = {
    manuals: [{
      ...catalog.manuals[0],
      title: 'Architecture <review> "draft"',
      description: "Evidence & authority",
    }],
  };
  const html = renderLibraryPage(
    template,
    unsafeCatalog,
    "https://manuals.example.com/fdai",
    "target-architecture",
  );

  assert.match(html, /content="Architecture &lt;review&gt; &quot;draft&quot;"/);
  assert.match(html, /content="Evidence &amp; authority"/);
  assert.throws(
    () => renderLibraryPage(template, catalog, "https://manuals.example.com/fdai", "missing"),
    /catalog has no manual/,
  );
  assert.throws(
    () => renderLibraryPage(template, {
      manuals: [{ ...catalog.manuals[0], coverImage: "https://outside.example.com/cover.jpeg" }],
    }, "https://manuals.example.com/fdai", "target-architecture"),
    /cover image must stay under the public base URL/,
  );
});
