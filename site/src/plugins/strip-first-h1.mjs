// strip-first-h1.mjs - remark plugin that removes a document's first H1
// when Starlight already owns the page H1 through front-matter `title`.
//
// Why: Starlight renders `frontmatter.title` as the page's H1 automatically.
// Our canonical docs at docs/roadmap/**/*.md still open with a Markdown
// `# Title` line so they read naturally in a plain-text viewer or on
// GitHub. Left as-is, the site shows both headings back-to-back. This
// plugin strips the first Markdown H1 whenever a title exists. The
// front-matter title is the site's accessible H1, while the Markdown H1
// remains in the canonical source for GitHub readers. This also prevents
// display-terminology differences from producing two page H1 elements.
//
// This runs during Markdown rendering - after content sync - so it does
// not interfere with `docsSchema()` validation.

/**
 * @typedef {import('mdast').Root} MdastRoot
 */

export function remarkStripFirstH1() {
  return (tree, file) => {
    const title = file.data.astro?.frontmatter?.title;
    if (typeof title !== "string" || title.trim().length === 0) return;

    const idx = tree.children.findIndex(
      (node) => node.type === "heading" && node.depth === 1,
    );
    if (idx === -1) return;

    tree.children.splice(idx, 1);
  };
}

export default remarkStripFirstH1;
