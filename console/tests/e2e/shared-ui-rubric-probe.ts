/**
 * Shared UI/UX Rubric & Functional Probe across all 63 registered Console routes.
 *
 * Implements automated DOM geometry, overflow, clipping, accessible-name,
 * nested-interactive, and Calm Slate edge-restraint checks mapped to
 * docs/reference/ui-ux-quality-rubric.md (UX-01 through UX-50).
 */
import { expect, type Page } from "@playwright/test";

export const ALL_CONSOLE_ROUTES = [
  "/overview",
  "/resource-dashboard",
  "/live",
  "/gpu-monitoring",
  "/incidents",
  "/agents",
  "/approvals",
  "/provisioning",
  "/onboarding",
  "/detection-coverage",
  "/alert-quality",
  "/configuration-baselines",
  "/processes",
  "/workflow-apps",
  "/scheduler-runs",
  "/background-tasks",
  "/automation-blueprints",
  "/scheduled-continuations",
  "/conversation-delivery",
  "/conversation-assurance",
  "/audit",
  "/browser-evidence",
  "/forecast-learning",
  "/assurance-twin",
  "/code-security",
  "/conversation-search",
  "/reports",
  "/trace",
  "/root-cause-analysis",
  "/architecture",
  "/ontology",
  "/pantheon",
  "/agent-activity",
  "/agent-oversight",
  "/rules",
  "/workflow-builder",
  "/capabilities",
  "/skills",
  "/knowledge",
  "/documents",
  "/github",
  "/gitlab",
  "/azure-devops",
  "/blast-radius",
  "/promotion-gates",
  "/context-selection-comparisons",
  "/scope",
  "/operating-outcomes",
  "/control-assurance",
  "/verticals",
  "/trust-routing",
  "/llm-cost",
  "/aks-commerce",
  "/cost-governance",
  "/settings/general",
  "/settings/environment-and-deployment",
  "/settings/models",
  "/settings/runtime-policies",
  "/settings/memory",
  "/settings/iam",
  "/settings/integrations",
  "/settings/diagnostics",
  "/labs",
] as const;

export const SAMPLE_ENABLED_ROUTES = [
  "/overview",
  "/live",
  "/gpu-monitoring",
  "/incidents",
  "/audit",
  "/trace",
  "/root-cause-analysis",
  "/approvals",
  "/provisioning",
  "/onboarding",
  "/detection-coverage",
  "/configuration-baselines",
  "/processes",
  "/workflow-apps",
  "/scheduler-runs",
  "/background-tasks",
  "/automation-blueprints",
  "/scheduled-continuations",
  "/conversation-delivery",
  "/operating-outcomes",
  "/control-assurance",
  "/verticals",
  "/trust-routing",
  "/llm-cost",
  "/cost-governance",
  "/aks-commerce",
] as const;

export interface RouteRubricMeasurement {
  readonly route: string;
  readonly locale: "en" | "ko";
  readonly dataMode: "live" | "sample";
  readonly viewport: { readonly width: number; readonly height: number };
  readonly headingText: string;
  readonly documentOverflowPx: number;
  readonly mainOverflowPx: number;
  readonly unlabeledControls: readonly string[];
  readonly nestedInteractiveControls: readonly string[];
  readonly coloredEdgeContainers: readonly string[];
  readonly clippedControls: readonly string[];
  readonly lowContrastElements: readonly string[];
  readonly unexpectedErrorBlocks: number;
}

export async function waitForRouteSettled(page: Page, routePath: string): Promise<void> {
  const root = routePath.includes("/settings/")
    ? page.locator(".settings-overlay-content")
    : page.locator("main");
  await expect(root).toBeVisible({ timeout: 10_000 });
  await expect(root.locator("[aria-busy='true']")).toHaveCount(0, { timeout: 10_000 });
  await expect(root.locator("h1, h2").first()).toBeVisible({ timeout: 10_000 });
}

