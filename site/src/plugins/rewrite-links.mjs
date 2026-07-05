// rewrite-links.mjs — remark plugin that rewrites Markdown links so
// cross-file navigation works on the deployed site.
//
// The docs at docs/roadmap/**/*.md are authored to be read on GitHub as
// plain Markdown. That means every cross-reference is a relative path
// to another Markdown file (e.g. `[foo](phases/foo.md)`,
// `[bar](../../.github/instructions/architecture.instructions.md)`).
// Left untouched by the site pipeline, `.md` links 404 and `.github/`
// links point at a directory the site intentionally does not publish.
//
// The plugin rewrites each link in three flavours:
//
//   1. Links whose *original* target resolves to a Markdown file inside
//      docs/roadmap/ become relative site URLs. `.md` becomes a trailing
//      slash, `-ko.md` moves under the `/ko/…` locale, and `README.md`
//      collapses to the directory index. We compute *relative* URLs so
//      the same output works regardless of the deploy base path.
//
//   2. Links whose original target lands under `.github/**` become an
//      absolute GitHub blob URL. This is the documented English-only
//      developer scope, kept off the site on purpose — but readers
//      still deserve to reach the source.
//
//   3. Anchors, external URLs, and `mailto:` links are untouched.
//
// Resolution is done against each file's *original* location under
// docs/roadmap/, not its symlink under site/src/content/docs/, so the
// authored relative paths (which assume the canonical layout) resolve
// correctly. The plugin infers each file's original path from its
// mounted slug: `ko/roadmap/foo.md` corresponds to `foo-ko.md`,
// `roadmap/index.md` corresponds to `README.md`, and so on.

import path from "node:path";
import { visit } from "unist-util-visit";

const CONTENT_ROOT = "src/content/docs";
const ROADMAP_ORIGINAL_DIR = "docs/roadmap";
const GITHUB_BLOB_BASE = "https://github.com/dotnetpower/aiopspilot/blob/main/";

/**
 * Split a URL into its path and hash components. A pure `#anchor`
 * returns `{ pathPart: "", hash: "anchor" }` so callers can short-circuit.
 */
function splitHash(url) {
  const hashAt = url.indexOf("#");
  if (hashAt === -1) return { pathPart: url, hash: "" };
  return { pathPart: url.slice(0, hashAt), hash: url.slice(hashAt + 1) };
}

/**
 * Convert an absolute file path (as reported by the vfile) into the
 * collection-relative slug it is mounted under, e.g.
 * `site/src/content/docs/ko/roadmap/foo.md` → `ko/roadmap/foo.md`.
 * Returns null when the file is outside the mount tree.
 */
function mountSlugFrom(absPath) {
  const marker = `${path.sep}${CONTENT_ROOT.split("/").join(path.sep)}${path.sep}`;
  const idx = absPath.indexOf(marker);
  if (idx === -1) return null;
  const slug = absPath.slice(idx + marker.length).split(path.sep).join("/");
  return slug;
}

/**
 * Map a mounted slug back to its canonical repo-relative source path.
 *
 *   reference/roadmap/foo.md              → docs/roadmap/foo.md
 *   reference/roadmap/index.md            → docs/roadmap/README.md
 *   reference/roadmap/phases/foo.md       → docs/roadmap/phases/foo.md
 *   ko/reference/roadmap/foo.md           → docs/roadmap/foo-ko.md
 *   ko/reference/roadmap/index.md         → docs/roadmap/README-ko.md
 *   ko/reference/roadmap/phases/foo.md    → docs/roadmap/phases/foo-ko.md
 */
