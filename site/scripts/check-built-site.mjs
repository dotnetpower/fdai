#!/usr/bin/env node
import { readdir, readFile, stat } from "node:fs/promises";
import { posix, resolve } from "node:path";
import process from "node:process";
import { parse } from "parse5";

const siteRoot = resolve(import.meta.dirname, "..");
const distRoot = resolve(siteRoot, "dist");
const manifestPath = resolve(siteRoot, "src", "data", "publication-routes.json");
const basePath = `/${(process.env.BASE_PATH ?? "/fdai").replace(/^\/+|\/+$/gu, "")}`;
const origin = "https://fdai.invalid";

async function filesUnder(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const absolute = resolve(directory, entry.name);
    return entry.isDirectory() ? filesUnder(absolute) : [absolute];
  }));
  return nested.flat();
}

function walk(node, visit) {
  visit(node);
  for (const child of node.childNodes ?? []) walk(child, visit);
  if (node.content) walk(node.content, visit);
}

function attribute(node, name) {
  return node.attrs?.find((item) => item.name === name)?.value;
}

function accessibleText(node) {
  const explicit = attribute(node, "aria-label");
  if (explicit?.trim()) return explicit.trim();
  if (node.tagName === "img") return attribute(node, "alt")?.trim() ?? "";
  if (node.nodeName === "#text") return node.value ?? "";
  const content = [
    ...(node.childNodes ?? []),
    ...(node.content ? [node.content] : []),
  ].map(accessibleText).join(" ").replace(/\s+/gu, " ").trim();
  return content || attribute(node, "title")?.trim() || "";
}

function routeForHtml(relativePath) {
  const normalized = relativePath.replaceAll("\\", "/");
  if (normalized === "index.html") return "/";
  if (normalized.endsWith("/index.html")) return `/${normalized.slice(0, -"index.html".length)}`;
  return `/${normalized}`;
}

async function existingTarget(pathname) {
  const relativePath = decodeURI(pathname.slice(basePath.length)).replace(/^\//u, "");
  const candidates = relativePath.endsWith("/")
    ? [`${relativePath}index.html`]
    : posix.extname(relativePath)
      ? [relativePath]
      : [relativePath, `${relativePath}.html`, `${relativePath}/index.html`];
  for (const candidate of candidates) {
    const target = resolve(distRoot, candidate || "index.html");
    const info = await stat(target).catch(() => null);
    if (info?.isFile()) return target;
  }
  return null;
}

function pageUrl(route) {
  return new URL(`${basePath}${route}`, `${origin}/`);
}

function graphReachable(graph, start) {
  const seen = new Set([start]);
  const pending = [start];
  while (pending.length) {
    const route = pending.shift();
    for (const next of graph.get(route) ?? []) {
      if (seen.has(next)) continue;
      seen.add(next);
      pending.push(next);
    }
  }
  return seen;
}

async function main() {
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  const manifestRoutes = new Map(manifest.map((record) => [record.route, record]));
  const htmlFiles = (await filesUnder(distRoot)).filter((file) => file.endsWith(".html"));
  const pages = new Map();
  const errors = [];
  let diagramCount = 0;
  let mermaidCount = 0;

  for (const file of htmlFiles) {
    const relativePath = posix.relative(distRoot, file);
    const route = routeForHtml(relativePath);
    const document = parse(await readFile(file, "utf8"), { sourceCodeLocationInfo: true });
    const ids = new Set();
    const references = [];
    const accessibility = [];
    let h1Count = 0;
    walk(document, (node) => {
      if (!node.tagName) return;
      const id = attribute(node, "id") ?? (node.tagName === "a" ? attribute(node, "name") : null);
      if (id && ids.has(id)) accessibility.push(`duplicate id '${id}'`);
      if (id) ids.add(id);
      if (node.tagName === "h1") h1Count += 1;
      if (node.tagName === "html" && !attribute(node, "lang")?.trim()) accessibility.push("html element has no lang");
      if (node.tagName === "img" && attribute(node, "alt") === undefined) accessibility.push("image has no alt attribute");
      if (["a", "button"].includes(node.tagName) && !accessibleText(node)) {
        accessibility.push(`${node.tagName} has no accessible name`);
      }
      if (node.tagName === "fdai-architecture-diagram") diagramCount += 1;
      if (node.tagName === "pre" && (attribute(node, "class") ?? "").split(/\s+/u).includes("mermaid")) {
        mermaidCount += 1;
      }
      for (const name of node.tagName === "a" ? ["href"] : ["src"]) {
        const value = attribute(node, name);
        if (value) references.push({ name, value });
      }
    });
    pages.set(route, { file, ids, references, h1Count, accessibility });
  }

  for (const [route, page] of pages) {
    const record = manifestRoutes.get(route);
    if (!record) errors.push(`${route}: generated HTML route has no publication record`);
    if (record?.publication_state !== "fallback" && page.h1Count !== 1) {
      errors.push(`${route}: expected one H1, found ${page.h1Count}`);
    }
    page.accessibility.forEach((finding) => errors.push(`${route}: ${finding}`));
  }
  for (const route of manifestRoutes.keys()) {
    if (!pages.has(route)) errors.push(`${route}: publication record has no generated HTML route`);
  }

  const graph = new Map([...pages.keys()].map((route) => [route, new Set()]));
  for (const [route, page] of pages) {
    for (const reference of page.references) {
      if (/^(?:data:|mailto:|tel:|javascript:)/iu.test(reference.value)) continue;
      const target = new URL(reference.value, pageUrl(route));
      if (target.origin !== origin) continue;
      if (target.pathname !== basePath && !target.pathname.startsWith(`${basePath}/`)) {
        errors.push(`${route}: internal ${reference.name} escapes base path: ${reference.value}`);
        continue;
      }
      const targetFile = await existingTarget(target.pathname);
      if (!targetFile) {
        errors.push(`${route}: missing internal target ${reference.value}`);
        continue;
      }
      if (reference.name !== "href" || !targetFile.endsWith(".html")) continue;
      const targetRoute = routeForHtml(posix.relative(distRoot, targetFile));
      graph.get(route)?.add(targetRoute);
      if (target.hash && !pages.get(targetRoute)?.ids.has(decodeURIComponent(target.hash.slice(1)))) {
        errors.push(`${route}: missing anchor ${reference.value}`);
      }
    }
  }

  const reachable = {
    en: graphReachable(graph, "/"),
    ko: graphReachable(graph, "/ko/"),
  };
  for (const record of manifest) {
    if (record.publication_state !== "navigated") continue;
    if (!reachable[record.locale].has(record.route)) {
      errors.push(`${record.route}: navigated ${record.locale} route is unreachable from its locale home`);
    }
  }
  if (mermaidCount) errors.push(`built site contains ${mermaidCount} Mermaid runtime container(s)`);

  if (errors.length) {
    errors.forEach((error) => console.error(`check-built-site: ${error}`));
    throw new Error(`built-site validation failed with ${errors.length} finding(s)`);
  }
  console.log(
    `check-built-site: OK (${pages.size} routes, ${manifest.length} publication records, ${diagramCount} FDAI diagram embeds, 0 Mermaid containers)`,
  );
}

main().catch((error) => {
  console.error(`check-built-site: ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
});
