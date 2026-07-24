import { t, type Locale } from "./i18n/index.js";

export type ViewMode = "stream" | "overview" | "focus";

export interface View {
  mode: ViewMode;
  focus?: string;
  paused: boolean;
}

const RESOURCE_KEYWORDS: Array<[RegExp, string]> = [
  [/network|nsg|load.?balancer|public.?ip|네트워크/, "network"],
  [/compute|vm|scale.?set|가상머신|컴퓨트/, "compute"],
  [/disk|디스크/, "disk"],
  [/postgres|postgre/, "postgres"],
  [/\bsql\b|database|데이터베이스/, "sql"],
  [/storage|object|스토리지|오브젝트/, "object-storage"],
  [/kubernetes|k8s|aks|node.?pool|쿠버네티스/, "kubernetes"],
  [/cache|redis|캐시/, "cache"],
  [/secret|key.?vault|비밀|시크릿/, "secret"],
  [/log.?workspace|로그/, "log-workspace"],
  [/resource.?group|리소스\s?그룹/, "resource-group"],
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
  if (/\b(pause|freeze|hold)\b|멈춰|정지|중지|일시정지/.test(normalized)) {
    return { patch: { paused: true }, reply: t("cockpit.cmd.paused", locale) };
  }
  if (/\b(resume|continue|unpause|play|live)\b|재개|계속|다시\s?시작|이어/.test(normalized)) {
    return { patch: { paused: false, mode: "stream" }, reply: t("cockpit.cmd.resumed", locale) };
  }
  if (/\b(overview|dashboard|summary)\b|대시보드|집계|한눈|요약\s?(화면|보기|뷰)/.test(normalized)) {
    return { patch: { mode: "overview", paused: false }, reply: t("cockpit.cmd.overview", locale) };
  }
  if (/\b(stream|feed|logs?)\b|스트림|피드|로그|흙름|실시간/.test(normalized)) {
    return {
      patch: { mode: "stream", focus: undefined, paused: false },
      reply: t("cockpit.cmd.streaming", locale),
    };
  }
  if (/\b(clear|reset|all|everything)\b|전체|초기화|해제/.test(normalized)) {
    return {
      patch: { mode: "stream", focus: undefined, paused: false },
      reply: t("cockpit.cmd.cleared", locale),
    };
  }
  const wantsFocus = /focus|only|필터|집중|만\s?(보여|봐|보기)/.test(normalized);
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
