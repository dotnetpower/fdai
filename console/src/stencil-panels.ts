import type { ConsolePanel, PanelGroup, PanelGroupMeta } from "./panels";

export const LOCKED_STENCIL_PANEL_IDS: readonly string[] = [
  "dashboard",
  "audit",
  "settings-general",
];

const PANEL_ID_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/**
 * Parse a comma-separated list of Stencil-enabled panel IDs.
 * Returns `null` when no Stencil filter is active (full build default).
 * Always unions in `LOCKED_STENCIL_PANEL_IDS` so safety-core surfaces cannot be stripped.
 */
export function parseStencilEnabledPanelIds(
  raw: string | undefined | null,
): ReadonlySet<string> | null {
  if (raw === undefined || raw === null || raw.trim() === "") {
    return null;
  }
  const parsed = new Set<string>(LOCKED_STENCIL_PANEL_IDS);
  for (const token of raw.split(",")) {
    const id = token.trim();
    if (!id) continue;
    if (!PANEL_ID_PATTERN.test(id)) {
      throw new Error(`Invalid Stencil panel id: ${id}`);
    }
    parsed.add(id);
  }
  return parsed;
}

export function activeStencilPanelIds(): ReadonlySet<string> | null {
  const raw = (import.meta.env as Record<string, string | undefined>).VITE_STENCIL_ENABLED_PANELS;
  return parseStencilEnabledPanelIds(raw);
}

export function filterPanelsByStencil<T extends Pick<ConsolePanel, "id">>(
  panels: readonly T[],
  enabledIds: ReadonlySet<string> | null = activeStencilPanelIds(),
): readonly T[] {
  if (enabledIds === null) return panels;
  return panels.filter(
    (panel) => enabledIds.has(panel.id) || LOCKED_STENCIL_PANEL_IDS.includes(panel.id),
  );
}

export function filterNavigationGroupsByStencil(
  groups: readonly PanelGroupMeta[],
  panels: readonly Pick<ConsolePanel, "id" | "group" | "hiddenFromNavigation">[],
  enabledIds: ReadonlySet<string> | null = activeStencilPanelIds(),
): readonly PanelGroupMeta[] {
  if (enabledIds === null) return groups;
  const filteredPanels = filterPanelsByStencil(panels, enabledIds);
  const groupsWithVisiblePanels = new Set<PanelGroup>(["overview", "settings"]);
  for (const panel of filteredPanels) {
    if (!panel.hiddenFromNavigation) {
      groupsWithVisiblePanels.add(panel.group);
    }
  }
  return groups.filter((group) => groupsWithVisiblePanels.has(group.id));
}

/**
 * Transform `console/src/panels.tsx` source at build time when a Stencil panel allowlist is active.
 * Removes disabled panel entries from `CORE_PANELS` and prunes unused lazy route declarations so
 * excluded routes are physically absent from the built JavaScript and CSS chunks (#2526).
 */
export function transformPanelsSourceForStencil(
  source: string,
  enabledIds: ReadonlySet<string> | null,
): string {
  if (enabledIds === null) return source;

  const coreStart = source.indexOf("export const CORE_PANELS: readonly ConsolePanel[] = [");
  if (coreStart < 0) return source;
  const assignOpen = source.indexOf("= [", coreStart);
  if (assignOpen < 0) return source;
  const arrayOpen = assignOpen + 2;
  const coreEnd = source.indexOf("\n];", arrayOpen);
  if (coreEnd < 0) return source;

  const beforeCore = source.slice(0, arrayOpen + 1);
  const coreBody = source.slice(arrayOpen + 1, coreEnd);
  const afterCore = source.slice(coreEnd);

  // Parse top-level entries inside CORE_PANELS (object literals, DASHBOARD_PANEL, or knowledgeSourcePanel(...)).
  const keptEntries: string[] = [];
  let index = 0;
  while (index < coreBody.length) {
    const ch = coreBody[index]!;
    if (/\s|,/.test(ch)) {
      index += 1;
      continue;
    }
    if (coreBody.startsWith("//", index)) {
      const lineEnd = coreBody.indexOf("\n", index);
      index = lineEnd < 0 ? coreBody.length : lineEnd + 1;
      continue;
    }
    if (ch === "{") {
      let depth = 0;
      let cursor = index;
      while (cursor < coreBody.length) {
        const current = coreBody[cursor]!;
        if (current === "{") depth += 1;
        else if (current === "}") {
          depth -= 1;
          if (depth === 0) {
            cursor += 1;
            break;
          }
        }
        cursor += 1;
      }
      const block = coreBody.slice(index, cursor);
      const idMatch = /\bid:\s*"([a-z0-9-]+)"/.exec(block);
      const panelId = idMatch?.[1];
      if (!panelId || enabledIds.has(panelId) || LOCKED_STENCIL_PANEL_IDS.includes(panelId)) {
        keptEntries.push(block);
      }
      index = cursor;
      continue;
    }
    if (coreBody.startsWith("DASHBOARD_PANEL", index)) {
      keptEntries.push("DASHBOARD_PANEL");
      index += "DASHBOARD_PANEL".length;
      continue;
    }
    if (coreBody.startsWith("knowledgeSourcePanel(", index)) {
      const closeParen = coreBody.indexOf(")", index);
      if (closeParen < 0) break;
      const callExpr = coreBody.slice(index, closeParen + 1);
      const idMatch = /knowledgeSourcePanel\(\s*"([a-z0-9-]+)"/.exec(callExpr);
      const panelId = idMatch?.[1];
      if (!panelId || enabledIds.has(panelId)) {
        keptEntries.push(callExpr);
      }
      index = closeParen + 1;
      continue;
    }
    index += 1;
  }

  const rebuiltCore = `\n  ${keptEntries.join(",\n  ")},\n`;
  let transformed = beforeCore + rebuiltCore + afterCore;

  // Prune lazy route declarations (`const XRoute = lazyRoute(...)` / `lazy(...)`) not referenced in rebuiltCore.
  const routeDeclPattern =
    /const\s+([A-Za-z0-9_]+Route)\s*=\s*(?:lazyRoute|lazy)\([\s\S]*?\);\n/g;
  const bodyAfterDecls = rebuiltCore + afterCore;
  transformed = transformed.replace(routeDeclPattern, (fullMatch, routeVar: string) => {
    if (routeVar === "DashboardRoute") return fullMatch;
    const refRegex = new RegExp(`\\b${routeVar}\\b`);
    return refRegex.test(bodyAfterDecls) ? fullMatch : "";
  });

  // Prune shared loader helpers (`loadAnalyticsHubs`, `loadSettingsSystem`) if no longer referenced.
  for (const helperName of ["loadAnalyticsHubs", "loadSettingsSystem"]) {
    const helperPattern = new RegExp(
      `const\\s+${helperName}\\s*=\\s*\\(\\)\\s*=>\\s*import\\([^)]+\\);\\n`,
    );
    const remainingRefs = transformed
      .replace(helperPattern, "")
      .match(new RegExp(`\\b${helperName}\\b`, "g"));
    if (!remainingRefs || remainingRefs.length === 0) {
      transformed = transformed.replace(helperPattern, "");
    }
  }

  // Round C09 hardening: prune `alertQualityNavText` import when `alert-quality` is excluded.
  if (!/\balertQualityNavText\b/.test(rebuiltCore + afterCore)) {
    transformed = transformed.replace(
      /import\s*\{\s*alertQualityNavText\s*\}\s*from\s*"\.\/routes\/i18n\/alert-quality-nav";\n/,
      "",
    );
  }

  return transformed;
}
