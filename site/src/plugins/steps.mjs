// steps.mjs - remark plugin that tags a marked ordered list so it renders
// as a vertical "steps" sequence (numbered badges + a connecting rail),
// the way a docs-site quickstart shows an ordered procedure.
//
// Design mirrors src/plugins/cards.mjs, but is deliberately lighter: a
// steps list is still a genuine ordered list, so instead of replacing it
// with raw HTML this plugin only attaches a class to the existing `list`
// node (via mdast `data.hProperties`). That keeps every child - including
// links, which remarkRewriteLinks has already rewritten - as real nodes,
// and preserves the ordered-list semantics for readers and assistive tech.
//
// Convention: an HTML comment marker on its own line, immediately before an
// ordered list. GitHub renders the marker invisibly and the list normally:
//
//   <!-- fdai:steps -->
//
//   1. **First step.** ...
//   2. **Second step.** ...
//
// The marker node is removed and the following ordered list gains the
// `fdai-steps` class (styled in src/styles/custom.css).

import { visit } from "unist-util-visit";

const MARKER = /^<!--\s*fdai:steps\s*-->\s*$/;

export function remarkSteps() {
  return (tree) => {
    const markersToRemove = [];
    visit(tree, "html", (node, index, parent) => {
      if (!parent || typeof index !== "number") return;
      if (!MARKER.test(node.value.trim())) return;
      const next = parent.children[index + 1];
      if (!next || next.type !== "list" || !next.ordered) return;

      next.data = next.data || {};
      next.data.hProperties = next.data.hProperties || {};
      const existing = next.data.hProperties.className;
      const classes = Array.isArray(existing)
        ? existing
        : existing
          ? [existing]
          : [];
      if (!classes.includes("fdai-steps")) classes.push("fdai-steps");
      next.data.hProperties.className = classes;

      markersToRemove.push({ parent, node });
    });

    for (const { parent, node } of markersToRemove) {
      const idx = parent.children.indexOf(node);
      if (idx !== -1) parent.children.splice(idx, 1);
    }
  };
}

export default remarkSteps;