function mountSlugToOriginal(slug) {
  const isKo = slug.startsWith("ko/");
  const withoutLocale = isKo ? slug.slice(3) : slug;
  const rest = withoutLocale.replace(/^reference\/roadmap\//, "");
  const parts = rest.split("/");
  const filename = parts[parts.length - 1];
  const dirParts = parts.slice(0, -1);
  const baseName = filename === "index.md" ? "README" : filename.replace(/\.md$/, "");
  const suffix = isKo ? "-ko.md" : ".md";
  return path.posix.join(ROADMAP_ORIGINAL_DIR, ...dirParts, `${baseName}${suffix}`);
}

/**
 * Inverse of mountSlugToOriginal: map a canonical repo-relative path
 * (`docs/roadmap/foo.md`, `docs/roadmap/foo-ko.md`, `docs/roadmap/README.md`)
 * back to its mounted slug. Returns null when the path is not under
 * docs/roadmap/.
 */
function originalToMountSlug(originalPath) {
  const rel = originalPath.startsWith(`${ROADMAP_ORIGINAL_DIR}/`)
    ? originalPath.slice(ROADMAP_ORIGINAL_DIR.length + 1)
    : null;
  if (rel == null) return null;
  const parts = rel.split("/");
  const filename = parts[parts.length - 1];
  const dirParts = parts.slice(0, -1);
  const isKo = /-ko\.md$/.test(filename);
  const bare = filename.replace(/-ko\.md$/, ".md");
  const asIndex = bare === "README.md" ? "index.md" : bare;
  const locale = isKo ? "ko/" : "";
  return `${locale}reference/roadmap/${[...dirParts, asIndex].join("/")}`;
}

/**
 * Convert a mounted slug to the URL the site will serve it under.
 *   roadmap/foo.md        → /roadmap/foo/
 *   roadmap/index.md      → /roadmap/
 *   ko/roadmap/foo.md     → /ko/roadmap/foo/
 */
function mountSlugToUrl(slug) {
  const noExt = slug.replace(/\.md$/, "");
  const noIndex = noExt.replace(/(^|\/)index$/, "$1");
  const trimmed = noIndex.endsWith("/") ? noIndex.slice(0, -1) : noIndex;
  return `/${trimmed}${trimmed.length > 0 ? "/" : ""}`;
}

/**
 * Compute a document-relative URL from one site URL to another so the
 * link works regardless of the deploy `base` path. Both inputs are
 * expected to be trailing-slash directory-style URLs, matching what
 * mountSlugToUrl() produces.
 */
function relativeSiteUrl(fromUrl, toUrl) {
  // Treat the current URL as a directory (it ends in "/") so path.relative
  // walks up the right number of levels.
  const fromDir = fromUrl.replace(/\/[^/]*$/, "/");
  const toClean = toUrl;
  let rel = path.posix.relative(fromDir, toClean);
  if (rel === "") rel = "./";
  else if (!rel.endsWith("/")) rel += "/";
  return rel;
}

export function remarkRewriteLinks() {
  return (tree, file) => {
    const currentMountSlug = mountSlugFrom(file.path ?? "");
    if (!currentMountSlug) return;
    const currentOriginal = mountSlugToOriginal(currentMountSlug);
    const currentOriginalDir = path.posix.dirname(currentOriginal);
    const currentUrl = mountSlugToUrl(currentMountSlug);

    visit(tree, "link", (node) => {
      const url = node.url;
      if (!url) return;

      // Anchor-only, absolute, or protocol-scoped links are already fine.
      if (url.startsWith("#") || /^[a-z]+:/i.test(url) || url.startsWith("//")) {
        return;
      }

      const { pathPart, hash } = splitHash(url);
      // We only rewrite links that point at Markdown files.
      if (!pathPart.endsWith(".md")) return;

      // Resolve against the *canonical* location so authored relative
      // paths (which assume the docs/roadmap/ layout) work correctly.
      const targetOriginal = path.posix.normalize(
        path.posix.join(currentOriginalDir, pathPart),
      );

      // Off-site: send readers to the canonical source on GitHub.
      const targetMount = originalToMountSlug(targetOriginal);
      if (targetMount == null) {
        // Any path outside docs/roadmap/ (e.g. .github/, ../../README.md)
        // is served as a GitHub blob link.
        const repoRelative = targetOriginal.replace(/^(\.\.\/)+/, "");
        node.url = `${GITHUB_BLOB_BASE}${repoRelative}${hash ? `#${hash}` : ""}`;
        return;
      }

      // On-site: compute a relative site URL so the link works under
      // any deploy `base` path.
      const targetUrl = mountSlugToUrl(targetMount);
      const rel = relativeSiteUrl(currentUrl, targetUrl);
      node.url = `${rel}${hash ? `#${hash}` : ""}`;
    });
  };
}

export default remarkRewriteLinks;
