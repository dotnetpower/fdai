import { t, type Locale } from "./i18n/index.js";

export type ViewMode = "stream" | "overview" | "focus";

export interface View {
  mode: ViewMode;
  focus?: string;
  paused: boolean;
}

const RESOURCE_TYPES = new Set([
  "network",
  "compute",
  "disk",
  "postgres",
  "sql",
  "object-storage",
  "kubernetes",
  "cache",
  "secret",
  "log-workspace",
  "resource-group",
]);

export function tierLabel(tier: string, locale: Locale): string {
  const key =
    tier === "t0"
      ? "cockpit.tier.t0"
      : tier === "t1"
        ? "cockpit.tier.t1"
        : tier === "t2"
          ? "cockpit.tier.t2"
          : "cockpit.tier.unrouted";
  return t(key, locale);
}

export function viewBadge(view: View, locale: Locale): string {
  if (view.paused) return t("cockpit.badge.paused", locale);
  if (view.mode === "overview") return t("cockpit.badge.overview", locale);
  if (view.mode === "focus")
    return t("cockpit.badge.focus", locale, { focus: (view.focus ?? "").toUpperCase() });
  return t("cockpit.badge.stream", locale);
}

export function parseScreenCommand(
  query: string,
  locale: Locale,
): { patch: Partial<View>; reply: string } | null {
  const [command, argument, ...extra] = query.trim().split(/\s+/);
  if (extra.length > 0 || !command?.startsWith("/")) return null;
  if (command === "/pause" && argument === undefined) {
    return { patch: { paused: true }, reply: t("cockpit.cmd.paused", locale) };
  }
  if (command === "/resume" && argument === undefined) {
    return { patch: { paused: false, mode: "stream" }, reply: t("cockpit.cmd.resumed", locale) };
  }
  if (command === "/overview" && argument === undefined) {
    return { patch: { mode: "overview", paused: false }, reply: t("cockpit.cmd.overview", locale) };
  }
  if (command === "/stream" && argument === undefined) {
    return {
      patch: { mode: "stream", focus: undefined, paused: false },
      reply: t("cockpit.cmd.streaming", locale),
    };
  }
  if (command === "/clear" && argument === undefined) {
    return {
      patch: { mode: "stream", focus: undefined, paused: false },
      reply: t("cockpit.cmd.cleared", locale),
    };
  }
  if (command === "/focus") {
    if (argument !== undefined && RESOURCE_TYPES.has(argument)) {
      return {
        patch: { mode: "focus", focus: argument, paused: false },
        reply: t("cockpit.cmd.focusing", locale, { focus: argument }),
      };
    }
    return {
      patch: { mode: "stream", focus: undefined, paused: false },
      reply: t("cockpit.cmd.whichResource", locale),
    };
  }
  return null;
}
