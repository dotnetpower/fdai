import { posix } from "node:path";

function bareName(relPath) {
  const filename = posix.basename(relPath);
  return filename.endsWith("-ko.md")
    ? filename.slice(0, -"-ko.md".length)
    : filename.slice(0, -".md".length);
}

export function publicationRoute(prefix, relPath) {
  const normalized = relPath.replaceAll("\\", "/");
  const directory = posix.dirname(normalized) === "." ? [] : posix.dirname(normalized).split("/");
  const suffix = bareName(normalized) === "README" ? directory : [...directory, bareName(normalized)];
  const route = `/${[...prefix, ...suffix].join("/")}/`.replaceAll(/\/{2,}/gu, "/");
  return route;
}

function navigationSection(sourceKind, relPath) {
  const normalized = relPath.replaceAll("\\", "/");
  if (sourceKind === "roadmap") return "Reference";
  if (sourceKind === "runbook") return "Operate";
  if (normalized.startsWith("deck/") || normalized === "diagram-gallery.md") return "Reference";
  if (normalized.startsWith("sre/")) return "SRE";
  if (normalized.startsWith("concepts/")) return "Understand";
  if (["get-started.md", "architecture.md", "deploy-quickstart.md"].includes(normalized)) {
    return "Get started";
  }
  return "Operate";
}

function publicationState(sourceKind, relPath) {
  const normalized = relPath.replaceAll("\\", "/");
  if (sourceKind === "roadmap" && bareName(normalized) === "README" && normalized !== "README.md") {
    return "search-only";
  }
  if (sourceKind === "user-guide" && normalized.startsWith("deck/") && bareName(normalized) !== "README") {
    return "search-only";
  }
  return "navigated";
}

function frontmatter(content) {
  if (!content.startsWith("---\n")) return "";
  const end = content.indexOf("\n---\n", 4);
  return end === -1 ? "" : content.slice(4, end);
}

function derivedSources(content) {
  return [...frontmatter(content).matchAll(/^\s*-\s+source:\s+([^\s#]+)\s*$/gmu)]
    .map((match) => match[1])
    .filter(Boolean);
}

function diagramIds(content) {
  return [...content.matchAll(/diagrams\/generated\/([a-z0-9-]+)\.(?:en|ko)\.svg/gu)]
    .map((match) => match[1])
    .filter(Boolean);
}

export function publicationRecord({ sourcePath, sourceKind, enPrefix, koPrefix, relPath, content }) {
  const locale = relPath.endsWith("-ko.md") ? "ko" : "en";
  return {
    route: publicationRoute(locale === "ko" ? koPrefix : enPrefix, relPath),
    locale,
    source_path: sourcePath.replaceAll("\\", "/"),
    source_kind: sourceKind,
    navigation_section: navigationSection(sourceKind, relPath),
    audience: sourceKind === "roadmap" ? "operator-and-contributor" : "operator",
    publication_state: publicationState(sourceKind, relPath),
    derived_sources: [...new Set(derivedSources(content))].sort(),
    diagram_ids: [...new Set(diagramIds(content))].sort(),
  };
}

export const SITE_OWNED_ROUTES = [
  {
    route: "/",
    locale: "en",
    source_path: "site/src/content/docs/index.mdx",
    source_kind: "site",
    navigation_section: "Get started",
    audience: "operator",
    publication_state: "navigated",
    derived_sources: [],
    diagram_ids: [],
  },
  {
    route: "/ko/",
    locale: "ko",
    source_path: "site/src/content/docs/ko/index.mdx",
    source_kind: "site",
    navigation_section: "Get started",
    audience: "operator",
    publication_state: "navigated",
    derived_sources: [],
    diagram_ids: [],
  },
  ...["en", "ko"].map((locale) => ({
    route: locale === "en" ? "/404.html" : "/ko/404/",
    locale,
    source_path: locale === "en" ? "@astrojs/starlight/404" : "site/src/pages/ko/404.astro",
    source_kind: "site",
    navigation_section: "Fallback",
    audience: "operator",
    publication_state: "fallback",
    derived_sources: [],
    diagram_ids: [],
  })),
];
