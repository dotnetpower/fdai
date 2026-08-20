import path from "node:path";
import { visit } from "unist-util-visit";

const CONTENT_MARKER = "/site/src/content/docs/";
const DIAGRAM_ASSET_RE = /(?:^|\/)diagrams\/generated\/([a-z0-9-]+)\.(en|ko)\.svg$/;

function escapeAttribute(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function routeForFile(filePath) {
  const normalized = filePath.replaceAll("\\", "/");
  const markerAt = normalized.indexOf(CONTENT_MARKER);
  if (markerAt === -1) return null;
  const slug = normalized.slice(markerAt + CONTENT_MARKER.length).replace(/\.mdx?$/, "");
  const route = slug.replace(/(^|\/)index$/, "$1").replace(/\/$/, "");
  return `/${route}${route ? "/" : ""}`;
}

function relativeAssetUrl(route, asset) {
  const relative = path.posix.relative(route, `/diagrams/generated/${asset}`);
  return relative.startsWith(".") ? relative : `./${relative}`;
}

export function diagramEmbedForImage(node, filePath) {
  const match = DIAGRAM_ASSET_RE.exec(node.url ?? "");
  const route = routeForFile(filePath);
  if (!match || route == null) return null;
  const [, id, locale] = match;
  const manifest = relativeAssetUrl(route, `${id}.manifest.json`);
  const image = relativeAssetUrl(route, `${id}.${locale}.svg`);
  const alt = escapeAttribute(node.alt ?? "");
  return `<fdai-architecture-diagram manifest="${manifest}" locale="${locale}" style="display:block">
  <img src="${image}" alt="${alt}" loading="lazy" style="display:block;width:100%;height:auto" />
</fdai-architecture-diagram>`;
}

export function remarkFdaiDiagrams() {
  return (tree, file) => {
    visit(tree, "image", (node, index, parent) => {
      if (index === undefined || !parent) return;
      const embed = diagramEmbedForImage(node, file.path ?? "");
      if (embed == null) return;
      parent.children[index] = { type: "html", value: embed };
    });
  };
}

export default remarkFdaiDiagrams;
