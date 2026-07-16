// cards.mjs - remark plugin that turns a marked Markdown list into a
// responsive card grid, so a "Next steps" style link list renders like a
// docs-site card deck without leaving the canonical Markdown behind.
//
// Why a plugin rather than authored HTML or MDX:
//
//   - The source stays valid Markdown that reads cleanly on GitHub (a
//     plain bulleted list of links). Canonical docs under docs/**/*.md
//     are the source of truth and must render on GitHub; MDX components
//     would break that and the .md-based mount + translation SHA gates.
//   - Each link stays a real mdast `link` node, so remarkRewriteLinks
//     (which must run BEFORE this plugin - see astro.config.mjs ordering)
//     rewrites `.md` targets to on-site URLs first. Authoring the cards as
//     raw HTML `<a href="...md">` would bypass that rewrite and 404.
//
// Convention: an HTML comment marker on its own line, immediately followed
// by a list. GitHub renders the marker invisibly and the list normally:
//
//   <!-- fdai:cards -->
//
//   - [Card title](target.md) - short description after a dash.
//   - [Another card](other.md) - its description.
//
// Each list item becomes one card: the first link is the card title and
// link target; any text after the link (minus a leading separator) is the
// card description. The marker node is replaced in place with the grid
// container and the original list node is removed.

import { visit } from "unist-util-visit";

const MARKER = /^<!--\s*fdai:cards\s*-->\s*$/;
const LEADING_SEPARATOR = /^\s*[-:\u2013\u2014]\s*/;

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
  return out;
}

function cardFor(item) {
  let href = "";
  let title = "";
  visit(item, "link", (link) => {
    if (title) return;
    href = link.url;
    title = collectText(link).trim();
  });
  if (!title || !href) return null;

  const full = collectText(item).replace(/\s+/g, " ").trim();
  let description = full;
  if (full.startsWith(title)) {
    description = full.slice(title.length).replace(LEADING_SEPARATOR, "").trim();
  }

  const descriptionHtml = description
    ? `<span class="fdai-card-desc">${escapeForHtml(description)}</span>`
    : "";
  return (
    `<a class="fdai-card" href="${escapeForAttribute(href)}">` +
    `<span class="fdai-card-title">${escapeForHtml(title)}</span>` +
    `${descriptionHtml}</a>`
  );
}

export function remarkCards() {
  return (tree) => {
    // Collect first, mutate after: removing the sibling list while visiting
    // would shift indices mid-traversal.
    const jobs = [];
    visit(tree, "html", (node, index, parent) => {
      if (!parent || typeof index !== "number") return;
      if (!MARKER.test(node.value.trim())) return;
      const next = parent.children[index + 1];
      if (!next || next.type !== "list") return;
      jobs.push({ node, listNode: next, parent });
    });

    for (const { node, listNode, parent } of jobs) {
      const cards = listNode.children
        .map(cardFor)
        .filter(Boolean)
        .join("");
      if (!cards) continue;
      node.value = `<div class="fdai-cards">${cards}</div>`;
      const listIndex = parent.children.indexOf(listNode);
      if (listIndex !== -1) parent.children.splice(listIndex, 1);
    }
  };
}

export default remarkCards;