export async function measureRouteRubric(
  page: Page,
  routePath: string,
  locale: "en" | "ko",
  dataMode: "live" | "sample",
): Promise<RouteRubricMeasurement> {
  await waitForRouteSettled(page, routePath);
  return await page.evaluate(
    ({ route, loc, mode }) => {
      const isSettings = route.includes("/settings/");
      const root = (
        isSettings
          ? document.querySelector(".settings-overlay-content")
          : document.querySelector("main")
      ) as HTMLElement | null;

      const heading = root?.querySelector("h1, h2");
      const headingText = (heading?.textContent ?? "").trim();

      const documentOverflowPx = Math.max(
        0,
        document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      const mainOverflowPx = root
        ? Math.max(0, root.scrollWidth - root.clientWidth)
        : 0;

      const visible = (el: Element): el is HTMLElement => {
        if (!(el instanceof HTMLElement)) return false;
        if (!el.checkVisibility()) return false;
        if (el.closest('.sr-only,[aria-hidden="true"],[hidden]')) return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      };

      const accessibleName = (el: HTMLElement): string => {
        const ariaLabel = el.getAttribute("aria-label")?.trim();
        if (ariaLabel) return ariaLabel;
        const labelledBy = el.getAttribute("aria-labelledby")?.trim();
        if (labelledBy) {
          const text = labelledBy
            .split(/\s+/)
            .map((id) => document.getElementById(id)?.textContent?.trim() ?? "")
            .join(" ")
            .trim();
          if (text) return text;
        }
        if (
          el instanceof HTMLInputElement ||
          el instanceof HTMLSelectElement ||
          el instanceof HTMLTextAreaElement
        ) {
          if (el.labels && el.labels.length > 0) {
            const labelText = [...el.labels]
              .map((l) => l.textContent?.trim() ?? "")
              .join(" ")
              .trim();
            if (labelText) return labelText;
          }
          const wrappingLabel = el.closest("label")?.textContent?.trim();
          if (wrappingLabel) return wrappingLabel;
        }
        const titleAttr = el.getAttribute("title")?.trim();
        if (titleAttr) return titleAttr;
        return (el.textContent ?? "").trim();
      };

      const scopeRoot = root ?? document.body;
      const controls = [
        ...scopeRoot.querySelectorAll("button, a[href], input, select, textarea"),
      ].filter(visible);

      const unlabeledControls: string[] = [];
      const clippedControls: string[] = [];
      for (const ctrl of controls) {
        if (ctrl instanceof HTMLInputElement && ctrl.type === "hidden") continue;
        const name = accessibleName(ctrl);
        if (!name) {
          unlabeledControls.push(
            `${ctrl.tagName.toLowerCase()}${ctrl.id ? `#${ctrl.id}` : ""}${
              ctrl.className ? `.${String(ctrl.className).trim().split(/\s+/).join(".")}` : ""
            }`,
          );
        }
        if (
          (ctrl instanceof HTMLButtonElement || ctrl instanceof HTMLInputElement) &&
          ctrl.clientHeight > 0
        ) {
          const style = getComputedStyle(ctrl);
          if (style.whiteSpace === "nowrap") {
            const lineHeight = parseFloat(style.lineHeight);
            const padY = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
            if (
              Number.isFinite(lineHeight) &&
              ctrl.clientHeight + 2 < lineHeight + padY &&
              ctrl.scrollHeight > ctrl.clientHeight + 2
            ) {
              clippedControls.push(
                `${ctrl.tagName.toLowerCase()}:${name.slice(0, 32)}`,
              );
            }
          }
        }
      }

      const nestedInteractiveControls = [
        ...scopeRoot.querySelectorAll("a[href] button, button a[href], button button, a[href] a[href]"),
      ]
        .filter(visible)
        .map((el) => `${el.tagName.toLowerCase()}:${(el.textContent ?? "").trim().slice(0, 32)}`);

      const coloredEdgeContainers = [
        ...scopeRoot.querySelectorAll(".card, .panel, .callout, .state-block"),
      ]
        .filter(visible)
        .filter((el) => {
          const s = getComputedStyle(el);
          const topW = parseFloat(s.borderTopWidth);
          const leftW = parseFloat(s.borderLeftWidth);
          const rightW = parseFloat(s.borderRightWidth);
          const bottomW = parseFloat(s.borderBottomWidth);
          const thickTop = topW > 2 && topW > bottomW + 1 && s.borderTopColor !== s.borderBottomColor;
          const thickLeft = leftW > 2 && leftW > rightW + 1 && s.borderLeftColor !== s.borderRightColor;
          return thickTop || thickLeft;
        })
        .map((el) => `${el.tagName.toLowerCase()}.${String(el.className).trim().split(/\s+/).join(".")}`);

      const unexpectedErrorBlocks = scopeRoot.querySelectorAll(
        ".empty.error, .panel-error-boundary, .state-block.state-error",
      ).length;

      const canvas = document.createElement("canvas");
      canvas.width = 1;
      canvas.height = 1;
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      const colorCache = new Map<string, number[] | null>();

      const parseRgba = (value: string): number[] | null => {
        if (!value || value === "transparent" || value === "rgba(0, 0, 0, 0)") {
          return [0, 0, 0, 0];
        }
        const cached = colorCache.get(value);
        if (cached !== undefined) return cached;
        if (value.startsWith("rgb")) {
          const matches = value.match(/[\d.]+/g);
          if (!matches || matches.length < 3) {
            colorCache.set(value, null);
            return null;
          }
          const nums = matches.map(Number);
          const res = [nums[0]!, nums[1]!, nums[2]!, nums[3] ?? 1];
          colorCache.set(value, res);
          return res;
        }
        if (!ctx) return null;
        ctx.clearRect(0, 0, 1, 1);
        ctx.fillStyle = value;
        ctx.fillRect(0, 0, 1, 1);
        const data = ctx.getImageData(0, 0, 1, 1).data;
        const res = [data[0]!, data[1]!, data[2]!, data[3]! / 255];
        colorCache.set(value, res);
        return res;
      };
      const composite = (fg: number[], bg: number[]): number[] => {
        const alpha = fg[3] ?? 1;
        return [0, 1, 2].map((i) => fg[i]! * alpha + bg[i]! * (1 - alpha));
      };
      const effectiveBg = (el: Element | null): number[] => {
        const chain: Element[] = [];
        for (let cur = el; cur; cur = cur.parentElement) chain.unshift(cur);
        return chain.reduce((base, cur) => {
          const parsed = parseRgba(getComputedStyle(cur).backgroundColor);
          return parsed ? composite(parsed, base) : base;
        }, [255, 255, 255]);
      };
      const luminance = (rgb: number[]): number => {
        const [r, g, b] = rgb.map((c) => {
          const s = c / 255;
          return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
        });
        return r! * 0.2126 + g! * 0.7152 + b! * 0.0722;
      };
      const contrastRatio = (fg: number[], bg: number[]): number => {
        const l1 = luminance(composite(fg, bg));
        const l2 = luminance(bg);
        return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      };

      const lowContrastElements: string[] = [];
      const textCandidates = [
        ...scopeRoot.querySelectorAll("h1, h2, h3, h4, button, label, th"),
      ].filter(visible);
      for (const el of textCandidates) {
        if (el.matches(":disabled,[aria-disabled='true']")) continue;
        const text = (el.textContent ?? "").trim();
        if (!text) continue;
        const style = getComputedStyle(el);
        const fg = parseRgba(style.color);
        if (!fg) continue;
        const bg = effectiveBg(el);
        const ratio = contrastRatio(fg, bg);
        const fontSize = parseFloat(style.fontSize);
        const fontWeight = Number(style.fontWeight) || 400;
        const minRatio =
          fontSize >= 24 || (fontSize >= 18.5 && fontWeight >= 600) ? 3.0 : 4.5;
        if (ratio + 0.05 < minRatio) {
          lowContrastElements.push(
            `${el.tagName.toLowerCase()}(${ratio.toFixed(2)}<${minRatio}):${text.slice(0, 28)}`,
          );
        }
      }

      return {
        route,
        locale: loc,
        dataMode: mode,
        viewport: { width: window.innerWidth, height: window.innerHeight },
        headingText,
        documentOverflowPx,
        mainOverflowPx,
        unlabeledControls,
        nestedInteractiveControls,
        coloredEdgeContainers,
        clippedControls,
        lowContrastElements,
        unexpectedErrorBlocks,
      };
    },
    { route: routePath, loc: locale, mode: dataMode },
  );
}
