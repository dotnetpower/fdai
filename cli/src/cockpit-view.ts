import { t, type Locale } from "./i18n/index.js";

export type ViewMode = "stream" | "overview" | "focus";

export interface View {
  mode: ViewMode;
  focus?: string;
  paused: boolean;
}

const RESOURCE_KEYWORDS: Array<[RegExp, string]> = [
  [/network|nsg|load.?balancer|public.?ip|\ub124\ud2b8\uc6cc\ud06c/, "network"],
  [/compute|vm|scale.?set|\uac00\uc0c1\uba38\uc2e0|\ucef4\ud4e8\ud2b8/, "compute"],
  [/disk|\ub514\uc2a4\ud06c/, "disk"],
  [/postgres|postgre/, "postgres"],
  [/\bsql\b|database|\ub370\uc774\ud130\ubca0\uc774\uc2a4/, "sql"],
  [/storage|object|\uc2a4\ud1a0\ub9ac\uc9c0|\uc624\ube0c\uc81d\ud2b8/, "object-storage"],
  [/kubernetes|k8s|aks|node.?pool|\ucfe0\ubc84\ub124\ud2f0\uc2a4/, "kubernetes"],
  [/cache|redis|\uce90\uc2dc/, "cache"],
  [/secret|key.?vault|\ube44\ubc00|\uc2dc\ud06c\ub9bf/, "secret"],
  [/log.?workspace|\ub85c\uadf8/, "log-workspace"],
  [/resource.?group|\ub9ac\uc18c\uc2a4\s?\uadf8\ub8f9/, "resource-group"],
];

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
  const normalized = query.toLowerCase().trim();
  if (/\b(pause|freeze|hold)\b|\uba48\ucdb0|\uc815\uc9c0|\uc911\uc9c0|\uc77c\uc2dc\uc815\uc9c0/.test(normalized)) {
    return { patch: { paused: true }, reply: t("cockpit.cmd.paused", locale) };
  }
  if (/\b(resume|continue|unpause|play|live)\b|\uc7ac\uac1c|\uacc4\uc18d|\ub2e4\uc2dc\s?\uc2dc\uc791|\uc774\uc5b4/.test(normalized)) {
    return { patch: { paused: false, mode: "stream" }, reply: t("cockpit.cmd.resumed", locale) };
  }
  if (/\b(overview|dashboard|summary)\b|\ub300\uc2dc\ubcf4\ub4dc|\uc9d1\uacc4|\ud55c\ub208|\uc694\uc57d\s?(\ud654\uba74|\ubcf4\uae30|\ubdf0)/.test(normalized)) {
    return { patch: { mode: "overview", paused: false }, reply: t("cockpit.cmd.overview", locale) };
  }
  if (/\b(stream|feed|logs?)\b|\uc2a4\ud2b8\ub9bc|\ud53c\ub4dc|\ub85c\uadf8|\ud759\ub984|\uc2e4\uc2dc\uac04/.test(normalized)) {
    return {
      patch: { mode: "stream", focus: undefined, paused: false },
      reply: t("cockpit.cmd.streaming", locale),
    };
  }
  if (/\b(clear|reset|all|everything)\b|\uc804\uccb4|\ucd08\uae30\ud654|\ud574\uc81c/.test(normalized)) {
    return {
      patch: { mode: "stream", focus: undefined, paused: false },
      reply: t("cockpit.cmd.cleared", locale),
    };
  }
  const wantsFocus = /focus|only|\ud544\ud130|\uc9d1\uc911|\ub9cc\s?(\ubcf4\uc5ec|\ubd10|\ubcf4\uae30)/.test(normalized);
  if (wantsFocus) {
    for (const [pattern, key] of RESOURCE_KEYWORDS) {
      if (pattern.test(normalized)) {
        return {
          patch: { mode: "focus", focus: key, paused: false },
          reply: t("cockpit.cmd.focusing", locale, { focus: key }),
        };
      }
    }
    return {
      patch: { mode: "stream", focus: undefined, paused: false },
      reply: t("cockpit.cmd.whichResource", locale),
    };
  }
  return null;
}
