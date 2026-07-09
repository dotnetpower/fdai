// mermaid.mjs - remark plugin that turns a fenced ```mermaid code block
// into a raw <pre class="mermaid"> node. Two things this buys us:
//
// 1. It lands as an HTML node in the mdast tree, so Starlight's default
//    code renderer (Expressive Code) skips it - otherwise the diagram
//    source would appear as a syntax-highlighted code snippet instead
//    of being handed to mermaid.js at runtime.
// 2. The `<pre class="mermaid">` shape matches what the mermaid client
//    library scans for when `mermaid.run()` is called, so the head-level
//    loader script (see astro.config.mjs) can render it in place without
//    any extra wiring per page.
//
// The escaping is deliberately minimal: mermaid syntax uses no HTML
// entities, but `<`/`>` do appear in flowchart edge syntax (e.g. `-->`)
// so we escape those to keep the browser parser happy before the client
// script rehydrates the original text back into the DOM. Node labels can
// also carry `"` (e.g. `Odin["Odin - Master Planner"]`); that is safe in
// element text content but MUST additionally be escaped inside the
// double-quoted `data-mermaid-src` attribute, or the attribute (and the
// whole <pre> tag) terminates early and the diagram source is truncated.

import { visit } from "unist-util-visit";

function escapeForHtml(value) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escapeForAttribute(value) {
  return escapeForHtml(value).replace(/"/g, "&quot;");
}

export function remarkMermaid() {
  return (tree) => {
    visit(tree, "code", (node, index, parent) => {
      if (!parent || typeof index !== "number") return;
      if (node.lang !== "mermaid") return;

      /** @type {import('mdast').Html} */
      const htmlNode = {
        type: "html",
        value: `<pre class="mermaid" data-mermaid-src="${escapeForAttribute(node.value)}">${escapeForHtml(node.value)}</pre>`,
      };
      parent.children[index] = htmlNode;
    });
  };
}

export default remarkMermaid;
