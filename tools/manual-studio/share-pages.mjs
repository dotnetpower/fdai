/** Render crawler-readable Manual Studio pages with manual-specific Open Graph metadata. */
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const manualIdPattern = /^[a-z0-9-]+$/;

function escapeAttribute(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function normalizedBaseUrl(value) {
  const url = new URL(value);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("Manual Studio share base URL must use HTTP or HTTPS.");
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new Error("Manual Studio share base URL must not contain credentials or URL state.");
  }
  return url.toString().replace(/\/+$/, "");
}

function replaceRequired(template, token, value) {
  if (!template.includes(token)) throw new Error(`Manual Studio template token is missing: ${token}`);
  return template.replaceAll(token, value);
}

/** Render the library shell for one manual, or generic library metadata when no manual is selected. */
export function renderLibraryPage(template, catalog, baseUrl, manualId = null) {
  const base = `${normalizedBaseUrl(baseUrl)}/`;
  const manual = manualId === null
    ? null
    : catalog.manuals.find((candidate) => candidate.id === manualId) ?? null;
  if (manualId !== null && manual === null) {
    throw new Error(`Manual Studio catalog has no manual: ${manualId}`);
  }

  const title = manual?.title ?? "FDAI Manual Studio";
  const description = manual?.description ??
    "FDAI 설명서를 단계별로 탐색하고 HTML 슬라이드로 확인합니다.";
  const imagePath = manual?.coverImage ?? catalog.manuals[0]?.coverImage;
  if (typeof imagePath !== "string") throw new Error("Manual Studio catalog has no cover image.");
  const pagePath = manual === null ? "library.html" : `${manual.id}.html`;
  const pageUrl = new URL(pagePath, base).toString();
  const imageUrlValue = new URL(imagePath, base);
  const baseValue = new URL(base);
  if (imageUrlValue.origin !== baseValue.origin ||
      !imageUrlValue.pathname.startsWith(baseValue.pathname)) {
    throw new Error("Manual Studio cover image must stay under the public base URL.");
  }
  const imageUrl = imageUrlValue.toString();
  const documentTitle = manual === null ? "FDAI Manual Studio - Library" : `${title} | FDAI Manual Studio`;
  const tags = [
    '<meta property="og:type" content="website">',
    '<meta property="og:site_name" content="FDAI Manual Studio">',
    '<meta property="og:locale" content="ko_KR">',
    `<meta property="og:title" content="${escapeAttribute(title)}">`,
    `<meta property="og:description" content="${escapeAttribute(description)}">`,
    `<meta property="og:image" content="${escapeAttribute(imageUrl)}">`,
    `<meta property="og:image:alt" content="${escapeAttribute(`${title} 표지`)}">`,
    `<meta property="og:url" content="${escapeAttribute(pageUrl)}">`,
    '<meta name="twitter:card" content="summary_large_image">',
    `<meta name="twitter:title" content="${escapeAttribute(title)}">`,
    `<meta name="twitter:description" content="${escapeAttribute(description)}">`,
    `<meta name="twitter:image" content="${escapeAttribute(imageUrl)}">`,
    `<link rel="canonical" href="${escapeAttribute(pageUrl)}">`,
  ].join("\n    ");

  let rendered = replaceRequired(template, "{{META_DESCRIPTION}}", escapeAttribute(description));
  rendered = replaceRequired(rendered, "{{DOCUMENT_TITLE}}", escapeAttribute(documentTitle));
  rendered = replaceRequired(rendered, "{{SOCIAL_META}}", tags);
  rendered = replaceRequired(rendered, "{{MANUAL_ID}}", escapeAttribute(manual?.id ?? ""));
  return rendered;
}

/** Generate one generic library page and one stable share page per catalog manual. */
export async function generateSharePages({ templatePath, catalogPath, output, baseUrl }) {
  const [template, catalogText] = await Promise.all([
    readFile(templatePath, "utf8"),
    readFile(catalogPath, "utf8"),
  ]);
  const catalog = JSON.parse(catalogText);
  if (!Array.isArray(catalog.manuals) ||
      catalog.manuals.some((manual) => !manualIdPattern.test(manual.id))) {
    throw new Error("Manual Studio catalog contains invalid manual identities.");
  }

  await mkdir(output, { recursive: true });
  const generated = [];
  for (const manualId of [null, ...catalog.manuals.map((manual) => manual.id)]) {
    const filename = manualId === null ? "library.html" : `${manualId}.html`;
    const destination = resolve(output, filename);
    await writeFile(destination, renderLibraryPage(template, catalog, baseUrl, manualId), "utf8");
    generated.push(destination);
  }
  return generated;
}

async function main() {
  const values = process.argv.slice(2);
  const args = {};
  for (let index = 0; index < values.length; index += 2) {
    const option = values[index];
    const value = values[index + 1];
    if (!option?.startsWith("--") || value === undefined) {
      throw new Error("Manual Studio share generator options must be --name value pairs.");
    }
    args[option.slice(2)] = value;
  }
  for (const key of ["template", "catalog", "output", "base-url"]) {
    if (!args[key]) throw new Error(`Missing required option: --${key}`);
  }
  await generateSharePages({
    templatePath: resolve(args.template),
    catalogPath: resolve(args.catalog),
    output: resolve(args.output),
    baseUrl: args["base-url"],
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  await main();
}
