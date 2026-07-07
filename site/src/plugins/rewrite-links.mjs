// rewrite-links.mjs - remark plugin that rewrites Markdown links so
// cross-file navigation works on the deployed site.
//
// The site presents docs from two source trees, both symlinked into
// src/content/docs/:
//   docs/user-guide/**   -> content root (root locale) and /ko/*
//   docs/roadmap/**      -> /reference/roadmap/**  and /ko/reference/roadmap/**
//
// The plugin resolves the current file via realpathSync (following
// symlinks) so it works uniformly for both mount trees without
// hardcoding either one. A one-time index maps every mounted source
// path back to its slug so outgoing links can be rewritten precisely.

import fs from "node:fs";
import path from "node:path";
import { visit } from "unist-util-visit";

const CONTENT_ROOT = "src/content/docs";
const GITHUB_BLOB_BASE = "https://github.com/dotnetpower/fdai/blob/main/";

const scriptDir = path.dirname(new URL(import.meta.url).pathname);
const REPO_ROOT = path.resolve(scriptDir, "..", "..", "..");
const CONTENT_ROOT_ABS = path.join(REPO_ROOT, "site", CONTENT_ROOT);

/**
 * Walk src/content/docs/** at load time and record every symlink as
 *   canonical repo-relative source path  ->  mount slug (POSIX).
 */
function buildSourceToSlugIndex() {
  const index = new Map();
  if (!fs.existsSync(CONTENT_ROOT_ABS)) return index;
  const stack = [CONTENT_ROOT_ABS];
  while (stack.length > 0) {
    const dir = stack.pop();
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const abs = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        stack.push(abs);
        continue;
      }
      if (!entry.isSymbolicLink()) continue;
      if (!entry.name.endsWith(".md")) continue;
      let realAbs;
      try {
        realAbs = fs.realpathSync(abs);
      } catch {
        continue;
      }
      const repoRelReal = path
        .relative(REPO_ROOT, realAbs)
        .split(path.sep)
        .join("/");
      const slug = path
        .relative(CONTENT_ROOT_ABS, abs)
        .split(path.sep)
        .join("/");
      index.set(repoRelReal, slug);
    }
  }
  return index;
}

const SOURCE_TO_SLUG = buildSourceToSlugIndex();

function splitHash(url) {
  const hashAt = url.indexOf("#");
  if (hashAt === -1) return { pathPart: url, hash: "" };
  return { pathPart: url.slice(0, hashAt), hash: url.slice(hashAt + 1) };
}

function mountSlugFrom(absPath) {
  const marker = `${path.sep}${CONTENT_ROOT.split("/").join(path.sep)}${path.sep}`;
  const idx = absPath.indexOf(marker);
  if (idx === -1) return null;
  return absPath.slice(idx + marker.length).split(path.sep).join("/");
}

function slugToOriginalPath(absPath) {
  try {
    const real = fs.realpathSync(absPath);
    return path.relative(REPO_ROOT, real).split(path.sep).join("/");
  } catch {
    return null;
  }
}

function originalToMountSlug(originalPath) {
  return SOURCE_TO_SLUG.get(originalPath) ?? null;
}

function mountSlugToUrl(slug) {
  const noExt = slug.replace(/\.md$/, "");
  const noIndex = noExt.replace(/(^|\/)index$/, "$1");
  const trimmed = noIndex.endsWith("/") ? noIndex.slice(0, -1) : noIndex;
  return `/${trimmed}${trimmed.length > 0 ? "/" : ""}`;
}

function relativeSiteUrl(fromUrl, toUrl) {
  const fromDir = fromUrl.replace(/\/[^/]*$/, "/");
  let rel = path.posix.relative(fromDir, toUrl);
  if (rel === "") rel = "./";
  else if (!rel.endsWith("/")) rel += "/";
  return rel;
}

export function remarkRewriteLinks() {
  return (tree, file) => {
    const absPath = file.path ?? "";
    const currentMountSlug = mountSlugFrom(absPath);
    if (!currentMountSlug) return;
    const currentOriginal = slugToOriginalPath(absPath);
    if (!currentOriginal) return;
    const currentOriginalDir = path.posix.dirname(currentOriginal);
    const currentUrl = mountSlugToUrl(currentMountSlug);

    visit(tree, "link", (node) => {
      const url = node.url;
      if (!url) return;
      if (
        url.startsWith("#") ||
        /^[a-z]+:/i.test(url) ||
        url.startsWith("//")
      ) {
        return;
      }
      const { pathPart, hash } = splitHash(url);
      // Anchor-only after strip? Already handled above.
      if (!pathPart) return;

      // Resolve against the *canonical* source location so authored
      // relative paths (which assume the docs/... layout) work correctly.
      const targetOriginal = path.posix.normalize(
        path.posix.join(currentOriginalDir, pathPart),
      );

      // Markdown targets get either an on-site URL or a GitHub blob URL.
      if (pathPart.endsWith(".md")) {
        const targetMount = originalToMountSlug(targetOriginal);
        if (targetMount == null) {
          const repoRelative = targetOriginal.replace(/^(\.\.\/)+/, "");
          node.url = `${GITHUB_BLOB_BASE}${repoRelative}${hash ? `#${hash}` : ""}`;
          return;
        }
        const targetUrl = mountSlugToUrl(targetMount);
        const rel = relativeSiteUrl(currentUrl, targetUrl);
        node.url = `${rel}${hash ? `#${hash}` : ""}`;
        return;
      }

      // Non-markdown links that point at a repo path (source code,
      // config, policy, etc.) are not published to the site. Send them
      // to GitHub so the reader still lands on the canonical source.
      // We treat as a repo link when the target has an extension we
      // publish only as source, OR when the target has no scheme AND
      // ends in `/` (a directory reference).
      const isSourceExt = /\.(py|yaml|yml|json|toml|ini|sh|ts|tsx|js|mjs|cjs|tf|tftpl|rego|mako|astro|mdx|css|html|env|env-example|env-local|Dockerfile|dockerignore|lock)$/i.test(pathPart);
      const isDirRef = pathPart.endsWith("/");
      if (isSourceExt || isDirRef) {
        const repoRelative = targetOriginal.replace(/^(\.\.\/)+/, "");
        const kind = isDirRef ? "tree/main/" : "blob/main/";
        node.url = `https://github.com/dotnetpower/fdai/${kind}${repoRelative}${hash ? `#${hash}` : ""}`;
        return;
      }

      // Anything else (images, other assets) - leave alone.
    });
  };
}

export default remarkRewriteLinks;
