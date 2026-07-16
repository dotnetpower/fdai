// tabs.mjs - remark plugin that turns a marked region of labelled sections
// into a tab group (like a docs-site "npm / pnpm / yarn" code switcher),
// while the Markdown source stays readable on GitHub as plain headings +
// code blocks.
//
// Same rationale as src/plugins/cards.mjs and steps.mjs: canonical docs live
// as .md and must render on GitHub, so the tab UI is produced at build time
// from a plain-Markdown convention rather than an MDX component.
//
// Convention: a `<!-- fdai:tabs -->` marker, one heading per tab (the heading
// text is the tab label), the tab's content below it, and a closing
// `<!-- /fdai:tabs -->` marker. On GitHub this reads as normal headings and
// code blocks:
//
//   <!-- fdai:tabs -->
//   #### azd
//   ```bash
//   azd up
//   ```
//   #### terraform
//   ```bash
//   terraform -chdir=infra apply
//   ```
//   <!-- /fdai:tabs -->
//
// The tabs are CSS-only (hidden radio inputs + :checked sibling selectors in
// src/styles/custom.css), so no client JavaScript is required. Code inside a
// tab is rendered as a plain <pre> (Expressive Code highlighting is skipped
// inside tabs) - acceptable for short command snippets.

import { visit } from "unist-util-visit";

const OPEN = /^<!--\s*fdai:tabs\s*-->\s*$/;
const CLOSE = /^<!--\s*\/fdai:tabs\s*-->\s*$/;

let groupSeq = 0;

function escapeForHtml(value) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escapeForAttribute(value) {
  return escapeForHtml(value).replace(/"/g, "&quot;");
}

function collectText(node) {
  let out = "";
  visit(node, "text", (t) => {
    out += t.value;
  });
  visit(node, "inlineCode", (t) => {
    out += t.value;
  });
  return out;
}

function renderPanel(nodes) {
  const parts = [];
  for (const node of nodes) {
    if (node.type === "code") {
      parts.push(
        `<pre class="fdai-tab-code"><code>${escapeForHtml(node.value)}</code></pre>`,
      );
    } else if (node.type === "paragraph") {
      parts.push(`<p>${escapeForHtml(collectText(node))}</p>`);
    }
  }
  return parts.join("");
}

function buildTabsHtml(tabs) {
  const gid = `fdai-tabs-${groupSeq++}`;
  const inputs = tabs
    .map(
      (_, i) =>
        `<input type="radio" name="${gid}" id="${gid}-${i}" class="fdai-tab-input"${
          i === 0 ? " checked" : ""
        }>`,
    )
    .join("");
  const labels = tabs
    .map(
      (tab, i) =>
        `<label for="${gid}-${i}" class="fdai-tab-label">${escapeForHtml(
          tab.label,
        )}</label>`,
    )
    .join("");
  const panels = tabs
    .map(
      (tab) =>
        `<div class="fdai-tabpanel">${renderPanel(tab.content)}</div>`,
    )
    .join("");
  return (
    `<div class="fdai-tabs" role="tablist" aria-label="${escapeForAttribute(
      tabs.map((t) => t.label).join(", "),
    )}">${inputs}<div class="fdai-tablist">${labels}</div>` +
    `<div class="fdai-tabpanels">${panels}</div></div>`
  );
}

export function remarkTabs() {
  return (tree) => {
    const groups = [];
    visit(tree, "html", (node, index, parent) => {
      if (!parent || typeof index !== "number") return;
      if (!OPEN.test(node.value.trim())) return;
      // Find the matching close marker among following siblings.
      let closeIdx = -1;
      for (let i = index + 1; i < parent.children.length; i += 1) {
        const sib = parent.children[i];
        if (sib.type === "html" && CLOSE.test(sib.value.trim())) {
          closeIdx = i;
          break;
        }
      }
      if (closeIdx === -1) return;

      // Group the range by heading: each heading opens a tab.
      const tabs = [];
      for (let i = index + 1; i < closeIdx; i += 1) {
        const child = parent.children[i];
        if (child.type === "heading") {
          tabs.push({ label: collectText(child).trim(), content: [] });
        } else if (tabs.length > 0) {
          tabs[tabs.length - 1].content.push(child);
        }
      }
      if (tabs.length === 0) return;

      groups.push({
        parent,
        openNode: node,
        closeNode: parent.children[closeIdx],
        html: buildTabsHtml(tabs),
      });
    });

    for (const { parent, openNode, closeNode, html } of groups) {
      const openIdx = parent.children.indexOf(openNode);
      const closeIdx = parent.children.indexOf(closeNode);
      if (openIdx === -1 || closeIdx === -1) continue;
      parent.children.splice(openIdx, closeIdx - openIdx + 1, {
        type: "html",
        value: html,
      });
    }
  };
}

export default remarkTabs;
